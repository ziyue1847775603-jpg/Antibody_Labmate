"""Phase D3: ColabFold container worker adapter.

This module translates ColabFold prediction requests into
``docker compose run`` commands targeting the isolated ColabFold GPU
container.  It does NOT replace the existing host-executable path; it
provides an alternative backend that communicates solely through fixed
CLI arguments, exit codes, and regular file artifacts on shared volumes.

The container communicates with Labmate only through:
- command-line arguments (list form, no shell string interpolation)
- exit codes
- stdout/stderr captured from the container process
- regular PDB and JSON files written to /work/output via a shared volume

Security invariants:
- No docker socket is exposed to any public web container.
- No GPU is granted to the LightDock worker; only the ColabFold service
  requests GPU resources (in the compose file).
- The entrypoint in the container enforces a subcommand whitelist and
  fixes all scientific parameters.
- No eval, shell, or arbitrary command execution.
- The compose file uses ``${VAR:?}`` syntax -- unset variable = fail.
- Host absolute paths are redacted from captured logs.
- Nonzero exit code -> LabmateError (fail closed).
- GPU invisibility, missing weights, missing rank-1 PDB all fail closed.
"""

from __future__ import annotations

import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any

from labmate.backends.base import (
    PREDICTION_AMINO_ACIDS,
    PredictionResult,
    normalize_prediction_sequence,
)
from labmate.errors import InputValidationError, LabmateError

_DEFAULT_COMPOSE_FILE = "docker-compose.live-local.yml"
_DEFAULT_SERVICE = "colabfold"
_DEFAULT_DOCKER_BIN = "docker"
_MAX_TIMEOUT = 7200  # ColabFold GPU inference can take a while

# Bounds
_MAX_FASTA_BYTES = 20_000

# Regex patterns
_BASENAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_RANK_ONE_PDB = re.compile(r"_rank_001_.*\.pdb$")
_ABSOLUTE_RE = re.compile(r"(?:[A-Za-z]:[\\/]|/(?:mnt|root|home|tmp)/)")
_TOKEN_RE = re.compile(
    r"(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16})"
)
_SAFE_SERVICE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_SAFE_DOCKER_BIN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

# Fixed scientific parameters — must match the host backend exactly.
FIXED_COLABFOLD_ARGS: list[str] = [
    "--msa-mode", "single_sequence",
    "--data", "/models/colabfold",
    "--model-type", "alphafold2_multimer_v3",
    "--num-models", "1",
    "--num-recycle", "1",
    "--num-relax", "0",
    "--random-seed", "0",
    "--disable-unified-memory",
    "--compile-mode", "fast",
]

# Expected multimer_v3 parameter files
_MULTIMER_V3_FILES = [
    f"params_model_{i}_multimer_v3.npz" for i in range(1, 6)
]


# ------------------------------------------------------------------
# Validation helpers
# ------------------------------------------------------------------

def _safe_basename(name: str, label: str) -> str:
    if not _BASENAME_RE.fullmatch(name):
        raise InputValidationError(
            f"{label} must be a single safe basename, got: {name!r}"
        )
    return name


def _validate_under_root(path: Path, root: Path, label: str) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise InputValidationError(
            f"{label} 路径越界: {resolved}"
        ) from exc
    return resolved


def _redact(text: str, roots: list[Path]) -> str:
    redacted = text
    for root in roots:
        for variant in (
            str(root.resolve()),
            str(root.resolve()).replace("\\", "/"),
        ):
            if len(variant) >= 4:
                redacted = redacted.replace(variant, "<local-path>")
    redacted = _ABSOLUTE_RE.sub("<local-path>", redacted)
    redacted = _TOKEN_RE.sub("<token-redacted>", redacted)
    return redacted


def _validate_fasta_content(text: str) -> dict[str, str]:
    """Validate a VH:VL FASTA payload.

    Returns ``{"VH": ..., "VL": ...}`` with normalized sequences.
    """
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        raise InputValidationError("FASTA is empty")
    if not lines[0].startswith(">"):
        raise InputValidationError("FASTA must start with a header line")
    if len(lines) < 2:
        raise InputValidationError("FASTA has no sequence lines")
    # Exactly one record: only one header allowed
    if any(ln.startswith(">") for ln in lines[1:]):
        raise InputValidationError("FASTA must contain exactly one record")
    sequence = "".join(lines[1:]).upper()
    if ":" not in sequence:
        raise InputValidationError("FASTA must contain exactly one ':' (VH:VL)")
    vh, _, rest = sequence.partition(":")
    if ":" in rest:
        raise InputValidationError("FASTA must contain exactly one ':' (VH:VL)")
    vl = rest
    if not vh or not vl:
        raise InputValidationError("VH and VL chains must both be non-empty")
    for label, chain in (("VH", vh), ("VL", vl)):
        invalid = sorted(set(chain) - PREDICTION_AMINO_ACIDS)
        if invalid:
            raise InputValidationError(
                f"{label} contains unsupported amino-acid symbols: "
                f"{''.join(invalid)}"
            )
    return {"VH": vh, "VL": vl}


def _validate_prediction_pdb(
    path: Path,
    *,
    expect_two_chains: bool = True,
) -> tuple[int, list[str]]:
    """Reject empty PDBs or PDBs with fewer chains than expected."""
    atom_count = 0
    chains: set[str] = set()
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if line.startswith(("ATOM  ", "HETATM")):
                atom_count += 1
                if len(line) > 21 and line[21].strip():
                    chains.add(line[21])
    if atom_count == 0:
        raise ValueError("ColabFold PDB contains no ATOM/HETATM records")
    minimum_chains = 2 if expect_two_chains else 1
    if len(chains) < minimum_chains:
        raise ValueError(
            f"ColabFold PDB has {len(chains)} chain(s); expected at least "
            f"{minimum_chains}"
        )
    return atom_count, sorted(chains)


# ------------------------------------------------------------------
# Backend
# ------------------------------------------------------------------

class ColabFoldContainerBackend:
    """Invoke ColabFold inside the D3 GPU worker container.

    Parameters
    ----------
    compose_file:
        Path to the docker-compose file.  Must exist as a regular file.
    service:
        Compose service name (default ``colabfold``).
    work_root:
        Host directory exported as ``LABMATE_DOCKER_WORK_ROOT``; the
        container mounts ``<work_root>/input`` -> ``/work/input`` (ro) and
        ``<work_root>/output`` -> ``/work/output`` (rw).
    data_root:
        Host directory with model weights, exported as
        ``LABMATE_COLABFOLD_DATA_ROOT``; mounted read-only at
        ``/models/colabfold``.
    cache_root:
        Host directory for the JAX compilation cache, exported as
        ``LABMATE_COLABFOLD_CACHE_ROOT``; mounted read-write at
        ``/work/cache``.
    docker_bin:
        Docker executable (default ``docker``).
    timeout_seconds:
        Per-invocation timeout.
    """

    name = "colabfold_container"

    def __init__(
        self,
        *,
        compose_file: str | None = None,
        service: str = _DEFAULT_SERVICE,
        work_root: Path,
        data_root: Path,
        cache_root: Path,
        docker_bin: str = _DEFAULT_DOCKER_BIN,
        timeout_seconds: int = 1800,
    ) -> None:
        if not _SAFE_SERVICE_RE.fullmatch(service):
            raise ValueError(f"service name invalid: {service!r}")
        self._service = service

        if not _SAFE_DOCKER_BIN_RE.fullmatch(docker_bin):
            raise ValueError(f"docker_bin invalid: {docker_bin!r}")
        self._docker_bin = docker_bin

        raw_compose = Path(compose_file or _DEFAULT_COMPOSE_FILE)
        self._compose_file = raw_compose.resolve()
        if not self._compose_file.is_file():
            raise ValueError(
                f"compose_file does not exist or is not a regular file: "
                f"{self._compose_file}"
            )

        self._work_root = work_root.resolve()
        if not self._work_root.is_dir():
            raise ValueError(f"work_root must be an existing directory: {self._work_root}")
        self._data_root = data_root.resolve()
        if not self._data_root.is_dir():
            raise ValueError(f"data_root must be an existing directory: {self._data_root}")
        self._cache_root = cache_root.resolve()
        if not self._cache_root.is_dir():
            raise ValueError(f"cache_root must be an existing directory: {self._cache_root}")

        # Ensure required subdirectories
        (self._work_root / "input").mkdir(parents=True, exist_ok=True)
        (self._work_root / "output").mkdir(parents=True, exist_ok=True)
        (self._cache_root).mkdir(parents=True, exist_ok=True)

        # Pre-verify the five multimer_v3 parameter files
        params_dir = self._data_root / "params"
        missing = [
            name for name in _MULTIMER_V3_FILES
            if not (params_dir / name).is_file()
        ]
        if missing:
            raise ValueError(
                "ColabFold model data incomplete; missing parameter files: "
                + ", ".join(missing)
            )

        if not 1 <= timeout_seconds <= _MAX_TIMEOUT:
            raise ValueError(
                f"timeout must be 1..{_MAX_TIMEOUT}s, got {timeout_seconds}"
            )
        self._timeout_seconds = timeout_seconds

        self._env = {
            **os.environ,
            "LABMATE_DOCKER_WORK_ROOT": str(self._work_root),
            "LABMATE_COLABFOLD_DATA_ROOT": str(self._data_root),
            "LABMATE_COLABFOLD_CACHE_ROOT": str(self._cache_root),
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def version(self) -> dict[str, str]:
        """Return ColabFold and JAX versions from inside the container."""
        record = self._run_container(["version"])
        return self._parse_version_output(record["stdout"])

    def gpu_check(self) -> dict[str, str]:
        """Verify GPU visibility inside the container."""
        record = self._run_container(["gpu-check"])
        return {"gpu_info": record["stdout"].strip()}

    def predict(
        self,
        heavy_chain: str,
        light_chain: str | None,
        antigen_pdb: Path | None = None,
        output_dir: Path | None = None,
    ) -> PredictionResult:
        """Predict one VH:VL pair inside the container.

        Mirrors the host ``ColabFoldBackend.predict`` contract.  The
        FASTA is written into ``<work_root>/input/`` and the fixed
        entrypoint parameters are used; the caller cannot override them.
        """
        if light_chain is None:
            return PredictionResult(
                backend_name=self.name,
                status="failed",
                warnings=["ColabFold container worker requires paired VH/VL"],
            )
        heavy = normalize_prediction_sequence(heavy_chain, label="heavy_chain")
        light = normalize_prediction_sequence(light_chain, label="light_chain")

        if output_dir is None:
            return PredictionResult(
                backend_name=self.name,
                status="failed",
                warnings=["ColabFold container prediction requires an output_dir"],
            )
        requested = output_dir.expanduser()
        if requested.is_symlink():
            return PredictionResult(
                backend_name=self.name,
                status="failed",
                warnings=["ColabFold output_dir must not be a symbolic link"],
            )
        output_dir = requested.resolve()
        output_dir.mkdir(parents=True, exist_ok=True)

        fasta_name = "input.fasta"
        input_dir = self._work_root / "input"
        fasta_path = input_dir / fasta_name
        fasta_path.write_text(
            f">antibody\n{heavy}:{light}\n",
            encoding="utf-8",
        )

        # Sanitized log-safe copies of the sequences (do not log full VH/VL)
        safe_heavy = heavy[:4] + "..." if len(heavy) > 4 else heavy
        safe_light = light[:4] + "..." if len(light) > 4 else light

        try:
            record = self._run_container(["predict", fasta_name, "out"])
        except LabmateError as exc:
            return PredictionResult(
                backend_name=self.name,
                status="failed",
                metadata={"return_code": "nonzero-or-timeout"},
                warnings=[str(exc)],
            )

        # Output discovery inside <work_root>/output/out/
        prediction_root = self._work_root / "output" / "out"
        pdb_candidates: list[Path] = []
        for path in prediction_root.rglob("*"):
            if path.is_symlink():
                return PredictionResult(
                    backend_name=self.name,
                    status="failed",
                    metadata=record,
                    warnings=[
                        "ColabFold output contains a symbolic link; refusing "
                        "unsafe output discovery"
                    ],
                )
            if path.suffix.lower() != ".pdb" or not path.is_file():
                continue
            resolved = path.resolve(strict=True)
            try:
                resolved.relative_to(prediction_root.resolve())
            except ValueError:
                return PredictionResult(
                    backend_name=self.name,
                    status="failed",
                    metadata=record,
                    warnings=[
                        "ColabFold PDB resolved outside the prediction directory"
                    ],
                )
            pdb_candidates.append(resolved)
        pdb_candidates.sort()

        if not pdb_candidates:
            return PredictionResult(
                backend_name=self.name,
                status="failed",
                metadata=record,
                warnings=["ColabFold completed but produced no PDB file"],
            )

        rank_one = [
            path for path in pdb_candidates
            if _RANK_ONE_PDB.search(path.name) or path.name == "ranked_0.pdb"
        ]
        if len(rank_one) != 1:
            return PredictionResult(
                backend_name=self.name,
                status="failed",
                metadata=record,
                warnings=[
                    "ColabFold output discovery expected exactly one rank-1 "
                    f"PDB, found {len(rank_one)}"
                ],
            )
        preferred = rank_one[0]
        try:
            atom_count, chains = _validate_prediction_pdb(
                preferred, expect_two_chains=True
            )
        except (OSError, ValueError) as exc:
            return PredictionResult(
                backend_name=self.name,
                status="failed",
                metadata=record,
                warnings=[str(exc)],
            )

        metadata: dict[str, object] = {
            **record,
            "pdb_count": len(pdb_candidates),
            "atom_count": atom_count,
            "chains": chains,
            "chain_sequence_sha256": {
                "VH": _sequence_sha256(heavy),
                "VL": _sequence_sha256(light),
            },
            "network_policy": "offline_single_sequence/runtime_network_disabled",
            "model_data_policy": "user_mounted_preinstalled_only",
            "fixed_parameters": list(FIXED_COLABFOLD_ARGS),
            "input_sequence_preview": {
                "VH": safe_heavy,
                "VL": safe_light,
            },
        }

        warnings: list[str] = []
        if "CUDA_ERROR_OUT_OF_MEMORY" in str(record.get("stderr", "")):
            warnings.append(
                "ColabFold completed after GPU memory allocation warnings; "
                "review colabfold.stderr.log."
            )

        return PredictionResult(
            pdb_path=preferred,
            backend_name=self.name,
            status="succeeded",
            metadata=metadata,
            warnings=warnings,
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _run_container(self, args: list[str]) -> dict[str, Any]:
        command = [
            self._docker_bin,
            "compose",
            "-f", str(self._compose_file),
            "run",
            "--rm",
            "--no-TTY",
            "--quiet-pull",
            self._service,
            *args,
        ]
        safe_args = [self._redact_arg(a) for a in args]
        display = " ".join(
            [Path(self._docker_bin).name, "compose", "-f",
             self._compose_file.name, "run", "--rm", self._service]
            + safe_args
        )
        roots = [self._work_root, self._data_root, self._cache_root]

        started = time.perf_counter()
        try:
            completed = subprocess.run(
                command,
                cwd=str(self._work_root),
                env=self._env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=self._timeout_seconds,
                encoding="utf-8",
                errors="replace",
                shell=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise LabmateError(
                f"ColabFold container timed out after {self._timeout_seconds}s"
            ) from exc
        except OSError as exc:
            raise LabmateError(
                f"Failed to invoke docker ({self._docker_bin}): {exc}"
            ) from exc

        elapsed = round(time.perf_counter() - started, 6)
        stdout = _redact(completed.stdout or "", roots)
        stderr = _redact(completed.stderr or "", roots)

        record: dict[str, Any] = {
            "command": safe_args,
            "display": display,
            "stdout": stdout,
            "stderr": stderr,
            "return_code": completed.returncode,
            "elapsed_seconds": elapsed,
        }
        if completed.returncode != 0:
            raise LabmateError(
                f"ColabFold container failed (exit {completed.returncode}); "
                f"stderr: {stderr[:512]}"
            )
        return record

    @staticmethod
    def _redact_arg(arg: str) -> str:
        arg = _ABSOLUTE_RE.sub("<local-path>", arg)
        arg = _TOKEN_RE.sub("<token-redacted>", arg)
        if len(arg) > 120:
            arg = arg[:117] + "..."
        return arg

    @staticmethod
    def _parse_version_output(text: str) -> dict[str, str]:
        result: dict[str, str] = {}
        for line in text.splitlines():
            if line.startswith("colabfold "):
                result["colabfold"] = line.split()[1]
            if line.startswith("jax "):
                parts = line.split()
                if len(parts) >= 4:
                    result["jax"] = parts[1]
                    result["jax_backend"] = parts[3]
        return result


def _sequence_sha256(sequence: str) -> str:
    import hashlib
    return hashlib.sha256(sequence.encode("utf-8")).hexdigest()

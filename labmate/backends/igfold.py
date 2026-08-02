"""Optional local IgFold structure-prediction wrapper."""

from __future__ import annotations

import importlib.metadata
import importlib.util
import json
import os
import re
import stat
import subprocess
import sys
from collections.abc import Callable
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Protocol

from labmate.backends.base import (
    PredictionBackend,
    PredictionResult,
    normalize_prediction_sequence,
)
from labmate.validators.antigen import THREE_TO_ONE, parse_complex_pdb

_MAX_METADATA_LOG_BYTES = 64 * 1024
_MAX_WARNING_BYTES = 4 * 1024
_WORKER_SCHEMA_VERSION = 1
_DEFAULT_WORKER_TIMEOUT_SECONDS = 30 * 60
_ANSI_ESCAPE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
_TOKEN_SHAPES = re.compile(
    r"(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|"
    r"xox[baprs]-[A-Za-z0-9-]{20,}|AKIA[0-9A-Z]{16})"
)
_ENVIRONMENT_VARIABLE_REFERENCE = re.compile(
    r"\b[A-Z][A-Z0-9_]{2,}\b"
    r"(?=(?:\s+shell)?\s+environment variable\b)"
)
_WINDOWS_ABSOLUTE_PATH = re.compile(
    r"(?<![A-Za-z0-9_])[A-Za-z]:[\\/][^\s'\"<>]+"
)
_POSIX_ABSOLUTE_PATH = re.compile(
    r"(?<![A-Za-z0-9_:/])/[^\s'\"<>]+"
)


class IgFoldRunnerProtocol(Protocol):
    def fold(
        self,
        output_path: str,
        *,
        sequences: dict[str, str],
        do_refine: bool,
        do_renum: bool,
    ) -> object:
        """Write an antibody PDB to ``output_path``."""


def _redact_text(value: str, replacements: list[tuple[str, str]]) -> str:
    sanitized = _ANSI_ESCAPE.sub("", value)
    for source, replacement in sorted(
        replacements,
        key=lambda item: len(item[0]),
        reverse=True,
    ):
        if source:
            sanitized = sanitized.replace(source, replacement)
    sanitized = _TOKEN_SHAPES.sub("<token-redacted>", sanitized)
    sanitized = _ENVIRONMENT_VARIABLE_REFERENCE.sub(
        "<environment-variable>",
        sanitized,
    )
    sanitized = _WINDOWS_ABSOLUTE_PATH.sub("<local-path>", sanitized)
    return _POSIX_ABSOLUTE_PATH.sub("<local-path>", sanitized)


def _bounded_warning(value: str) -> str:
    encoded = value.encode("utf-8", errors="replace")
    if len(encoded) <= _MAX_WARNING_BYTES:
        return value
    marker = b"...<warning truncated>"
    return (encoded[: _MAX_WARNING_BYTES - len(marker)] + marker).decode(
        "utf-8",
        errors="ignore",
    )


def _sanitize_log(
    raw_path: Path,
    destination: Path,
    replacements: list[tuple[str, str]],
) -> None:
    with raw_path.open("r", encoding="utf-8", errors="replace") as source:
        with destination.open("x", encoding="utf-8", newline="") as target:
            for line in source:
                target.write(_redact_text(line, replacements))
    raw_path.unlink()


def _bounded_log_text(path: Path) -> str:
    size = path.stat().st_size
    with path.open("rb") as handle:
        if size <= _MAX_METADATA_LOG_BYTES:
            return handle.read().decode("utf-8", errors="replace")
        half = _MAX_METADATA_LOG_BYTES // 2
        first = handle.read(half)
        handle.seek(-half, 2)
        last = handle.read(half)
    omitted = size - len(first) - len(last)
    marker = f"\n<log excerpt: {omitted} bytes omitted>\n".encode()
    return (first + marker + last).decode("utf-8", errors="replace")


def _ordered_chain_sequence(parsed: object, chain_id: str) -> str:
    atoms = getattr(parsed, "atoms")
    residues = list(
        dict.fromkeys(
            atom.residue
            for atom in atoms
            if atom.residue.chain_id == chain_id
        )
    )
    return "".join(THREE_TO_ONE[residue.residue_name] for residue in residues)


def _validate_prediction_pdb(
    path: Path,
    *,
    output_dir: Path,
    expected_sequences: dict[str, str],
) -> dict[str, object]:
    if path.is_symlink():
        raise ValueError(
            "IgFold output contains a symbolic link; refusing unsafe output discovery"
        )
    resolved = path.resolve()
    try:
        resolved.relative_to(output_dir)
    except ValueError as exc:
        raise ValueError("IgFold PDB resolved outside output_dir") from exc
    if not resolved.is_file() or resolved.stat().st_size == 0:
        raise ValueError("IgFold completed but produced no PDB file")

    data = resolved.read_bytes()
    text = data.decode("utf-8", errors="replace")
    if "<html" in text[:4096].lower():
        raise ValueError("IgFold output is HTML rather than a PDB")

    atom_count = 0
    hetero_atom_count = 0
    hydrogen_atom_count = 0
    nonstandard_residues: set[tuple[str, str, str, str]] = set()
    for line in text.splitlines():
        record = line[0:6].strip().upper()
        if record not in {"ATOM", "HETATM"}:
            continue
        atom_count += 1
        if record == "HETATM":
            hetero_atom_count += 1
        residue_name = line[17:20].strip().upper()
        if residue_name not in THREE_TO_ONE:
            nonstandard_residues.add(
                (
                    line[21:22].strip(),
                    line[22:26].strip(),
                    line[26:27].strip(),
                    residue_name,
                )
            )
        element = line[76:78].strip().upper() if len(line) >= 78 else ""
        atom_name = line[12:16].strip().upper() if len(line) >= 16 else ""
        if element == "H" or (not element and atom_name.startswith("H")):
            hydrogen_atom_count += 1
    if atom_count == 0:
        raise ValueError("IgFold PDB contains no ATOM/HETATM records")

    parsed = parse_complex_pdb(data)
    observed_chains = set(parsed.chains)
    if observed_chains != set(expected_sequences):
        raise ValueError(
            "IgFold PDB chain IDs do not exactly match the requested H/L pair"
        )

    residue_counts: dict[str, int] = {}
    for chain_id, expected in expected_sequences.items():
        observed = _ordered_chain_sequence(parsed, chain_id)
        if observed != expected:
            raise ValueError(
                f"IgFold PDB chain {chain_id} sequence does not exactly match input"
            )
        residue_counts[chain_id] = len(observed)

    return {
        "atom_count": atom_count,
        "hetero_atom_count": hetero_atom_count,
        "hydrogen_atom_count": hydrogen_atom_count,
        "nonstandard_residue_count": len(nonstandard_residues),
        "chains": sorted(observed_chains),
        "residue_counts": residue_counts,
        "sequence_preserved": True,
    }


def _runner_device(runner: object) -> str | None:
    try:
        models = getattr(runner, "models")
        return str(next(models[0].parameters()).device)
    except (AttributeError, IndexError, StopIteration, TypeError):
        return None


class IgFoldBackend(PredictionBackend):
    """Run an installed IgFold package; model installation stays external."""

    name = "igfold"

    def __init__(
        self,
        *,
        runner_factory: Callable[[], IgFoldRunnerProtocol] | None = None,
        num_models: int = 1,
        try_gpu: bool = True,
        igfold_python: str | Path | None = None,
        worker_timeout_seconds: int = _DEFAULT_WORKER_TIMEOUT_SECONDS,
    ) -> None:
        if num_models != 1:
            raise ValueError(
                "IgFoldBackend currently fixes num_models=1 for bounded prediction-only runs"
            )
        self.runner_factory = runner_factory
        self.num_models = num_models
        self.try_gpu = try_gpu
        self.igfold_python = igfold_python
        if worker_timeout_seconds <= 0:
            raise ValueError("IgFold worker timeout must be positive")
        self.worker_timeout_seconds = worker_timeout_seconds

    def _configured_external_python(self) -> str | Path | None:
        if self.igfold_python is not None:
            return self.igfold_python
        configured = os.environ.get("LABMATE_IGFOLD_PYTHON")
        return configured or None

    @staticmethod
    def _validate_external_python(value: str | Path) -> Path:
        if not isinstance(value, (str, Path)) or not str(value).strip():
            raise ValueError("IgFold Python interpreter must be a non-empty path")
        raw = Path(value)
        # An interpreter is one executable path, never an argument string.
        if any(character in str(raw) for character in "\n\r\x00;|&`$<>"):
            raise ValueError("IgFold Python interpreter must be an executable path")
        resolved = raw.expanduser().resolve()
        if not resolved.is_file() or not stat.S_ISREG(resolved.stat().st_mode):
            raise ValueError("IgFold Python interpreter must be an existing regular file")
        if not os.access(resolved, os.X_OK):
            raise ValueError("IgFold Python interpreter is not executable")
        return resolved

    @staticmethod
    def _worker_script() -> Path:
        worker = Path(__file__).resolve().parents[1] / "workers" / "igfold_worker.py"
        if not worker.is_file() or worker.is_symlink():
            raise RuntimeError("IgFold external worker is unavailable")
        return worker

    @staticmethod
    def _safe_worker_environment(*, worker_dir: Path) -> dict[str, str]:
        cache_dir = worker_dir / "cache"
        cache_dir.mkdir(mode=0o700, exist_ok=True)
        return {
            "PATH": os.defpath,
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "PYTHONNOUSERSITE": "1",
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "HF_HOME": str(cache_dir),
            "TORCH_HOME": str(cache_dir),
        }

    @staticmethod
    def _write_private_json(path: Path, payload: dict[str, object]) -> None:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _read_worker_response(path: Path, *, worker_dir: Path) -> dict[str, object]:
        if path.is_symlink() or not path.is_file():
            raise ValueError("IgFold worker did not produce a regular response JSON")
        resolved = path.resolve()
        try:
            resolved.relative_to(worker_dir)
        except ValueError as exc:
            raise ValueError("IgFold worker response resolved outside output_dir") from exc
        try:
            response = json.loads(resolved.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("IgFold worker response JSON is invalid") from exc
        if not isinstance(response, dict):
            raise ValueError("IgFold worker response must be a JSON object")
        allowed = {
            "schema_version", "status", "pdb_filename", "backend_version",
            "model_count", "device", "native_metrics", "warnings",
            "error_type", "error_message",
        }
        if set(response) - allowed or response.get("schema_version") != _WORKER_SCHEMA_VERSION:
            raise ValueError("IgFold worker response schema is invalid")
        return response

    def _predict_external(
        self,
        *,
        heavy: str,
        light: str,
        antigen_pdb: Path | None,
        output_dir: Path | None,
        interpreter_value: str | Path,
    ) -> PredictionResult:
        try:
            interpreter = self._validate_external_python(interpreter_value)
        except ValueError as exc:
            return PredictionResult(backend_name=self.name, status="unavailable", warnings=[str(exc)])
        if output_dir is None:
            return PredictionResult(backend_name=self.name, status="failed", warnings=["IgFold prediction requires an explicit output_dir"])
        requested_output_dir = Path(output_dir)
        if requested_output_dir.is_symlink():
            return PredictionResult(backend_name=self.name, status="failed", warnings=["IgFold output directory must not be a symbolic link"])
        resolved_output_dir = requested_output_dir.resolve()
        if resolved_output_dir.exists():
            if not resolved_output_dir.is_dir():
                return PredictionResult(backend_name=self.name, status="failed", warnings=["IgFold output path is not a directory"])
            if any(resolved_output_dir.iterdir()):
                return PredictionResult(backend_name=self.name, status="failed", warnings=["IgFold output directory must be empty to prevent stale-output selection"])
        else:
            resolved_output_dir.mkdir(parents=True, mode=0o700)

        worker_dir = resolved_output_dir / "igfold"
        worker_dir.mkdir(mode=0o700)
        request_path = worker_dir / "request.json"
        response_path = worker_dir / "response.json"
        stdout_log = worker_dir / "igfold_stdout.log"
        stderr_log = worker_dir / "igfold_stderr.log"
        self._write_private_json(request_path, {
            "schema_version": _WORKER_SCHEMA_VERSION,
            "heavy_chain": heavy, "light_chain": light,
            "output_pdb": "igfold_prediction.pdb", "model_count": 1,
            "do_refine": False, "do_renum": False,
        })
        replacements = [
            (str(resolved_output_dir), "<output_dir>"), (str(worker_dir), "<worker_dir>"),
            (str(Path.cwd().resolve()), "<project_root>"), (str(Path.home().resolve()), "<home>"),
            (str(interpreter), "<igfold-python>"), (heavy, "<heavy-chain>"), (light, "<light-chain>"),
        ]
        try:
            worker_script = self._worker_script()
            version = subprocess.run(
                [str(interpreter), "--version"], capture_output=True, text=True,
                check=False, shell=False, timeout=30,
                env=self._safe_worker_environment(worker_dir=worker_dir),
            )
            if version.returncode != 0:
                raise RuntimeError("IgFold Python interpreter version check failed")
            command = [str(interpreter), str(worker_script), "--request", str(request_path), "--response", str(response_path)]
            completed = subprocess.run(
                command, capture_output=True, text=True, check=False, shell=False,
                timeout=self.worker_timeout_seconds,
                env=self._safe_worker_environment(worker_dir=worker_dir),
            )
        except subprocess.TimeoutExpired:
            stdout_log.write_text("", encoding="utf-8")
            stderr_log.write_text("IgFold worker timed out.\n", encoding="utf-8")
            return PredictionResult(backend_name=self.name, status="failed", metadata={"stdout_log": stdout_log.name, "stderr_log": stderr_log.name}, warnings=["IgFold worker timed out"])
        except (OSError, RuntimeError) as exc:
            safe_error = _bounded_warning(_redact_text(str(exc), replacements))
            return PredictionResult(backend_name=self.name, status="failed", warnings=[f"IgFold worker startup failed: {safe_error}"])

        stdout_log.write_text(_redact_text(completed.stdout or "", replacements), encoding="utf-8")
        stderr_log.write_text(_redact_text(completed.stderr or "", replacements), encoding="utf-8")
        log_metadata: dict[str, object] = {
            "stdout_log": stdout_log.name, "stderr_log": stderr_log.name,
            "stdout": _bounded_log_text(stdout_log), "stderr": _bounded_log_text(stderr_log),
            "execution_kind": "external_interpreter_local_prediction_only",
            "interpreter": "external_python",
            "interpreter_version": _bounded_warning(_redact_text((version.stdout or version.stderr).strip(), replacements)),
            "model_count": 1, "refinement": False, "renumbering": False,
        }
        if completed.returncode != 0:
            return PredictionResult(backend_name=self.name, status="failed", metadata=log_metadata, warnings=[f"IgFold worker failed with exit code {completed.returncode}"])
        try:
            response = self._read_worker_response(response_path, worker_dir=worker_dir)
            if response.get("status") != "succeeded":
                raise ValueError("IgFold worker reported failure")
            filename = response.get("pdb_filename")
            if not isinstance(filename, str) or Path(filename).name != filename:
                raise ValueError("IgFold worker returned an unsafe PDB filename")
            pdb_path = worker_dir / filename
            pdb_metadata = _validate_prediction_pdb(pdb_path, output_dir=worker_dir, expected_sequences={"H": heavy, "L": light})
        except ValueError as exc:
            return PredictionResult(backend_name=self.name, status="failed", metadata=log_metadata, warnings=[_bounded_warning(_redact_text(f"IgFold output validation failed: {exc}", replacements))])
        for name in ("backend_version", "device"):
            value = response.get(name)
            if isinstance(value, str) and value:
                log_metadata[f"igfold_{name}"] = _bounded_warning(_redact_text(value, replacements))
        native_metrics = response.get("native_metrics")
        if isinstance(native_metrics, dict):
            log_metadata["native_metrics"] = native_metrics
            log_metadata["native_metrics_semantics"] = "backend_native_unscaled"
        log_metadata.update(pdb_metadata)
        warnings = [_bounded_warning(_redact_text(item, replacements)) for item in response.get("warnings", []) if isinstance(item, str)]
        if antigen_pdb is not None:
            warnings.append("IgFold prediction-only backend does not use antigen_pdb.")
        return PredictionResult(pdb_path=pdb_path.resolve(), backend_name=self.name, status="succeeded", metadata=log_metadata, warnings=warnings)

    def _load_runner(self) -> IgFoldRunnerProtocol | None:
        if self.runner_factory is not None:
            return self.runner_factory()
        if importlib.util.find_spec("igfold") is None:
            return None
        from igfold import IgFoldRunner  # type: ignore[import-not-found]
        import torch  # type: ignore[import-not-found]
        from transformers.models.bert.configuration_bert import (  # type: ignore[import-not-found]
            BertConfig,
        )
        try:
            from transformers.models.bert.tokenization_bert import (  # type: ignore[import-not-found]
                BasicTokenizer,
                BertTokenizer,
                WordpieceTokenizer,
            )
            from transformers.tokenization_utils import Trie  # type: ignore[import-not-found]
        except ImportError as exc:
            try:
                transformers_version = importlib.metadata.version(
                    "transformers"
                )
            except importlib.metadata.PackageNotFoundError:
                transformers_version = "unknown"
            raise RuntimeError(
                "IgFold checkpoint compatibility unavailable: installed "
                f"Transformers {transformers_version} does not expose the "
                "legacy BERT tokenizer types required by IgFold 0.4.0"
            ) from exc
        checkpoint_globals: list[object] = [
            BasicTokenizer,
            BertConfig,
            BertTokenizer,
            Trie,
            WordpieceTokenizer,
        ]

        serialization = getattr(torch, "serialization", None)
        safe_globals = getattr(serialization, "safe_globals", None)
        if safe_globals is None:
            self._checkpoint_loading = "legacy_torch_checkpoint_loading"
            return IgFoldRunner(
                num_models=self.num_models,
                try_gpu=self.try_gpu,
            )
        self._checkpoint_loading = "weights_only_with_fixed_safe_globals"
        with safe_globals(checkpoint_globals):
            return IgFoldRunner(
                num_models=self.num_models,
                try_gpu=self.try_gpu,
            )

    def predict(
        self,
        heavy_chain: str,
        light_chain: str | None,
        antigen_pdb: Path | None = None,
        output_dir: Path | None = None,
    ) -> PredictionResult:
        heavy = normalize_prediction_sequence(heavy_chain, label="heavy_chain")
        light = normalize_prediction_sequence(light_chain, label="light_chain")
        if light is None:
            return PredictionResult(
                backend_name=self.name,
                status="failed",
                warnings=[
                    "IgFold prediction-only backend requires a paired VH/VL input"
                ],
            )
        external_python = self._configured_external_python()
        if external_python is not None:
            if self.runner_factory is not None:
                return PredictionResult(
                    backend_name=self.name,
                    status="failed",
                    warnings=[
                        "IgFold external interpreter cannot be combined with a runner factory"
                    ],
                )
            return self._predict_external(
                heavy=heavy,
                light=light,
                antigen_pdb=antigen_pdb,
                output_dir=output_dir,
                interpreter_value=external_python,
            )
        if (
            self.runner_factory is None
            and importlib.util.find_spec("igfold") is None
        ):
            return PredictionResult(
                backend_name=self.name,
                status="unavailable",
                warnings=["IgFold backend unavailable"],
            )
        if output_dir is None:
            return PredictionResult(
                backend_name=self.name,
                status="failed",
                warnings=["IgFold prediction requires an explicit output_dir"],
            )

        requested_output_dir = Path(output_dir)
        if requested_output_dir.is_symlink():
            return PredictionResult(
                backend_name=self.name,
                status="failed",
                warnings=[
                    "IgFold output directory must not be a symbolic link"
                ],
            )
        resolved_output_dir = requested_output_dir.resolve()
        if resolved_output_dir.exists():
            if not resolved_output_dir.is_dir():
                return PredictionResult(
                    backend_name=self.name,
                    status="failed",
                    warnings=["IgFold output path is not a directory"],
                )
            if any(resolved_output_dir.iterdir()):
                return PredictionResult(
                    backend_name=self.name,
                    status="failed",
                    warnings=[
                        "IgFold output directory must be empty to prevent stale-output selection"
                    ],
                )
        else:
            resolved_output_dir.mkdir(parents=True)

        pdb_path = resolved_output_dir / "igfold_prediction.pdb"
        raw_stdout = resolved_output_dir / ".igfold.stdout.raw"
        raw_stderr = resolved_output_dir / ".igfold.stderr.raw"
        stdout_log = resolved_output_dir / "igfold.stdout.log"
        stderr_log = resolved_output_dir / "igfold.stderr.log"
        replacements = [
            (str(resolved_output_dir), "<output_dir>"),
            (str(Path.cwd().resolve()), "<project_root>"),
            (str(Path.home().resolve()), "<home>"),
            (str(Path(sys.prefix).resolve()), "<python-environment>"),
            (heavy, "<heavy-chain>"),
            (light, "<light-chain>"),
        ]
        phase = "initialization"
        failure: Exception | None = None
        runner: IgFoldRunnerProtocol | None = None
        with raw_stdout.open("x", encoding="utf-8", newline="") as stdout_handle:
            with raw_stderr.open("x", encoding="utf-8", newline="") as stderr_handle:
                with redirect_stdout(stdout_handle), redirect_stderr(stderr_handle):
                    try:
                        runner = self._load_runner()
                        if runner is None:
                            raise RuntimeError(
                                "IgFold package became unavailable during initialization"
                            )
                        phase = "inference"
                        runner.fold(
                            str(pdb_path),
                            sequences={"H": heavy, "L": light},
                            do_refine=False,
                            do_renum=False,
                        )
                    except Exception as exc:  # external package boundary
                        failure = exc

        _sanitize_log(raw_stdout, stdout_log, replacements)
        _sanitize_log(raw_stderr, stderr_log, replacements)
        log_metadata: dict[str, object] = {
            "stdout_log": stdout_log.name,
            "stderr_log": stderr_log.name,
            "stdout": _bounded_log_text(stdout_log),
            "stderr": _bounded_log_text(stderr_log),
            "refinement": False,
            "renumbering": False,
            "model_count": self.num_models,
        }
        if failure is not None:
            safe_error = _bounded_warning(
                _redact_text(str(failure), replacements)
            )
            return PredictionResult(
                backend_name=self.name,
                status="failed",
                metadata=log_metadata,
                warnings=[f"IgFold {phase} failed: {safe_error}"],
            )

        try:
            pdb_metadata = _validate_prediction_pdb(
                pdb_path,
                output_dir=resolved_output_dir,
                expected_sequences={"H": heavy, "L": light},
            )
        except Exception as exc:
            return PredictionResult(
                backend_name=self.name,
                status="failed",
                metadata=log_metadata,
                warnings=[
                    _redact_text(
                        f"IgFold output validation failed: {exc}",
                        replacements,
                    )
                ],
            )

        device = _runner_device(runner)
        if device is not None:
            log_metadata["device"] = device
        if self.runner_factory is None:
            try:
                log_metadata["igfold_version"] = importlib.metadata.version(
                    "igfold"
                )
            except importlib.metadata.PackageNotFoundError:
                pass
            log_metadata["checkpoint_loading"] = getattr(
                self,
                "_checkpoint_loading",
                "unknown",
            )
        log_metadata.update(pdb_metadata)
        log_metadata.update(
            {
                "execution_kind": "local_prediction_only",
                "model_source": "user-installed IgFold environment",
                "confidence_semantics": (
                    "IgFold predicted RMSD is stored in the PDB B-factor "
                    "column; it is not pLDDT and is not used for Replay ranking."
                ),
            }
        )
        warnings: list[str] = []
        if antigen_pdb is not None:
            warnings.append(
                "IgFold prediction-only backend does not use antigen_pdb."
            )
        return PredictionResult(
            pdb_path=pdb_path.resolve(),
            backend_name=self.name,
            status="succeeded",
            metadata=log_metadata,
            warnings=warnings,
        )

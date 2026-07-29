"""Local ColabFold structure-prediction wrapper."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from labmate.backends.base import (
    PredictionBackend,
    PredictionResult,
    normalize_prediction_sequence,
)

_MAX_METADATA_LOG_BYTES = 64 * 1024
_RANK_ONE_PDB = re.compile(r"_rank_001_.*\.pdb$")
_TOKEN_SHAPES = re.compile(
    r"(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|"
    r"xox[baprs]-[A-Za-z0-9-]{20,}|AKIA[0-9A-Z]{16})"
)
_ENVIRONMENT_VARIABLE_REFERENCE = re.compile(
    r"\b[A-Z][A-Z0-9_]{2,}\b"
    r"(?=(?:\s+shell)?\s+environment variable\b)"
)


def _redact_text(value: str, replacements: list[tuple[str, str]]) -> str:
    sanitized = value
    for source, replacement in sorted(
        replacements,
        key=lambda item: len(item[0]),
        reverse=True,
    ):
        if source:
            sanitized = sanitized.replace(source, replacement)
    sanitized = _TOKEN_SHAPES.sub("<token-redacted>", sanitized)
    return _ENVIRONMENT_VARIABLE_REFERENCE.sub(
        "<environment-variable>",
        sanitized,
    )


def _sanitize_log(
    raw_path: Path,
    destination: Path,
    replacements: list[tuple[str, str]],
) -> None:
    with raw_path.open("r", encoding="utf-8", errors="replace") as source:
        with destination.open("w", encoding="utf-8", newline="") as target:
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


def _validate_prediction_pdb(
    path: Path,
    *,
    expect_two_chains: bool,
) -> tuple[int, list[str]]:
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


class ColabFoldBackend(PredictionBackend):
    """Invoke a user-installed ``colabfold_batch`` without bundling it."""

    name = "colabfold"

    def __init__(
        self,
        *,
        executable: str = "colabfold_batch",
        model_data_dir: Path | None = None,
    ) -> None:
        self.executable = executable
        self.model_data_dir = (
            model_data_dir.resolve() if model_data_dir is not None else None
        )

    def _locate_executable(self) -> str | None:
        candidate = Path(self.executable)
        if candidate.parent != Path("."):
            return str(candidate.resolve()) if candidate.is_file() else None
        return shutil.which(self.executable)

    def predict(
        self,
        heavy_chain: str,
        light_chain: str | None,
        antigen_pdb: Path | None = None,
        output_dir: Path | None = None,
    ) -> PredictionResult:
        antigen_supplied = antigen_pdb is not None
        heavy = normalize_prediction_sequence(heavy_chain, label="heavy_chain")
        light = normalize_prediction_sequence(light_chain, label="light_chain")
        executable = self._locate_executable()
        if executable is None:
            message = "ColabFold backend unavailable: colabfold_batch not found"
            return PredictionResult(
                backend_name=self.name,
                status="unavailable",
                warnings=[message],
            )
        if self.model_data_dir is None or not self.model_data_dir.is_dir():
            return PredictionResult(
                backend_name=self.name,
                status="unavailable",
                warnings=[
                    "ColabFold backend unavailable: preinstalled model data directory not configured"
                ],
            )
        model_type = (
            "alphafold2_multimer_v3"
            if light is not None
            else "alphafold2_ptm"
        )
        parameter_name = (
            "params_model_1_multimer_v3.npz"
            if light is not None
            else "params_model_1_ptm.npz"
        )
        parameter_path = self.model_data_dir / "params" / parameter_name
        if not parameter_path.is_file():
            return PredictionResult(
                backend_name=self.name,
                status="unavailable",
                warnings=[
                    "ColabFold backend unavailable: required preinstalled "
                    f"weight file missing ({parameter_name})"
                ],
            )
        if output_dir is None:
            return PredictionResult(
                backend_name=self.name,
                status="failed",
                warnings=["ColabFold prediction requires an explicit output_dir"],
            )

        requested_output_dir = output_dir.expanduser()
        if requested_output_dir.is_symlink():
            return PredictionResult(
                backend_name=self.name,
                status="failed",
                warnings=["ColabFold output_dir must not be a symbolic link"],
            )
        output_dir = requested_output_dir.resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        if any(output_dir.iterdir()):
            return PredictionResult(
                backend_name=self.name,
                status="failed",
                warnings=["ColabFold prediction output_dir must be empty"],
            )
        fasta_path = output_dir / "input.fasta"
        prediction_dir = output_dir / "colabfold"
        multimer_sequence = heavy if light is None else f"{heavy}:{light}"
        fasta_path.write_text(
            f">antibody\n{multimer_sequence}\n",
            encoding="utf-8",
        )
        try:
            fasta_path.chmod(0o600)
        except OSError:
            pass
        prediction_dir.mkdir()
        command = [
            executable,
            str(fasta_path),
            str(prediction_dir),
            "--msa-mode",
            "single_sequence",
            "--data",
            str(self.model_data_dir),
            "--model-type",
            model_type,
            "--num-models",
            "1",
            "--num-recycle",
            "1",
            "--num-relax",
            "0",
            "--random-seed",
            "0",
            "--disable-unified-memory",
            "--compile-mode",
            "fast",
        ]
        raw_stdout = output_dir / ".colabfold.stdout.raw"
        raw_stderr = output_dir / ".colabfold.stderr.raw"
        stdout_log = output_dir / "colabfold.stdout.log"
        stderr_log = output_dir / "colabfold.stderr.log"
        replacements = [
            (str(output_dir), "<output_dir>"),
            (str(self.model_data_dir), "<preinstalled_model_data>"),
            (str(Path(executable).parent), "<colabfold_env>"),
            (str(Path.cwd().resolve()), "<project_root>"),
            (str(Path.home()), "<home>"),
        ]
        try:
            with raw_stdout.open("w", encoding="utf-8") as stdout_handle:
                with raw_stderr.open("w", encoding="utf-8") as stderr_handle:
                    completed = subprocess.run(
                        command,
                        stdout=stdout_handle,
                        stderr=stderr_handle,
                        text=True,
                        check=False,
                        shell=False,
                    )
        except OSError as exc:
            for raw_path, log_path in (
                (raw_stdout, stdout_log),
                (raw_stderr, stderr_log),
            ):
                if raw_path.is_file():
                    _sanitize_log(raw_path, log_path, replacements)
            return PredictionResult(
                backend_name=self.name,
                status="failed",
                metadata={"return_code": None},
                warnings=[
                    "ColabFold execution failed: "
                    + _redact_text(str(exc), replacements)
                ],
            )
        _sanitize_log(raw_stdout, stdout_log, replacements)
        _sanitize_log(raw_stderr, stderr_log, replacements)

        metadata: dict[str, object] = {
            "return_code": completed.returncode,
            "stdout": _bounded_log_text(stdout_log),
            "stderr": _bounded_log_text(stderr_log),
            "stdout_log": stdout_log.relative_to(output_dir).as_posix(),
            "stderr_log": stderr_log.relative_to(output_dir).as_posix(),
            "command": [
                Path(executable).name,
                "input.fasta",
                "colabfold",
                "--msa-mode",
                "single_sequence",
                "--data",
                "<preinstalled_model_data>",
                "--model-type",
                model_type,
                "--num-models",
                "1",
                "--num-recycle",
                "1",
                "--num-relax",
                "0",
                "--random-seed",
                "0",
                "--disable-unified-memory",
                "--compile-mode",
                "fast",
            ],
            "network_policy": "offline_single_sequence",
            "model_data_policy": "preinstalled_only",
        }
        if completed.returncode != 0:
            return PredictionResult(
                backend_name=self.name,
                status="failed",
                metadata=metadata,
                warnings=[
                    f"ColabFold execution failed with exit code {completed.returncode}"
                ],
            )

        prediction_root = prediction_dir.resolve()
        pdb_candidates: list[Path] = []
        for path in prediction_dir.rglob("*"):
            if path.is_symlink():
                return PredictionResult(
                    backend_name=self.name,
                    status="failed",
                    metadata=metadata,
                    warnings=[
                        "ColabFold output contains a symbolic link; refusing "
                        "unsafe output discovery"
                    ],
                )
            if path.suffix.lower() != ".pdb" or not path.is_file():
                continue
            resolved = path.resolve(strict=True)
            try:
                resolved.relative_to(prediction_root)
            except ValueError:
                return PredictionResult(
                    backend_name=self.name,
                    status="failed",
                    metadata=metadata,
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
                metadata=metadata,
                warnings=["ColabFold completed but produced no PDB file"],
            )
        rank_one = [
            path
            for path in pdb_candidates
            if _RANK_ONE_PDB.search(path.name) or path.name == "ranked_0.pdb"
        ]
        if len(rank_one) != 1:
            return PredictionResult(
                backend_name=self.name,
                status="failed",
                metadata=metadata,
                warnings=[
                    "ColabFold output discovery expected exactly one rank-1 "
                    f"PDB, found {len(rank_one)}"
                ],
            )
        preferred = rank_one[0]
        try:
            atom_count, chains = _validate_prediction_pdb(
                preferred,
                expect_two_chains=light is not None,
            )
        except (OSError, ValueError) as exc:
            return PredictionResult(
                backend_name=self.name,
                status="failed",
                metadata=metadata,
                warnings=[str(exc)],
            )
        metadata["pdb_count"] = len(pdb_candidates)
        metadata["atom_count"] = atom_count
        metadata["chains"] = chains
        warnings: list[str] = []
        if "CUDA_ERROR_OUT_OF_MEMORY" in str(metadata["stderr"]):
            warnings.append(
                "ColabFold completed after GPU memory allocation warnings; "
                "review colabfold.stderr.log."
            )
        if antigen_supplied:
            warnings.append(
                "antigen_pdb is not used by the prediction-only ColabFold backend."
            )
        return PredictionResult(
            pdb_path=preferred,
            backend_name=self.name,
            status="succeeded",
            metadata=metadata,
            warnings=warnings,
        )

"""External-interpreter bridge for the official RFantibody VHH design stage."""
from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

from .artifact import (
    DesignArtifact,
    DesignCandidate,
    DesignInput,
    regular_file,
    safe_native_metrics,
    sha256,
    sequence_sha256,
    validate_design_input,
    validate_vhh_candidate,
)

_WORKER_SCHEMA_VERSION = 1
_TOKEN = re.compile(r"(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16})")
_ABSOLUTE = re.compile(r"(?:[A-Za-z]:[\\/]|/(?:mnt|root|home)/)")


class RFantibodyBackend:
    """Run the verified official RFantibody VHH sequence-design pipeline locally."""

    name = "rfantibody"

    def __init__(self, *, python: Path, root: Path, worker: Path | None = None, timeout_seconds: int = 3600) -> None:
        self.python = self._executable(python, "RFantibody Python interpreter")
        self.root = root.resolve()
        if self.root.is_symlink() or not (self.root / "scripts" / "rfdiffusion_inference.py").is_file():
            raise ValueError("RFantibody root does not contain the official inference script")
        self.worker = worker or Path(__file__).resolve().parents[1] / "workers" / "rfantibody_worker.py"
        if self.worker.is_symlink() or not self.worker.is_file():
            raise ValueError("RFantibody worker is unavailable")
        if not 1 <= timeout_seconds <= 3600:
            raise ValueError("RFantibody timeout must be 1..3600 seconds")
        self.timeout_seconds = timeout_seconds

    @staticmethod
    def _executable(value: Path, label: str) -> Path:
        raw = Path(value)
        if any(char in str(raw) for char in "\n\r\x00;|&`$<>"):
            raise ValueError(f"{label} must be one executable path")
        resolved = raw.expanduser().resolve()
        if not resolved.is_file() or not stat.S_ISREG(resolved.stat().st_mode) or not os.access(resolved, os.X_OK):
            raise ValueError(f"{label} must be an executable regular file")
        return resolved

    @staticmethod
    def _environment() -> dict[str, str]:
        # Do not propagate credentials or a caller's arbitrary runtime state.
        return {"PATH": os.defpath, "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "PYTHONNOUSERSITE": "1"}

    @staticmethod
    def _write_json(path: Path, value: dict[str, object]) -> None:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            json.dump(value, handle, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _redact(value: str) -> str:
        value = _TOKEN.sub("<token-redacted>", value)
        return _ABSOLUTE.sub("<local-path>", value)

    @staticmethod
    def _copy_regular(source: Path, destination: Path, *, root: Path, label: str) -> None:
        source = regular_file(source, root=root, label=label)
        if destination.exists() or destination.is_symlink():
            raise ValueError(f"{label} destination already exists")
        destination.write_bytes(source.read_bytes())

    def execute(self, design_input: DesignInput, *, allowed_root: Path, output_dir: Path) -> DesignArtifact:
        root = allowed_root.resolve()
        target = validate_design_input(design_input, root=root)
        if output_dir.is_symlink() or output_dir.exists():
            raise ValueError("RFantibody output directory must be new and empty")
        output = output_dir.resolve()
        try:
            output.relative_to(root)
        except ValueError as exc:
            raise ValueError("RFantibody output escaped allowed root") from exc
        output.mkdir(parents=True, mode=0o700)
        worker_dir = output / "worker"
        worker_dir.mkdir(mode=0o700)
        copied_target = worker_dir / "target.pdb"
        copied_target.write_bytes(target.read_bytes())
        if sha256(copied_target) != design_input.target_sha256:
            raise ValueError("RFantibody target copy hash mismatch")
        resume_filename: str | None = None
        if design_input.resume_backbone_pdb is not None:
            resume_source = regular_file(root / design_input.resume_backbone_pdb, root=root, label="resume backbone PDB")
            resume_filename = "resume_backbone.pdb"
            (worker_dir / resume_filename).write_bytes(resume_source.read_bytes())
            if sha256(worker_dir / resume_filename) != design_input.resume_backbone_sha256:
                raise ValueError("RFantibody resume backbone copy hash mismatch")
        request = worker_dir / "request.json"; response = worker_dir / "response.json"
        self._write_json(request, {
            "schema_version": _WORKER_SCHEMA_VERSION,
            "target_filename": copied_target.name,
            "target_sha256": design_input.target_sha256,
            "target_chains": design_input.target_chains,
            "hotspot_residues": design_input.hotspot_residues,
            "antibody_format": design_input.antibody_format,
            "seed": design_input.seed,
            "candidate_count": design_input.candidate_count,
            "parameters": design_input.parameters,
            "resume_backbone_filename": resume_filename,
            "resume_backbone_sha256": design_input.resume_backbone_sha256,
        })
        logs = output / "logs"; logs.mkdir(mode=0o700)
        started = datetime.now(UTC); timer = time.monotonic()
        command = [str(self.python), str(self.worker), "--request", str(request), "--response", str(response), "--rfantibody-root", str(self.root), "--timeout-seconds", str(self.timeout_seconds)]
        try:
            completed = subprocess.run(command, cwd=worker_dir, env=self._environment(), capture_output=True, text=True, timeout=self.timeout_seconds + 30, shell=False, check=False)
        except subprocess.TimeoutExpired as exc:
            (logs / "stderr.log").write_text("TIMEOUT\n", encoding="utf-8")
            raise RuntimeError("RFantibody worker timed out") from exc
        (logs / "stdout.log").write_text(self._redact(completed.stdout or ""), encoding="utf-8")
        (logs / "stderr.log").write_text(self._redact(completed.stderr or ""), encoding="utf-8")
        if response.is_symlink() or not response.is_file():
            if completed.returncode:
                raise RuntimeError(f"RFantibody worker failed with exit code {completed.returncode}")
            raise ValueError("RFantibody worker did not produce a regular response")
        payload = json.loads(response.read_text(encoding="utf-8"))
        allowed = {"schema_version", "status", "backend_version", "repo_commit", "checkpoints", "checkpoint_sha256", "intermediate", "candidates", "pipeline_stages", "warnings", "error_type", "error_message"}
        if not isinstance(payload, dict) or set(payload) - allowed or payload.get("schema_version") != _WORKER_SCHEMA_VERSION:
            raise ValueError("RFantibody worker response schema is invalid")
        if payload.get("status") != "succeeded":
            # A worker failure must never create a prediction-ready candidate.
            # Preserve only its explicitly reported intermediate provenance.
            intermediate = payload.get("intermediate")
            if not isinstance(intermediate, dict):
                raise RuntimeError("RFantibody worker did not report success")
            return DesignArtifact(
                backend="rfantibody", backend_version=str(payload.get("backend_version", "unknown")),
                repo_commit=str(payload.get("repo_commit", "unknown")),
                checkpoints=dict(payload.get("checkpoints", {})), checkpoint_sha256=dict(payload.get("checkpoint_sha256", {})),
                input_sha256=sha256(request), seed=design_input.seed, parameters=design_input.parameters,
                intermediates=[intermediate], candidates=[], requested_candidate_count=design_input.candidate_count,
                pipeline_stages=list(payload.get("pipeline_stages", [])), prediction_ready=False,
                provenance={"execution_mode": "external_interpreter_worker", "target_sha256": design_input.target_sha256, "created_at": started.isoformat().replace("+00:00", "Z")},
                runtime_seconds=round(time.monotonic() - timer, 3), warnings=[str(item) for item in payload.get("warnings", [])],
                unsupported_claims=["no affinity prediction", "no binder validation", "no experimental validation", "no therapeutic claim", "no candidate quality ranking", "no cross-stage score comparability"], status="partial",
            )
        if completed.returncode:
            raise RuntimeError(f"RFantibody worker failed with exit code {completed.returncode}")
        candidates: list[DesignCandidate] = []
        for raw in payload.get("candidates", []):
            if not isinstance(raw, dict):
                raise ValueError("RFantibody worker candidate is invalid")
            filename = raw.get("pdb_filename")
            if not isinstance(filename, str) or Path(filename).name != filename:
                raise ValueError("RFantibody worker candidate filename is invalid")
            candidate_path = worker_dir / filename
            sequence, _atoms = validate_vhh_candidate(candidate_path, root=worker_dir)
            if raw.get("sequence") != sequence:
                raise ValueError("RFantibody worker candidate sequence disagrees with PDB")
            fasta_filename = raw.get("fasta_filename")
            if not isinstance(fasta_filename, str) or Path(fasta_filename).name != fasta_filename:
                raise ValueError("RFantibody worker candidate FASTA filename is invalid")
            fasta = worker_dir / fasta_filename
            if fasta.is_symlink() or not fasta.is_file() or "\n" not in fasta.read_text(encoding="utf-8"):
                raise ValueError("RFantibody worker candidate FASTA is invalid")
            metrics = safe_native_metrics(raw.get("native_metrics", {}))
            index = raw.get("generation_index")
            if not isinstance(index, int) or index < 0:
                raise ValueError("RFantibody generation_index is invalid")
            destination = output / "candidates" / f"candidate_{index:03d}.pdb"
            destination.parent.mkdir(exist_ok=True)
            self._copy_regular(candidate_path, destination, root=worker_dir, label="candidate PDB")
            fasta_destination = output / "candidates" / f"candidate_{index:03d}.fasta"
            self._copy_regular(fasta, fasta_destination, root=worker_dir, label="candidate FASTA")
            if sequence not in fasta_destination.read_text(encoding="utf-8"):
                raise ValueError("candidate FASTA does not contain the validated sequence")
            designed_count = raw.get("designed_residue_count")
            fixed_count = raw.get("fixed_residue_count")
            if not isinstance(designed_count, int) or designed_count < 1 or not isinstance(fixed_count, int) or fixed_count < 1:
                raise ValueError("RFantibody worker candidate position counts are invalid")
            candidates.append(DesignCandidate(candidate_id=f"rfantibody-{index:03d}", generation_index=index, antibody_format="vhh", heavy_sequence=sequence, sequence_sha256=sequence_sha256(sequence), sequence_fasta=fasta_destination.relative_to(output).as_posix(), designed_structure=destination.relative_to(output).as_posix(), designed_structure_sha256=sha256(destination), semantic_chain_map={"heavy": "H"}, designed_residue_count=designed_count, fixed_residue_count=fixed_count, native_metrics=metrics if isinstance(metrics, dict) else {}, native_metric_semantics="official ProteinMPNN sequence-design score; unscaled negative log-likelihood, not affinity or candidate quality", warnings=[]))
        if not candidates or len(candidates) != design_input.candidate_count or len({candidate.candidate_id for candidate in candidates}) != len(candidates):
            raise ValueError("RFantibody worker candidate count/identity is invalid")
        finished = datetime.now(UTC)
        intermediate = payload.get("intermediate")
        if not isinstance(intermediate, dict):
            raise ValueError("RFantibody worker did not preserve backbone intermediate provenance")
        backbone_name = intermediate.get("backbone_pdb")
        if not isinstance(backbone_name, str) or Path(backbone_name).name != backbone_name:
            raise ValueError("RFantibody worker backbone intermediate filename is invalid")
        backbone_source = worker_dir / backbone_name
        backbone_destination = output / "intermediates" / "backbone_000.pdb"
        backbone_destination.parent.mkdir(exist_ok=True)
        self._copy_regular(backbone_source, backbone_destination, root=worker_dir, label="backbone intermediate")
        intermediate = dict(intermediate)
        intermediate["backbone_pdb"] = backbone_destination.relative_to(output).as_posix()
        intermediate["backbone_pdb_sha256"] = sha256(backbone_destination)
        return DesignArtifact(backend="rfantibody", backend_version=str(payload.get("backend_version", "unknown")), repo_commit=str(payload.get("repo_commit", "unknown")), checkpoints=dict(payload.get("checkpoints", {})), checkpoint_sha256=dict(payload.get("checkpoint_sha256", {})), input_sha256=sha256(request), seed=design_input.seed, parameters=design_input.parameters, intermediates=[intermediate], candidates=sorted(candidates, key=lambda candidate: candidate.generation_index), requested_candidate_count=design_input.candidate_count, sequence_designed_candidate_count=len(candidates), sequence_validated_candidate_count=len(candidates), prediction_ready=True, pipeline_stages=list(payload.get("pipeline_stages", [])), provenance={"execution_mode": "external_interpreter_worker", "target_sha256": design_input.target_sha256, "created_at": started.isoformat().replace("+00:00", "Z")}, runtime_seconds=round(time.monotonic() - timer, 3), warnings=[str(item) for item in payload.get("warnings", [])], unsupported_claims=["no affinity prediction", "no binder validation", "no experimental validation", "no therapeutic claim", "no candidate quality ranking", "no cross-stage score comparability"], status="success")

"""LightDock-shaped Replay parser and an explicit Live capability gate."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from labmate.docking.base import DockingProvider
from labmate.errors import FixtureIntegrityError, LiveCapabilityUnavailable
from labmate.models import Capability, CapabilityStatus
from labmate.prediction_artifact import DockingInput

REQUIRED_COLUMNS = {
    "candidate_id",
    "pose_rank",
    "pose_id",
    "raw_score",
    "score_name",
    "score_direction",
    "complex_path",
    "provider",
    "provider_version",
    "source_kind",
    "tool_execution",
}


@dataclass(frozen=True)
class ParsedDockingPose:
    candidate_id: str
    pose_rank: int
    pose_id: str
    raw_score: float
    score_name: str
    score_direction: str
    complex_path: str
    provider: str
    provider_version: str
    source_kind: str
    tool_execution: str


@dataclass(frozen=True)
class DockingExecutionResult:
    """Tool-native local LightDock result; it is not an affinity estimate."""
    schema_version: int
    status: str
    docking_backend: str
    execution_mode: str
    output_directory: str
    pose_paths: list[str]
    pose_sha256: dict[str, str]
    native_scores: list[dict[str, object]]
    native_score_semantics: str
    selected_pose: str | None
    selected_pose_reason: str | None
    started_at: str
    completed_at: str
    runtime_seconds: float
    exit_codes: dict[str, int | None]
    tool_versions: dict[str, str]
    warnings: list[str]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _executable(path: Path, label: str) -> Path:
    if not path.exists() or not path.is_file() or not os.access(path, os.X_OK):
        raise ValueError(f"{label} must be an executable regular file")
    return path.resolve()


class LocalLightDockExecutor:
    """Fail-closed LightDock 0.9.x executor, separate from Replay ranking."""

    def __init__(self, *, setup_executable: Path, sampling_executable: Path, conformation_executable: Path) -> None:
        self.setup_executable = _executable(setup_executable, "LightDock setup executable")
        self.sampling_executable = _executable(sampling_executable, "LightDock sampling executable")
        self.conformation_executable = _executable(conformation_executable, "LightDock conformation executable")

    @staticmethod
    def _environment() -> dict[str, str]:
        return {"PATH": os.defpath, "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}

    @staticmethod
    def _redact_log(text: str) -> str:
        text = text.replace("\x1b", "")
        text = re.sub(r"(?:[A-Za-z]:[\\/]|/(?:mnt|root|home)/)\S+", "[redacted-path]", text)
        text = re.sub(r"(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16})", "[redacted-token]", text)
        return text[-16000:]

    def _run(self, command: list[str], *, cwd: Path, timeout_seconds: int, logs: Path, name: str) -> int:
        try:
            completed = subprocess.run(command, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, shell=False, timeout=timeout_seconds, env=self._environment(), encoding="utf-8", errors="replace")
        except subprocess.TimeoutExpired as exc:
            (logs / f"{name}.stderr.log").write_text("TIMEOUT\n", encoding="utf-8")
            raise RuntimeError(f"LightDock {name} timed out") from exc
        (logs / f"{name}.stdout.log").write_text(self._redact_log(completed.stdout or ""), encoding="utf-8")
        (logs / f"{name}.stderr.log").write_text(self._redact_log(completed.stderr or ""), encoding="utf-8")
        if completed.returncode:
            raise RuntimeError(f"LightDock {name} failed with exit code {completed.returncode}")
        return completed.returncode

    def _version(self) -> str:
        """Best-effort provenance probe; execution never trusts an inferred version."""
        try:
            completed = subprocess.run([str(self.sampling_executable), "-v"], cwd=self.sampling_executable.parent, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False, shell=False, timeout=10, env=self._environment(), encoding="utf-8", errors="replace")
        except (OSError, subprocess.TimeoutExpired):
            return "not-probed"
        match = re.search(r"\b([0-9]+\.[0-9]+(?:\.[0-9]+)?)\b", completed.stdout or "")
        return match.group(1) if completed.returncode == 0 and match else "not-probed"

    def execute(self, docking_input: DockingInput, *, allowed_root: Path, output_dir: Path, swarms: int = 1, glowworms: int = 5, steps: int = 5, seed: int = 0, timeout_seconds: int = 1800) -> DockingExecutionResult:
        if not 1 <= timeout_seconds <= 1800 or min(swarms, glowworms, steps) < 1:
            raise ValueError("timeout must be 1..1800 and sampling counts must be positive")
        root = allowed_root.resolve()
        antibody_source = root / docking_input.antibody_artifact.pdb_path
        antigen_source = root / docking_input.antigen_pdb_path
        inputs: list[tuple[Path, str, str]] = [
            (antibody_source, docking_input.antibody_artifact.pdb_sha256, "antibody"),
            (antigen_source, docking_input.antigen_pdb_sha256, "antigen"),
        ]
        resolved_inputs: list[Path] = []
        for source, expected, label in inputs:
            if source.is_symlink() or not source.is_file():
                raise ValueError(f"{label} input is missing, unsafe, or hash-mismatched")
            path = source.resolve()
            try:
                path.relative_to(root)
            except ValueError as exc:
                raise ValueError(f"{label} input escaped allowed root") from exc
            if _sha256(path) != expected:
                raise ValueError(f"{label} input is missing, unsafe, or hash-mismatched")
            resolved_inputs.append(path)
        antibody, antigen = resolved_inputs
        if output_dir.is_symlink() or (output_dir.exists() and any(output_dir.iterdir())):
            raise ValueError("docking output directory must be new and empty")
        output = output_dir.resolve(); output.mkdir(parents=True, exist_ok=False)
        started = datetime.now(UTC); timer = time.monotonic()
        work, logs, poses = output / "work", output / "logs", output / "poses"
        work.mkdir(); logs.mkdir(); poses.mkdir()
        receptor, ligand = work / "receptor_A.pdb", work / "antibody_HL.pdb"
        shutil.copy2(antigen, receptor); shutil.copy2(antibody, ligand)
        exits: dict[str, int | None] = {"setup": None, "sampling": None, "conformations": None}
        exits["setup"] = self._run([str(self.setup_executable), receptor.name, ligand.name, "-s", str(swarms), "-g", str(glowworms), "--seed_points", str(seed), "--noxt", "--noh", "--now"], cwd=work, timeout_seconds=timeout_seconds, logs=logs, name="setup")
        exits["sampling"] = self._run([str(self.sampling_executable), "setup.json", str(steps), "-c", "1", "-sg", str(seed)], cwd=work, timeout_seconds=timeout_seconds, logs=logs, name="sampling")
        gso = work / "swarm_0" / f"gso_{steps}.out"
        if gso.is_symlink() or not gso.is_file(): raise RuntimeError("LightDock GSO output is missing")
        rows = [line for line in gso.read_text(encoding="utf-8").splitlines() if line and not line.startswith("#")]
        parsed = [(index, float(row.split()[-1]), row) for index, row in enumerate(rows) if len(row.split()) >= 8]
        if not parsed: raise RuntimeError("LightDock GSO contained no score rows")
        row_index, score, row = max(parsed, key=lambda item: item[1])
        selected = work / "selected_top_poses.gso"; selected.write_text(row + "\n", encoding="utf-8")
        exits["conformations"] = self._run([str(self.conformation_executable), receptor.name, ligand.name, selected.name, "1"], cwd=work, timeout_seconds=timeout_seconds, logs=logs, name="conformations")
        generated = work / "lightdock_0.pdb"
        if generated.is_symlink() or not generated.is_file() or generated.stat().st_size == 0 or b"ATOM" not in generated.read_bytes(): raise RuntimeError("LightDock pose is absent or invalid")
        pose = poses / "pose_001.pdb"; shutil.copy2(generated, pose)
        # Reuse the established Phase 2a exact chain/residue validator rather
        # than accepting an arbitrary ATOM-bearing PDB as a successful pose.
        from labmate.live_local import _pdb_chain_contract, _validate_lightdock_pose
        receptor_sequences, receptor_keys = _pdb_chain_contract(receptor)
        ligand_sequences, ligand_keys = _pdb_chain_contract(ligand)
        _validate_lightdock_pose(
            pose,
            expected_sequences={**receptor_sequences, **ligand_sequences},
            expected_residue_keys={**receptor_keys, **ligand_keys},
        )
        native = [{"swarm": 0, "gso_row": row_index, "score": score, "score_name": "fastdfire", "score_direction": "higher_is_better"}]
        finished = datetime.now(UTC)
        tool_versions = {"lightdock_version": self._version(), "setup_sha256":_sha256(self.setup_executable),"sampling_sha256":_sha256(self.sampling_executable),"conformation_sha256":_sha256(self.conformation_executable)}
        result = DockingExecutionResult(1, "succeeded", "lightdock", "local_external_executable", ".", [_relative(pose, output)], {_relative(pose, output): _sha256(pose)}, native, "LightDock tool-native docking score (fastdfire); higher_is_better; not affinity", _relative(pose, output), f"highest explicit score in swarm_0/gso_{steps}.out", started.isoformat().replace("+00:00", "Z"), finished.isoformat().replace("+00:00", "Z"), round(time.monotonic()-timer,3), exits, tool_versions, [])
        manifest = {"schema_version":1,"run_id":output.name,"mode":"local_docking_execution","status":result.status,"prediction_backend":docking_input.antibody_artifact.backend_name,"prediction_pdb_sha256":docking_input.antibody_artifact.pdb_sha256,"antibody_chain_map":docking_input.antibody_artifact.chain_map,"antigen_sha256":docking_input.antigen_pdb_sha256,"antigen_chains":docking_input.antigen_chains,"receptor_role":docking_input.receptor_role,"ligand_role":docking_input.ligand_role,"docking_backend":"lightdock","tool_version":tool_versions["lightdock_version"],"parameters":{"swarms":swarms,"glowworms":glowworms,"gso_steps":steps,"seed":seed,"timeout_seconds":timeout_seconds},"normalized_inputs":{"receptor":_relative(receptor,output),"ligand":_relative(ligand,output),"receptor_sha256":_sha256(receptor),"ligand_sha256":_sha256(ligand)},"exit_codes":exits,"pose_count":1,"pose_paths":result.pose_paths,"pose_sha256":result.pose_sha256,"native_scores":native,"selected_pose":result.selected_pose,"selected_pose_reason":result.selected_pose_reason,"validation_steps":["input_sha256","regular_files","explicit_gso_row","pose_atom_records"],"unsupported_claims":["no scientific docking validation","no affinity prediction","no experimental validation","no epitope validation","no cross-backend confidence comparison","no therapeutic claim"]}
        (output / "docking_manifest.json").write_text(json.dumps(manifest, indent=2)+"\n", encoding="utf-8")
        return result


class LightDockProvider(DockingProvider):
    """Default provider contract; only fixed-output parsing exists in P0."""

    def preflight(self) -> Capability:
        return Capability(
            name="LightDockProvider",
            status=CapabilityStatus.REPLAY_ONLY,
            enabled=True,
            provider="lightdock",
            version="not-executed-in-p0",
            license_status="GPL-3.0 external tool; not bundled or invoked",
            reason=(
                "P0 only parses a project-authored synthetic fixture with a LightDock-shaped schema. "
                "No LightDock executable, source, or third-party output is bundled."
            ),
        )

    def parse_replay_output(self, score_file: Path) -> list[ParsedDockingPose]:
        with score_file.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            columns = set(reader.fieldnames or [])
            missing = REQUIRED_COLUMNS - columns
            if missing:
                raise FixtureIntegrityError(f"docking score 缺少字段: {', '.join(sorted(missing))}")
            poses: list[ParsedDockingPose] = []
            for row_number, row in enumerate(reader, start=2):
                try:
                    pose = ParsedDockingPose(
                        candidate_id=row["candidate_id"],
                        pose_rank=int(row["pose_rank"]),
                        pose_id=row["pose_id"],
                        raw_score=float(row["raw_score"]),
                        score_name=row["score_name"],
                        score_direction=row["score_direction"],
                        complex_path=row["complex_path"],
                        provider=row["provider"],
                        provider_version=row["provider_version"],
                        source_kind=row["source_kind"],
                        tool_execution=row["tool_execution"],
                    )
                except (KeyError, TypeError, ValueError) as exc:
                    raise FixtureIntegrityError(f"docking score 第 {row_number} 行无效") from exc
                if pose.provider != "lightdock":
                    raise FixtureIntegrityError("P0 默认 docking provider 必须声明为 lightdock")
                if pose.score_direction not in {"higher_is_better", "lower_is_better"}:
                    raise FixtureIntegrityError(f"未知 score 方向: {pose.score_direction}")
                if pose.source_kind != "project_authored_synthetic_replay":
                    raise FixtureIntegrityError("P0 fixture 必须明确声明为项目自建合成 Replay 数据")
                if pose.tool_execution != "not_executed":
                    raise FixtureIntegrityError("P0 fixture 不得声称执行了 LightDock")
                if pose.pose_rank < 1 or not pose.candidate_id.startswith("CAND-"):
                    raise FixtureIntegrityError(f"docking pose 标识无效: {pose}")
                poses.append(pose)
        if not poses:
            raise FixtureIntegrityError("docking score 文件没有 pose")
        return sorted(poses, key=lambda item: (item.candidate_id, item.pose_rank))

    def dock(self, *args: object, **kwargs: object) -> list[object]:
        raise LiveCapabilityUnavailable(
            "LightDock Live execution is unavailable in Phase 1 Replay MVP; only verified fixture parsing is implemented."
        )

"""LightDock-shaped Replay parser and an explicit Live capability gate."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path

from labmate.docking.base import DockingProvider
from labmate.errors import FixtureIntegrityError, LiveCapabilityUnavailable
from labmate.models import Capability, CapabilityStatus
from labmate.prediction_artifact import DockingInput

GLOBAL_RANK_METHOD = "lightdock_native_score_cross_swarm_sort_v1"
NATIVE_SCORE_NAME = "fastdfire"
NATIVE_SCORE_DIRECTION = "higher_is_better"
NATIVE_SCORE_SEMANTICS = (
    "LightDock tool-native docking score (fastdfire); higher_is_better; "
    "not affinity"
)

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
    requested_pose_count: int = 1
    generated_pose_count: int = 0
    validated_pose_count: int = 0
    pose_records: list["DockingPoseRecord"] = field(default_factory=list)


@dataclass(frozen=True)
class DockingPoseRecord:
    pose_index: int
    global_tool_score_rank: int
    tool_native_rank: int
    swarm_id: int
    swarm_local_rank: int
    gso_row_id: int
    gso_row: int
    pose_path: str | None
    pose_sha256: str | None
    native_score: float
    raw_native_score: float
    native_score_name: str
    native_score_semantics: str
    global_rank_method: str
    tie_break_fields: list[str]
    generation_status: str
    validation_status: str
    failure_reason: str | None = None
    duplicate_pose_group: str | None = None
    provenance: dict[str, object] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


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


@dataclass(frozen=True)
class _RankedGsoRow:
    global_tool_score_rank: int
    swarm_id: int
    swarm_local_rank: int
    gso_row_id: int
    score: float
    raw_line: str
    source_path: Path
    source_sha256: str
    native_score_name: str
    native_score_semantics: str


@dataclass(frozen=True)
class _UnrankedGsoRow:
    swarm_id: int
    gso_row_id: int
    score: float
    raw_line: str
    source_path: Path
    source_sha256: str
    native_score_name: str
    native_score_semantics: str


def _direction_from_semantics(semantics: str) -> str:
    directions = re.findall(
        r"\b(higher_is_better|lower_is_better)\b", semantics
    )
    if len(directions) != 1:
        raise RuntimeError(
            "LightDock native score semantics must declare exactly one direction"
        )
    return directions[0]


def _rank_gso_rows(rows: list[_UnrankedGsoRow]) -> list[_RankedGsoRow]:
    """Validate one score contract and derive a stable cross-swarm order."""
    if not rows:
        raise RuntimeError("LightDock produced no globally rankable GSO rows")
    score_names = {row.native_score_name for row in rows}
    if len(score_names) != 1:
        raise RuntimeError("LightDock swarms reported inconsistent score names")
    semantics = {row.native_score_semantics for row in rows}
    if len(semantics) != 1:
        raise RuntimeError("LightDock swarms reported inconsistent score semantics")
    direction = _direction_from_semantics(next(iter(semantics)))

    by_swarm: dict[int, list[_UnrankedGsoRow]] = {}
    for row in rows:
        if not math.isfinite(row.score):
            raise RuntimeError(
                f"LightDock native score is not finite in swarm_{row.swarm_id}"
            )
        by_swarm.setdefault(row.swarm_id, []).append(row)

    local_ranks: dict[tuple[int, int], int] = {}
    for swarm_id, swarm_rows in by_swarm.items():
        if len({row.gso_row_id for row in swarm_rows}) != len(swarm_rows):
            raise RuntimeError(f"duplicate LightDock GSO row id in swarm_{swarm_id}")
        local_order = sorted(
            swarm_rows,
            key=(
                (lambda row: (-row.score, row.gso_row_id))
                if direction == "higher_is_better"
                else (lambda row: (row.score, row.gso_row_id))
            ),
        )
        local_ranks.update(
            {
                (swarm_id, row.gso_row_id): rank
                for rank, row in enumerate(local_order, start=1)
            }
        )

    ordered = sorted(
        rows,
        key=(
            (lambda row: (-row.score, row.swarm_id, row.gso_row_id))
            if direction == "higher_is_better"
            else (lambda row: (row.score, row.swarm_id, row.gso_row_id))
        ),
    )
    return [
        _RankedGsoRow(
            global_tool_score_rank=rank,
            swarm_id=row.swarm_id,
            swarm_local_rank=local_ranks[(row.swarm_id, row.gso_row_id)],
            gso_row_id=row.gso_row_id,
            score=row.score,
            raw_line=row.raw_line,
            source_path=row.source_path,
            source_sha256=row.source_sha256,
            native_score_name=row.native_score_name,
            native_score_semantics=row.native_score_semantics,
        )
        for rank, row in enumerate(ordered, start=1)
    ]


def _collect_ranked_gso_rows(
    work: Path,
    *,
    expected_swarms: int,
    steps: int,
    native_score_name: str,
    native_score_semantics: str,
) -> list[_RankedGsoRow]:
    """Collect every current-run swarm and derive a deterministic score order.

    LightDock exposes scores inside each swarm but does not expose one native
    cross-swarm rank.  The returned global rank is therefore a Labmate-derived
    order over a single LightDock scoring function, never a CAPRI/reference
    rank.
    """
    from labmate.live_local import _parse_lightdock_output

    swarm_paths: dict[int, Path] = {}
    for child in work.iterdir():
        if not child.name.startswith("swarm_"):
            continue
        match = re.fullmatch(r"swarm_([0-9]+)", child.name)
        if match is None:
            raise RuntimeError(f"malformed LightDock swarm directory: {child.name}")
        swarm_id = int(match.group(1))
        if child.is_symlink() or not child.is_dir():
            raise RuntimeError(f"LightDock swarm_{swarm_id} is not a regular directory")
        resolved = child.resolve()
        try:
            resolved.relative_to(work.resolve())
        except ValueError as exc:
            raise RuntimeError(f"LightDock swarm_{swarm_id} escaped the run directory") from exc
        if swarm_id in swarm_paths:
            raise RuntimeError(f"duplicate LightDock swarm id: {swarm_id}")
        swarm_paths[swarm_id] = resolved

    expected_ids = set(range(expected_swarms))
    observed_ids = set(swarm_paths)
    if observed_ids != expected_ids:
        missing = sorted(expected_ids - observed_ids)
        extra = sorted(observed_ids - expected_ids)
        raise RuntimeError(
            f"LightDock swarm set mismatch; missing={missing}, unexpected={extra}"
        )

    candidates: list[_UnrankedGsoRow] = []
    for swarm_id in sorted(swarm_paths):
        gso = swarm_paths[swarm_id] / f"gso_{steps}.out"
        if gso.is_symlink() or not gso.is_file():
            raise RuntimeError(f"LightDock GSO output is missing for swarm_{swarm_id}")
        resolved = gso.resolve()
        try:
            resolved.relative_to(work.resolve())
        except ValueError as exc:
            raise RuntimeError(f"LightDock GSO escaped the run directory: swarm_{swarm_id}") from exc
        source_hash = _sha256(resolved)
        try:
            solutions = _parse_lightdock_output(resolved)
        except Exception as exc:
            raise RuntimeError(
                f"LightDock GSO parse failed for swarm_{swarm_id}: "
                f"{type(exc).__name__}"
            ) from exc
        for row in solutions:
            if not math.isfinite(row.score):
                raise RuntimeError(
                    f"LightDock native score is not finite in swarm_{swarm_id}"
                )
            candidates.append(
                _UnrankedGsoRow(
                    swarm_id=swarm_id,
                    gso_row_id=row.glowworm_id,
                    score=row.score,
                    raw_line=row.raw_line,
                    source_path=resolved,
                    source_sha256=source_hash,
                    native_score_name=native_score_name,
                    native_score_semantics=native_score_semantics,
                )
            )
    return _rank_gso_rows(candidates)


def _mark_duplicate_pose_groups(
    records: list[DockingPoseRecord],
) -> list[DockingPoseRecord]:
    hashes: dict[str, list[int]] = {}
    for index, record in enumerate(records):
        if record.pose_sha256:
            hashes.setdefault(record.pose_sha256, []).append(index)
    duplicate_groups = {
        digest: f"duplicate_pose_sha256_{group_index:03d}"
        for group_index, (digest, indices) in enumerate(
            ((digest, indices) for digest, indices in sorted(hashes.items()) if len(indices) > 1),
            start=1,
        )
    }
    return [
        replace(record, duplicate_pose_group=duplicate_groups.get(record.pose_sha256 or ""))
        for record in records
    ]


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

    def execute(self, docking_input: DockingInput, *, allowed_root: Path, output_dir: Path, swarms: int = 1, glowworms: int = 5, steps: int = 5, seed: int = 0, timeout_seconds: int = 1800, poses_per_case: int = 1, cores: int = 1) -> DockingExecutionResult:
        if not 1 <= timeout_seconds <= 3600 or min(swarms, glowworms, steps, poses_per_case, cores) < 1 or poses_per_case > 100:
            raise ValueError("timeout must be 1..3600 and sampling counts/cores/poses_per_case must be 1..100")
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
        exits["sampling"] = self._run([str(self.sampling_executable), "setup.json", str(steps), "-c", str(cores), "-sg", str(seed)], cwd=work, timeout_seconds=timeout_seconds, logs=logs, name="sampling")
        ranked_rows = _collect_ranked_gso_rows(
            work,
            expected_swarms=swarms,
            steps=steps,
            native_score_name=NATIVE_SCORE_NAME,
            native_score_semantics=NATIVE_SCORE_SEMANTICS,
        )
        selected_rows = ranked_rows[:poses_per_case]
        if not selected_rows:
            raise RuntimeError("LightDock produced no globally rankable GSO rows")
        selected = work / "selected_top_poses.gso"
        selected.write_text(
            "\n".join(row.raw_line for row in selected_rows) + "\n",
            encoding="utf-8",
        )
        exits["conformations"] = self._run([str(self.conformation_executable), receptor.name, ligand.name, selected.name, str(len(selected_rows))], cwd=work, timeout_seconds=timeout_seconds, logs=logs, name="conformations")
        # Reuse the established Phase 2a exact chain/residue validator rather
        # than accepting an arbitrary ATOM-bearing PDB as a successful pose.
        from labmate.live_local import _pdb_chain_contract, _validate_lightdock_pose
        receptor_sequences, receptor_keys = _pdb_chain_contract(receptor)
        ligand_sequences, ligand_keys = _pdb_chain_contract(ligand)
        pose_records: list[DockingPoseRecord] = []
        pose_paths: list[str] = []; pose_hashes: dict[str, str] = {}; native: list[dict[str, object]] = []
        for row in selected_rows:
            rank = row.global_tool_score_rank
            generated = work / f"lightdock_{rank - 1}.pdb"
            provenance = {
                "gso_path": _relative(row.source_path, output),
                "gso_sha256": row.source_sha256,
                "global_rank_method": GLOBAL_RANK_METHOD,
                "native_score_name": row.native_score_name,
                "native_score_semantics": row.native_score_semantics,
                "score_direction": _direction_from_semantics(
                    row.native_score_semantics
                ),
            }
            native.append(
                {
                    "global_tool_score_rank": rank,
                    "swarm": row.swarm_id,
                    "swarm_local_rank": row.swarm_local_rank,
                    "gso_row_id": row.gso_row_id,
                    "score": row.score,
                    "score_name": row.native_score_name,
                    "score_direction": _direction_from_semantics(
                        row.native_score_semantics
                    ),
                    "native_score": row.score,
                    "native_score_name": row.native_score_name,
                    "native_score_semantics": row.native_score_semantics,
                }
            )
            if (
                generated.is_symlink()
                or not generated.is_file()
                or generated.stat().st_size == 0
                or b"ATOM" not in generated.read_bytes()
            ):
                pose_records.append(
                    DockingPoseRecord(
                        pose_index=rank,
                        global_tool_score_rank=rank,
                        tool_native_rank=rank,
                        swarm_id=row.swarm_id,
                        swarm_local_rank=row.swarm_local_rank,
                        gso_row_id=row.gso_row_id,
                        gso_row=row.gso_row_id,
                        pose_path=None,
                        pose_sha256=None,
                        native_score=row.score,
                        raw_native_score=row.score,
                        native_score_name=row.native_score_name,
                        native_score_semantics=row.native_score_semantics,
                        global_rank_method=GLOBAL_RANK_METHOD,
                        tie_break_fields=["numeric_swarm_id", "gso_row_id"],
                        generation_status="failed",
                        validation_status="not_run",
                        failure_reason="generated pose was absent, unsafe, empty, or lacked ATOM records",
                        provenance=provenance,
                    )
                )
                continue
            pose = poses / f"pose_{rank:03d}.pdb"
            shutil.copy2(generated, pose)
            try:
                _validate_lightdock_pose(
                    pose,
                    expected_sequences={**receptor_sequences, **ligand_sequences},
                    expected_residue_keys={**receptor_keys, **ligand_keys},
                )
            except Exception as exc:
                pose_records.append(
                    DockingPoseRecord(
                        pose_index=rank,
                        global_tool_score_rank=rank,
                        tool_native_rank=rank,
                        swarm_id=row.swarm_id,
                        swarm_local_rank=row.swarm_local_rank,
                        gso_row_id=row.gso_row_id,
                        gso_row=row.gso_row_id,
                        pose_path=None,
                        pose_sha256=None,
                        native_score=row.score,
                        raw_native_score=row.score,
                        native_score_name=row.native_score_name,
                        native_score_semantics=row.native_score_semantics,
                        global_rank_method=GLOBAL_RANK_METHOD,
                        tie_break_fields=["numeric_swarm_id", "gso_row_id"],
                        generation_status="succeeded",
                        validation_status="failed",
                        failure_reason=f"pose validation failed: {type(exc).__name__}",
                        provenance=provenance,
                    )
                )
                pose.unlink(missing_ok=True)
                continue
            relative_pose = _relative(pose, output)
            pose_sha = _sha256(pose)
            pose_paths.append(relative_pose)
            pose_hashes[relative_pose] = pose_sha
            pose_records.append(
                DockingPoseRecord(
                    pose_index=rank,
                    global_tool_score_rank=rank,
                    tool_native_rank=rank,
                    swarm_id=row.swarm_id,
                    swarm_local_rank=row.swarm_local_rank,
                    gso_row_id=row.gso_row_id,
                    gso_row=row.gso_row_id,
                    pose_path=relative_pose,
                    pose_sha256=pose_sha,
                    native_score=row.score,
                    raw_native_score=row.score,
                    native_score_name=row.native_score_name,
                    native_score_semantics=row.native_score_semantics,
                    global_rank_method=GLOBAL_RANK_METHOD,
                    tie_break_fields=["numeric_swarm_id", "gso_row_id"],
                    generation_status="succeeded",
                    validation_status="validated",
                    provenance=provenance,
                )
            )
        pose_records = _mark_duplicate_pose_groups(pose_records)
        validated_records = [
            record for record in pose_records if record.validation_status == "validated"
        ]
        if not validated_records:
            raise RuntimeError("LightDock produced no validated poses")
        selected_record = min(
            validated_records, key=lambda record: record.global_tool_score_rank
        )
        warnings: list[str] = []
        if selected_record.global_tool_score_rank != 1:
            warnings.append(
                "global_tool_score_rank 1 did not validate; selected the first "
                "validated global_tool_score_rank without renumbering"
            )
        finished = datetime.now(UTC)
        tool_versions = {"lightdock_version": self._version(), "setup_sha256":_sha256(self.setup_executable),"sampling_sha256":_sha256(self.sampling_executable),"conformation_sha256":_sha256(self.conformation_executable)}
        result = DockingExecutionResult(1, "succeeded", "lightdock", "local_external_executable", ".", pose_paths, pose_hashes, native, NATIVE_SCORE_SEMANTICS, selected_record.pose_path, "first_validated_global_tool_score_rank", started.isoformat().replace("+00:00", "Z"), finished.isoformat().replace("+00:00", "Z"), round(time.monotonic()-timer,3), exits, tool_versions, warnings, poses_per_case, sum(record.generation_status == "succeeded" for record in pose_records), len(validated_records), pose_records)
        manifest = {"schema_version":1,"run_id":output.name,"mode":"local_docking_execution","status":result.status,"prediction_backend":docking_input.antibody_artifact.backend_name,"prediction_pdb_sha256":docking_input.antibody_artifact.pdb_sha256,"antibody_chain_map":docking_input.antibody_artifact.chain_map,"antigen_sha256":docking_input.antigen_pdb_sha256,"antigen_chains":docking_input.antigen_chains,"receptor_role":docking_input.receptor_role,"ligand_role":docking_input.ligand_role,"docking_backend":"lightdock","tool_version":tool_versions["lightdock_version"],"parameters":{"swarms":swarms,"glowworms":glowworms,"gso_steps":steps,"seed":seed,"timeout_seconds":timeout_seconds,"poses_per_case":poses_per_case,"cores":cores},"global_rank_method":GLOBAL_RANK_METHOD,"global_rank_is_lightdock_native_rank":False,"tie_break_fields":["numeric_swarm_id","gso_row_id"],"normalized_inputs":{"receptor":_relative(receptor,output),"ligand":_relative(ligand,output),"receptor_sha256":_sha256(receptor),"ligand_sha256":_sha256(ligand)},"exit_codes":exits,"pose_count":len(pose_records),"generated_pose_count":result.generated_pose_count,"validated_pose_count":result.validated_pose_count,"unique_validated_pose_count":len({record.pose_sha256 for record in validated_records}),"pose_paths":result.pose_paths,"pose_sha256":result.pose_sha256,"native_scores":native,"pose_records":[record.__dict__ for record in pose_records],"selected_pose":result.selected_pose,"selected_pose_reason":result.selected_pose_reason,"warnings":result.warnings,"validation_steps":["input_sha256","regular_files","all_expected_swarm_directories","single_native_score_contract","gso_sha256","global_tool_score_rank","pose_atom_records","exact_chain_sequence"],"unsupported_claims":["no LightDock-native cross-swarm rank","no scientific docking validation","no affinity prediction","no experimental validation","no epitope validation","no cross-backend confidence comparison","no therapeutic claim"]}
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

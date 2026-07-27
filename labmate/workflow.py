"""End-to-end Phase 1 Replay workflow."""

from __future__ import annotations

import csv
import json
import platform
import re
import shutil
import uuid
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from labmate import __version__
from labmate.analysis.interface import analyze_interfaces
from labmate.analysis.ranking import build_candidate_metrics, rank_candidates
from labmate.config import DEFAULT_INTERFACE_CONFIG, SCIENTIFIC_LIMITATION
from labmate.docking.lightdock import LightDockProvider, ParsedDockingPose
from labmate.errors import FixtureIntegrityError
from labmate.models import (
    ArtifactRecord,
    Capability,
    CapabilityStatus,
    JobSpec,
    Manifest,
    RunResult,
    StageStatus,
)
from labmate.provenance import (
    artifact_record,
    build_input_hashes,
    safe_relative_path,
    sha256_file,
)
from labmate.reporting.builder import build_report
from labmate.state import StageStateMachine
from labmate.validators.antigen import THREE_TO_ONE, PDBParseResult, parse_antigen_pdb, parse_complex_pdb
from labmate.validators.cdr import STANDARD_AMINO_ACIDS


def _utc_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _run_id() -> str:
    now = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return f"RUN-{now}-{uuid.uuid4().hex[:8]}"


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _hash_map(paths: list[Path], root: Path) -> dict[str, str]:
    return {path.relative_to(root).as_posix(): sha256_file(path) for path in paths}


def _parse_fasta(path: Path) -> dict[str, dict[str, str]]:
    records: dict[str, str] = {}
    current: str | None = None
    chunks: list[str] = []
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        if line.startswith(">"):
            if current is not None:
                if current in records:
                    raise FixtureIntegrityError(f"FASTA 标题重复: {current}")
                records[current] = "".join(chunks)
            current = line[1:].strip()
            if not current:
                raise FixtureIntegrityError(f"FASTA 第 {line_number} 行标题为空")
            chunks = []
        elif current is None:
            raise FixtureIntegrityError(f"FASTA 第 {line_number} 行缺少标题")
        else:
            chunks.append(line.upper())
    if current is not None:
        if current in records:
            raise FixtureIntegrityError(f"FASTA 标题重复: {current}")
        records[current] = "".join(chunks)
    candidates: dict[str, dict[str, str]] = {}
    for header, sequence in records.items():
        try:
            candidate_id, chain_name = header.split("|", 1)
        except ValueError as exc:
            raise FixtureIntegrityError(f"FASTA 标题格式无效: {header}") from exc
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", candidate_id):
            raise FixtureIntegrityError(f"FASTA candidate ID 不安全: {candidate_id!r}")
        chain = {"VH": "H", "VL": "L"}.get(chain_name)
        if chain is None:
            raise FixtureIntegrityError(f"FASTA 链标签无效: {chain_name}")
        if not sequence or set(sequence) - STANDARD_AMINO_ACIDS:
            raise FixtureIntegrityError(f"{header} 含空序列或非法残基")
        if chain in candidates.setdefault(candidate_id, {}):
            raise FixtureIntegrityError(f"FASTA 候选链重复: {candidate_id}|{chain_name}")
        candidates[candidate_id][chain] = sequence
    if not candidates or any(set(chains) != {"H", "L"} for chains in candidates.values()):
        raise FixtureIntegrityError("每个候选必须同时包含 VH 与 VL")
    if len({(chains["H"], chains["L"]) for chains in candidates.values()}) != len(candidates):
        raise FixtureIntegrityError("fixture 含完全重复候选")
    return candidates


def _validate_candidate_regions(job: JobSpec, path: Path, candidates: dict[str, dict[str, str]]) -> None:
    rows = _read_csv(path)
    observed: dict[tuple[str, str], str] = {}
    assembled: dict[tuple[str, str], list[str]] = {}
    for row in rows:
        key = (row.get("candidate_id", ""), row.get("region", ""))
        if key in observed:
            raise FixtureIntegrityError(f"重复 candidate region: {key}")
        observed[key] = row.get("sequence", "")
        if row.get("source_kind") != "project_authored_synthetic_replay":
            raise FixtureIntegrityError("候选 region 未声明合成 Replay 来源")
        chain = row.get("chain", "")
        if chain not in {"H", "L"}:
            raise FixtureIntegrityError(f"候选 region 链无效: {chain}")
        assembled.setdefault((row["candidate_id"], chain), []).append(row.get("sequence", ""))
    if {candidate_id for candidate_id, _ in assembled} != set(candidates):
        raise FixtureIntegrityError("candidate region ID set 与 FASTA 不一致")
    for candidate_id in candidates:
        for region, expected in job.antibody.region_map().items():
            actual = observed.get((candidate_id, region))
            if actual != expected:
                raise FixtureIntegrityError(f"{candidate_id} 未逐字符保留 {region}")
        for chain in ("H", "L"):
            if "".join(assembled.get((candidate_id, chain), [])) != candidates[candidate_id][chain]:
                raise FixtureIntegrityError(f"{candidate_id} {chain} region 拼接与 FASTA 不一致")


def _chain_sequence(parsed: PDBParseResult, chain_id: str) -> str:
    residues = list(dict.fromkeys(atom.residue for atom in parsed.atoms if atom.residue.chain_id == chain_id))
    return "".join(THREE_TO_ONE[residue.residue_name] for residue in residues)


def _validate_structure_sequence_map(pdb_path: Path, map_path: Path, candidate_id: str) -> PDBParseResult:
    parsed = parse_complex_pdb(pdb_path.read_bytes())
    try:
        sequence_map = json.loads(map_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise FixtureIntegrityError(f"{candidate_id} sequence_map.json 无效") from exc
    if sequence_map.get("mapping_verified") is not True:
        raise FixtureIntegrityError(f"{candidate_id} sequence map 未验证")
    for chain_id in ("H", "L"):
        chain_data = sequence_map.get("chains", {}).get(chain_id)
        if not isinstance(chain_data, dict):
            raise FixtureIntegrityError(f"{candidate_id} sequence map 缺少 {chain_id}")
        pdb_sequence = _chain_sequence(parsed, chain_id)
        expected_sequence = chain_data.get("sequence")
        residue_rows = chain_data.get("residues")
        if pdb_sequence != expected_sequence:
            raise FixtureIntegrityError(f"{candidate_id} {chain_id} PDB 序列与 sequence map 不一致")
        if not isinstance(residue_rows, list) or len(residue_rows) != len(pdb_sequence):
            raise FixtureIntegrityError(f"{candidate_id} {chain_id} residue mapping 长度不一致")
        for position, (amino_acid, row) in enumerate(zip(pdb_sequence, residue_rows, strict=True), start=1):
            if (
                row.get("pdb_residue_number") != position
                or row.get("sequence_position") != position
                or row.get("amino_acid") != amino_acid
                or not row.get("region")
            ):
                raise FixtureIntegrityError(f"{candidate_id} {chain_id} residue mapping 在位置 {position} 错位")
    return parsed


def _copy_tree(source: Path, destination: Path) -> list[Path]:
    if destination.exists():
        raise FixtureIntegrityError(f"目标目录已存在: {destination.name}")
    shutil.copytree(source, destination)
    return [path for path in destination.rglob("*") if path.is_file()]


def _artifact_role(relative: Path, *, execution_mode: str = "replay") -> str:
    if relative.name == "report.html":
        return "offline_report"
    if relative.name == "candidate_ranking.csv":
        return "candidate_ranking"
    if relative.name == "interface_residues.csv":
        return "interface_residues"
    if relative.name == "candidates.fasta":
        return "candidate_sequences"
    if relative.parts[0] == "inputs":
        return "validated_input"
    if relative.parts[0] == "docking":
        return (
            "replay_docking_artifact"
            if execution_mode == "replay"
            else "live_local_docking_artifact"
        )
    if relative.parts[0] == "structures":
        return (
            "replay_structure_artifact"
            if execution_mode == "replay"
            else "live_local_structure_artifact"
        )
    if relative.parts[0] == "analysis":
        return (
            "local_replay_analysis"
            if execution_mode == "replay"
            else "local_live_analysis"
        )
    if relative.parts[0] == "ranking":
        return (
            "local_replay_ranking"
            if execution_mode == "replay"
            else "local_live_ranking"
        )
    if relative.parts[0] == "logs":
        return "run_log"
    return "run_artifact"


def _collect_artifacts(
    run_dir: Path, *, execution_mode: str = "replay"
) -> list[ArtifactRecord]:
    records: list[ArtifactRecord] = []
    for path in sorted(run_dir.rglob("*")):
        if not path.is_file() or path.name in {"manifest.json", "manifest.sha256"}:
            continue
        relative = path.relative_to(run_dir)
        records.append(
            artifact_record(
                path,
                run_dir,
                role=_artifact_role(relative, execution_mode=execution_mode),
            )
        )
    return records


def _safe_zip(run_dir: Path, zip_path: Path) -> None:
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(run_dir.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(run_dir)
            safe_relative_path(relative.as_posix())
            archive.write(path, arcname=relative.as_posix())


def execute_replay(*, job: JobSpec, antigen_bytes: bytes, fixture_root: Path, output_root: Path) -> RunResult:
    """Execute parser/analysis/ranking/reporting over a verified fixed fixture."""

    output_root = output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    run_id = _run_id()
    run_dir = output_root / run_id
    run_dir.mkdir(parents=False, exist_ok=False)
    for directory in ("inputs", "candidates", "structures", "docking", "analysis", "ranking", "figures", "logs"):
        (run_dir / directory).mkdir()

    fixture_manifest_path = fixture_root / "fixture_manifest.json"
    fixture_manifest_hash = sha256_file(fixture_manifest_path)
    fixture_manifest = json.loads(fixture_manifest_path.read_text(encoding="utf-8"))
    input_hashes = build_input_hashes(job, antigen_bytes)
    state = StageStateMachine(fixture_id=job.fixture_id, fixture_manifest_hash=fixture_manifest_hash)
    log_lines = [f"{_utc_iso()} REPLAY run {run_id} initialized", "REPLAY: no scientific external tool execution"]

    state.start("S00", input_hashes=input_hashes, notes=["REPLAY label fixed for the entire run"])
    sanitized_job = job.model_dump(mode="json")
    sanitized_job["antigen"]["file"] = "inputs/antigen_original.pdb"  # type: ignore[index]
    _write_json(run_dir / "job.json", sanitized_job)
    state.succeed("S00", output_hashes=_hash_map([run_dir / "job.json"], run_dir))

    state.start("S01", input_hashes=input_hashes, notes=["PDB parsed locally; fixture inputs already hash-matched"])
    original_pdb = run_dir / "inputs" / "antigen_original.pdb"
    original_pdb.write_bytes(antigen_bytes)
    antigen = parse_antigen_pdb(antigen_bytes, selected_chains=job.antigen.chains)
    cleaned_pdb = run_dir / "inputs" / "antigen_cleaned.pdb"
    cleaned_pdb.write_text(antigen.cleaned_pdb, encoding="utf-8")
    mapping_path = run_dir / "inputs" / "antigen_residue_mapping.json"
    _write_json(
        mapping_path,
        {
            "selected_model": antigen.selected_model,
            "altloc_rule": "blank_then_A",
            "chains": antigen.chains,
            "residue_mapping": antigen.residue_mapping,
            "removed": {
                "hetero_atoms": antigen.removed_hetero_atoms,
                "nonstandard_atoms": antigen.removed_nonstandard_atoms,
                "altloc_atoms": antigen.removed_altloc_atoms,
                "ignored_model_atoms": antigen.ignored_model_atoms,
            },
            "warnings": antigen.warnings,
        },
    )
    state.succeed("S01", output_hashes=_hash_map([original_pdb, cleaned_pdb, mapping_path], run_dir))

    state.start(
        "S02",
        input_hashes=input_hashes,
        notes=["Copied fixed project-authored synthetic candidate artifacts; IgCraft not executed"],
    )
    candidate_files = _copy_tree(fixture_root / "igcraft_output", run_dir / "candidates" / "fixture_output")
    fasta_source = run_dir / "candidates" / "fixture_output" / "candidates.fasta"
    regions_source = run_dir / "candidates" / "fixture_output" / "candidates_regions.csv"
    root_fasta = run_dir / "candidates.fasta"
    shutil.copy2(fasta_source, root_fasta)
    candidates = _parse_fasta(root_fasta)
    if len(candidates) != job.antibody.candidate_count:
        raise FixtureIntegrityError("candidate_count 与 fixture 不一致")
    state.succeed("S02", output_hashes=_hash_map(candidate_files + [root_fasta], run_dir))

    state.start(
        "S03",
        input_hashes={"candidates_fasta_sha256": sha256_file(root_fasta), "antibody_sha256": input_hashes["antibody_sha256"]},
        notes=["CDR preservation and candidate uniqueness checked locally"],
    )
    _validate_candidate_regions(job, regions_source, candidates)
    rejected_path = run_dir / "candidates" / "rejected_candidates.csv"
    rejected_path.write_text("candidate_id,rejected_reason\n", encoding="utf-8")
    state.succeed("S03", output_hashes=_hash_map([regions_source, rejected_path], run_dir))

    state.start(
        "S04",
        input_hashes={"candidates_fasta_sha256": sha256_file(root_fasta)},
        notes=["Copied fixed project-authored synthetic structure artifacts; ColabFold not executed"],
    )
    structure_files = _copy_tree(fixture_root / "colabfold_output", run_dir / "structures" / "fixture_output")
    # Promote the uniform candidate directories into structures/CAND-* for downstream mapping.
    promoted_structure_files: list[Path] = []
    for candidate_id in sorted(candidates):
        destination = run_dir / "structures" / candidate_id
        promoted_structure_files.extend(
            _copy_tree(run_dir / "structures" / "fixture_output" / candidate_id, destination)
        )
    structure_metrics_path = run_dir / "structures" / "structure_metrics.csv"
    shutil.copy2(run_dir / "structures" / "fixture_output" / "structure_metrics.csv", structure_metrics_path)
    state.succeed(
        "S04",
        output_hashes=_hash_map(structure_files + promoted_structure_files + [structure_metrics_path], run_dir),
    )

    state.start(
        "S05",
        input_hashes={"structure_metrics_sha256": sha256_file(structure_metrics_path)},
        notes=["Checked both-chain PDB sequence mapping and synthetic metric schema locally"],
    )
    structure_rows = _read_csv(structure_metrics_path)
    metric_ids = {row["candidate_id"] for row in structure_rows}
    if metric_ids != set(candidates):
        raise FixtureIntegrityError("structure metrics candidate set 不一致")
    for row in structure_rows:
        if row.get("source_kind") != "project_authored_synthetic_replay" or row.get("tool_execution") != "not_executed":
            raise FixtureIntegrityError("structure metric provenance 声明无效")
        candidate_id = row["candidate_id"]
        parsed_structure = _validate_structure_sequence_map(
            run_dir / "structures" / candidate_id / "ranked_1.pdb",
            run_dir / "structures" / candidate_id / "sequence_map.json",
            candidate_id,
        )
        if not {"H", "L"}.issubset(set(parsed_structure.chains)):
            raise FixtureIntegrityError(f"{candidate_id} structure 缺少 VH/VL 链")
    state.succeed("S05", output_hashes=_hash_map([structure_metrics_path], run_dir))

    state.start(
        "S06",
        input_hashes={
            "antigen_cleaned_sha256": sha256_file(cleaned_pdb),
            "structure_metrics_sha256": sha256_file(structure_metrics_path),
        },
        notes=["Parsed fixed synthetic docking schema; LightDock executable was not installed or invoked"],
    )
    docking_files = _copy_tree(fixture_root / "docking_output", run_dir / "docking" / "fixture_output")
    # Keep paths in docking_scores.csv relative to the promoted docking root.
    promoted_docking_files: list[Path] = []
    for candidate_id in sorted(candidates):
        promoted_docking_files.extend(
            _copy_tree(
                run_dir / "docking" / "fixture_output" / candidate_id,
                run_dir / "docking" / candidate_id,
            )
        )
    docking_score_path = run_dir / "docking" / "docking_scores.csv"
    docking_manifest_path = run_dir / "docking" / "docking_manifest.json"
    shutil.copy2(run_dir / "docking" / "fixture_output" / "docking_scores.csv", docking_score_path)
    shutil.copy2(run_dir / "docking" / "fixture_output" / "docking_manifest.json", docking_manifest_path)
    provider = LightDockProvider()
    docking_poses = provider.parse_replay_output(docking_score_path)
    if {pose.candidate_id for pose in docking_poses} != set(candidates):
        raise FixtureIntegrityError("docking candidate set 不一致")
    for pose in docking_poses:
        pose_relative = safe_relative_path(pose.complex_path)
        pose_path = (run_dir / "docking" / pose_relative).resolve()
        try:
            pose_path.relative_to((run_dir / "docking").resolve())
        except ValueError as exc:
            raise FixtureIntegrityError(f"pose path traversal: {pose.complex_path}") from exc
        parsed_pose = parse_complex_pdb(pose_path.read_bytes())
        if not {"A", "H", "L"}.issubset(set(parsed_pose.chains)):
            raise FixtureIntegrityError(f"{pose.pose_id} complex 链不完整")
        if _chain_sequence(parsed_pose, "A") != _chain_sequence(antigen, "A"):
            raise FixtureIntegrityError(f"{pose.pose_id} antigen 链序列与输入不一致")
        if _chain_sequence(parsed_pose, "H") != candidates[pose.candidate_id]["H"]:
            raise FixtureIntegrityError(f"{pose.pose_id} VH 链序列与候选不一致")
        if _chain_sequence(parsed_pose, "L") != candidates[pose.candidate_id]["L"]:
            raise FixtureIntegrityError(f"{pose.pose_id} VL 链序列与候选不一致")
    state.succeed(
        "S06",
        output_hashes=_hash_map(
            docking_files + promoted_docking_files + [docking_score_path, docking_manifest_path], run_dir
        ),
    )

    state.start(
        "S07",
        input_hashes={"docking_scores_sha256": sha256_file(docking_score_path)},
        notes=["Geometry recomputed locally from verified poses; PyMOL not required"],
    )
    analysis_result = analyze_interfaces(
        docking_poses,
        docking_root=run_dir / "docking",
        structures_root=run_dir / "structures",
        output_dir=run_dir / "analysis",
        config=DEFAULT_INTERFACE_CONFIG,
    )
    interface_root = run_dir / "interface_residues.csv"
    shutil.copy2(run_dir / "analysis" / "interface_residues.csv", interface_root)
    analysis_files = [path for path in (run_dir / "analysis").iterdir() if path.is_file()] + [interface_root]
    state.succeed("S07", output_hashes=_hash_map(analysis_files, run_dir), notes=analysis_result["warnings"])

    state.start(
        "S08",
        input_hashes={
            "structure_metrics_sha256": sha256_file(structure_metrics_path),
            "docking_scores_sha256": sha256_file(docking_score_path),
            "pose_consensus_sha256": sha256_file(run_dir / "analysis" / "pose_consensus.csv"),
        },
        notes=["Within-run min-max normalization and heuristic ranking recomputed locally"],
    )
    candidate_metrics, docking_higher_is_better = build_candidate_metrics(
        structure_metrics_path=structure_metrics_path,
        docking_poses=docking_poses,
        pose_consensus_path=run_dir / "analysis" / "pose_consensus.csv",
    )
    ranking_result = rank_candidates(
        candidate_metrics,
        docking_higher_is_better=docking_higher_is_better,
        output_dir=run_dir / "ranking",
    )
    ranking_root = run_dir / "candidate_ranking.csv"
    shutil.copy2(run_dir / "ranking" / "candidate_ranking.csv", ranking_root)
    ranking_files = [path for path in (run_dir / "ranking").iterdir() if path.is_file()] + [ranking_root]
    state.succeed("S08", output_hashes=_hash_map(ranking_files, run_dir), notes=ranking_result["warnings"])

    state.skip_optional("S09", note="PyMOL not invoked; visualization is optional and no placeholder image was created")
    (run_dir / "figures" / "README.txt").write_text(
        "REPLAY: visualization skipped_optional. No PyMOL call and no placeholder image.\n",
        encoding="utf-8",
    )

    warnings = list(
        dict.fromkeys(
            fixture_manifest.get("warnings", [])
            + antigen.warnings
            + analysis_result["warnings"]
            + ranking_result["warnings"]
        )
    )
    log_lines.extend(f"{_utc_iso()} {record.stage_id} {record.status}" for record in state.records)
    (run_dir / "logs" / "replay.log").write_text("\n".join(log_lines) + "\n", encoding="utf-8")

    state.start(
        "S10",
        input_hashes={
            "candidate_ranking_sha256": sha256_file(ranking_root),
            "interface_residues_sha256": sha256_file(interface_root),
        },
        notes=["Single-file offline HTML generated locally with persistent REPLAY label"],
    )
    state.succeed("S10")
    pre_report_artifacts = _collect_artifacts(run_dir)
    antigen_summary = {
        "chains": antigen.chains,
        "atom_count": len(antigen.atoms),
        "residue_count": antigen.residue_count,
        "selected_model": antigen.selected_model,
    }
    docking_rows = [pose.__dict__ for pose in docking_poses]
    build_report(
        run_dir / "report.html",
        run_id=run_id,
        created_at=_utc_iso(),
        job=job,
        input_hashes=input_hashes,
        fixture_manifest_hash=fixture_manifest_hash,
        antigen_summary=antigen_summary,
        stages=state.records,
        structure_rows=structure_rows,
        docking_rows=docking_rows,
        ranking_rows=ranking_result["rows"],
        interface_rows=analysis_result["interface_residues"],
        consensus_rows=analysis_result["pose_consensus"],
        sensitivity_rows=ranking_result["sensitivity"],
        warnings=warnings,
        artifact_preview=[item.model_dump(mode="json") for item in pre_report_artifacts[:30]],
    )
    state.records[-1].output_hashes = _hash_map([run_dir / "report.html"], run_dir)

    artifacts = _collect_artifacts(run_dir)
    project_root = Path(__file__).resolve().parents[1]
    dependency_spec = project_root / "requirements.lock"
    if not dependency_spec.is_file():
        dependency_spec = project_root / "pyproject.toml"
    replay_capability = Capability(
        name="ReplayBackend",
        status=CapabilityStatus.REPLAY_ONLY,
        enabled=True,
        provider="fixture:demo_001",
        version="1.0.0",
        license_status="CC0-1.0 fixture",
        reason="Exact input and artifact hashes verified before replay.",
    )
    manifest = Manifest(
        run_id=run_id,
        created_at=datetime.now(UTC),
        input_hashes=input_hashes,
        parameters={
            "candidate_count": job.antibody.candidate_count,
            "random_seed": job.antibody.random_seed,
            "numbering_scheme": job.antibody.numbering_scheme,
            "interface": {
                "contact_cutoff_angstrom": DEFAULT_INTERFACE_CONFIG.contact_cutoff_angstrom,
                "polar_contact_cutoff_angstrom": DEFAULT_INTERFACE_CONFIG.polar_contact_cutoff_angstrom,
                "ionic_contact_cutoff_angstrom": DEFAULT_INTERFACE_CONFIG.ionic_contact_cutoff_angstrom,
                "severe_clash_cutoff_angstrom": DEFAULT_INTERFACE_CONFIG.severe_clash_cutoff_angstrom,
                "analyze_top_poses": DEFAULT_INTERFACE_CONFIG.analyze_top_poses,
            },
            "ranking_weights": {"structure": 0.35, "docking": 0.45, "interface": 0.20},
        },
        tools={
            "antibody_labmate": {"version": __version__, "commit": "not-a-git-checkout"},
            "python": {"runtime": platform.python_version(), "supported": "3.11-3.12"},
            "dependency_spec_sha256": sha256_file(dependency_spec),
            "igcraft": {"version": "not-installed-not-run", "execution": "not_executed"},
            "colabfold": {"version": "not-installed-not-run", "execution": "not_executed"},
            "lightdock": {"version": "not-installed-not-run", "execution": "not_executed"},
            "pymol": {"version": "not-installed-not-run", "execution": "skipped_optional"},
        },
        models={
            "igcraft_checkpoint": "not-present-not-run",
            "colabfold_model": "not-present-not-run",
            "docking_fixture_schema": "project-authored-synthetic-v1",
        },
        capabilities={
            "replay": replay_capability,
            "live_local": Capability(
                name="Live Local",
                status=CapabilityStatus.UNAVAILABLE,
                enabled=False,
                reason="This Replay run does not invoke Live Local; the separate local CLI adapter has its own verified_live validation scope.",
            ),
            "live_remote": Capability(
                name="Live Remote",
                status=CapabilityStatus.UNAVAILABLE,
                enabled=False,
                reason="Phase 3 API/worker/auth/isolation is not implemented.",
            ),
            "lightdock_provider": provider.preflight(),
        },
        licenses={
            "project_code": "MIT",
            "demo_fixture": "CC0-1.0",
            "lightdock": "GPL-3.0 external project; not bundled or executed",
            "hdock": "not included; unavailable without a separate written-license gate",
        },
        chain_mappings={
            "antigen": {"input": job.antigen.chains, "docking": ["A"]},
            "antibody": {"VH": "H", "VL": "L"},
            "mapping_status": "verified_fixture",
        },
        stages=state.records,
        artifacts=artifacts,
        warnings=warnings,
        limitations=[
            SCIENTIFIC_LIMITATION,
            "All demo sequences, coordinates, confidence metrics, docking scores, and poses are synthetic test data.",
            "This Replay run did not invoke Live Local or Live Remote; Live Local has a separate CLI validation record.",
            "CDR syntax validation cannot prove IMGT annotation, framework compatibility, folding, or binding.",
            "Ranking is a within-run product heuristic, not a calibrated biological predictor.",
        ],
        fixture_id=job.fixture_id,
        fixture_manifest_hash=fixture_manifest_hash,
    )
    manifest_path = run_dir / "manifest.json"
    _write_json(manifest_path, manifest.model_dump(mode="json"))
    manifest_hash = sha256_file(manifest_path)
    (run_dir / "manifest.sha256").write_text(f"{manifest_hash}  manifest.json\n", encoding="utf-8")

    zip_path = output_root / f"{run_id}.zip"
    _safe_zip(run_dir, zip_path)
    return RunResult(
        run_id=run_id,
        run_dir=str(run_dir),
        zip_path=str(zip_path),
        manifest_path=str(manifest_path),
        report_path=str(run_dir / "report.html"),
        stages=state.records,
    )


def load_project(project_path: Path) -> tuple[JobSpec, bytes]:
    """Load the JSON-compatible project.yaml used by the verified demo."""

    project_path = project_path.resolve()
    try:
        payload = json.loads(project_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FixtureIntegrityError("Phase 1 project.yaml 必须是 JSON-compatible YAML") from exc
    job = JobSpec.model_validate(payload)
    antigen_relative = safe_relative_path(job.antigen.file)
    antigen_path = (project_path.parent / antigen_relative).resolve()
    try:
        antigen_path.relative_to(project_path.parent.resolve())
    except ValueError as exc:
        raise FixtureIntegrityError("antigen file 路径越界") from exc
    if not antigen_path.is_file():
        raise FixtureIntegrityError(f"antigen PDB 不存在: {job.antigen.file}")
    return job, antigen_path.read_bytes()

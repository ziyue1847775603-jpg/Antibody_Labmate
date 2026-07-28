"""Local PDB-to-LightDock benchmark mode.

The workflow is deliberately separate from Replay and Live Local: it never
accepts FASTA, never invokes ColabFold, and never performs network I/O.  All
scientific executables are supplied and licensed by the user.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import platform
import re
import shutil
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

from labmate import __version__
from labmate.config import DEFAULT_INTERFACE_CONFIG, SCIENTIFIC_LIMITATION
from labmate.errors import InputValidationError, LabmateError
from labmate.live_local import (
    LightDockSolution,
    _audit_run_privacy,
    _chain_sequence,
    _command_path,
    _lightdock_version,
    _ordered_residues,
    _pdb_chain_contract,
    _redact_text,
    _rewrite_chains,
    _run,
    _sanitize_run_metadata,
    _select_lightdock_solutions,
)
from labmate.models import BenchmarkLocalJobSpec, RunResult
from labmate.provenance import safe_relative_path, sha256_file
from labmate.reporting.builder import build_benchmark_report
from labmate.validators.antigen import AtomRecord, PDBParseResult, ResidueKey, parse_antigen_pdb, parse_complex_pdb
from labmate.workflow import _collect_artifacts, _run_id, _safe_zip, _write_json

BENCHMARK_STATUS = "implemented_unverified"
REAL_SMOKE_VALIDATION_RECORD = "BENCHMARK_LOCAL_VALIDATION.md"
NATIVE_CONTACT_CUTOFF_ANGSTROM = 5.0
BACKBONE_ATOMS = frozenset({"N", "CA", "C", "O"})


def _resolve_local(project_dir: Path, value: str, label: str) -> Path:
    if "://" in value or value.lower().startswith(("http:", "https:", "ftp:")):
        raise InputValidationError(f"{label} 只接受本地路径，URL 被拒绝")
    try:
        relative = safe_relative_path(value)
    except Exception as exc:
        raise InputValidationError(f"{label} 必须是项目目录内的安全相对路径") from exc
    path = (project_dir / relative).resolve()
    try:
        path.relative_to(project_dir.resolve())
    except ValueError as exc:
        raise InputValidationError(f"{label} 路径越界") from exc
    if not path.is_file():
        raise InputValidationError(f"{label} 不存在: {value}")
    return path


def load_benchmark_local_project(
    project_path: Path,
) -> tuple[BenchmarkLocalJobSpec, Path, Path, Path | None, Path]:
    project_path = project_path.resolve()
    try:
        payload = json.loads(project_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InputValidationError(
            "Benchmark Local project.json 必须是 JSON"
        ) from exc
    job = BenchmarkLocalJobSpec.model_validate(payload)
    root = project_path.parent
    output_relative = safe_relative_path(job.output_dir)
    output_dir = (root / output_relative).resolve()
    try:
        output_dir.relative_to(root.resolve())
    except ValueError as exc:
        raise InputValidationError("output_dir 路径越界") from exc
    return (
        job,
        _resolve_local(root, job.antibody_pdb, "antibody_pdb"),
        _resolve_local(root, job.antigen_pdb, "antigen_pdb"),
        (
            _resolve_local(root, job.reference_complex_pdb, "reference_complex_pdb")
            if job.reference_complex_pdb
            else None
        ),
        output_dir,
    )


def _strict_pdb_audit(
    data: bytes, *, selected_chains: Iterable[str], label: str
) -> PDBParseResult:
    """Parse selected chains and reject ambiguous residue/atom identities."""
    selected = set(selected_chains)
    if not selected:
        raise InputValidationError(f"{label} 链映射为空")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InputValidationError(f"{label} 必须是 UTF-8/ASCII PDB") from exc
    parsed = parse_antigen_pdb(data, selected_chains=list(selected))
    if parsed.model_count > 1 or parsed.ignored_model_atoms:
        raise InputValidationError(f"{label} 不得包含多个 MODEL 或 MODEL 外 ATOM")
    if set(parsed.chains) != selected:
        raise InputValidationError(f"{label} 链集合无法完整映射")
    residue_names: dict[tuple[str, int, str], str] = {}
    atom_keys: set[tuple[str, int, str, str, str]] = set()
    closed_residues: set[tuple[str, int, str]] = set()
    active_residue: tuple[str, int, str] | None = None
    for line_number, raw in enumerate(text.splitlines(), start=1):
        line = raw.ljust(80)
        if line[0:6].strip().upper() != "ATOM":
            continue
        chain = line[21].strip() or "_"
        if chain not in selected:
            continue
        altloc = line[16].strip()
        if altloc:
            raise InputValidationError(
                f"{label} 第 {line_number} 行存在不允许的 altloc {altloc!r}"
            )
        try:
            number = int(line[22:26].strip())
        except ValueError as exc:
            raise InputValidationError(
                f"{label} 第 {line_number} 行残基编号无效"
            ) from exc
        insertion = line[26].strip()
        residue_name = line[17:20].strip().upper()
        residue_key = (chain, number, insertion)
        if residue_key != active_residue:
            if active_residue is not None:
                closed_residues.add(active_residue)
            if residue_key in closed_residues:
                raise InputValidationError(
                    f"{label} 第 {line_number} 行存在非连续重复 residue key"
                )
            active_residue = residue_key
        previous = residue_names.setdefault(residue_key, residue_name)
        if previous != residue_name:
            raise InputValidationError(
                f"{label} 第 {line_number} 行重复 residue key 对应不同残基"
            )
        atom_key = (*residue_key, residue_name, line[12:16].strip().upper())
        if atom_key in atom_keys:
            raise InputValidationError(
                f"{label} 第 {line_number} 行存在重复原子/残基记录"
            )
        atom_keys.add(atom_key)
    residues = list(dict.fromkeys(atom.residue for atom in parsed.atoms))
    ca_residues = {
        atom.residue for atom in parsed.atoms if atom.name.strip().upper() == "CA"
    }
    missing_ca = [residue.display_number for residue in residues if residue not in ca_residues]
    if missing_ca:
        raise InputValidationError(
            f"{label} 存在无 CA 的残基: {', '.join(missing_ca[:8])}"
        )
    return parsed


def _normalized_structure(
    source: Path,
    *,
    mapping: dict[str, str],
    original_copy: Path,
    normalized_path: Path,
    label: str,
) -> tuple[PDBParseResult, dict[str, Any]]:
    data = source.read_bytes()
    parsed = _strict_pdb_audit(data, selected_chains=mapping, label=label)
    original_copy.write_bytes(data)
    selected = normalized_path.with_suffix(".selected.pdb")
    selected.write_text(parsed.cleaned_pdb, encoding="utf-8")
    _rewrite_chains(selected, normalized_path, mapping)
    selected.unlink()
    normalized = _strict_pdb_audit(
        normalized_path.read_bytes(),
        selected_chains=mapping.values(),
        label=f"{label} normalized",
    )
    source_sequences = {
        chain: _chain_sequence(parsed, chain) for chain in parsed.chains
    }
    normalized_sequences = {
        chain: _chain_sequence(normalized, chain) for chain in normalized.chains
    }
    for source_chain, target_chain in mapping.items():
        if source_sequences[source_chain] != normalized_sequences[target_chain]:
            raise InputValidationError(f"{label} 标准化后序列未逐字符保留")
    mapping_rows = []
    for row in parsed.residue_mapping:
        if row["original_chain"] in mapping:
            mapping_rows.append(
                {
                    **row,
                    "normalized_chain": mapping[str(row["original_chain"])],
                }
            )
    return normalized, {
        "source_file_sha256": hashlib.sha256(data).hexdigest(),
        "normalized_file_sha256": sha256_file(normalized_path),
        "chain_mapping": mapping,
        "exact_sequences_preserved": True,
        "residue_mapping": mapping_rows,
    }


def _atom_key(atom: AtomRecord) -> tuple[str, int, str, str, str]:
    residue = atom.residue
    return (
        residue.chain_id,
        residue.residue_number,
        residue.insertion_code,
        residue.residue_name,
        atom.name.strip().upper(),
    )


def _residue_key(residue: ResidueKey) -> tuple[str, int, str, str]:
    return (
        residue.chain_id,
        residue.residue_number,
        residue.insertion_code,
        residue.residue_name,
    )


def _distance(left: tuple[float, float, float], right: tuple[float, float, float]) -> float:
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(left, right, strict=True)))


def _coord(atom: AtomRecord) -> tuple[float, float, float]:
    return atom.x, atom.y, atom.z


def _contact_set(
    parsed: PDBParseResult,
    receptor_chains: set[str],
    ligand_chains: set[str],
    *,
    cutoff: float = NATIVE_CONTACT_CUTOFF_ANGSTROM,
) -> set[tuple[tuple[str, int, str, str], tuple[str, int, str, str]]]:
    receptor: dict[ResidueKey, list[AtomRecord]] = defaultdict(list)
    ligand: dict[ResidueKey, list[AtomRecord]] = defaultdict(list)
    for atom in parsed.atoms:
        if atom.is_hydrogen:
            continue
        if atom.residue.chain_id in receptor_chains:
            receptor[atom.residue].append(atom)
        elif atom.residue.chain_id in ligand_chains:
            ligand[atom.residue].append(atom)
    contacts = set()
    for left_residue, left_atoms in receptor.items():
        for right_residue, right_atoms in ligand.items():
            if any(
                _distance(_coord(left), _coord(right)) <= cutoff
                for left in left_atoms
                for right in right_atoms
            ):
                contacts.add((_residue_key(left_residue), _residue_key(right_residue)))
    return contacts


def _largest_eigenvector_symmetric4(matrix: list[list[float]]) -> list[float]:
    """Jacobi eigen-solver for the 4x4 Horn quaternion matrix."""
    a = [row[:] for row in matrix]
    vectors = [[1.0 if i == j else 0.0 for j in range(4)] for i in range(4)]
    for _ in range(80):
        p, q = max(
            ((i, j) for i in range(4) for j in range(i + 1, 4)),
            key=lambda pair: abs(a[pair[0]][pair[1]]),
        )
        if abs(a[p][q]) < 1e-14:
            break
        angle = 0.5 * math.atan2(2.0 * a[p][q], a[q][q] - a[p][p])
        c, s = math.cos(angle), math.sin(angle)
        for k in range(4):
            if k not in (p, q):
                apk, aqk = a[p][k], a[q][k]
                a[p][k] = a[k][p] = c * apk - s * aqk
                a[q][k] = a[k][q] = s * apk + c * aqk
        app, aqq, apq = a[p][p], a[q][q], a[p][q]
        a[p][p] = c * c * app - 2 * s * c * apq + s * s * aqq
        a[q][q] = s * s * app + 2 * s * c * apq + c * c * aqq
        a[p][q] = a[q][p] = 0.0
        for k in range(4):
            vkp, vkq = vectors[k][p], vectors[k][q]
            vectors[k][p] = c * vkp - s * vkq
            vectors[k][q] = s * vkp + c * vkq
    index = max(range(4), key=lambda item: a[item][item])
    vector = [vectors[row][index] for row in range(4)]
    norm = math.sqrt(sum(value * value for value in vector))
    return [value / norm for value in vector]


def _receptor_transform(
    pose: PDBParseResult,
    reference: PDBParseResult,
    receptor_chains: set[str],
) -> tuple[list[list[float]], tuple[float, float, float], tuple[float, float, float], int]:
    moving = {
        _atom_key(atom): _coord(atom)
        for atom in pose.atoms
        if atom.residue.chain_id in receptor_chains and atom.name.strip() == "CA"
    }
    fixed = {
        _atom_key(atom): _coord(atom)
        for atom in reference.atoms
        if atom.residue.chain_id in receptor_chains and atom.name.strip() == "CA"
    }
    keys = sorted(set(moving) & set(fixed))
    if len(keys) < 3:
        raise LabmateError("reference 评价至少需要 3 个可匹配的 receptor CA 原子")
    p = [moving[key] for key in keys]
    q = [fixed[key] for key in keys]
    for label, points in (("pose", p), ("reference", q)):
        max_distance_squared = max(
            sum((left[index] - right[index]) ** 2 for index in range(3))
            for left in points
            for right in points
        )
        max_area_squared = max(
            sum(value * value for value in (
                (middle[1] - anchor[1]) * (right[2] - anchor[2])
                - (middle[2] - anchor[2]) * (right[1] - anchor[1]),
                (middle[2] - anchor[2]) * (right[0] - anchor[0])
                - (middle[0] - anchor[0]) * (right[2] - anchor[2]),
                (middle[0] - anchor[0]) * (right[1] - anchor[1])
                - (middle[1] - anchor[1]) * (right[0] - anchor[0]),
            ))
            for anchor in points
            for middle in points
            for right in points
        )
        if (
            max_distance_squared <= 1e-20
            or max_area_squared <= max_distance_squared * max_distance_squared * 1e-12
        ):
            raise LabmateError(
                f"reference receptor CA 对齐退化：{label} 匹配点共线或重合"
            )
    cp = tuple(sum(row[i] for row in p) / len(p) for i in range(3))
    cq = tuple(sum(row[i] for row in q) / len(q) for i in range(3))
    covariance = [[0.0] * 3 for _ in range(3)]
    for left, right in zip(p, q, strict=True):
        lp = [left[i] - cp[i] for i in range(3)]
        rq = [right[i] - cq[i] for i in range(3)]
        for i in range(3):
            for j in range(3):
                covariance[i][j] += lp[i] * rq[j]
    sxx, sxy, sxz = covariance[0]
    syx, syy, syz = covariance[1]
    szx, szy, szz = covariance[2]
    horn = [
        [sxx + syy + szz, syz - szy, szx - sxz, sxy - syx],
        [syz - szy, sxx - syy - szz, sxy + syx, szx + sxz],
        [szx - sxz, sxy + syx, -sxx + syy - szz, syz + szy],
        [sxy - syx, szx + sxz, syz + szy, -sxx - syy + szz],
    ]
    w, x, y, z = _largest_eigenvector_symmetric4(horn)
    rotation = [
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ]
    determinant = (
        rotation[0][0]
        * (rotation[1][1] * rotation[2][2] - rotation[1][2] * rotation[2][1])
        - rotation[0][1]
        * (rotation[1][0] * rotation[2][2] - rotation[1][2] * rotation[2][0])
        + rotation[0][2]
        * (rotation[1][0] * rotation[2][1] - rotation[1][1] * rotation[2][0])
    )
    if not math.isfinite(determinant) or abs(determinant - 1.0) > 1e-6:
        raise LabmateError("reference receptor CA 对齐未产生有效的 proper rotation")
    return rotation, cp, cq, len(keys)


def _apply_transform(
    point: tuple[float, float, float],
    transform: tuple[list[list[float]], tuple[float, float, float], tuple[float, float, float], int],
) -> tuple[float, float, float]:
    rotation, moving_center, fixed_center, _ = transform
    centered = [point[i] - moving_center[i] for i in range(3)]
    return tuple(
        sum(rotation[i][j] * centered[j] for j in range(3)) + fixed_center[i]
        for i in range(3)
    )


def _matched_rmsd(
    pose: PDBParseResult,
    reference: PDBParseResult,
    transform: tuple[list[list[float]], tuple[float, float, float], tuple[float, float, float], int],
    *,
    chains: set[str],
    residue_filter: set[tuple[str, int, str, str]] | None = None,
    atom_names: set[str] | frozenset[str] | None = None,
) -> tuple[float, int, int, int]:
    moving = {
        _atom_key(atom): atom
        for atom in pose.atoms
        if atom.residue.chain_id in chains
        and not atom.is_hydrogen
        and (atom_names is None or atom.name.strip().upper() in atom_names)
        and (residue_filter is None or _residue_key(atom.residue) in residue_filter)
    }
    fixed = {
        _atom_key(atom): atom
        for atom in reference.atoms
        if atom.residue.chain_id in chains
        and not atom.is_hydrogen
        and (atom_names is None or atom.name.strip().upper() in atom_names)
        and (residue_filter is None or _residue_key(atom.residue) in residue_filter)
    }
    keys = sorted(set(moving) & set(fixed))
    if not keys:
        raise LabmateError("reference 评价没有可匹配原子")
    squared = [
        _distance(_apply_transform(_coord(moving[key]), transform), _coord(fixed[key])) ** 2
        for key in keys
    ]
    return math.sqrt(sum(squared) / len(squared)), len(keys), len(moving), len(fixed)


def compute_reference_metrics(
    pose_path: Path,
    reference_path: Path,
    *,
    receptor_chains: set[str],
    ligand_chains: set[str],
) -> dict[str, Any]:
    pose = parse_complex_pdb(pose_path.read_bytes())
    reference = parse_complex_pdb(reference_path.read_bytes())
    transform = _receptor_transform(pose, reference, receptor_chains)
    native_contacts = _contact_set(reference, receptor_chains, ligand_chains)
    predicted_contacts = _contact_set(pose, receptor_chains, ligand_chains)
    if not native_contacts:
        raise LabmateError("reference 没有 5 Å 内原生界面接触")
    native_interface = {
        residue for pair in native_contacts for residue in pair
    }
    predicted_interface = {
        residue for pair in predicted_contacts for residue in pair
    }
    true_contacts = native_contacts & predicted_contacts
    true_residues = native_interface & predicted_interface
    fnat = len(true_contacts) / len(native_contacts)
    precision = (
        len(true_residues) / len(predicted_interface)
        if predicted_interface
        else 0.0
    )
    recall = len(true_residues) / len(native_interface)
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision + recall
        else 0.0
    )
    ligand_rmsd, ligand_atoms, ligand_pose_atoms, ligand_reference_atoms = _matched_rmsd(
        pose,
        reference,
        transform,
        chains=ligand_chains,
    )
    (
        interface_rmsd,
        interface_atoms,
        interface_pose_atoms,
        interface_reference_atoms,
    ) = _matched_rmsd(
        pose,
        reference,
        transform,
        chains=receptor_chains | ligand_chains,
        residue_filter=native_interface,
        atom_names=BACKBONE_ATOMS,
    )
    return {
        "ligand_rmsd": round(ligand_rmsd, 6),
        "interface_rmsd": round(interface_rmsd, 6),
        "fraction_native_contacts": round(fnat, 6),
        "interface_residue_precision": round(precision, 6),
        "interface_residue_recall": round(recall, 6),
        "interface_residue_f1": round(f1, 6),
        "receptor_ca_alignment_atoms": transform[3],
        "ligand_matched_heavy_atoms": ligand_atoms,
        "ligand_pose_heavy_atoms": ligand_pose_atoms,
        "ligand_reference_heavy_atoms": ligand_reference_atoms,
        "ligand_unmatched_pose_heavy_atoms": ligand_pose_atoms - ligand_atoms,
        "ligand_unmatched_reference_heavy_atoms": ligand_reference_atoms - ligand_atoms,
        "interface_matched_backbone_atoms": interface_atoms,
        "interface_pose_backbone_atoms": interface_pose_atoms,
        "interface_reference_backbone_atoms": interface_reference_atoms,
        "interface_unmatched_pose_backbone_atoms": interface_pose_atoms - interface_atoms,
        "interface_unmatched_reference_backbone_atoms": (
            interface_reference_atoms - interface_atoms
        ),
        "native_contact_count": len(native_contacts),
        "predicted_contact_count": len(predicted_contacts),
    }


def _write_csv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _interface_rows(
    pose_rows: list[dict[str, Any]],
    *,
    receptor_chains: set[str],
    ligand_chains: set[str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for pose_row in pose_rows:
        parsed = parse_complex_pdb(Path(pose_row["_absolute_path"]).read_bytes())
        receptor: dict[ResidueKey, list[AtomRecord]] = defaultdict(list)
        ligand: dict[ResidueKey, list[AtomRecord]] = defaultdict(list)
        for atom in parsed.atoms:
            if atom.is_hydrogen:
                continue
            if atom.residue.chain_id in receptor_chains:
                receptor[atom.residue].append(atom)
            elif atom.residue.chain_id in ligand_chains:
                ligand[atom.residue].append(atom)
        for left, left_atoms in receptor.items():
            for right, right_atoms in ligand.items():
                minimum = min(
                    _distance(_coord(a), _coord(b))
                    for a in left_atoms
                    for b in right_atoms
                )
                if minimum <= DEFAULT_INTERFACE_CONFIG.contact_cutoff_angstrom:
                    rows.append(
                        {
                            "pose_rank": pose_row["pose_rank"],
                            "pose_id": pose_row["pose_id"],
                            "antibody_chain": left.chain_id,
                            "antibody_residue_number": left.display_number,
                            "antibody_residue_name": left.residue_name,
                            "antigen_chain": right.chain_id,
                            "antigen_residue_number": right.display_number,
                            "antigen_residue_name": right.residue_name,
                            "min_distance_angstrom": f"{minimum:.3f}",
                            "definition": f"heavy_atom_distance_le_{DEFAULT_INTERFACE_CONFIG.contact_cutoff_angstrom:g}A",
                        }
                    )
    return rows


def _validate_pose_contract(
    path: Path,
    *,
    expected_sequences: dict[str, str],
    expected_keys: dict[str, list[tuple[int, str, str]]],
) -> None:
    _strict_pdb_audit(
        path.read_bytes(),
        selected_chains=expected_sequences,
        label="LightDock pose",
    )
    sequences, keys = _pdb_chain_contract(path)
    if sequences != expected_sequences:
        raise LabmateError("LightDock pose 链集合或序列与标准化输入不一致")
    if keys != expected_keys:
        raise LabmateError("LightDock pose residue key 与标准化输入不一致")


def _summary_rows(metrics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for cutoff in (1, 5, 10):
        selected = metrics[:cutoff]
        rows.append(
            {
                "summary": f"Top {cutoff}",
                "poses_available": len(selected),
                "best_ligand_rmsd": min(float(row["ligand_rmsd"]) for row in selected),
                "best_interface_rmsd": min(float(row["interface_rmsd"]) for row in selected),
                "best_fraction_native_contacts": max(float(row["fraction_native_contacts"]) for row in selected),
                "best_interface_residue_f1": max(float(row["interface_residue_f1"]) for row in selected),
            }
        )
    return rows


def _snapshot(job: BenchmarkLocalJobSpec) -> dict[str, Any]:
    data = job.model_dump(mode="json")
    data["antibody_pdb"] = "inputs/antibody_original.pdb"
    data["antigen_pdb"] = "inputs/antigen_original.pdb"
    if data["reference_complex_pdb"]:
        data["reference_complex_pdb"] = "inputs/reference_original.pdb"
    data["output_dir"] = "."
    for key in data["tools"]:
        data["tools"][key] = Path(data["tools"][key]).name
    return data


def execute_benchmark_local(
    *,
    job: BenchmarkLocalJobSpec,
    antibody_path: Path,
    antigen_path: Path,
    reference_path: Path | None,
    output_root: Path,
) -> RunResult:
    """Execute one fail-closed local benchmark case."""
    executable_values = job.tools.model_dump()
    located = {name: _command_path(value) for name, value in executable_values.items()}
    missing = [name for name, value in located.items() if value is None]
    if missing:
        raise LabmateError("Benchmark Local 预检失败，缺少 executable: " + ", ".join(missing))
    lightdock_version = _lightdock_version(str(located["lightdock_run"]))
    if lightdock_version == "not-probed":
        raise LabmateError("Benchmark Local 预检失败：无法探测 LightDock 版本")

    output_root = output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    run_id = _run_id().replace("RUN-", "BENCH-")
    run_dir = output_root / run_id
    run_dir.mkdir()
    for name in ("inputs", "work", "top_poses", "logs"):
        (run_dir / name).mkdir()
    log_path = run_dir / "logs" / "benchmark_local.log"
    command_records: list[dict[str, Any]] = []
    snapshot = _snapshot(job)
    _write_json(run_dir / "job.json", snapshot)

    antibody, antibody_mapping = _normalized_structure(
        antibody_path,
        mapping=job.antibody_chain_mapping,
        original_copy=run_dir / "inputs" / "antibody_original.pdb",
        normalized_path=run_dir / "inputs" / "antibody_normalized.pdb",
        label="antibody_pdb",
    )
    antigen, antigen_mapping = _normalized_structure(
        antigen_path,
        mapping=job.antigen_chain_mapping,
        original_copy=run_dir / "inputs" / "antigen_original.pdb",
        normalized_path=run_dir / "inputs" / "antigen_normalized.pdb",
        label="antigen_pdb",
    )
    reference_mapping: dict[str, Any] | None = None
    normalized_reference: Path | None = None
    normalized_reference_parsed: PDBParseResult | None = None
    if reference_path is not None:
        normalized_reference = run_dir / "inputs" / "reference_normalized.pdb"
        normalized_reference_parsed, reference_mapping = _normalized_structure(
            reference_path,
            mapping=job.reference_chain_mapping or {},
            original_copy=run_dir / "inputs" / "reference_original.pdb",
            normalized_path=normalized_reference,
            label="reference_complex_pdb",
        )

    receptor_chains = set(job.antibody_chain_mapping.values())
    ligand_chains = set(job.antigen_chain_mapping.values())
    receptor = run_dir / "inputs" / "antibody_normalized.pdb"
    ligand = run_dir / "inputs" / "antigen_normalized.pdb"
    expected_sequences = {
        **{chain: _chain_sequence(antibody, chain) for chain in antibody.chains},
        **{chain: _chain_sequence(antigen, chain) for chain in antigen.chains},
    }
    _, receptor_keys = _pdb_chain_contract(receptor)
    _, ligand_keys = _pdb_chain_contract(ligand)
    expected_keys = {**receptor_keys, **ligand_keys}
    if normalized_reference_parsed is not None:
        reference_sequences = {
            chain: _chain_sequence(normalized_reference_parsed, chain)
            for chain in normalized_reference_parsed.chains
        }
        _, reference_keys = _pdb_chain_contract(normalized_reference)
        if reference_sequences != expected_sequences or reference_keys != expected_keys:
            raise InputValidationError(
                "reference 标准化链的序列或 residue key 与抗体/抗原输入不一致"
            )
    work_receptor = run_dir / "work" / "antibody_receptor.pdb"
    work_ligand = run_dir / "work" / "antigen_ligand.pdb"
    shutil.copy2(receptor, work_receptor)
    shutil.copy2(ligand, work_ligand)

    _run(
        [
            str(located["lightdock_setup"]),
            work_receptor.name,
            work_ligand.name,
            "-s",
            str(job.swarms),
            "-g",
            str(job.glowworms),
            "--noxt",
            "--noh",
            "--now",
        ],
        cwd=run_dir / "work",
        log_path=log_path,
        command_records=command_records,
    )
    _run(
        [
            str(located["lightdock_run"]),
            "setup.json",
            str(job.steps),
            "-c",
            str(job.cores),
        ],
        cwd=run_dir / "work",
        log_path=log_path,
        command_records=command_records,
    )
    score_files = list((run_dir / "work").glob(f"swarm_*/gso_{job.steps}.out"))
    swarm_ids = {
        int(path.parent.name.removeprefix("swarm_"))
        for path in score_files
        if re.fullmatch(r"swarm_[0-9]+", path.parent.name)
    }
    if swarm_ids != set(range(job.swarms)):
        raise LabmateError("LightDock gso swarm 集合不完整或不一致")
    selected: list[LightDockSolution] = _select_lightdock_solutions(
        score_files,
        count=job.top_poses,
        score_direction=job.score_direction,
    )
    selected_gso = run_dir / "work" / "selected_top_poses.gso"
    selected_gso.write_text(
        "\n".join(solution.raw_line for solution in selected) + "\n",
        encoding="utf-8",
    )
    _run(
        [
            str(located["lightdock_generate"]),
            work_receptor.name,
            work_ligand.name,
            selected_gso.name,
            str(len(selected)),
        ],
        cwd=run_dir / "work",
        log_path=log_path,
        command_records=command_records,
    )

    generated_ids = {
        int(match.group(1))
        for path in (run_dir / "work").glob("lightdock_*.pdb")
        if (match := re.fullmatch(r"lightdock_([0-9]+)\.pdb", path.name))
    }
    if generated_ids != set(range(len(selected))):
        raise LabmateError("LightDock score/pose 数量不一致")
    pose_rows: list[dict[str, Any]] = []
    for rank, solution in enumerate(selected, start=1):
        generated = run_dir / "work" / f"lightdock_{rank - 1}.pdb"
        if not generated.is_file():
            raise LabmateError("LightDock score/pose 数量不一致")
        destination = run_dir / "top_poses" / f"pose_{rank:03d}.pdb"
        shutil.copy2(generated, destination)
        _validate_pose_contract(
            destination,
            expected_sequences=expected_sequences,
            expected_keys=expected_keys,
        )
        pose_rows.append(
            {
                "pose_rank": rank,
                "pose_id": f"{job.project_name}-P{rank:03d}",
                "docking_score": solution.score,
                "score_name": job.score_name,
                "score_direction": job.score_direction,
                "swarm_id": solution.swarm_id,
                "glowworm_id": solution.glowworm_id,
                "source_gso": solution.source_path.relative_to(run_dir / "work").as_posix(),
                "source_gso_sha256": sha256_file(solution.source_path),
                "selected_gso_line_number": rank,
                "generated_filename": generated.name,
                "pose_path": destination.relative_to(run_dir).as_posix(),
                "pose_sha256": sha256_file(destination),
                "mapping_verification": "explicit_selected_gso_line_to_lightdock_<line_index>.pdb",
                "_absolute_path": str(destination),
            }
        )
    pose_fields = [key for key in pose_rows[0] if not key.startswith("_")]
    _write_csv(run_dir / "poses.csv", pose_fields, pose_rows)

    interface_rows = _interface_rows(
        pose_rows,
        receptor_chains=receptor_chains,
        ligand_chains=ligand_chains,
    )
    interface_fields = [
        "pose_rank", "pose_id", "antibody_chain", "antibody_residue_number",
        "antibody_residue_name", "antigen_chain", "antigen_residue_number",
        "antigen_residue_name", "min_distance_angstrom", "definition",
    ]
    _write_csv(run_dir / "interface_residues.csv", interface_fields, interface_rows)

    metric_rows: list[dict[str, Any]] = []
    if normalized_reference is not None:
        for pose_row in pose_rows:
            metric_rows.append(
                {
                    "pose_rank": pose_row["pose_rank"],
                    "pose_id": pose_row["pose_id"],
                    "docking_score": pose_row["docking_score"],
                    "score_name": job.score_name,
                    "score_direction": job.score_direction,
                    **compute_reference_metrics(
                        Path(pose_row["_absolute_path"]),
                        normalized_reference,
                        receptor_chains=receptor_chains,
                        ligand_chains=ligand_chains,
                    ),
                }
            )
        _write_csv(
            run_dir / "benchmark_metrics.csv",
            list(metric_rows[0]),
            metric_rows,
        )
        summaries = _summary_rows(metric_rows)
    else:
        summaries = [
            {
                "summary": label,
                "poses_available": min(cutoff, len(pose_rows)),
                "reference_metrics": "not_computed_no_reference",
            }
            for cutoff, label in ((1, "Top 1"), (5, "Top 5"), (10, "Top 10"))
        ]
    _write_csv(run_dir / "case_summary.csv", list(summaries[0]), summaries)

    tool_versions = {
        name: lightdock_version for name in executable_values
    }
    warnings = [
        SCIENTIFIC_LIMITATION,
        "BENCHMARK LOCAL is a computational docking benchmark, not binding or affinity evidence.",
        "Docking score direction was declared by the user and was not inferred.",
        "Random seed is recorded only; the external LightDock CLI is responsible for determinism.",
        "PyMOL skipped_optional; interface analysis is independent of PyMOL.",
    ]
    build_benchmark_report(
        run_dir / "report.html",
        run_id=run_id,
        created_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        job=snapshot,
        pose_rows=pose_rows,
        metric_rows=metric_rows,
        summaries=summaries,
        warnings=warnings,
        tool_versions=tool_versions,
    )
    (run_dir / "logs" / "commands.json").write_text(
        json.dumps(command_records, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (run_dir / "logs" / "pymol.txt").write_text(
        "skipped_optional: PyMOL was not invoked.\n", encoding="utf-8"
    )
    _sanitize_run_metadata(run_dir)
    forbidden = [
        str(antibody_path.resolve()),
        str(antigen_path.resolve()),
        str(reference_path.resolve()) if reference_path else "",
        str(output_root),
        str(run_dir),
        str(Path.home()),
        *executable_values.values(),
    ]
    _audit_run_privacy(run_dir, forbidden)
    artifacts = _collect_artifacts(run_dir, execution_mode="benchmark_local")
    manifest_path = run_dir / "manifest.json"
    _write_json(
        manifest_path,
        {
            "schema_version": "2.2.0",
            "run_id": run_id,
            "mode": "benchmark_local",
            "backend": "local_external_lightdock",
            "status": BENCHMARK_STATUS,
            "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "network_used": False,
            "colabfold_invoked": False,
            "input_hashes": {
                "antibody_pdb_sha256": sha256_file(antibody_path),
                "antigen_pdb_sha256": sha256_file(antigen_path),
                **(
                    {"reference_complex_pdb_sha256": sha256_file(reference_path)}
                    if reference_path
                    else {}
                ),
            },
            "normalization": {
                "antibody": antibody_mapping,
                "antigen": antigen_mapping,
                "reference": reference_mapping,
            },
            "chain_mappings": {
                "antibody": job.antibody_chain_mapping,
                "antigen": job.antigen_chain_mapping,
                "reference": job.reference_chain_mapping,
            },
            "parameters": {
                "score_name": job.score_name,
                "score_direction": job.score_direction,
                "steps": job.steps,
                "swarms": job.swarms,
                "glowworms": job.glowworms,
                "cores": job.cores,
                "top_poses": job.top_poses,
                "random_seed": job.random_seed,
                "random_seed_recording": job.random_seed_recording,
            },
            "tools": {
                "antibody_labmate": {
                    "version": __version__,
                    "python": platform.python_version(),
                },
                "lightdock": {
                    "version": lightdock_version,
                    "license": "GPL-3.0 external user installation; not bundled",
                    "executables": {
                        name: Path(value).name for name, value in executable_values.items()
                    },
                    "commands": command_records,
                    "cluster_executable_checked_but_not_invoked": True,
                },
            },
            "pose_score_mapping": {
                "file": "poses.csv",
                "rule": "explicit selected GSO line order maps to lightdock_<zero_based_line_index>.pdb",
                "filename_sorting_used": False,
            },
            "reference_definitions": {
                "receptor": "normalized antibody H/L or H (VHH)",
                "ligand": "all normalized antigen chains",
                "receptor_alignment": "least-squares Horn quaternion fit over exact-key matched receptor CA atoms",
                "atom_matching": "normalized chain, residue number, insertion code, residue name, atom name",
                "ligand_rmsd": "matched ligand heavy atoms after receptor alignment",
                "interface_rmsd": "matched N/CA/C/O atoms of native 5 A interface residues after receptor alignment",
                "native_contact": "residue pair with any heavy-atom distance <= 5.0 A",
                "missing_atoms": "omit unmatched atoms; fail if no matched atoms; all input residues require CA",
                "fnat": "fraction of native residue contacts recovered",
                "interface_precision_recall_f1": "set comparison over interface residue identities on both partners",
            },
            "verification": {
                "scope": "synthetic software integration only; no scientific validation",
                "real_external_lightdock_smoke_completed": True,
                "validation_record": REAL_SMOKE_VALIDATION_RECORD,
                "scientific_validation_completed": False,
                "pose_chain_sequence_residue_contract_verified": True,
                "privacy_audit_passed": True,
            },
            "artifacts": [
                artifact.model_dump(mode="json") for artifact in artifacts
            ],
            "warnings": warnings,
            "limitations": [
                SCIENTIFIC_LIMITATION,
                "Status remains implemented_unverified because the real LightDock run is synthetic and is not a DB5.5 scientific benchmark.",
                "Scores are within-run docking priorities, not affinity, binding free energy, specificity, efficacy, safety, or experimental evidence.",
            ],
        },
    )
    _audit_run_privacy(run_dir, forbidden)
    (run_dir / "manifest.sha256").write_text(
        f"{sha256_file(manifest_path)}  manifest.json\n", encoding="utf-8"
    )
    zip_path = output_root / f"{run_id}.zip"
    _safe_zip(run_dir, zip_path)
    return RunResult(
        run_id=run_id,
        run_dir=str(run_dir),
        zip_path=str(zip_path),
        manifest_path=str(manifest_path),
        report_path=str(run_dir / "report.html"),
        stages=[],
    )

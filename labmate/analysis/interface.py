"""PyMOL-independent geometric interface analysis for verified pose fixtures."""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from itertools import combinations
from math import dist
from pathlib import Path
from typing import Any

from labmate.config import DEFAULT_INTERFACE_CONFIG, InterfaceConfig
from labmate.docking.lightdock import ParsedDockingPose
from labmate.errors import FixtureIntegrityError
from labmate.validators.antigen import AtomRecord, ResidueKey, parse_complex_pdb

POSITIVE_RESIDUES = {"ARG", "LYS", "HIS"}
NEGATIVE_RESIDUES = {"ASP", "GLU"}
POLAR_ELEMENTS = {"N", "O", "S"}

INTERFACE_RESIDUE_FIELDS = [
    "candidate_id",
    "pose_rank",
    "antibody_chain",
    "antibody_residue_number",
    "antibody_residue_name",
    "antibody_region",
    "antigen_chain",
    "antigen_residue_number",
    "antigen_residue_name",
    "min_distance_angstrom",
    "interaction_types",
    "pose_frequency",
    "pose_frequency_denominator",
    "is_cdr_contact",
    "has_severe_clash",
]

INTERFACE_CONTACT_FIELDS = [
    "candidate_id",
    "pose_rank",
    "antibody_chain",
    "antibody_residue_number",
    "antibody_atom",
    "antigen_chain",
    "antigen_residue_number",
    "antigen_atom",
    "distance_angstrom",
    "contact_type",
]


def _atom_distance(left: AtomRecord, right: AtomRecord) -> float:
    return dist((left.x, left.y, left.z), (right.x, right.y, right.z))


def _load_sequence_map(path: Path) -> dict[tuple[str, int, str], str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FixtureIntegrityError(f"无法读取 sequence map: {path.name}") from exc
    if data.get("mapping_verified") is not True:
        raise FixtureIntegrityError(f"sequence map 未标记为 verified: {path.name}")
    mapping: dict[tuple[str, int, str], str] = {}
    for chain_id, chain_data in data.get("chains", {}).items():
        for row in chain_data.get("residues", []):
            key = (chain_id, int(row["pdb_residue_number"]), str(row.get("insertion_code", "")))
            mapping[key] = str(row["region"])
    if not mapping:
        raise FixtureIntegrityError(f"sequence map 为空: {path.name}")
    return mapping


def _interaction_types(
    antibody_residue: ResidueKey,
    antigen_residue: ResidueKey,
    min_pair: tuple[AtomRecord, AtomRecord],
    min_distance: float,
    config: InterfaceConfig,
) -> list[str]:
    kinds = ["distance_contact"]
    left, right = min_pair
    if (
        min_distance <= config.polar_contact_cutoff_angstrom
        and left.element.upper() in POLAR_ELEMENTS
        and right.element.upper() in POLAR_ELEMENTS
    ):
        kinds.append("distance_based_polar_contact")
    charged_pair = (
        antibody_residue.residue_name in POSITIVE_RESIDUES
        and antigen_residue.residue_name in NEGATIVE_RESIDUES
    ) or (
        antibody_residue.residue_name in NEGATIVE_RESIDUES
        and antigen_residue.residue_name in POSITIVE_RESIDUES
    )
    if charged_pair and min_distance <= config.ionic_contact_cutoff_angstrom:
        kinds.append("distance_based_ionic_contact")
    return kinds


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def analyze_interfaces(
    poses: list[ParsedDockingPose],
    *,
    docking_root: Path,
    structures_root: Path,
    output_dir: Path,
    config: InterfaceConfig = DEFAULT_INTERFACE_CONFIG,
) -> dict[str, Any]:
    """Compute residue contacts, clash flags, and top-pose consensus."""

    grouped: dict[str, list[ParsedDockingPose]] = defaultdict(list)
    for pose in poses:
        grouped[pose.candidate_id].append(pose)

    residue_rows: list[dict[str, Any]] = []
    contact_rows: list[dict[str, Any]] = []
    consensus_rows: list[dict[str, Any]] = []
    warnings: list[str] = []

    for candidate_id in sorted(grouped):
        candidate_poses = sorted(grouped[candidate_id], key=lambda item: item.pose_rank)[: config.analyze_top_poses]
        sequence_map = _load_sequence_map(structures_root / candidate_id / "sequence_map.json")
        fingerprints: list[set[tuple[str, str, str]]] = []
        pose_has_clash: list[bool] = []
        candidate_row_indexes: list[int] = []
        cdr_flags_by_pair: dict[tuple[str, str, str], bool] = {}
        unmapped_contacts = 0

        for pose in candidate_poses:
            complex_path = (docking_root / pose.complex_path).resolve()
            try:
                complex_path.relative_to(docking_root.resolve())
            except ValueError as exc:
                raise FixtureIntegrityError(f"pose 路径越界: {pose.complex_path}") from exc
            if not complex_path.is_file():
                raise FixtureIntegrityError(f"pose 文件不存在: {pose.complex_path}")
            parsed = parse_complex_pdb(complex_path.read_bytes())
            required_chains = {"A", "H", "L"}
            if not required_chains.issubset(set(parsed.chains)):
                raise FixtureIntegrityError(
                    f"{pose.candidate_id} pose {pose.pose_rank} 未同时包含 antigen A、VH H 与 VL L"
                )
            antigen_atoms = [atom for atom in parsed.atoms if atom.residue.chain_id == "A" and not atom.is_hydrogen]
            antibody_atoms = [
                atom for atom in parsed.atoms if atom.residue.chain_id in {"H", "L"} and not atom.is_hydrogen
            ]
            antigen_by_residue: dict[ResidueKey, list[AtomRecord]] = defaultdict(list)
            antibody_by_residue: dict[ResidueKey, list[AtomRecord]] = defaultdict(list)
            for atom in antigen_atoms:
                antigen_by_residue[atom.residue].append(atom)
            for atom in antibody_atoms:
                antibody_by_residue[atom.residue].append(atom)

            fingerprint: set[tuple[str, str, str]] = set()
            severe_clash = False
            for antibody_residue, antibody_residue_atoms in antibody_by_residue.items():
                for antigen_residue, antigen_residue_atoms in antigen_by_residue.items():
                    pairs: list[tuple[float, AtomRecord, AtomRecord]] = []
                    for antibody_atom in antibody_residue_atoms:
                        for antigen_atom in antigen_residue_atoms:
                            distance = _atom_distance(antibody_atom, antigen_atom)
                            if distance <= config.contact_cutoff_angstrom:
                                pairs.append((distance, antibody_atom, antigen_atom))
                                contact_type = "distance_contact"
                                if (
                                    distance <= config.polar_contact_cutoff_angstrom
                                    and antibody_atom.element.upper() in POLAR_ELEMENTS
                                    and antigen_atom.element.upper() in POLAR_ELEMENTS
                                ):
                                    contact_type = "distance_based_polar_contact"
                                contact_rows.append(
                                    {
                                        "candidate_id": candidate_id,
                                        "pose_rank": pose.pose_rank,
                                        "antibody_chain": antibody_residue.chain_id,
                                        "antibody_residue_number": antibody_residue.display_number,
                                        "antibody_atom": antibody_atom.name,
                                        "antigen_chain": antigen_residue.chain_id,
                                        "antigen_residue_number": antigen_residue.display_number,
                                        "antigen_atom": antigen_atom.name,
                                        "distance_angstrom": f"{distance:.3f}",
                                        "contact_type": contact_type,
                                    }
                                )
                    if not pairs:
                        continue
                    pairs.sort(key=lambda item: item[0])
                    minimum, antibody_atom, antigen_atom = pairs[0]
                    region = sequence_map.get(
                        (
                            antibody_residue.chain_id,
                            antibody_residue.residue_number,
                            antibody_residue.insertion_code,
                        ),
                        "UNMAPPED",
                    )
                    if region == "UNMAPPED":
                        unmapped_contacts += 1
                    is_cdr = "cdr" in region.lower()
                    clash = minimum < config.severe_clash_cutoff_angstrom
                    severe_clash = severe_clash or clash
                    pair_key = (
                        antibody_residue.chain_id,
                        antibody_residue.display_number,
                        f"{antigen_residue.chain_id}:{antigen_residue.display_number}",
                    )
                    fingerprint.add(pair_key)
                    cdr_flags_by_pair[pair_key] = is_cdr
                    candidate_row_indexes.append(len(residue_rows))
                    residue_rows.append(
                        {
                            "candidate_id": candidate_id,
                            "pose_rank": pose.pose_rank,
                            "antibody_chain": antibody_residue.chain_id,
                            "antibody_residue_number": antibody_residue.display_number,
                            "antibody_residue_name": antibody_residue.residue_name,
                            "antibody_region": region,
                            "antigen_chain": antigen_residue.chain_id,
                            "antigen_residue_number": antigen_residue.display_number,
                            "antigen_residue_name": antigen_residue.residue_name,
                            "min_distance_angstrom": f"{minimum:.3f}",
                            "interaction_types": "|".join(
                                _interaction_types(
                                    antibody_residue,
                                    antigen_residue,
                                    (antibody_atom, antigen_atom),
                                    minimum,
                                    config,
                                )
                            ),
                            "pose_frequency": 0,
                            "pose_frequency_denominator": len(candidate_poses),
                            "is_cdr_contact": is_cdr,
                            "has_severe_clash": clash,
                            "_pair_key": pair_key,
                        }
                    )
            if not fingerprint:
                warnings.append(f"{candidate_id} pose {pose.pose_rank} 没有 {config.contact_cutoff_angstrom} Å 内接触")
            fingerprints.append(fingerprint)
            pose_has_clash.append(severe_clash)

        frequency = Counter(pair for fingerprint in fingerprints for pair in fingerprint)
        for index in candidate_row_indexes:
            pair_key = residue_rows[index]["_pair_key"]
            residue_rows[index]["pose_frequency"] = frequency[pair_key]

        unique_pairs = set().union(*fingerprints) if fingerprints else set()
        cdr_pairs = sum(1 for pair in unique_pairs if cdr_flags_by_pair.get(pair, False))
        cdr_ratio = cdr_pairs / len(unique_pairs) if unique_pairs else 0.0
        if len(fingerprints) < 2:
            consensus = 1.0 if fingerprints and fingerprints[0] else 0.0
        else:
            jaccards: list[float] = []
            for left, right in combinations(fingerprints, 2):
                union = left | right
                jaccards.append(len(left & right) / len(union) if union else 0.0)
            consensus = sum(jaccards) / len(jaccards)
        clash_free_ratio = (
            sum(1 for has_clash in pose_has_clash if not has_clash) / len(pose_has_clash)
            if pose_has_clash
            else 0.0
        )
        consensus_rows.append(
            {
                "candidate_id": candidate_id,
                "poses_analyzed": len(candidate_poses),
                "unique_contact_pairs": len(unique_pairs),
                "cdr_contact_ratio": round(cdr_ratio, 6),
                "pose_consensus": round(consensus, 6),
                "clash_free_ratio": round(clash_free_ratio, 6),
                "unmapped_contacts": unmapped_contacts,
            }
        )

    for row in residue_rows:
        row.pop("_pair_key", None)
    consensus_fields = [
        "candidate_id",
        "poses_analyzed",
        "unique_contact_pairs",
        "cdr_contact_ratio",
        "pose_consensus",
        "clash_free_ratio",
        "unmapped_contacts",
    ]
    _write_csv(output_dir / "interface_contacts.csv", INTERFACE_CONTACT_FIELDS, contact_rows)
    _write_csv(output_dir / "interface_residues.csv", INTERFACE_RESIDUE_FIELDS, residue_rows)
    _write_csv(output_dir / "pose_consensus.csv", consensus_fields, consensus_rows)
    analysis_manifest = {
        "schema_version": "1.0.0",
        "execution_mode": "replay",
        "analysis_execution": "local_recompute_from_hash_verified_fixture_poses",
        "pymol_required": False,
        "definitions": {
            "contact_cutoff_angstrom": config.contact_cutoff_angstrom,
            "polar_contact_cutoff_angstrom": config.polar_contact_cutoff_angstrom,
            "ionic_contact_cutoff_angstrom": config.ionic_contact_cutoff_angstrom,
            "severe_clash_cutoff_angstrom": config.severe_clash_cutoff_angstrom,
            "polar_label": "distance_based_polar_contact",
            "ionic_label": "distance_based_ionic_contact",
        },
        "warnings": warnings,
    }
    (output_dir / "analysis_manifest.json").write_text(
        json.dumps(analysis_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return {
        "interface_contacts": contact_rows,
        "interface_residues": residue_rows,
        "pose_consensus": consensus_rows,
        "warnings": warnings,
    }


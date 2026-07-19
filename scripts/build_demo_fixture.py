#!/usr/bin/env python3
"""Deterministically build the CC0 synthetic demo_001 Replay fixture.

This script creates software-test data only. It does not invoke IgCraft,
ColabFold, LightDock, or any other scientific compute engine.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from labmate.models import JobSpec
from labmate.provenance import build_input_hashes, sha256_file

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "demo_001"
FIXED_CREATED_AT = "2026-07-19T00:00:00Z"

ONE_TO_THREE = {
    "A": "ALA",
    "R": "ARG",
    "N": "ASN",
    "D": "ASP",
    "C": "CYS",
    "Q": "GLN",
    "E": "GLU",
    "G": "GLY",
    "H": "HIS",
    "I": "ILE",
    "L": "LEU",
    "K": "LYS",
    "M": "MET",
    "F": "PHE",
    "P": "PRO",
    "S": "SER",
    "T": "THR",
    "W": "TRP",
    "Y": "TYR",
    "V": "VAL",
}

CDRS = {
    "H-cdr1": "GFTFSSYA",
    "H-cdr2": "ISYDGSNK",
    "H-cdr3": "ARDYGYFDY",
    "L-cdr1": "QSISSY",
    "L-cdr2": "AAS",
    "L-cdr3": "QQYNNW",
}

FRAMEWORKS = {
    "CAND-001": {
        "H": ["EVQLVEAG", "WVRQAPGK", "RFTISQDN", "WGQGTLVT"],
        "L": ["DIQMTQSP", "LAVSLGER", "FSGSGSGT", "FGQGTKVE"],
    },
    "CAND-002": {
        "H": ["QVQLKESG", "WIRQPPGK", "RFTISRDD", "WGQGTMVT"],
        "L": ["EIVLTQSP", "LAVSLGKR", "FSGSGTGT", "FGQGTRLE"],
    },
    "CAND-003": {
        "H": ["DVQLQESG", "WVRQAPGR", "RFTISQDG", "WGQGTLVS"],
        "L": ["DIVMTQAP", "LAVSLGDR", "FSGSGSGS", "FGQGTKVD"],
    },
    "CAND-004": {
        "H": ["EVQLQASG", "WIRQAPGK", "RFTISQDE", "WGQGTMVS"],
        "L": ["EIVMTQSP", "LAVSLGER", "FSGSGTGS", "FGQGTKLE"],
    },
}

ANTIGEN_SEQUENCE = "ESYDNTKRQAVG"

STRUCTURE_METRICS = {
    "CAND-001": (82.0, 78.0, 9.0, 0.80),
    "CAND-002": (88.0, 84.0, 12.0, 0.74),
    "CAND-003": (74.0, 69.0, 18.0, 0.61),
    "CAND-004": (80.0, 76.0, 11.0, 0.77),
}

DOCKING_SCORES = {
    "CAND-001": [-120.0, -116.0, -110.0],
    "CAND-002": [-125.0, -105.0, -98.0],
    "CAND-003": [-90.0, -86.0, -80.0],
    "CAND-004": [-112.0, -108.0, -104.0],
}

# (antibody chain, residue number, antigen residue number, minimum heavy-atom distance)
POSE_TARGETS = {
    ("CAND-001", 1): [("H", 9, 2, 2.9), ("H", 10, 3, 3.1), ("H", 25, 5, 3.0), ("H", 41, 7, 3.2), ("L", 9, 4, 2.8), ("L", 34, 9, 3.0)],
    ("CAND-001", 2): [("H", 9, 2, 3.0), ("H", 25, 5, 3.1), ("H", 41, 7, 3.0), ("H", 42, 4, 3.2), ("L", 9, 4, 3.0), ("L", 34, 9, 3.1)],
    ("CAND-001", 3): [("H", 9, 2, 3.2), ("H", 25, 5, 3.2), ("H", 41, 7, 3.3), ("L", 34, 9, 3.3)],
    ("CAND-002", 1): [("H", 9, 2, 3.0), ("H", 17, 3, 3.1), ("H", 25, 5, 3.2), ("L", 15, 4, 3.0), ("L", 34, 9, 2.9)],
    ("CAND-002", 2): [("H", 9, 2, 1.2), ("H", 17, 3, 3.1), ("H", 26, 6, 3.2), ("L", 15, 4, 3.0), ("L", 34, 9, 3.0)],
    ("CAND-002", 3): [("H", 9, 2, 3.3), ("H", 17, 3, 3.2), ("L", 15, 4, 3.2), ("L", 34, 9, 3.2)],
    ("CAND-003", 1): [("H", 1, 1, 3.0), ("H", 17, 3, 3.1), ("H", 33, 5, 3.2), ("L", 1, 7, 3.0), ("L", 23, 9, 3.1)],
    ("CAND-003", 2): [("H", 1, 1, 3.1), ("H", 17, 3, 3.2), ("H", 33, 5, 3.1), ("L", 1, 7, 3.2), ("L", 26, 10, 3.0)],
    ("CAND-003", 3): [("H", 1, 1, 3.3), ("H", 17, 3, 3.3), ("L", 1, 7, 3.3)],
    ("CAND-004", 1): [("H", 9, 2, 3.0), ("H", 25, 5, 3.1), ("H", 41, 7, 3.2), ("L", 9, 4, 3.0), ("L", 34, 9, 3.1)],
    ("CAND-004", 2): [("H", 9, 2, 3.1), ("H", 25, 5, 3.0), ("H", 42, 4, 3.2), ("L", 10, 6, 3.1), ("L", 34, 9, 3.0)],
    ("CAND-004", 3): [("H", 9, 2, 3.3), ("H", 25, 5, 3.2), ("L", 34, 9, 3.2)],
}


def write_text(relative: str, content: str) -> None:
    path = FIXTURE / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def write_json(relative: str, payload: object) -> None:
    write_text(relative, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def write_csv(relative: str, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    path = FIXTURE / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def atom_line(
    serial: int,
    name: str,
    residue_name: str,
    chain: str,
    residue_number: int,
    x: float,
    y: float,
    z: float,
    element: str,
    *,
    record: str = "ATOM",
) -> str:
    return (
        f"{record:<6s}{serial:5d} {name:>4s} {residue_name:>3s} {chain:1s}{residue_number:4d}    "
        f"{x:8.3f}{y:8.3f}{z:8.3f}{1.00:6.2f}{20.00:6.2f}          {element:>2s}  "
    )


def sequence_regions(candidate_id: str) -> tuple[dict[str, str], dict[str, str]]:
    framework = FRAMEWORKS[candidate_id]
    heavy = {
        "H-fwr1": framework["H"][0],
        "H-cdr1": CDRS["H-cdr1"],
        "H-fwr2": framework["H"][1],
        "H-cdr2": CDRS["H-cdr2"],
        "H-fwr3": framework["H"][2],
        "H-cdr3": CDRS["H-cdr3"],
        "H-fwr4": framework["H"][3],
    }
    light = {
        "L-fwr1": framework["L"][0],
        "L-cdr1": CDRS["L-cdr1"],
        "L-fwr2": framework["L"][1],
        "L-cdr2": CDRS["L-cdr2"],
        "L-fwr3": framework["L"][2],
        "L-cdr3": CDRS["L-cdr3"],
        "L-fwr4": framework["L"][3],
    }
    return heavy, light


def flatten_regions(regions: dict[str, str]) -> tuple[str, list[dict[str, object]]]:
    sequence = ""
    mapping: list[dict[str, object]] = []
    for region, segment in regions.items():
        for amino_acid in segment:
            sequence += amino_acid
            mapping.append(
                {
                    "pdb_residue_number": len(sequence),
                    "insertion_code": "",
                    "sequence_position": len(sequence),
                    "region": region,
                    "amino_acid": amino_acid,
                }
            )
    return sequence, mapping


def protein_atoms(sequence: str, chain: str, *, x_base: float, y_step: float = 1.6) -> list[tuple[str, str, str, int, float, float, float, str]]:
    atoms: list[tuple[str, str, str, int, float, float, float, str]] = []
    for residue_number, amino_acid in enumerate(sequence, start=1):
        residue_name = ONE_TO_THREE[amino_acid]
        y = (residue_number - 1) * y_step
        atoms.extend(
            [
                ("N", residue_name, chain, residue_number, x_base - 0.4, y, 0.0, "N"),
                ("CA", residue_name, chain, residue_number, x_base, y, 0.0, "C"),
                ("O", residue_name, chain, residue_number, x_base + 0.4, y, 0.0, "O"),
            ]
        )
    return atoms


def antigen_atoms() -> list[tuple[str, str, str, int, float, float, float, str]]:
    atoms: list[tuple[str, str, str, int, float, float, float, str]] = []
    for residue_number, amino_acid in enumerate(ANTIGEN_SEQUENCE, start=1):
        residue_name = ONE_TO_THREE[amino_acid]
        y = (residue_number - 1) * 6.0
        atoms.extend(
            [
                ("N", residue_name, "A", residue_number, -0.4, y, 0.0, "N"),
                ("CA", residue_name, "A", residue_number, 0.0, y, 0.0, "C"),
                ("O", residue_name, "A", residue_number, 0.4, y, 0.0, "O"),
            ]
        )
    return atoms


def pdb_from_atoms(atoms: list[tuple[str, str, str, int, float, float, float, str]], *, add_water: bool = False) -> str:
    lines: list[str] = []
    for serial, (name, residue, chain, number, x, y, z, element) in enumerate(atoms, start=1):
        lines.append(atom_line(serial, name, residue, chain, number, x, y, z, element))
    if add_water:
        lines.append(atom_line(len(lines) + 1, "O", "HOH", "A", 901, 25.0, 25.0, 25.0, "O", record="HETATM"))
    lines.extend(["TER", "END", ""])
    return "\n".join(lines)


def pose_pdb(candidate_id: str, pose_rank: int, heavy_sequence: str, light_sequence: str) -> str:
    targets = {(chain, residue): (antigen_residue, distance) for chain, residue, antigen_residue, distance in POSE_TARGETS[(candidate_id, pose_rank)]}
    atoms = antigen_atoms()
    for chain, sequence, far_x in (("H", heavy_sequence, 14.0), ("L", light_sequence, 18.0)):
        for residue_number, amino_acid in enumerate(sequence, start=1):
            residue_name = ONE_TO_THREE[amino_acid]
            target = targets.get((chain, residue_number))
            if target:
                antigen_residue, minimum_distance = target
                # Ag O is x=0.4 and Ab N is base-0.4, so base = minimum + 0.8.
                x_base = minimum_distance + 0.8
                y = (antigen_residue - 1) * 6.0
            else:
                x_base = far_x
                y = (residue_number - 1) * 1.6
            atoms.extend(
                [
                    ("N", residue_name, chain, residue_number, x_base - 0.4, y, 0.0, "N"),
                    ("CA", residue_name, chain, residue_number, x_base, y, 0.0, "C"),
                    ("O", residue_name, chain, residue_number, x_base + 0.4, y, 0.0, "O"),
                ]
            )
    return pdb_from_atoms(atoms)


def build() -> None:
    FIXTURE.mkdir(parents=True, exist_ok=True)
    project_payload = {
        "schema_version": "1.0.0",
        "mode": "replay",
        "backend": "replay",
        "fixture_id": "demo_001",
        "rights_confirmed": True,
        "source_type": "project_authored_synthetic",
        "antibody": {
            "h_cdr1": CDRS["H-cdr1"],
            "h_cdr2": CDRS["H-cdr2"],
            "h_cdr3": CDRS["H-cdr3"],
            "l_cdr1": CDRS["L-cdr1"],
            "l_cdr2": CDRS["L-cdr2"],
            "l_cdr3": CDRS["L-cdr3"],
            "light_chain_type": "auto",
            "numbering_scheme": "imgt",
            "candidate_count": 4,
            "random_seed": 42,
        },
        "antigen": {
            "source": "upload",
            "file": "input/antigen.pdb",
            "chains": ["A"],
            "remove_waters": True,
            "remove_ions": True,
            "remove_hetero": True,
            "keep_cofactors": [],
            "docking_mode": "blind",
        },
    }
    write_json("project.yaml", project_payload)
    write_text("input/antigen.pdb", pdb_from_atoms(antigen_atoms(), add_water=True))
    write_text(
        "README.md",
        "# demo_001 synthetic fixture\n\n"
        "Every sequence, coordinate, score, and metadata value in this directory was authored "
        "for software testing and is dedicated to the public domain under CC0-1.0. "
        "It is not a biological result. IgCraft, ColabFold, LightDock, ElliDock, HDOCK, and "
        "PyMOL were not executed to create this fixture.\n",
    )
    write_text(
        "LICENSE-CC0.txt",
        "CC0 1.0 Universal dedication notice\n\n"
        "To the extent possible under law, Antibody Labmate contributors have waived all "
        "copyright and related or neighboring rights to the synthetic demo_001 fixture. "
        "The fixture is provided without warranty. See https://creativecommons.org/publicdomain/zero/1.0/\n",
    )

    fasta_lines: list[str] = []
    region_rows: list[dict[str, object]] = []
    sequences: dict[str, tuple[str, str]] = {}
    for candidate_id in sorted(FRAMEWORKS):
        heavy_regions, light_regions = sequence_regions(candidate_id)
        heavy_sequence, heavy_mapping = flatten_regions(heavy_regions)
        light_sequence, light_mapping = flatten_regions(light_regions)
        sequences[candidate_id] = (heavy_sequence, light_sequence)
        fasta_lines.extend([f">{candidate_id}|VH", heavy_sequence, f">{candidate_id}|VL", light_sequence])
        for chain_regions in (heavy_regions, light_regions):
            for region, sequence in chain_regions.items():
                region_rows.append(
                    {
                        "candidate_id": candidate_id,
                        "chain": region[0],
                        "region": region,
                        "sequence": sequence,
                        "source_kind": "project_authored_synthetic_replay",
                    }
                )
        candidate_dir = f"colabfold_output/{candidate_id}"
        write_json(
            f"{candidate_dir}/sequence_map.json",
            {
                "candidate_id": candidate_id,
                "mapping_verified": True,
                "source_kind": "project_authored_synthetic_replay",
                "tool_execution": "not_executed",
                "chains": {
                    "H": {"sequence": heavy_sequence, "residues": heavy_mapping},
                    "L": {"sequence": light_sequence, "residues": light_mapping},
                },
            },
        )
        structure_atoms = protein_atoms(heavy_sequence, "H", x_base=10.0) + protein_atoms(
            light_sequence, "L", x_base=16.0
        )
        write_text(f"{candidate_dir}/ranked_1.pdb", pdb_from_atoms(structure_atoms))
        mean_plddt, cdr_plddt, interface_pae, iptm = STRUCTURE_METRICS[candidate_id]
        write_json(
            f"{candidate_dir}/scores.json",
            {
                "candidate_id": candidate_id,
                "mean_plddt": mean_plddt,
                "cdr_plddt": cdr_plddt,
                "interface_pae": interface_pae,
                "iptm": iptm,
                "source_kind": "project_authored_synthetic_replay",
                "tool_execution": "not_executed",
                "warning": "Synthetic parser-test values; not ColabFold output.",
            },
        )
        for pose_rank in (1, 2, 3):
            write_text(
                f"docking_output/{candidate_id}/pose_{pose_rank:03d}.pdb",
                pose_pdb(candidate_id, pose_rank, heavy_sequence, light_sequence),
            )

    write_text("igcraft_output/candidates.fasta", "\n".join(fasta_lines) + "\n")
    write_csv(
        "igcraft_output/candidates_regions.csv",
        ["candidate_id", "chain", "region", "sequence", "source_kind"],
        region_rows,
    )
    write_json(
        "igcraft_output/generation_manifest.json",
        {
            "schema_version": "1.0.0",
            "source_kind": "project_authored_synthetic_replay",
            "tool_execution": "not_executed",
            "igcraft_version": "not-installed-not-run",
            "candidate_ids": sorted(FRAMEWORKS),
            "cdr_preservation_expected": True,
            "warning": "Synthetic carriers for deterministic software testing only.",
        },
    )

    structure_rows = []
    for candidate_id, values in STRUCTURE_METRICS.items():
        structure_rows.append(
            {
                "candidate_id": candidate_id,
                "mean_plddt": values[0],
                "cdr_plddt": values[1],
                "interface_pae": values[2],
                "iptm": values[3],
                "has_both_chains": True,
                "source_kind": "project_authored_synthetic_replay",
                "tool_execution": "not_executed",
            }
        )
    write_csv(
        "colabfold_output/structure_metrics.csv",
        [
            "candidate_id",
            "mean_plddt",
            "cdr_plddt",
            "interface_pae",
            "iptm",
            "has_both_chains",
            "source_kind",
            "tool_execution",
        ],
        structure_rows,
    )
    write_json(
        "colabfold_output/structure_manifest.json",
        {
            "schema_version": "1.0.0",
            "source_kind": "project_authored_synthetic_replay",
            "tool_execution": "not_executed",
            "colabfold_version": "not-installed-not-run",
            "warning": "All confidence metrics and coordinates are synthetic parser-test data.",
        },
    )

    docking_rows = []
    for candidate_id, scores in DOCKING_SCORES.items():
        for pose_rank, score in enumerate(scores, start=1):
            docking_rows.append(
                {
                    "candidate_id": candidate_id,
                    "pose_rank": pose_rank,
                    "pose_id": f"{candidate_id}-POSE-{pose_rank:03d}",
                    "raw_score": score,
                    "score_name": "synthetic_fixture_score",
                    "score_direction": "lower_is_better",
                    "complex_path": f"{candidate_id}/pose_{pose_rank:03d}.pdb",
                    "provider": "lightdock",
                    "provider_version": "not-executed-in-p0",
                    "source_kind": "project_authored_synthetic_replay",
                    "tool_execution": "not_executed",
                }
            )
    write_csv(
        "docking_output/docking_scores.csv",
        [
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
        ],
        docking_rows,
    )
    write_json(
        "docking_output/docking_manifest.json",
        {
            "schema_version": "1.0.0",
            "provider_contract": "LightDockProvider",
            "provider_capability": "replay_only",
            "provider_version": "not-executed-in-p0",
            "source_kind": "project_authored_synthetic_replay",
            "tool_execution": "not_executed",
            "score_name": "synthetic_fixture_score",
            "score_direction": "lower_is_better",
            "license_status": "No LightDock code, binary, or output is distributed in this fixture.",
            "warning": "Scores and poses are synthetic software-test values, not LightDock results.",
        },
    )
    write_json(
        "expected/golden.json",
        {
            "candidate_order": ["CAND-001", "CAND-002", "CAND-004", "CAND-003"],
            "interface_residue_row_count": 42,
            "required_report_markers": [
                "REPLAY · FIXED HASH-VERIFIED DEMO · NOT LIVE COMPUTE",
                "计算优先级排名",
                "科学限制与使用声明",
            ],
            "required_artifacts": [
                "report.html",
                "job.json",
                "manifest.json",
                "manifest.sha256",
                "candidates.fasta",
                "candidate_ranking.csv",
                "interface_residues.csv",
            ],
        },
    )

    job = JobSpec.model_validate(project_payload)
    antigen_bytes = (FIXTURE / "input" / "antigen.pdb").read_bytes()
    input_hashes = build_input_hashes(job, antigen_bytes)
    artifact_hashes: dict[str, str] = {}
    for path in sorted(FIXTURE.rglob("*")):
        if path.is_file() and path.name != "fixture_manifest.json":
            artifact_hashes[path.relative_to(FIXTURE).as_posix()] = sha256_file(path)
    fixture_manifest = {
        "schema_version": "1.0.0",
        "fixture_id": "demo_001",
        "created_at": FIXED_CREATED_AT,
        "title": "Project-authored synthetic Replay fixture",
        "rights": {
            "author": "Antibody Labmate contributors",
            "license": "CC0-1.0",
            "redistribution_allowed": True,
            "contains_patent_or_confidential_sequence": False,
            "contains_third_party_binary": False,
            "contains_third_party_tool_output": False,
        },
        "input_hashes": input_hashes,
        "artifact_hashes": artifact_hashes,
        "tool_provenance": {
            "IgCraft": {"version": "not-installed-not-run", "execution": "not_executed"},
            "ColabFold": {"version": "not-installed-not-run", "execution": "not_executed"},
            "LightDock": {"version": "not-installed-not-run", "execution": "not_executed"},
            "PyMOL": {"version": "not-installed-not-run", "execution": "not_executed"},
        },
        "default_docking_provider": "lightdock",
        "provider_capability": "replay_only",
        "warnings": [
            "All sequences, coordinates, structure metrics, docking scores, and poses are synthetic.",
            "The fixture validates software behavior only and has no biological interpretation.",
        ],
    }
    write_json("fixture_manifest.json", fixture_manifest)


if __name__ == "__main__":
    build()
    print(FIXTURE)

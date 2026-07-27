from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from labmate.errors import LabmateError
from labmate.live_local import (
    _colabfold_chain_mapping,
    _parse_lightdock_output,
    _plddt,
    _select_colabfold_result,
    _select_lightdock_solutions,
)
from labmate.models import LiveLocalTools


def _gso_line(score: str | float, *, conformer: bool = False) -> str:
    coordinates = "(0.0, 1.0, 2.0, 1.0, 0.0, 0.0, 0.0)"
    if conformer:
        return f"{coordinates} 3 4 0.25 5 0.75 {score}"
    return f"{coordinates} 0.25 4 0.75 {score}"


def _write_gso(
    root: Path,
    swarm_id: int,
    lines: list[str],
    *,
    steps: int = 20,
) -> Path:
    path = root / f"swarm_{swarm_id}" / f"gso_{steps}.out"
    path.parent.mkdir(parents=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _atom_line(
    serial: int,
    atom_name: str,
    residue_name: str,
    chain: str,
    residue_number: int,
    *,
    insertion_code: str = "",
    bfactor: float = 80.0,
) -> str:
    element = atom_name.strip()[0]
    return (
        f"ATOM  {serial:5d} {atom_name:>4s} {residue_name:>3s} "
        f"{chain:1s}{residue_number:4d}{insertion_code:1s}   "
        f"{float(serial):8.3f}{0.0:8.3f}{0.0:8.3f}"
        f"{1.0:6.2f}{bfactor:6.2f}          {element:>2s}"
    )


def _write_two_chain_pdb(
    path: Path,
    chain_sequences: dict[str, list[tuple[str, int, str]]],
) -> Path:
    one_to_three = {
        "A": "ALA",
        "C": "CYS",
        "D": "ASP",
        "E": "GLU",
        "F": "PHE",
        "G": "GLY",
        "H": "HIS",
        "I": "ILE",
        "K": "LYS",
        "L": "LEU",
        "M": "MET",
        "N": "ASN",
        "P": "PRO",
        "Q": "GLN",
        "R": "ARG",
        "S": "SER",
        "T": "THR",
        "V": "VAL",
        "W": "TRP",
        "Y": "TYR",
    }
    lines: list[str] = []
    serial = 1
    for chain, residues in chain_sequences.items():
        for amino_acid, residue_number, insertion_code in residues:
            lines.append(
                _atom_line(
                    serial,
                    "CA",
                    one_to_three[amino_acid],
                    chain,
                    residue_number,
                    insertion_code=insertion_code,
                )
            )
            serial += 1
    path.write_text("\n".join([*lines, "TER", "END", ""]), encoding="utf-8")
    return path


def test_lightdock_official_default_and_conformer_schemas_use_solution_ordinal(
    tmp_path: Path,
) -> None:
    score_file = _write_gso(
        tmp_path,
        7,
        [
            "# LightDock 0.9.4 output",
            "",
            _gso_line(-8.25),
            "# comments do not consume a glowworm id",
            _gso_line(-9.5, conformer=True),
        ],
    )

    solutions = _parse_lightdock_output(score_file)

    assert [(item.swarm_id, item.glowworm_id, item.score) for item in solutions] == [
        (7, 0, -8.25),
        (7, 1, -9.5),
    ]
    assert solutions[0].raw_line == _gso_line(-8.25)
    assert solutions[1].raw_line == _gso_line(-9.5, conformer=True)


@pytest.mark.parametrize(
    "line",
    [
        "(0.0, 1.0) 0.25 4 0.75 -1.0",
        "(0.0, 1.0, 2.0, 1.0, 0.0, 0.0, nan) 0.25 4 0.75 -1.0",
        _gso_line("inf"),
        _gso_line("-inf", conformer=True),
        "(0.0, 1.0, 2.0, 1.0, 0.0, 0.0, 0.0) malformed",
        "(0.0, 1.0, 2.0, 1.0, 0.0, 0.0, 0.0) 1 2 3 4 5",
    ],
)
def test_lightdock_rejects_malformed_or_nonfinite_solution_rows(
    tmp_path: Path, line: str
) -> None:
    score_file = _write_gso(tmp_path, 0, [line])

    with pytest.raises(LabmateError):
        _parse_lightdock_output(score_file)


@pytest.mark.parametrize(
    ("direction", "expected"),
    [
        (
            "higher_is_better",
            [(2, 1, 12.0), (5, 0, 11.0), (9, 0, 10.0)],
        ),
        (
            "lower_is_better",
            [(2, 0, -4.0), (5, 1, -3.0), (9, 1, 1.0)],
        ),
    ],
)
def test_lightdock_global_top_k_maps_scores_to_explicit_swarm_and_glowworm_ids(
    tmp_path: Path,
    direction: str,
    expected: list[tuple[int, int, float]],
) -> None:
    swarm_9 = _write_gso(tmp_path, 9, [_gso_line(10), _gso_line(1)])
    swarm_2 = _write_gso(
        tmp_path, 2, [_gso_line(-4, conformer=True), _gso_line(12)]
    )
    swarm_5 = _write_gso(tmp_path, 5, [_gso_line(11), _gso_line(-3)])

    selected = _select_lightdock_solutions(
        [swarm_9, swarm_2, swarm_5],
        count=3,
        score_direction=direction,
    )

    assert [
        (item.swarm_id, item.glowworm_id, item.score) for item in selected
    ] == expected
    raw_by_identity = {
        (9, 0): _gso_line(10),
        (9, 1): _gso_line(1),
        (2, 0): _gso_line(-4, conformer=True),
        (2, 1): _gso_line(12),
        (5, 0): _gso_line(11),
        (5, 1): _gso_line(-3),
    }
    for item in selected:
        assert item.raw_line == raw_by_identity[(item.swarm_id, item.glowworm_id)]


def test_colabfold_rank_001_pairs_pdb_with_exact_model_tag_score_json(
    tmp_path: Path,
) -> None:
    tag = "alphafold2_multimer_v3_model_2_seed_003"
    pdb_path = tmp_path / f"query_unrelaxed_rank_001_{tag}.pdb"
    score_path = tmp_path / f"query_scores_rank_001_{tag}.json"
    pdb_path.write_text("END\n", encoding="utf-8")
    score_path.write_text(json.dumps({"plddt": [91.0]}), encoding="utf-8")
    # A tempting same-rank score from another model must never be paired.
    (tmp_path / "query_scores_rank_001_wrong_tag.json").write_text(
        json.dumps({"plddt": [1.0]}), encoding="utf-8"
    )

    result = _select_colabfold_result(tmp_path)

    assert result.pdb_path == pdb_path
    assert result.score_path == score_path
    assert result.model_tag == tag
    assert result.rank == 1
    assert result.scores == {"plddt": [91.0]}


def test_colabfold_rank_001_rejects_missing_exact_tag_score_json(
    tmp_path: Path,
) -> None:
    tag = "alphafold2_multimer_v3_model_1_seed_000"
    (tmp_path / f"query_unrelaxed_rank_001_{tag}.pdb").write_text(
        "END\n", encoding="utf-8"
    )
    (tmp_path / "query_scores_rank_001_different_tag.json").write_text(
        "{}", encoding="utf-8"
    )

    with pytest.raises(LabmateError):
        _select_colabfold_result(tmp_path)


def test_colabfold_rank_001_rejects_ambiguous_pdb_models(tmp_path: Path) -> None:
    for tag in ("model_1_seed_000", "model_2_seed_000"):
        (tmp_path / f"query_unrelaxed_rank_001_{tag}.pdb").write_text(
            "END\n", encoding="utf-8"
        )
        (tmp_path / f"query_scores_rank_001_{tag}.json").write_text(
            "{}", encoding="utf-8"
        )

    with pytest.raises(LabmateError):
        _select_colabfold_result(tmp_path)


def test_colabfold_chain_mapping_uses_exact_sequences_when_a_b_are_reversed(
    tmp_path: Path,
) -> None:
    pdb_path = _write_two_chain_pdb(
        tmp_path / "reversed.pdb",
        {
            "A": [("G", 7, ""), ("S", 8, ""), ("T", 9, "")],
            "B": [("A", 42, ""), ("C", 43, ""), ("D", 44, "")],
        },
    )

    assert _colabfold_chain_mapping(pdb_path, {"H": "ACD", "L": "GST"}) == {
        "B": "H",
        "A": "L",
    }


def test_colabfold_chain_mapping_rejects_mutation(tmp_path: Path) -> None:
    pdb_path = _write_two_chain_pdb(
        tmp_path / "mutation.pdb",
        {
            "A": [("G", 7, ""), ("S", 8, ""), ("T", 9, "")],
            "B": [("A", 42, ""), ("C", 43, ""), ("E", 44, "")],
        },
    )

    with pytest.raises(LabmateError):
        _colabfold_chain_mapping(pdb_path, {"H": "ACD", "L": "GST"})


def test_colabfold_chain_mapping_rejects_ambiguous_equal_sequences(
    tmp_path: Path,
) -> None:
    pdb_path = _write_two_chain_pdb(
        tmp_path / "ambiguous.pdb",
        {
            "A": [("A", 7, ""), ("C", 8, "")],
            "B": [("A", 42, ""), ("C", 43, "")],
        },
    )

    with pytest.raises(LabmateError):
        _colabfold_chain_mapping(pdb_path, {"H": "AC", "L": "AC"})


def test_plddt_is_residue_weighted_and_cross_checks_json_with_pdb_keys(
    tmp_path: Path,
) -> None:
    pdb_path = tmp_path / "plddt.pdb"
    pdb_path.write_text(
        "\n".join(
            [
                _atom_line(
                    1,
                    "CA",
                    "ALA",
                    "H",
                    10,
                    insertion_code="A",
                    bfactor=90.0,
                ),
                _atom_line(
                    2,
                    "N",
                    "GLY",
                    "L",
                    27,
                    insertion_code="B",
                    bfactor=30.0,
                ),
                _atom_line(
                    3,
                    "CA",
                    "GLY",
                    "L",
                    27,
                    insertion_code="B",
                    bfactor=30.0,
                ),
                _atom_line(
                    4,
                    "C",
                    "GLY",
                    "L",
                    27,
                    insertion_code="B",
                    bfactor=30.0,
                ),
                "END",
                "",
            ]
        ),
        encoding="utf-8",
    )
    sequence_map = {
        "H": [
            {
                "pdb_residue_number": 10,
                "insertion_code": "A",
                "region": "CDR-H1",
            }
        ],
        "L": [
            {
                "pdb_residue_number": 27,
                "insertion_code": "B",
                "region": "FR-L1",
            }
        ],
    }

    mean_plddt, cdr_plddt = _plddt(
        pdb_path,
        sequence_map,
        scores={"plddt": [90.0, 30.0]},
    )

    # Each residue has equal weight despite the second residue having three atoms.
    assert mean_plddt == 60.0
    assert cdr_plddt == 90.0

    with pytest.raises(LabmateError):
        _plddt(
            pdb_path,
            sequence_map,
            scores={"plddt": [90.0, 31.0]},
        )


def _valid_colabfold_args() -> list[str]:
    return [
        "--msa-mode",
        "single_sequence",
        "--data",
        "not-inspected-by-config-validation",
        "--model-type",
        "alphafold2_multimer_v3",
    ]


def test_colabfold_msa_args_accept_explicit_offline_preinstalled_contract() -> None:
    tools = LiveLocalTools(colabfold_args=_valid_colabfold_args())

    assert tools.msa_network_policy == "offline_single_sequence"
    assert tools.model_data_policy == "preinstalled_only"


@pytest.mark.parametrize(
    "arguments",
    [
        [
            "--data",
            "unused",
            "--model-type",
            "alphafold2_multimer_v3",
        ],
        [
            "--msa-mode",
            "mmseqs2_uniref_env",
            "--data",
            "unused",
            "--model-type",
            "alphafold2_multimer_v3",
        ],
        [
            "--msa-mode",
            "single_sequence",
            "--model-type",
            "alphafold2_multimer_v3",
        ],
        [
            "--msa-mode",
            "single_sequence",
            "--data",
            "",
            "--model-type",
            "alphafold2_multimer_v3",
        ],
        [
            "--msa-mode",
            "single_sequence",
            "--data",
            "unused",
        ],
        [
            "--msa-mode",
            "single_sequence",
            "--data",
            "unused",
            "--model-type",
            "alphafold2_multimer",
        ],
    ],
)
def test_colabfold_msa_args_fail_closed_without_required_offline_contract(
    arguments: list[str],
) -> None:
    with pytest.raises(ValidationError):
        LiveLocalTools(colabfold_args=arguments)

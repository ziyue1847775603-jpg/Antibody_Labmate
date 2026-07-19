from __future__ import annotations

import pytest

from labmate.config import InputLimits
from labmate.errors import InputValidationError
from labmate.validators.antigen import parse_antigen_pdb
from scripts.build_demo_fixture import atom_line


def test_demo_pdb_is_cleaned_and_summarized(demo_antigen: bytes) -> None:
    result = parse_antigen_pdb(demo_antigen, selected_chains=["A"])
    assert result.chains == ["A"]
    assert len(result.atoms) == 36
    assert result.residue_count == 12
    assert result.removed_hetero_atoms == 1
    assert "HETATM" not in result.cleaned_pdb


def test_only_first_model_is_selected() -> None:
    first = atom_line(1, "CA", "ALA", "A", 1, 0.0, 0.0, 0.0, "C")
    second = atom_line(2, "CA", "GLY", "B", 1, 9.0, 9.0, 9.0, "C")
    pdb = f"MODEL        1\n{first}\nENDMDL\nMODEL        2\n{second}\nENDMDL\nEND\n".encode()
    result = parse_antigen_pdb(pdb, selected_chains=["A"])
    assert result.model_count == 2
    assert result.selected_model == 1
    assert result.chains == ["A"]
    assert result.ignored_model_atoms == 1


def test_blank_altloc_wins_over_a() -> None:
    base = atom_line(1, "CA", "ALA", "A", 1, 1.0, 0.0, 0.0, "C")
    alt = list(atom_line(2, "CA", "ALA", "A", 1, 7.0, 0.0, 0.0, "C"))
    alt[16] = "A"
    pdb = ("".join(alt) + "\n" + base + "\nEND\n").encode()
    result = parse_antigen_pdb(pdb, selected_chains=["A"])
    assert len(result.atoms) == 1
    assert result.atoms[0].x == 1.0
    assert result.removed_altloc_atoms == 1


def test_missing_selected_chain_is_rejected(demo_antigen: bytes) -> None:
    with pytest.raises(InputValidationError, match="所选链|缺少"):
        parse_antigen_pdb(demo_antigen, selected_chains=["Z"])


def test_pdb_size_limit_is_enforced() -> None:
    with pytest.raises(InputValidationError, match="超过"):
        parse_antigen_pdb(b"ATOM" * 20, limits=InputLimits(max_pdb_bytes=10))


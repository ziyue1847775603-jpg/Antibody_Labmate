import math
from pathlib import Path

import pytest

from labmate.benchmarking.metrics import (
    CATEGORY_DEFINITION_ID,
    METRIC_DEFINITION_ID,
    CAPRI_DOCKQ_2016,
    classify_capri_quality,
    compute_capri_metrics,
)


_BACKBONE = {
    "N": (-0.45, 0.15, 0.0, "N"),
    "CA": (0.0, 0.0, 0.0, "C"),
    "C": (0.45, -0.15, 0.0, "C"),
    "O": (0.75, -0.30, 0.0, "O"),
}


def _transform(
    point: tuple[float, float, float],
    *,
    translate: tuple[float, float, float] = (0.0, 0.0, 0.0),
    rotate_z_degrees: float = 0.0,
) -> tuple[float, float, float]:
    angle = math.radians(rotate_z_degrees)
    cosine, sine = math.cos(angle), math.sin(angle)
    x, y, z = point
    return (
        cosine * x - sine * y + translate[0],
        sine * x + cosine * y + translate[1],
        z + translate[2],
    )


def _write_complex(
    path: Path,
    *,
    receptor_chain: str = "A",
    ligand_chain: str = "H",
    whole_translate: tuple[float, float, float] = (0.0, 0.0, 0.0),
    whole_rotate_z_degrees: float = 0.0,
    ligand_translate_by_residue: dict[int, tuple[float, float, float]] | None = None,
) -> None:
    bases = ((0.0, 0.0, 0.0), (10.0, 0.0, 0.0), (0.0, 10.0, 0.0), (10.0, 10.0, 0.0))
    residue_names = ("ALA", "CYS", "ASP", "GLU")
    rows: list[str] = []
    serial = 1
    for chain, z in ((receptor_chain, 0.0), (ligand_chain, 4.0)):
        for residue_number, base in enumerate(bases, start=1):
            residue_name = residue_names[residue_number - 1]
            local_translate = (
                (ligand_translate_by_residue or {}).get(
                    residue_number, (0.0, 0.0, 0.0)
                )
                if chain == ligand_chain
                else (0.0, 0.0, 0.0)
            )
            for atom_name, (dx, dy, dz, element) in _BACKBONE.items():
                raw = (
                    base[0] + dx + local_translate[0],
                    base[1] + dy + local_translate[1],
                    z + dz + local_translate[2],
                )
                x, y, transformed_z = _transform(
                    raw,
                    translate=whole_translate,
                    rotate_z_degrees=whole_rotate_z_degrees,
                )
                rows.append(
                    f"ATOM  {serial:5d} {atom_name:>4s} {residue_name} {chain}{residue_number:4d}    "
                    f"{x:8.3f}{y:8.3f}{transformed_z:8.3f}{1.0:6.2f}{20.0:6.2f}"
                    f"          {element:>2s}  "
                )
                serial += 1
    path.write_text("\n".join(rows) + "\nEND\n", encoding="utf-8")


def _copy_chain(
    source: Path,
    target: Path,
    *,
    source_chain: str,
    target_chain: str,
) -> None:
    rows = source.read_text(encoding="utf-8").splitlines()
    copied = []
    for row in rows:
        if row.startswith("ATOM") and row[21] == source_chain:
            copied.append(row[:21] + target_chain + row[22:])
    target.write_text(
        "\n".join([row for row in rows if row != "END"] + copied) + "\nEND\n",
        encoding="utf-8",
    )


def _metrics(
    model: Path,
    native: Path,
    root: Path,
    *,
    model_receptor: str = "A",
    model_ligand: str = "H",
):
    return compute_capri_metrics(
        model,
        native,
        allowed_root=root,
        model_receptor_chains=(model_receptor,),
        model_ligand_chains=(model_ligand,),
        native_receptor_chains=("A",),
        native_ligand_chains=("H",),
        chain_mapping={model_receptor: "A", model_ligand: "H"},
    )


def test_metric_definition_is_frozen_and_source_versioned() -> None:
    assert CAPRI_DOCKQ_2016.definition_id == METRIC_DEFINITION_ID
    assert CAPRI_DOCKQ_2016.contact_cutoff_angstrom == 5.0
    assert CAPRI_DOCKQ_2016.interface_atom_selection == "corresponding N, CA, C, O atoms"


def test_identical_and_common_rigid_transform_are_invariant(tmp_path: Path) -> None:
    native, identical, transformed = (
        tmp_path / "native.pdb",
        tmp_path / "identical.pdb",
        tmp_path / "transformed.pdb",
    )
    _write_complex(native)
    _write_complex(identical)
    _write_complex(
        transformed,
        whole_translate=(7.0, -4.0, 3.0),
        whole_rotate_z_degrees=37.0,
    )
    for model in (identical, transformed):
        result = _metrics(model, native, tmp_path)
        assert result.fnat == 1.0
        assert result.i_rmsd == pytest.approx(0.0, abs=1e-3)
        assert result.l_rmsd == pytest.approx(0.0, abs=1e-3)
        assert result.native_contact_count == 4
        assert result.recovered_native_contact_count == 4
        assert result.metric_definition_id == METRIC_DEFINITION_ID


def test_ligand_translation_and_partial_contacts_have_exact_fnat(tmp_path: Path) -> None:
    native = tmp_path / "native.pdb"
    translated = tmp_path / "translated.pdb"
    partial = tmp_path / "partial.pdb"
    _write_complex(native)
    _write_complex(
        translated,
        ligand_translate_by_residue={
            1: (0.0, 0.0, 6.0),
            2: (0.0, 0.0, 6.0),
            3: (0.0, 0.0, 6.0),
            4: (0.0, 0.0, 6.0),
        },
    )
    _write_complex(
        partial,
        ligand_translate_by_residue={
            3: (0.0, 0.0, 30.0),
            4: (0.0, 0.0, 30.0),
        },
    )
    moved = _metrics(translated, native, tmp_path)
    assert moved.fnat == 0.0
    assert moved.l_rmsd == pytest.approx(6.0, abs=1e-6)
    partly = _metrics(partial, native, tmp_path)
    assert partly.native_contact_count == 4
    assert partly.recovered_native_contact_count == 2
    assert partly.fnat == 0.5


def test_non_native_contacts_do_not_increase_fnat(tmp_path: Path) -> None:
    native, model = tmp_path / "native.pdb", tmp_path / "model.pdb"
    _write_complex(native)
    _write_complex(model)
    result = _metrics(model, native, tmp_path)
    assert result.fnat == 1.0
    assert result.recovered_native_contact_count == result.native_contact_count


def test_semantic_chain_rename_works_and_role_swap_fails(tmp_path: Path) -> None:
    native, renamed = tmp_path / "native.pdb", tmp_path / "renamed.pdb"
    _write_complex(native)
    _write_complex(renamed, receptor_chain="R", ligand_chain="L")
    result = _metrics(
        renamed,
        native,
        tmp_path,
        model_receptor="R",
        model_ligand="L",
    )
    assert result.fnat == 1.0
    with pytest.raises(ValueError, match="semantic roles"):
        compute_capri_metrics(
            renamed,
            native,
            allowed_root=tmp_path,
            model_receptor_chains=("R",),
            model_ligand_chains=("L",),
            native_receptor_chains=("A",),
            native_ligand_chains=("H",),
            chain_mapping={"R": "H", "L": "A"},
        )


def test_multichain_ligand_group_and_missing_interface_fail_closed(
    tmp_path: Path,
) -> None:
    base_native = tmp_path / "base_native.pdb"
    native = tmp_path / "native_multichain.pdb"
    base_model = tmp_path / "base_model.pdb"
    model = tmp_path / "model_multichain.pdb"
    _write_complex(base_native)
    _copy_chain(base_native, native, source_chain="H", target_chain="L")
    _write_complex(base_model, receptor_chain="R", ligand_chain="Q")
    _copy_chain(base_model, model, source_chain="Q", target_chain="S")
    result = compute_capri_metrics(
        model,
        native,
        allowed_root=tmp_path,
        model_receptor_chains=("R",),
        model_ligand_chains=("Q", "S"),
        native_receptor_chains=("A",),
        native_ligand_chains=("H", "L"),
        chain_mapping={"R": "A", "Q": "H", "S": "L"},
    )
    assert result.fnat == 1.0
    assert result.l_rmsd == pytest.approx(0.0, abs=1e-6)

    missing = tmp_path / "missing_interface.pdb"
    missing.write_text(
        "\n".join(
            row
            for row in model.read_text(encoding="utf-8").splitlines()
            if not (row.startswith("ATOM") and row[21] == "Q" and int(row[22:26]) == 1)
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unmapped residue"):
        compute_capri_metrics(
            missing,
            native,
            allowed_root=tmp_path,
            model_receptor_chains=("R",),
            model_ligand_chains=("Q", "S"),
            native_receptor_chains=("A",),
            native_ligand_chains=("H", "L"),
            chain_mapping={"R": "A", "Q": "H", "S": "L"},
        )


def test_insertion_code_and_altloc_policy_are_explicit(tmp_path: Path) -> None:
    native = tmp_path / "native.pdb"
    model = tmp_path / "model.pdb"
    _write_complex(native)
    _write_complex(model)
    for path in (native, model):
        rows = []
        for row in path.read_text(encoding="utf-8").splitlines():
            if row.startswith("ATOM") and int(row[22:26]) == 2:
                row = row[:26] + "A" + row[27:]
            rows.append(row)
        path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    model_rows = model.read_text(encoding="utf-8").splitlines()
    blank_ca = next(
        row
        for row in model_rows
        if row.startswith("ATOM") and row[12:16].strip() == "CA"
    )
    altloc_a = blank_ca[:16] + "A" + blank_ca[17:]
    model.write_text(
        "\n".join([altloc_a, *model_rows]) + "\n", encoding="utf-8"
    )
    result = _metrics(model, native, tmp_path)
    assert result.fnat == 1.0
    assert any("alternate-location" in warning for warning in result.warnings)


def test_metric_inputs_reject_symlink_escape_and_nan(tmp_path: Path) -> None:
    native = tmp_path / "native.pdb"
    _write_complex(native)
    link = tmp_path / "link.pdb"
    link.symlink_to(native)
    with pytest.raises(ValueError, match="non-symlink"):
        _metrics(link, native, tmp_path)
    outside = tmp_path.parent / "capri-outside.pdb"
    _write_complex(outside)
    with pytest.raises(ValueError, match="escaped"):
        _metrics(outside, native, tmp_path)
    invalid = tmp_path / "invalid.pdb"
    _write_complex(invalid)
    invalid.write_text(
        invalid.read_text(encoding="utf-8").replace("   0.000", "     nan", 1),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="coordinate"):
        _metrics(invalid, native, tmp_path)


@pytest.mark.parametrize(
    ("fnat", "i_rmsd", "l_rmsd", "expected"),
    [
        (0.5, 1.0, 20.0, "high"),
        (0.5, 20.0, 1.0, "high"),
        (0.5, 1.000001, 1.000001, "medium"),
        (0.3, 2.0, 20.0, "medium"),
        (0.499999, 20.0, 5.0, "medium"),
        (0.3, 2.000001, 5.000001, "acceptable"),
        (0.1, 4.0, 20.0, "acceptable"),
        (0.299999, 20.0, 10.0, "acceptable"),
        (0.099999, 0.0, 0.0, "incorrect"),
        (0.1, 4.000001, 10.000001, "incorrect"),
    ],
)
def test_capri_category_exact_boundaries(
    fnat: float, i_rmsd: float, l_rmsd: float, expected: str
) -> None:
    result = classify_capri_quality(fnat, i_rmsd, l_rmsd)
    assert result.category == expected
    assert result.category_definition_id == CATEGORY_DEFINITION_ID
    assert result.matched_rule


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_capri_category_rejects_non_finite(value: float) -> None:
    with pytest.raises(ValueError, match="finite"):
        classify_capri_quality(value, 1.0, 1.0)

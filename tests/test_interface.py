from __future__ import annotations

from labmate.analysis.interface import analyze_interfaces
from labmate.docking.lightdock import LightDockProvider


def test_interface_analysis_is_pymol_independent_and_matches_golden(fixture_root, tmp_path) -> None:
    poses = LightDockProvider().parse_replay_output(fixture_root / "docking_output" / "docking_scores.csv")
    result = analyze_interfaces(
        poses,
        docking_root=fixture_root / "docking_output",
        structures_root=fixture_root / "colabfold_output",
        output_dir=tmp_path,
    )
    assert len(result["interface_residues"]) == 42
    assert any(row["has_severe_clash"] for row in result["interface_residues"])
    assert any("distance_based_ionic_contact" in row["interaction_types"] for row in result["interface_residues"])
    assert all(row["antibody_region"] != "UNMAPPED" for row in result["interface_residues"])
    assert (tmp_path / "interface_residues.csv").is_file()
    assert (tmp_path / "pose_consensus.csv").is_file()


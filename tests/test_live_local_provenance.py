import json
from pathlib import Path

from labmate.analysis.interface import analyze_interfaces
from labmate.analysis.ranking import rank_candidates
from labmate.docking.lightdock import LightDockProvider
from labmate.docking.registry import capability_matrix
from labmate.models import CandidateMetric
from labmate.workflow import _artifact_role


def test_live_analysis_manifest_never_claims_replay(
    fixture_root: Path, tmp_path: Path
) -> None:
    poses = LightDockProvider().parse_replay_output(
        fixture_root / "docking_output" / "docking_scores.csv"
    )
    analyze_interfaces(
        poses[:3],
        docking_root=fixture_root / "docking_output",
        structures_root=fixture_root / "colabfold_output",
        output_dir=tmp_path,
        execution_mode="live_local",
        analysis_execution="local_recompute_from_executed_live_local_poses",
    )
    manifest = json.loads(
        (tmp_path / "analysis_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["execution_mode"] == "live_local"
    assert manifest["analysis_execution"] == (
        "local_recompute_from_executed_live_local_poses"
    )


def test_live_ranking_manifest_is_same_run_heuristic(tmp_path: Path) -> None:
    rank_candidates(
        [
            CandidateMetric(
                candidate_id="LIVE-SMOKE-001",
                mean_plddt=70,
                cdr_plddt=65,
                interface_pae=None,
                iptm=0.4,
                docking_best_score=5,
                docking_topk_median=4,
                cdr_contact_ratio=0.2,
                pose_consensus=0.3,
                clash_free_ratio=1,
                pose_count=3,
            )
        ],
        docking_higher_is_better=True,
        output_dir=tmp_path,
        execution_mode="live_local",
        ranking_execution="local_recompute_from_executed_live_local_artifacts",
    )
    manifest = json.loads(
        (tmp_path / "ranking_manifest.json").read_text(encoding="utf-8")
    )
    definitions = json.loads(
        (tmp_path / "metric_definitions.json").read_text(encoding="utf-8")
    )
    assert manifest["execution_mode"] == "live_local"
    assert "affinity" in definitions["interpretation"]
    assert definitions["scope"].startswith("same run")


def test_live_artifact_roles_do_not_claim_replay() -> None:
    assert (
        _artifact_role(
            Path("docking/LIVE-SMOKE-001/pose_001.pdb"),
            execution_mode="live_local",
        )
        == "live_local_docking_artifact"
    )
    assert (
        _artifact_role(
            Path("analysis/analysis_manifest.json"),
            execution_mode="live_local",
        )
        == "local_live_analysis"
    )


def test_global_live_local_capability_reports_verified_scope() -> None:
    live_local = capability_matrix()["live_local"]
    assert live_local["status"] == "verified_live"
    assert live_local["enabled"] is True
    assert "ColabFold 1.6.2" in live_local["reason"]
    assert "LightDock 0.9.4" in live_local["reason"]

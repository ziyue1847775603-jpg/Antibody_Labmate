from __future__ import annotations

from labmate.analysis.ranking import normalize_metric, rank_candidates
from labmate.models import CandidateMetric


def test_normalization_constant_metric_returns_fifty() -> None:
    assert normalize_metric({"A": 7.0, "B": 7.0}, higher_is_better=True) == {"A": 50.0, "B": 50.0}


def test_lower_is_better_direction_is_applied_before_scaling() -> None:
    normalized = normalize_metric({"A": -10.0, "B": -5.0}, higher_is_better=False)
    assert normalized == {"A": 100.0, "B": 0.0}


def test_two_candidate_ranking_warns_and_writes_sensitivity(tmp_path) -> None:
    metrics = [
        CandidateMetric(
            candidate_id="CAND-001",
            mean_plddt=80,
            cdr_plddt=80,
            interface_pae=10,
            iptm=None,
            docking_best_score=-10,
            docking_topk_median=-9,
            cdr_contact_ratio=0.8,
            pose_consensus=0.8,
            clash_free_ratio=1.0,
            pose_count=2,
        ),
        CandidateMetric(
            candidate_id="CAND-002",
            mean_plddt=70,
            cdr_plddt=70,
            interface_pae=20,
            iptm=None,
            docking_best_score=-5,
            docking_topk_median=-4,
            cdr_contact_ratio=0.4,
            pose_consensus=0.4,
            clash_free_ratio=0.5,
            pose_count=2,
        ),
    ]
    result = rank_candidates(metrics, docking_higher_is_better=False, output_dir=tmp_path)
    assert result["rows"][0]["candidate_id"] == "CAND-001"
    assert result["warnings"]
    assert (tmp_path / "weight_sensitivity.csv").is_file()
    assert result["rows"][0]["norm_iptm"] == "missing"


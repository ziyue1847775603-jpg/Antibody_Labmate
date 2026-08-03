import math

import pytest

from labmate.benchmarking import (
    BenchmarkPoseResult,
    BenchmarkRunConfig,
    evaluate_case_top_k,
)


def _config(**updates: object) -> BenchmarkRunConfig:
    values = {
        "dataset_manifest_sha256": "a" * 64,
        "docking_backend_version": "0.9.4",
        "swarms": 3,
        "glowworms": 20,
        "gso_steps": 50,
        "poses_per_case": 10,
        "seed": 0,
        "timeout_seconds": 3600,
        "minimum_valid_pose_count": 1,
        "software_versions": {"labmate": "0.4.0", "lightdock": "0.9.4"},
    }
    values.update(updates)
    return BenchmarkRunConfig.model_validate(values)


def _pose(rank: int, category: str, *, fnat: float = 0.2) -> BenchmarkPoseResult:
    return BenchmarkPoseResult(
        global_tool_score_rank=rank,
        status="evaluated",
        native_score=100.0 - rank,
        category=category,
        fnat=fnat,
        i_rmsd=3.0,
        l_rmsd=8.0,
    )


def test_run_config_is_frozen_and_rejects_parameter_hash_tampering() -> None:
    config = _config()
    assert len(config.fixed_parameters_sha256) == 64
    with pytest.raises(ValueError, match="hash mismatch"):
        _config(fixed_parameters_sha256="b" * 64)
    with pytest.raises(ValueError, match="cannot exceed"):
        _config(poses_per_case=1, minimum_valid_pose_count=2)


def test_tool_ranked_top_k_and_oracle_are_separate() -> None:
    poses = [
        _pose(1, "incorrect", fnat=0.0),
        _pose(2, "incorrect", fnat=0.0),
        _pose(3, "acceptable", fnat=0.2),
        _pose(7, "high", fnat=0.9),
    ]
    result = evaluate_case_top_k(case_id="synthetic", config=_config(), poses=poses)
    assert result.top_1_success is False
    assert result.top_5_success is True
    assert result.top_10_success is True
    assert result.oracle_best_of_n_rank == 7
    assert result.oracle_best_of_n_is_reference_selected is True
    assert not hasattr(result, "affinity")


def test_failed_and_missing_ranks_are_retained_as_failures() -> None:
    config = _config(minimum_valid_pose_count=2)
    poses = [
        BenchmarkPoseResult(
            global_tool_score_rank=1,
            status="failed",
            native_score=9.0,
            failure_reason="pose generation failed",
        ),
        _pose(3, "acceptable"),
    ]
    result = evaluate_case_top_k(
        case_id="synthetic",
        config=config,
        poses=poses,
        failure_reason="minimum valid pose count not met",
    )
    assert result.status == "failed"
    assert [pose.global_tool_score_rank for pose in result.pose_results] == [1, 3]
    assert result.top_1_success is False
    assert result.top_5_success is True
    assert result.failure_reason


def test_evaluation_rejects_duplicate_or_out_of_range_rank() -> None:
    with pytest.raises(ValueError, match="unique"):
        evaluate_case_top_k(
            case_id="duplicate",
            config=_config(),
            poses=[_pose(1, "incorrect"), _pose(1, "acceptable")],
        )
    with pytest.raises(ValueError, match="exceeds"):
        evaluate_case_top_k(
            case_id="outside",
            config=_config(),
            poses=[_pose(11, "acceptable")],
        )


@pytest.mark.parametrize("native_score", [math.nan, math.inf, -math.inf])
def test_pose_result_rejects_non_finite_tool_score(native_score: float) -> None:
    with pytest.raises(ValueError, match="finite"):
        BenchmarkPoseResult(
            global_tool_score_rank=1,
            status="failed",
            native_score=native_score,
            failure_reason="synthetic",
        )

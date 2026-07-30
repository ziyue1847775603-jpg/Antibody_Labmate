"""Frozen benchmark configuration and reference-only top-k aggregation."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .metrics import CATEGORY_DEFINITION_ID, METRIC_DEFINITION_ID

SHA256_PATTERN = r"^[0-9a-f]{64}$"
CATEGORY_ORDER = {"incorrect": 0, "acceptable": 1, "medium": 2, "high": 3}


def _canonical_sha256(payload: dict[str, object]) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class BenchmarkRunConfig(BaseModel):
    """One immutable parameter set shared by every case in one benchmark run."""

    model_config = ConfigDict(extra="forbid")
    schema_version: int = 1
    dataset_manifest_sha256: str = Field(pattern=SHA256_PATTERN)
    metric_definition_id: Literal["capri_dockq_2016_v1"] = METRIC_DEFINITION_ID
    category_definition_id: Literal[
        "capri_quality_dockq_paper_2016_v1"
    ] = CATEGORY_DEFINITION_ID
    docking_backend: Literal["lightdock"] = "lightdock"
    docking_backend_version: str
    scoring_function: str = "fastdfire"
    swarms: int = Field(ge=1)
    glowworms: int = Field(ge=1)
    gso_steps: int = Field(ge=1)
    poses_per_case: int = Field(ge=1, le=100)
    seed: int = Field(ge=0)
    timeout_seconds: int = Field(ge=1, le=14400)
    minimum_valid_pose_count: int = Field(ge=1, le=100)
    global_rank_method: Literal[
        "lightdock_native_score_cross_swarm_sort_v1"
    ] = "lightdock_native_score_cross_swarm_sort_v1"
    success_category_threshold: Literal[
        "acceptable", "medium", "high"
    ] = "acceptable"
    missing_rank_policy: Literal["count_missing_as_failure"] = (
        "count_missing_as_failure"
    )
    started_at: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z")
    )
    software_versions: dict[str, str]
    fixed_parameters_sha256: str = ""

    def fixed_parameters(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "dataset_manifest_sha256": self.dataset_manifest_sha256,
            "metric_definition_id": self.metric_definition_id,
            "category_definition_id": self.category_definition_id,
            "docking_backend": self.docking_backend,
            "docking_backend_version": self.docking_backend_version,
            "scoring_function": self.scoring_function,
            "swarms": self.swarms,
            "glowworms": self.glowworms,
            "gso_steps": self.gso_steps,
            "poses_per_case": self.poses_per_case,
            "seed": self.seed,
            "timeout_seconds": self.timeout_seconds,
            "minimum_valid_pose_count": self.minimum_valid_pose_count,
            "global_rank_method": self.global_rank_method,
            "success_category_threshold": self.success_category_threshold,
            "missing_rank_policy": self.missing_rank_policy,
            "software_versions": self.software_versions,
        }

    @model_validator(mode="after")
    def freeze_hash(self) -> "BenchmarkRunConfig":
        if self.minimum_valid_pose_count > self.poses_per_case:
            raise ValueError("minimum_valid_pose_count cannot exceed poses_per_case")
        expected = _canonical_sha256(self.fixed_parameters())
        if self.fixed_parameters_sha256 and self.fixed_parameters_sha256 != expected:
            raise ValueError("fixed benchmark parameter hash mismatch")
        self.fixed_parameters_sha256 = expected
        return self


class BenchmarkPoseResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    global_tool_score_rank: int = Field(ge=1)
    status: Literal["evaluated", "failed"]
    native_score: float
    category: Literal["high", "medium", "acceptable", "incorrect"] | None = None
    fnat: float | None = None
    i_rmsd: float | None = None
    l_rmsd: float | None = None
    failure_reason: str | None = None

    @model_validator(mode="after")
    def finite_metrics(self) -> "BenchmarkPoseResult":
        if not math.isfinite(self.native_score):
            raise ValueError("tool-native score must be finite")
        values = (self.fnat, self.i_rmsd, self.l_rmsd)
        if self.status == "evaluated":
            if self.category is None or any(value is None for value in values):
                raise ValueError("evaluated pose requires CAPRI metrics and category")
            if not all(math.isfinite(float(value)) for value in values):
                raise ValueError("CAPRI metrics must be finite")
        elif not self.failure_reason:
            raise ValueError("failed pose requires a failure reason")
        return self


class BenchmarkCaseResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: int = 1
    case_id: str
    status: Literal["completed", "failed"]
    config_sha256: str = Field(pattern=SHA256_PATTERN)
    metric_definition_id: str = METRIC_DEFINITION_ID
    category_definition_id: str = CATEGORY_DEFINITION_ID
    requested_pose_count: int = Field(ge=1)
    pose_results: list[BenchmarkPoseResult]
    top_1_success: bool
    top_5_success: bool
    top_10_success: bool
    oracle_best_of_n_rank: int | None
    oracle_best_of_n_is_reference_selected: bool = True
    warnings: list[str] = Field(default_factory=list)
    failure_reason: str | None = None
    unsupported_claims: list[str] = Field(
        default_factory=lambda: [
            "no affinity validation",
            "no experimental validation",
            "no therapeutic validation",
            "no sequence-generation validation",
            "no generalization claim from a small pilot",
            "no comparison to competing methods unless run under matched conditions",
        ]
    )


def _successful_at_k(
    poses: list[BenchmarkPoseResult], *, k: int, category_threshold: str
) -> bool:
    required = CATEGORY_ORDER[category_threshold]
    return any(
        pose.status == "evaluated"
        and pose.global_tool_score_rank <= k
        and pose.category is not None
        and CATEGORY_ORDER[pose.category] >= required
        for pose in poses
    )


def evaluate_case_top_k(
    *,
    case_id: str,
    config: BenchmarkRunConfig,
    poses: list[BenchmarkPoseResult],
    failure_reason: str | None = None,
) -> BenchmarkCaseResult:
    ranks = [pose.global_tool_score_rank for pose in poses]
    if len(ranks) != len(set(ranks)):
        raise ValueError("benchmark pose global ranks must be unique")
    if any(rank > config.poses_per_case for rank in ranks):
        raise ValueError("benchmark pose rank exceeds frozen poses_per_case")
    evaluated = [pose for pose in poses if pose.status == "evaluated"]
    oracle_rank = None
    if evaluated:
        oracle_rank = max(
            evaluated,
            key=lambda pose: (
                CATEGORY_ORDER[pose.category or "incorrect"],
                pose.fnat if pose.fnat is not None else -1.0,
                -(pose.i_rmsd if pose.i_rmsd is not None else math.inf),
                -(pose.l_rmsd if pose.l_rmsd is not None else math.inf),
                -pose.global_tool_score_rank,
            ),
        ).global_tool_score_rank
    status = (
        "completed"
        if len(evaluated) >= config.minimum_valid_pose_count
        else "failed"
    )
    return BenchmarkCaseResult(
        case_id=case_id,
        status=status,
        config_sha256=config.fixed_parameters_sha256,
        requested_pose_count=config.poses_per_case,
        pose_results=sorted(poses, key=lambda pose: pose.global_tool_score_rank),
        top_1_success=_successful_at_k(
            poses, k=1, category_threshold=config.success_category_threshold
        ),
        top_5_success=_successful_at_k(
            poses, k=5, category_threshold=config.success_category_threshold
        ),
        top_10_success=_successful_at_k(
            poses, k=10, category_threshold=config.success_category_threshold
        ),
        oracle_best_of_n_rank=oracle_rank,
        failure_reason=failure_reason if status == "failed" else None,
    )

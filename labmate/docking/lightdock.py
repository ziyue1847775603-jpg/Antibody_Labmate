"""LightDock-shaped Replay parser and an explicit Live capability gate."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from labmate.docking.base import DockingProvider
from labmate.errors import FixtureIntegrityError, LiveCapabilityUnavailable
from labmate.models import Capability, CapabilityStatus

REQUIRED_COLUMNS = {
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
}


@dataclass(frozen=True)
class ParsedDockingPose:
    candidate_id: str
    pose_rank: int
    pose_id: str
    raw_score: float
    score_name: str
    score_direction: str
    complex_path: str
    provider: str
    provider_version: str
    source_kind: str
    tool_execution: str


class LightDockProvider(DockingProvider):
    """Default provider contract; only fixed-output parsing exists in P0."""

    def preflight(self) -> Capability:
        return Capability(
            name="LightDockProvider",
            status=CapabilityStatus.REPLAY_ONLY,
            enabled=True,
            provider="lightdock",
            version="not-executed-in-p0",
            license_status="GPL-3.0 external tool; not bundled or invoked",
            reason=(
                "P0 only parses a project-authored synthetic fixture with a LightDock-shaped schema. "
                "No LightDock executable, source, or third-party output is bundled."
            ),
        )

    def parse_replay_output(self, score_file: Path) -> list[ParsedDockingPose]:
        with score_file.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            columns = set(reader.fieldnames or [])
            missing = REQUIRED_COLUMNS - columns
            if missing:
                raise FixtureIntegrityError(f"docking score 缺少字段: {', '.join(sorted(missing))}")
            poses: list[ParsedDockingPose] = []
            for row_number, row in enumerate(reader, start=2):
                try:
                    pose = ParsedDockingPose(
                        candidate_id=row["candidate_id"],
                        pose_rank=int(row["pose_rank"]),
                        pose_id=row["pose_id"],
                        raw_score=float(row["raw_score"]),
                        score_name=row["score_name"],
                        score_direction=row["score_direction"],
                        complex_path=row["complex_path"],
                        provider=row["provider"],
                        provider_version=row["provider_version"],
                        source_kind=row["source_kind"],
                        tool_execution=row["tool_execution"],
                    )
                except (KeyError, TypeError, ValueError) as exc:
                    raise FixtureIntegrityError(f"docking score 第 {row_number} 行无效") from exc
                if pose.provider != "lightdock":
                    raise FixtureIntegrityError("P0 默认 docking provider 必须声明为 lightdock")
                if pose.score_direction not in {"higher_is_better", "lower_is_better"}:
                    raise FixtureIntegrityError(f"未知 score 方向: {pose.score_direction}")
                if pose.source_kind != "project_authored_synthetic_replay":
                    raise FixtureIntegrityError("P0 fixture 必须明确声明为项目自建合成 Replay 数据")
                if pose.tool_execution != "not_executed":
                    raise FixtureIntegrityError("P0 fixture 不得声称执行了 LightDock")
                if pose.pose_rank < 1 or not pose.candidate_id.startswith("CAND-"):
                    raise FixtureIntegrityError(f"docking pose 标识无效: {pose}")
                poses.append(pose)
        if not poses:
            raise FixtureIntegrityError("docking score 文件没有 pose")
        return sorted(poses, key=lambda item: (item.candidate_id, item.pose_rank))

    def dock(self, *args: object, **kwargs: object) -> list[object]:
        raise LiveCapabilityUnavailable(
            "LightDock Live execution is unavailable in Phase 1 Replay MVP; only verified fixture parsing is implemented."
        )


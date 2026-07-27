"""Sequential stage state machine for S00-S10."""

from __future__ import annotations

from datetime import UTC, datetime

from labmate.errors import StateTransitionError
from labmate.models import ExecutionKind, StageRecord, StageStatus

STAGES: tuple[tuple[str, str], ...] = (
    ("S00", "Job initialization"),
    ("S01", "Input validation"),
    ("S02", "Candidate generation artifact replay"),
    ("S03", "Sequence quality control"),
    ("S04", "Structure prediction artifact replay"),
    ("S05", "Structure quality control"),
    ("S06", "Docking artifact replay"),
    ("S07", "Interface analysis"),
    ("S08", "Candidate ranking"),
    ("S09", "Visualization"),
    ("S10", "Reporting"),
)

LIVE_LOCAL_STAGES: tuple[tuple[str, str], ...] = (
    ("S00", "Job initialization"),
    ("S01", "Input validation"),
    ("S02", "Candidate input transfer"),
    ("S03", "Sequence quality control"),
    ("S04", "Local structure prediction"),
    ("S05", "Structure quality control"),
    ("S06", "Local docking"),
    ("S07", "Interface analysis"),
    ("S08", "Candidate ranking"),
    ("S09", "Visualization"),
    ("S10", "Reporting"),
)


def utc_now() -> datetime:
    return datetime.now(UTC)


class StageStateMachine:
    def __init__(
        self,
        *,
        fixture_id: str | None = None,
        fixture_manifest_hash: str | None = None,
        execution_kind: ExecutionKind = ExecutionKind.REPLAY,
        provider: str = "ReplayBackend",
        stages: tuple[tuple[str, str], ...] = STAGES,
    ) -> None:
        self.records = [
            StageRecord(
                stage_id=stage_id,
                name=name,
                execution_kind=execution_kind,
                provider=provider,
                fixture_id=fixture_id,
                fixture_manifest_hash=fixture_manifest_hash,
            )
            for stage_id, name in stages
        ]

    def _record(self, stage_id: str) -> StageRecord:
        for record in self.records:
            if record.stage_id == stage_id:
                return record
        raise StateTransitionError(f"未知阶段: {stage_id}")

    def start(self, stage_id: str, *, input_hashes: dict[str, str] | None = None, notes: list[str] | None = None) -> StageRecord:
        record = self._record(stage_id)
        index = self.records.index(record)
        if record.status is not StageStatus.PENDING:
            raise StateTransitionError(f"{stage_id} 不能从 {record.status} 进入 running")
        previous = self.records[:index]
        if any(item.status not in {StageStatus.SUCCEEDED, StageStatus.SKIPPED_OPTIONAL} for item in previous):
            raise StateTransitionError(f"{stage_id} 的前置阶段尚未完成")
        record.status = StageStatus.RUNNING
        record.started_at = utc_now()
        record.input_hashes = input_hashes or {}
        record.notes.extend(notes or [])
        return record

    def succeed(self, stage_id: str, *, output_hashes: dict[str, str] | None = None, notes: list[str] | None = None) -> StageRecord:
        record = self._record(stage_id)
        if record.status is not StageStatus.RUNNING:
            raise StateTransitionError(f"{stage_id} 不能从 {record.status} 进入 succeeded")
        record.status = StageStatus.SUCCEEDED
        record.ended_at = utc_now()
        record.output_hashes = output_hashes or {}
        record.notes.extend(notes or [])
        return record

    def skip_optional(self, stage_id: str, *, note: str) -> StageRecord:
        record = self._record(stage_id)
        if record.status is not StageStatus.PENDING:
            raise StateTransitionError(f"{stage_id} 不能从 {record.status} 跳过")
        index = self.records.index(record)
        if any(
            item.status not in {StageStatus.SUCCEEDED, StageStatus.SKIPPED_OPTIONAL}
            for item in self.records[:index]
        ):
            raise StateTransitionError(f"{stage_id} 的前置阶段尚未完成")
        now = utc_now()
        record.status = StageStatus.SKIPPED_OPTIONAL
        record.started_at = now
        record.ended_at = now
        record.notes.append(note)
        return record

    def fail(self, stage_id: str, error: str) -> StageRecord:
        record = self._record(stage_id)
        if record.status is not StageStatus.RUNNING:
            raise StateTransitionError(f"{stage_id} 不能从 {record.status} 进入 failed")
        record.status = StageStatus.FAILED
        record.ended_at = utc_now()
        record.error = error
        return record

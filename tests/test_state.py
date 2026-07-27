from __future__ import annotations

import pytest

from labmate.errors import StateTransitionError
from labmate.models import ExecutionKind, StageStatus
from labmate.state import LIVE_LOCAL_STAGES, STAGES, StageStateMachine


def test_state_machine_enforces_stage_order() -> None:
    state = StageStateMachine(fixture_id="demo_001", fixture_manifest_hash="a" * 64)
    with pytest.raises(StateTransitionError, match="前置"):
        state.start("S01")
    state.start("S00")
    state.succeed("S00")
    assert state.records[0].status is StageStatus.SUCCEEDED
    with pytest.raises(StateTransitionError):
        state.start("S00")


def test_optional_visualization_can_be_skipped_after_prior_stages() -> None:
    state = StageStateMachine(fixture_id="demo_001", fixture_manifest_hash="b" * 64)
    for stage_id, _ in STAGES[:9]:
        state.start(stage_id)
        state.succeed(stage_id)
    state.skip_optional("S09", note="PyMOL unavailable")
    state.start("S10")
    state.succeed("S10")
    assert state.records[9].status is StageStatus.SKIPPED_OPTIONAL
    assert state.records[10].status is StageStatus.SUCCEEDED


def test_live_local_stage_names_do_not_claim_replay() -> None:
    state = StageStateMachine(
        execution_kind=ExecutionKind.LIVE,
        provider="LiveLocalBackend",
        stages=LIVE_LOCAL_STAGES,
    )
    assert [record.stage_id for record in state.records] == [
        f"S{index:02d}" for index in range(11)
    ]
    assert all("replay" not in record.name.lower() for record in state.records)

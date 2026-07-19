from __future__ import annotations

import pytest

from labmate.docking.lightdock import LightDockProvider
from labmate.errors import LiveCapabilityUnavailable
from labmate.models import CapabilityStatus


def test_lightdock_provider_is_truthfully_replay_only(fixture_root) -> None:
    provider = LightDockProvider()
    capability = provider.preflight()
    assert capability.status is CapabilityStatus.REPLAY_ONLY
    assert capability.version == "not-executed-in-p0"
    poses = provider.parse_replay_output(fixture_root / "docking_output" / "docking_scores.csv")
    assert len(poses) == 12
    assert {pose.source_kind for pose in poses} == {"project_authored_synthetic_replay"}
    assert {pose.tool_execution for pose in poses} == {"not_executed"}


def test_live_dock_call_is_hard_disabled() -> None:
    with pytest.raises(LiveCapabilityUnavailable, match="unavailable"):
        LightDockProvider().dock()


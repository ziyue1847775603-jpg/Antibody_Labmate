"""Capability registry for Replay and the separately installed local adapter."""

from labmate.docking.lightdock import LightDockProvider


def default_provider() -> LightDockProvider:
    return LightDockProvider()


def capability_matrix() -> dict[str, object]:
    provider = default_provider()
    return {
        "replay": {
            "status": "replay_only",
            "enabled": True,
            "reason": "Verified demo input can replay fixed, hash-checked artifacts.",
        },
        "live_local": {
            "status": "verified_live",
            "enabled": True,
            "reason": "End-to-end verified for the recorded one-candidate WSL2 smoke configuration with ColabFold 1.6.2 offline single_sequence and external LightDock 0.9.4; other versions and configurations remain outside that validation scope.",
        },
        "live_remote": {
            "status": "unavailable",
            "enabled": False,
            "reason": "Phase 3 not implemented; no API or worker is included.",
        },
        "lightdock": provider.preflight().model_dump(mode="json"),
    }

"""Single-provider registry for the Phase 1 scope."""

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
            "status": "unavailable",
            "enabled": False,
            "reason": "Phase 2 not implemented or end-to-end verified.",
        },
        "live_remote": {
            "status": "unavailable",
            "enabled": False,
            "reason": "Phase 3 not implemented; no API or worker is included.",
        },
        "lightdock": provider.preflight().model_dump(mode="json"),
    }


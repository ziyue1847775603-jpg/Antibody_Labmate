"""Full-workflow and structure-prediction backend exports."""

from typing import Any

from labmate.backends.base import ComputeBackend, PredictionBackend, PredictionResult

__all__ = [
    "BenchmarkLocalBackend",
    "ColabFoldBackend",
    "ComputeBackend",
    "IgFoldBackend",
    "LiveLocalBackend",
    "PREDICTION_BACKEND_NAMES",
    "PredictionBackend",
    "PredictionResult",
    "ReplayBackend",
    "get_backend",
]


def __getattr__(name: str) -> Any:
    """Resolve concrete backends lazily to avoid workflow import cycles."""

    if name == "BenchmarkLocalBackend":
        from labmate.backends.benchmark import BenchmarkLocalBackend

        return BenchmarkLocalBackend
    if name == "ColabFoldBackend":
        from labmate.backends.colabfold import ColabFoldBackend

        return ColabFoldBackend
    if name == "IgFoldBackend":
        from labmate.backends.igfold import IgFoldBackend

        return IgFoldBackend
    if name == "LiveLocalBackend":
        from labmate.backends.local import LiveLocalBackend

        return LiveLocalBackend
    if name in {"PREDICTION_BACKEND_NAMES", "get_backend"}:
        from labmate.backends.registry import (
            PREDICTION_BACKEND_NAMES,
            get_backend,
        )

        return {
            "PREDICTION_BACKEND_NAMES": PREDICTION_BACKEND_NAMES,
            "get_backend": get_backend,
        }[name]
    if name == "ReplayBackend":
        from labmate.backends.replay import ReplayBackend

        return ReplayBackend
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

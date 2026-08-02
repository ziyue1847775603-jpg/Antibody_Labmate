"""Registry for pluggable structure-prediction backends."""

from __future__ import annotations

from pathlib import Path

from labmate.backends.base import PredictionBackend
from labmate.backends.colabfold import ColabFoldBackend
from labmate.backends.igfold import IgFoldBackend
from labmate.backends.replay import ReplayBackend

PREDICTION_BACKEND_NAMES = ("replay", "colabfold", "igfold")


def _default_fixture_root() -> Path:
    return Path(__file__).resolve().parents[2] / "fixtures" / "demo_001"


def get_backend(name: str, **options: object) -> PredictionBackend:
    """Create a prediction backend or raise a clear configuration error."""

    normalized = name.strip().lower()
    if normalized == "replay":
        fixture_root = options.pop("fixture_root", _default_fixture_root())
        if options:
            raise TypeError(
                "Unsupported Replay backend options: "
                + ", ".join(sorted(options))
            )
        return ReplayBackend(Path(fixture_root))
    if normalized == "colabfold":
        return ColabFoldBackend(**options)  # type: ignore[arg-type]
    if normalized == "igfold":
        return IgFoldBackend(**options)  # type: ignore[arg-type]
    supported = ", ".join(PREDICTION_BACKEND_NAMES)
    raise ValueError(
        f"Unknown prediction backend '{name}'. Supported backends: {supported}"
    )

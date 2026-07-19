"""Docking provider interface with Live execution intentionally unavailable."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from labmate.models import Capability


class DockingProvider(ABC):
    @abstractmethod
    def preflight(self) -> Capability:
        """Return a truthful capability state."""

    @abstractmethod
    def parse_replay_output(self, score_file: Path) -> list[object]:
        """Parse a pre-verified fixed output; never execute an external tool."""

    @abstractmethod
    def dock(self, *args: object, **kwargs: object) -> list[object]:
        """Live execution hook. Replay P0 implementations must reject it."""


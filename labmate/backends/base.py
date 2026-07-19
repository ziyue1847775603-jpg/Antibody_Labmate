"""Backend contract shared by future modes; only Replay is implemented."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from labmate.models import Capability, JobSpec, RunResult


class ComputeBackend(ABC):
    @abstractmethod
    def preflight(self, job: JobSpec, antigen_bytes: bytes) -> Capability:
        """Verify the backend can truthfully process this exact input."""

    @abstractmethod
    def submit(self, job: JobSpec, antigen_bytes: bytes, output_root: Path) -> RunResult:
        """Run or replay a job."""

    @abstractmethod
    def status(self, job_id: str) -> str:
        """Return a coarse status."""

    @abstractmethod
    def cancel(self, job_id: str) -> bool:
        """Attempt cancellation."""

    @abstractmethod
    def collect(self, job_id: str) -> RunResult:
        """Collect a completed result."""


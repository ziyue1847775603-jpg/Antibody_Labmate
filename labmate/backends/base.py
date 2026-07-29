"""Backend contracts for full workflows and pluggable structure prediction."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from labmate.models import Capability, JobSpec, RunResult


PREDICTION_AMINO_ACIDS = frozenset("ACDEFGHIKLMNPQRSTVWY")


class PredictionResult(BaseModel):
    """Provider-neutral result consumed by downstream workflow stages."""

    model_config = ConfigDict(extra="forbid")

    pdb_path: Path | None = None
    backend_name: str
    status: Literal["succeeded", "unavailable", "failed"]
    metadata: dict[str, object] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


def normalize_prediction_sequence(value: str | None, *, label: str) -> str | None:
    """Normalize and validate a complete antibody-chain sequence."""

    if value is None:
        return None
    normalized = value.strip().upper()
    if not normalized:
        raise ValueError(f"{label} must not be empty")
    invalid = sorted(set(normalized) - PREDICTION_AMINO_ACIDS)
    if invalid:
        raise ValueError(
            f"{label} contains unsupported amino-acid symbols: {''.join(invalid)}"
        )
    return normalized


class PredictionBackend(ABC):
    """Stage-level interface for antibody structure prediction providers."""

    name: str

    @abstractmethod
    def predict(
        self,
        heavy_chain: str,
        light_chain: str | None,
        antigen_pdb: Path | None = None,
        output_dir: Path | None = None,
    ) -> PredictionResult:
        """Predict or replay one antibody structure without docking it."""


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

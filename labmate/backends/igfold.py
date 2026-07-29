"""Optional local IgFold structure-prediction wrapper."""

from __future__ import annotations

import importlib.util
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from labmate.backends.base import (
    PredictionBackend,
    PredictionResult,
    normalize_prediction_sequence,
)


class IgFoldRunnerProtocol(Protocol):
    def fold(self, output_path: str, *, sequences: dict[str, str]) -> object:
        """Write an antibody PDB to ``output_path``."""


class IgFoldBackend(PredictionBackend):
    """Run an installed IgFold package; model installation stays external."""

    name = "igfold"

    def __init__(
        self,
        *,
        runner_factory: Callable[[], IgFoldRunnerProtocol] | None = None,
    ) -> None:
        self.runner_factory = runner_factory

    def _load_runner(self) -> IgFoldRunnerProtocol | None:
        if self.runner_factory is not None:
            return self.runner_factory()
        if importlib.util.find_spec("igfold") is None:
            return None
        from igfold import IgFoldRunner  # type: ignore[import-not-found]

        return IgFoldRunner()

    def predict(
        self,
        heavy_chain: str,
        light_chain: str | None,
        antigen_pdb: Path | None = None,
        output_dir: Path | None = None,
    ) -> PredictionResult:
        del antigen_pdb
        heavy = normalize_prediction_sequence(heavy_chain, label="heavy_chain")
        light = normalize_prediction_sequence(light_chain, label="light_chain")
        if (
            self.runner_factory is None
            and importlib.util.find_spec("igfold") is None
        ):
            return PredictionResult(
                backend_name=self.name,
                status="unavailable",
                warnings=["IgFold backend unavailable"],
            )
        if output_dir is None:
            return PredictionResult(
                backend_name=self.name,
                status="failed",
                warnings=["IgFold prediction requires an explicit output_dir"],
            )
        output_dir = output_dir.resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        pdb_path = output_dir / "igfold_prediction.pdb"
        if pdb_path.exists():
            return PredictionResult(
                backend_name=self.name,
                status="failed",
                warnings=[
                    "IgFold prediction output already exists: igfold_prediction.pdb"
                ],
            )
        try:
            runner = self._load_runner()
        except Exception as exc:  # external package initialization boundary
            return PredictionResult(
                backend_name=self.name,
                status="failed",
                warnings=[f"IgFold initialization failed: {exc}"],
            )
        if runner is None:  # defensive: availability changed during lazy import
            return PredictionResult(
                backend_name=self.name,
                status="unavailable",
                warnings=["IgFold backend unavailable"],
            )

        sequences = {"H": heavy}
        if light is not None:
            sequences["L"] = light
        try:
            runner.fold(str(pdb_path), sequences=sequences)
        except Exception as exc:  # external inference boundary
            return PredictionResult(
                backend_name=self.name,
                status="failed",
                warnings=[f"IgFold inference failed: {exc}"],
            )
        if not pdb_path.is_file() or pdb_path.stat().st_size == 0:
            return PredictionResult(
                backend_name=self.name,
                status="failed",
                warnings=["IgFold completed but produced no PDB file"],
            )
        return PredictionResult(
            pdb_path=pdb_path,
            backend_name=self.name,
            status="succeeded",
            metadata={
                "chains": sorted(sequences),
                "model_source": "user-installed IgFold environment",
            },
        )

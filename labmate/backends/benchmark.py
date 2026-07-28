"""Benchmark Local backend using only user-installed external LightDock."""

from pathlib import Path

from labmate.benchmark_local import execute_benchmark_local
from labmate.models import BenchmarkLocalJobSpec, RunResult


class BenchmarkLocalBackend:
    def submit(
        self,
        job: BenchmarkLocalJobSpec,
        *,
        antibody_path: Path,
        antigen_path: Path,
        reference_path: Path | None,
        output_root: Path,
    ) -> RunResult:
        return execute_benchmark_local(
            job=job,
            antibody_path=antibody_path,
            antigen_path=antigen_path,
            reference_path=reference_path,
            output_root=output_root,
        )

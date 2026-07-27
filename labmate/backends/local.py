"""Live Local backend; tools remain user-installed external dependencies."""

from pathlib import Path

from labmate.live_local import execute_live_local, preflight_live_local
from labmate.models import Capability, LiveLocalJobSpec, RunResult


class LiveLocalBackend:
    def preflight(self, job: LiveLocalJobSpec) -> dict[str, Capability]:
        return preflight_live_local(job)

    def submit(
        self,
        job: LiveLocalJobSpec,
        *,
        candidate_fasta: Path,
        regions_file: Path,
        antigen_bytes: bytes,
        output_root: Path,
    ) -> RunResult:
        return execute_live_local(
            job=job,
            candidate_fasta=candidate_fasta,
            regions_file=regions_file,
            antigen_bytes=antigen_bytes,
            output_root=output_root,
        )

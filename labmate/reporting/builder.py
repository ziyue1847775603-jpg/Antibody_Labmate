"""Render a single-file, autoescaped, offline Replay report."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from labmate.config import SCIENTIFIC_LIMITATION
from labmate.models import JobSpec, StageRecord


def build_report(
    output_path: Path,
    *,
    run_id: str,
    created_at: str,
    job: JobSpec,
    input_hashes: dict[str, str],
    fixture_manifest_hash: str,
    antigen_summary: dict[str, Any],
    stages: list[StageRecord],
    structure_rows: list[dict[str, Any]],
    docking_rows: list[dict[str, Any]],
    ranking_rows: list[dict[str, Any]],
    interface_rows: list[dict[str, Any]],
    consensus_rows: list[dict[str, Any]],
    sensitivity_rows: list[dict[str, Any]],
    warnings: list[str],
    artifact_preview: list[dict[str, Any]],
) -> Path:
    template_dir = Path(__file__).resolve().parent / "templates"
    environment = Environment(
        loader=FileSystemLoader(template_dir),
        # The template filename ends in .html.j2, so extension-based selection
        # would inspect only .j2. Reports are always HTML: fail closed and escape
        # every dynamic value unconditionally.
        autoescape=True,
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = environment.get_template("report.html.j2")
    output_path.write_text(
        template.render(
            run_id=run_id,
            created_at=created_at,
            replay_label="REPLAY",
            job=job,
            cdr_regions=job.antibody.region_map(),
            input_hashes=input_hashes,
            fixture_manifest_hash=fixture_manifest_hash,
            antigen_summary=antigen_summary,
            stages=stages,
            structure_rows=structure_rows,
            docking_rows=docking_rows,
            ranking_rows=ranking_rows,
            interface_rows=interface_rows,
            consensus_rows=consensus_rows,
            sensitivity_rows=sensitivity_rows,
            warnings=warnings,
            artifact_preview=artifact_preview,
            scientific_limitation=SCIENTIFIC_LIMITATION,
        ),
        encoding="utf-8",
    )
    return output_path


def build_live_report(
    output_path: Path,
    *,
    run_id: str,
    created_at: str,
    job: dict[str, Any],
    input_hashes: dict[str, str],
    antigen_summary: dict[str, Any],
    stages: list[StageRecord],
    ranking_rows: list[dict[str, Any]],
    warnings: list[str],
    tool_versions: dict[str, str | None],
) -> Path:
    """Render the deliberately separate Live Local report; never use Replay branding."""
    environment = Environment(
        loader=FileSystemLoader(Path(__file__).resolve().parent / "templates"),
        autoescape=True,
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    output_path.write_text(
        environment.get_template("live_report.html.j2").render(
            run_id=run_id, created_at=created_at, job=job, input_hashes=input_hashes,
            antigen_summary=antigen_summary, stages=stages, ranking_rows=ranking_rows,
            warnings=warnings, tool_versions=tool_versions,
        ),
        encoding="utf-8",
    )
    return output_path

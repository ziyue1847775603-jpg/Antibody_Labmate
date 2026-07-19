from __future__ import annotations

from labmate.reporting.builder import build_report
from labmate.state import StageStateMachine


def test_report_autoescapes_dynamic_text_and_stays_offline(tmp_path, demo_job) -> None:
    stages = StageStateMachine(fixture_id="demo_001", fixture_manifest_hash="f" * 64).records
    output = tmp_path / "report.html"
    build_report(
        output,
        run_id='<script>alert("x")</script>',
        created_at="2026-07-19T00:00:00Z",
        job=demo_job,
        input_hashes={"input_bundle_sha256": "a" * 64},
        fixture_manifest_hash="b" * 64,
        antigen_summary={"chains": ["A"], "atom_count": 3, "residue_count": 1, "selected_model": 1},
        stages=stages,
        structure_rows=[],
        docking_rows=[],
        ranking_rows=[],
        interface_rows=[],
        consensus_rows=[],
        sensitivity_rows=[],
        warnings=['<img src=x onerror="alert(1)">'],
        artifact_preview=[],
    )
    html = output.read_text(encoding="utf-8")
    assert '<script>alert("x")</script>' not in html
    assert "&lt;script&gt;alert" in html
    assert '<img src=x onerror="alert(1)">' not in html
    assert "&lt;img src=x" in html
    assert "cdn." not in html.lower()
    assert "https://" not in html.lower()


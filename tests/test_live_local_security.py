import json
from pathlib import Path

import pytest

from labmate.errors import FixtureIntegrityError, InputValidationError, LabmateError
from labmate.live_local import (
    _audit_run_privacy,
    _live_interface_config,
    _read_regions,
    _redact_text,
    _sanitized_job_snapshot,
)
from labmate.models import LiveLocalJobSpec
from labmate.reporting.builder import build_live_report
from labmate.workflow import _parse_fasta


def _live_job() -> LiveLocalJobSpec:
    return LiveLocalJobSpec.model_validate(
        {
            "schema_version": "2.0.0",
            "mode": "live_local",
            "backend": "local",
            "candidate_fasta": "candidates.fasta",
            "candidate_regions_file": "candidate_regions.csv",
            "antigen": {"file": "antigen.pdb", "chains": ["A"]},
            "tools": {
                "colabfold_batch": "/root/miniconda3/envs/colabfold/bin/colabfold_batch",
                "lightdock_setup": "/mnt/d/external/lightdock/bin/lightdock3_setup.py",
                "lightdock_run": "/mnt/d/external/lightdock/bin/lightdock3.py",
                "lightdock_generate": "/mnt/d/external/lightdock/bin/lgd_generate_conformations.py",
                "colabfold_args": [
                    "--msa-mode",
                    "single_sequence",
                    "--data",
                    "/mnt/d/private/models",
                    "--model-type",
                    "alphafold2_multimer_v3",
                ],
                "msa_network_policy": "offline_single_sequence",
                "model_data_policy": "preinstalled_only",
            },
            "docking": {
                "steps": 20,
                "swarms": 4,
                "glowworms": 50,
                "cores": 1,
                "top_poses_per_candidate": 3,
                "score_direction": "higher_is_better",
                "score_name": "fastdfire",
            },
            "rights_confirmed": True,
            "source_type": "project_authored_synthetic",
        }
    )


@pytest.mark.parametrize("candidate_id", ["../escape", "a/b", ".hidden", "A" * 65])
def test_live_fasta_rejects_unsafe_candidate_ids(
    tmp_path: Path, candidate_id: str
) -> None:
    fasta = tmp_path / "bad.fasta"
    fasta.write_text(
        f">{candidate_id}|VH\nACDE\n>{candidate_id}|VL\nFGHI\n",
        encoding="utf-8",
    )
    with pytest.raises(FixtureIntegrityError):
        _parse_fasta(fasta)


def test_live_fasta_rejects_duplicate_headers(tmp_path: Path) -> None:
    fasta = tmp_path / "duplicate.fasta"
    fasta.write_text(
        ">SAFE-001|VH\nACDE\n>SAFE-001|VH\nFGHI\n>SAFE-001|VL\nKLMN\n",
        encoding="utf-8",
    )
    with pytest.raises(FixtureIntegrityError, match="重复"):
        _parse_fasta(fasta)


def test_live_regions_reject_duplicate_region_rows(tmp_path: Path) -> None:
    regions = tmp_path / "candidate_regions.csv"
    regions.write_text(
        "candidate_id,chain,region,sequence\n"
        "SAFE-001,H,H-fwr1,AC\n"
        "SAFE-001,H,H-fwr1,DE\n"
        "SAFE-001,L,L-fwr1,FGHI\n",
        encoding="utf-8",
    )
    candidates = {"SAFE-001": {"H": "ACDE", "L": "FGHI"}}
    with pytest.raises(InputValidationError, match="重复"):
        _read_regions(regions, candidates)


def test_live_interface_analysis_uses_every_selected_top_pose() -> None:
    assert _live_interface_config(_live_job()).analyze_top_poses == 3


def test_redaction_and_live_report_hide_local_paths_and_tokens(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_token = "sk-" + "abcdefghijklmnopqrstuvwxyz123456"
    monkeypatch.setenv("USER", "privateuser")
    monkeypatch.setenv("PRIVATE_API_TOKEN", fake_token)
    raw = (
        "/mnt/d/privateuser/project/input.pdb "
        r"D:\Users\privateuser\project\input.pdb "
        f"token={fake_token} "
        "JAX_ENABLE_X64 shell environment variable"
    )
    redacted = _redact_text(raw, cwd=tmp_path)
    assert "/mnt/d/" not in redacted
    assert "D:\\" not in redacted
    assert "privateuser" not in redacted
    assert "abcdefghijklmnopqrstuvwxyz" not in redacted
    assert "JAX_ENABLE_X64" not in redacted

    snapshot = _sanitized_job_snapshot(_live_job(), cwd=tmp_path)
    serialized = json.dumps(snapshot)
    assert "/root/" not in serialized
    assert "/mnt/d/" not in serialized
    report = build_live_report(
        tmp_path / "report.html",
        run_id="RUN-TEST",
        created_at="2026-07-26T00:00:00Z",
        job=snapshot,
        input_hashes={"candidate_fasta_sha256": "a" * 64},
        antigen_summary={"chains": ["A"], "atom_count": 1, "residue_count": 1},
        stages=[],
        ranking_rows=[],
        warnings=[],
        tool_versions={"colabfold": "1.6.2", "lightdock_run": "0.9.4"},
    ).read_text(encoding="utf-8")
    assert "/root/" not in report
    assert "/mnt/d/" not in report
    assert "LIVE LOCAL · VERIFIED LIVE" in report


def test_privacy_audit_rejects_absolute_context_and_token(tmp_path: Path) -> None:
    bad = tmp_path / "bad.log"
    fake_token = "sk-" + "abcdefghijklmnopqrstuvwxyz123456"
    bad.write_text(
        f"/mnt/d/private/project/file token={fake_token}\n",
        encoding="utf-8",
    )
    with pytest.raises(LabmateError, match="隐私审计失败"):
        _audit_run_privacy(tmp_path, ["/mnt/d/private/project"])

from __future__ import annotations

import csv
import json
import re
import shutil
import zipfile
from pathlib import Path, PurePosixPath

import pytest

from labmate.backends.replay import ReplayBackend
from labmate.cli import main
from labmate.errors import FixtureIntegrityError
from labmate.models import JobSpec
from labmate.provenance import sha256_file


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_replay_end_to_end_matches_golden(demo_job, demo_antigen, fixture_root, tmp_path) -> None:
    result = ReplayBackend(fixture_root).submit(demo_job, demo_antigen, tmp_path)
    run_dir = Path(result.run_dir)
    golden = json.loads((fixture_root / "expected" / "golden.json").read_text(encoding="utf-8"))

    for relative in golden["required_artifacts"]:
        assert (run_dir / relative).is_file(), relative
    ranking = read_csv(run_dir / "candidate_ranking.csv")
    interfaces = read_csv(run_dir / "interface_residues.csv")
    assert [row["candidate_id"] for row in ranking] == golden["candidate_order"]
    assert len(interfaces) == golden["interface_residue_row_count"]

    report = (run_dir / "report.html").read_text(encoding="utf-8")
    for marker in golden["required_report_markers"]:
        assert marker in report
    assert str(run_dir) not in report
    assert "LightDock 未执行" in report

    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["mode"] == "replay"
    assert manifest["replay_label"] == "REPLAY"
    assert manifest["capabilities"]["live_local"]["status"] == "unavailable"
    assert manifest["capabilities"]["live_remote"]["status"] == "unavailable"
    assert manifest["capabilities"]["lightdock_provider"]["status"] == "replay_only"
    assert all(stage["execution_kind"] == "replay" for stage in manifest["stages"])
    assert manifest["stages"][9]["status"] == "skipped_optional"
    assert all(stage["status"] in {"succeeded", "skipped_optional"} for stage in manifest["stages"])
    for artifact in manifest["artifacts"]:
        assert sha256_file(run_dir / artifact["path"]) == artifact["sha256"]

    manifest_checksum = (run_dir / "manifest.sha256").read_text(encoding="utf-8").split()[0]
    assert manifest_checksum == sha256_file(run_dir / "manifest.json")
    with zipfile.ZipFile(result.zip_path) as archive:
        names = archive.namelist()
        assert "manifest.json" in names
        assert "report.html" in names
        assert all(not PurePosixPath(name).is_absolute() and ".." not in PurePosixPath(name).parts for name in names)


def test_replay_rejects_valid_but_different_cdr(demo_job, demo_antigen, fixture_root, tmp_path) -> None:
    payload = demo_job.model_dump(mode="json")
    payload["antibody"]["h_cdr1"] = "AAAAAAAA"
    changed = JobSpec.model_validate(payload)
    with pytest.raises(FixtureIntegrityError, match="输入哈希不匹配"):
        ReplayBackend(fixture_root).submit(changed, demo_antigen, tmp_path)


def test_replay_rejects_antigen_byte_mismatch(demo_job, demo_antigen, fixture_root, tmp_path) -> None:
    with pytest.raises(FixtureIntegrityError, match="输入哈希不匹配"):
        ReplayBackend(fixture_root).submit(demo_job, demo_antigen + b"\n", tmp_path)


def test_replay_rejects_tampered_fixture(demo_job, demo_antigen, fixture_root, tmp_path) -> None:
    copied = tmp_path / "demo_001"
    shutil.copytree(fixture_root, copied)
    with (copied / "docking_output" / "docking_scores.csv").open("a", encoding="utf-8") as handle:
        handle.write("tampered\n")
    with pytest.raises(FixtureIntegrityError, match="哈希不匹配"):
        ReplayBackend(copied).preflight(demo_job, demo_antigen)


def test_cli_runs_verified_demo(fixture_root, tmp_path, capsys) -> None:
    exit_code = main(
        [
            "run",
            str(fixture_root / "project.yaml"),
            "--mode",
            "replay",
            "--fixture",
            "demo_001",
            "--output",
            str(tmp_path),
        ]
    )
    captured = capsys.readouterr()
    assert exit_code == 0
    payload = json.loads(captured.out)
    assert payload["mode"] == "REPLAY"
    assert Path(payload["zip"]).is_file()


def test_report_log_manifest_and_run_zip_do_not_leak_local_context(
    demo_job, demo_antigen, fixture_root, tmp_path, monkeypatch
) -> None:
    sentinel = "LABMATE_HARDENING_SENTINEL_DO_NOT_EXPORT"
    monkeypatch.setenv("LABMATE_PRIVATE_TEST_VALUE", sentinel)
    result = ReplayBackend(fixture_root).submit(demo_job, demo_antigen, tmp_path)
    run_dir = Path(result.run_dir)

    # A leading slash followed by two path components identifies a POSIX-style
    # absolute path while avoiding normal MIME types and closing HTML tags.
    posix_absolute = re.compile(rb"(?<![A-Za-z0-9])/(?:[A-Za-z0-9_.-]+/){2,}")
    windows_absolute = re.compile(rb"[A-Za-z]:[\\/][^\r\n\"<>]+")
    forbidden_values = [sentinel.encode(), str(tmp_path).encode()]

    def assert_private_context_absent(name: str, data: bytes) -> None:
        for value in forbidden_values:
            assert value not in data, name
        assert posix_absolute.search(data) is None, name
        assert windows_absolute.search(data) is None, name

    for path in sorted(run_dir.rglob("*")):
        if path.is_file():
            assert_private_context_absent(path.relative_to(run_dir).as_posix(), path.read_bytes())

    report = (run_dir / "report.html").read_text(encoding="utf-8")
    log = (run_dir / "logs" / "replay.log").read_text(encoding="utf-8")
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert "REPLAY · FIXED HASH-VERIFIED DEMO · NOT LIVE COMPUTE" in report
    assert "REPLAY" in log
    assert manifest["replay_label"] == "REPLAY"

    with zipfile.ZipFile(result.zip_path) as archive:
        for name in archive.namelist():
            assert_private_context_absent(name, archive.read(name))


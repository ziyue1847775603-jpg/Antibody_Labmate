from __future__ import annotations

import hashlib
import json
import re
import shutil
import tomllib
import zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath

import pytest

from labmate import __version__
from scripts import package_project
from scripts.package_project import (
    EXCLUDED_PARTS,
    REQUIRED_RELEASE_PATHS,
    project_version,
)


def test_version_and_streamlit_deployment_contract(project_root: Path) -> None:
    pyproject = tomllib.loads((project_root / "pyproject.toml").read_text(encoding="utf-8"))
    config = tomllib.loads((project_root / ".streamlit" / "config.toml").read_text(encoding="utf-8"))
    requirements = (project_root / "requirements.txt").read_text(encoding="utf-8").splitlines()

    assert __version__ == project_version() == pyproject["project"]["version"] == "0.3.0"
    assert pyproject["project"]["requires-python"] == ">=3.11,<3.13"
    assert config["server"] == {
        "headless": True,
        "maxUploadSize": 2,
        "maxMessageSize": 5,
        "enableCORS": True,
        "enableXsrfProtection": True,
        "enableStaticServing": False,
    }
    assert config["browser"]["gatherUsageStats"] is False
    assert config["client"]["showErrorDetails"] == "none"
    assert "-r requirements-runtime.lock" in requirements
    assert (project_root / "requirements-runtime.lock").is_file()
    assert not (project_root / "packages.txt").exists()


def test_documentation_and_license_submission_contract(project_root: Path) -> None:
    readme = (project_root / "README.md").read_text(encoding="utf-8")
    deployment = (project_root / "DEPLOYMENT.md").read_text(encoding="utf-8")
    demo = (project_root / "DEMO_SCRIPT.md").read_text(encoding="utf-8")
    devpost = (project_root / "DEVPOST_PROJECT_DESCRIPTION.md").read_text(encoding="utf-8")
    license_text = (project_root / "LICENSE").read_text(encoding="utf-8")
    notices = (project_root / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    release_notes = (project_root / "RELEASE_NOTES.md").read_text(encoding="utf-8")
    benchmark_docs = "\n".join(
        (project_root / name).read_text(encoding="utf-8")
        for name in ("BENCHMARK_LOCAL.md", "BENCHMARK_LOCAL_VALIDATION.md")
    )

    assert ".\\.venv\\Scripts\\python.exe" in readme
    assert "Activate.ps1" not in readme
    assert "Python 3.11" in deployment
    assert "REPLAY ONLY" in deployment
    assert "MIT License" in license_text
    for dependency in ("Streamlit", "Pydantic", "Jinja2", "pytest"):
        assert dependency in notices
    assert "not bundled" in notices

    spoken_sections = re.findall(r"\*\*Say:\*\* “(.*?)”", demo, flags=re.DOTALL)
    spoken_words = re.findall(r"[A-Za-z0-9][A-Za-z0-9’'_.-]*", " ".join(spoken_sections))
    assert len(spoken_sections) == 6
    assert 250 <= len(spoken_words) <= 390
    assert "below 3:00" in demo
    assert "REPLAY · NOT LIVE COMPUTE" in devpost
    assert "It does not install, call, or imitate" in devpost
    assert "AI assistance disclosure" in devpost
    assert "v0.3.0 — Benchmark Local" in release_notes
    assert "implemented_unverified" in release_notes
    assert "Live Remote remains unavailable" in release_notes

    public_release_text = "\n".join((readme, release_notes, benchmark_docs, notices))
    assert not re.search(r"(?<![A-Za-z0-9])[A-Za-z]:[\\\\/]", public_release_text)
    assert not re.search(r"/(?:mnt|root|home)/", public_release_text, flags=re.IGNORECASE)
    assert not re.search(
        r"\b" + "LAP" + r"TOP-[A-Za-z0-9-]*\b",
        public_release_text,
        flags=re.IGNORECASE,
    )
    assert not re.search(r"(?:sk-|gh[pousr]_)[A-Za-z0-9_-]{20,}", public_release_text)


def test_fixture_paths_are_safe_on_posix_and_windows(project_root: Path) -> None:
    fixture_root = project_root / "fixtures" / "demo_001"
    fixture_manifest = json.loads((fixture_root / "fixture_manifest.json").read_text(encoding="utf-8"))
    paths = list(fixture_manifest["artifact_hashes"])
    paths.append("input/antigen.pdb")

    for value in paths:
        posix = PurePosixPath(value)
        windows = PureWindowsPath(*posix.parts)
        assert not posix.is_absolute()
        assert not windows.is_absolute()
        assert "\\" not in value
        assert ".." not in posix.parts
        assert windows.parts == posix.parts
        assert (fixture_root / Path(*posix.parts)).is_file()


def test_clean_release_zip_and_source_checksums(
    project_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository_checksum = project_root / "SOURCE_CHECKSUMS.sha256"
    checksum_before = repository_checksum.read_bytes()
    isolated_root = tmp_path / project_root.name
    shutil.copytree(
        project_root,
        isolated_root,
        ignore=shutil.ignore_patterns(*EXCLUDED_PARTS),
    )
    monkeypatch.setattr(package_project, "ROOT", isolated_root)

    output = package_project.build(
        tmp_path / "Antibody_Labmate_Phase2b_Benchmark_Local_v0.3.0.zip"
    )
    prefix = f"{project_root.name}/"

    with zipfile.ZipFile(output) as archive:
        names = archive.namelist()
        assert len(names) == len(set(names))
        assert all(name.startswith(prefix) for name in names)
        assert all("\\" not in name and ".." not in PurePosixPath(name).parts for name in names)
        assert all(not (set(PurePosixPath(name).parts) & EXCLUDED_PARTS) for name in names)
        assert all(not part.endswith(".egg-info") for name in names for part in PurePosixPath(name).parts)
        assert all(not name.endswith((".pyc", ".pyo", ".zip")) for name in names)
        assert {
            prefix + relative
            for relative in REQUIRED_RELEASE_PATHS
        }.issubset(names)

        checksum_name = prefix + "SOURCE_CHECKSUMS.sha256"
        archived_checksum = archive.read(checksum_name)
        checksum_lines = archived_checksum.decode("utf-8").splitlines()
        if b"\r\n" in checksum_before:
            assert archived_checksum.count(b"\r\n") == len(checksum_lines)
        listed_paths: set[str] = set()
        for line in checksum_lines:
            expected, relative = line.split("  ", 1)
            listed_paths.add(relative)
            actual = hashlib.sha256(archive.read(prefix + relative)).hexdigest()
            assert actual == expected, relative
        assert listed_paths == {
            name.removeprefix(prefix) for name in names if name != checksum_name
        }
    assert repository_checksum.read_bytes() == checksum_before


def test_release_excludes_external_models_databases_and_uploads(
    project_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    isolated_root = tmp_path / project_root.name
    shutil.copytree(
        project_root,
        isolated_root,
        ignore=shutil.ignore_patterns(*EXCLUDED_PARTS),
    )
    forbidden_directories = {
        "models": "weights.ckpt",
        "databases": "sequence.db",
        "params": "params_model_1_multimer_v3.npz",
        "uploads": "user_input.pdb",
        "runs": "prediction.pdb",
    }
    for directory, filename in forbidden_directories.items():
        target = isolated_root / directory
        target.mkdir()
        (target / filename).write_bytes(b"must not ship")
    monkeypatch.setattr(package_project, "ROOT", isolated_root)

    output = package_project.build(tmp_path / "clean.zip")
    with zipfile.ZipFile(output) as archive:
        names = archive.namelist()
    assert not any(
        part in forbidden_directories
        for name in names
        for part in PurePosixPath(name).parts
    )


def test_release_refuses_model_weight_file_in_source_scope(
    project_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    isolated_root = tmp_path / project_root.name
    shutil.copytree(
        project_root,
        isolated_root,
        ignore=shutil.ignore_patterns(*EXCLUDED_PARTS),
    )
    (isolated_root / "unexpected_weights.ckpt").write_bytes(b"must not ship")
    monkeypatch.setattr(package_project, "ROOT", isolated_root)

    with pytest.raises(
        RuntimeError,
        match="refuses model or generated-output file",
    ):
        package_project.build(tmp_path / "rejected.zip")

from __future__ import annotations

import hashlib
import json
import re
import tomllib
import zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath

from labmate import __version__
from scripts.package_project import EXCLUDED_PARTS, build, project_version


def test_version_and_streamlit_deployment_contract(project_root: Path) -> None:
    pyproject = tomllib.loads((project_root / "pyproject.toml").read_text(encoding="utf-8"))
    config = tomllib.loads((project_root / ".streamlit" / "config.toml").read_text(encoding="utf-8"))
    requirements = (project_root / "requirements.txt").read_text(encoding="utf-8").splitlines()

    assert __version__ == project_version() == pyproject["project"]["version"] == "0.2.0"
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


def test_clean_release_zip_and_source_checksums(project_root: Path, tmp_path: Path) -> None:
    output = build(tmp_path / "Antibody_Labmate_Phase2a_Live_Local_v0.2.0.zip")
    prefix = f"{project_root.name}/"

    with zipfile.ZipFile(output) as archive:
        names = archive.namelist()
        assert len(names) == len(set(names))
        assert all(name.startswith(prefix) for name in names)
        assert all("\\" not in name and ".." not in PurePosixPath(name).parts for name in names)
        assert all(not (set(PurePosixPath(name).parts) & EXCLUDED_PARTS) for name in names)
        assert all(not part.endswith(".egg-info") for name in names for part in PurePosixPath(name).parts)
        assert all(not name.endswith((".pyc", ".pyo", ".zip")) for name in names)

        checksum_name = prefix + "SOURCE_CHECKSUMS.sha256"
        checksum_lines = archive.read(checksum_name).decode("utf-8").splitlines()
        listed_paths: set[str] = set()
        for line in checksum_lines:
            expected, relative = line.split("  ", 1)
            listed_paths.add(relative)
            actual = hashlib.sha256(archive.read(prefix + relative)).hexdigest()
            assert actual == expected, relative
        assert listed_paths == {
            name.removeprefix(prefix) for name in names if name != checksum_name
        }

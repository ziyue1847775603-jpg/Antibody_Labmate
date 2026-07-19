from __future__ import annotations

import json
from pathlib import Path

import pytest

from labmate.models import JobSpec


@pytest.fixture(scope="session")
def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def fixture_root(project_root: Path) -> Path:
    return project_root / "fixtures" / "demo_001"


@pytest.fixture()
def demo_job(fixture_root: Path) -> JobSpec:
    payload = json.loads((fixture_root / "project.yaml").read_text(encoding="utf-8"))
    return JobSpec.model_validate(payload)


@pytest.fixture()
def demo_antigen(fixture_root: Path) -> bytes:
    return (fixture_root / "input" / "antigen.pdb").read_bytes()


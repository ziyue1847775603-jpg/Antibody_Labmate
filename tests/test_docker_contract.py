from __future__ import annotations

from pathlib import Path


def test_replay_docker_contract_does_not_bundle_scientific_tools(
    project_root: Path,
) -> None:
    dockerfile = (project_root / "Dockerfile").read_text(encoding="utf-8")
    compose = (project_root / "docker-compose.yml").read_text(encoding="utf-8")
    dockerignore = (project_root / ".dockerignore").read_text(encoding="utf-8")
    docs = (project_root / "docs" / "docker.md").read_text(encoding="utf-8")

    assert dockerfile.startswith("FROM python:3.11-slim\n")
    assert 'CMD ["python", "-m", "streamlit", "run", "app.py"' in dockerfile
    assert "8501:8501" in compose
    for excluded in (
        ".git",
        ".venv*",
        "__pycache__",
        "runs",
        "models",
        "databases",
        "params",
        "uploads",
        "checkpoints",
        "*.ckpt",
        "*.safetensors",
    ):
        assert excluded in dockerignore
    assert "does not contain ColabFold, IgFold, LightDock" in docs
    assert "docker compose up --build" in docs
    assert "pip install colabfold" not in dockerfile.lower()
    assert "pip install igfold" not in dockerfile.lower()
    assert "lightdock" not in dockerfile.lower()

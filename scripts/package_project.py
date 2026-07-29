#!/usr/bin/env python3
"""Create a clean, deterministic source ZIP without local environments/caches."""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_PARTS = {
    ".git",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
    ".nox",
    ".venv",
    ".venv311",
    ".idea",
    ".vscode",
    "__pycache__",
    ".cache",
    ".conda",
    "build",
    "checkpoints",
    "database",
    "databases",
    "dist",
    "htmlcov",
    "models",
    "params",
    "runs",
    "uploads",
    "user_uploads",
    "wandb",
}

FORBIDDEN_FILENAMES = {
    ".env",
    "credentials.json",
    "id_dsa",
    "id_ed25519",
    "id_rsa",
    "secrets.toml",
    "service-account.json",
}
FORBIDDEN_SUFFIXES = {".key", ".p12", ".pem", ".pfx"}
FORBIDDEN_MODEL_OR_OUTPUT_SUFFIXES = {
    ".ckpt",
    ".onnx",
    ".pickle",
    ".pkl",
    ".pt",
    ".pth",
    ".safetensors",
}
REQUIRED_RELEASE_PATHS = {
    ".dockerignore",
    "Dockerfile",
    "docker-compose.yml",
    "docs/docker.md",
    "labmate/run.py",
    "labmate/backends/base.py",
    "labmate/backends/registry.py",
    "labmate/backends/replay.py",
    "labmate/backends/colabfold.py",
    "labmate/backends/igfold.py",
}
HIGH_CONFIDENCE_SECRET_PATTERNS = {
    "private_key": re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "openai_key": re.compile(rb"sk-[A-Za-z0-9_-]{20,}"),
    "github_token": re.compile(rb"gh[pousr]_[A-Za-z0-9]{20,}"),
    "aws_access_key": re.compile(rb"AKIA[0-9A-Z]{16}"),
    "slack_token": re.compile(rb"xox[baprs]-[A-Za-z0-9-]{20,}"),
}
LOCAL_PATH_PATTERNS = {
    # Assemble these byte strings so the scanner does not match its own source.
    "workspace_path": re.compile(rb"/" + b"workspace" + rb"/"),
    "temporary_path": re.compile(rb"/" + b"tmp" + rb"/"),
    "windows_user_path": re.compile(rb"[A-Za-z]:" + rb"\\\\" + b"Users" + rb"\\\\"),
}


def project_version() -> str:
    version_source = (ROOT / "labmate" / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'^__version__\s*=\s*"([0-9]+\.[0-9]+\.[0-9]+)"$', version_source, re.MULTILINE)
    if not match:
        raise RuntimeError("Unable to resolve project version")
    return match.group(1)


def included_files() -> list[Path]:
    files: list[Path] = []
    for current, directories, filenames in os.walk(
        ROOT, topdown=True, followlinks=False
    ):
        current_path = Path(current)
        retained_directories: list[str] = []
        for name in directories:
            path = current_path / name
            relative = path.relative_to(ROOT)
            if (
                name in EXCLUDED_PARTS
                or name.endswith(".egg-info")
                or any(
                    part in EXCLUDED_PARTS or part.endswith(".egg-info")
                    for part in relative.parts
                )
            ):
                continue
            if path.is_symlink():
                raise RuntimeError(
                    f"Release refuses symlinked directory: {relative.as_posix()}"
                )
            retained_directories.append(name)
        directories[:] = retained_directories

        for name in filenames:
            path = current_path / name
            relative = path.relative_to(ROOT)
            if path.is_symlink():
                raise RuntimeError(
                    f"Release refuses symlinked file: {relative.as_posix()}"
                )
            if not path.is_file():
                continue
            if path.suffix.lower() in {".pyc", ".pyo", ".zip"}:
                continue
            files.append(path)
    return sorted(files, key=lambda item: item.relative_to(ROOT).as_posix())


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def audit_release_files(files: list[Path]) -> None:
    relative_paths = {
        path.relative_to(ROOT).as_posix()
        for path in files
    }
    missing = sorted(REQUIRED_RELEASE_PATHS - relative_paths)
    if missing:
        raise RuntimeError(
            "Release is missing required architecture files: "
            + ", ".join(missing)
        )
    for path in files:
        relative = path.relative_to(ROOT)
        if path.name.lower() in FORBIDDEN_FILENAMES or path.suffix.lower() in FORBIDDEN_SUFFIXES:
            raise RuntimeError(f"Release refuses secret-bearing filename: {relative.as_posix()}")
        if path.suffix.lower() in FORBIDDEN_MODEL_OR_OUTPUT_SUFFIXES:
            raise RuntimeError(
                "Release refuses model or generated-output file: "
                f"{relative.as_posix()}"
            )
        data = path.read_bytes()
        for label, pattern in HIGH_CONFIDENCE_SECRET_PATTERNS.items():
            if pattern.search(data):
                raise RuntimeError(f"Release secret scan matched {label}: {relative.as_posix()}")
        for label, pattern in LOCAL_PATH_PATTERNS.items():
            if pattern.search(data):
                raise RuntimeError(f"Release local-path scan matched {label}: {relative.as_posix()}")


def audit_archive(output: Path) -> None:
    with zipfile.ZipFile(output) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise RuntimeError("Release ZIP contains duplicate entries")
        expected_prefix = f"{ROOT.name}/"
        for name in names:
            parts = Path(name).parts
            if not name.startswith(expected_prefix) or name.startswith("/") or ".." in parts or "\\" in name:
                raise RuntimeError(f"Unsafe release ZIP entry: {name}")
            if set(parts) & EXCLUDED_PARTS or any(part.endswith(".egg-info") for part in parts):
                raise RuntimeError(f"Excluded content entered release ZIP: {name}")
            basename = Path(name).name.lower()
            suffix = Path(name).suffix.lower()
            if basename in FORBIDDEN_FILENAMES or suffix in FORBIDDEN_SUFFIXES:
                raise RuntimeError(f"Secret-bearing filename entered release ZIP: {name}")
            if suffix in FORBIDDEN_MODEL_OR_OUTPUT_SUFFIXES:
                raise RuntimeError(
                    f"Model or generated-output file entered release ZIP: {name}"
                )
            data = archive.read(name)
            for label, pattern in HIGH_CONFIDENCE_SECRET_PATTERNS.items():
                if pattern.search(data):
                    raise RuntimeError(f"Release ZIP secret scan matched {label}: {name}")
            for label, pattern in LOCAL_PATH_PATTERNS.items():
                if pattern.search(data):
                    raise RuntimeError(f"Release ZIP local-path scan matched {label}: {name}")


def build(output: Path) -> Path:
    checksum_path = ROOT / "SOURCE_CHECKSUMS.sha256"
    before_checksum = [path for path in included_files() if path != checksum_path]
    audit_release_files(before_checksum)
    existing = checksum_path.read_bytes() if checksum_path.is_file() else b""
    line_ending = (
        b"\r\n"
        if b"\r\n" in existing and existing.count(b"\n") == existing.count(b"\r\n")
        else b"\n"
    )
    checksum_path.write_bytes(
        line_ending.join(
            f"{sha256(path)}  {path.relative_to(ROOT).as_posix()}".encode("utf-8")
            for path in before_checksum
        )
        + line_ending
    )
    output = output.resolve()
    try:
        output.relative_to(ROOT)
    except ValueError:
        pass
    else:
        raise RuntimeError("Release ZIP must be written outside the project root")
    output.parent.mkdir(parents=True, exist_ok=True)
    release_files = included_files()
    audit_release_files(release_files)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in release_files:
            relative = Path(ROOT.name) / path.relative_to(ROOT)
            info = zipfile.ZipInfo(relative.as_posix(), date_time=(2026, 7, 27, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o755 if path.stat().st_mode & 0o111 else 0o644) << 16
            archive.writestr(info, path.read_bytes())
    audit_archive(output)
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "output",
        nargs="?",
        type=Path,
        default=ROOT.parent
        / f"Antibody_Labmate_Backend_Architecture_v{project_version()}.zip",
    )
    args = parser.parse_args()
    print(build(args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

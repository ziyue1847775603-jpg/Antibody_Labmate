"""Canonical hashing and safe artifact bookkeeping."""

from __future__ import annotations

import hashlib
import json
import mimetypes
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from labmate.errors import FixtureIntegrityError
from labmate.models import ArtifactRecord, JobSpec


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_input_hashes(job: JobSpec, antigen_bytes: bytes) -> dict[str, str]:
    cdr_payload = job.antibody.model_dump(mode="json")
    cdr_sha = sha256_bytes(canonical_json_bytes(cdr_payload))
    antigen_sha = sha256_bytes(antigen_bytes)
    bundle = {
        "schema_version": job.schema_version,
        "fixture_id": job.fixture_id,
        "antibody_sha256": cdr_sha,
        "antigen_sha256": antigen_sha,
        "antigen_options": job.antigen.model_dump(mode="json", exclude={"file"}),
        "rights_confirmed": job.rights_confirmed,
        "source_type": job.source_type,
    }
    return {
        "antibody_sha256": cdr_sha,
        "antigen_sha256": antigen_sha,
        "input_bundle_sha256": sha256_bytes(canonical_json_bytes(bundle)),
    }


def safe_relative_path(path: str) -> Path:
    if not path or path.startswith("./") or "\\" in path or "\x00" in path:
        raise FixtureIntegrityError(f"不安全的相对路径: {path!r}")
    posix = PurePosixPath(path)
    windows = PureWindowsPath(path)
    if (
        posix.is_absolute()
        or windows.is_absolute()
        or windows.drive
        or not posix.parts
        or any(part in {"", ".", ".."} for part in posix.parts)
    ):
        raise FixtureIntegrityError(f"不安全的相对路径: {path!r}")
    return Path(*posix.parts)


def artifact_record(path: Path, run_root: Path, *, role: str, media_type: str | None = None) -> ArtifactRecord:
    resolved_root = run_root.resolve()
    resolved_path = path.resolve()
    try:
        relative = resolved_path.relative_to(resolved_root)
    except ValueError as exc:
        raise FixtureIntegrityError("artifact 位于 run 目录之外") from exc
    guessed = media_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return ArtifactRecord(
        path=relative.as_posix(),
        sha256=sha256_file(path),
        size_bytes=path.stat().st_size,
        media_type=guessed,
        role=role,
    )


def verify_artifact_hashes(root: Path, expected: dict[str, str]) -> None:
    for relative_text, expected_sha in sorted(expected.items()):
        relative = safe_relative_path(relative_text)
        target = (root / relative).resolve()
        try:
            target.relative_to(root.resolve())
        except ValueError as exc:
            raise FixtureIntegrityError(f"fixture 路径越界: {relative_text}") from exc
        if not target.is_file():
            raise FixtureIntegrityError(f"fixture 缺少文件: {relative_text}")
        actual = sha256_file(target)
        if actual != expected_sha:
            raise FixtureIntegrityError(
                f"fixture 文件哈希不匹配: {relative_text} (expected {expected_sha}, got {actual})"
            )

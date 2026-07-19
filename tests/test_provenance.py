from __future__ import annotations

import json

import pytest

from labmate.errors import FixtureIntegrityError
from labmate.provenance import build_input_hashes, canonical_json_bytes, safe_relative_path, sha256_bytes


def test_canonical_json_hash_ignores_dict_insertion_order() -> None:
    assert sha256_bytes(canonical_json_bytes({"b": 2, "a": 1})) == sha256_bytes(
        canonical_json_bytes({"a": 1, "b": 2})
    )


@pytest.mark.parametrize("path", ["../escape", "/absolute", "a/../../b", "./local"])
def test_unsafe_relative_paths_are_rejected(path: str) -> None:
    with pytest.raises(FixtureIntegrityError):
        safe_relative_path(path)


def test_demo_input_hashes_match_fixture_manifest(demo_job, demo_antigen, fixture_root) -> None:
    manifest = json.loads((fixture_root / "fixture_manifest.json").read_text(encoding="utf-8"))
    assert build_input_hashes(demo_job, demo_antigen) == manifest["input_hashes"]


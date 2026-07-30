import hashlib
import json
from pathlib import Path

import pytest

from labmate.benchmarking import load_manifest


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _manifest(root: Path) -> Path:
    paths = []
    for name in ("receptor.pdb", "ligand.pdb", "bound.pdb"):
        path = root / name
        path.write_text("ATOM\n", encoding="utf-8")
        paths.append(path)
    case = {
        "schema_version": 1, "case_id": "case-1", "dataset_name": "synthetic",
        "dataset_version": "0", "source_reference": "test", "source_license": "test-only",
        "receptor_unbound_path": paths[0].name, "receptor_unbound_sha256": _sha(paths[0]),
        "ligand_unbound_path": paths[1].name, "ligand_unbound_sha256": _sha(paths[1]),
        "bound_reference_path": paths[2].name, "bound_reference_sha256": _sha(paths[2]),
        "receptor_chains": ["A"], "ligand_heavy_chain": "H", "ligand_light_chain": "L",
        "bound_receptor_chains": ["A"], "bound_heavy_chain": "H", "bound_light_chain": "L",
        "residue_mapping": {"declared": True},
    }
    path = root / "manifest.json"
    path.write_text(json.dumps({"schema_version": 1, "dataset_name": "synthetic", "dataset_version": "0", "source_reference": "test", "source_license": "test-only", "cases": [case]}), encoding="utf-8")
    return path


def test_manifest_revalidates_hashes_and_roles(tmp_path: Path) -> None:
    path = _manifest(tmp_path)
    assert load_manifest(path).cases[0].case_id == "case-1"
    (tmp_path / "ligand.pdb").write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="hash mismatch"):
        load_manifest(path)


def test_manifest_rejects_bound_input_reuse(tmp_path: Path) -> None:
    path = _manifest(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["cases"][0]["bound_reference_path"] = "receptor.pdb"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="distinct"):
        load_manifest(path)

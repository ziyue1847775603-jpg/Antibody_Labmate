from pathlib import Path

import pytest

from labmate.backends.base import PredictionResult
from labmate.docking.lightdock import LocalLightDockExecutor
from labmate.prediction_artifact import DockingInput, docking_input, prediction_artifact


_AA = {"A": "ALA", "C": "CYS", "D": "ASP", "E": "GLU", "F": "PHE", "G": "GLY", "H": "HIS", "I": "ILE"}


def _pdb(path: Path, chains: dict[str, str]) -> None:
    rows: list[str] = []; serial = 1
    for chain, sequence in chains.items():
        for residue_number, amino_acid in enumerate(sequence, 1):
            rows.append(f"ATOM  {serial:5d}  CA  {_AA[amino_acid]:>3s} {chain}{residue_number:4d}    {float(serial):8.3f}{0.0:8.3f}{0.0:8.3f}{1.0:6.2f}{20.0:6.2f}           C  ")
            serial += 1
    path.write_text("\n".join(rows) + "\nEND\n", encoding="utf-8")


def _script(path: Path, source: str) -> Path:
    path.write_text("#!/bin/sh\nset -eu\n" + source, encoding="utf-8")
    path.chmod(0o700)
    return path


def _handoff(tmp_path: Path) -> DockingInput:
    antibody, antigen = tmp_path / "antibody.pdb", tmp_path / "antigen.pdb"
    _pdb(antibody, {"H": "ACDE", "L": "FGHI"}); _pdb(antigen, {"A": "ACDE"})
    result = PredictionResult(pdb_path=antibody, backend_name="igfold", status="succeeded")
    artifact = prediction_artifact(result, heavy_chain="ACDE", light_chain="FGHI", allowed_root=tmp_path)
    return docking_input(artifact, antigen_pdb=antigen, allowed_root=tmp_path, output_root=tmp_path / "handoff")


def _executor(tmp_path: Path, *, sampling: str = "mkdir -p swarm_0\nprintf '%s\\n' '(0,0,0,0,0,0,0) 0 0 0 0 0 0 2.0' > swarm_0/gso_5.out\n") -> LocalLightDockExecutor:
    setup = _script(tmp_path / "setup", "printf '{}' > setup.json\n")
    sample = _script(tmp_path / "sample", sampling)
    conform = _script(tmp_path / "conform", 'cat "$1" "$2" > lightdock_0.pdb\n')
    return LocalLightDockExecutor(setup_executable=setup, sampling_executable=sample, conformation_executable=conform)


def test_fake_lightdock_executes_explicit_gso_to_validated_pose(tmp_path: Path) -> None:
    result = _executor(tmp_path).execute(_handoff(tmp_path), allowed_root=tmp_path, output_dir=tmp_path / "output", timeout_seconds=10)
    assert result.status == "succeeded"
    assert result.selected_pose == "poses/pose_001.pdb"
    assert result.native_scores[0]["score"] == 2.0
    assert (tmp_path / "output" / "docking_manifest.json").is_file()
    assert (tmp_path / "output" / "poses" / "pose_001.pdb").read_bytes().startswith(b"ATOM")


def test_fake_lightdock_nonzero_and_timeout_fail_closed(tmp_path: Path) -> None:
    handoff = _handoff(tmp_path)
    with pytest.raises(RuntimeError, match="exit code 7"):
        _executor(tmp_path, sampling="exit 7\n").execute(handoff, allowed_root=tmp_path, output_dir=tmp_path / "nonzero", timeout_seconds=10)
    with pytest.raises(RuntimeError, match="timed out"):
        _executor(tmp_path, sampling="sleep 2\n").execute(handoff, allowed_root=tmp_path, output_dir=tmp_path / "timeout", timeout_seconds=1)


def test_executor_rejects_symlink_and_path_escape(tmp_path: Path) -> None:
    handoff = _handoff(tmp_path)
    outside = tmp_path.parent / "outside.pdb"; _pdb(outside, {"H": "ACDE", "L": "FGHI"})
    escaped = handoff.model_copy(update={"antibody_artifact": handoff.antibody_artifact.model_copy(update={"pdb_path": "../outside.pdb"})})
    with pytest.raises(ValueError, match="escaped"):
        _executor(tmp_path).execute(escaped, allowed_root=tmp_path, output_dir=tmp_path / "escaped", timeout_seconds=10)
    link = tmp_path / "linked.pdb"; link.symlink_to(tmp_path / "antibody.pdb")
    linked = handoff.model_copy(update={"antibody_artifact": handoff.antibody_artifact.model_copy(update={"pdb_path": "linked.pdb"})})
    with pytest.raises(ValueError, match="unsafe"):
        _executor(tmp_path).execute(linked, allowed_root=tmp_path, output_dir=tmp_path / "linked", timeout_seconds=10)


def test_lightdock_executor_rejects_non_executable_or_directory(tmp_path: Path) -> None:
    directory = tmp_path / "tool"; directory.mkdir()
    with pytest.raises(ValueError, match="executable regular file"):
        LocalLightDockExecutor(setup_executable=directory, sampling_executable=directory, conformation_executable=directory)


def test_lightdock_log_redaction_removes_local_paths_and_tokens() -> None:
    local_path = "/" + "mnt" + "/d/private/run "
    redacted = LocalLightDockExecutor._redact_log(local_path + "sk-" + ("a" * 30))
    assert local_path not in redacted and "sk-" not in redacted

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from labmate.backends.base import PredictionResult
from labmate.design.artifact import DesignArtifact, DesignCandidate, sequence_sha256, validate_vhh_candidate
from labmate.prediction_artifact import prediction_artifact
from labmate.workers.rfantibody_worker import _proteinmpnn_output, _validate_fixed_backbone


def _atom(serial: int, atom: str, residue: str, chain: str, number: int, x: float) -> str:
    return f"ATOM  {serial:5d} {atom:<4s} {residue:>3s} {chain}{number:4d}    {x:8.3f}{0.0:8.3f}{0.0:8.3f}  1.00 20.00           C\n"


def _vhh(path: Path, *, residue: str = "ALA") -> None:
    path.write_text(
        _atom(1, "N", residue, "H", 1, 0.0)
        + _atom(2, "CA", residue, "H", 1, 1.0)
        + _atom(3, "C", residue, "H", 1, 2.0)
        + _atom(4, "O", residue, "H", 1, 3.0)
        + "TER\nEND\n",
        encoding="utf-8",
    )


def test_sequence_sha_is_the_raw_sequence_not_the_fasta_wrapper() -> None:
    assert sequence_sha256("A") == hashlib.sha256(b"A").hexdigest()
    assert sequence_sha256("A") != hashlib.sha256(b">candidate\nA\n").hexdigest()


def test_sequence_validated_candidate_is_prediction_ready() -> None:
    candidate = DesignCandidate(
        candidate_id="rfantibody-000", generation_index=0, antibody_format="vhh",
        heavy_sequence="A", sequence_sha256=sequence_sha256("A"), sequence_fasta="candidates/candidate_000.fasta",
        designed_structure="candidates/candidate_000.pdb", designed_structure_sha256="0" * 64,
        semantic_chain_map={"heavy": "H"}, designed_residue_count=1, fixed_residue_count=1,
    )
    artifact = DesignArtifact(
        backend="rfantibody", backend_version="1.0.0", repo_commit="0" * 40,
        checkpoints={}, checkpoint_sha256={}, input_sha256="0" * 64, seed=0, parameters={},
        candidates=[candidate], requested_candidate_count=1, sequence_designed_candidate_count=1,
        sequence_validated_candidate_count=1, prediction_ready=True, provenance={}, runtime_seconds=0.1,
        unsupported_claims=["no affinity prediction"],
    )
    assert artifact.status == "success"
    assert artifact.candidates[0].design_stage == "sequence_validated"
    assert artifact.candidates[0].prediction_ready is True


def test_backbone_or_partial_design_result_cannot_enter_prediction_artifact(tmp_path: Path) -> None:
    pdb = tmp_path / "candidate.pdb"
    _vhh(pdb)
    result = PredictionResult(
        backend_name="colabfold", status="succeeded", pdb_path=pdb,
        metadata={"design_stage": "backbone_generated"},
    )
    with pytest.raises(ValueError, match="backbone-only or partial"):
        prediction_artifact(result, heavy_chain="A", light_chain=None, allowed_root=tmp_path)


def test_vhh_prediction_artifact_preserves_single_heavy_chain(tmp_path: Path) -> None:
    pdb = tmp_path / "candidate.pdb"
    _vhh(pdb)
    result = PredictionResult(
        backend_name="colabfold", status="succeeded", pdb_path=pdb,
        metadata={"design_stage": "sequence_validated"},
    )
    artifact = prediction_artifact(result, heavy_chain="A", light_chain=None, allowed_root=tmp_path)
    assert artifact.chain_map == {"heavy": "H"}
    assert artifact.input_sequences == {"heavy": "A"}


def test_worker_parses_exact_official_proteinmpnn_records() -> None:
    output = "loopH: [26, 27]\nsequence_optimize: [('AQ', 1.25)]\n"
    candidates, positions = _proteinmpnn_output(output, expected_count=1)
    assert candidates == [("AQ", 1.25)]
    assert positions == [26, 27]
    with pytest.raises(ValueError, match="requested sequence count"):
        _proteinmpnn_output(output, expected_count=2)


def test_fixed_framework_backbone_is_preserved_and_mutation_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "source.pdb"
    threaded = tmp_path / "threaded.pdb"
    _vhh(source)
    _vhh(threaded)
    _validate_fixed_backbone(source, threaded, designed_positions={2})
    _vhh(threaded)
    threaded.write_text(threaded.read_text(encoding="utf-8").replace("   1.000", "   9.000", 1), encoding="utf-8")
    with pytest.raises(ValueError, match="fixed framework backbone coordinates"):
        _validate_fixed_backbone(source, threaded, designed_positions={2})


def test_vhh_candidate_rejects_non_heavy_or_unsafe_pdb(tmp_path: Path) -> None:
    pdb = tmp_path / "candidate.pdb"
    _vhh(pdb)
    assert validate_vhh_candidate(pdb, root=tmp_path)[0] == "A"
    other = tmp_path / "other.pdb"
    other.write_text(pdb.read_text(encoding="utf-8").replace(" H   1", " L   1"), encoding="utf-8")
    with pytest.raises(ValueError, match="exactly one explicit heavy"):
        validate_vhh_candidate(other, root=tmp_path)

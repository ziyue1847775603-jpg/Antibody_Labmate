"""Validated artifacts for local antibody-design candidates.

Validation is strictly engineering validation.  It says nothing about binding,
affinity, expression, stability, specificity, or therapeutic suitability.
"""
from __future__ import annotations

import hashlib
import math
import re
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from labmate.validators.antigen import THREE_TO_ONE, parse_complex_pdb

SCHEMA_VERSION = 1
_AMINO_ACIDS = frozenset("ACDEFGHIKLMNPQRSTVWY")
_TOKEN = re.compile(r"(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16})")
_ABSOLUTE = re.compile(r"(?:[A-Za-z]:[\\/]|/(?:mnt|root|home)/)")


class DesignInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: int = SCHEMA_VERSION
    design_backend: str = "rfantibody"
    target_pdb: str
    target_sha256: str
    target_chains: list[str]
    hotspot_residues: list[str]
    antibody_format: str = "vhh"
    seed: int = 0
    candidate_count: int = 1
    parameters: dict[str, object] = Field(default_factory=dict)
    resume_backbone_pdb: str | None = None
    resume_backbone_sha256: str | None = None


class DesignCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidate_id: str
    generation_index: int
    antibody_format: str
    design_stage: str = "sequence_validated"
    heavy_sequence: str
    sequence_sha256: str
    sequence_fasta: str
    sequence_source: str = "official_proteinmpnn"
    light_sequence: str | None = None
    designed_structure: str
    designed_structure_sha256: str
    semantic_chain_map: dict[str, str]
    designed_residue_count: int
    fixed_residue_count: int
    prediction_ready: bool = True
    native_metrics: dict[str, object] = Field(default_factory=dict)
    native_metric_semantics: str = "backend_native_unscaled"
    generation_status: str = "succeeded"
    validation_status: str = "validated"
    warnings: list[str] = Field(default_factory=list)


class DesignArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: int = SCHEMA_VERSION
    backend: str
    backend_version: str
    repo_commit: str
    checkpoints: dict[str, str]
    checkpoint_sha256: dict[str, str]
    input_sha256: str
    seed: int
    parameters: dict[str, object]
    intermediates: list[dict[str, object]] = Field(default_factory=list)
    candidates: list[DesignCandidate]
    requested_candidate_count: int
    sequence_designed_candidate_count: int = 0
    sequence_validated_candidate_count: int = 0
    prediction_ready: bool = False
    pipeline_stages: list[dict[str, object]] = Field(default_factory=list)
    provenance: dict[str, str]
    runtime_seconds: float
    warnings: list[str] = Field(default_factory=list)
    unsupported_claims: list[str]
    status: str = "success"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sequence_sha256(sequence: str) -> str:
    """Return the hash of the sequence itself, never of a FASTA wrapper."""
    return hashlib.sha256(sequence.encode("ascii")).hexdigest()


def safe_native_metrics(value: object) -> object:
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("native metrics cannot contain NaN or infinity")
        return value
    if isinstance(value, str):
        if _TOKEN.search(value) or _ABSOLUTE.search(value):
            raise ValueError("native metrics contain private data")
        return value
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, list):
        return [safe_native_metrics(item) for item in value]
    if isinstance(value, dict):
        return {str(key): safe_native_metrics(item) for key, item in value.items()}
    raise ValueError("native metrics contain unsupported data")


def regular_file(path: Path, *, root: Path, label: str) -> Path:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be a regular non-symlink file")
    resolved = path.resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"{label} escaped its allowed root") from exc
    return resolved


def validate_design_input(value: DesignInput, *, root: Path) -> Path:
    if value.schema_version != SCHEMA_VERSION or value.design_backend != "rfantibody":
        raise ValueError("unsupported design input schema/backend")
    if value.seed < 0 or not 1 <= value.candidate_count <= 2:
        raise ValueError("seed must be non-negative and candidate_count must be 1..2")
    if value.antibody_format != "vhh":
        raise ValueError("the verified RFantibody bridge currently supports only vhh")
    target = regular_file(root / value.target_pdb, root=root, label="target PDB")
    if sha256(target) != value.target_sha256:
        raise ValueError("target PDB hash mismatch")
    if not value.target_chains or not all(re.fullmatch(r"[A-Za-z0-9]", chain) for chain in value.target_chains):
        raise ValueError("target chains must be explicit one-character PDB chain IDs")
    if not value.hotspot_residues or not all(re.fullmatch(r"[A-Za-z0-9]:-?[0-9]+[A-Za-z]?", item) for item in value.hotspot_residues):
        raise ValueError("hotspots must use explicit chain:residue identifiers")
    parsed = parse_complex_pdb(target.read_bytes())
    observed = set(parsed.chains)
    if not set(value.target_chains).issubset(observed):
        raise ValueError("a requested target chain is absent from target PDB")
    if any(item.split(":", 1)[0] not in value.target_chains for item in value.hotspot_residues):
        raise ValueError("a hotspot chain is not a declared target chain")
    observed_residues = {
        f"{atom.residue.chain_id}:{atom.residue.residue_number}{atom.residue.insertion_code or ''}"
        for atom in parsed.atoms
    }
    if not set(value.hotspot_residues).issubset(observed_residues):
        raise ValueError("a hotspot residue is absent from target PDB")
    if (value.resume_backbone_pdb is None) != (value.resume_backbone_sha256 is None):
        raise ValueError("resume backbone path and hash must be supplied together")
    if value.resume_backbone_pdb is not None:
        backbone = regular_file(root / value.resume_backbone_pdb, root=root, label="resume backbone PDB")
        if sha256(backbone) != value.resume_backbone_sha256:
            raise ValueError("resume backbone PDB hash mismatch")
    return target


def validate_vhh_candidate(path: Path, *, root: Path, expected_chain: str = "H") -> tuple[str, int]:
    resolved = regular_file(path, root=root, label="candidate PDB")
    data = resolved.read_bytes()
    if not data or b"ATOM" not in data or b"<html" in data[:4096].lower():
        raise ValueError("candidate PDB is empty, HTML, or contains no ATOM records")
    for line in data.splitlines():
        if line.startswith((b"ATOM  ", b"HETATM")):
            try:
                values = (float(line[30:38]), float(line[38:46]), float(line[46:54]))
            except ValueError as exc:
                raise ValueError("candidate PDB has invalid coordinates") from exc
            if not all(math.isfinite(value) for value in values):
                raise ValueError("candidate PDB has non-finite coordinates")
    parsed = parse_complex_pdb(data)
    if set(parsed.chains) != {expected_chain}:
        raise ValueError("VHH candidate must contain exactly one explicit heavy chain")
    residues = list(dict.fromkeys(atom.residue for atom in parsed.atoms if atom.residue.chain_id == expected_chain))
    sequence = "".join(THREE_TO_ONE[residue.residue_name] for residue in residues)
    if not sequence or not set(sequence).issubset(_AMINO_ACIDS):
        raise ValueError("candidate sequence is invalid")
    atom_count = sum(1 for line in data.splitlines() if line.startswith(b"ATOM  "))
    if not atom_count:
        raise ValueError("candidate PDB has no ATOM records")
    return sequence, atom_count

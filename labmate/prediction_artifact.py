"""Backend-neutral, validated handoff from prediction-only to local docking.

This module intentionally does not run docking or rank candidates.  Backend
native metrics are preserved only as annotations and are never normalized.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from labmate.backends.base import PredictionResult
from labmate.validators.antigen import THREE_TO_ONE, parse_complex_pdb

SCHEMA_VERSION = 1
_TOKEN = re.compile(r"(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16})")
_ABSOLUTE = re.compile(r"(?:[A-Za-z]:[\\/]|/(?:mnt|root|home)/)")


class PredictionArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: int = SCHEMA_VERSION
    backend_name: str
    pdb_path: str
    pdb_sha256: str
    structure_role: str = "antibody"
    chain_map: dict[str, str]
    input_sequences: dict[str, str] = Field(default_factory=dict)
    observed_sequences: dict[str, str]
    residue_counts: dict[str, int]
    atom_count: int
    native_metrics: dict[str, object] = Field(default_factory=dict)
    native_metrics_semantics: str = "backend_native_unscaled"
    warnings: list[str] = Field(default_factory=list)
    provenance: dict[str, str]
    validated: bool = True


class DockingInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: int = SCHEMA_VERSION
    antibody_artifact: PredictionArtifact
    antigen_pdb_path: str
    antigen_pdb_sha256: str
    antigen_chains: list[str]
    receptor_role: str = "antigen"
    ligand_role: str = "antibody"
    docking_backend: str = "lightdock"
    parameters: dict[str, object] = Field(default_factory=dict)
    provenance: dict[str, str]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _inside(path: Path, root: Path) -> Path:
    if path.is_symlink() or not path.is_file():
        raise ValueError("structure must be a regular non-symlink file")
    resolved = path.resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError("structure path resolved outside allowed root") from exc
    return resolved


def _chains(path: Path) -> tuple[dict[str, str], int]:
    data = path.read_bytes()
    if not data or b"ATOM" not in data or b"<html" in data[:4096].lower():
        raise ValueError("structure is empty, HTML, or contains no ATOM records")
    parsed = parse_complex_pdb(data)
    sequences: dict[str, str] = {}
    for chain in parsed.chains:
        residues = list(dict.fromkeys(atom.residue for atom in parsed.atoms if atom.residue.chain_id == chain))
        sequences[chain] = "".join(THREE_TO_ONE[residue.residue_name] for residue in residues)
    atoms = sum(1 for line in data.splitlines() if line.startswith(b"ATOM  "))
    if not atoms or not sequences:
        raise ValueError("structure contains no protein ATOM chains")
    return sequences, atoms


def _safe_native(value: object) -> object:
    if isinstance(value, float):
        if not math.isfinite(value): raise ValueError("native metrics cannot contain NaN or infinity")
        return value
    if isinstance(value, str):
        if _TOKEN.search(value) or _ABSOLUTE.search(value): raise ValueError("native metrics contain private data")
        return value
    if isinstance(value, list): return [_safe_native(item) for item in value]
    if isinstance(value, dict): return {str(key): _safe_native(item) for key, item in value.items()}
    if value is None or isinstance(value, (bool, int)): return value
    raise ValueError("native metrics contain unsupported data")


def prediction_artifact(
    result: PredictionResult, *, heavy_chain: str, light_chain: str, allowed_root: Path, source_run_id: str = "prediction-only"
) -> PredictionArtifact:
    if result.status != "succeeded" or result.pdb_path is None:
        raise ValueError("only succeeded prediction results can enter docking")
    path = _inside(Path(result.pdb_path), allowed_root)
    observed, atoms = _chains(path)
    matches = {role: [chain for chain, sequence in observed.items() if sequence == expected] for role, expected in {"heavy": heavy_chain, "light": light_chain}.items()}
    if any(len(chains) != 1 for chains in matches.values()) or matches["heavy"] == matches["light"]:
        raise ValueError("heavy/light chain mapping is missing or ambiguous")
    if len(observed) != 2:
        raise ValueError("antibody prediction contains an unexpected extra protein chain")
    root = allowed_root.resolve()
    native = _safe_native(result.metadata.get("native_metrics", {}))
    semantics = str(result.metadata.get("native_metrics_semantics", "backend_native_unscaled"))
    return PredictionArtifact(
        backend_name=result.backend_name,
        pdb_path=path.relative_to(root).as_posix(), pdb_sha256=_sha(path),
        chain_map={role: chains[0] for role, chains in matches.items()},
        input_sequences={"heavy": heavy_chain, "light": light_chain}, observed_sequences={"heavy": heavy_chain, "light": light_chain},
        residue_counts={role: len(sequence) for role, sequence in {"heavy": heavy_chain, "light": light_chain}.items()}, atom_count=atoms,
        native_metrics=native if isinstance(native, dict) else {}, native_metrics_semantics=semantics,
        warnings=list(result.warnings), provenance={"prediction_backend": result.backend_name, "execution_mode": str(result.metadata.get("execution_kind", "unknown")), "source_run_identifier": source_run_id, "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"), "validation_method": "exact_chain_sequence_and_sha256"},
    )


def docking_input(artifact: PredictionArtifact, *, antigen_pdb: Path, allowed_root: Path, output_root: Path) -> DockingInput:
    if artifact.schema_version != SCHEMA_VERSION or not artifact.validated:
        raise ValueError("prediction artifact is not locally validated")
    root = allowed_root.resolve(); antibody = _inside(root / artifact.pdb_path, root)
    if _sha(antibody) != artifact.pdb_sha256: raise ValueError("prediction artifact PDB hash mismatch")
    antigen = _inside(antigen_pdb, root); chains, atoms = _chains(antigen)
    if not atoms: raise ValueError("antigen contains no ATOM records")
    if output_root.is_symlink() or (output_root.exists() and any(output_root.iterdir())): raise ValueError("adapter output directory must be new and empty")
    output_root.mkdir(parents=True, exist_ok=False)
    return DockingInput(antibody_artifact=artifact, antigen_pdb_path=antigen.relative_to(root).as_posix(), antigen_pdb_sha256=_sha(antigen), antigen_chains=sorted(chains), provenance={"validation_method": "regular_files_sha256_protein_chains", "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z")})


def write_handoff(path: Path, value: PredictionArtifact | DockingInput) -> None:
    path.write_text(value.model_dump_json(indent=2) + "\n", encoding="utf-8")

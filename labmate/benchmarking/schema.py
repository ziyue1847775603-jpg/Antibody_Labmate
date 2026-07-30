"""Fail-closed manifest validation for bound/unbound docking benchmarks."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
SCHEMA_VERSION = 1
class BenchmarkCase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: int = SCHEMA_VERSION
    case_id: str
    dataset_name: str
    dataset_version: str
    source_reference: str
    source_license: str
    difficulty_label: str = "unknown"
    difficulty_label_source: str = "not_assigned"
    receptor_unbound_path: str
    receptor_unbound_sha256: str
    ligand_unbound_path: str
    ligand_unbound_sha256: str
    bound_reference_path: str
    bound_reference_sha256: str
    receptor_chains: list[str] = Field(min_length=1)
    ligand_heavy_chain: str
    ligand_light_chain: str
    bound_receptor_chains: list[str] = Field(min_length=1)
    bound_heavy_chain: str
    bound_light_chain: str
    residue_mapping: dict[str, object]
    notes: str = ""
    validated: bool = False
    @field_validator("case_id", "dataset_name", "dataset_version", "source_reference", "source_license")
    @classmethod
    def required(cls, value: str) -> str:
        if not value.strip(): raise ValueError("benchmark provenance fields must be non-empty")
        return value
    @model_validator(mode="after")
    def roles(self) -> "BenchmarkCase":
        if self.ligand_heavy_chain == self.ligand_light_chain: raise ValueError("heavy and light chains must be distinct")
        if len({self.receptor_unbound_path, self.ligand_unbound_path, self.bound_reference_path}) != 3: raise ValueError("bound reference and unbound docking inputs must be distinct files")
        return self
class BenchmarkDatasetManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: int = SCHEMA_VERSION
    dataset_name: str
    dataset_version: str
    source_reference: str
    source_license: str
    cases: list[BenchmarkCase] = Field(min_length=1)
    @model_validator(mode="after")
    def unique_cases(self) -> "BenchmarkDatasetManifest":
        if len({case.case_id for case in self.cases}) != len(self.cases): raise ValueError("benchmark case IDs must be unique")
        return self
def _sha256(path: Path) -> str: return hashlib.sha256(path.read_bytes()).hexdigest()
def _safe_file(root: Path, relative: str) -> Path:
    declared = Path(relative)
    candidate = root / declared
    if declared.is_absolute() or candidate.is_symlink() or not candidate.is_file(): raise ValueError("benchmark structures must be regular manifest-relative files")
    resolved = candidate.resolve()
    try: resolved.relative_to(root.resolve())
    except ValueError as exc: raise ValueError("benchmark structure path escaped manifest root") from exc
    return resolved
def load_manifest(path: Path) -> BenchmarkDatasetManifest:
    if path.is_symlink() or not path.is_file(): raise ValueError("benchmark manifest must be a regular file")
    manifest = BenchmarkDatasetManifest.model_validate(json.loads(path.read_text(encoding="utf-8")))
    root = path.parent.resolve()
    for case in manifest.cases:
        for relative, expected in ((case.receptor_unbound_path, case.receptor_unbound_sha256), (case.ligand_unbound_path, case.ligand_unbound_sha256), (case.bound_reference_path, case.bound_reference_sha256)):
            if _sha256(_safe_file(root, relative)) != expected: raise ValueError(f"benchmark structure hash mismatch: {relative}")
    return manifest

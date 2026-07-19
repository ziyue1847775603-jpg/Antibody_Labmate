"""Pydantic data contracts shared by CLI, UI, workflow, and report generation."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from labmate.validators.cdr import normalize_cdr_sequence


class CapabilityStatus(StrEnum):
    VERIFIED_LIVE = "verified_live"
    AVAILABLE_UNVERIFIED = "available_unverified"
    REPLAY_ONLY = "replay_only"
    UNAVAILABLE = "unavailable"


class StageStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED_OPTIONAL = "skipped_optional"


class ExecutionKind(StrEnum):
    LIVE = "live"
    CACHE = "cache"
    REPLAY = "replay"


class CDRInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    h_cdr1: str
    h_cdr2: str
    h_cdr3: str
    l_cdr1: str
    l_cdr2: str
    l_cdr3: str
    light_chain_type: Literal["auto", "kappa", "lambda"] = "auto"
    numbering_scheme: Literal["imgt"] = "imgt"
    candidate_count: Annotated[int, Field(ge=1, le=16)] = 4
    random_seed: Annotated[int, Field(ge=0, le=2**31 - 1)] = 42

    @field_validator("h_cdr1", "h_cdr2", "h_cdr3", "l_cdr1", "l_cdr2", "l_cdr3", mode="before")
    @classmethod
    def normalize_sequences(cls, value: object, info) -> str:
        return normalize_cdr_sequence(value, field_name=info.field_name)  # type: ignore[arg-type]

    def region_map(self) -> dict[str, str]:
        return {
            "H-cdr1": self.h_cdr1,
            "H-cdr2": self.h_cdr2,
            "H-cdr3": self.h_cdr3,
            "L-cdr1": self.l_cdr1,
            "L-cdr2": self.l_cdr2,
            "L-cdr3": self.l_cdr3,
        }


class AntigenSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: Literal["upload"] = "upload"
    file: str = "input/antigen.pdb"
    chains: list[str] = Field(default_factory=lambda: ["A"], min_length=1, max_length=16)
    remove_waters: bool = True
    remove_ions: bool = True
    remove_hetero: bool = True
    keep_cofactors: list[str] = Field(default_factory=list)
    docking_mode: Literal["blind"] = "blind"

    @field_validator("chains")
    @classmethod
    def validate_chains(cls, chains: list[str]) -> list[str]:
        cleaned: list[str] = []
        for chain in chains:
            chain = chain.strip()
            if len(chain) != 1 or not chain.isalnum():
                raise ValueError("PDB chain ID 必须是单个字母或数字")
            if chain not in cleaned:
                cleaned.append(chain)
        return cleaned


class JobSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0.0"] = "1.0.0"
    mode: Literal["replay"] = "replay"
    backend: Literal["replay"] = "replay"
    fixture_id: str = "demo_001"
    antibody: CDRInput
    antigen: AntigenSpec
    rights_confirmed: bool
    source_type: Literal["project_authored_synthetic"] = "project_authored_synthetic"

    @model_validator(mode="after")
    def require_rights_confirmation(self) -> "JobSpec":
        if not self.rights_confirmed:
            raise ValueError("必须确认拥有输入与计算所需权利")
        return self


class Capability(BaseModel):
    name: str
    status: CapabilityStatus
    enabled: bool
    reason: str
    provider: str | None = None
    version: str | None = None
    license_status: str | None = None


class StageRecord(BaseModel):
    stage_id: str
    name: str
    status: StageStatus = StageStatus.PENDING
    execution_kind: ExecutionKind = ExecutionKind.REPLAY
    provider: str = "ReplayBackend"
    started_at: datetime | None = None
    ended_at: datetime | None = None
    input_hashes: dict[str, str] = Field(default_factory=dict)
    output_hashes: dict[str, str] = Field(default_factory=dict)
    fixture_id: str | None = None
    fixture_manifest_hash: str | None = None
    notes: list[str] = Field(default_factory=list)
    error: str | None = None


class ArtifactRecord(BaseModel):
    path: str
    sha256: str
    size_bytes: int
    media_type: str
    role: str


class CandidateMetric(BaseModel):
    candidate_id: str
    mean_plddt: float
    cdr_plddt: float
    interface_pae: float
    iptm: float | None = None
    docking_best_score: float
    docking_topk_median: float
    cdr_contact_ratio: float
    pose_consensus: float
    clash_free_ratio: float
    pose_count: int
    rejected_reason: str | None = None


class Manifest(BaseModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    run_id: str
    mode: Literal["replay"] = "replay"
    backend: Literal["replay"] = "replay"
    replay_label: Literal["REPLAY"] = "REPLAY"
    created_at: datetime
    display_timezone: str = "Asia/Taipei"
    input_hashes: dict[str, str]
    parameters: dict[str, object]
    tools: dict[str, object]
    models: dict[str, object]
    capabilities: dict[str, Capability]
    licenses: dict[str, object]
    chain_mappings: dict[str, object]
    stages: list[StageRecord]
    artifacts: list[ArtifactRecord]
    warnings: list[str]
    limitations: list[str]
    fixture_id: str
    fixture_manifest_hash: str


class RunResult(BaseModel):
    run_id: str
    run_dir: str
    zip_path: str
    manifest_path: str
    report_path: str
    stages: list[StageRecord]


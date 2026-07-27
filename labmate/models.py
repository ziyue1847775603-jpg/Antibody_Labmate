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


class LiveLocalTools(BaseModel):
    """Commands installed by the user on the local machine.

    They are deliberately not packaged with Antibody Labmate.  Keeping the
    executable names/paths in the project file makes the provenance record
    inspectable and avoids silently downloading or invoking a cloud service.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    colabfold_batch: str = "colabfold_batch"
    lightdock_setup: str = "lightdock3_setup.py"
    lightdock_run: str = "lightdock3.py"
    lightdock_generate: str = "lgd_generate_conformations.py"
    colabfold_args: list[str] = Field(default_factory=list, max_length=32)
    msa_network_policy: Literal["offline_single_sequence", "public_service_confirmed"] = (
        "offline_single_sequence"
    )
    model_data_policy: Literal["preinstalled_only"] = "preinstalled_only"

    @field_validator("colabfold_args")
    @classmethod
    def reject_nul_arguments(cls, value: list[str]) -> list[str]:
        if any("\x00" in item for item in value):
            raise ValueError("工具参数不得包含 NUL 字符")
        return value

    @model_validator(mode="after")
    def require_explicit_colabfold_network_and_model_policy(self) -> "LiveLocalTools":
        def option_values(name: str) -> list[str]:
            values: list[str] = []
            index = 0
            while index < len(self.colabfold_args):
                argument = self.colabfold_args[index]
                if argument == name:
                    if index + 1 >= len(self.colabfold_args):
                        raise ValueError(f"{name} 缺少参数值")
                    values.append(self.colabfold_args[index + 1])
                    index += 2
                    continue
                prefix = name + "="
                if argument.startswith(prefix):
                    values.append(argument[len(prefix) :])
                index += 1
            return values

        msa_modes = option_values("--msa-mode")
        if len(msa_modes) != 1:
            raise ValueError("必须且只能显式指定一次 ColabFold --msa-mode")
        if self.msa_network_policy == "offline_single_sequence":
            if msa_modes[0] != "single_sequence":
                raise ValueError(
                    "offline_single_sequence 策略只允许 --msa-mode single_sequence"
                )
        elif msa_modes[0] == "single_sequence":
            raise ValueError(
                "public_service_confirmed 策略与 --msa-mode single_sequence 矛盾"
            )

        data_paths = option_values("--data")
        if len(data_paths) != 1 or not data_paths[0]:
            raise ValueError(
                "preinstalled_only 策略要求显式指定一次非空 ColabFold --data"
            )
        model_types = option_values("--model-type")
        if model_types != ["alphafold2_multimer_v3"]:
            raise ValueError(
                "Phase 2a 当前要求显式使用 --model-type alphafold2_multimer_v3"
            )
        return self


class LiveLocalDockingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    steps: Annotated[int, Field(ge=1, le=10000)] = 20
    swarms: Annotated[int, Field(ge=1, le=200)] = 4
    glowworms: Annotated[int, Field(ge=1, le=500)] = 50
    cores: Annotated[int, Field(ge=1, le=64)] = 1
    top_poses_per_candidate: Annotated[int, Field(ge=1, le=20)] = 3
    # LightDock scores are provider/scoring-function dependent.  The user must
    # make the direction explicit rather than the application silently guessing.
    score_direction: Literal["higher_is_better", "lower_is_better"]
    score_name: str = "lightdock_score"


class LiveLocalJobSpec(BaseModel):
    """Phase 2a local, auditable execution contract.

    Candidate sequences and region annotations are supplied by the user or an
    external generator such as IgCraft.  No claim is made that IgCraft itself
    was invoked by this application.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["2.0.0"] = "2.0.0"
    mode: Literal["live_local"] = "live_local"
    backend: Literal["local"] = "local"
    candidate_fasta: str
    candidate_regions_file: str
    antigen: AntigenSpec
    tools: LiveLocalTools = Field(default_factory=LiveLocalTools)
    docking: LiveLocalDockingConfig
    rights_confirmed: bool
    source_type: Literal[
        "user_provided", "igcraft_generated", "project_authored_synthetic"
    ] = "user_provided"

    @model_validator(mode="after")
    def require_rights_confirmation(self) -> "LiveLocalJobSpec":
        if not self.rights_confirmed:
            raise ValueError("必须确认拥有输入、工具及计算所需权利")
        if len(self.antigen.chains) != 1:
            raise ValueError("Live Local v2.0 目前只支持一个抗原链；多链抗原尚未验证")
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
    interface_pae: float | None = None
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

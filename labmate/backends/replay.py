"""Strict fixture-bound Replay backend."""

from __future__ import annotations

import json
from pathlib import Path

from labmate.backends.base import (
    ComputeBackend,
    PredictionBackend,
    PredictionResult,
    normalize_prediction_sequence,
)
from labmate.errors import FixtureIntegrityError
from labmate.models import Capability, CapabilityStatus, JobSpec, RunResult
from labmate.provenance import build_input_hashes, sha256_file, verify_artifact_hashes


class ReplayBackend(ComputeBackend, PredictionBackend):
    name = "replay"

    def __init__(
        self,
        fixture_root: Path,
        *,
        prediction_backend: PredictionBackend | None = None,
    ) -> None:
        self.fixture_root = fixture_root.resolve()
        self.prediction_backend = prediction_backend or self
        self._results: dict[str, RunResult] = {}
        self._statuses: dict[str, str] = {}

    def _load_manifest(self) -> dict[str, object]:
        manifest_path = self.fixture_root / "fixture_manifest.json"
        if not manifest_path.is_file():
            raise FixtureIntegrityError("fixture_manifest.json 不存在")
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise FixtureIntegrityError("fixture_manifest.json 不是有效 JSON") from exc
        if payload.get("schema_version") != "1.0.0":
            raise FixtureIntegrityError("不支持的 fixture schema_version")
        if payload.get("fixture_id") != self.fixture_root.name:
            raise FixtureIntegrityError("fixture ID 与目录名不一致")
        rights = payload.get("rights")
        if not isinstance(rights, dict):
            raise FixtureIntegrityError("fixture 缺少权利元数据")
        required_rights = {
            "redistribution_allowed": True,
            "contains_patent_or_confidential_sequence": False,
            "contains_third_party_binary": False,
            "contains_third_party_tool_output": False,
        }
        for key, expected in required_rights.items():
            if rights.get(key) is not expected:
                raise FixtureIntegrityError(f"fixture 权利 gate 未通过: {key}")
        artifact_hashes = payload.get("artifact_hashes")
        if not isinstance(artifact_hashes, dict) or not artifact_hashes:
            raise FixtureIntegrityError("fixture 缺少 artifact SHA-256 清单")
        verify_artifact_hashes(self.fixture_root, {str(k): str(v) for k, v in artifact_hashes.items()})
        return payload

    def preflight(self, job: JobSpec, antigen_bytes: bytes) -> Capability:
        fixture_manifest = self._load_manifest()
        if job.mode != "replay" or job.backend != "replay":
            raise FixtureIntegrityError("Phase 1 只接受 replay/replay")
        if job.fixture_id != fixture_manifest["fixture_id"]:
            raise FixtureIntegrityError("Job fixture_id 与已验证 fixture 不一致")
        expected_hashes = fixture_manifest.get("input_hashes")
        if not isinstance(expected_hashes, dict):
            raise FixtureIntegrityError("fixture manifest 缺少 input_hashes")
        actual_hashes = build_input_hashes(job, antigen_bytes)
        if actual_hashes != expected_hashes:
            mismatches = [
                key
                for key in sorted(set(actual_hashes) | set(expected_hashes))
                if actual_hashes.get(key) != expected_hashes.get(key)
            ]
            raise FixtureIntegrityError(
                "REPLAY 输入哈希不匹配（"
                + ", ".join(mismatches)
                + "）；请加载 verified demo，不能把固定结果用于自定义输入"
            )
        return Capability(
            name="ReplayBackend",
            status=CapabilityStatus.REPLAY_ONLY,
            enabled=True,
            provider="fixture:demo_001",
            version="1.0.0",
            license_status="fixture CC0-1.0; redistribution gate passed",
            reason="Exact normalized CDR and antigen byte hashes match the verified fixture.",
        )

    def submit(self, job: JobSpec, antigen_bytes: bytes, output_root: Path) -> RunResult:
        self.preflight(job, antigen_bytes)
        from labmate.workflow import execute_replay

        result = execute_replay(
            job=job,
            antigen_bytes=antigen_bytes,
            fixture_root=self.fixture_root,
            output_root=output_root,
            prediction_backend=self.prediction_backend,
        )
        self._results[result.run_id] = result
        self._statuses[result.run_id] = "succeeded"
        return result

    def status(self, job_id: str) -> str:
        return self._statuses.get(job_id, "unknown")

    def cancel(self, job_id: str) -> bool:
        # Replay is synchronous and bounded; never pretend a completed job was cancelled.
        return False

    def collect(self, job_id: str) -> RunResult:
        try:
            return self._results[job_id]
        except KeyError as exc:
            raise FixtureIntegrityError(f"未知或未完成的 Replay job: {job_id}") from exc

    def predict(
        self,
        heavy_chain: str,
        light_chain: str | None,
        antigen_pdb: Path | None = None,
        output_dir: Path | None = None,
    ) -> PredictionResult:
        """Return the exact matching hash-verified fixture structure.

        This stage-level method does not weaken the full Replay input gate:
        ``submit`` still verifies the complete CDR/antigen bundle before any
        workflow output is created.
        """

        del antigen_pdb
        heavy = normalize_prediction_sequence(heavy_chain, label="heavy_chain")
        light = normalize_prediction_sequence(light_chain, label="light_chain")
        fixture_manifest = self._load_manifest()
        matches: list[tuple[str, Path]] = []
        structures_root = self.fixture_root / "colabfold_output"
        for candidate_dir in sorted(structures_root.glob("CAND-*")):
            sequence_map_path = candidate_dir / "sequence_map.json"
            pdb_path = candidate_dir / "ranked_1.pdb"
            if not sequence_map_path.is_file() or not pdb_path.is_file():
                continue
            try:
                sequence_map = json.loads(
                    sequence_map_path.read_text(encoding="utf-8")
                )
            except json.JSONDecodeError as exc:
                raise FixtureIntegrityError(
                    f"Invalid Replay sequence map: {sequence_map_path.name}"
                ) from exc
            chains = sequence_map.get("chains", {})
            if not isinstance(chains, dict):
                continue
            heavy_row = chains.get("H")
            light_row = chains.get("L")
            if not isinstance(heavy_row, dict):
                continue
            if heavy_row.get("sequence") != heavy:
                continue
            if light is None:
                if light_row is not None:
                    continue
            elif not isinstance(light_row, dict) or light_row.get("sequence") != light:
                continue
            matches.append((candidate_dir.name, pdb_path))

        if len(matches) != 1:
            raise FixtureIntegrityError(
                "Replay prediction requires one exact fixture VH/VL sequence match"
            )

        candidate_id, source_pdb = matches[0]
        result_pdb = source_pdb
        if output_dir is not None:
            output_dir = output_dir.resolve()
            output_dir.mkdir(parents=True, exist_ok=True)
            result_pdb = output_dir / "ranked_1.pdb"
            if result_pdb.exists():
                raise FixtureIntegrityError(
                    "Replay prediction output already exists: ranked_1.pdb"
                )
            result_pdb.write_bytes(source_pdb.read_bytes())

        return PredictionResult(
            pdb_path=result_pdb,
            backend_name=self.name,
            status="succeeded",
            metadata={
                "fixture_id": fixture_manifest["fixture_id"],
                "candidate_id": candidate_id,
                "execution_kind": "replay",
                "hash_verified": True,
            },
            warnings=[
                "Deterministic offline fixture replay; no prediction engine executed."
            ],
        )

    @property
    def fixture_manifest_hash(self) -> str:
        return sha256_file(self.fixture_root / "fixture_manifest.json")

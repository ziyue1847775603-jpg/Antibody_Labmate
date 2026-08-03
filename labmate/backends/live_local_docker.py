"""Phase D4: Docker Compose Live Local execution runners.

These executors plug into ``execute_live_local`` (labmate/live_local.py)
by replacing the host ``_run`` tool invocations with container
invocations, while reusing every downstream validation stage
(chain mapping, exact sequence checks, pLDDT, GSO/pose score mapping,
interface analysis, ranking, report, manifest, ZIP).

Architecture (fixed for D4):
    host Labmate Python 3.11 CLI orchestrator
        -> ColabFold GPU worker container
        -> LightDock CPU worker container
        -> Labmate host-side validation/analysis/ranking/report/manifest/ZIP

Security invariants:
- Both workers communicate only via fixed CLI args, exit codes, and
  regular files on shared volumes.
- No Docker socket is mounted anywhere.
- GPU is granted only to the ColabFold service.
- ``network_mode: none`` on the ColabFold service (single_sequence).
- Fail closed on any nonzero exit, timeout, GPU invisibility, missing
  weights, missing rank-1 PDB, or validation failure.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from labmate.backends.colabfold_container import ColabFoldContainerBackend
from labmate.backends.lightdock_container import LightDockContainerBackend
from labmate.errors import InputValidationError, LabmateError

# Reuse the shared validation helpers from the host workflow so there is
# exactly one set of chain/pose/score checks for both execution paths.
from labmate.live_local import (
    ColabFoldResult,
    _parse_lightdock_output,
    _pdb_chain_contract,
    _select_lightdock_solutions,
    _validate_lightdock_pose,
    _write_json,
    sha256_file,
)
from labmate.docking.lightdock import ParsedDockingPose


@dataclass(frozen=True)
class DockerComposeConfig:
    """User-supplied Docker Compose execution configuration."""

    compose_file: str
    docker_bin: str = "docker"
    colabfold_timeout_seconds: int = 1800
    lightdock_timeout_seconds: int = 600


class DockerComposeExecutors:
    """Factory for the two Phase D4 executors.

    Attributes
    ----------
    colabfold_versions / lightdock_versions:
        Filled in by the light preflight (``probe_versions``) so the
        manifest can record container versions.
    """

    def __init__(
        self,
        *,
        compose_file: str,
        docker_bin: str = "docker",
        colabfold_data_root: Path,
        colabfold_cache_root: Path,
        docker_work_root: Path,
        colabfold_timeout_seconds: int = 1800,
        lightdock_timeout_seconds: int = 600,
    ) -> None:
        self._config = DockerComposeConfig(
            compose_file=compose_file,
            docker_bin=docker_bin,
            colabfold_timeout_seconds=colabfold_timeout_seconds,
            lightdock_timeout_seconds=lightdock_timeout_seconds,
        )
        self._data_root = colabfold_data_root.resolve()
        if not self._data_root.is_dir():
            raise ValueError(
                f"colabfold data root must be an existing directory: {self._data_root}"
            )
        self._cache_root = colabfold_cache_root.resolve()
        if not self._cache_root.is_dir():
            raise ValueError(
                f"colabfold cache root must be an existing directory: {self._cache_root}"
            )
        self._work_root = docker_work_root.resolve()
        self._work_root.mkdir(parents=True, exist_ok=True)

        self.colabfold_versions: dict[str, str] = {}
        self.lightdock_versions: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Preflight — probe container versions (requires Docker + GPU)
    # ------------------------------------------------------------------

    def probe_versions(self) -> dict[str, str]:
        """Probe ColabFold and LightDock versions inside their containers."""
        cf_work = self._candidate_colabfold_root("_preflight")
        backend = self._colabfold_backend(cf_work)
        try:
            self.colabfold_versions = backend.version()
        except LabmateError as exc:
            raise LabmateError(
                f"ColabFold container preflight failed: {exc}"
            ) from exc

        ld_work = self._candidate_lightdock_root("_preflight")
        ld_backend = self._lightdock_backend(ld_work)
        try:
            version = ld_backend.version()
        except LabmateError as exc:
            raise LabmateError(
                f"LightDock container preflight failed: {exc}"
            ) from exc
        self.lightdock_versions = {"lightdock": version}
        return {
            "colabfold": self.colabfold_versions.get("colabfold", "not-probed"),
            "lightdock": version,
        }

    # ------------------------------------------------------------------
    # ColabFold executor
    # ------------------------------------------------------------------

    def colabfold_executor(
        self,
        *,
        candidate_id: str,
        chains: dict[str, str],
        candidate_dir: Path,
        run_dir: Path,
    ) -> ColabFoldResult:
        """Predict one VH:VL pair inside the GPU container.

        Returns a ColabFoldResult-compatible object whose PDB has already
        been copied into ``candidate_dir/colabfold/`` (matching the host
        layout) and whose score JSON is preserved.
        """
        docker_root = self._candidate_colabfold_root(candidate_id)
        backend = self._colabfold_backend(docker_root)
        output_root = docker_root / "output" / "out"
        result = backend.predict(
            heavy_chain=chains["H"],
            light_chain=chains["L"],
            output_dir=output_root,
        )
        if result.status != "succeeded" or result.pdb_path is None:
            raise LabmateError(
                f"{candidate_id} ColabFold 容器预测失败: "
                + "; ".join(result.warnings)
            )

        # Copy the rank-1 PDB and its score JSON into the host layout
        # so downstream chain mapping / pLDDT checks are unchanged.
        container_dir = candidate_dir / "colabfold"
        container_dir.mkdir(parents=True, exist_ok=True)
        pdb_dest = container_dir / result.pdb_path.name
        shutil.copy2(result.pdb_path, pdb_dest)

        score_path: Path | None = None
        for candidate in output_root.rglob("*"):
            if candidate.is_file() and "scores_rank_001" in candidate.name:
                score_path = candidate
                break
        if score_path is None:
            # Fall back to any *_scores_rank_*.json
            for candidate in output_root.rglob("*_scores_rank_*.json"):
                score_path = candidate
                break
        if score_path is None:
            raise LabmateError(
                f"{candidate_id} ColabFold 容器输出缺少 score JSON"
            )
        scores = __import__("json").loads(score_path.read_text(encoding="utf-8"))

        return ColabFoldResult(
            pdb_path=pdb_dest,
            score_path=score_path,
            scores=scores,
            rank=1,
            model_tag="alphafold2_multimer_v3_model_1_seed_000",
        )

    # ------------------------------------------------------------------
    # LightDock executor
    # ------------------------------------------------------------------

    def lightdock_executor(
        self,
        *,
        candidate_id: str,
        work: Path,
        ligand: Path,
        cleaned: Path,
        run_dir: Path,
        job: Any,
        expected_sequences: dict[str, str],
        expected_residue_keys: dict[str, list[Any]],
        lightdock_version: str,
    ) -> tuple[list[ParsedDockingPose], list[dict[str, Any]], list[dict[str, Any]]]:
        """Run setup/run/generate inside the CPU container and validate.

        Reuses the shared GSO parsing, solution selection, and pose
        contract validation from the host path.
        """
        docker_root = self._candidate_lightdock_root(candidate_id)
        backend = self._lightdock_backend(docker_root)

        # Copy receptor + ligand into the container inputs dir
        inputs_dir = docker_root / "inputs"
        outputs_dir = docker_root / "outputs"
        inputs_dir.mkdir(parents=True, exist_ok=True)
        outputs_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(cleaned, inputs_dir / "receptor_A.pdb")
        shutil.copy2(ligand, inputs_dir / "antibody_HL.pdb")

        try:
            backend.setup(
                receptor_basename="receptor_A.pdb",
                ligand_basename="antibody_HL.pdb",
                swarms=job.docking.swarms,
                glowworms=job.docking.glowworms,
            )
            backend.run(steps=job.docking.steps, cores=job.docking.cores)
        except LabmateError as exc:
            raise LabmateError(f"{candidate_id} LightDock 容器执行失败: {exc}") from exc

        score_files = list(outputs_dir.glob(f"swarm_*/gso_{job.docking.steps}.out"))
        swarm_ids = {
            int(path.parent.name.removeprefix("swarm_"))
            for path in score_files
            if path.parent.name.startswith("swarm_")
        }
        if swarm_ids != set(range(job.docking.swarms)):
            raise LabmateError(
                f"{candidate_id} LightDock 容器 gso swarm 集合不完整或不一致"
            )
        selected = _select_lightdock_solutions(
            score_files,
            count=job.docking.top_poses_per_candidate,
            score_direction=job.docking.score_direction,
        )
        selected_gso = outputs_dir / "selected_top_poses.gso"
        selected_gso.write_text(
            "\n".join(solution.raw_line for solution in selected) + "\n",
            encoding="utf-8",
        )
        try:
            backend.generate(
                receptor_basename="receptor_A.pdb",
                ligand_basename="antibody_HL.pdb",
                gso_basename="selected_top_poses.gso",
                pose_count=len(selected),
            )
        except LabmateError as exc:
            raise LabmateError(
                f"{candidate_id} LightDock 容器 pose 生成失败: {exc}"
            ) from exc

        poses: list[ParsedDockingPose] = []
        docking_rows: list[dict[str, Any]] = []
        pose_mapping_rows: list[dict[str, Any]] = []
        ligand_sequences, ligand_residue_keys = _pdb_chain_contract(ligand)
        for rank, solution in enumerate(selected, start=1):
            pose_file = outputs_dir / f"lightdock_{rank - 1}.pdb"
            if not pose_file.is_file():
                raise LabmateError(
                    f"{candidate_id} LightDock 容器未生成预期的显式 pose 序号"
                )
            destination = run_dir / "docking" / candidate_id / f"pose_{rank:03d}.pdb"
            shutil.copy2(pose_file, destination)
            _validate_lightdock_pose(
                destination,
                expected_sequences=expected_sequences,
                expected_residue_keys=expected_residue_keys,
            )
            pose_rel = destination.relative_to(run_dir / "docking").as_posix()
            pose = ParsedDockingPose(
                candidate_id,
                rank,
                f"{candidate_id}-P{rank:03d}",
                solution.score,
                job.docking.score_name,
                job.docking.score_direction,
                pose_rel,
                "lightdock",
                lightdock_version,
                job.source_type,
                "executed_local",
            )
            poses.append(pose)
            source_gso = solution.source_path.relative_to(outputs_dir).as_posix()
            mapping = {
                "candidate_id": candidate_id,
                "pose_rank": rank,
                "pose_id": pose.pose_id,
                "swarm_id": solution.swarm_id,
                "glowworm_id": solution.glowworm_id,
                "raw_score": solution.score,
                "score_direction": job.docking.score_direction,
                "source_gso": source_gso,
                "source_gso_sha256": sha256_file(solution.source_path),
                "selected_gso_line_number": rank,
                "generated_filename": pose_file.name,
                "complex_path": pose_rel,
                "pose_sha256": sha256_file(destination),
                "mapping_verification": "explicit_selected_gso_line_to_lightdock_<line_index>.pdb",
            }
            pose_mapping_rows.append(mapping)
            docking_rows.append({**pose.__dict__, **mapping})

        return poses, docking_rows, pose_mapping_rows

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _colabfold_backend(self, work_root: Path) -> ColabFoldContainerBackend:
        return ColabFoldContainerBackend(
            compose_file=self._config.compose_file,
            docker_bin=self._config.docker_bin,
            work_root=work_root,
            data_root=self._data_root,
            cache_root=self._cache_root,
            timeout_seconds=self._config.colabfold_timeout_seconds,
        )

    def _lightdock_backend(self, work_root: Path) -> LightDockContainerBackend:
        return LightDockContainerBackend(
            compose_file=self._config.compose_file,
            docker_bin=self._config.docker_bin,
            work_root=work_root,
            timeout_seconds=self._config.lightdock_timeout_seconds,
        )

    def _candidate_colabfold_root(self, candidate_id: str) -> Path:
        root = self._work_root / candidate_id / "colabfold"
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _candidate_lightdock_root(self, candidate_id: str) -> Path:
        root = self._work_root / candidate_id / "lightdock"
        root.mkdir(parents=True, exist_ok=True)
        return root

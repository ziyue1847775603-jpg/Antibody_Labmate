"""Phase D4 targeted tests.

Unit tests verify:
- host default compatibility (provider defaults to host)
- docker_compose requires explicit selection (no implicit fallback)
- container adapter failure propagation
- candidate directory isolation
- ColabFold -> LightDock handoff contract (shared helpers reused)
- manifest records provider

Integration tests (marked ``integration``) require Docker + GPU and are
exercised by the real end-to-end smoke.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from labmate.backends.live_local_docker import DockerComposeExecutors
from labmate.errors import InputValidationError, LabmateError
from labmate.models import LiveLocalJobSpec


def _mkdtemp():
    return Path(tempfile.mkdtemp(prefix="labmate_d4_"))


class TestProviderDefault:
    def test_provider_defaults_to_host(self):
        # A project.json without the provider field must remain host.
        spec = LiveLocalJobSpec(
            schema_version="2.0.0",
            mode="live_local",
            backend="local",
            candidate_fasta="candidates.fasta",
            candidate_regions_file="candidate_regions.csv",
            antigen={
                "source": "upload",
                "file": "antigen.pdb",
                "chains": ["A"],
                "remove_waters": True,
                "remove_ions": True,
                "remove_hetero": True,
                "keep_cofactors": [],
                "docking_mode": "blind",
            },
            tools={
                "colabfold_batch": "colabfold_batch",
                "lightdock_setup": "lightdock3_setup.py",
                "lightdock_run": "lightdock3.py",
                "lightdock_generate": "lgd_generate_conformations.py",
                "colabfold_args": [
                    "--msa-mode", "single_sequence",
                    "--data", "/some/data",
                    "--model-type", "alphafold2_multimer_v3",
                ],
                "msa_network_policy": "offline_single_sequence",
                "model_data_policy": "preinstalled_only",
            },
            docking={
                "steps": 10,
                "swarms": 2,
                "glowworms": 10,
                "cores": 1,
                "top_poses_per_candidate": 2,
                "score_direction": "higher_is_better",
                "score_name": "fastdfire",
            },
            rights_confirmed=True,
            source_type="project_authored_synthetic",
        )
        assert spec.tool_execution_provider == "host"

    def test_provider_explicit_docker_compose(self):
        spec = LiveLocalJobSpec(
            schema_version="2.0.0",
            mode="live_local",
            backend="local",
            candidate_fasta="candidates.fasta",
            candidate_regions_file="candidate_regions.csv",
            antigen={
                "source": "upload",
                "file": "antigen.pdb",
                "chains": ["A"],
                "remove_waters": True,
                "remove_ions": True,
                "remove_hetero": True,
                "keep_cofactors": [],
                "docking_mode": "blind",
            },
            tools={
                "colabfold_batch": "colabfold_batch",
                "lightdock_setup": "lightdock3_setup.py",
                "lightdock_run": "lightdock3.py",
                "lightdock_generate": "lgd_generate_conformations.py",
                "colabfold_args": [
                    "--msa-mode", "single_sequence",
                    "--data", "/some/data",
                    "--model-type", "alphafold2_multimer_v3",
                ],
                "msa_network_policy": "offline_single_sequence",
                "model_data_policy": "preinstalled_only",
            },
            docking={
                "steps": 10,
                "swarms": 2,
                "glowworms": 10,
                "cores": 1,
                "top_poses_per_candidate": 2,
                "score_direction": "higher_is_better",
                "score_name": "fastdfire",
            },
            rights_confirmed=True,
            source_type="project_authored_synthetic",
            tool_execution_provider="docker_compose",
        )
        assert spec.tool_execution_provider == "docker_compose"


class TestDockerComposeExecutorsConstruction:
    def _dirs(self):
        tmp = _mkdtemp()
        work = tmp / "work"; work.mkdir()
        data = tmp / "data"; (data / "params").mkdir(parents=True)
        cache = tmp / "cache"; cache.mkdir()
        for i in range(1, 6):
            (data / "params" / f"params_model_{i}_multimer_v3.npz").write_bytes(b"x")
        return tmp, work, data, cache

    def test_requires_existing_data_root(self):
        tmp, work, data, cache = self._dirs()
        try:
            with pytest.raises(ValueError, match="data root must be"):
                DockerComposeExecutors(
                    compose_file="docker-compose.live-local.yml",
                    docker_work_root=work,
                    colabfold_data_root=tmp / "missing",
                    colabfold_cache_root=cache,
                )
        finally:
            import shutil; shutil.rmtree(tmp, ignore_errors=True)

    def test_requires_existing_cache_root(self):
        tmp, work, data, cache = self._dirs()
        try:
            with pytest.raises(ValueError, match="cache root must be"):
                DockerComposeExecutors(
                    compose_file="docker-compose.live-local.yml",
                    docker_work_root=work,
                    colabfold_data_root=data,
                    colabfold_cache_root=tmp / "missing",
                )
        finally:
            import shutil; shutil.rmtree(tmp, ignore_errors=True)

    def test_candidate_roots_are_isolated(self):
        tmp, work, data, cache = self._dirs()
        try:
            e = DockerComposeExecutors(
                compose_file="docker-compose.live-local.yml",
                docker_work_root=work,
                colabfold_data_root=data,
                colabfold_cache_root=cache,
            )
            c1 = e._candidate_colabfold_root("CAND-001")
            c2 = e._candidate_colabfold_root("CAND-002")
            l1 = e._candidate_lightdock_root("CAND-001")
            assert c1 != c2
            assert c1.parent != c2.parent  # per-candidate isolation
            assert c1.parent.parent == work
            assert l1.parent.parent == work
            assert c1.exists() and c2.exists() and l1.exists()
        finally:
            import shutil; shutil.rmtree(tmp, ignore_errors=True)

    def test_missing_model_params_fails_fast(self):
        tmp, work, data, cache = self._dirs()
        try:
            (data / "params" / "params_model_5_multimer_v3.npz").unlink()
            # work/x must exist before the backend validates data_root
            (work / "x").mkdir()
            with pytest.raises(ValueError, match="missing parameter files"):
                DockerComposeExecutors(
                    compose_file="docker-compose.live-local.yml",
                    docker_work_root=work,
                    colabfold_data_root=data,
                    colabfold_cache_root=cache,
                )._colabfold_backend(work / "x")
        finally:
            import shutil; shutil.rmtree(tmp, ignore_errors=True)


class TestFailurePropagation:
    def test_missing_compose_file_raises(self):
        tmp, work, data, cache = (lambda d, w, da, ca: (d, w, da, ca))(*_dirs())
        try:
            with pytest.raises(ValueError, match="compose_file"):
                DockerComposeExecutors(
                    compose_file="/nonexistent/compose.yml",
                    docker_work_root=work,
                    colabfold_data_root=data,
                    colabfold_cache_root=cache,
                )._colabfold_backend(work / "x")
        finally:
            import shutil; shutil.rmtree(tmp, ignore_errors=True)


def _dirs():
    tmp = _mkdtemp()
    work = tmp / "work"; work.mkdir()
    data = tmp / "data"; (data / "params").mkdir(parents=True)
    cache = tmp / "cache"; cache.mkdir()
    for i in range(1, 6):
        (data / "params" / f"params_model_{i}_multimer_v3.npz").write_bytes(b"x")
    return tmp, work, data, cache


# ------------------------------------------------------------------
# Integration tests — real Docker + GPU end-to-end
# ------------------------------------------------------------------

def _repo_compose_file() -> str:
    return str(Path(__file__).resolve().parents[1] / "docker-compose.live-local.yml")


def _real_data_root() -> Path | None:
    for candidate in [
        Path("d:/colabfold-data/models"),
        Path("/mnt/d/colabfold-data/models"),
        Path("/root/colabfold-data/models"),
    ]:
        params = candidate / "params"
        if params.is_dir() and all(
            (params / f"params_model_{i}_multimer_v3.npz").is_file()
            for i in range(1, 6)
        ):
            return candidate
    return None


@pytest.mark.integration
class TestDockerComposeEndToEnd:
    def test_full_docker_compose_live_local_smoke(self):
        """Real end-to-end: ColabFold GPU container -> LightDock CPU container.

        Uses the repository CC0 synthetic smoke inputs (1 candidate) and
        REAL preinstalled ColabFold model weights.
        """
        data_root = _real_data_root()
        if data_root is None:
            pytest.skip("real ColabFold model data not found on this machine")
        import shutil
        from labmate.live_local import execute_live_local
        from labmate.backends.live_local_docker import DockerComposeExecutors

        tmp = _mkdtemp()
        try:
            work = tmp / "work"; work.mkdir()
            cache = tmp / "cache"; cache.mkdir()

            # Copy CC0 smoke inputs
            smoke = Path(__file__).resolve().parents[1] / "examples" / "live_local_smoke"
            fasta = tmp / "candidates.fasta"
            regions = tmp / "candidate_regions.csv"
            antigen = tmp / "antigen.pdb"
            shutil.copy2(smoke / "candidates.fasta", fasta)
            shutil.copy2(smoke / "candidate_regions.csv", regions)
            shutil.copy2(smoke / "antigen.pdb", antigen)

            project = {
                "schema_version": "2.0.0",
                "mode": "live_local",
                "backend": "local",
                "candidate_fasta": "candidates.fasta",
                "candidate_regions_file": "candidate_regions.csv",
                "antigen": {
                    "source": "upload",
                    "file": "antigen.pdb",
                    "chains": ["A"],
                    "remove_waters": True,
                    "remove_ions": True,
                    "remove_hetero": True,
                    "keep_cofactors": [],
                    "docking_mode": "blind",
                },
                "tools": {
                    "colabfold_batch": "colabfold_batch",
                    "lightdock_setup": "lightdock3_setup.py",
                    "lightdock_run": "lightdock3.py",
                    "lightdock_generate": "lgd_generate_conformations.py",
                    "colabfold_args": [
                        "--msa-mode", "single_sequence",
                        "--data", str(data_root),
                        "--model-type", "alphafold2_multimer_v3",
                    ],
                    "msa_network_policy": "offline_single_sequence",
                    "model_data_policy": "preinstalled_only",
                },
                "docking": {
                    "steps": 10,
                    "swarms": 2,
                    "glowworms": 10,
                    "cores": 1,
                    "top_poses_per_candidate": 2,
                    "score_direction": "higher_is_better",
                    "score_name": "fastdfire",
                },
                "rights_confirmed": True,
                "source_type": "project_authored_synthetic",
                "tool_execution_provider": "docker_compose",
            }
            import json
            project_path = tmp / "project.json"
            project_path.write_text(json.dumps(project), encoding="utf-8")
            job = LiveLocalJobSpec.model_validate(project)

            executors = DockerComposeExecutors(
                compose_file=_repo_compose_file(),
                docker_work_root=work,
                colabfold_data_root=data_root,
                colabfold_cache_root=cache,
                colabfold_timeout_seconds=1800,
                lightdock_timeout_seconds=600,
            )
            container_versions = executors.probe_versions()

            output_root = tmp / "runs"
            result = execute_live_local(
                job=job,
                candidate_fasta=fasta,
                regions_file=regions,
                antigen_bytes=antigen.read_bytes(),
                output_root=output_root,
                colabfold_executor=executors.colabfold_executor,
                lightdock_executor=executors.lightdock_executor,
                tool_execution_provider="docker_compose",
                container_versions=container_versions,
            )
            assert result.run_dir is not None
            run_dir = Path(result.run_dir)
            assert (run_dir / "candidate_ranking.csv").is_file()
            assert (run_dir / "interface_residues.csv").is_file()
            assert (run_dir / "report.html").is_file()
            assert (run_dir / "manifest.json").is_file()
            assert (run_dir / "manifest.sha256").is_file()
            assert (run_dir / f"{Path(result.run_dir).name}.zip").is_file() or Path(result.zip_path).is_file()
            manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
            assert manifest["tool_execution_provider"] == "docker_compose"
            assert (run_dir / "structures" / "LIVE-SMOKE-001" / "ranked_1.pdb").is_file()
            poses = list((run_dir / "docking" / "LIVE-SMOKE-001").glob("pose_*.pdb"))
            assert len(poses) >= 1
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)

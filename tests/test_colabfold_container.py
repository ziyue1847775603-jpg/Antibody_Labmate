"""Phase D3 ColabFold container backend — unit and integration tests.

Unit tests run without Docker.  Integration tests (marked ``integration``)
require a running Docker daemon with GPU passthrough and the colabfold
image built.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from labmate.backends.colabfold_container import (
    ColabFoldContainerBackend,
    FIXED_COLABFOLD_ARGS,
    _safe_basename,
    _validate_fasta_content,
    _validate_under_root,
    _redact,
    _validate_prediction_pdb,
)
from labmate.errors import InputValidationError


def _mkdtemp():
    return Path(tempfile.mkdtemp(prefix="labmate_d3_"))


def _make_backend(work_root, data_root, cache_root, **kwargs):
    return ColabFoldContainerBackend(
        work_root=work_root,
        data_root=data_root,
        cache_root=cache_root,
        compose_file="docker-compose.live-local.yml",
        **kwargs,
    )


def _fixture_dirs():
    tmp = _mkdtemp()
    work = tmp / "work"; work.mkdir()
    data = tmp / "data"; (data / "params").mkdir(parents=True)
    cache = tmp / "cache"; cache.mkdir()
    for i in range(1, 6):
        (data / "params" / f"params_model_{i}_multimer_v3.npz").write_bytes(b"x")
    return tmp, work, data, cache


# ------------------------------------------------------------------
# Unit tests — no Docker required
# ------------------------------------------------------------------

class TestSafeBasename:
    def test_accepts_valid(self):
        assert _safe_basename("input.fasta", "fasta") == "input.fasta"
        assert _safe_basename("out-1", "dir") == "out-1"

    def test_rejects_traversal(self):
        with pytest.raises(InputValidationError):
            _safe_basename("../../etc/passwd", "fasta")

    def test_rejects_absolute(self):
        with pytest.raises(InputValidationError):
            _safe_basename("/etc/passwd", "fasta")

    def test_rejects_shell_metachars(self):
        with pytest.raises(InputValidationError):
            _safe_basename("a; rm -rf /", "fasta")

    def test_rejects_empty(self):
        with pytest.raises(InputValidationError):
            _safe_basename("", "fasta")


class TestValidateFastaContent:
    GOOD_VH = "EVQLVESGGGLVQPGGSLRLSCAASGFTFSSYAMSWVRQAPGKGLEWVSGISGSGGSTYYADSVKGRFTISRDNSKNTLYLQMNSLRAEDTAVYYCAK"
    GOOD_VL = "DIQMTQSPSSLSASVGDRVTITCRASQGISNYLAWYQQKPGKAPKLLIYAASSLQSGVPSRFSGSGSGTDFTLTISSLQPEDFATYYCQQYNSYPYTFGQGTKVEIK"

    def test_valid_vh_vl(self):
        result = _validate_fasta_content(f">antibody\n{self.GOOD_VH}:{self.GOOD_VL}\n")
        assert result["VH"] == self.GOOD_VH
        assert result["VL"] == self.GOOD_VL

    def test_rejects_empty(self):
        with pytest.raises(InputValidationError, match="empty"):
            _validate_fasta_content("")

    def test_rejects_no_header(self):
        with pytest.raises(InputValidationError, match="header"):
            _validate_fasta_content(f"{self.GOOD_VH}:{self.GOOD_VL}\n")

    def test_rejects_two_records(self):
        with pytest.raises(InputValidationError, match="exactly one record"):
            _validate_fasta_content(f">a\n{self.GOOD_VH}:{self.GOOD_VL}\n>b\n{self.GOOD_VH}:{self.GOOD_VL}\n")

    def test_rejects_missing_separator(self):
        with pytest.raises(InputValidationError, match="':'"):
            _validate_fasta_content(f">a\n{self.GOOD_VH}\n")

    def test_rejects_third_chain(self):
        with pytest.raises(InputValidationError, match="exactly one ':'"):
            _validate_fasta_content(f">a\n{self.GOOD_VH}:{self.GOOD_VL}:ANTIGEN\n")

    def test_rejects_invalid_residues(self):
        with pytest.raises(InputValidationError, match="unsupported amino-acid"):
            _validate_fasta_content(f">a\n{self.GOOD_VH}X:{self.GOOD_VL}\n")

    def test_rejects_empty_chain(self):
        with pytest.raises(InputValidationError, match="non-empty"):
            _validate_fasta_content(f">a\n:{self.GOOD_VL}\n")


class TestValidateUnderRoot:
    def test_within_root_passes(self):
        tmp = _mkdtemp()
        try:
            root = tmp / "work"; root.mkdir()
            child = root / "input" / "x.fasta"; child.parent.mkdir(); child.write_text(">a\nACDE")
            result = _validate_under_root(child, root, "test")
            assert result == child.resolve()
        finally:
            import shutil; shutil.rmtree(tmp, ignore_errors=True)

    def test_outside_root_raises(self):
        tmp = _mkdtemp()
        try:
            root = tmp / "work"; root.mkdir()
            outside = tmp / "other"; outside.mkdir(); f = outside / "x"; f.write_text("y")
            with pytest.raises(InputValidationError, match="路径越界"):
                _validate_under_root(f, root, "test")
        finally:
            import shutil; shutil.rmtree(tmp, ignore_errors=True)


class TestRedact:
    def test_redacts_linux_path(self):
        result = _redact("path /home/user/x", [Path("/work")])
        assert "/home/user" not in result

    def test_redacts_windows_path(self):
        result = _redact("path C:\\Users\\test\\x", [Path("/work")])
        assert "C:\\Users" not in result

    def test_redacts_token(self):
        result = _redact("tok sk-abcdef1234567890abcdef1234567890abcdef12", [Path("/work")])
        assert "sk-abcdef" not in result
        assert "<token-redacted>" in result

    def test_redacts_roots(self):
        root = Path("C:/fake/work")
        result = _redact(f"writing {root}/input/x", [root])
        assert "<local-path>" in result or "fake" not in result


class TestValidatePredictionPdb:
    def _tmp_dir(self):
        return _mkdtemp()

    def _write_pdb(self, path, chains):
        lines = []
        i = 1
        for chain in chains:
            lines.append(f"ATOM  {i:5d}  CA  ALA {chain}   1       1.000   2.000   3.000  1.00  0.00           C  ")
            i += 1
        path.write_text("\n".join(lines) + "\n")

    def test_accepts_two_chains(self):
        tmp = self._tmp_dir()
        try:
            p = tmp / "ranked.pdb"
            self._write_pdb(p, ["A", "B"])
            count, chains = _validate_prediction_pdb(p)
            assert count == 2
            assert chains == ["A", "B"]
        finally:
            import shutil; shutil.rmtree(tmp, ignore_errors=True)

    def test_rejects_empty(self):
        tmp = self._tmp_dir()
        try:
            p = tmp / "ranked.pdb"
            p.write_text("")
            with pytest.raises(ValueError, match="no ATOM"):
                _validate_prediction_pdb(p)
        finally:
            import shutil; shutil.rmtree(tmp, ignore_errors=True)

    def test_rejects_single_chain_when_two_expected(self):
        tmp = self._tmp_dir()
        try:
            p = tmp / "ranked.pdb"
            self._write_pdb(p, ["A"])
            with pytest.raises(ValueError, match="at least 2"):
                _validate_prediction_pdb(p, expect_two_chains=True)
        finally:
            import shutil; shutil.rmtree(tmp, ignore_errors=True)


class TestBackendConstruction:
    def test_requires_dirs(self):
        tmp = _mkdtemp()
        try:
            with pytest.raises(ValueError, match="work_root"):
                _make_backend(tmp / "nope", tmp / "nope", tmp / "nope")
        finally:
            import shutil; shutil.rmtree(tmp, ignore_errors=True)

    def test_requires_model_params(self):
        tmp, work, data, cache = _fixture_dirs()
        try:
            (data / "params" / "params_model_5_multimer_v3.npz").unlink()
            with pytest.raises(ValueError, match="missing parameter files"):
                _make_backend(work, data, cache)
        finally:
            import shutil; shutil.rmtree(tmp, ignore_errors=True)

    def test_requires_compose_file(self):
        tmp, work, data, cache = _fixture_dirs()
        try:
            with pytest.raises(ValueError, match="compose_file"):
                ColabFoldContainerBackend(
                    work_root=work, data_root=data, cache_root=cache,
                    compose_file="/nonexistent/compose.yml",
                )
        finally:
            import shutil; shutil.rmtree(tmp, ignore_errors=True)

    def test_invalid_service_name(self):
        tmp, work, data, cache = _fixture_dirs()
        try:
            with pytest.raises(ValueError, match="service"):
                ColabFoldContainerBackend(
                    work_root=work, data_root=data, cache_root=cache,
                    service="bad service;rm",
                )
        finally:
            import shutil; shutil.rmtree(tmp, ignore_errors=True)

    def test_invalid_docker_bin(self):
        tmp, work, data, cache = _fixture_dirs()
        try:
            with pytest.raises(ValueError, match="docker_bin"):
                ColabFoldContainerBackend(
                    work_root=work, data_root=data, cache_root=cache,
                    docker_bin="bad bin;rm",
                )
        finally:
            import shutil; shutil.rmtree(tmp, ignore_errors=True)

    def test_timeout_bounds(self):
        tmp, work, data, cache = _fixture_dirs()
        try:
            with pytest.raises(ValueError, match="timeout"):
                _make_backend(work, data, cache, timeout_seconds=0)
            with pytest.raises(ValueError, match="timeout"):
                _make_backend(work, data, cache, timeout_seconds=7201)
        finally:
            import shutil; shutil.rmtree(tmp, ignore_errors=True)


class TestFixedParameters:
    def test_fixed_params_are_exact(self):
        # Must match the verified host backend exactly.
        assert FIXED_COLABFOLD_ARGS == [
            "--msa-mode", "single_sequence",
            "--data", "/models/colabfold",
            "--model-type", "alphafold2_multimer_v3",
            "--num-models", "1",
            "--num-recycle", "1",
            "--num-relax", "0",
            "--random-seed", "0",
            "--disable-unified-memory",
            "--compile-mode", "fast",
        ]


# ------------------------------------------------------------------
# Integration tests — require Docker + GPU + REAL model weights
# ------------------------------------------------------------------

def _repo_compose_file() -> str:
    return str(Path(__file__).resolve().parents[1] / "docker-compose.live-local.yml")


# The integration tests must use REAL preinstalled multimer_v3 weights;
# fake weight files (used by the unit-test fixtures) would fail inside
# the container.  Look for a real data root on this machine.
_CANDIDATE_DATA_ROOTS = [
    Path("d:/colabfold-data/models"),
    Path("/mnt/d/colabfold-data/models"),
    Path("/root/colabfold-data/models"),
]


def _real_data_root() -> Path | None:
    for candidate in _CANDIDATE_DATA_ROOTS:
        params = candidate / "params"
        if params.is_dir() and all(
            (params / f"params_model_{i}_multimer_v3.npz").is_file()
            for i in range(1, 6)
        ):
            return candidate
    return None


def _real_cache_root() -> Path:
    import tempfile
    return Path(tempfile.mkdtemp(prefix="labmate_d3_cache_"))


@pytest.mark.integration
class TestColabFoldContainerIntegration:
    def test_version_and_gpu_check(self):
        data_root = _real_data_root()
        if data_root is None:
            pytest.skip("real ColabFold model data not found on this machine")
        tmp, work, _data, _cache = _fixture_dirs()
        cache = _real_cache_root()
        try:
            backend = ColabFoldContainerBackend(
                work_root=work,
                data_root=data_root,
                cache_root=cache,
                compose_file=_repo_compose_file(),
                timeout_seconds=300,
            )
            version = backend.version()
            assert version.get("colabfold", "").startswith("1.6")
            gpu = backend.gpu_check()
            assert "jax gpu device" in gpu.get("gpu_info", "")
        finally:
            import shutil; shutil.rmtree(tmp, ignore_errors=True)
            shutil.rmtree(cache, ignore_errors=True)

    def test_predict_produces_rank1_pdb(self):
        data_root = _real_data_root()
        if data_root is None:
            pytest.skip("real ColabFold model data not found on this machine")
        tmp, work, _data, _cache = _fixture_dirs()
        cache = _real_cache_root()
        try:
            backend = ColabFoldContainerBackend(
                work_root=work,
                data_root=data_root,
                cache_root=cache,
                compose_file=_repo_compose_file(),
                timeout_seconds=1800,
            )
            vh = "EVQLVESGGGLVQPGGSLRLSCAASGFTFSSYAMSWVRQAPGKGLEWVSGISGSGGSTYYADSVKGRFTISRDNSKNTLYLQMNSLRAEDTAVYYCAK"
            vl = "DIQMTQSPSSLSASVGDRVTITCRASQGISNYLAWYQQKPGKAPKLLIYAASSLQSGVPSRFSGSGSGTDFTLTISSLQPEDFATYYCQQYNSYPYTFGQGTKVEIK"
            output_dir = work / "output" / "out"
            result = backend.predict(vh, vl, output_dir=output_dir)
            assert result.status == "succeeded"
            assert result.pdb_path is not None
            assert result.pdb_path.is_file()
            assert result.pdb_path.stat().st_size > 0
        finally:
            import shutil; shutil.rmtree(tmp, ignore_errors=True)
            shutil.rmtree(cache, ignore_errors=True)

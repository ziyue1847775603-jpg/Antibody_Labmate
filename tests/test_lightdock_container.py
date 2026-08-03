"""Phase D1 LightDock container backend — unit and integration tests.

These tests exercise the LightDockContainerBackend Python adapter.
Integration tests (marked ``integration``) require a running Docker
daemon with the lightdock image built.  Unit tests run without Docker.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from labmate.backends.lightdock_container import (
    LightDockContainerBackend,
    _safe_basename,
    _validate_under_root,
    _redact,
)
from labmate.errors import InputValidationError, LabmateError


# ------------------------------------------------------------------
# Unit tests — no Docker required
# ------------------------------------------------------------------

class TestSafeBasename:
    def test_accepts_valid_posix_name(self):
        assert _safe_basename("receptor_A.pdb", "receptor") == "receptor_A.pdb"

    def test_accepts_alphanumeric_with_dashes(self):
        assert _safe_basename("antibody_HL.pdb", "ligand") == "antibody_HL.pdb"

    def test_rejects_path_traversal(self):
        with pytest.raises(InputValidationError, match="single safe basename"):
            _safe_basename("../../../etc/passwd", "bad")

    def test_rejects_absolute_path(self):
        with pytest.raises(InputValidationError, match="single safe basename"):
            _safe_basename("/etc/passwd", "bad")

    def test_rejects_shell_metacharacters(self):
        with pytest.raises(InputValidationError, match="single safe basename"):
            _safe_basename("file; rm -rf /", "bad")

    def test_rejects_empty_string(self):
        with pytest.raises(InputValidationError, match="single safe basename"):
            _safe_basename("", "empty")


class TestValidateUnderRoot:
    @staticmethod
    def _temp_dir():
        import tempfile
        return Path(tempfile.mkdtemp(prefix="labmate_test_"))

    def test_path_within_root_passes(self):
        tmp = self._temp_dir()
        try:
            root = tmp / "work"
            root.mkdir()
            child = root / "inputs" / "test.pdb"
            child.parent.mkdir()
            child.write_text("ATOM")
            result = _validate_under_root(child, root, "test")
            assert result == child.resolve()
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)

    def test_path_outside_root_raises(self):
        tmp = self._temp_dir()
        try:
            root = tmp / "work"
            root.mkdir()
            outside = tmp / "outside" / "test.pdb"
            outside.parent.mkdir()
            outside.write_text("ATOM")
            with pytest.raises(InputValidationError, match="路径越界"):
                _validate_under_root(outside, root, "test")
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)


class TestRedact:
    def test_redacts_linux_absolute_path(self):
        text = "Found at /home/user/secret/output.pdb"
        result = _redact(text, root=Path("/work"))
        assert "/home/user" not in result
        assert "<local-path>" in result

    def test_redacts_windows_absolute_path(self):
        text = "Reading from C:\\Users\\test\\data.pdb"
        result = _redact(text, root=Path("/work"))
        assert "C:\\Users" not in result
        assert "<local-path>" in result

    def test_redacts_token_patterns(self):
        text = "Authorization: sk-abc123def4567890abcdef1234567890abcdef12"
        result = _redact(text, root=Path("/work"))
        assert "sk-abc" not in result
        assert "<token-redacted>" in result

    def test_redacts_work_root(self):
        import tempfile
        root = Path(tempfile.mkdtemp(prefix="labmate_redact_"))
        try:
            text = f"Writing to {root}/outputs/pose_001.pdb"
            result = _redact(text, root=root)
            assert str(root) not in result
            assert "<work-root>" in result
        finally:
            import shutil
            shutil.rmtree(root, ignore_errors=True)


class TestBackendConstruction:
    @staticmethod
    def _temp_dir():
        import tempfile
        return Path(tempfile.mkdtemp(prefix="labmate_test_"))

    def test_requires_valid_timeout(self):
        tmp = self._temp_dir()
        try:
            work = tmp / "work"
            work.mkdir()
            with pytest.raises(ValueError, match="timeout"):
                LightDockContainerBackend(work_root=work, timeout_seconds=0)
            with pytest.raises(ValueError, match="timeout"):
                LightDockContainerBackend(work_root=work, timeout_seconds=3601)
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)

    def test_accepts_valid_timeout(self):
        tmp = self._temp_dir()
        try:
            work = tmp / "work"
            work.mkdir()
            backend = LightDockContainerBackend(work_root=work, timeout_seconds=300)
            assert backend._timeout_seconds == 300
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)

    def test_work_root_is_resolved(self):
        tmp = self._temp_dir()
        try:
            work = tmp / "real_work"
            work.mkdir()
            backend = LightDockContainerBackend(work_root=work)
            assert backend._work_root == work.resolve()
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)


# ------------------------------------------------------------------
# Integration tests — require Docker with built lightdock image
# ------------------------------------------------------------------

@pytest.mark.integration
class TestLightDockContainerVersion:
    def test_version_returns_package_version(self):
        """Verify the container prints the installed LightDock version."""
        import tempfile
        tmp = Path(tempfile.mkdtemp(prefix="labmate_d1_"))
        try:
            work = tmp / "work"
            work.mkdir()
            (work / "inputs").mkdir()
            (work / "outputs").mkdir()

            backend = LightDockContainerBackend(
                work_root=work,
                compose_file="docker-compose.live-local.yml",
            )
            version = backend.version()
            assert version == "0.9.4"
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)


@pytest.mark.integration
class TestLightDockContainerSmoke:
    """Minimal synthetic smoke: setup -> run -> generate -> pose discovery."""

    def test_full_smoke(self):
        import tempfile
        tmp = Path(tempfile.mkdtemp(prefix="labmate_d1_"))
        try:
            work = tmp / "work"
            work.mkdir()
            inputs_dir = work / "inputs"
            inputs_dir.mkdir()
            outputs_dir = work / "outputs"
            outputs_dir.mkdir()

            _write_minimal_pdb(inputs_dir / "receptor_A.pdb", "A", 10)
            _write_minimal_pdb(inputs_dir / "antibody_HL.pdb", "H", 15)

            backend = LightDockContainerBackend(
                work_root=work,
                compose_file="docker-compose.live-local.yml",
                timeout_seconds=120,
            )

            version = backend.version()
            assert version == "0.9.4", f"Expected 0.9.4, got {version}"

            result = backend.setup(
                receptor_basename="receptor_A.pdb",
                ligand_basename="antibody_HL.pdb",
                swarms=1,
                glowworms=5,
            )
            assert result["return_code"] == 0
            assert (outputs_dir / "setup.json").is_file()

            result = backend.run(steps=5, cores=1)
            assert result["return_code"] == 0
            gso_files = list(outputs_dir.glob("swarm_*/gso_5.out"))
            assert len(gso_files) >= 1, "Expected at least one GSO output"

            gso_path = gso_files[0]
            lines = [
                line for line in gso_path.read_text().splitlines()
                if line.strip() and not line.startswith("#")
            ]
            assert len(lines) >= 1, "GSO file has no solutions"

            selected_gso = outputs_dir / "selected.gso"
            selected_gso.write_text(lines[0] + "\n")

            result = backend.generate(
                receptor_basename="receptor_A.pdb",
                ligand_basename="antibody_HL.pdb",
                gso_basename="selected.gso",
                pose_count=1,
            )
            assert result["return_code"] == 0

            pose_files = list(outputs_dir.glob("lightdock_*.pdb"))
            assert len(pose_files) == 1, f"Expected 1 pose, found {len(pose_files)}"
            assert pose_files[0].stat().st_size > 0
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)

    def test_setup_rejects_path_traversal(self):
        import tempfile
        tmp = Path(tempfile.mkdtemp(prefix="labmate_d1_"))
        try:
            work = tmp / "work"
            work.mkdir()
            (work / "inputs").mkdir()
            (work / "outputs").mkdir()
            (work / "inputs" / "receptor_A.pdb").write_text("ATOM")
            (work / "inputs" / "antibody_HL.pdb").write_text("ATOM")

            backend = LightDockContainerBackend(work_root=work)
            with pytest.raises(InputValidationError, match="single safe basename"):
                backend.setup(
                    receptor_basename="../../../etc/passwd",
                    ligand_basename="antibody_HL.pdb",
                    swarms=1,
                    glowworms=5,
                )
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)

    def test_generate_rejects_path_traversal(self):
        import tempfile
        tmp = Path(tempfile.mkdtemp(prefix="labmate_d1_"))
        try:
            work = tmp / "work"
            work.mkdir()
            (work / "inputs").mkdir()
            (work / "outputs").mkdir()

            backend = LightDockContainerBackend(work_root=work)
            with pytest.raises(InputValidationError, match="single safe basename"):
                backend.generate(
                    receptor_basename="receptor_A.pdb",
                    ligand_basename="antibody_HL.pdb",
                    gso_basename="../../etc/passwd",
                    pose_count=1,
                )
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)

    def test_invalid_run_steps_raises(self):
        import tempfile
        tmp = Path(tempfile.mkdtemp(prefix="labmate_d1_"))
        try:
            work = tmp / "work"
            work.mkdir()
            (work / "inputs").mkdir()
            (work / "outputs").mkdir()

            backend = LightDockContainerBackend(work_root=work)
            with pytest.raises(InputValidationError, match="steps"):
                backend.run(steps=0)
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)


def _write_minimal_pdb(path: Path, chain: str, residue_count: int) -> None:
    """Write a minimal PDB with ``residue_count`` ALA ATOM records."""
    lines = []
    atom_index = 1
    for residue_num in range(1, residue_count + 1):
        x = float(residue_num * 3.8)
        for atom_name, (dx, dy, dz) in [
            ("N  ", (-0.5, 0.0, 0.0)),
            ("CA ", (0.0, 0.0, 0.0)),
            ("C  ", (0.5, 0.0, 0.0)),
            ("O  ", (0.0, 0.5, 0.0)),
        ]:
            lines.append(
                f"ATOM  {atom_index:5d} {atom_name} ALA {chain}{residue_num:4d}    "
                f"{x + dx:8.3f}{dy:8.3f}{dz:8.3f}  1.00  0.00           C  "
            )
            atom_index += 1
    lines.append("TER\nEND\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")

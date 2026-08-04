"""Unit tests for the AMD compose file structure.

No Docker daemon or YAML library is required — these tests validate the
raw text of docker-compose.live-local-amd.yml against the AMD contract:
- ColabFold service uses ROCm /dev/kfd + /dev/dri, not NVIDIA driver
- LightDock service is CPU-only and byte-identical to the NVIDIA variant
- Required env variables use :? fail-closed syntax
- Security invariants (no privileged, cap_drop ALL, read_only, no_new_privileges)
"""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
AMD_COMPOSE = REPO / "docker-compose.live-local-amd.yml"
NVIDIA_COMPOSE = REPO / "docker-compose.live-local.yml"


class TestAmdComposeStructure:
    def _read(self, path: Path) -> str:
        return path.read_text(encoding="utf-8")

    def test_file_exists(self):
        assert AMD_COMPOSE.is_file()

    def test_colabfold_uses_rocm_devices(self):
        text = self._read(AMD_COMPOSE)
        assert "/dev/kfd" in text, "ROCm requires /dev/kfd"
        assert "/dev/dri" in text, "ROCm requires /dev/dri"
        # Must NOT mention nvidia in colabfold service section
        colabfold_section = text.split("lightdock:")[0]
        assert colabfold_section.count("nvidia") == 0, (
            "AMD colabfold section must not reference nvidia"
        )

    def test_colabfold_has_group_add_video(self):
        text = self._read(AMD_COMPOSE)
        colabfold_section = text.split("lightdock:")[0]
        assert "group_add:" in colabfold_section
        assert "video" in colabfold_section

    def test_no_driver_nvidia_anywhere(self):
        text = self._read(AMD_COMPOSE)
        assert "driver: nvidia" not in text, (
            "AMD compose must not use driver: nvidia anywhere"
        )

    def test_no_privileged(self):
        text = self._read(AMD_COMPOSE)
        assert "privileged: true" not in text, (
            "AMD compose must not use privileged mode"
        )

    def test_cap_drop_all_both_services(self):
        text = self._read(AMD_COMPOSE)
        assert text.count("cap_drop:") >= 2
        # Each service has "- ALL" under cap_drop = 2 total
        assert text.count("- ALL") >= 2

    def test_read_only_both_services(self):
        text = self._read(AMD_COMPOSE)
        assert text.count("read_only: true") >= 2

    def test_network_mode_none(self):
        text = self._read(AMD_COMPOSE)
        colabfold_section = text.split("lightdock:")[0]
        assert "network_mode: none" in colabfold_section

    def test_variables_use_fail_closed(self):
        text = self._read(AMD_COMPOSE)
        for var in (
            "LABMATE_DOCKER_WORK_ROOT",
            "LABMATE_COLABFOLD_DATA_ROOT",
            "LABMATE_COLABFOLD_CACHE_ROOT",
        ):
            assert f"${{{var}:?" in text, f"{var} must use :? fail-closed syntax"

    def test_fixed_scientific_params_not_embedded_in_compose(self):
        """Scientific parameters live in the entrypoint, not the compose file."""
        text = self._read(AMD_COMPOSE)
        assert "--msa-mode" not in text
        assert "--model-type" not in text

    def test_no_docker_socket_mount(self):
        text = self._read(AMD_COMPOSE)
        assert "/var/run/docker.sock" not in text

    def test_image_names_match_amd_convention(self):
        text = self._read(AMD_COMPOSE)
        assert "antibody-labmate-colabfold-amd:1.6.2" in text
        assert "antibody-labmate-lightdock:0.9.4" in text

    def test_lightdock_has_same_key_attributes_as_nvidia(self):
        """LightDock service must have the same image, volumes, and security
        settings as the NVIDIA variant (CPU-only, no GPU dependency)."""
        amd = self._read(AMD_COMPOSE)
        nv = self._read(NVIDIA_COMPOSE)
        # Core invariants that must match
        for key in (
            "image: antibody-labmate-lightdock:0.9.4",
            "privileged: false",
            "read_only: true",
            "no-new-privileges:true",
        ):
            assert key in amd, f"AMD lightdock must contain: {key}"
            assert nv.count(key) == amd.count(key), (
                f"'{key}' count mismatch between AMD and NVIDIA compose"
            )

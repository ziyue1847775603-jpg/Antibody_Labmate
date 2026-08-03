"""Phase D1: LightDock container worker adapter.

This module translates Labmate LightDock tool invocations into
``docker compose run`` commands targeting the isolated LightDock CPU
container.  It does NOT replace the existing host-executable path; it
provides an alternative backend that communicates solely through fixed
CLI arguments, exit codes, and regular file artifacts on a shared volume.

The container communicates with Labmate only through:
- command-line arguments (list form, no shell string interpolation)
- exit codes
- stdout/stderr captured from the container process
- regular PDB and GSO files written to /work/outputs via a shared volume
  whose host path is injected as LABMATE_DOCKER_WORK_ROOT

Security invariants:
- No docker socket is exposed to any public web container.
- Every input path is validated to reside under the allowed work root.
- The entrypoint in the container enforces a subcommand whitelist.
- No eval, shell, or arbitrary command execution.
- The compose file uses ``${VAR:?}`` syntax -- unset variable = fail.
- Host absolute paths are redacted from captured logs.
- Nonzero exit code -> LabmateError (fail closed).
- All numeric parameters have explicit min/max bounds.
"""

from __future__ import annotations

import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any

from labmate.errors import InputValidationError, LabmateError

# Compose file relative to the repository root
_DEFAULT_COMPOSE_FILE = "docker-compose.live-local.yml"
_DEFAULT_SERVICE = "lightdock"
_DEFAULT_DOCKER_BIN = "docker"

# Parameter bounds
_MAX_SWARMS = 64
_MAX_GLOWWORMS = 1000
_MAX_STEPS = 10000
_MAX_CORES = 64
_MAX_POSE_COUNT = 1000
_MAX_TIMEOUT = 3600

# Regex patterns
_BASENAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_ABSOLUTE_RE = re.compile(r"(?:[A-Za-z]:[\\/]|/(?:mnt|root|home|tmp)/)")
_TOKEN_RE = re.compile(
    r"(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16})"
)
_SAFE_SERVICE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_SAFE_DOCKER_BIN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


# ------------------------------------------------------------------
# Validation helpers
# ------------------------------------------------------------------

def _safe_basename(name: str, label: str) -> str:
    """Reject any string that is not a single safe POSIX basename."""
    if not _BASENAME_RE.fullmatch(name):
        raise InputValidationError(
            f"{label} must be a single safe basename, got: {name!r}"
        )
    return name


def _validate_under_root(path: Path, root: Path, label: str) -> Path:
    """Resolve and confirm a path is within the allowed work root."""
    resolved = path.resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise InputValidationError(
            f"{label} 路径越界: {resolved}"
        ) from exc
    return resolved


def _validate_positive_int(value: int, label: str, max_value: int) -> int:
    """Reject non-positive integers or values exceeding the maximum."""
    if not isinstance(value, int) or value < 1:
        raise InputValidationError(
            f"{label} must be a positive integer, got: {value}"
        )
    if value > max_value:
        raise InputValidationError(
            f"{label} exceeds maximum {max_value}, got: {value}"
        )
    return value


def _redact(text: str, root: Path) -> str:
    """Remove host absolute paths and token patterns from captured text.

    Redact the work-root path first so that generic absolute-path patterns
    don't partially replace it and prevent the full-path match.
    """
    redacted = text
    for variant in (
        str(root.resolve()),
        str(root.resolve()).replace("\\", "/"),
    ):
        if len(variant) >= 4:
            redacted = redacted.replace(variant, "<work-root>")
    redacted = _ABSOLUTE_RE.sub("<local-path>", redacted)
    redacted = _TOKEN_RE.sub("<token-redacted>", redacted)
    return redacted


# ------------------------------------------------------------------
# Backend
# ------------------------------------------------------------------

class LightDockContainerBackend:
    """Invoke LightDock inside the D1 worker container via ``docker compose run``.

    The compose file uses ``${LABMATE_DOCKER_WORK_ROOT:?...}`` to mount
    the host work directory.  This backend sets that variable in the
    subprocess environment so the caller does not need to export it.

    Parameters
    ----------
    compose_file:
        Path to the docker-compose file (default: repo-root
        ``docker-compose.live-local.yml``).  Must exist as a regular file.
    service:
        Compose service name (default: ``lightdock``).  Validated against
        safe pattern.
    work_root:
        Host directory that will be exported as
        ``LABMATE_DOCKER_WORK_ROOT``.  Must exist and be a directory.
        Subdirectories ``inputs/`` and ``outputs/`` are created if missing.
    docker_bin:
        Path or basename of the docker executable.  Validated against
        safe pattern.
    timeout_seconds:
        Per-invocation timeout (1..3600).
    """

    name = "lightdock_container"

    def __init__(
        self,
        *,
        compose_file: str | None = None,
        service: str = _DEFAULT_SERVICE,
        work_root: Path,
        docker_bin: str = _DEFAULT_DOCKER_BIN,
        timeout_seconds: int = 600,
    ) -> None:
        # Validate service name
        if not _SAFE_SERVICE_RE.fullmatch(service):
            raise ValueError(
                f"service name must be alphanumeric with dashes/underscores, "
                f"got: {service!r}"
            )
        self._service = service

        # Validate docker_bin (either a simple name like "docker" or a full path)
        if not _SAFE_DOCKER_BIN_RE.fullmatch(docker_bin):
            raise ValueError(
                f"docker_bin must be a simple executable name or safe path, "
                f"got: {docker_bin!r}"
            )
        self._docker_bin = docker_bin

        # Resolve and validate compose_file
        raw = Path(compose_file or _DEFAULT_COMPOSE_FILE)
        self._compose_file = raw.resolve()
        if not self._compose_file.is_file():
            raise ValueError(
                f"compose_file does not exist or is not a regular file: "
                f"{self._compose_file}"
            )

        # Resolve and validate work_root
        self._work_root = work_root.resolve()
        if not self._work_root.is_dir():
            raise ValueError(
                f"work_root must be an existing directory: {self._work_root}"
            )

        # Ensure subdirectories
        (self._work_root / "inputs").mkdir(parents=True, exist_ok=True)
        (self._work_root / "outputs").mkdir(parents=True, exist_ok=True)

        # Timeout
        if not 1 <= timeout_seconds <= _MAX_TIMEOUT:
            raise ValueError(
                f"LightDock container timeout must be 1..{_MAX_TIMEOUT}s, "
                f"got {timeout_seconds}"
            )
        self._timeout_seconds = timeout_seconds

        # Controlled environment passed to every subprocess invocation.
        # We keep most host env vars for Docker to function correctly
        # (Docker needs HOME/USER/PATH and potentially DOCKER_* vars).
        # The compose file's ${VAR:?} syntax guards the required var.
        #
        # The compose file declares BOTH services, so compose interpolates
        # every referenced variable regardless of which service is run.
        # The ColabFold variables must therefore be present even when
        # invoking the lightdock service; they are unused by lightdock.
        self._env = {
            **os.environ,
            "LABMATE_DOCKER_WORK_ROOT": str(self._work_root),
            "LABMATE_COLABFOLD_DATA_ROOT": str(self._work_root / "colabfold_unused_data"),
            "LABMATE_COLABFOLD_CACHE_ROOT": str(self._work_root / "colabfold_unused_cache"),
        }

    # ------------------------------------------------------------------
    # Public API — mirrors the three LightDock stages
    # ------------------------------------------------------------------

    def version(self) -> str:
        """Return the installed LightDock version inside the container."""
        record = self._run_container(["version"])
        return record["stdout"].strip()

    def setup(
        self,
        receptor_basename: str,
        ligand_basename: str,
        *,
        swarms: int,
        glowworms: int,
        receptor_local: Path | None = None,
        ligand_local: Path | None = None,
    ) -> dict[str, Any]:
        """Run lightdock3_setup.py inside the container.

        The receptor and ligand PDBs must already exist under
        ``<work_root>/inputs/`` after this method copies them into place.
        """
        receptor = _safe_basename(receptor_basename, "receptor")
        ligand = _safe_basename(ligand_basename, "ligand")

        _validate_positive_int(swarms, "swarms", _MAX_SWARMS)
        _validate_positive_int(glowworms, "glowworms", _MAX_GLOWWORMS)

        inputs_dir = self._work_root / "inputs"
        if receptor_local is not None:
            _validate_under_root(receptor_local, self._work_root, "receptor PDB")
            (inputs_dir / receptor).write_bytes(receptor_local.read_bytes())
        if ligand_local is not None:
            _validate_under_root(ligand_local, self._work_root, "ligand PDB")
            (inputs_dir / ligand).write_bytes(ligand_local.read_bytes())

        return self._run_container([
            "setup",
            receptor,
            ligand,
            "-s", str(swarms),
            "-g", str(glowworms),
            "--noxt",
            "--noh",
            "--now",
        ])

    def run(
        self,
        steps: int,
        *,
        cores: int = 1,
    ) -> dict[str, Any]:
        """Run lightdock3.py inside the container."""
        _validate_positive_int(steps, "steps", _MAX_STEPS)
        _validate_positive_int(cores, "cores", _MAX_CORES)

        return self._run_container([
            "run",
            str(steps),
            "-c", str(cores),
        ])

    def generate(
        self,
        receptor_basename: str,
        ligand_basename: str,
        gso_basename: str,
        pose_count: int,
    ) -> dict[str, Any]:
        """Run lgd_generate_conformations.py inside the container."""
        receptor = _safe_basename(receptor_basename, "receptor")
        ligand = _safe_basename(ligand_basename, "ligand")
        gso = _safe_basename(gso_basename, "gso file")

        _validate_positive_int(pose_count, "pose_count", _MAX_POSE_COUNT)

        return self._run_container([
            "generate",
            receptor,
            ligand,
            gso,
            str(pose_count),
        ])

    # ------------------------------------------------------------------
    # Internal — container invocation
    # ------------------------------------------------------------------

    def _run_container(self, args: list[str]) -> dict[str, Any]:
        """Execute ``docker compose run --rm lightdock <args>`` safely.

        Returns a dict with keys: command, stdout, stderr, return_code,
        elapsed_seconds.  Raises LabmateError on nonzero exit or timeout.

        The LABMATE_DOCKER_WORK_ROOT environment variable is set explicitly
        so the compose file's ``${VAR:?}`` interpolation succeeds.
        """
        compose_file = str(self._compose_file)
        safe_args = [self._redact_arg(a) for a in args]

        command = [
            self._docker_bin,
            "compose",
            "-f", compose_file,
            "run",
            "--rm",
            "--no-TTY",
            "--quiet-pull",
            self._service,
            *args,
        ]

        display = " ".join(
            [Path(self._docker_bin).name, "compose", "-f",
             self._compose_file.name, "run", "--rm", self._service]
            + safe_args
        )

        started = time.perf_counter()
        try:
            completed = subprocess.run(
                command,
                cwd=str(self._work_root),
                env=self._env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=self._timeout_seconds,
                encoding="utf-8",
                errors="replace",
                shell=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise LabmateError(
                f"LightDock container timed out after {self._timeout_seconds}s"
            ) from exc
        except OSError as exc:
            raise LabmateError(
                f"Failed to invoke docker ({self._docker_bin}): {exc}"
            ) from exc

        elapsed = round(time.perf_counter() - started, 6)
        stdout = _redact(completed.stdout or "", root=self._work_root)
        stderr = _redact(completed.stderr or "", root=self._work_root)

        record: dict[str, Any] = {
            "command": safe_args,
            "display": display,
            "stdout": stdout,
            "stderr": stderr,
            "return_code": completed.returncode,
            "elapsed_seconds": elapsed,
        }

        if completed.returncode != 0:
            raise LabmateError(
                f"LightDock container failed (exit {completed.returncode}); "
                f"stderr: {stderr[:512]}"
            )

        return record

    @staticmethod
    def _redact_arg(arg: str) -> str:
        """Return a log-safe version of one argument."""
        arg = _ABSOLUTE_RE.sub("<local-path>", arg)
        arg = _TOKEN_RE.sub("<token-redacted>", arg)
        if len(arg) > 120:
            arg = arg[:117] + "..."
        return arg

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
- regular PDB and GSO files written to /work/outputs

Security invariants:
- No docker socket is exposed to any public web container.
- Every input path is validated to reside under the allowed work root.
- The entrypoint in the container enforces a subcommand whitelist.
- No eval, shell, or arbitrary command execution.
- Host absolute paths are redacted from captured logs.
- Nonzero exit code → LabmateError (fail closed).
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

# Validate a filename is a single basename (no path traversal)
_BASENAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_ABSOLUTE_RE = re.compile(r"(?:[A-Za-z]:[\\/]|/(?:mnt|root|home|tmp)/)")
_TOKEN_RE = re.compile(
    r"(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16})"
)


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


def _redact(text: str, root: Path) -> str:
    """Remove host absolute paths and token patterns from captured text.

    Redact the work-root path first so that generic absolute-path patterns
    don't partially replace it and prevent the full-path match.
    """
    redacted = text
    # Redact the resolved root path before generic patterns
    for variant in (
        str(root.resolve()),
        str(root.resolve()).replace("\\", "/"),
    ):
        if len(variant) >= 4:
            redacted = redacted.replace(variant, "<work-root>")
    redacted = _ABSOLUTE_RE.sub("<local-path>", redacted)
    redacted = _TOKEN_RE.sub("<token-redacted>", redacted)
    return redacted


class LightDockContainerBackend:
    """Invoke LightDock inside the D1 worker container via ``docker compose run``.

    Parameters
    ----------
    compose_file:
        Path to the docker-compose file (default: repo-root
        ``docker-compose.live-local.yml``).
    service:
        Compose service name (default: ``lightdock``).
    work_root:
        Host directory mapped to ``/work`` inside the container.
        Input PDBs must already exist under ``<work_root>/inputs/``.
    docker_bin:
        Path to the docker executable (default: ``docker`` on PATH).
    timeout_seconds:
        Per-invocation timeout.
    """

    name = "lightdock_container"

    def __init__(
        self,
        *,
        compose_file: str | None = None,
        service: str = _DEFAULT_SERVICE,
        work_root: Path,
        docker_bin: str = "docker",
        timeout_seconds: int = 600,
    ) -> None:
        self._compose_file = str(compose_file or _DEFAULT_COMPOSE_FILE)
        self._service = service
        self._work_root = work_root.resolve()
        self._docker_bin = docker_bin
        if not 1 <= timeout_seconds <= 3600:
            raise ValueError("LightDock container timeout must be 1..3600 seconds")
        self._timeout_seconds = timeout_seconds

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
        ``<work_root>/inputs/``.  The PDBs passed as *receptor_local* /
        *ligand_local* are validated to be under *work_root* and copied
        into place before the container is invoked.
        """
        receptor = _safe_basename(receptor_basename, "receptor")
        ligand = _safe_basename(ligand_basename, "ligand")

        # If caller provided local paths, copy them into the inputs directory
        inputs_dir = self._work_root / "inputs"
        inputs_dir.mkdir(parents=True, exist_ok=True)
        if receptor_local is not None:
            _validate_under_root(receptor_local, self._work_root, "receptor PDB")
            (inputs_dir / receptor).write_bytes(receptor_local.read_bytes())
        if ligand_local is not None:
            _validate_under_root(ligand_local, self._work_root, "ligand PDB")
            (inputs_dir / ligand).write_bytes(ligand_local.read_bytes())

        outputs_dir = self._work_root / "outputs"
        outputs_dir.mkdir(parents=True, exist_ok=True)

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
        if steps < 1:
            raise InputValidationError(f"LightDock steps must be positive, got {steps}")

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

        if pose_count < 1:
            raise InputValidationError(
                f"pose_count must be positive, got {pose_count}"
            )

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
        """
        compose_file = str(Path(self._compose_file).resolve())
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
            *args,  # list-form — no shell string
        ]

        display = " ".join(
            [self._docker_bin, "compose", "-f",
             Path(compose_file).name, "run", "--rm", self._service]
            + safe_args
        )

        started = time.perf_counter()
        try:
            completed = subprocess.run(
                command,
                cwd=str(self._work_root),
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
                f"Failed to invoke docker: {exc}"
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

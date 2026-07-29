from __future__ import annotations

import importlib.util
import json
import os
import stat
import subprocess
from pathlib import Path

import pytest

from labmate.backends.igfold import IgFoldBackend
from labmate.cli import build_parser


_ONE_TO_THREE = {
    "A": "ALA", "C": "CYS", "D": "ASP", "E": "GLU",
    "F": "PHE", "G": "GLY", "H": "HIS", "I": "ILE",
}


def _worker_module() -> object:
    path = Path(__file__).parents[1] / "labmate" / "workers" / "igfold_worker.py"
    spec = importlib.util.spec_from_file_location("isolated_igfold_worker", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _request(**overrides: object) -> dict[str, object]:
    request: dict[str, object] = {
        "schema_version": 1,
        "heavy_chain": "ACDE",
        "light_chain": "FGHI",
        "output_pdb": "igfold_prediction.pdb",
        "model_count": 1,
        "do_refine": False,
        "do_renum": False,
    }
    request.update(overrides)
    return request


@pytest.mark.parametrize(
    "overrides",
    [
        {"unexpected": True},
        {"light_chain": ""},
        {"heavy_chain": "ACD*"},
        {"output_pdb": "../outside.pdb"},
        {"output_pdb": str(Path("/") / "tmp" / "outside.pdb")},
        {"model_count": 2},
        {"do_refine": True},
        {"do_renum": True},
    ],
)
def test_igfold_worker_rejects_unsafe_request_schema(
    tmp_path: Path, overrides: dict[str, object]
) -> None:
    worker = _worker_module()
    request_path = tmp_path / "request.json"
    request_path.write_text(json.dumps(_request(**overrides)), encoding="utf-8")

    with pytest.raises(ValueError):
        worker._read_request(request_path)


def _make_executable(path: Path) -> Path:
    path.write_text("#!/bin/sh\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def _write_pdb(path: Path, sequences: dict[str, str]) -> None:
    lines: list[str] = []
    serial = 1
    for chain_id, sequence in sequences.items():
        for residue_number, residue in enumerate(sequence, 1):
            lines.append(
                f"ATOM  {serial:5d}  CA  {_ONE_TO_THREE[residue]:>3s} "
                f"{chain_id}{residue_number:4d}    {float(serial):8.3f}{0.0:8.3f}{0.0:8.3f}"
                f"{1.0:6.2f}{20.0:6.2f}           C  "
            )
            serial += 1
    path.write_text("\n".join([*lines, "TER", "END", ""]), encoding="utf-8")


def _successful_worker_run(
    observed: dict[str, object], *, response_status: str = "succeeded",
    pdb_kind: str = "valid",
) -> object:
    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        observed.setdefault("calls", []).append((command, kwargs))
        if command[1] == "--version":
            return subprocess.CompletedProcess(command, 0, stdout="Python 3.10.20\n")
        response_path = Path(command[command.index("--response") + 1])
        worker_dir = response_path.parent
        pdb = worker_dir / "igfold_prediction.pdb"
        if pdb_kind == "valid":
            _write_pdb(pdb, {"H": "ACDE", "L": "FGHI"})
        elif pdb_kind == "empty":
            pdb.write_text("END\n", encoding="utf-8")
        elif pdb_kind == "symlink":
            outside = worker_dir.parent / "outside.pdb"
            _write_pdb(outside, {"H": "ACDE", "L": "FGHI"})
            pdb.symlink_to(outside)
        response_path.write_text(
            json.dumps({
                "schema_version": 1,
                "status": response_status,
                "pdb_filename": "igfold_prediction.pdb",
                "backend_version": "0.4.0",
                "model_count": 1,
                "device": "cpu",
                "native_metrics": {"prmsd": {"shape": [1, 8, 4]}},
                "warnings": [],
            }),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(
            command, 0, stdout="worker output", stderr="OPENAI_API_KEY shell environment variable"
        )
    return fake_run


def test_external_igfold_bridge_uses_list_sanitizes_environment_and_validates_pdb(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    interpreter = _make_executable(tmp_path / "python310")
    observed: dict[str, object] = {}
    monkeypatch.setenv("OPENAI_API_KEY", "sk-" + "x" * 24)
    monkeypatch.setenv("HF_TOKEN", "sensitive")
    monkeypatch.setattr(
        "labmate.backends.igfold.subprocess.run", _successful_worker_run(observed)
    )

    result = IgFoldBackend(igfold_python=interpreter).predict(
        "ACDE", "FGHI", output_dir=tmp_path / "output"
    )

    assert result.status == "succeeded"
    assert result.backend_name == "igfold"
    assert result.pdb_path is not None and result.pdb_path.is_file()
    assert result.metadata["execution_kind"] == "external_interpreter_local_prediction_only"
    assert result.metadata["native_metrics_semantics"] == "backend_native_unscaled"
    assert "plddt" not in result.metadata
    calls = observed["calls"]
    worker_command, worker_options = calls[1]
    assert isinstance(worker_command, list)
    assert worker_command[0] == str(interpreter.resolve())
    assert worker_options["shell"] is False
    assert worker_options["check"] is False
    assert "ACDE" not in worker_command and "FGHI" not in worker_command
    environment = worker_options["env"]
    assert "OPENAI_API_KEY" not in environment
    assert "HF_TOKEN" not in environment
    assert environment["HF_HUB_OFFLINE"] == "1"
    assert "OPENAI_API_KEY" not in result.metadata["stderr"]
    assert "<environment-variable>" in result.metadata["stderr"]
    request = json.loads(
        (tmp_path / "output" / "igfold" / "request.json").read_text(encoding="utf-8")
    )
    assert request["do_refine"] is False and request["do_renum"] is False
    assert (tmp_path / "output" / "igfold" / "request.json").stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize(
    "candidate, message",
    [
        ("missing", "existing regular file"),
        ("directory", "existing regular file"),
        ("nonexecutable", "not executable"),
        ("injection;echo", "executable path"),
    ],
)
def test_external_igfold_bridge_rejects_unsafe_interpreter(
    tmp_path: Path, candidate: str, message: str
) -> None:
    value = tmp_path / candidate
    if candidate == "directory":
        value.mkdir()
    elif candidate == "nonexecutable":
        value.write_text("not executable", encoding="utf-8")
    result = IgFoldBackend(igfold_python=value).predict(
        "ACDE", "FGHI", output_dir=tmp_path / "output"
    )
    assert result.status == "unavailable"
    assert message in result.warnings[0]


@pytest.mark.parametrize(
    "response_status, pdb_kind, expected",
    [
        ("failed", "valid", "reported failure"),
        ("succeeded", "empty", "contains no ATOM/HETATM"),
        ("succeeded", "symlink", "symbolic link"),
    ],
)
def test_external_igfold_bridge_fail_closed_on_bad_worker_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    response_status: str,
    pdb_kind: str,
    expected: str,
) -> None:
    interpreter = _make_executable(tmp_path / "python310")
    monkeypatch.setattr(
        "labmate.backends.igfold.subprocess.run",
        _successful_worker_run({}, response_status=response_status, pdb_kind=pdb_kind),
    )
    result = IgFoldBackend(igfold_python=interpreter).predict(
        "ACDE", "FGHI", output_dir=tmp_path / "output"
    )
    assert result.status == "failed"
    assert result.pdb_path is None
    assert expected in result.warnings[0]


def test_external_igfold_bridge_timeout_and_nonzero_exit_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    interpreter = _make_executable(tmp_path / "python310")

    def timeout_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if command[1] == "--version":
            return subprocess.CompletedProcess(command, 0, stdout="Python 3.10\n")
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr("labmate.backends.igfold.subprocess.run", timeout_run)
    timeout = IgFoldBackend(igfold_python=interpreter, worker_timeout_seconds=1).predict(
        "ACDE", "FGHI", output_dir=tmp_path / "timeout"
    )
    assert timeout.status == "failed" and timeout.warnings == ["IgFold worker timed out"]

    def failed_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if command[1] == "--version":
            return subprocess.CompletedProcess(command, 0, stdout="Python 3.10\n")
        return subprocess.CompletedProcess(command, 9, stdout="", stderr="failed")

    monkeypatch.setattr("labmate.backends.igfold.subprocess.run", failed_run)
    failed = IgFoldBackend(igfold_python=interpreter).predict(
        "ACDE", "FGHI", output_dir=tmp_path / "failed"
    )
    assert failed.status == "failed"
    assert failed.warnings == ["IgFold worker failed with exit code 9"]


def test_igfold_cli_accepts_external_interpreter_only_for_igfold() -> None:
    args = build_parser().parse_args([
        "predict", "--prediction-backend", "igfold", "--heavy-chain", "ACDE",
        "--light-chain", "FGHI", "--igfold-python", "/opt/igfold/python",
    ])
    assert args.igfold_python == Path("/opt/igfold/python")

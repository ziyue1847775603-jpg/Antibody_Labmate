from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from labmate.backends.base import PredictionBackend, PredictionResult
from labmate.backends.colabfold import ColabFoldBackend
from labmate.backends.igfold import IgFoldBackend
from labmate.backends.registry import PREDICTION_BACKEND_NAMES, get_backend
from labmate.backends.replay import ReplayBackend
from labmate.cli import build_parser
from labmate.run import main as prediction_cli_main


def _fixture_sequences(fixture_root: Path) -> tuple[str, str]:
    payload = json.loads(
        (
            fixture_root
            / "colabfold_output"
            / "CAND-001"
            / "sequence_map.json"
        ).read_text(encoding="utf-8")
    )
    return payload["chains"]["H"]["sequence"], payload["chains"]["L"]["sequence"]


def test_backend_discovery(fixture_root: Path) -> None:
    replay = get_backend("replay", fixture_root=fixture_root)
    colabfold = get_backend("colabfold")
    igfold = get_backend("igfold")

    assert PREDICTION_BACKEND_NAMES == ("replay", "colabfold", "igfold")
    assert isinstance(replay, ReplayBackend)
    assert isinstance(colabfold, ColabFoldBackend)
    assert isinstance(igfold, IgFoldBackend)
    assert all(
        isinstance(backend, PredictionBackend)
        for backend in (replay, colabfold, igfold)
    )


def test_workflow_imports_in_fresh_python_process(
    project_root: Path,
) -> None:
    completed = subprocess.run(
        [sys.executable, "-c", "import labmate.workflow"],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
        shell=False,
    )

    assert completed.returncode == 0, completed.stderr


def test_invalid_backend_has_clear_error() -> None:
    with pytest.raises(
        ValueError,
        match=r"Unknown prediction backend 'other'.*replay, colabfold, igfold",
    ):
        get_backend("other")


def test_replay_prediction_preserves_fixture_contract(fixture_root: Path) -> None:
    heavy, light = _fixture_sequences(fixture_root)
    result = get_backend(
        "replay",
        fixture_root=fixture_root,
    ).predict(heavy, light)

    assert result == PredictionResult(
        pdb_path=(
            fixture_root
            / "colabfold_output"
            / "CAND-001"
            / "ranked_1.pdb"
        ),
        backend_name="replay",
        status="succeeded",
        metadata={
            "fixture_id": "demo_001",
            "candidate_id": "CAND-001",
            "execution_kind": "replay",
            "hash_verified": True,
        },
        warnings=[
            "Deterministic offline fixture replay; no prediction engine executed."
        ],
    )


def test_prediction_cli_defaults_to_replay(
    fixture_root: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    heavy, light = _fixture_sequences(fixture_root)
    exit_code = prediction_cli_main(
        [
            "--heavy-chain",
            heavy,
            "--light-chain",
            light,
            "--fixture",
            "demo_001",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["backend_name"] == "replay"
    assert payload["status"] == "succeeded"
    assert payload["metadata"]["hash_verified"] is True


def test_workflow_cli_accepts_explicit_prediction_backend(
    fixture_root: Path,
) -> None:
    args = build_parser().parse_args(
        [
            "run",
            str(fixture_root / "project.yaml"),
            "--prediction-backend",
            "replay",
        ]
    )

    assert args.prediction_backend == "replay"
    assert args.mode == "replay"


def test_colabfold_missing_executable_is_structured_unavailable(
    tmp_path: Path,
) -> None:
    backend = get_backend(
        "colabfold",
        executable=str(tmp_path / "missing" / "colabfold_batch"),
    )
    result = backend.predict("ACDE", "FGHI", output_dir=tmp_path / "output")

    assert result.pdb_path is None
    assert result.backend_name == "colabfold"
    assert result.status == "unavailable"
    assert result.warnings == [
        "ColabFold backend unavailable: colabfold_batch not found"
    ]


def test_colabfold_uses_argument_list_and_captures_process_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = tmp_path / "colabfold_batch"
    executable.write_text("# local test stub; never executed\n", encoding="utf-8")
    model_data = tmp_path / "model-data"
    (model_data / "params").mkdir(parents=True)
    (model_data / "params" / "params_model_1_multimer_v3.npz").write_bytes(
        b"preinstalled-test-weight"
    )
    observed: dict[str, object] = {}

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        observed["command"] = command
        observed["kwargs"] = kwargs
        kwargs["stdout"].write(f"output at {command[2]}\n")
        kwargs["stderr"].write(
            f"using data {model_data.resolve()}\n"
            "CUDA_ERROR_OUT_OF_MEMORY recovered\n"
            "JAX_ENABLE_X64 shell environment variable\n"
        )
        prediction_dir = Path(command[2])
        (prediction_dir / "antibody_unrelaxed_rank_001_model_1.pdb").write_text(
            "ATOM      1  CA  ALA A   1       0.000   0.000   0.000  1.00 50.00           C\n"
            "ATOM      2  CA  GLY B   1       1.000   1.000   1.000  1.00 50.00           C\n"
            "END\n",
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(
            command,
            returncode=0,
        )

    monkeypatch.setattr(
        "labmate.backends.colabfold.subprocess.run",
        fake_run,
    )
    backend = get_backend(
        "colabfold",
        executable=str(executable),
        model_data_dir=model_data,
    )
    result = backend.predict("ACDE", "FGHI", output_dir=tmp_path / "output")

    assert result.status == "succeeded"
    assert result.pdb_path is not None and result.pdb_path.is_file()
    run_options = observed["kwargs"]
    assert run_options["text"] is True
    assert run_options["check"] is False
    assert run_options["shell"] is False
    assert "stdout" in run_options and "stderr" in run_options
    command = observed["command"]
    assert isinstance(command, list)
    assert command[0] == str(executable.resolve())
    assert "--msa-mode" in command
    assert "single_sequence" in command
    assert (
        tmp_path / "output" / "input.fasta"
    ).read_text(encoding="utf-8") == ">antibody\nACDE:FGHI\n"
    assert "--model-type" in command
    assert "alphafold2_multimer_v3" in command
    assert command[command.index("--num-models") + 1] == "1"
    assert command[command.index("--num-recycle") + 1] == "1"
    assert command[command.index("--num-relax") + 1] == "0"
    assert "--disable-unified-memory" in command
    assert command[command.index("--compile-mode") + 1] == "fast"
    assert str(tmp_path.resolve()) not in result.metadata["stdout"]
    assert str(model_data.resolve()) not in result.metadata["stderr"]
    assert "JAX_ENABLE_X64" not in result.metadata["stderr"]
    assert "<environment-variable>" in result.metadata["stderr"]
    assert result.metadata["stdout_log"] == "colabfold.stdout.log"
    assert result.metadata["stderr_log"] == "colabfold.stderr.log"
    assert result.metadata["chains"] == ["A", "B"]
    assert result.metadata["atom_count"] == 2
    assert result.warnings == [
        "ColabFold completed after GPU memory allocation warnings; "
        "review colabfold.stderr.log."
    ]


def test_colabfold_refuses_symlinked_pdb_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = tmp_path / "colabfold_batch"
    executable.write_text("# local test stub; never executed\n", encoding="utf-8")
    model_data = tmp_path / "model-data"
    (model_data / "params").mkdir(parents=True)
    (model_data / "params" / "params_model_1_multimer_v3.npz").write_bytes(
        b"preinstalled-test-weight"
    )
    outside_pdb = tmp_path / "outside.pdb"
    outside_pdb.write_text(
        "ATOM      1  CA  ALA A   1       0.000   0.000   0.000  1.00 50.00           C\n"
        "ATOM      2  CA  GLY B   1       1.000   1.000   1.000  1.00 50.00           C\n",
        encoding="utf-8",
    )

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        Path(
            command[2],
            "antibody_unrelaxed_rank_001_model_1.pdb",
        ).symlink_to(outside_pdb)
        return subprocess.CompletedProcess(command, returncode=0)

    monkeypatch.setattr(
        "labmate.backends.colabfold.subprocess.run",
        fake_run,
    )
    result = ColabFoldBackend(
        executable=str(executable),
        model_data_dir=model_data,
    ).predict("ACDE", "FGHI", output_dir=tmp_path / "output")

    assert result.status == "failed"
    assert result.pdb_path is None
    assert result.warnings == [
        "ColabFold output contains a symbolic link; refusing unsafe output discovery"
    ]


_ONE_TO_THREE = {
    "A": "ALA",
    "C": "CYS",
    "D": "ASP",
    "E": "GLU",
    "F": "PHE",
    "G": "GLY",
    "H": "HIS",
    "I": "ILE",
}


def _write_test_antibody_pdb(
    path: Path,
    sequences: dict[str, str],
) -> None:
    lines: list[str] = []
    serial = 1
    for chain_id, sequence in sequences.items():
        for residue_number, residue in enumerate(sequence, start=1):
            lines.append(
                f"ATOM  {serial:5d}  CA  {_ONE_TO_THREE[residue]:>3s} "
                f"{chain_id}{residue_number:4d}    "
                f"{float(serial):8.3f}{0.0:8.3f}{0.0:8.3f}"
                f"{1.0:6.2f}{20.0:6.2f}           C  "
            )
            serial += 1
    path.write_text("\n".join([*lines, "TER", "END", ""]), encoding="utf-8")


class _FakeIgFoldRunner:
    observed_options: dict[str, object] = {}

    def fold(
        self,
        output_path: str,
        *,
        sequences: dict[str, str],
        do_refine: bool,
        do_renum: bool,
    ) -> None:
        self.observed_options = {
            "sequences": sequences,
            "do_refine": do_refine,
            "do_renum": do_renum,
        }
        _write_test_antibody_pdb(Path(output_path), sequences)


def test_prediction_result_format_with_injected_igfold_runner(
    tmp_path: Path,
) -> None:
    runner = _FakeIgFoldRunner()
    backend = IgFoldBackend(runner_factory=lambda: runner)
    result = backend.predict("acde", "fghi", output_dir=tmp_path)

    assert isinstance(result, PredictionResult)
    assert result.model_dump().keys() == {
        "pdb_path",
        "backend_name",
        "status",
        "metadata",
        "warnings",
    }
    assert result.status == "succeeded"
    assert result.backend_name == "igfold"
    assert result.metadata["chains"] == ["H", "L"]
    assert result.metadata["residue_counts"] == {"H": 4, "L": 4}
    assert result.metadata["sequence_preserved"] is True
    assert result.metadata["refinement"] is False
    assert result.metadata["renumbering"] is False
    assert result.metadata["stdout_log"] == "igfold.stdout.log"
    assert result.metadata["stderr_log"] == "igfold.stderr.log"
    assert runner.observed_options == {
        "sequences": {"H": "ACDE", "L": "FGHI"},
        "do_refine": False,
        "do_renum": False,
    }


def test_igfold_missing_environment_is_structured_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "labmate.backends.igfold.importlib.util.find_spec",
        lambda name: None,
    )
    result = get_backend("igfold").predict("ACDE", "FGHI")

    assert result.status == "unavailable"
    assert result.warnings == ["IgFold backend unavailable"]


def test_igfold_requires_paired_valid_sequences(tmp_path: Path) -> None:
    backend = IgFoldBackend(runner_factory=_FakeIgFoldRunner)

    result = backend.predict("ACDE", None, output_dir=tmp_path / "single")
    assert result.status == "failed"
    assert result.warnings == [
        "IgFold prediction-only backend requires a paired VH/VL input"
    ]

    with pytest.raises(ValueError, match="heavy_chain must not be empty"):
        backend.predict("", "FGHI", output_dir=tmp_path / "empty")
    with pytest.raises(ValueError, match="unsupported amino-acid symbols"):
        backend.predict("ACDX", "FGHI", output_dir=tmp_path / "invalid")


def test_igfold_refuses_nonempty_output_directory(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    (output_dir / "old.pdb").write_text("old output", encoding="utf-8")

    result = IgFoldBackend(runner_factory=_FakeIgFoldRunner).predict(
        "ACDE",
        "FGHI",
        output_dir=output_dir,
    )

    assert result.status == "failed"
    assert result.pdb_path is None
    assert result.warnings == [
        "IgFold output directory must be empty to prevent stale-output selection"
    ]


def test_igfold_failure_cannot_promote_leftover_pdb(
    tmp_path: Path,
) -> None:
    class FailingRunner:
        def fold(
            self,
            output_path: str,
            *,
            sequences: dict[str, str],
            do_refine: bool,
            do_renum: bool,
        ) -> None:
            _write_test_antibody_pdb(Path(output_path), sequences)
            raise RuntimeError(
                f"\x1b[31mfailed at {tmp_path} with sk-{'a' * 24} "
                f"{'x' * (5 * 1024)}"
            )

    result = IgFoldBackend(runner_factory=FailingRunner).predict(
        "ACDE",
        "FGHI",
        output_dir=tmp_path / "output",
    )

    assert result.status == "failed"
    assert result.pdb_path is None
    assert str(tmp_path) not in result.warnings[0]
    assert "sk-" not in result.warnings[0]
    assert "<token-redacted>" in result.warnings[0]
    assert "\x1b" not in result.warnings[0]
    assert len(result.warnings[0].encode()) < 4200
    assert result.warnings[0].endswith("<warning truncated>")


def test_igfold_rejects_symlinked_pdb_and_sequence_mismatch(
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside.pdb"
    _write_test_antibody_pdb(outside, {"H": "ACDE", "L": "FGHI"})

    class SymlinkRunner:
        def fold(
            self,
            output_path: str,
            *,
            sequences: dict[str, str],
            do_refine: bool,
            do_renum: bool,
        ) -> None:
            Path(output_path).symlink_to(outside)

    symlink_result = IgFoldBackend(runner_factory=SymlinkRunner).predict(
        "ACDE",
        "FGHI",
        output_dir=tmp_path / "symlink-output",
    )
    assert symlink_result.status == "failed"
    assert symlink_result.pdb_path is None
    assert "symbolic link" in symlink_result.warnings[0]

    class MismatchRunner:
        def fold(
            self,
            output_path: str,
            *,
            sequences: dict[str, str],
            do_refine: bool,
            do_renum: bool,
        ) -> None:
            _write_test_antibody_pdb(
                Path(output_path),
                {"H": "ACDE", "L": "FGHH"},
            )

    mismatch_result = IgFoldBackend(runner_factory=MismatchRunner).predict(
        "ACDE",
        "FGHI",
        output_dir=tmp_path / "mismatch-output",
    )
    assert mismatch_result.status == "failed"
    assert mismatch_result.pdb_path is None
    assert "sequence does not exactly match input" in mismatch_result.warnings[0]


def test_igfold_logs_are_sanitized_and_metadata_is_bounded(
    tmp_path: Path,
) -> None:
    class NoisyRunner:
        def fold(
            self,
            output_path: str,
            *,
            sequences: dict[str, str],
            do_refine: bool,
            do_renum: bool,
        ) -> None:
            print(f"{tmp_path} {'x' * (70 * 1024)}")
            print("AWS_SECRET_ACCESS_KEY shell environment variable", file=sys.stderr)
            _write_test_antibody_pdb(Path(output_path), sequences)

    result = IgFoldBackend(runner_factory=NoisyRunner).predict(
        "ACDE",
        "FGHI",
        output_dir=tmp_path / "output",
    )

    assert result.status == "succeeded"
    assert "<log excerpt:" in result.metadata["stdout"]
    assert len(result.metadata["stdout"].encode()) < 66 * 1024
    assert str(tmp_path) not in result.metadata["stdout"]
    assert "AWS_SECRET_ACCESS_KEY" not in result.metadata["stderr"]
    assert "<environment-variable>" in result.metadata["stderr"]
    stdout_log = tmp_path / "output" / result.metadata["stdout_log"]
    assert str(tmp_path) not in stdout_log.read_text(encoding="utf-8")

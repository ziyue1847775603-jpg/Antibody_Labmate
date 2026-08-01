import json
from pathlib import Path

import pytest

from labmate.backends.base import PredictionResult
from labmate.docking.lightdock import (
    NATIVE_SCORE_NAME,
    NATIVE_SCORE_SEMANTICS,
    LocalLightDockExecutor,
    _UnrankedGsoRow,
    _rank_gso_rows,
)
from labmate.prediction_artifact import DockingInput, docking_input, prediction_artifact


_AA = {"A": "ALA", "C": "CYS", "D": "ASP", "E": "GLU", "F": "PHE", "G": "GLY", "H": "HIS", "I": "ILE"}


def _pdb(path: Path, chains: dict[str, str]) -> None:
    rows: list[str] = []; serial = 1
    for chain, sequence in chains.items():
        for residue_number, amino_acid in enumerate(sequence, 1):
            rows.append(f"ATOM  {serial:5d}  CA  {_AA[amino_acid]:>3s} {chain}{residue_number:4d}    {float(serial):8.3f}{0.0:8.3f}{0.0:8.3f}{1.0:6.2f}{20.0:6.2f}           C  ")
            serial += 1
    path.write_text("\n".join(rows) + "\nEND\n", encoding="utf-8")


def _script(path: Path, source: str) -> Path:
    path.write_text("#!/bin/sh\nset -eu\n" + source, encoding="utf-8")
    path.chmod(0o700)
    return path


def _handoff(tmp_path: Path) -> DockingInput:
    antibody, antigen = tmp_path / "antibody.pdb", tmp_path / "antigen.pdb"
    _pdb(antibody, {"H": "ACDE", "L": "FGHI"}); _pdb(antigen, {"A": "ACDE"})
    result = PredictionResult(pdb_path=antibody, backend_name="igfold", status="succeeded")
    artifact = prediction_artifact(result, heavy_chain="ACDE", light_chain="FGHI", allowed_root=tmp_path)
    return docking_input(artifact, antigen_pdb=antigen, allowed_root=tmp_path, output_root=tmp_path / "handoff")


def _executor(tmp_path: Path, *, sampling: str = "mkdir -p swarm_0\nprintf '%s\\n' '(0,0,0,0,0,0,0) 0 0 0 0 0 2.0' > swarm_0/gso_5.out\n") -> LocalLightDockExecutor:
    setup = _script(tmp_path / "setup", "printf '{}' > setup.json\n")
    sample = _script(tmp_path / "sample", sampling)
    conform = _script(tmp_path / "conform", 'cat "$1" "$2" > lightdock_0.pdb\n')
    return LocalLightDockExecutor(setup_executable=setup, sampling_executable=sample, conformation_executable=conform)


def _multi_conformation_script(*, skip_index: int | None = None, unique: bool = True) -> str:
    skip = "" if skip_index is None else f'if [ "$index" -eq {skip_index} ]; then index=$((index + 1)); continue; fi\n'
    remark = 'printf "REMARK SYNTHETIC TEST FIXTURE %s\\n" "$index" >> "lightdock_$index.pdb"\n' if unique else ""
    return (
        'count="$4"\nindex=0\nwhile [ "$index" -lt "$count" ]; do\n'
        + skip
        + 'cat "$1" "$2" > "lightdock_$index.pdb"\n'
        + remark
        + 'index=$((index + 1))\ndone\n'
    )


def test_fake_lightdock_executes_explicit_gso_to_validated_pose(tmp_path: Path) -> None:
    result = _executor(tmp_path).execute(_handoff(tmp_path), allowed_root=tmp_path, output_dir=tmp_path / "output", timeout_seconds=10)
    assert result.status == "succeeded"
    assert result.selected_pose == "poses/pose_001.pdb"
    assert result.pose_records[0].global_tool_score_rank == 1
    assert result.pose_records[0].swarm_id == 0
    assert result.pose_records[0].swarm_local_rank == 1
    assert result.pose_records[0].gso_row_id == 0
    assert result.pose_records[0].native_score_name == "fastdfire"
    assert "higher_is_better" in result.pose_records[0].native_score_semantics
    assert result.requested_pose_count == 1
    assert result.validated_pose_count == 1
    assert result.native_scores[0]["score"] == 2.0
    assert (tmp_path / "output" / "docking_manifest.json").is_file()
    assert (tmp_path / "output" / "poses" / "pose_001.pdb").read_bytes().startswith(b"ATOM")


def test_explicit_lightdock_cores_are_forwarded_and_recorded(tmp_path: Path) -> None:
    sampling = (
        'printf "%s\\n" "$@" > sampling_args.txt\n'
        "mkdir -p swarm_0\n"
        "printf '%s\\n' '(0,0,0,0,0,0,0) 0 0 0 0 0 2.0' > swarm_0/gso_5.out\n"
    )
    result = _executor(tmp_path, sampling=sampling).execute(
        _handoff(tmp_path),
        allowed_root=tmp_path,
        output_dir=tmp_path / "output",
        timeout_seconds=10,
        cores=3,
    )
    assert (tmp_path / "output" / "work" / "sampling_args.txt").read_text(
        encoding="utf-8"
    ).splitlines() == ["setup.json", "5", "-c", "3", "-sg", "0"]
    manifest = json.loads(
        (tmp_path / "output" / "docking_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["parameters"]["cores"] == 3
    assert result.status == "succeeded"


def test_fake_lightdock_preserves_tool_native_multi_pose_order(tmp_path: Path) -> None:
    setup = _script(tmp_path / "setup", "printf '{}' > setup.json\n")
    sampling = _script(
        tmp_path / "sample",
        """\
mkdir -p swarm_0 swarm_1 swarm_2
printf '%s\n' \
  '(0,0,0,0,0,0,0) 0 0 0 0 0 9.0' \
  '(0,0,0,0,0,0,0) 0 0 0 0 0 6.0' \
  '(0,0,0,0,0,0,0) 0 0 0 0 0 3.0' \
  '(0,0,0,0,0,0,0) 0 0 0 0 0 0.0' > swarm_0/gso_5.out
printf '%s\n' \
  '(0,0,0,0,0,0,0) 0 0 0 0 0 8.0' \
  '(0,0,0,0,0,0,0) 0 0 0 0 0 5.0' \
  '(0,0,0,0,0,0,0) 0 0 0 0 0 2.0' \
  '(0,0,0,0,0,0,0) 0 0 0 0 0 -1.0' > swarm_1/gso_5.out
printf '%s\n' \
  '(0,0,0,0,0,0,0) 0 0 0 0 0 7.0' \
  '(0,0,0,0,0,0,0) 0 0 0 0 0 4.0' \
  '(0,0,0,0,0,0,0) 0 0 0 0 0 1.0' \
  '(0,0,0,0,0,0,0) 0 0 0 0 0 -2.0' > swarm_2/gso_5.out
""",
    )
    conform = _script(
        tmp_path / "conform",
        _multi_conformation_script(),
    )
    executor = LocalLightDockExecutor(setup_executable=setup, sampling_executable=sampling, conformation_executable=conform)
    result = executor.execute(_handoff(tmp_path), allowed_root=tmp_path, output_dir=tmp_path / "output", timeout_seconds=10, swarms=3, poses_per_case=10)
    assert [row.native_score for row in result.pose_records] == [9.0, 8.0, 7.0, 6.0, 5.0, 4.0, 3.0, 2.0, 1.0, 0.0]
    assert [row.swarm_id for row in result.pose_records] == [0, 1, 2, 0, 1, 2, 0, 1, 2, 0]
    assert [row.global_tool_score_rank for row in result.pose_records] == list(range(1, 11))
    assert [row.tool_native_rank for row in result.pose_records] == list(range(1, 11))
    assert len(set(result.pose_sha256.values())) == 10
    assert all(row.global_rank_method == "lightdock_native_score_cross_swarm_sort_v1" for row in result.pose_records)
    assert result.selected_pose == "poses/pose_001.pdb"
    assert all(not Path(row.pose_path or "").is_absolute() for row in result.pose_records)
    assert all(row.provenance["gso_sha256"] for row in result.pose_records)
    assert all(row.provenance["gso_path"].startswith("work/swarm_") for row in result.pose_records)
    manifest = json.loads((tmp_path / "output" / "docking_manifest.json").read_text(encoding="utf-8"))
    assert manifest["global_rank_is_lightdock_native_rank"] is False
    assert manifest["unique_validated_pose_count"] == 10
    assert '"affinity":' not in json.dumps(manifest).lower()


def test_cross_swarm_tie_break_and_failed_rank_do_not_reorder(tmp_path: Path) -> None:
    setup = _script(tmp_path / "setup", "printf '{}' > setup.json\n")
    sampling = _script(
        tmp_path / "sample",
        """\
mkdir -p swarm_0 swarm_1
printf '%s\n' \
  '(0,0,0,0,0,0,0) 0 0 0 0 0 5.0' \
  '(0,0,0,0,0,0,0) 0 0 0 0 0 3.0' \
  '(0,0,0,0,0,0,0) 0 0 0 0 0 1.0' > swarm_0/gso_5.out
printf '%s\n' \
  '(0,0,0,0,0,0,0) 0 0 0 0 0 5.0' \
  '(0,0,0,0,0,0,0) 0 0 0 0 0 4.0' \
  '(0,0,0,0,0,0,0) 0 0 0 0 0 2.0' > swarm_1/gso_5.out
""",
    )
    conform = _script(
        tmp_path / "conform",
        _multi_conformation_script(skip_index=3, unique=False),
    )
    result = LocalLightDockExecutor(
        setup_executable=setup,
        sampling_executable=sampling,
        conformation_executable=conform,
    ).execute(
        _handoff(tmp_path),
        allowed_root=tmp_path,
        output_dir=tmp_path / "output",
        timeout_seconds=10,
        swarms=2,
        poses_per_case=6,
    )
    assert [(row.global_tool_score_rank, row.swarm_id, row.gso_row_id) for row in result.pose_records[:2]] == [(1, 0, 0), (2, 1, 0)]
    assert result.pose_records[3].global_tool_score_rank == 4
    assert result.pose_records[3].generation_status == "failed"
    assert result.pose_records[4].global_tool_score_rank == 5
    assert result.selected_pose_reason == "first_validated_global_tool_score_rank"


def _candidate(
    tmp_path: Path,
    *,
    swarm_id: int,
    row_id: int,
    score: float,
    score_name: str = NATIVE_SCORE_NAME,
    score_semantics: str = NATIVE_SCORE_SEMANTICS,
) -> _UnrankedGsoRow:
    source = tmp_path / f"swarm_{swarm_id}" / "gso_5.out"
    return _UnrankedGsoRow(
        swarm_id=swarm_id,
        gso_row_id=row_id,
        score=score,
        raw_line=f"row-{swarm_id}-{row_id}",
        source_path=source,
        source_sha256="a" * 64,
        native_score_name=score_name,
        native_score_semantics=score_semantics,
    )


def test_numeric_swarm_and_gso_row_tie_break_is_stable(tmp_path: Path) -> None:
    ranked = _rank_gso_rows(
        [
            _candidate(tmp_path, swarm_id=10, row_id=0, score=5.0),
            _candidate(tmp_path, swarm_id=2, row_id=3, score=5.0),
            _candidate(tmp_path, swarm_id=2, row_id=1, score=5.0),
        ]
    )
    assert [(row.swarm_id, row.gso_row_id) for row in ranked] == [
        (2, 1),
        (2, 3),
        (10, 0),
    ]


def test_cross_swarm_sort_direction_comes_from_declared_semantics(
    tmp_path: Path,
) -> None:
    semantics = "synthetic tool-native score; lower_is_better; not affinity"
    ranked = _rank_gso_rows(
        [
            _candidate(
                tmp_path,
                swarm_id=0,
                row_id=0,
                score=2.0,
                score_semantics=semantics,
            ),
            _candidate(
                tmp_path,
                swarm_id=1,
                row_id=0,
                score=-1.0,
                score_semantics=semantics,
            ),
        ]
    )
    assert [row.score for row in ranked] == [-1.0, 2.0]


@pytest.mark.parametrize(
    ("changed_field", "message"),
    [
        ("name", "inconsistent score names"),
        ("semantics", "inconsistent score semantics"),
    ],
)
def test_cross_swarm_score_contract_mismatch_fails_closed(
    tmp_path: Path, changed_field: str, message: str
) -> None:
    first = _candidate(tmp_path, swarm_id=0, row_id=0, score=2.0)
    second = _candidate(
        tmp_path,
        swarm_id=1,
        row_id=0,
        score=1.0,
        score_name="other_score" if changed_field == "name" else NATIVE_SCORE_NAME,
        score_semantics=(
            "other tool-native score; lower_is_better; not affinity"
            if changed_field == "semantics"
            else NATIVE_SCORE_SEMANTICS
        ),
    )
    with pytest.raises(RuntimeError, match=message):
        _rank_gso_rows([first, second])


def test_rank_one_failure_selects_first_validated_without_renumbering(
    tmp_path: Path,
) -> None:
    sampling = """\
mkdir -p swarm_0
printf '%s\n' \
  '(0,0,0,0,0,0,0) 0 0 0 0 0 3.0' \
  '(0,0,0,0,0,0,0) 0 0 0 0 0 2.0' \
  '(0,0,0,0,0,0,0) 0 0 0 0 0 1.0' > swarm_0/gso_5.out
"""
    setup = _script(tmp_path / "setup", "printf '{}' > setup.json\n")
    sample = _script(tmp_path / "sample", sampling)
    conform = _script(
        tmp_path / "conform", _multi_conformation_script(skip_index=0)
    )
    result = LocalLightDockExecutor(
        setup_executable=setup,
        sampling_executable=sample,
        conformation_executable=conform,
    ).execute(
        _handoff(tmp_path),
        allowed_root=tmp_path,
        output_dir=tmp_path / "output",
        timeout_seconds=10,
        poses_per_case=3,
    )
    assert result.pose_records[0].global_tool_score_rank == 1
    assert result.pose_records[0].generation_status == "failed"
    assert result.pose_records[1].global_tool_score_rank == 2
    assert result.selected_pose == "poses/pose_002.pdb"
    assert result.selected_pose_reason == "first_validated_global_tool_score_rank"
    assert result.warnings == [
        "global_tool_score_rank 1 did not validate; selected the first "
        "validated global_tool_score_rank without renumbering"
    ]


def test_duplicate_pose_hashes_are_grouped_without_deduplication(
    tmp_path: Path,
) -> None:
    sampling = """\
mkdir -p swarm_0
printf '%s\n' \
  '(0,0,0,0,0,0,0) 0 0 0 0 0 2.0' \
  '(0,0,0,0,0,0,0) 0 0 0 0 0 1.0' > swarm_0/gso_5.out
"""
    setup = _script(tmp_path / "setup", "printf '{}' > setup.json\n")
    sample = _script(tmp_path / "sample", sampling)
    conform = _script(
        tmp_path / "conform", _multi_conformation_script(unique=False)
    )
    result = LocalLightDockExecutor(
        setup_executable=setup,
        sampling_executable=sample,
        conformation_executable=conform,
    ).execute(
        _handoff(tmp_path),
        allowed_root=tmp_path,
        output_dir=tmp_path / "output",
        timeout_seconds=10,
        poses_per_case=2,
    )
    assert [row.global_tool_score_rank for row in result.pose_records] == [1, 2]
    assert result.pose_records[0].pose_sha256 == result.pose_records[1].pose_sha256
    assert result.pose_records[0].duplicate_pose_group is not None
    assert (
        result.pose_records[0].duplicate_pose_group
        == result.pose_records[1].duplicate_pose_group
    )
    manifest = json.loads(
        (tmp_path / "output" / "docking_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["pose_count"] == 2
    assert manifest["unique_validated_pose_count"] == 1


@pytest.mark.parametrize(
    ("sampling", "swarms", "message"),
    [
        (
            "mkdir -p swarm_0\nprintf '%s\\n' '(0,0,0,0,0,0,0) 0 0 0 0 0 1.0' > swarm_0/gso_5.out\n",
            2,
            "swarm set mismatch",
        ),
        ("mkdir -p swarm_bad\n", 1, "malformed LightDock swarm"),
        (
            "mkdir real_swarm\nln -s real_swarm swarm_0\n",
            1,
            "not a regular directory",
        ),
        (
            "mkdir -p swarm_0 swarm_00\n",
            1,
            "duplicate LightDock swarm id",
        ),
        (
            "mkdir -p swarm_0\n: > swarm_0/gso_5.out\n",
            1,
            "GSO parse failed",
        ),
        (
            "mkdir -p swarm_0\nprintf '%s\\n' '(0,0,0,0,0,0,0) 0 0 0 0 0 nan' > swarm_0/gso_5.out\n",
            1,
            "GSO parse failed",
        ),
    ],
)
def test_cross_swarm_discovery_fails_closed(
    tmp_path: Path, sampling: str, swarms: int, message: str
) -> None:
    with pytest.raises(RuntimeError, match=message):
        _executor(tmp_path, sampling=sampling).execute(
            _handoff(tmp_path),
            allowed_root=tmp_path,
            output_dir=tmp_path / "output",
            timeout_seconds=10,
            swarms=swarms,
        )


def test_poses_per_case_upper_bound(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="poses_per_case"):
        _executor(tmp_path).execute(
            _handoff(tmp_path),
            allowed_root=tmp_path,
            output_dir=tmp_path / "output",
            timeout_seconds=10,
            poses_per_case=101,
        )


def test_poses_per_case_one_hundred_is_supported(tmp_path: Path) -> None:
    rows = "".join(
        f"printf '%s\\n' '(0,0,0,0,0,0,0) 0 0 0 0 0 {100 - index}.0' >> swarm_0/gso_5.out\n"
        for index in range(100)
    )
    sampling = "mkdir -p swarm_0\n: > swarm_0/gso_5.out\n" + rows
    setup = _script(tmp_path / "setup", "printf '{}' > setup.json\n")
    sample = _script(tmp_path / "sample", sampling)
    conform = _script(tmp_path / "conform", _multi_conformation_script())
    result = LocalLightDockExecutor(
        setup_executable=setup,
        sampling_executable=sample,
        conformation_executable=conform,
    ).execute(
        _handoff(tmp_path),
        allowed_root=tmp_path,
        output_dir=tmp_path / "output",
        timeout_seconds=10,
        poses_per_case=100,
    )
    assert len(result.pose_records) == 100
    assert [row.global_tool_score_rank for row in result.pose_records] == list(
        range(1, 101)
    )
    assert result.selected_pose == "poses/pose_001.pdb"


def test_execution_argv_excludes_reference_and_prediction_confidence(
    tmp_path: Path,
) -> None:
    setup = _script(
        tmp_path / "setup",
        "printf '%s\\n' \"$@\" > command_argv.log\nprintf '{}' > setup.json\n",
    )
    sampling = _script(
        tmp_path / "sample",
        "printf '%s\\n' \"$@\" >> command_argv.log\n"
        "mkdir -p swarm_0\n"
        "printf '%s\\n' '(0,0,0,0,0,0,0) 0 0 0 0 0 1.0' > swarm_0/gso_5.out\n",
    )
    conform = _script(
        tmp_path / "conform",
        "printf '%s\\n' \"$@\" >> command_argv.log\n"
        'cat "$1" "$2" > lightdock_0.pdb\n',
    )
    handoff = _handoff(tmp_path)
    handoff = handoff.model_copy(
        update={
            "antibody_artifact": handoff.antibody_artifact.model_copy(
                update={"native_metrics": {"prediction_confidence": 99.999}}
            )
        }
    )
    result = LocalLightDockExecutor(
        setup_executable=setup,
        sampling_executable=sampling,
        conformation_executable=conform,
    ).execute(
        handoff,
        allowed_root=tmp_path,
        output_dir=tmp_path / "output",
        timeout_seconds=10,
    )
    command_log = (tmp_path / "output" / "work" / "command_argv.log").read_text(
        encoding="utf-8"
    )
    assert "bound" not in command_log.lower()
    assert "confidence" not in command_log.lower()
    assert "99.999" not in command_log
    assert result.pose_records[0].native_score == 1.0


def test_fake_lightdock_nonzero_and_timeout_fail_closed(tmp_path: Path) -> None:
    handoff = _handoff(tmp_path)
    with pytest.raises(RuntimeError, match="exit code 7"):
        _executor(tmp_path, sampling="exit 7\n").execute(handoff, allowed_root=tmp_path, output_dir=tmp_path / "nonzero", timeout_seconds=10)
    with pytest.raises(RuntimeError, match="timed out"):
        _executor(tmp_path, sampling="sleep 2\n").execute(handoff, allowed_root=tmp_path, output_dir=tmp_path / "timeout", timeout_seconds=1)


def test_executor_rejects_symlink_and_path_escape(tmp_path: Path) -> None:
    handoff = _handoff(tmp_path)
    outside = tmp_path.parent / "outside.pdb"; _pdb(outside, {"H": "ACDE", "L": "FGHI"})
    escaped = handoff.model_copy(update={"antibody_artifact": handoff.antibody_artifact.model_copy(update={"pdb_path": "../outside.pdb"})})
    with pytest.raises(ValueError, match="escaped"):
        _executor(tmp_path).execute(escaped, allowed_root=tmp_path, output_dir=tmp_path / "escaped", timeout_seconds=10)
    link = tmp_path / "linked.pdb"; link.symlink_to(tmp_path / "antibody.pdb")
    linked = handoff.model_copy(update={"antibody_artifact": handoff.antibody_artifact.model_copy(update={"pdb_path": "linked.pdb"})})
    with pytest.raises(ValueError, match="unsafe"):
        _executor(tmp_path).execute(linked, allowed_root=tmp_path, output_dir=tmp_path / "linked", timeout_seconds=10)


def test_lightdock_executor_rejects_non_executable_or_directory(tmp_path: Path) -> None:
    directory = tmp_path / "tool"; directory.mkdir()
    with pytest.raises(ValueError, match="executable regular file"):
        LocalLightDockExecutor(setup_executable=directory, sampling_executable=directory, conformation_executable=directory)


def test_lightdock_log_redaction_removes_local_paths_and_tokens() -> None:
    local_path = "/" + "mnt" + "/d/private/run "
    redacted = LocalLightDockExecutor._redact_log(local_path + "sk-" + ("a" * 30))
    assert local_path not in redacted and "sk-" not in redacted

from __future__ import annotations

import json
import platform
from pathlib import Path

import pytest
from pydantic import ValidationError

from labmate.benchmark_local import (
    _strict_pdb_audit,
    _summary_rows,
    compute_reference_metrics,
    execute_benchmark_local,
    load_benchmark_local_project,
)
from labmate.cli import main
from labmate.docking.registry import capability_matrix
from labmate.errors import InputValidationError, LabmateError
from labmate.live_local import _redact_text
from labmate.models import BenchmarkLocalJobSpec


def _atom(
    serial: int,
    chain: str,
    residue: int,
    x: float,
    y: float,
    z: float,
    *,
    name: str = "CA",
    residue_name: str = "ALA",
) -> str:
    element = name[0]
    return (
        f"ATOM  {serial:5d} {name:>4s} {residue_name:>3s} "
        f"{chain}{residue:4d}    {x:8.3f}{y:8.3f}{z:8.3f}"
        f"{1.0:6.2f}{20.0:6.2f}          {element:>2s}"
    )


def _write_pdb(path: Path, coordinates: dict[str, list[tuple[float, float, float]]]) -> Path:
    lines: list[str] = []
    serial = 1
    for chain, points in coordinates.items():
        for residue, (x, y, z) in enumerate(points, start=1):
            lines.append(_atom(serial, chain, residue, x, y, z))
            serial += 1
    path.write_text("\n".join([*lines, "TER", "END", ""]), encoding="utf-8")
    return path


def _payload(tmp_path: Path, *, vhh: bool = False, reference: bool = False) -> dict:
    antibody_mapping = {"H": "H"} if vhh else {"H": "H", "L": "L"}
    payload = {
        "schema_version": "2.2.0",
        "project_name": "CC0-SYNTHETIC-CASE",
        "mode": "benchmark_local",
        "rights_confirmed": True,
        "antibody_pdb": "antibody.pdb",
        "antigen_pdb": "antigen.pdb",
        "antibody_chain_mapping": antibody_mapping,
        "antigen_chain_mapping": {"A": "A"},
        "tools": {
            "lightdock_setup": str(tmp_path / "lightdock3_setup.py"),
            "lightdock_run": str(tmp_path / "lightdock3.py"),
            "lightdock_generate": str(tmp_path / "lgd_generate_conformations.py"),
            "lightdock_cluster": str(tmp_path / "lgd_cluster_bsas.py"),
        },
        "score_name": "synthetic_test_score",
        "score_direction": "higher_is_better",
        "steps": 20,
        "swarms": 4,
        "glowworms": 50,
        "cores": 1,
        "top_poses": 3,
        "random_seed": 42,
        "random_seed_recording": "manifest_only_external_lightdock_cli",
        "output_dir": "runs",
        "source_type": "project_authored_synthetic",
    }
    if reference:
        payload["reference_complex_pdb"] = "reference.pdb"
        payload["reference_chain_mapping"] = {
            **antibody_mapping,
            "A": "A",
        }
    return payload


def _make_inputs(tmp_path: Path, *, vhh: bool = False) -> tuple[Path, Path, Path]:
    antibody = (
        {"H": [(0, 0, 0), (10, 0, 0), (0, 10, 0)]}
        if vhh
        else {"H": [(0, 0, 0), (10, 0, 0)], "L": [(0, 10, 0)]}
    )
    antigen = {"A": [(0, 0, 4), (10, 0, 4)]}
    antibody_path = _write_pdb(tmp_path / "antibody.pdb", antibody)
    antigen_path = _write_pdb(tmp_path / "antigen.pdb", antigen)
    reference_path = _write_pdb(tmp_path / "reference.pdb", {**antibody, **antigen})
    return antibody_path, antigen_path, reference_path


def _write_executable(path: Path, body: str) -> Path:
    path.write_text("#!/usr/bin/env python3\n" + body, encoding="utf-8")
    path.chmod(0o755)
    return path


def _mock_tools(tmp_path: Path, *, setup_exit: int = 0, poses_to_write: int = 3) -> None:
    _write_executable(
        tmp_path / "lightdock3_setup.py",
        (
            "import json,sys\n"
            f"raise SystemExit({setup_exit})\n"
            if setup_exit
            else
            "import json,sys\n"
            "swarms=int(sys.argv[sys.argv.index('-s')+1])\n"
            "json.dump({'swarms':swarms},open('setup.json','w'))\n"
        ),
    )
    _write_executable(
        tmp_path / "lightdock3.py",
        "import json,pathlib,sys\n"
        "if '-v' in sys.argv:\n print('lightdock3 0.9.4'); raise SystemExit(0)\n"
        "setup=json.load(open('setup.json'))\n"
        "steps=int(sys.argv[2])\n"
        "line='(0, 0, 0, 1, 0, 0, 0) 0.25 0 0.75 {}\\n'\n"
        "for swarm in range(setup['swarms']):\n"
        " d=pathlib.Path(f'swarm_{swarm}'); d.mkdir(); "
        "(d/f'gso_{steps}.out').write_text(line.format(10-swarm))\n",
    )
    _write_executable(
        tmp_path / "lgd_generate_conformations.py",
        "import pathlib,sys\n"
        "receptor=pathlib.Path(sys.argv[1]).read_text().splitlines()\n"
        "ligand=pathlib.Path(sys.argv[2]).read_text().splitlines()\n"
        "atoms=[x for x in receptor+ligand if x.startswith('ATOM  ')]\n"
        f"count=min(int(sys.argv[4]),{poses_to_write})\n"
        "for i in range(count):\n"
        " pathlib.Path(f'lightdock_{i}.pdb').write_text('\\n'.join(atoms+['TER','END','']))\n",
    )
    _write_executable(
        tmp_path / "lgd_cluster_bsas.py",
        "import sys\nprint('cluster test double')\n",
    )


@pytest.mark.parametrize("vhh", [False, True])
def test_valid_vh_vl_and_vhh_contracts(tmp_path: Path, vhh: bool) -> None:
    job = BenchmarkLocalJobSpec.model_validate(_payload(tmp_path, vhh=vhh))
    assert set(job.antibody_chain_mapping.values()) == ({"H"} if vhh else {"H", "L"})


def test_rights_not_confirmed_is_rejected(tmp_path: Path) -> None:
    payload = _payload(tmp_path)
    payload["rights_confirmed"] = False
    with pytest.raises(ValidationError, match="权利"):
        BenchmarkLocalJobSpec.model_validate(payload)


@pytest.mark.parametrize("field", ["antibody_pdb", "antigen_pdb", "output_dir"])
def test_url_inputs_are_rejected(tmp_path: Path, field: str) -> None:
    payload = _payload(tmp_path)
    payload[field] = "https://example.invalid/data.pdb"
    with pytest.raises(ValidationError, match="本地路径"):
        BenchmarkLocalJobSpec.model_validate(payload)


def test_chain_overlap_is_rejected(tmp_path: Path) -> None:
    payload = _payload(tmp_path)
    payload["antigen_chain_mapping"] = {"A": "H"}
    with pytest.raises(ValidationError, match="不得重叠"):
        BenchmarkLocalJobSpec.model_validate(payload)


def test_reference_mapping_error_is_rejected(tmp_path: Path) -> None:
    payload = _payload(tmp_path, reference=True)
    payload["reference_chain_mapping"] = {"H": "H", "A": "A"}
    with pytest.raises(ValidationError, match="完全一致"):
        BenchmarkLocalJobSpec.model_validate(payload)


def test_missing_chain_and_missing_ca_fail_closed(tmp_path: Path) -> None:
    path = _write_pdb(tmp_path / "one.pdb", {"H": [(0, 0, 0)]})
    with pytest.raises(InputValidationError, match="缺少所选链"):
        _strict_pdb_audit(path.read_bytes(), selected_chains=["H", "L"], label="antibody")
    no_ca = tmp_path / "no_ca.pdb"
    no_ca.write_text(_atom(1, "H", 1, 0, 0, 0, name="N") + "\nEND\n", encoding="utf-8")
    with pytest.raises(InputValidationError, match="无 CA"):
        _strict_pdb_audit(no_ca.read_bytes(), selected_chains=["H"], label="antibody")


def test_duplicate_atom_residue_record_fails_closed(tmp_path: Path) -> None:
    line = _atom(1, "H", 1, 0, 0, 0)
    data = (line + "\n" + line + "\nEND\n").encode()
    with pytest.raises(InputValidationError, match="重复"):
        _strict_pdb_audit(data, selected_chains=["H"], label="antibody")


def test_multiple_models_and_altloc_fail_closed(tmp_path: Path) -> None:
    line = _atom(1, "H", 1, 0, 0, 0)
    multiple_models = (
        f"MODEL        1\n{line}\nENDMDL\n"
        f"MODEL        2\n{line}\nENDMDL\nEND\n"
    ).encode()
    with pytest.raises(InputValidationError, match="MODEL"):
        _strict_pdb_audit(
            multiple_models, selected_chains=["H"], label="antibody"
        )

    altloc_line = line[:16] + "A" + line[17:]
    with pytest.raises(InputValidationError, match="altloc"):
        _strict_pdb_audit(
            (altloc_line + "\nEND\n").encode(),
            selected_chains=["H"],
            label="antibody",
        )


def test_noncontiguous_duplicate_residue_fails_but_insertion_code_is_preserved(
    tmp_path: Path,
) -> None:
    residue_one_ca = _atom(1, "H", 1, 0, 0, 0)
    residue_two_ca = _atom(2, "H", 2, 1, 0, 0)
    residue_one_n = _atom(3, "H", 1, 0, 1, 0, name="N")
    duplicate = "\n".join(
        [residue_one_ca, residue_two_ca, residue_one_n, "END", ""]
    ).encode()
    with pytest.raises(InputValidationError, match="重复 residue"):
        _strict_pdb_audit(duplicate, selected_chains=["H"], label="antibody")

    inserted = residue_one_ca[:26] + "A" + residue_one_ca[27:]
    parsed = _strict_pdb_audit(
        (inserted + "\nEND\n").encode(),
        selected_chains=["H"],
        label="antibody",
    )
    assert parsed.atoms[0].residue.insertion_code == "A"


def test_bundled_cc0_example_structures_are_strict_and_reference_compatible(
    project_root: Path,
) -> None:
    root = project_root / "examples" / "benchmark_local"
    antibody = _strict_pdb_audit(
        (root / "antibody.pdb").read_bytes(),
        selected_chains=["H", "L"],
        label="antibody",
    )
    antigen = _strict_pdb_audit(
        (root / "antigen.pdb").read_bytes(),
        selected_chains=["A"],
        label="antigen",
    )
    reference = _strict_pdb_audit(
        (root / "reference_complex.pdb").read_bytes(),
        selected_chains=["H", "L", "A"],
        label="reference",
    )
    assert antibody.residue_count == 8
    assert antigen.residue_count == 5
    assert reference.residue_count == 13
    metrics = compute_reference_metrics(
        root / "reference_complex.pdb",
        root / "reference_complex.pdb",
        receptor_chains={"H", "L"},
        ligand_chains={"A"},
    )
    assert metrics["ligand_rmsd"] == pytest.approx(0.0, abs=1e-8)
    assert metrics["interface_rmsd"] == pytest.approx(0.0, abs=1e-8)
    assert metrics["fraction_native_contacts"] == 1.0


def test_known_zero_rmsd_and_perfect_interface_metrics(tmp_path: Path) -> None:
    _, _, reference = _make_inputs(tmp_path, vhh=True)
    metrics = compute_reference_metrics(
        reference,
        reference,
        receptor_chains={"H"},
        ligand_chains={"A"},
    )
    assert metrics["ligand_rmsd"] == pytest.approx(0.0, abs=1e-8)
    assert metrics["interface_rmsd"] == pytest.approx(0.0, abs=1e-8)
    assert metrics["fraction_native_contacts"] == 1.0
    assert metrics["interface_residue_precision"] == 1.0
    assert metrics["interface_residue_recall"] == 1.0
    assert metrics["interface_residue_f1"] == 1.0
    assert metrics["ligand_unmatched_pose_heavy_atoms"] == 0
    assert metrics["ligand_unmatched_reference_heavy_atoms"] == 0
    assert metrics["interface_unmatched_pose_backbone_atoms"] == 0
    assert metrics["interface_unmatched_reference_backbone_atoms"] == 0


def test_receptor_alignment_removes_rigid_rotation_and_translation(
    tmp_path: Path,
) -> None:
    reference_coordinates = {
        "H": [(0, 0, 0), (10, 0, 0), (0, 10, 0)],
        "A": [(0, 0, 4), (10, 0, 4)],
    }

    def transform(point: tuple[float, float, float]) -> tuple[float, float, float]:
        x, y, z = point
        return -y + 7, x - 3, z + 11

    pose_coordinates = {
        chain: [transform(point) for point in points]
        for chain, points in reference_coordinates.items()
    }
    reference = _write_pdb(tmp_path / "reference.pdb", reference_coordinates)
    pose = _write_pdb(tmp_path / "pose.pdb", pose_coordinates)
    metrics = compute_reference_metrics(
        pose, reference, receptor_chains={"H"}, ligand_chains={"A"}
    )
    assert metrics["ligand_rmsd"] == pytest.approx(0.0, abs=1e-6)
    assert metrics["interface_rmsd"] == pytest.approx(0.0, abs=1e-6)
    assert metrics["fraction_native_contacts"] == 1.0


def test_known_fnat_precision_recall_and_f1(tmp_path: Path) -> None:
    receptor = {"H": [(0, 0, 0), (10, 0, 0), (0, 10, 0)]}
    reference = _write_pdb(
        tmp_path / "reference.pdb",
        {**receptor, "A": [(0, 0, 4), (10, 0, 4)]},
    )
    pose = _write_pdb(
        tmp_path / "pose.pdb",
        {**receptor, "A": [(0, 0, 4), (0, 10, 4)]},
    )
    metrics = compute_reference_metrics(
        pose, reference, receptor_chains={"H"}, ligand_chains={"A"}
    )
    assert metrics["fraction_native_contacts"] == 0.5
    assert metrics["interface_residue_precision"] == 0.75
    assert metrics["interface_residue_recall"] == 0.75
    assert metrics["interface_residue_f1"] == 0.75


def test_degenerate_receptor_alignment_fails_closed(tmp_path: Path) -> None:
    coordinates = {
        "H": [(0, 0, 0), (5, 0, 0), (10, 0, 0)],
        "A": [(0, 0, 4)],
    }
    reference = _write_pdb(tmp_path / "reference.pdb", coordinates)
    pose = _write_pdb(tmp_path / "pose.pdb", coordinates)
    with pytest.raises(LabmateError, match="退化"):
        compute_reference_metrics(
            pose, reference, receptor_chains={"H"}, ligand_chains={"A"}
        )


def test_top_k_summary_uses_ranked_prefix_not_global_best() -> None:
    metrics = [
        {
            "ligand_rmsd": rank,
            "interface_rmsd": rank,
            "fraction_native_contacts": 1 / rank,
            "interface_residue_f1": 1 / rank,
        }
        for rank in (5, 4, 3, 2, 1, 0.1)
    ]
    summaries = _summary_rows(metrics)
    assert summaries[0]["best_ligand_rmsd"] == 5
    assert summaries[1]["best_ligand_rmsd"] == 1
    assert summaries[2]["best_ligand_rmsd"] == 0.1


def test_missing_executable_is_rejected(tmp_path: Path) -> None:
    antibody, antigen, _ = _make_inputs(tmp_path)
    job = BenchmarkLocalJobSpec.model_validate(_payload(tmp_path))
    with pytest.raises(LabmateError, match="缺少 executable"):
        execute_benchmark_local(
            job=job,
            antibody_path=antibody,
            antigen_path=antigen,
            reference_path=None,
            output_root=tmp_path / "runs",
        )


def test_nonzero_version_probe_is_rejected_even_if_version_is_printed(
    tmp_path: Path,
) -> None:
    antibody, antigen, _ = _make_inputs(tmp_path)
    for name in (
        "lightdock3_setup.py",
        "lgd_generate_conformations.py",
        "lgd_cluster_bsas.py",
    ):
        _write_executable(tmp_path / name, "raise SystemExit(0)\n")
    _write_executable(
        tmp_path / "lightdock3.py",
        "print('lightdock3 0.9.4')\nraise SystemExit(7)\n",
    )
    job = BenchmarkLocalJobSpec.model_validate(_payload(tmp_path))
    with pytest.raises(LabmateError, match="无法探测 LightDock 版本"):
        execute_benchmark_local(
            job=job,
            antibody_path=antibody,
            antigen_path=antigen,
            reference_path=None,
            output_root=tmp_path / "runs",
        )


def test_lightdock_nonzero_exit_fails_case(tmp_path: Path) -> None:
    antibody, antigen, _ = _make_inputs(tmp_path)
    _mock_tools(tmp_path, setup_exit=7)
    job = BenchmarkLocalJobSpec.model_validate(_payload(tmp_path))
    with pytest.raises(LabmateError, match="exit 7"):
        execute_benchmark_local(
            job=job,
            antibody_path=antibody,
            antigen_path=antigen,
            reference_path=None,
            output_root=tmp_path / "runs",
        )


def test_score_pose_count_mismatch_fails_case(tmp_path: Path) -> None:
    antibody, antigen, _ = _make_inputs(tmp_path)
    _mock_tools(tmp_path, poses_to_write=2)
    job = BenchmarkLocalJobSpec.model_validate(_payload(tmp_path))
    with pytest.raises(LabmateError, match="score/pose"):
        execute_benchmark_local(
            job=job,
            antibody_path=antibody,
            antigen_path=antigen,
            reference_path=None,
            output_root=tmp_path / "runs",
        )


def test_synthetic_smoke_outputs_are_complete_private_and_unverified(tmp_path: Path) -> None:
    antibody, antigen, reference = _make_inputs(tmp_path)
    _mock_tools(tmp_path)
    job = BenchmarkLocalJobSpec.model_validate(_payload(tmp_path, reference=True))
    result = execute_benchmark_local(
        job=job,
        antibody_path=antibody,
        antigen_path=antigen,
        reference_path=reference,
        output_root=tmp_path / "runs",
    )
    run_dir = Path(result.run_dir)
    expected = {
        "job.json", "manifest.json", "manifest.sha256", "poses.csv",
        "interface_residues.csv", "benchmark_metrics.csv", "case_summary.csv",
        "report.html",
    }
    assert expected.issubset({path.name for path in run_dir.iterdir()})
    assert len(list((run_dir / "top_poses").glob("pose_*.pdb"))) == 3
    assert Path(result.zip_path).is_file()
    manifest = json.loads((run_dir / "manifest.json").read_text())
    assert manifest["status"] == "implemented_unverified"
    assert manifest["network_used"] is False
    assert manifest["colabfold_invoked"] is False
    assert manifest["verification"]["real_external_lightdock_smoke_completed"] is True
    assert manifest["verification"]["scientific_validation_completed"] is False
    assert (
        manifest["verification"]["validation_record"]
        == "BENCHMARK_LOCAL_VALIDATION.md"
    )
    assert manifest["pose_score_mapping"]["filename_sorting_used"] is False
    roles = {
        artifact["path"]: artifact["role"] for artifact in manifest["artifacts"]
    }
    assert roles["poses.csv"] == "benchmark_local_pose_ranking"
    assert roles["benchmark_metrics.csv"] == "benchmark_local_reference_metrics"
    assert roles["case_summary.csv"] == "benchmark_local_top_k_summary"
    assert roles["job.json"] == "benchmark_local_configuration"
    assert roles["top_poses/pose_001.pdb"] == "benchmark_local_structure_artifact"
    assert roles["work/selected_top_poses.gso"] == "benchmark_local_docking_artifact"
    assert all(
        {"command", "stdout", "stderr", "return_code", "elapsed_seconds"}
        <= set(record)
        for record in manifest["tools"]["lightdock"]["commands"]
    )
    report = (run_dir / "report.html").read_text()
    for label in (
        "BENCHMARK LOCAL",
        "COMPUTATIONAL DOCKING BENCHMARK",
        "NOT BINDING OR AFFINITY EVIDENCE",
    ):
        assert label in report
    forbidden = str(tmp_path)
    for path in run_dir.rglob("*"):
        if path.is_file() and path.suffix in {".json", ".csv", ".html", ".log", ".txt"}:
            assert forbidden not in path.read_text(errors="replace")


def test_redaction_removes_hostname_environment_assignments_and_absolute_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOSTNAME", "benchmark-audit-host")
    text = (
        f"{platform.node()} benchmark-audit-host\n"
        "PATH=/opt/lightdock/bin:/usr/bin\n"
        "output=/opt/lightdock/results/pose.pdb"
    )
    redacted = _redact_text(text, cwd=tmp_path)
    assert platform.node() not in redacted
    assert "benchmark-audit-host" not in redacted
    assert "/opt/lightdock" not in redacted
    assert "/usr/bin" not in redacted
    assert "PATH=" not in redacted


def test_redaction_does_not_corrupt_html_attributes_or_css(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    monkeypatch.setenv("DISPLAY", ":0")
    html = '<html lang="en"><style>.badge{display:inline-block}</style></html>'
    assert _redact_text(html, cwd=tmp_path) == html


def test_benchmark_local_cli_runs_synthetic_contract(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _make_inputs(tmp_path)
    _mock_tools(tmp_path)
    payload = _payload(tmp_path)
    project = tmp_path / "project.json"
    project.write_text(json.dumps(payload), encoding="utf-8")
    exit_code = main(
        [
            "run",
            str(project),
            "--mode",
            "benchmark_local",
            "--output",
            str(tmp_path / "cli-runs"),
        ]
    )
    captured = capsys.readouterr()
    assert exit_code == 0, captured.err
    result = json.loads(captured.out)
    assert result["mode"] == "BENCHMARK LOCAL (IMPLEMENTED UNVERIFIED)"
    assert Path(result["zip"]).is_file()


def test_project_loader_rejects_url_without_network(tmp_path: Path) -> None:
    payload = _payload(tmp_path)
    payload["antibody_pdb"] = "https://example.invalid/antibody.pdb"
    project = tmp_path / "project.json"
    project.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises((InputValidationError, ValidationError)):
        load_benchmark_local_project(project)


def test_capability_is_implemented_unverified_and_legacy_fields_remain() -> None:
    capabilities = capability_matrix()
    assert capabilities["benchmark_local"]["status"] == "implemented_unverified"
    assert capabilities["replay"]["status"] == "replay_only"
    assert capabilities["live_local"]["status"] == "verified_live"
    assert capabilities["live_remote"]["status"] == "unavailable"
    assert "lightdock_replay_parser" in capabilities
    assert "lightdock_live_runner" in capabilities

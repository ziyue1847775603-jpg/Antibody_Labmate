"""Command-line entry point for Replay and explicitly marked Live Local runs."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from pydantic import ValidationError

from labmate import __version__
from labmate.backends.registry import PREDICTION_BACKEND_NAMES, get_backend
from labmate.backends.replay import ReplayBackend
from labmate.backends.local import LiveLocalBackend
from labmate.backends.benchmark import BenchmarkLocalBackend
from labmate.benchmark_local import load_benchmark_local_project
from labmate.docking.registry import capability_matrix
from labmate.docking.lightdock import LocalLightDockExecutor
from labmate.design import DesignInput, RFantibodyBackend
from labmate.design.artifact import sha256
from labmate.benchmarking import load_manifest
from labmate.prediction_artifact import DockingInput
from labmate.errors import LabmateError
from labmate.workflow import load_project
from labmate.live_local import load_live_local_project


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def fixture_path(fixture_id: str) -> Path:
    if not re.fullmatch(r"demo_[0-9]{3}", fixture_id):
        raise LabmateError("fixture ID 格式无效")
    path = (project_root() / "fixtures" / fixture_id).resolve()
    try:
        path.relative_to((project_root() / "fixtures").resolve())
    except ValueError as exc:
        raise LabmateError("fixture 路径越界") from exc
    return path


def chain_sequence_file(path: Path, *, label: str) -> str:
    """Read one local raw chain sequence without placing it in process argv."""

    if path.is_symlink() or not path.is_file():
        raise LabmateError(f"{label} sequence file must be a regular file: {path}")
    try:
        sequence = "".join(path.read_text(encoding="utf-8").split())
    except OSError as exc:
        raise LabmateError(f"unable to read {label} sequence file") from exc
    if not sequence:
        raise LabmateError(f"{label} sequence file is empty")
    return sequence


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="labmate", description="Antibody Labmate")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subcommands = parser.add_subparsers(dest="command", required=True)

    run = subcommands.add_parser("run", help="run Replay or the user-installed Live Local pipeline")
    run.add_argument("project", type=Path, help="JSON-compatible project.yaml")
    run.add_argument(
        "--mode",
        choices=["replay", "live_local", "benchmark_local"],
        default="replay",
    )
    run.add_argument("--fixture", default="demo_001")
    run.add_argument("--output", type=Path, default=Path("runs"))
    run.add_argument(
        "--prediction-backend",
        choices=PREDICTION_BACKEND_NAMES,
        default=None,
        help="structure prediction backend (default: replay for Replay mode)",
    )
    run.add_argument(
        "--tool-execution-provider",
        choices=["host", "docker_compose"],
        default="host",
        help="how Live Local external tools run (default: host; docker_compose is explicit)",
    )
    run.add_argument(
        "--docker-compose-file",
        type=Path,
        default=Path("docker-compose.live-local.yml"),
        help="compose file for --tool-execution-provider docker_compose",
    )
    run.add_argument(
        "--docker-work-root",
        type=Path,
        help="host work dir for --tool-execution-provider docker_compose",
    )
    run.add_argument(
        "--docker-data-root",
        type=Path,
        help="host ColabFold model-data dir for docker_compose (read-only mount)",
    )
    run.add_argument(
        "--docker-cache-root",
        type=Path,
        help="host JAX cache dir for docker_compose (read-write mount)",
    )

    predict = subcommands.add_parser(
        "predict",
        help="run one local structure-prediction backend without docking",
    )
    predict.add_argument(
        "--prediction-backend",
        choices=PREDICTION_BACKEND_NAMES,
        default="replay",
    )

    dock = subcommands.add_parser(
        "dock", help="run a local docking executable from a validated docking input",
    )
    dock.add_argument("--docking-input", required=True, type=Path)
    dock.add_argument("--output", required=True, type=Path)
    dock.add_argument("--docking-backend", choices=["lightdock"], default="lightdock")
    dock.add_argument("--lightdock-setup-executable", required=True, type=Path)
    dock.add_argument("--lightdock-sampling-executable", required=True, type=Path)
    dock.add_argument("--lightdock-conformation-executable", required=True, type=Path)
    dock.add_argument("--swarms", type=int, default=1)
    dock.add_argument("--glowworms", type=int, default=5)
    dock.add_argument("--gso-steps", type=int, default=5)
    dock.add_argument("--seed", type=int, default=0)
    dock.add_argument("--timeout-seconds", type=int, default=1800)
    dock.add_argument(
        "--lightdock-cores",
        type=int,
        default=1,
        help="explicit LightDock --cores value; execution control only (default: 1)",
    )

    design = subcommands.add_parser(
        "design", help="run one local RFantibody VHH candidate-generation stage; no affinity prediction",
    )
    design.add_argument("--design-backend", choices=["rfantibody"], default="rfantibody")
    design.add_argument("--target-pdb", required=True, type=Path)
    design.add_argument("--target-chains", required=True, help="explicit antigen PDB chain IDs, comma-separated")
    design.add_argument("--hotspots", required=True, help="explicit antigen hotspots, e.g. C:200,C:169")
    design.add_argument("--antibody-format", choices=["vhh"], default="vhh")
    design.add_argument("--candidate-count", type=int, default=1)
    design.add_argument("--seed", type=int, default=0)
    design.add_argument("--output", required=True, type=Path)
    design.add_argument("--rfantibody-python", required=True, type=Path)
    design.add_argument("--rfantibody-root", required=True, type=Path)
    design.add_argument("--resume-backbone", type=Path, help="verified full H/T RFdiffusion intermediate; resumes at official ProteinMPNN")
    design.add_argument("--timeout-seconds", type=int, default=3600)
    dock.add_argument(
        "--poses-per-case",
        type=int,
        default=1,
        help="cross-swarm native-score-ordered GSO rows to retain (1..100)",
    )

    benchmark = subcommands.add_parser(
        "benchmark", help="validate public docking benchmark metadata; local-only"
    )
    benchmark_commands = benchmark.add_subparsers(
        dest="benchmark_command", required=True
    )
    benchmark_validate = benchmark_commands.add_parser(
        "validate", help="validate hashes and bound/unbound isolation; does not run docking"
    )
    benchmark_validate.add_argument("--manifest", required=True, type=Path)
    heavy_input = predict.add_mutually_exclusive_group(required=True)
    heavy_input.add_argument("--heavy-chain", help="complete heavy variable-domain sequence required")
    heavy_input.add_argument("--heavy-chain-file", type=Path)
    light_input = predict.add_mutually_exclusive_group()
    light_input.add_argument("--light-chain", help="complete light variable-domain sequence required")
    light_input.add_argument("--light-chain-file", type=Path)
    predict.add_argument("--antigen-pdb", type=Path)
    predict.add_argument(
        "--output",
        type=Path,
        default=Path("runs") / "predictions",
    )
    predict.add_argument("--fixture", default="demo_001")
    predict.add_argument(
        "--colabfold-executable",
        default="colabfold_batch",
    )
    predict.add_argument("--colabfold-model-data", type=Path)
    predict.add_argument(
        "--igfold-python",
        type=Path,
        help=(
            "explicit local Python interpreter containing IgFold; only valid "
            "with --prediction-backend igfold"
        ),
    )

    subcommands.add_parser("capabilities", help="print truthful capability states")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "capabilities":
            print(json.dumps(capability_matrix(), ensure_ascii=False, indent=2))
            return 0
        if args.command == "predict":
            backend_options: dict[str, object] = {}
            if (
                args.igfold_python is not None
                and args.prediction_backend != "igfold"
            ):
                raise LabmateError(
                    "--igfold-python is only valid with --prediction-backend igfold"
                )
            if args.prediction_backend == "replay":
                backend_options["fixture_root"] = fixture_path(args.fixture)
            elif args.prediction_backend == "colabfold":
                if args.igfold_python is not None:
                    raise LabmateError(
                        "--igfold-python is only valid with --prediction-backend igfold"
                    )
                backend_options["executable"] = args.colabfold_executable
                backend_options["model_data_dir"] = args.colabfold_model_data
            elif args.prediction_backend == "igfold":
                if args.colabfold_model_data is not None or (
                    args.colabfold_executable != "colabfold_batch"
                ):
                    raise LabmateError(
                        "ColabFold options are not valid with --prediction-backend igfold"
                    )
                if args.igfold_python is not None:
                    backend_options["igfold_python"] = args.igfold_python
            backend = get_backend(args.prediction_backend, **backend_options)
            antigen_path = (
                args.antigen_pdb.resolve()
                if args.antigen_pdb is not None
                else None
            )
            if antigen_path is not None and not antigen_path.is_file():
                raise LabmateError(
                    f"antigen PDB does not exist: {args.antigen_pdb}"
                )
            heavy_chain = (
                args.heavy_chain
                if args.heavy_chain is not None
                else chain_sequence_file(args.heavy_chain_file, label="heavy_chain")
            )
            light_chain = (
                args.light_chain
                if args.light_chain is not None
                else (
                    chain_sequence_file(args.light_chain_file, label="light_chain")
                    if args.light_chain_file is not None
                    else None
                )
            )
            prediction = backend.predict(
                heavy_chain=heavy_chain,
                light_chain=light_chain,
                antigen_pdb=antigen_path,
                output_dir=(
                    None
                    if args.prediction_backend == "replay"
                    else args.output
                ),
            )
            print(
                json.dumps(
                    prediction.model_dump(mode="json"),
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0 if prediction.status == "succeeded" else 3
        if args.command == "dock":
            input_path = args.docking_input.resolve()
            if input_path.is_symlink() or not input_path.is_file():
                raise LabmateError("--docking-input must be a regular JSON file")
            try:
                handoff = DockingInput.model_validate_json(input_path.read_text(encoding="utf-8"))
            except (OSError, ValueError, ValidationError) as exc:
                raise LabmateError("invalid docking input JSON") from exc
            if handoff.schema_version != 1 or handoff.docking_backend != args.docking_backend:
                raise LabmateError("docking input schema/backend is not supported")
            executor = LocalLightDockExecutor(
                setup_executable=args.lightdock_setup_executable,
                sampling_executable=args.lightdock_sampling_executable,
                conformation_executable=args.lightdock_conformation_executable,
            )
            result = executor.execute(
                handoff,
                allowed_root=project_root(),
                output_dir=args.output,
                swarms=args.swarms,
                glowworms=args.glowworms,
                steps=args.gso_steps,
                seed=args.seed,
                timeout_seconds=args.timeout_seconds,
                poses_per_case=args.poses_per_case,
                cores=args.lightdock_cores,
            )
            print(json.dumps({"status": result.status, "docking_backend": result.docking_backend, "selected_pose": result.selected_pose, "native_scores": result.native_scores}, ensure_ascii=False, indent=2))
            return 0
        if args.command == "design":
            target = args.target_pdb.resolve()
            root = project_root()
            try:
                relative_target = target.relative_to(root.resolve()).as_posix()
            except ValueError as exc:
                raise LabmateError("--target-pdb must be inside the local project root") from exc
            design_input = DesignInput(
                target_pdb=relative_target,
                target_sha256=sha256(target),
                target_chains=[item.strip() for item in args.target_chains.split(",") if item.strip()],
                hotspot_residues=[item.strip() for item in args.hotspots.split(",") if item.strip()],
                antibody_format=args.antibody_format,
                candidate_count=args.candidate_count,
                seed=args.seed,
                parameters={"design_loops": "official_vhh_default", "deterministic": True},
                resume_backbone_pdb=(args.resume_backbone.resolve().relative_to(root.resolve()).as_posix() if args.resume_backbone is not None else None),
                resume_backbone_sha256=(sha256(args.resume_backbone.resolve()) if args.resume_backbone is not None else None),
            )
            backend = RFantibodyBackend(
                python=args.rfantibody_python,
                root=args.rfantibody_root,
                timeout_seconds=args.timeout_seconds,
            )
            artifact = backend.execute(design_input, allowed_root=root, output_dir=args.output)
            (args.output / "design_artifact.json").write_text(
                artifact.model_dump_json(indent=2) + "\n", encoding="utf-8"
            )
            print(json.dumps({"status": artifact.status, "backend": artifact.backend, "candidate_count": len(artifact.candidates), "generation_order_is_ranking": False}, ensure_ascii=False, indent=2))
            return 0 if artifact.status == "success" and artifact.prediction_ready else 2
        if args.command == "benchmark":
            manifest = load_manifest(args.manifest)
            print(
                json.dumps(
                    {
                        "status": "validated",
                        "dataset_name": manifest.dataset_name,
                        "dataset_version": manifest.dataset_version,
                        "case_count": len(manifest.cases),
                        "scientific_benchmark_run": False,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        if args.mode == "replay":
            prediction_backend_name = args.prediction_backend or "replay"
            if prediction_backend_name != "replay":
                raise LabmateError(
                    "Replay mode requires --prediction-backend replay; "
                    "use 'labmate predict' for local prediction engines"
                )
            job, antigen_bytes = load_project(args.project)
            if job.fixture_id != args.fixture:
                raise LabmateError("project fixture_id 与 --fixture 不一致")
            prediction_backend = get_backend(
                prediction_backend_name,
                fixture_root=fixture_path(args.fixture),
            )
            if not isinstance(prediction_backend, ReplayBackend):
                raise LabmateError("Replay prediction backend type mismatch")
            backend = ReplayBackend(
                fixture_path(args.fixture),
                prediction_backend=prediction_backend,
            )
            result = backend.submit(job, antigen_bytes, args.output)
            mode_label = "REPLAY"
        elif args.mode == "live_local":
            if args.prediction_backend not in (None, "colabfold"):
                raise LabmateError(
                    "Live Local currently requires the ColabFold prediction stage"
                )
            job, candidate_fasta, regions_file, antigen_bytes = load_live_local_project(args.project)
            colabfold_executor = None
            lightdock_executor = None
            provider = "host"
            if args.tool_execution_provider == "docker_compose":
                if args.docker_work_root is None or args.docker_data_root is None or args.docker_cache_root is None:
                    raise LabmateError(
                        "docker_compose provider requires --docker-work-root, "
                        "--docker-data-root, and --docker-cache-root"
                    )
                from labmate.backends.live_local_docker import DockerComposeExecutors
                executors = DockerComposeExecutors(
                    compose_file=str(args.docker_compose_file.resolve()),
                    docker_work_root=args.docker_work_root,
                    colabfold_data_root=args.docker_data_root,
                    colabfold_cache_root=args.docker_cache_root,
                )
                # Preflight: probe both container versions before running.
                container_versions = executors.probe_versions()
                colabfold_executor = executors.colabfold_executor
                lightdock_executor = executors.lightdock_executor
                provider = "docker_compose"
            backend = LiveLocalBackend()
            result = backend.submit(
                job,
                candidate_fasta=candidate_fasta,
                regions_file=regions_file,
                antigen_bytes=antigen_bytes,
                output_root=args.output,
                colabfold_executor=colabfold_executor,
                lightdock_executor=lightdock_executor,
                tool_execution_provider=provider,
                container_versions=container_versions,
            )
            mode_label = "LIVE LOCAL (VERIFIED LIVE)"
        else:
            if args.prediction_backend is not None:
                raise LabmateError(
                    "Benchmark Local accepts prepared PDB structures and does not "
                    "run a structure-prediction backend"
                )
            (
                job,
                antibody_path,
                antigen_path,
                reference_path,
                configured_output,
            ) = load_benchmark_local_project(args.project)
            backend = BenchmarkLocalBackend()
            result = backend.submit(
                job,
                antibody_path=antibody_path,
                antigen_path=antigen_path,
                reference_path=reference_path,
                output_root=(
                    args.output
                    if args.output != Path("runs")
                    else configured_output
                ),
            )
            mode_label = "BENCHMARK LOCAL (IMPLEMENTED UNVERIFIED)"
        print(
            json.dumps(
                {
                    "mode": mode_label,
                    "run_id": result.run_id,
                    "run_dir": result.run_dir,
                    "report": result.report_path,
                    "manifest": result.manifest_path,
                    "zip": result.zip_path,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    except (LabmateError, ValidationError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

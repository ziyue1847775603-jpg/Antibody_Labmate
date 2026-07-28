"""Command-line entry point for Replay and explicitly marked Live Local runs."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from pydantic import ValidationError

from labmate import __version__
from labmate.backends.replay import ReplayBackend
from labmate.backends.local import LiveLocalBackend
from labmate.backends.benchmark import BenchmarkLocalBackend
from labmate.benchmark_local import load_benchmark_local_project
from labmate.docking.registry import capability_matrix
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

    subcommands.add_parser("capabilities", help="print truthful capability states")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "capabilities":
            print(json.dumps(capability_matrix(), ensure_ascii=False, indent=2))
            return 0
        if args.mode == "replay":
            job, antigen_bytes = load_project(args.project)
            if job.fixture_id != args.fixture:
                raise LabmateError("project fixture_id 与 --fixture 不一致")
            backend = ReplayBackend(fixture_path(args.fixture))
            result = backend.submit(job, antigen_bytes, args.output)
            mode_label = "REPLAY"
        elif args.mode == "live_local":
            job, candidate_fasta, regions_file, antigen_bytes = load_live_local_project(args.project)
            backend = LiveLocalBackend()
            result = backend.submit(job, candidate_fasta=candidate_fasta, regions_file=regions_file, antigen_bytes=antigen_bytes, output_root=args.output)
            mode_label = "LIVE LOCAL (VERIFIED LIVE)"
        else:
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
    except (LabmateError, ValidationError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

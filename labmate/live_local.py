"""Phase 2a local execution adapter.

This module never downloads tools, sends credentials, or calls a remote worker.
It executes user-installed command line tools with argument lists (not a shell),
captures their stdout/stderr, and preserves every input/output in the run folder.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import platform
import re
import shutil
import subprocess
import time
from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from typing import Any

from labmate import __version__
from labmate.analysis.interface import analyze_interfaces
from labmate.analysis.ranking import build_candidate_metrics, rank_candidates
from labmate.config import DEFAULT_INTERFACE_CONFIG, SCIENTIFIC_LIMITATION
from labmate.docking.lightdock import ParsedDockingPose
from labmate.errors import InputValidationError, LabmateError
from labmate.models import Capability, CapabilityStatus, ExecutionKind, LiveLocalJobSpec, RunResult
from labmate.provenance import safe_relative_path, sha256_file
from labmate.reporting.builder import build_live_report
from labmate.state import LIVE_LOCAL_STAGES, StageStateMachine
from labmate.validators.antigen import THREE_TO_ONE, parse_antigen_pdb, parse_complex_pdb
from labmate.validators.cdr import STANDARD_AMINO_ACIDS
from labmate.workflow import (
    _collect_artifacts,
    _hash_map,
    _parse_fasta,
    _read_csv,
    _run_id,
    _safe_zip,
    _utc_iso,
    _write_json,
)


def _resolve_input(project_dir: Path, relative: str, label: str) -> Path:
    path = (project_dir / safe_relative_path(relative)).resolve()
    try:
        path.relative_to(project_dir.resolve())
    except ValueError as exc:
        raise InputValidationError(f"{label} 路径越界") from exc
    if not path.is_file():
        raise InputValidationError(f"{label} 不存在: {relative}")
    return path


def load_live_local_project(project_path: Path) -> tuple[LiveLocalJobSpec, Path, Path, bytes]:
    project_path = project_path.resolve()
    try:
        data = json.loads(project_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InputValidationError("Live Local project.yaml 必须是 JSON-compatible YAML") from exc
    job = LiveLocalJobSpec.model_validate(data)
    root = project_path.parent
    return (
        job,
        _resolve_input(root, job.candidate_fasta, "candidate FASTA"),
        _resolve_input(root, job.candidate_regions_file, "candidate regions CSV"),
        _resolve_input(root, job.antigen.file, "antigen PDB").read_bytes(),
    )


def _command_path(command: str) -> str | None:
    supplied = Path(command).expanduser()
    if supplied.parent != Path("."):
        return str(supplied) if supplied.is_file() and os.access(supplied, os.X_OK) else None
    return shutil.which(command)


def _argument_values(arguments: list[str], option: str) -> list[str]:
    values: list[str] = []
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument == option:
            if index + 1 >= len(arguments):
                raise InputValidationError(f"{option} 缺少参数值")
            values.append(arguments[index + 1])
            index += 2
            continue
        prefix = option + "="
        if argument.startswith(prefix):
            values.append(argument[len(prefix) :])
        index += 1
    return values


def _validate_preinstalled_colabfold_data(arguments: list[str]) -> Path:
    values = _argument_values(arguments, "--data")
    if len(values) != 1:
        raise InputValidationError("ColabFold 必须且只能指定一次 --data")
    data_root = Path(values[0]).expanduser()
    params_root = data_root / "params"
    expected = [
        params_root / f"params_model_{index}_multimer_v3.npz"
        for index in range(1, 6)
    ]
    missing = [path.name for path in expected if not path.is_file()]
    if missing:
        raise InputValidationError(
            "preinstalled_only 策略拒绝运行：ColabFold multimer_v3 本地权重不完整"
        )
    return data_root


def _probe_version(command: list[str], pattern: str) -> str:
    try:
        completed = subprocess.run(
            command,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
            timeout=30,
            encoding="utf-8",
            errors="replace",
        )
    except (OSError, subprocess.TimeoutExpired):
        return "not-probed"
    if completed.returncode != 0:
        return "not-probed"
    match = re.search(pattern, completed.stdout or "", flags=re.IGNORECASE)
    return match.group(1) if match else "not-probed"


def _colabfold_version(executable: str) -> str:
    python = Path(executable).parent / "python"
    if not python.is_file():
        return "not-probed"
    return _probe_version(
        [
            str(python),
            "-c",
            "from importlib.metadata import version; print(version('colabfold'))",
        ],
        r"\b([0-9]+\.[0-9]+(?:\.[0-9]+)?)\b",
    )


def _lightdock_version(executable: str) -> str:
    return _probe_version(
        [executable, "-v"],
        r"\blightdock3(?:_setup)?\s+([0-9]+\.[0-9]+(?:\.[0-9]+)?)\b",
    )


def preflight_live_local(job: LiveLocalJobSpec) -> dict[str, Capability]:
    commands = {
        "colabfold": job.tools.colabfold_batch,
        "lightdock_setup": job.tools.lightdock_setup,
        "lightdock_run": job.tools.lightdock_run,
        "lightdock_generate": job.tools.lightdock_generate,
    }
    located_commands = {name: _command_path(command) for name, command in commands.items()}
    colabfold_version = (
        _colabfold_version(located_commands["colabfold"])
        if located_commands["colabfold"]
        else "not-probed"
    )
    lightdock_version = (
        _lightdock_version(located_commands["lightdock_run"])
        if located_commands["lightdock_run"]
        else "not-probed"
    )
    result: dict[str, Capability] = {}
    for name, command in commands.items():
        located = located_commands[name]
        version = colabfold_version if name == "colabfold" else lightdock_version
        is_lightdock = name.startswith("lightdock")
        result[name] = Capability(
            name=name,
            status=CapabilityStatus.AVAILABLE_UNVERIFIED if located else CapabilityStatus.UNAVAILABLE,
            enabled=located is not None,
            provider="local executable",
            version=version,
            license_status=(
                "GPL-3.0 external installation; not bundled"
                if is_lightdock
                else "external ColabFold installation; not bundled"
            ),
            reason=(
                "Found local executable and probed its installed package version."
                if located and version != "not-probed"
                else (
                    "Found local executable; version probe was inconclusive."
                    if located
                    else f"Executable not found: {Path(command).name}"
                )
            ),
        )
    return result


_WINDOWS_ABSOLUTE = re.compile(r"(?i)(?<![A-Za-z0-9])[A-Z]:[\\/][^\s\"'<>]+")
_POSIX_LOCAL_ABSOLUTE = re.compile(
    r"(?<![A-Za-z0-9<:/])/(?:[A-Za-z0-9._~+-]+/)+[A-Za-z0-9._~+-]+"
)
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(token|api[_-]?key|password|secret|authorization|credential)"
    r"\s*([=:])\s*[^\s,;]+"
)
_TOKEN_SHAPES = re.compile(
    r"(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|"
    r"xox[baprs]-[A-Za-z0-9-]{20,}|AKIA[0-9A-Z]{16})"
)
_ENVIRONMENT_VARIABLE_REFERENCE = re.compile(
    r"\b[A-Z][A-Z0-9_]{2,}\b"
    r"(?=(?:\s+shell)?\s+environment variable\b)"
)
def _redact_text(text: str, *, cwd: Path) -> str:
    sensitive: set[str] = {
        str(cwd.resolve()),
        str(Path.home()),
        str(cwd.resolve()).replace("\\", "/"),
        str(Path.home()).replace("\\", "/"),
    }
    for key in ("USERNAME", "USER", "LOGNAME", "HOSTNAME", "COMPUTERNAME"):
        value = os.environ.get(key, "")
        if len(value) >= 3:
            sensitive.add(value)
    hostname = platform.node()
    if len(hostname) >= 3:
        sensitive.add(hostname)
    for key, value in os.environ.items():
        if (
            re.search(r"(?i)(token|key|secret|password|credential|authorization)", key)
            and len(value) >= 4
        ):
            sensitive.add(value)
    redacted = text
    for value in sorted(sensitive, key=len, reverse=True):
        redacted = redacted.replace(value, "<redacted>")
    redacted = _WINDOWS_ABSOLUTE.sub("<local-path>", redacted)
    redacted = _POSIX_LOCAL_ABSOLUTE.sub("<local-path>", redacted)
    redacted = _SECRET_ASSIGNMENT.sub(r"\1\2<redacted>", redacted)
    redacted = _TOKEN_SHAPES.sub("<redacted-token>", redacted)
    for key in sorted(os.environ, key=len, reverse=True):
        redacted = re.sub(
            rf"(?im)^\s*(?:export\s+)?{re.escape(key)}\s*[=:]\s*[^\r\n;]+$",
            "<environment-variable>=<redacted>",
            redacted,
        )
    redacted = _ENVIRONMENT_VARIABLE_REFERENCE.sub(
        "<environment-variable>", redacted
    )
    return redacted


def _run(
    command: list[str],
    *,
    cwd: Path,
    log_path: Path,
    command_records: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run a user-configured executable safely and append reproducible logs."""
    safe_command = [
        Path(command[0]).name,
        *[_redact_text(argument, cwd=cwd) for argument in command[1:]],
    ]
    display = " ".join(safe_command)
    started = time.perf_counter()
    completed = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        encoding="utf-8",
        errors="replace",
    )
    elapsed = round(time.perf_counter() - started, 6)
    stdout = _redact_text(completed.stdout or "", cwd=cwd)
    stderr = _redact_text(completed.stderr or "", cwd=cwd)
    with log_path.open("a", encoding="utf-8") as log:
        log.write("$ " + display + "\n")
        log.write("[stdout]\n" + stdout)
        log.write("[stderr]\n" + stderr)
        log.write(f"[exit={completed.returncode} elapsed_seconds={elapsed}]\n")
    record = {
        "command": safe_command,
        "stdout": stdout,
        "stderr": stderr,
        "return_code": completed.returncode,
        "elapsed_seconds": elapsed,
    }
    if command_records is not None:
        command_records.append(record)
    if completed.returncode != 0:
        raise LabmateError(
            f"本地工具失败（exit {completed.returncode}）；请查看 logs/{log_path.name}"
        )
    return record


def _read_regions(path: Path, candidates: dict[str, dict[str, str]]) -> dict[str, dict[str, list[dict[str, Any]]]]:
    rows = _read_csv(path)
    needed = {"candidate_id", "chain", "region", "sequence"}
    if not rows or not needed.issubset(rows[0]):
        raise InputValidationError("candidate_regions.csv 必须包含 candidate_id, chain, region, sequence")
    result: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    seen: set[tuple[str, str, str]] = set()
    for row in rows:
        candidate_id, chain = row["candidate_id"].strip(), row["chain"].strip().upper()
        region = row["region"].strip()
        sequence = row["sequence"].strip().upper()
        key = (candidate_id, chain, region)
        if (
            candidate_id not in candidates
            or chain not in {"H", "L"}
            or not region
            or not sequence
            or set(sequence) - STANDARD_AMINO_ACIDS
        ):
            raise InputValidationError(f"candidate regions 行无效: {candidate_id}/{chain}")
        if key in seen:
            raise InputValidationError(
                f"candidate regions 重复: {candidate_id}/{chain}/{region}"
            )
        seen.add(key)
        result[candidate_id][chain].append({"region": region, "sequence": sequence})
    for candidate_id, chains in candidates.items():
        for chain in ("H", "L"):
            chunks = result[candidate_id][chain]
            if not chunks or "".join(item["sequence"] for item in chunks) != chains[chain]:
                raise InputValidationError(f"{candidate_id} {chain} 的 regions 拼接必须严格等于 FASTA 序列")
    return result


def _rewrite_chains(source: Path, destination: Path, mapping: dict[str, str]) -> None:
    lines: list[str] = []
    for raw in source.read_text(encoding="utf-8", errors="strict").splitlines():
        if raw.startswith(("ATOM  ", "HETATM")) and len(raw) >= 22:
            chain = raw[21].strip() or "_"
            if chain in mapping:
                raw = raw[:21] + mapping[chain] + raw[22:]
        lines.append(raw)
    destination.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _ordered_residues(parsed: Any, chain_id: str) -> list[Any]:
    return list(
        dict.fromkeys(
            atom.residue
            for atom in parsed.atoms
            if atom.residue.chain_id == chain_id
        )
    )


def _chain_sequence(parsed: Any, chain_id: str) -> str:
    return "".join(
        THREE_TO_ONE[residue.residue_name]
        for residue in _ordered_residues(parsed, chain_id)
    )


def _colabfold_chain_mapping(
    source: Path, candidate: dict[str, str]
) -> dict[str, str]:
    parsed = parse_complex_pdb(source.read_bytes())
    if len(parsed.chains) != 2:
        raise LabmateError(
            f"ColabFold PDB 必须恰好有两条链，实际数量为 {len(parsed.chains)}"
        )
    observed = {
        chain_id: _chain_sequence(parsed, chain_id) for chain_id in parsed.chains
    }
    mapping: dict[str, str] = {}
    for target in ("H", "L"):
        matches = [
            chain_id
            for chain_id, sequence in observed.items()
            if sequence == candidate[target]
        ]
        if len(matches) != 1:
            raise LabmateError(
                f"ColabFold 输出无法通过逐字符序列唯一映射到 {target} 链"
            )
        mapping[matches[0]] = target
    if len(mapping) != 2:
        raise LabmateError("ColabFold VH/VL 序列映射存在歧义")
    return mapping


def _make_sequence_map(
    candidate_id: str,
    candidate: dict[str, str],
    regions: dict[str, list[dict[str, Any]]],
    pdb_path: Path,
    path: Path,
) -> None:
    parsed = parse_complex_pdb(pdb_path.read_bytes())
    if set(parsed.chains) != {"H", "L"}:
        raise LabmateError(f"{candidate_id} 结构链集合必须严格为 H/L")
    payload: dict[str, Any] = {
        "mapping_verified": True,
        "verification": "exact_input_sequence_to_observed_pdb_residue_order",
        "candidate_id": candidate_id,
        "chains": {},
    }
    for chain in ("H", "L"):
        residues = _ordered_residues(parsed, chain)
        observed = "".join(
            THREE_TO_ONE[residue.residue_name] for residue in residues
        )
        if observed != candidate[chain]:
            raise LabmateError(
                f"{candidate_id} ColabFold {chain} 链序列与输入逐字符不一致"
            )
        labels: list[str] = []
        for chunk in regions[chain]:
            labels.extend([chunk["region"]] * len(chunk["sequence"]))
        if len(labels) != len(residues):
            raise LabmateError(f"{candidate_id} {chain} 链 region/PDB 长度不一致")
        residue_rows = [
            {
                "pdb_residue_number": residue.residue_number,
                "sequence_position": position,
                "insertion_code": residue.insertion_code,
                "amino_acid": THREE_TO_ONE[residue.residue_name],
                "region": labels[position - 1],
            }
            for position, residue in enumerate(residues, start=1)
        ]
        payload["chains"][chain] = {
            "sequence": candidate[chain],
            "residues": residue_rows,
        }
    _write_json(path, payload)


def _plddt(
    path: Path,
    sequence_map: dict[str, list[dict[str, Any]]],
    scores: dict[str, Any] | None = None,
) -> tuple[float, float]:
    by_residue: dict[tuple[str, int, str], list[float]] = defaultdict(list)
    for line_number, raw in enumerate(
        path.read_text(encoding="utf-8", errors="strict").splitlines(), start=1
    ):
        if not raw.startswith("ATOM  "):
            continue
        if len(raw) < 66:
            raise LabmateError(f"PDB 第 {line_number} 行缺少 pLDDT B-factor")
        try:
            key = (raw[21].strip(), int(raw[22:26]), raw[26].strip())
            value = float(raw[60:66])
        except ValueError as exc:
            raise LabmateError(
                f"PDB 第 {line_number} 行 pLDDT B-factor 无效"
            ) from exc
        if not math.isfinite(value) or not 0.0 <= value <= 100.0:
            raise LabmateError(f"PDB 第 {line_number} 行 pLDDT 超出 0-100")
        by_residue[key].append(value)

    ordered_values: list[float] = []
    cdr_values: list[float] = []
    for chain in ("H", "L"):
        for row in sequence_map[chain]:
            key = (
                chain,
                int(row["pdb_residue_number"]),
                str(row["insertion_code"]),
            )
            atom_values = by_residue.get(key)
            if not atom_values:
                raise LabmateError(
                    f"ColabFold PDB 缺少映射残基的 pLDDT: {chain} {key[1]}{key[2]}"
                )
            residue_value = mean(atom_values)
            ordered_values.append(residue_value)
            if "cdr" in str(row["region"]).lower():
                cdr_values.append(residue_value)
    if not ordered_values or not cdr_values:
        raise LabmateError("ColabFold PDB 缺少可用的全链或 CDR pLDDT")

    json_plddt = (scores or {}).get("plddt")
    if json_plddt is not None:
        if not isinstance(json_plddt, list) or len(json_plddt) != len(ordered_values):
            raise LabmateError("ColabFold score JSON 的 pLDDT 长度与 PDB 不一致")
        try:
            score_values = [float(value) for value in json_plddt]
        except (TypeError, ValueError) as exc:
            raise LabmateError("ColabFold score JSON 的 pLDDT 无效") from exc
        if any(
            not math.isfinite(value) or not 0.0 <= value <= 100.0
            for value in score_values
        ):
            raise LabmateError("ColabFold score JSON 的 pLDDT 超出 0-100")
        if any(
            abs(pdb_value - json_value) > 0.06
            for pdb_value, json_value in zip(ordered_values, score_values)
        ):
            raise LabmateError("ColabFold PDB 与 score JSON 的逐残基 pLDDT 不一致")
    return round(mean(ordered_values), 4), round(mean(cdr_values), 4)


@dataclass(frozen=True)
class ColabFoldResult:
    pdb_path: Path
    score_path: Path
    scores: dict[str, Any]
    rank: int
    model_tag: str


_COLABFOLD_PDB_NAME = re.compile(
    r"^(?P<prefix>.+)_(?P<kind>unrelaxed|relaxed)_rank_"
    r"(?P<rank>[0-9]{3})_(?P<tag>.+)\.pdb$"
)


def _select_colabfold_result(directory: Path) -> ColabFoldResult:
    matches: list[tuple[Path, re.Match[str]]] = []
    for path in directory.rglob("*.pdb"):
        match = _COLABFOLD_PDB_NAME.fullmatch(path.name)
        if match and int(match.group("rank")) == 1:
            matches.append((path, match))
    if not matches:
        raise LabmateError("ColabFold 未生成官方 rank_001 PDB 输出")
    preferred_kind = (
        "relaxed"
        if any(match.group("kind") == "relaxed" for _, match in matches)
        else "unrelaxed"
    )
    preferred = [
        (path, match)
        for path, match in matches
        if match.group("kind") == preferred_kind
    ]
    if len(preferred) != 1:
        raise LabmateError("ColabFold rank_001 PDB 输出存在歧义")
    pdb_path, match = preferred[0]
    score_name = (
        f"{match.group('prefix')}_scores_rank_{match.group('rank')}_"
        f"{match.group('tag')}.json"
    )
    score_path = pdb_path.with_name(score_name)
    if not score_path.is_file():
        raise LabmateError("ColabFold rank_001 PDB 缺少同 model tag 的 score JSON")
    try:
        scores = json.loads(score_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LabmateError("ColabFold rank_001 score JSON 无效") from exc
    if not isinstance(scores, dict):
        raise LabmateError("ColabFold rank_001 score JSON 必须是对象")
    return ColabFoldResult(
        pdb_path=pdb_path,
        score_path=score_path,
        scores=scores,
        rank=1,
        model_tag=match.group("tag"),
    )


def _write_csv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader(); writer.writerows(rows)


@dataclass(frozen=True)
class LightDockSolution:
    swarm_id: int
    glowworm_id: int
    score: float
    raw_line: str
    source_path: Path


def _parse_lightdock_output(path: Path) -> list[LightDockSolution]:
    swarm_match = re.fullmatch(r"swarm_([0-9]+)", path.parent.name)
    if not swarm_match:
        raise LabmateError("LightDock gso 文件不在明确的 swarm_<id> 目录")
    swarm_id = int(swarm_match.group(1))
    solutions: list[LightDockSolution] = []
    for line_number, raw in enumerate(
        path.read_text(encoding="utf-8", errors="strict").splitlines(), start=1
    ):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        glowworm_id = len(solutions)
        if not line.startswith("(") or ")" not in line:
            raise LabmateError(
                f"LightDock gso 第 {line_number} 行不是官方 solution 格式"
            )
        closing = line.index(")")
        coordinate_fields = [
            field.strip() for field in line[1:closing].split(",")
        ]
        try:
            coordinates = [float(field) for field in coordinate_fields]
        except ValueError as exc:
            raise LabmateError(
                f"LightDock gso 第 {line_number} 行坐标无效"
            ) from exc
        if len(coordinates) < 7 or any(
            not math.isfinite(value) for value in coordinates
        ):
            raise LabmateError(
                f"LightDock gso 第 {line_number} 行坐标维度或数值无效"
            )
        rest = line[closing + 1 :].split()
        try:
            if len(rest) == 4:
                float(rest[0])
                int(rest[1])
                float(rest[2])
                score = float(rest[3])
            elif len(rest) == 6:
                int(rest[0])
                int(rest[1])
                float(rest[2])
                int(rest[3])
                float(rest[4])
                score = float(rest[5])
            else:
                raise ValueError
        except ValueError as exc:
            raise LabmateError(
                f"LightDock gso 第 {line_number} 行 score schema 无效"
            ) from exc
        if not math.isfinite(score):
            raise LabmateError(
                f"LightDock gso 第 {line_number} 行 score 不是有限数"
            )
        solutions.append(
            LightDockSolution(
                swarm_id=swarm_id,
                glowworm_id=glowworm_id,
                score=score,
                raw_line=line,
                source_path=path,
            )
        )
    if not solutions:
        raise LabmateError("LightDock gso 文件没有有效 solution")
    return solutions


def _select_lightdock_solutions(
    score_files: list[Path], *, count: int, score_direction: str
) -> list[LightDockSolution]:
    solutions = [
        solution
        for score_file in score_files
        for solution in _parse_lightdock_output(score_file)
    ]
    if len(solutions) < count:
        raise LabmateError("LightDock solution 数少于请求的 top poses")
    if score_direction == "higher_is_better":
        key = lambda item: (-item.score, item.swarm_id, item.glowworm_id)
    elif score_direction == "lower_is_better":
        key = lambda item: (item.score, item.swarm_id, item.glowworm_id)
    else:
        raise LabmateError("LightDock score_direction 无效")
    return sorted(solutions, key=key)[:count]


def _pdb_chain_contract(
    path: Path,
) -> tuple[dict[str, str], dict[str, list[tuple[int, str, str]]]]:
    parsed = parse_complex_pdb(path.read_bytes())
    sequences = {
        chain_id: _chain_sequence(parsed, chain_id) for chain_id in parsed.chains
    }
    residue_keys = {
        chain_id: [
            (
                residue.residue_number,
                residue.insertion_code,
                residue.residue_name,
            )
            for residue in _ordered_residues(parsed, chain_id)
        ]
        for chain_id in parsed.chains
    }
    return sequences, residue_keys


def _validate_lightdock_pose(
    path: Path,
    *,
    expected_sequences: dict[str, str],
    expected_residue_keys: dict[str, list[tuple[int, str, str]]],
) -> None:
    observed_sequences, observed_keys = _pdb_chain_contract(path)
    if set(observed_sequences) != {"A", "H", "L"}:
        raise LabmateError("LightDock pose 链集合必须严格为 A/H/L")
    if observed_sequences != expected_sequences:
        raise LabmateError("LightDock pose 的 A/H/L 序列与输入逐字符不一致")
    if observed_keys != expected_residue_keys:
        raise LabmateError("LightDock pose 的 A/H/L residue key 映射发生变化")


def _sanitized_job_snapshot(job: LiveLocalJobSpec, *, cwd: Path) -> dict[str, Any]:
    snapshot = job.model_dump(mode="json")
    snapshot["candidate_fasta"] = "inputs/candidates.fasta"
    snapshot["candidate_regions_file"] = "inputs/candidate_regions.csv"
    snapshot["antigen"]["file"] = "inputs/antigen_original.pdb"
    for key in (
        "colabfold_batch",
        "lightdock_setup",
        "lightdock_run",
        "lightdock_generate",
    ):
        snapshot["tools"][key] = Path(snapshot["tools"][key]).name
    snapshot["tools"]["colabfold_args"] = [
        _redact_text(argument, cwd=cwd)
        for argument in snapshot["tools"]["colabfold_args"]
    ]
    return snapshot


_TEXT_METADATA_SUFFIXES = {
    ".bibtex",
    ".csv",
    ".html",
    ".json",
    ".log",
    ".txt",
    ".yaml",
    ".yml",
}


def _sanitize_run_metadata(run_dir: Path) -> list[str]:
    changed: list[str] = []
    for path in run_dir.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in _TEXT_METADATA_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        redacted = _redact_text(text, cwd=run_dir)
        if redacted != text:
            path.write_text(redacted, encoding="utf-8")
            changed.append(path.relative_to(run_dir).as_posix())
    return sorted(changed)


def _audit_run_privacy(run_dir: Path, forbidden_values: list[str]) -> None:
    forbidden: set[bytes] = set()
    local_context = [
        platform.node(),
        *(
            os.environ.get(key, "")
            for key in ("USERNAME", "USER", "LOGNAME", "HOSTNAME", "COMPUTERNAME")
        ),
        *(
            value
            for key, value in os.environ.items()
            if re.search(
                r"(?i)(token|key|secret|password|credential|authorization)", key
            )
        ),
    ]
    for value in [*forbidden_values, *local_context]:
        if not value:
            continue
        for variant in {value, value.replace("\\", "/"), value.replace("/", "\\")}:
            if len(variant) >= 4:
                forbidden.add(variant.encode("utf-8", errors="ignore"))
    for path in run_dir.rglob("*"):
        if not path.is_file():
            continue
        data = path.read_bytes()
        if any(value and value in data for value in forbidden):
            raise LabmateError(
                f"隐私审计失败：artifact 含本机上下文（{path.relative_to(run_dir).as_posix()}）"
            )
        if path.suffix.lower() in _TEXT_METADATA_SUFFIXES:
            text = data.decode("utf-8", errors="replace")
            if _WINDOWS_ABSOLUTE.search(text) or _POSIX_LOCAL_ABSOLUTE.search(text):
                raise LabmateError(
                    f"隐私审计失败：metadata 含绝对路径（{path.relative_to(run_dir).as_posix()}）"
                )
            if _TOKEN_SHAPES.search(text):
                raise LabmateError(
                    f"隐私审计失败：metadata 含疑似 token（{path.relative_to(run_dir).as_posix()}）"
                )
            if _ENVIRONMENT_VARIABLE_REFERENCE.search(text):
                raise LabmateError(
                    f"隐私审计失败：metadata 含环境变量引用（{path.relative_to(run_dir).as_posix()}）"
                )


def _live_interface_config(job: LiveLocalJobSpec):
    """Analyze every pose that this Live Local job selected."""
    return replace(
        DEFAULT_INTERFACE_CONFIG,
        analyze_top_poses=job.docking.top_poses_per_candidate,
    )


def execute_live_local(
    *,
    job: LiveLocalJobSpec,
    candidate_fasta: Path,
    regions_file: Path,
    antigen_bytes: bytes,
    output_root: Path,
    colabfold_executor: Any | None = None,
    lightdock_executor: Any | None = None,
    tool_execution_provider: str = "host",
    container_versions: dict[str, str] | None = None,
) -> RunResult:
    """Run ColabFold + LightDock, then analyze locally.

    ``colabfold_executor`` / ``lightdock_executor`` (Phase D4) replace the
    host ``_run`` invocations with container-based executors while reusing
    every downstream validation stage.  When both are None the unchanged
    host path is used.  ``container_versions`` records the probed worker
    versions for the manifest/capabilities in docker mode.
    """
    model_data_root = _validate_preinstalled_colabfold_data(
        job.tools.colabfold_args
    )
    docker_mode = colabfold_executor is not None or lightdock_executor is not None
    if docker_mode:
        versions = container_versions or {}
        lightdock_version = versions.get("lightdock", "not-probed")
        capabilities = {
            "colabfold": Capability(
                name="colabfold",
                status=CapabilityStatus.AVAILABLE_UNVERIFIED,
                enabled=True,
                provider="docker-compose colabfold worker",
                version=versions.get("colabfold", "not-probed"),
                license_status="external ColabFold official image; not bundled",
                reason="Docker Compose worker selected explicitly by the user.",
            ),
            "lightdock_setup": Capability(
                name="lightdock_setup",
                status=CapabilityStatus.AVAILABLE_UNVERIFIED,
                enabled=True,
                provider="docker-compose lightdock worker",
                version=lightdock_version,
                license_status="GPL-3.0 external installation; not bundled",
                reason="Docker Compose worker selected explicitly by the user.",
            ),
            "lightdock_run": Capability(
                name="lightdock_run",
                status=CapabilityStatus.AVAILABLE_UNVERIFIED,
                enabled=True,
                provider="docker-compose lightdock worker",
                version=lightdock_version,
                license_status="GPL-3.0 external installation; not bundled",
                reason="Docker Compose worker selected explicitly by the user.",
            ),
            "lightdock_generate": Capability(
                name="lightdock_generate",
                status=CapabilityStatus.AVAILABLE_UNVERIFIED,
                enabled=True,
                provider="docker-compose lightdock worker",
                version=lightdock_version,
                license_status="GPL-3.0 external installation; not bundled",
                reason="Docker Compose worker selected explicitly by the user.",
            ),
        }
    else:
        capabilities = preflight_live_local(job)
    missing = [name for name, item in capabilities.items() if not item.enabled]
    if missing:
        raise LabmateError("Live Local 预检失败，缺少工具: " + ", ".join(missing))
    if capabilities["colabfold"].version == "not-probed":
        raise LabmateError("Live Local 预检失败：无法探测 ColabFold 版本")
    if capabilities["lightdock_run"].version == "not-probed":
        raise LabmateError("Live Local 预检失败：无法探测 LightDock 版本")
    candidates = _parse_fasta(candidate_fasta)
    regions = _read_regions(regions_file, candidates)
    output_root = output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    run_id = _run_id()
    run_dir = output_root / run_id
    run_dir.mkdir()
    for name in (
        "inputs",
        "candidates",
        "structures",
        "docking",
        "analysis",
        "ranking",
        "figures",
        "logs",
    ):
        (run_dir / name).mkdir()
    log = run_dir / "logs" / "live_local.log"
    state = StageStateMachine(
        execution_kind=ExecutionKind.LIVE,
        provider="LiveLocalBackend",
        stages=LIVE_LOCAL_STAGES,
    )
    input_hashes = {
        "candidate_fasta_sha256": sha256_file(candidate_fasta),
        "candidate_regions_sha256": sha256_file(regions_file),
        "antigen_sha256": hashlib.sha256(antigen_bytes).hexdigest(),
    }
    forbidden_values = [
        str(candidate_fasta.resolve()),
        str(regions_file.resolve()),
        str(output_root),
        str(run_dir),
        str(model_data_root.resolve()),
        str(Path.home()),
    ]
    if not docker_mode:
        # Host-mode tool fields are full paths to user-installed executables;
        # they are genuine local context.  In docker mode they are bare
        # placeholder names (the real tools live in containers) and are not
        # local context at all.
        forbidden_values.extend(
            [
                job.tools.colabfold_batch,
                job.tools.lightdock_setup,
                job.tools.lightdock_run,
                job.tools.lightdock_generate,
            ]
        )

    state.start(
        "S00",
        input_hashes=input_hashes,
        notes=[
            "LIVE LOCAL; external commands are invoked only from this machine.",
            "ColabFold MSA policy is offline_single_sequence; no public MSA request is permitted.",
            "ColabFold model data was verified as preinstalled before execution.",
        ],
    )
    snapshot = _sanitized_job_snapshot(job, cwd=run_dir)
    _write_json(run_dir / "job.json", snapshot)
    state.succeed(
        "S00", output_hashes=_hash_map([run_dir / "job.json"], run_dir)
    )

    state.start(
        "S01",
        notes=["Validated and normalized the single selected antigen chain to chain A."],
    )
    original = run_dir / "inputs" / "antigen_original.pdb"
    original.write_bytes(antigen_bytes)
    antigen = parse_antigen_pdb(antigen_bytes, selected_chains=job.antigen.chains)
    raw_clean = run_dir / "inputs" / "antigen_cleaned_original_chain.pdb"
    raw_clean.write_text(antigen.cleaned_pdb, encoding="utf-8")
    original_chain = antigen.chains[0]
    cleaned = run_dir / "inputs" / "antigen_cleaned.pdb"
    _rewrite_chains(raw_clean, cleaned, {original_chain: "A"})
    antigen_sequences, antigen_residue_keys = _pdb_chain_contract(cleaned)
    if set(antigen_sequences) != {"A"}:
        raise LabmateError("清理后的抗原链集合必须严格为 A")
    antigen_mapping = run_dir / "inputs" / "antigen_residue_mapping.json"
    _write_json(
        antigen_mapping,
        {
            "input_chain": original_chain,
            "docking_chain": "A",
            "sequence_exactly_preserved": True,
            "residue_mapping": antigen.residue_mapping,
            "warnings": antigen.warnings,
        },
    )
    state.succeed(
        "S01",
        output_hashes=_hash_map(
            [original, raw_clean, cleaned, antigen_mapping], run_dir
        ),
    )

    state.start(
        "S02",
        notes=[
            "Copied candidate artifacts; IgCraft is not executed by Live Local v2.0."
        ],
    )
    root_fasta = run_dir / "inputs" / "candidates.fasta"
    shutil.copy2(candidate_fasta, root_fasta)
    root_regions = run_dir / "inputs" / "candidate_regions.csv"
    shutil.copy2(regions_file, root_regions)
    state.succeed(
        "S02", output_hashes=_hash_map([root_fasta, root_regions], run_dir)
    )

    state.start(
        "S03", notes=["Verified VH/VL FASTA and exact region concatenation."]
    )
    for candidate_id in candidates:
        _write_json(
            run_dir / "candidates" / f"{candidate_id}_input_annotations.json",
            {
                "candidate_id": candidate_id,
                "pdb_mapping_status": "pending_structure_prediction",
                "chains": candidates[candidate_id],
                "regions": regions[candidate_id],
            },
        )
    state.succeed(
        "S03",
        output_hashes=_hash_map(
            list((run_dir / "candidates").glob("*.json")), run_dir
        ),
    )

    state.start(
        "S04",
        notes=[
            "Invoking locally installed ColabFold once per VH:VL candidate.",
            "MSA mode is explicitly single_sequence; no sequence is sent to a public MSA service.",
            "Model type is explicitly alphafold2_multimer_v3 using preinstalled weights.",
        ],
    )
    structure_rows: list[dict[str, Any]] = []
    colabfold_chain_mappings: dict[str, dict[str, str]] = {}
    for candidate_id, chains in sorted(candidates.items()):
        candidate_dir = run_dir / "structures" / candidate_id
        candidate_dir.mkdir()
        fasta = candidate_dir / "input.fasta"
        fasta.write_text(
            f">{candidate_id}\n{chains['H']}:{chains['L']}\n",
            encoding="utf-8",
        )
        output = candidate_dir / "colabfold"
        output.mkdir()
        if colabfold_executor is not None:
            # Phase D4: ColabFold runs inside the isolated GPU container.
            # The executor returns a ColabFoldResult-compatible object whose
            # PDB is already copied under candidate_dir/colabfold/ and whose
            # score JSON is preserved for the exact sequence/pLDDT checks.
            result = colabfold_executor(
                candidate_id=candidate_id,
                chains=chains,
                candidate_dir=candidate_dir,
                run_dir=run_dir,
            )
        else:
            _run(
                [
                    job.tools.colabfold_batch,
                    "input.fasta",
                    "colabfold",
                    *job.tools.colabfold_args,
                ],
                cwd=candidate_dir,
                log_path=log,
            )
            result = _select_colabfold_result(output)
        normalized = candidate_dir / "ranked_1.pdb"
        chain_mapping = _colabfold_chain_mapping(result.pdb_path, chains)
        _rewrite_chains(result.pdb_path, normalized, chain_mapping)
        colabfold_chain_mappings[candidate_id] = chain_mapping
        sequence_map_path = candidate_dir / "sequence_map.json"
        _make_sequence_map(
            candidate_id,
            chains,
            regions[candidate_id],
            normalized,
            sequence_map_path,
        )
        sequence_map_data = json.loads(
            sequence_map_path.read_text(encoding="utf-8")
        )
        mean_plddt, cdr_plddt = _plddt(
            normalized,
            {
                chain: chain_data["residues"]
                for chain, chain_data in sequence_map_data["chains"].items()
            },
            result.scores,
        )
        iptm: float | str = ""
        if "iptm" in result.scores:
            try:
                iptm_value = float(result.scores["iptm"])
            except (TypeError, ValueError) as exc:
                raise LabmateError("ColabFold ipTM 无效") from exc
            if not math.isfinite(iptm_value) or not 0.0 <= iptm_value <= 1.0:
                raise LabmateError("ColabFold ipTM 超出 0-1")
            iptm = iptm_value
        selection_path = candidate_dir / "colabfold_selection.json"
        _write_json(
            selection_path,
            {
                "rank": result.rank,
                "model_tag": result.model_tag,
                "selected_pdb": result.pdb_path.name,
                "matched_score_json": result.score_path.name,
                "source_chain_to_HL": chain_mapping,
                "exact_sequence_verified": True,
                "plddt_source": "PDB B-factor; cross-checked with score JSON when present",
            },
        )
        _sanitize_run_metadata(candidate_dir)
        structure_rows.append(
            {
                "candidate_id": candidate_id,
                "mean_plddt": mean_plddt,
                "cdr_plddt": cdr_plddt,
                "interface_pae": "",
                "iptm": iptm,
                "has_both_chains": True,
                "source_kind": job.source_type,
                "tool_execution": "executed_local",
            }
        )
    metrics_path = run_dir / "structures" / "structure_metrics.csv"
    _write_csv(
        metrics_path,
        [
            "candidate_id",
            "mean_plddt",
            "cdr_plddt",
            "interface_pae",
            "iptm",
            "has_both_chains",
            "source_kind",
            "tool_execution",
        ],
        structure_rows,
    )
    state.succeed(
        "S04",
        output_hashes=_hash_map(
            [
                path
                for path in (run_dir / "structures").rglob("*")
                if path.is_file()
            ],
            run_dir,
        ),
    )

    state.start(
        "S05",
        notes=[
            "Validated chain identity by exact sequence matching and recorded residue-weighted pLDDT.",
            "Interface PAE is unavailable for antibody-only prediction.",
        ],
    )
    state.succeed(
        "S05", output_hashes=_hash_map([metrics_path], run_dir)
    )

    state.start(
        "S06",
        notes=[
            "Invoking separately installed LightDock; GPL software is not bundled.",
            "Top poses are selected globally from explicit swarm/glowworm score records using the declared direction.",
        ],
    )
    poses: list[ParsedDockingPose] = []
    docking_rows: list[dict[str, Any]] = []
    pose_mapping_rows: list[dict[str, Any]] = []
    lightdock_version = capabilities["lightdock_run"].version or "not-probed"
    for candidate_id in sorted(candidates):
        work = run_dir / "docking" / candidate_id / "work"
        work.mkdir(parents=True)
        ligand = run_dir / "structures" / candidate_id / "ranked_1.pdb"
        receptor_local = work / "receptor_A.pdb"
        ligand_local = work / "antibody_HL.pdb"
        shutil.copy2(cleaned, receptor_local)
        shutil.copy2(ligand, ligand_local)
        if lightdock_executor is not None:
            # Phase D4: LightDock runs inside the isolated CPU container.
            # The executor performs setup/run/generate in the container and
            # reuses the shared GSO/pose validation helpers, returning the
            # same list types the host path would have filled.
            candidate_poses, candidate_rows, candidate_mappings = lightdock_executor(
                candidate_id=candidate_id,
                work=work,
                ligand=ligand,
                cleaned=cleaned,
                run_dir=run_dir,
                job=job,
                expected_sequences={
                    "A": antigen_sequences["A"],
                    "H": candidates[candidate_id]["H"],
                    "L": candidates[candidate_id]["L"],
                },
                expected_residue_keys={
                    "A": antigen_residue_keys["A"],
                    "H": _pdb_chain_contract(ligand)[1]["H"],
                    "L": _pdb_chain_contract(ligand)[1]["L"],
                },
                lightdock_version=lightdock_version,
            )
            poses.extend(candidate_poses)
            docking_rows.extend(candidate_rows)
            pose_mapping_rows.extend(candidate_mappings)
            continue
        _run(
            [
                job.tools.lightdock_setup,
                receptor_local.name,
                ligand_local.name,
                "-s",
                str(job.docking.swarms),
                "-g",
                str(job.docking.glowworms),
                "--noxt",
                "--noh",
                "--now",
            ],
            cwd=work,
            log_path=log,
        )
        _run(
            [
                job.tools.lightdock_run,
                "setup.json",
                str(job.docking.steps),
                "-c",
                str(job.docking.cores),
            ],
            cwd=work,
            log_path=log,
        )
        score_files = list(
            work.glob(f"swarm_*/gso_{job.docking.steps}.out")
        )
        swarm_ids = {
            int(path.parent.name.removeprefix("swarm_"))
            for path in score_files
            if re.fullmatch(r"swarm_[0-9]+", path.parent.name)
        }
        if swarm_ids != set(range(job.docking.swarms)):
            raise LabmateError(
                f"{candidate_id} LightDock gso swarm 集合不完整或不一致"
            )
        selected = _select_lightdock_solutions(
            score_files,
            count=job.docking.top_poses_per_candidate,
            score_direction=job.docking.score_direction,
        )
        selected_gso = work / "selected_top_poses.gso"
        selected_gso.write_text(
            "\n".join(solution.raw_line for solution in selected) + "\n",
            encoding="utf-8",
        )
        _run(
            [
                job.tools.lightdock_generate,
                receptor_local.name,
                ligand_local.name,
                selected_gso.name,
                str(len(selected)),
            ],
            cwd=work,
            log_path=log,
        )
        expected_sequences = {
            "A": antigen_sequences["A"],
            "H": candidates[candidate_id]["H"],
            "L": candidates[candidate_id]["L"],
        }
        _, ligand_residue_keys = _pdb_chain_contract(ligand)
        expected_residue_keys = {
            "A": antigen_residue_keys["A"],
            "H": ligand_residue_keys["H"],
            "L": ligand_residue_keys["L"],
        }
        for rank, solution in enumerate(selected, start=1):
            pose_file = work / f"lightdock_{rank - 1}.pdb"
            if not pose_file.is_file():
                raise LabmateError(
                    f"{candidate_id} LightDock 未生成预期的显式 pose 序号"
                )
            destination = (
                run_dir / "docking" / candidate_id / f"pose_{rank:03d}.pdb"
            )
            shutil.copy2(pose_file, destination)
            _validate_lightdock_pose(
                destination,
                expected_sequences=expected_sequences,
                expected_residue_keys=expected_residue_keys,
            )
            pose_rel = destination.relative_to(run_dir / "docking").as_posix()
            pose = ParsedDockingPose(
                candidate_id,
                rank,
                f"{candidate_id}-P{rank:03d}",
                solution.score,
                job.docking.score_name,
                job.docking.score_direction,
                pose_rel,
                "lightdock",
                lightdock_version,
                job.source_type,
                "executed_local",
            )
            poses.append(pose)
            source_gso = solution.source_path.relative_to(work).as_posix()
            mapping = {
                "candidate_id": candidate_id,
                "pose_rank": rank,
                "pose_id": pose.pose_id,
                "swarm_id": solution.swarm_id,
                "glowworm_id": solution.glowworm_id,
                "raw_score": solution.score,
                "score_direction": job.docking.score_direction,
                "source_gso": source_gso,
                "source_gso_sha256": sha256_file(solution.source_path),
                "selected_gso_line_number": rank,
                "generated_filename": pose_file.name,
                "complex_path": pose_rel,
                "pose_sha256": sha256_file(destination),
                "mapping_verification": "explicit_selected_gso_line_to_lightdock_<line_index>.pdb",
            }
            pose_mapping_rows.append(mapping)
            docking_rows.append({**pose.__dict__, **mapping})
        _sanitize_run_metadata(work)
    docking_path = run_dir / "docking" / "docking_scores.csv"
    docking_fields = [
        "candidate_id",
        "pose_rank",
        "pose_id",
        "raw_score",
        "score_name",
        "score_direction",
        "complex_path",
        "provider",
        "provider_version",
        "source_kind",
        "tool_execution",
        "swarm_id",
        "glowworm_id",
        "source_gso",
        "source_gso_sha256",
        "selected_gso_line_number",
        "generated_filename",
        "pose_sha256",
        "mapping_verification",
    ]
    _write_csv(docking_path, docking_fields, docking_rows)
    pose_mapping_path = run_dir / "docking" / "pose_score_mapping.csv"
    _write_csv(
        pose_mapping_path,
        [
            "candidate_id",
            "pose_rank",
            "pose_id",
            "swarm_id",
            "glowworm_id",
            "raw_score",
            "score_direction",
            "source_gso",
            "source_gso_sha256",
            "selected_gso_line_number",
            "generated_filename",
            "complex_path",
            "pose_sha256",
            "mapping_verification",
        ],
        pose_mapping_rows,
    )
    state.succeed(
        "S06",
        output_hashes=_hash_map(
            [
                path
                for path in (run_dir / "docking").rglob("*")
                if path.is_file()
            ],
            run_dir,
        ),
    )

    state.start(
        "S07",
        notes=[
            "Computed geometry-based contacts locally; PyMOL is optional and was not invoked."
        ],
    )
    analysis = analyze_interfaces(
        poses,
        docking_root=run_dir / "docking",
        structures_root=run_dir / "structures",
        output_dir=run_dir / "analysis",
        config=_live_interface_config(job),
        execution_mode="live_local",
        analysis_execution="local_recompute_from_executed_live_local_poses",
    )
    interface_root = run_dir / "interface_residues.csv"
    shutil.copy2(
        run_dir / "analysis" / "interface_residues.csv", interface_root
    )
    state.succeed(
        "S07",
        output_hashes=_hash_map(
            [
                path
                for path in (run_dir / "analysis").rglob("*")
                if path.is_file()
            ]
            + [interface_root],
            run_dir,
        ),
        notes=analysis["warnings"],
    )

    state.start(
        "S08",
        notes=[
            "Applied a same-run computational prioritization heuristic; it is not affinity or free energy."
        ],
    )
    metrics, higher = build_candidate_metrics(
        structure_metrics_path=metrics_path,
        docking_poses=poses,
        pose_consensus_path=run_dir / "analysis" / "pose_consensus.csv",
    )
    ranking = rank_candidates(
        metrics,
        docking_higher_is_better=higher,
        output_dir=run_dir / "ranking",
        execution_mode="live_local",
        ranking_execution="local_recompute_from_executed_live_local_artifacts",
    )
    ranking_root = run_dir / "candidate_ranking.csv"
    shutil.copy2(
        run_dir / "ranking" / "candidate_ranking.csv", ranking_root
    )
    state.succeed(
        "S08",
        output_hashes=_hash_map(
            [
                path
                for path in (run_dir / "ranking").rglob("*")
                if path.is_file()
            ]
            + [ranking_root],
            run_dir,
        ),
        notes=ranking["warnings"],
    )

    state.skip_optional(
        "S09",
        note="PyMOL not invoked; optional visualization is not part of this Live Local run.",
    )
    (run_dir / "figures" / "README.txt").write_text(
        "LIVE LOCAL: PyMOL skipped_optional.\n", encoding="utf-8"
    )
    redacted_metadata = _sanitize_run_metadata(run_dir)
    warnings = list(
        dict.fromkeys(
            antigen.warnings
            + analysis["warnings"]
            + ranking["warnings"]
            + [
                SCIENTIFIC_LIMITATION,
                "ColabFold ran with --msa-mode single_sequence; no public MSA service was used.",
                "ColabFold used preinstalled model weights; this application did not download models.",
                "LightDock score direction was explicitly declared; scores are only comparable within this run and scoring configuration.",
                "One-candidate smoke rankings have no between-candidate discriminatory meaning.",
            ]
            + (
                [
                    f"Redacted local context from {len(redacted_metadata)} metadata artifact(s)."
                ]
                if redacted_metadata
                else []
            )
        )
    )
    state.start(
        "S10",
        notes=[
            "Generated a single-file offline HTML report marked LIVE LOCAL · VERIFIED LIVE."
        ],
    )
    build_live_report(
        run_dir / "report.html",
        run_id=run_id,
        created_at=_utc_iso(),
        job=snapshot,
        input_hashes=input_hashes,
        antigen_summary={
            "chains": ["A"],
            "atom_count": len(antigen.atoms),
            "residue_count": antigen.residue_count,
        },
        stages=state.records,
        ranking_rows=ranking["rows"],
        warnings=warnings,
        tool_versions={
            name: capability.version
            for name, capability in capabilities.items()
        },
    )
    _sanitize_run_metadata(run_dir)
    reporting_record = state.succeed("S10")
    # Re-render after the transition so the final standalone HTML and the
    # manifest agree that the Reporting stage succeeded.
    build_live_report(
        run_dir / "report.html",
        run_id=run_id,
        created_at=_utc_iso(),
        job=snapshot,
        input_hashes=input_hashes,
        antigen_summary={
            "chains": ["A"],
            "atom_count": len(antigen.atoms),
            "residue_count": antigen.residue_count,
        },
        stages=state.records,
        ranking_rows=ranking["rows"],
        warnings=warnings,
        tool_versions={
            name: capability.version
            for name, capability in capabilities.items()
        },
    )
    _sanitize_run_metadata(run_dir)
    reporting_record.output_hashes = _hash_map(
        [run_dir / "report.html"], run_dir
    )
    _audit_run_privacy(run_dir, forbidden_values)
    artifacts = _collect_artifacts(run_dir, execution_mode="live_local")
    verified_capabilities = {
        name: capability.model_copy(
            update={
                "status": CapabilityStatus.VERIFIED_LIVE,
                "reason": (
                    "Executed successfully in this run and passed output, "
                    "mapping, and privacy checks."
                ),
            }
        )
        for name, capability in capabilities.items()
    }
    manifest_path = run_dir / "manifest.json"
    _write_json(
        manifest_path,
        {
            "schema_version": "2.1.0",
            "run_id": run_id,
            "mode": "live_local",
            "backend": "local",
            "status": "verified_live",
            "tool_execution_provider": tool_execution_provider,
            "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "input_hashes": input_hashes,
            "job": snapshot,
            "tools": {
                "antibody_labmate": {
                    "version": __version__,
                    "python": platform.python_version(),
                },
                "external": {
                    name: value.model_dump(mode="json")
                    for name, value in verified_capabilities.items()
                },
            },
            "models": {
                "colabfold_model_type": "alphafold2_multimer_v3",
                "model_data_policy": "preinstalled_only",
                "model_downloaded_by_application": False,
                "msa_mode": "single_sequence",
                "public_msa_service_used": False,
                "sequence_uploaded_by_application": False,
            },
            "chain_mappings": {
                "antigen": {
                    "input_chain": original_chain,
                    "docking_chain": "A",
                    "exact_sequence_verified": True,
                },
                "antibody": colabfold_chain_mappings,
                "pose_chain_contract": "exact A/H/L chain set, sequence, residue number, insertion code, and residue name",
            },
            "pose_score_mapping": {
                "file": "docking/pose_score_mapping.csv",
                "selection": "global across all requested swarms",
                "score_direction": job.docking.score_direction,
                "score_name": job.docking.score_name,
                "mapping_rule": "selected gso rows are materialized in explicit line order; filenames are not sorted to infer scores",
            },
            "verification": {
                "scope": "local integration run only; not scientific validation",
                "exact_input_sequences_matched_to_colabfold_pdb": True,
                "plddt_cross_checked_with_score_json": True,
                "pose_chain_contract_verified": True,
                "all_requested_top_poses_analyzed": True,
                "artifact_hashes_verified_before_packaging": True,
                "privacy_audit_passed": True,
            },
            "stages": [
                record.model_dump(mode="json") for record in state.records
            ],
            "artifacts": [
                artifact.model_dump(mode="json") for artifact in artifacts
            ],
            "warnings": warnings,
            "limitations": [
                SCIENTIFIC_LIMITATION,
                "verified_live refers only to the tested local software integration and exact recorded tool/configuration scope.",
                "The one-candidate smoke run is an integration check, not scientific validation.",
                "Ranking is a within-run heuristic priority, not affinity, binding free energy, efficacy, or an experimental conclusion.",
            ],
        },
    )
    _audit_run_privacy(run_dir, forbidden_values)
    (run_dir / "manifest.sha256").write_text(
        f"{sha256_file(manifest_path)}  manifest.json\n", encoding="utf-8"
    )
    zip_path = output_root / f"{run_id}.zip"
    _safe_zip(run_dir, zip_path)
    return RunResult(
        run_id=run_id,
        run_dir=str(run_dir),
        zip_path=str(zip_path),
        manifest_path=str(manifest_path),
        report_path=str(run_dir / "report.html"),
        stages=state.records,
    )

"""Transparent within-run heuristic ranking with fixed direction handling."""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path
from statistics import median
from typing import Any

from labmate.docking.lightdock import ParsedDockingPose
from labmate.errors import FixtureIntegrityError
from labmate.models import CandidateMetric

DEFAULT_WEIGHTS = {"structure": 0.35, "docking": 0.45, "interface": 0.20}
STRUCTURE_WEIGHTS = {"mean_plddt": 0.30, "cdr_plddt": 0.40, "interface_pae": 0.20, "iptm": 0.10}
DOCKING_WEIGHTS = {"docking_best_score": 0.50, "docking_topk_median": 0.50}
INTERFACE_WEIGHTS = {"cdr_contact_ratio": 0.40, "pose_consensus": 0.30, "clash_free_ratio": 0.30}

METRIC_DIRECTIONS = {
    "mean_plddt": "higher_is_better",
    "cdr_plddt": "higher_is_better",
    "interface_pae": "lower_is_better",
    "iptm": "higher_is_better",
    "docking_best_score": "provider_declared",
    "docking_topk_median": "provider_declared",
    "cdr_contact_ratio": "higher_is_better",
    "pose_consensus": "higher_is_better",
    "clash_free_ratio": "higher_is_better",
}


def normalize_metric(values: dict[str, float | None], *, higher_is_better: bool) -> dict[str, float | None]:
    present = [value for value in values.values() if value is not None]
    if not present:
        return {key: None for key in values}
    low, high = min(present), max(present)
    if high == low:
        return {key: (50.0 if value is not None else None) for key, value in values.items()}
    normalized: dict[str, float | None] = {}
    for key, value in values.items():
        if value is None:
            normalized[key] = None
            continue
        scaled = (value - low) / (high - low)
        if not higher_is_better:
            scaled = 1.0 - scaled
        normalized[key] = scaled * 100.0
    return normalized


def _weighted_average(values: dict[str, float | None], weights: dict[str, float]) -> float:
    available = [(name, value) for name, value in values.items() if value is not None]
    if not available:
        raise FixtureIntegrityError("子分数组没有可用指标")
    denominator = sum(weights[name] for name, _ in available)
    return sum(float(value) * weights[name] for name, value in available) / denominator


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def build_candidate_metrics(
    *,
    structure_metrics_path: Path,
    docking_poses: list[ParsedDockingPose],
    pose_consensus_path: Path,
) -> tuple[list[CandidateMetric], bool]:
    structure_rows = {row["candidate_id"]: row for row in _read_csv(structure_metrics_path)}
    consensus_rows = {row["candidate_id"]: row for row in _read_csv(pose_consensus_path)}
    poses_by_candidate: dict[str, list[ParsedDockingPose]] = defaultdict(list)
    for pose in docking_poses:
        poses_by_candidate[pose.candidate_id].append(pose)
    candidates = sorted(set(structure_rows) | set(consensus_rows) | set(poses_by_candidate))
    if not candidates:
        raise FixtureIntegrityError("没有可排名候选")

    directions = {pose.score_direction for pose in docking_poses}
    if len(directions) != 1:
        raise FixtureIntegrityError("同一运行中的 docking score 方向不一致")
    docking_higher_is_better = directions.pop() == "higher_is_better"

    result: list[CandidateMetric] = []
    for candidate_id in candidates:
        structure = structure_rows.get(candidate_id)
        consensus = consensus_rows.get(candidate_id)
        poses = sorted(poses_by_candidate.get(candidate_id, []), key=lambda item: item.pose_rank)
        rejected: list[str] = []
        if structure is None:
            rejected.append("missing_structure_metrics")
        elif structure.get("has_both_chains", "").lower() != "true":
            rejected.append("missing_vh_or_vl")
        if consensus is None:
            rejected.append("missing_interface_analysis")
        if not poses:
            rejected.append("missing_docking_pose")
        if rejected:
            raise FixtureIntegrityError(f"{candidate_id} 不满足排名硬门槛: {', '.join(rejected)}")
        assert structure is not None and consensus is not None
        scores = [pose.raw_score for pose in poses]
        best = max(scores) if docking_higher_is_better else min(scores)
        result.append(
            CandidateMetric(
                candidate_id=candidate_id,
                mean_plddt=float(structure["mean_plddt"]),
                cdr_plddt=float(structure["cdr_plddt"]),
                interface_pae=float(structure["interface_pae"]) if structure.get("interface_pae") else None,
                iptm=float(structure["iptm"]) if structure.get("iptm") else None,
                docking_best_score=best,
                docking_topk_median=float(median(scores)),
                cdr_contact_ratio=float(consensus["cdr_contact_ratio"]),
                pose_consensus=float(consensus["pose_consensus"]),
                clash_free_ratio=float(consensus["clash_free_ratio"]),
                pose_count=len(poses),
            )
        )
    return result, docking_higher_is_better


def _scenario_rows(base_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    scenarios = {
        "base": DEFAULT_WEIGHTS,
        "structure_focus": {"structure": 0.45, "docking": 0.35, "interface": 0.20},
        "docking_focus": {"structure": 0.25, "docking": 0.55, "interface": 0.20},
        "interface_focus": {"structure": 0.30, "docking": 0.40, "interface": 0.30},
    }
    output: list[dict[str, Any]] = []
    for scenario, weights in scenarios.items():
        ranked: list[tuple[str, float]] = []
        for row in base_rows:
            score = (
                weights["structure"] * row["structure_score"]
                + weights["docking"] * row["docking_score"]
                + weights["interface"] * row["interface_score"]
            )
            ranked.append((row["candidate_id"], score))
        ranked.sort(key=lambda item: (-item[1], item[0]))
        for index, (candidate_id, score) in enumerate(ranked, start=1):
            output.append(
                {
                    "scenario": scenario,
                    "structure_weight": weights["structure"],
                    "docking_weight": weights["docking"],
                    "interface_weight": weights["interface"],
                    "rank": index,
                    "candidate_id": candidate_id,
                    "final_score": round(score, 6),
                }
            )
    return output


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def rank_candidates(
    metrics: list[CandidateMetric],
    *,
    docking_higher_is_better: bool,
    output_dir: Path,
    execution_mode: str = "replay",
    ranking_execution: str = "local_recompute_from_replay_artifacts",
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    normalized: dict[str, dict[str, float | None]] = {}
    metric_names = [
        "mean_plddt",
        "cdr_plddt",
        "interface_pae",
        "iptm",
        "docking_best_score",
        "docking_topk_median",
        "cdr_contact_ratio",
        "pose_consensus",
        "clash_free_ratio",
    ]
    for metric_name in metric_names:
        values = {item.candidate_id: getattr(item, metric_name) for item in metrics}
        if metric_name in {"docking_best_score", "docking_topk_median"}:
            higher = docking_higher_is_better
        else:
            higher = METRIC_DIRECTIONS[metric_name] == "higher_is_better"
        normalized[metric_name] = normalize_metric(values, higher_is_better=higher)

    rows: list[dict[str, Any]] = []
    for metric in metrics:
        candidate_id = metric.candidate_id
        structure_norm = {name: normalized[name][candidate_id] for name in STRUCTURE_WEIGHTS}
        docking_norm = {name: normalized[name][candidate_id] for name in DOCKING_WEIGHTS}
        interface_norm = {name: normalized[name][candidate_id] for name in INTERFACE_WEIGHTS}
        structure_score = _weighted_average(structure_norm, STRUCTURE_WEIGHTS)
        docking_score = _weighted_average(docking_norm, DOCKING_WEIGHTS)
        interface_score = _weighted_average(interface_norm, INTERFACE_WEIGHTS)
        final_score = (
            DEFAULT_WEIGHTS["structure"] * structure_score
            + DEFAULT_WEIGHTS["docking"] * docking_score
            + DEFAULT_WEIGHTS["interface"] * interface_score
        )
        row: dict[str, Any] = metric.model_dump(mode="json")
        for metric_name in metric_names:
            value = normalized[metric_name][candidate_id]
            row[f"norm_{metric_name}"] = "missing" if value is None else round(value, 6)
        row.update(
            {
                "structure_weight": DEFAULT_WEIGHTS["structure"],
                "docking_weight": DEFAULT_WEIGHTS["docking"],
                "interface_weight": DEFAULT_WEIGHTS["interface"],
                "structure_score": round(structure_score, 6),
                "docking_score": round(docking_score, 6),
                "interface_score": round(interface_score, 6),
                "final_score": round(final_score, 6),
                "rank": 0,
                "is_tied": False,
            }
        )
        rows.append(row)

    rows.sort(key=lambda row: (-row["final_score"], row["candidate_id"]))
    last_score: float | None = None
    last_rank = 0
    score_counts: dict[float, int] = defaultdict(int)
    for row in rows:
        score_counts[row["final_score"]] += 1
    for index, row in enumerate(rows, start=1):
        if last_score is None or row["final_score"] != last_score:
            last_rank = index
            last_score = row["final_score"]
        row["rank"] = last_rank
        row["is_tied"] = score_counts[row["final_score"]] > 1

    fields = [
        "rank",
        "is_tied",
        "candidate_id",
        "mean_plddt",
        "cdr_plddt",
        "interface_pae",
        "iptm",
        "docking_best_score",
        "docking_topk_median",
        "cdr_contact_ratio",
        "pose_consensus",
        "clash_free_ratio",
        "pose_count",
        "norm_mean_plddt",
        "norm_cdr_plddt",
        "norm_interface_pae",
        "norm_iptm",
        "norm_docking_best_score",
        "norm_docking_topk_median",
        "norm_cdr_contact_ratio",
        "norm_pose_consensus",
        "norm_clash_free_ratio",
        "structure_weight",
        "docking_weight",
        "interface_weight",
        "structure_score",
        "docking_score",
        "interface_score",
        "final_score",
        "rejected_reason",
    ]
    _write_csv(output_dir / "candidate_ranking.csv", fields, rows)
    sensitivity = _scenario_rows(rows)
    _write_csv(
        output_dir / "weight_sensitivity.csv",
        [
            "scenario",
            "structure_weight",
            "docking_weight",
            "interface_weight",
            "rank",
            "candidate_id",
            "final_score",
        ],
        sensitivity,
    )
    warnings: list[str] = []
    if len(metrics) < 3:
        warnings.append("候选数少于 3；min-max 归一化排名不稳定，应优先查看原始指标")
    metric_definitions = {
        "scope": "same run, same antigen, same provider schema and parameters only",
        "directions": {
            **METRIC_DIRECTIONS,
            "docking_best_score": "higher_is_better" if docking_higher_is_better else "lower_is_better",
            "docking_topk_median": "higher_is_better" if docking_higher_is_better else "lower_is_better",
        },
        "subscore_weights": {
            "structure": STRUCTURE_WEIGHTS,
            "docking": DOCKING_WEIGHTS,
            "interface": INTERFACE_WEIGHTS,
        },
        "final_weights": DEFAULT_WEIGHTS,
        "interpretation": "product heuristic for computational prioritization; not affinity or free energy",
    }
    normalization = {
        "method": "within-run min-max to 0-100 after direction alignment",
        "constant_metric_rule": "all candidates receive 50 when max == min",
        "missing_optional_metric_rule": "renormalize remaining weights within the subscore",
        "tie_rule": "equal rounded final_score is a tie; candidate_id only stabilizes display",
        "warnings": warnings,
    }
    ranking_manifest = {
        "schema_version": "1.0.0",
        "execution_mode": execution_mode,
        "ranking_execution": ranking_execution,
        "candidate_count": len(metrics),
        "warnings": warnings,
    }
    for name, payload in (
        ("metric_definitions.json", metric_definitions),
        ("normalization.json", normalization),
        ("ranking_manifest.json", ranking_manifest),
    ):
        (output_dir / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"rows": rows, "sensitivity": sensitivity, "warnings": warnings}

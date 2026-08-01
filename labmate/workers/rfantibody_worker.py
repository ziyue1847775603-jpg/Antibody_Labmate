"""Minimal RFantibody external worker; it intentionally imports no Labmate code."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path

SCHEMA_VERSION = 1
AA3 = {"ALA":"A","ARG":"R","ASN":"N","ASP":"D","CYS":"C","GLN":"Q","GLU":"E","GLY":"G","HIS":"H","ILE":"I","LEU":"L","LYS":"K","MET":"M","PHE":"F","PRO":"P","SER":"S","THR":"T","TRP":"W","TYR":"Y","VAL":"V"}
HOTSPOT = re.compile(r"[A-Za-z0-9]:-?[0-9]+[A-Za-z]?")
TOKEN = re.compile(r"(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16})")
ABSOLUTE = re.compile(r"(?<![\w:/])(?:[A-Za-z]:[\\/]|/(?:mnt|root|home)/)[^\s'\"<>]*")
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_request(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    allowed = {"schema_version","target_filename","target_sha256","target_chains","hotspot_residues","antibody_format","seed","candidate_count","parameters","resume_backbone_filename","resume_backbone_sha256"}
    if not isinstance(value, dict) or set(value) - allowed or value.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("invalid request schema")
    if value.get("antibody_format") != "vhh" or not isinstance(value.get("seed"), int) or value["seed"] < 0 or value.get("candidate_count") not in {1,2}:
        raise ValueError("invalid RFantibody request controls")
    if not isinstance(value.get("target_filename"), str) or Path(value["target_filename"]).name != value["target_filename"]:
        raise ValueError("target filename must be one relative filename")
    if not isinstance(value.get("hotspot_residues"), list) or not value["hotspot_residues"] or not all(isinstance(item, str) and HOTSPOT.fullmatch(item) for item in value["hotspot_residues"]):
        raise ValueError("invalid hotspots")
    return value


def sequence_and_pdb(source: Path, destination: Path) -> str:
    lines = source.read_text(encoding="utf-8", errors="strict").splitlines(keepends=True)
    selected = [line for line in lines if line.startswith("ATOM  ") and line[21:22] == "H"]
    if not selected:
        raise ValueError("RFantibody output has no expected VHH H chain")
    residues: list[tuple[str, str, str]] = []
    for line in selected:
        try:
            xyz = (float(line[30:38]), float(line[38:46]), float(line[46:54]))
        except ValueError as exc:
            raise ValueError("candidate coordinates are invalid") from exc
        if not all(math.isfinite(value) for value in xyz):
            raise ValueError("candidate coordinates are non-finite")
        key = (line[22:26], line[26:27], line[17:20].strip())
        if not residues or residues[-1] != key:
            residues.append(key)
    try:
        sequence = "".join(AA3[name] for _number, _icode, name in residues)
    except KeyError as exc:
        raise ValueError("candidate has unsupported residue") from exc
    if not sequence:
        raise ValueError("candidate sequence is empty")
    destination.write_text("".join(selected) + "TER\nEND\n", encoding="utf-8")
    return sequence


def write_response(path: Path, value: dict[str, object]) -> None:
    if path.exists() or path.is_symlink():
        raise ValueError("response must be new")
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")


def sanitize_log(value: str) -> str:
    value = "\n".join(
        line for line in value.splitlines() if "input to next step:" not in line
    )
    value = ANSI.sub("", value)
    return ABSOLUTE.sub("<local-path>", TOKEN.sub("<token-redacted>", value))


def native_metrics(stdout: str) -> dict[str, object]:
    metrics: dict[str, object] = {
        "pipeline_stage": "rfdiffusion_antibody_backbone_design",
    }
    patterns = {
        "overall_min_hotspot_to_designed_loop_distance_angstrom": r"Overall min distance hotspot to designed loop: ([0-9.eE+-]+)",
        "average_min_hotspot_to_designed_loop_distance_angstrom": r"Average min distance hotspot to designed loop: ([0-9.eE+-]+)",
    }
    for key, pattern in patterns.items():
        match = re.search(pattern, stdout)
        if match:
            value = float(match.group(1))
            if not math.isfinite(value):
                raise ValueError("non-finite RFantibody native metric")
            metrics[key] = value
    return metrics


def _proteinmpnn_output(stdout: str, *, expected_count: int) -> tuple[list[tuple[str, float]], list[int]]:
    sequences = re.search(r"sequence_optimize: (\[.*\])", stdout)
    loops = re.search(r"loopH: (\[.*\])", stdout)
    if sequences is None or loops is None:
        raise ValueError("official ProteinMPNN output is missing sequence/loop records")
    parsed = ast.literal_eval(sequences.group(1))
    positions = ast.literal_eval(loops.group(1))
    if not isinstance(parsed, list) or len(parsed) != expected_count:
        raise ValueError("official ProteinMPNN did not produce the requested sequence count")
    candidates: list[tuple[str, float]] = []
    for item in parsed:
        if not isinstance(item, tuple) or len(item) != 2:
            raise ValueError("official ProteinMPNN candidate record is malformed")
        sequence, score = item
        if not isinstance(sequence, str) or not re.fullmatch(r"[ACDEFGHIKLMNPQRSTVWY]+", sequence):
            raise ValueError("official ProteinMPNN sequence is invalid")
        if not isinstance(score, (int, float)) or not math.isfinite(float(score)):
            raise ValueError("official ProteinMPNN score is non-finite")
        candidates.append((sequence, float(score)))
    if not isinstance(positions, list) or not all(isinstance(item, int) and item > 0 for item in positions):
        raise ValueError("official ProteinMPNN designed-position record is invalid")
    return candidates, positions


def _validate_reusable_backbone(path: Path) -> None:
    """ProteinMPNN's official interface mode requires a binder H and target T."""
    lines = path.read_text(encoding="utf-8", errors="strict").splitlines()
    chains = {line[21:22] for line in lines if line.startswith("ATOM  ")}
    labels = {line.split()[-1] for line in lines if line.startswith("REMARK PDBinfo-LABEL")}
    if chains != {"H", "T"}:
        raise ValueError("verified RFdiffusion resume backbone must contain exactly H and T chains")
    if not {"H1", "H2", "H3"}.issubset(labels):
        raise ValueError("verified RFdiffusion resume backbone lacks official H1/H2/H3 metadata")


def _backbone_atom_coordinates(path: Path, *, chain: str, excluded_residue_numbers: set[int]) -> dict[tuple[int, str, str], tuple[float, float, float]]:
    result: dict[tuple[int, str, str], tuple[float, float, float]] = {}
    for line in path.read_text(encoding="utf-8", errors="strict").splitlines():
        if not line.startswith("ATOM  ") or line[21:22] != chain or line[12:16].strip() not in {"N", "CA", "C", "O"}:
            continue
        residue_number = int(line[22:26])
        if residue_number in excluded_residue_numbers:
            continue
        key = (residue_number, line[26:27], line[12:16].strip())
        coordinates = (float(line[30:38]), float(line[38:46]), float(line[46:54]))
        if not all(math.isfinite(value) for value in coordinates):
            raise ValueError("backbone contains non-finite coordinates")
        result[key] = coordinates
    if not result:
        raise ValueError("no fixed framework backbone atoms were found")
    return result


def _validate_fixed_backbone(input_pdb: Path, threaded_pdb: Path, designed_positions: list[int]) -> None:
    before = _backbone_atom_coordinates(input_pdb, chain="H", excluded_residue_numbers=set(designed_positions))
    after = _backbone_atom_coordinates(threaded_pdb, chain="H", excluded_residue_numbers=set(designed_positions))
    if before.keys() != after.keys():
        raise ValueError("ProteinMPNN threaded PDB changed the fixed framework atom set")
    for key, coordinates in before.items():
        if any(abs(left - right) > 1e-4 for left, right in zip(coordinates, after[key])):
            raise ValueError("ProteinMPNN threaded PDB changed fixed framework backbone coordinates")


def _backbone_intermediate(path: Path, *, resumed: bool) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise ValueError("backbone intermediate is missing or unsafe")
    return {
        "intermediate_id": "rfantibody-backbone-000",
        "design_stage": "backbone_generated",
        "backbone_pdb": path.name,
        "backbone_pdb_sha256": sha256(path),
        "semantic_chain_map": {"heavy": "H", "target": "T"},
        "placeholder_policy": "official_rfdiffusion_backbone_residue_names_are_not_sequence_design_output",
        "placeholder_regions": "official CDR REMARK metadata; do not infer final sequence from residue names",
        "provenance": {"resumed_from_verified_backbone_intermediate": resumed},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", type=Path, required=True); parser.add_argument("--response", type=Path, required=True)
    parser.add_argument("--rfantibody-root", type=Path, required=True); parser.add_argument("--timeout-seconds", type=int, required=True)
    args = parser.parse_args(); response: dict[str, object] = {"schema_version": SCHEMA_VERSION, "status": "failed"}
    try:
        request_path = args.request.resolve(); response_path = args.response.resolve(); work = request_path.parent.resolve()
        if args.request.is_symlink() or args.response.is_symlink() or response_path.parent != work or not work.is_dir():
            raise ValueError("request/response must be regular files in one controlled directory")
        request = read_request(request_path)
        target = work / str(request["target_filename"])
        if target.is_symlink() or not target.is_file() or sha256(target) != request["target_sha256"]:
            raise ValueError("target is not the requested regular file")
        root = args.rfantibody_root.resolve()
        script = root / "scripts" / "rfdiffusion_inference.py"; framework = root / "scripts" / "examples" / "example_inputs" / "h-NbBCII10.pdb"; weights = root / "weights" / "RFdiffusion_Ab.pt"
        if root.is_symlink() or not all(path.is_file() and not path.is_symlink() for path in (script, framework, weights)):
            raise ValueError("official RFantibody files are unavailable")
        resume_name = request.get("resume_backbone_filename")
        resume_hash = request.get("resume_backbone_sha256")
        if (resume_name is None) != (resume_hash is None):
            raise ValueError("resume backbone request is incomplete")
        if resume_name is not None:
            if not isinstance(resume_name, str) or Path(resume_name).name != resume_name or not isinstance(resume_hash, str):
                raise ValueError("resume backbone request is invalid")
            source_backbone = work / resume_name
            if source_backbone.is_symlink() or not source_backbone.is_file() or sha256(source_backbone) != resume_hash:
                raise ValueError("resume backbone hash mismatch")
            _validate_reusable_backbone(source_backbone)
            backbone = work / "backbone_000.pdb"; backbone.write_bytes(source_backbone.read_bytes())
            backbone_stage = {"name": "rfdiffusion_antibody_backbone_design", "status": "reused_verified_intermediate", "output_sha256": sha256(backbone)}
        else:
            output_prefix = work / "rfantibody_backbone"
            command = [sys.executable, str(script), "--config-name", "antibody", f"antibody.target_pdb={target}", f"antibody.framework_pdb={framework}", f"inference.output_prefix={output_prefix}", f"inference.num_designs={request['candidate_count']}", "antibody.design_loops=[H1:7,H2:6,H3:5-13]", f"ppi.hotspot_res=[{','.join(str(item).replace(':', '') for item in request['hotspot_residues'])}]", f"inference.ckpt_override_path={weights}", "diffuser.T=50", "inference.final_step=48", "inference.deterministic=True", "inference.write_trajectory=False"]
            completed = subprocess.run(command, cwd=root, env={"PATH": os.defpath, "LANG":"C.UTF-8", "LC_ALL":"C.UTF-8", "PYTHONNOUSERSITE":"1"}, capture_output=True, text=True, timeout=args.timeout_seconds, shell=False, check=False)
            (work / "rfdiffusion.stdout.log").write_text(sanitize_log(completed.stdout or ""), encoding="utf-8")
            (work / "rfdiffusion.stderr.log").write_text(sanitize_log(completed.stderr or ""), encoding="utf-8")
            if completed.returncode:
                raise RuntimeError(f"RFantibody inference exited {completed.returncode}")
            source_backbone = work / "rfantibody_backbone_0.pdb"
            if source_backbone.is_symlink() or not source_backbone.is_file():
                raise ValueError("RFdiffusion backbone output is missing")
            backbone = work / "backbone_000.pdb"; backbone.write_bytes(source_backbone.read_bytes())
            backbone_stage = {"name": "rfdiffusion_antibody_backbone_design", "status": "succeeded", "output_sha256": sha256(backbone)}
        intermediate = _backbone_intermediate(backbone, resumed=resume_name is not None)
        mpnn_output = work / "proteinmpnn"; mpnn_output.mkdir()
        mpnn = root / "scripts" / "proteinmpnn_interface_design.py"; mpnn_weights = root / "weights" / "ProteinMPNN_v48_noise_0.2.pt"
        if not mpnn.is_file() or mpnn.is_symlink() or not mpnn_weights.is_file() or mpnn_weights.is_symlink():
            raise ValueError("official ProteinMPNN files are unavailable")
        mpnn_input = work / "proteinmpnn_input"; mpnn_input.mkdir(); (mpnn_input / "backbone_000.pdb").write_bytes(backbone.read_bytes())
        mpnn_command = [sys.executable, str(mpnn), "-pdbdir", str(mpnn_input), "-outpdbdir", str(mpnn_output), "-loop_string", "H1,H2,H3", "-seqs_per_struct", str(request["candidate_count"]), "-temperature", "0.1", "-omit_AAs", "CX", "-checkpoint_path", str(mpnn_weights), "-deterministic", "-debug"]
        mpnn_run = subprocess.run(mpnn_command, cwd=root, env={"PATH": os.defpath, "LANG":"C.UTF-8", "LC_ALL":"C.UTF-8", "PYTHONNOUSERSITE":"1"}, capture_output=True, text=True, timeout=args.timeout_seconds, shell=False, check=False)
        (work / "proteinmpnn.stdout.log").write_text(sanitize_log(mpnn_run.stdout or ""), encoding="utf-8")
        (work / "proteinmpnn.stderr.log").write_text(sanitize_log(mpnn_run.stderr or ""), encoding="utf-8")
        if mpnn_run.returncode:
            raise RuntimeError(f"official ProteinMPNN exited {mpnn_run.returncode}")
        sequences, positions = _proteinmpnn_output(mpnn_run.stdout or "", expected_count=int(request["candidate_count"]))
        candidates = []
        for index, (sequence, score) in enumerate(sequences):
            source = mpnn_output / f"backbone_000_dldesign_{index}.pdb"; destination = work / f"candidate_{index:03d}.pdb"; fasta = work / f"candidate_{index:03d}.fasta"
            if source.is_symlink() or not source.is_file():
                raise ValueError("ProteinMPNN threaded PDB is missing")
            threaded_sequence = sequence_and_pdb(source, destination)
            if threaded_sequence != sequence:
                raise ValueError("ProteinMPNN sequence and threaded PDB disagree")
            _validate_fixed_backbone(backbone, source, positions)
            fasta.write_text(f">rfantibody_{index:03d}\n{sequence}\n", encoding="utf-8")
            candidate_metrics = {
                "pipeline_stage": "official_proteinmpnn_sequence_design",
                "proteinmpnn_negative_log_likelihood": score,
                "threaded_pdb_sha256": sha256(source),
                "tool_deterministic_seed": 42,
            }
            candidates.append({"generation_index": index, "pdb_filename": destination.name, "fasta_filename": fasta.name, "sequence": sequence, "designed_residue_count": len(positions), "fixed_residue_count": len(sequence) - len(positions), "native_metrics": candidate_metrics})
        commit = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, check=False, timeout=20, shell=False)
        if commit.returncode or not re.fullmatch(r"[0-9a-f]{40}", commit.stdout.strip()):
            raise ValueError("RFantibody root does not expose one verified Git commit")
        response.update({"status":"succeeded","backend_version":"1.0.0","repo_commit":commit.stdout.strip(),"checkpoints":{"rfdiffusion":"RFdiffusion_Ab.pt","proteinmpnn":"ProteinMPNN_v48_noise_0.2.pt"},"checkpoint_sha256":{"rfdiffusion":sha256(weights),"proteinmpnn":sha256(mpnn_weights)},"intermediate":intermediate,"candidates":candidates,"pipeline_stages":[backbone_stage,{"name":"official_proteinmpnn_sequence_design","status":"succeeded","checkpoint_sha256":sha256(mpnn_weights),"deterministic_seed":42,"temperature":0.1}],"warnings":["official RFantibody requires an explicit supplied VHH framework; this bridge exposes only the verified VHH mode"]})
        write_response(response_path, response); return 0
    except Exception as exc:
        response.update({"error_type":type(exc).__name__,"error_message":str(exc)[:512]})
        try: write_response(args.response, response)
        except Exception: pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Python 3.10-compatible isolated worker for an externally installed IgFold."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import re
import sys
import traceback
from pathlib import Path


SCHEMA_VERSION = 1
AMINO_ACIDS = frozenset("ACDEFGHIKLMNPQRSTVWY")
REQUEST_FIELDS = {
    "schema_version",
    "heavy_chain",
    "light_chain",
    "output_pdb",
    "model_count",
    "do_refine",
    "do_renum",
}
RESPONSE_FIELDS = {
    "schema_version",
    "status",
    "pdb_filename",
    "backend_version",
    "model_count",
    "device",
    "native_metrics",
    "warnings",
    "error_type",
    "error_message",
}
MAX_ERROR_BYTES = 4096
_ANSI_ESCAPE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")


def _bounded_error(error: BaseException) -> str:
    text = _ANSI_ESCAPE.sub("", str(error))
    return text.encode("utf-8", errors="replace")[:MAX_ERROR_BYTES].decode(
        "utf-8", errors="ignore"
    )


def _read_request(path: Path) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise ValueError("request must be a regular file")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or set(payload) != REQUEST_FIELDS:
        raise ValueError("request schema is invalid")
    if payload["schema_version"] != SCHEMA_VERSION:
        raise ValueError("request schema_version is unsupported")
    if payload["model_count"] != 1:
        raise ValueError("worker requires model_count=1")
    if payload["do_refine"] is not False:
        raise ValueError("worker requires do_refine=false")
    if payload["do_renum"] is not False:
        raise ValueError("worker requires do_renum=false")
    for field in ("heavy_chain", "light_chain"):
        value = payload[field]
        if not isinstance(value, str):
            raise ValueError(field + " must be a string")
        sequence = value.strip().upper()
        if not sequence or set(sequence) - AMINO_ACIDS:
            raise ValueError(field + " is not a complete standard amino-acid sequence")
        payload[field] = sequence
    filename = payload["output_pdb"]
    if not isinstance(filename, str) or not filename:
        raise ValueError("output_pdb must be a non-empty relative filename")
    output_path = Path(filename)
    if output_path.is_absolute() or len(output_path.parts) != 1 or output_path.name != filename:
        raise ValueError("output_pdb must not contain a path")
    if output_path.suffix.lower() != ".pdb":
        raise ValueError("output_pdb must use the .pdb suffix")
    return payload


def _device_name(runner: object) -> str:
    try:
        models = getattr(runner, "models")
        return str(next(models[0].parameters()).device)
    except (AttributeError, IndexError, StopIteration, TypeError):
        return "unknown"


def _write_response(path: Path, payload: dict[str, object]) -> None:
    if path.exists() or path.is_symlink():
        raise ValueError("response must be a new regular file")
    if set(payload) - RESPONSE_FIELDS:
        raise ValueError("response contains unsupported fields")
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--response", type=Path, required=True)
    args = parser.parse_args()
    response = {"schema_version": SCHEMA_VERSION, "status": "failed"}
    try:
        request_path = args.request.resolve()
        response_path = args.response.resolve()
        if args.request.is_symlink() or args.response.is_symlink():
            raise ValueError("request and response must not be symbolic links")
        if request_path.parent != response_path.parent:
            raise ValueError("request and response must share one controlled directory")
        work_dir = request_path.parent
        if not work_dir.is_dir() or any(
            path.suffix.lower() == ".pdb" for path in work_dir.iterdir()
        ):
            raise ValueError("worker directory is not a new PDB-free directory")
        request = _read_request(request_path)
        output_path = work_dir / str(request["output_pdb"])
        if output_path.exists() or output_path.is_symlink():
            raise ValueError("worker output PDB already exists")

        from igfold import IgFoldRunner

        runner = IgFoldRunner(num_models=1, try_gpu=True)
        native_output = runner.fold(
            str(output_path),
            sequences={
                "H": str(request["heavy_chain"]),
                "L": str(request["light_chain"]),
            },
            do_refine=False,
            do_renum=False,
        )
        if output_path.is_symlink() or not output_path.is_file() or output_path.stat().st_size == 0:
            raise ValueError("IgFold did not produce a regular non-empty PDB")
        native_metrics = {}
        prmsd = getattr(native_output, "prmsd", None)
        if prmsd is not None:
            native_metrics["prmsd"] = {
                "shape": list(prmsd.shape),
                "source": "IgFold fold return",
            }
        response.update(
            {
                "status": "succeeded",
                "pdb_filename": output_path.name,
                "backend_version": importlib.metadata.version("igfold"),
                "model_count": 1,
                "device": _device_name(runner),
                "native_metrics": native_metrics,
                "warnings": [],
            }
        )
        _write_response(response_path, response)
        return 0
    except Exception as exc:
        response.update(
            {
                "error_type": type(exc).__name__,
                "error_message": _bounded_error(exc),
            }
        )
        try:
            _write_response(args.response, response)
        except Exception:
            pass
        traceback.print_exc(file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

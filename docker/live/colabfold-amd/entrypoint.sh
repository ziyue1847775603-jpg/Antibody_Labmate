#!/usr/bin/env bash
# ColabFold GPU worker entrypoint (AMD/ROCm) — subcommand whitelist only.
# No arbitrary command execution, no eval, no shell string interpolation.
set -euo pipefail

usage() {
    cat <<'EOF'
ColabFold GPU worker (AMD/ROCm) — whitelisted subcommands:

  version
      Print colabfold package version and JAX backend info.

  gpu-check
      Verify GPU visibility (rocm-smi and JAX devices).

  predict INPUT_FASTA OUTPUT_DIR
      Run colabfold_batch with FIXED scientific parameters:
        --msa-mode single_sequence
        --data /models/colabfold
        --model-type alphafold2_multimer_v3
        --num-models 1
        --num-recycle 1
        --num-relax 0
        --random-seed 0
        --disable-unified-memory
        --compile-mode fast
      INPUT_FASTA must be a single basename under /work/input.
      OUTPUT_DIR must be a single basename under /work/output.
      The FASTA must contain exactly one VH:VL pair (two chains).
      No scientific parameter may be overridden by the caller.

All output is written to /work/output/<OUTPUT_DIR>.  Exit codes are
passed through.  No network access is used (single_sequence mode).
EOF
}

die() {
    echo "[colabfold-worker-amd] ERROR: $*" >&2
    exit 1
}

require_file() {
    local path="$1" label="$2"
    if [[ ! -f "$path" ]]; then
        die "${label} not found: ${path}"
    fi
}

validate_basename() {
    local name="$1" label="$2"
    if [[ -z "$name" ]]; then
        die "${label} must not be empty"
    fi
    if [[ "$name" =~ [/\\] ]]; then
        die "${label} must be a single basename (no path separators), got: ${name}"
    fi
    if [[ "$name" =~ ^- ]]; then
        die "${label} must not start with a dash, got: ${name}"
    fi
    if [[ "$name" =~ \.\. ]]; then
        die "${label} must not contain '..', got: ${name}"
    fi
    if [[ "$name" =~ [^[:print:]] ]]; then
        die "${label} contains non-printable characters"
    fi
    if [[ "${#name}" -gt 128 ]]; then
        die "${label} exceeds 128 characters"
    fi
    # Reject symlinks in the input area
    if [[ -L "/work/input/${name}" ]]; then
        die "${label} must not be a symbolic link"
    fi
}

# Validate FASTA: exactly one record, exactly one ':' separator (VH:VL),
# standard amino acids only, no empty chains.
validate_fasta() {
    local path="$1"
    local total_bytes
    total_bytes=$(stat -c %s "$path" 2>/dev/null || stat -f %z "$path")
    if (( total_bytes > 20000 )); then
        die "FASTA exceeds 20 KB size limit"
    fi
    local header="" seq=""
    while IFS= read -r line || [[ -n "$line" ]]; do
        line=$(printf '%s' "$line" | tr -d '\r')
        [[ -z "$line" ]] && continue
        if [[ "$line" == ">"* ]]; then
            if [[ -n "$header" ]]; then
                die "FASTA must contain exactly one record"
            fi
            header="$line"
        else
            seq="${seq}${line}"
        fi
    done < "$path"
    [[ -n "$header" ]] || die "FASTA has no header"
    [[ "$header" == ">"* ]] || die "FASTA header must start with '>'"

    if [[ "$seq" != *:* ]]; then
        die "FASTA must contain a ':' separator (VH:VL)"
    fi
    local vh="${seq%%:*}"
    local vl=""
    local rest="${seq#*:}"
    if [[ "$rest" == *:* ]]; then
        die "FASTA must contain exactly one ':' separator (VH:VL)"
    fi
    vl="$rest"
    [[ -n "$vh" ]] || die "VH chain must not be empty"
    [[ -n "$vl" ]] || die "VL chain must not be empty"

    if [[ ! "$vh" =~ ^[ACDEFGHIKLMNPQRSTVWY]+$ ]]; then
        die "VH chain contains non-standard amino acids"
    fi
    if [[ ! "$vl" =~ ^[ACDEFGHIKLMNPQRSTVWY]+$ ]]; then
        die "VL chain contains non-standard amino acids"
    fi
}

# ---- subcommand: version ----
cmd_version() {
    if [[ $# -ne 0 ]]; then
        die "version takes no arguments"
    fi
    python -c "from importlib.metadata import version; print('colabfold', version('colabfold'))" 2>&1 || true
    python -c "import jax; print('jax', jax.__version__, 'backend', jax.default_backend())" 2>&1 || true
}

# ---- subcommand: gpu-check ----
cmd_gpu_check() {
    if [[ $# -ne 0 ]]; then
        die "gpu-check takes no arguments"
    fi
    # ROCm tools: check with rocm-smi (AMD) instead of nvidia-smi
    if ! command -v rocm-smi >/dev/null 2>&1; then
        die "rocm-smi not found; AMD GPU not visible in container"
    fi
    rocm-smi --showproductname 2>&1 || die "rocm-smi failed"
    python -c "import jax; devs = jax.devices(); assert devs and devs[0].platform in ('gpu','rocm'), 'JAX ROCm/GPU device not found'; print('jax device:', devs[0])" 2>&1 || die "JAX GPU check failed"
}

# ---- subcommand: predict ----
cmd_predict() {
    if [[ $# -ne 2 ]]; then
        die "predict requires exactly 2 positional arguments: INPUT_FASTA OUTPUT_DIR"
    fi
    local fasta_name="$1" output_name="$2"
    validate_basename "$fasta_name" "input FASTA"
    validate_basename "$output_name" "output dir"

    local fasta="/work/input/${fasta_name}"
    local output="/work/output/${output_name}"
    require_file "$fasta" "input FASTA"

    validate_fasta "$fasta"

    if [[ -e "$output" ]]; then
        die "output directory already exists: ${output_name}"
    fi
    mkdir -p "$output"

    # FIXED scientific parameters — no caller overrides possible.
    exec colabfold_batch \
        "$fasta" \
        "$output" \
        --msa-mode single_sequence \
        --data /models/colabfold \
        --model-type alphafold2_multimer_v3 \
        --num-models 1 \
        --num-recycle 1 \
        --num-relax 0 \
        --random-seed 0 \
        --disable-unified-memory \
        --compile-mode fast
}

# ---- main dispatcher ----
if [[ $# -eq 0 ]]; then
    usage
    exit 1
fi

SUBCMD="$1"
shift

case "$SUBCMD" in
    version)
        cmd_version "$@"
        ;;
    gpu-check)
        cmd_gpu_check "$@"
        ;;
    predict)
        cmd_predict "$@"
        ;;
    -h|--help|help)
        usage
        ;;
    *)
        die "unknown subcommand: ${SUBCMD}"
        ;;
esac

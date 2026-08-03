#!/usr/bin/env bash
# LightDock worker entrypoint — subcommand whitelist only.
# No arbitrary command execution, no eval, no shell string interpolation.
set -euo pipefail

usage() {
    cat <<'EOF'
LightDock worker — whitelisted subcommands:

  version
      Print lightdock package version.

  setup RECEPTOR LIGAND -s SWARMS -g GLOWWORMS [--noxt] [--noh] [--now]
      Run lightdock3_setup.py inside /work/outputs.
      RECEPTOR and LIGAND are basenames resolved under /work/inputs.
      -s SWARMS    positive integer (1..64)
      -g GLOWWORMS positive integer (1..1000)

  run STEPS [-c CORES]
      Run lightdock3.py inside /work/outputs using setup.json.
      STEPS positive integer (1..10000)
      -c CORES positive integer (1..64, default 1)

  generate RECEPTOR LIGAND GSO_FILE COUNT
      Run lgd_generate_conformations.py inside /work/outputs.
      RECEPTOR and LIGAND basenames resolved under /work/inputs.
      GSO_FILE basename resolved under /work/outputs.
      COUNT positive integer (1..1000)

All output is written to /work/outputs.  Exit codes are passed through.
EOF
}

die() {
    echo "[lightdock-worker] ERROR: $*" >&2
    exit 1
}

require_file() {
    local path="$1" label="$2"
    if [[ ! -f "$path" ]]; then
        die "${label} not found: ${path}"
    fi
}

# ---- basename validation: reject anything with slashes, backslashes,
#      null bytes, leading dashes, or empty strings ----------------
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
    # Also reject control characters and anything outside printable ASCII
    if [[ "$name" =~ [^[:print:]] ]]; then
        die "${label} contains non-printable characters"
    fi
}

validate_positive_int() {
    local value="$1" label="$2" max="$3"
    if [[ ! "$value" =~ ^[1-9][0-9]*$ ]]; then
        die "${label} must be a positive integer, got: ${value}"
    fi
    if (( value > max )); then
        die "${label} exceeds maximum ${max}, got: ${value}"
    fi
}

# ---- subcommand: version ----
cmd_version() {
    if [[ $# -ne 0 ]]; then
        die "version takes no arguments"
    fi
    python -c "from importlib.metadata import version; print(version('lightdock'))"
}

# ---- subcommand: setup ----
cmd_setup() {
    # Parse: setup RECEPTOR LIGAND -s SWARMS -g GLOWWORMS [--noxt] [--noh] [--now]
    local receptor_name="" ligand_name=""
    local swarms="" glowworms=""
    local noxt="" noh="" now=""

    while [[ $# -gt 0 ]]; do
        case "$1" in
            -s)
                [[ $# -ge 2 ]] || die "-s requires a value"
                swarms="$2"; shift 2
                ;;
            -g)
                [[ $# -ge 2 ]] || die "-g requires a value"
                glowworms="$2"; shift 2
                ;;
            --noxt)
                noxt=1; shift
                ;;
            --noh)
                noh=1; shift
                ;;
            --now)
                now=1; shift
                ;;
            -*)
                die "unknown option: $1"
                ;;
            *)
                if [[ -z "$receptor_name" ]]; then
                    receptor_name="$1"
                elif [[ -z "$ligand_name" ]]; then
                    ligand_name="$1"
                else
                    die "unexpected positional argument: $1"
                fi
                shift
                ;;
        esac
    done

    [[ -n "$receptor_name" ]] || die "receptor basename is required"
    [[ -n "$ligand_name" ]]   || die "ligand basename is required"
    [[ -n "$swarms" ]]        || die "-s (swarms) is required"
    [[ -n "$glowworms" ]]     || die "-g (glowworms) is required"

    validate_basename "$receptor_name" "receptor"
    validate_basename "$ligand_name" "ligand"
    validate_positive_int "$swarms" "swarms" 64
    validate_positive_int "$glowworms" "glowworms" 1000

    local receptor="/work/inputs/${receptor_name}"
    local ligand="/work/inputs/${ligand_name}"
    require_file "$receptor" "receptor PDB"
    require_file "$ligand" "ligand PDB"

    local opts=()
    [[ -n "$noxt" ]] && opts+=("--noxt")
    [[ -n "$noh" ]]  && opts+=("--noh")
    [[ -n "$now" ]]  && opts+=("--now")

    cd /work/outputs
    exec lightdock3_setup.py "$receptor" "$ligand" -s "$swarms" -g "$glowworms" "${opts[@]}"
}

# ---- subcommand: run ----
cmd_run() {
    # Parse: run STEPS [-c CORES]
    if [[ $# -lt 1 ]]; then
        die "run requires STEPS"
    fi
    local steps="$1"; shift
    validate_positive_int "$steps" "steps" 10000

    local cores=1
    while [[ $# -gt 0 ]]; do
        case "$1" in
            -c)
                [[ $# -ge 2 ]] || die "-c requires a value"
                cores="$2"; shift 2
                ;;
            -*)
                die "unknown option: $1"
                ;;
            *)
                die "unexpected positional argument: $1"
                ;;
        esac
    done
    validate_positive_int "$cores" "cores" 64

    cd /work/outputs
    require_file "setup.json" "LightDock setup.json"
    exec lightdock3.py setup.json "$steps" -c "$cores"
}

# ---- subcommand: generate ----
cmd_generate() {
    # Parse: generate RECEPTOR LIGAND GSO_FILE COUNT
    if [[ $# -ne 4 ]]; then
        die "generate requires exactly 4 positional arguments: RECEPTOR LIGAND GSO_FILE COUNT"
    fi
    local receptor_name="$1" ligand_name="$2" gso_name="$3" count="$4"

    validate_basename "$receptor_name" "receptor"
    validate_basename "$ligand_name" "ligand"
    validate_basename "$gso_name" "gso file"
    validate_positive_int "$count" "pose count" 1000

    local receptor="/work/inputs/${receptor_name}"
    local ligand="/work/inputs/${ligand_name}"
    local gso="/work/outputs/${gso_name}"
    require_file "$receptor" "receptor PDB"
    require_file "$ligand" "ligand PDB"
    require_file "$gso" "selected GSO file"

    cd /work/outputs
    exec lgd_generate_conformations.py "$receptor" "$ligand" "$gso" "$count"
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
    setup)
        cmd_setup "$@"
        ;;
    run)
        cmd_run "$@"
        ;;
    generate)
        cmd_generate "$@"
        ;;
    -h|--help|help)
        usage
        ;;
    *)
        die "unknown subcommand: ${SUBCMD}"
        ;;
esac

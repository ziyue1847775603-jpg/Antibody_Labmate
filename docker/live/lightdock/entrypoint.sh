#!/usr/bin/env bash
# LightDock worker entrypoint — subcommand whitelist only.
# No arbitrary command execution, no eval, no shell string interpolation.
set -euo pipefail

usage() {
    cat <<'EOF'
LightDock worker — whitelisted subcommands:

  version
      Print lightdock package version.

  setup RECEPTOR LIGAND [--swarms N] [--glowworms N] [--noxt] [--noh] [--now]
      Run lightdock3_setup.py inside /work/outputs.
      RECEPTOR and LIGAND are basenames resolved under /work/inputs.

  run STEPS [--cores N]
      Run lightdock3.py inside /work/outputs using setup.json.

  generate RECEPTOR LIGAND GSO_FILE COUNT
      Run lgd_generate_conformations.py inside /work/outputs.

All subcommands write output to /work/outputs and read input PDBs from
/work/inputs.  Exit codes are passed through unmodified.
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

# ---- subcommand: version ----
cmd_version() {
    python -c "from importlib.metadata import version; print(version('lightdock'))"
}

# ---- subcommand: setup ----
cmd_setup() {
    local receptor_name="$1" ligand_name="$2"
    local receptor="/work/inputs/${receptor_name}"
    local ligand="/work/inputs/${ligand_name}"
    require_file "$receptor" "receptor PDB"
    require_file "$ligand" "ligand PDB"

    # Validate basenames — no path traversal
    if [[ "$(basename "$receptor_name")" != "$receptor_name" ]]; then
        die "receptor must be a single basename, got: ${receptor_name}"
    fi
    if [[ "$(basename "$ligand_name")" != "$ligand_name" ]]; then
        die "ligand must be a single basename, got: ${ligand_name}"
    fi

    shift 2
    cd /work/outputs
    exec lightdock3_setup.py "$receptor" "$ligand" "$@"
}

# ---- subcommand: run ----
cmd_run() {
    local steps="$1"
    if [[ ! "$steps" =~ ^[0-9]+$ ]]; then
        die "steps must be a positive integer, got: ${steps}"
    fi
    shift
    cd /work/outputs
    require_file "setup.json" "LightDock setup.json"
    exec lightdock3.py setup.json "$steps" "$@"
}

# ---- subcommand: generate ----
cmd_generate() {
    local receptor_name="$1" ligand_name="$2" gso_name="$3" count="$4"
    local receptor="/work/inputs/${receptor_name}"
    local ligand="/work/inputs/${ligand_name}"
    local gso="/work/outputs/${gso_name}"
    require_file "$receptor" "receptor PDB"
    require_file "$ligand" "ligand PDB"
    require_file "$gso" "selected GSO file"

    if [[ "$(basename "$receptor_name")" != "$receptor_name" ]]; then
        die "receptor must be a single basename, got: ${receptor_name}"
    fi
    if [[ "$(basename "$ligand_name")" != "$ligand_name" ]]; then
        die "ligand must be a single basename, got: ${ligand_name}"
    fi
    if [[ "$(basename "$gso_name")" != "$gso_name" ]]; then
        die "gso file must be a single basename, got: ${gso_name}"
    fi
    if [[ ! "$count" =~ ^[0-9]+$ ]]; then
        die "count must be a positive integer, got: ${count}"
    fi

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
        if [[ $# -lt 2 ]]; then
            die "setup requires RECEPTOR LIGAND [options]"
        fi
        cmd_setup "$@"
        ;;
    run)
        if [[ $# -lt 1 ]]; then
            die "run requires STEPS [options]"
        fi
        cmd_run "$@"
        ;;
    generate)
        if [[ $# -lt 4 ]]; then
            die "generate requires RECEPTOR LIGAND GSO_FILE COUNT"
        fi
        cmd_generate "$@"
        ;;
    -h|--help|help)
        usage
        ;;
    *)
        die "unknown subcommand: ${SUBCMD}\n$(usage)"
        ;;
esac

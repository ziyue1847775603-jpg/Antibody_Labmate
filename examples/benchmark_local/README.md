# Benchmark Local example

This directory contains only project-authored CC0 synthetic coordinates with no
biological meaning. The small N/CA/C/O structures are large enough for
LightDock's surface selection and exist only as software-integration inputs;
they are not claimed LightDock results.

Copy the directory before use. Set `rights_confirmed` to `true` only after
confirming rights to every input and external program, replace the four
executable paths with explicit local paths, and declare the score name and
direction from the scoring function documentation:

`$LIGHTDOCK_ROOT` in `project.json` is a documentation placeholder, not an
environment variable expanded by Antibody Labmate. Replace it with the
absolute root of your separately installed LightDock environment before
running the example.

```bash
labmate run project.json --mode benchmark_local
```

`antibody_chain_mapping` and `antigen_chain_mapping` map input PDB chain IDs to
normalized docking IDs. VH/VL must target `H` and `L`; VHH uses only `H`.
Antigen targets must be unique and must not overlap `H`/`L`. A reference mapping
must cover exactly the same normalized chains.

All paths in the project file are local. Input paths and `output_dir` are safe
relative paths under this project directory. URLs and automatic downloads are
rejected. The mode skips ColabFold and performs no network operation.

The template records `random_seed`, but LightDock 0.9.4 has no uniform seed
option across the three commands used here. Therefore
`random_seed_recording=manifest_only_external_lightdock_cli` is an explicit
limitation, not a claim of deterministic external execution.

The cluster executable is explicitly checked but not invoked. Poses are ranked
from the declared raw LightDock score and mapped directly from selected GSO row
order; clustering is not allowed to silently replace that order.

A real LightDock 0.9.4 synthetic integration smoke is recorded in
`BENCHMARK_LOCAL_VALIDATION.md`. Every result remains
`implemented_unverified` until real scientific benchmark validation is
completed.

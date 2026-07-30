# Local docking execution

`labmate dock` consumes a previously validated `DockingInput` JSON. It does
not repeat prediction and it does not combine prediction-native metrics with
LightDock scores. The receptor and ligand roles are explicit in that JSON;
the current recorded smoke uses the fixture antigen as receptor and the
validated antibody structure as ligand.

For LightDock 0.9.x, users must explicitly supply the separately installed
`lightdock3_setup.py`, `lightdock3.py`, and
`lgd_generate_conformations.py` executables. Labmate does not distribute
LightDock, its GPL-3.0 code, weights, databases, or an execution environment.
The Replay Docker image does not include any docking executable.

The executor uses a fresh output directory, verifies input SHA-256 values,
copies inputs without modifying originals, invokes setup, sampling, and
conformation generation using argument lists with `shell=False`, and writes a
run-relative `docking_manifest.json`. It fails on timeouts, non-zero exits,
unsafe paths, invalid GSO rows, or absent/invalid pose output.

The selected output is a tool-ranked pose: its `fastdfire` value is a native
LightDock score, not affinity, binding energy, or a cross-backend confidence
score. A fixture smoke only validates command construction, output discovery,
and pose-file checks. It is not a DB5.5 benchmark, scientific docking
validation, epitope validation, experimental validation, or a therapeutic
claim.

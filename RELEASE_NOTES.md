# Release Notes

## v0.2.0 — Phase 2a Live Local (2026-07-27)

- Added a CLI-only `--mode live_local` execution path for user-installed ColabFold and LightDock commands.
- Added paired VH/VL FASTA plus exact region CSV input validation, PDB chain normalization, command logs, local interface analysis, ranking, HTML report, provenance manifest, and an input template.
- Completed and independently audited a one-candidate WSL2 end-to-end smoke run with ColabFold 1.6.2 (`single_sequence`, preinstalled multimer-v3 weights) and separately installed LightDock 0.9.4. The bounded software-integration status is `verified_live`; exact evidence and limitations are in `LIVE_LOCAL_VALIDATION.md`.
- Added fail-closed network/model policy, exact VH/VL chain and residue mapping, PDB B-factor/score-JSON pLDDT cross-checks, explicit global GSO row-to-pose mapping, all-selected-pose interface analysis, metadata redaction, privacy auditing, and real-format regression tests.
- LightDock remains an external GPL-3.0 program and is not bundled; the application did not use a public MSA service or download model weights in the validation run.
- Streamlit Community Cloud remains Replay-only; Live Remote remains unavailable.

## v0.1.1 — Submission Hardening (2026-07-19)

> **REPLAY ONLY · FIXED HASH-VERIFIED DEMO · NOT LIVE COMPUTE**

This release hardens the Phase 1 Replay MVP for judging and public-source
delivery. It does not add or enable Live Local, Live Remote, IgCraft,
ColabFold, LightDock execution, PyMOL, or any other scientific provider.

### Delivery improvements

- Added an activation-free Windows 10/11 installation path for Python 3.11.
- Added a runtime-only dependency lock and root `requirements.txt` for
  Streamlit Community Cloud.
- Added a minimal `.streamlit/config.toml` with bounded uploads, CORS/XSRF
  protections, hidden browser error details, and disabled usage telemetry.
- Hardened source ZIP creation against caches, virtual environments, Git
  metadata, nested ZIPs, symlinks, secret-bearing filenames, high-confidence
  credential patterns, and local absolute-path disclosure.
- Added archive-entry and source-checksum verification.
- Added deployment, demo, Devpost, audit, and release documentation.
- Added submission-hardening tests covering packaging, deployment contracts,
  cross-platform paths, persistent REPLAY labeling, and output privacy.

### Scientific behavior

Unchanged. The synthetic fixture, CDR and PDB validation, interface geometry,
ranking formula, fixed output parsing, ReplayBackend state machine, golden
outputs, and hash rejection rules are unchanged from v0.1.0.

### Verification

The final verification record is in `SUBMISSION_AUDIT.md`. The release archive
is rebuilt from source after the full Python 3.11 test suite and startup smoke
test pass.

### Known limits

- Only the hash-exact bundled synthetic fixture can complete.
- LightDock is a Replay-only provider contract; `dock()` remains unavailable.
- No real antibody generation, structure prediction, docking, PyMOL rendering,
  remote worker, persistence, authentication, or confidential-data workflow is
  included.
- Scores are synthetic software-test values and do not establish binding,
  affinity, specificity, safety, or therapeutic effect.

# Release Notes

## Unreleased

Placeholder for changes after v0.4.0.

## v0.4.0 — Docker Compose Live Local (2026-08-03)

### Docker Compose Live Local

- Added an explicit `docker_compose` tool-execution provider for Live Local:
  the host Labmate Python 3.11 CLI orchestrates isolated worker containers
  (ColabFold GPU + LightDock CPU) through fixed CLI commands, exit codes, and
  shared work volumes. The default provider remains `host`; `docker_compose`
  is explicit opt-in only (`--tool-execution-provider docker_compose`), with
  no auto-detection and no silent fallback.
- End-to-end chain:
  `host Labmate orchestrator -> ColabFold GPU container -> LightDock CPU
  container -> host-side validation / analysis / ranking / report / manifest /
  ZIP`.
- The Labmate orchestrator is not containerized; the public Streamlit app
  remains Replay-only; no Docker socket is exposed to any web container.
- Each run and each candidate uses isolated work directories; the ColabFold
  rank-1 PDB passes the existing strict chain-mapping / exact-sequence checks
  before becoming the LightDock ligand input.
- Manifest records `tool_execution_provider`, worker versions, network and
  model-data policies, per-stage status, and artifact hashes; host paths,
  usernames, tokens, and environment dumps are never recorded.

### ColabFold GPU worker

- Isolated ColabFold 1.6.2 GPU worker based on the official
  `ghcr.io/sokrypton/colabfold:1.6.2-cuda13` image (digest pinned). JAX GPU
  backend; runtime `network_mode: none`; `single_sequence` MSA; fixed
  `alphafold2_multimer_v3` parameters identical to the verified host backend.
- Model weights are user-supplied preinstalled multimer-v3 files mounted
  read-only; nothing is written into the image and no public MSA service or
  model download occurs.
- Entrypoint whitelist (`version` / `gpu-check` / `predict`) with fail-closed
  validation: single-record VH:VL FASTA, standard amino acids, exactly one
  `:` separator, no third chain, no symlinks, no caller override of scientific
  parameters, strict output-dir contract (single-level subdirectory of the
  mounted output root, non-empty/stale output rejected).
- The rank-1 score JSON is matched exactly by prefix/rank/model tag, copied
  into the formal run artifacts, and included in the manifest and ZIP.

### LightDock worker

- Isolated LightDock 0.9.4 CPU worker (GPL-3.0, separately licensed; see the
  per-image third-party notices). Non-root user, read-only root filesystem,
  whitelisted entrypoint (`version` / `setup` / `run` / `generate`), fixed
  CLI parameters, and GPL notice retained in the image.

### Prediction backends

- Added a provider-neutral `PredictionBackend` / `PredictionResult` contract
  and registry with `replay`, `colabfold`, and `igfold` providers.
- Preserved the complete Replay workflow, strict fixture/input hash checks,
  deterministic outputs, and existing ranking/reporting contracts.
- Added prediction-only local wrappers for user-installed ColabFold and
  IgFold environments. They do not download or bundle source, model weights,
  databases, or third-party executables.
- Added backend selection to the CLI and explanatory selection to Streamlit.
  The web application remains Replay-only and never silently falls back from
  a selected local engine to Replay.
- Added a Python 3.11 Replay Docker deployment. The image deliberately excludes
  ColabFold, IgFold, LightDock, model weights, databases, user uploads, and
  runtime outputs.

### Security and provenance hardening

- Fixed a host-mode regression where `container_versions` was only assigned
  inside the docker_compose branch (host path previously raised NameError);
  the host Live Local path now fails closed with a clear tool-missing error.
- Split model-data validation by provider: host mode validates the
  `--data` path in `job.tools.colabfold_args`; docker mode validates only the
  mounted docker data root, with no fallback to host paths. Manifest
  `model_data_policy` records `preinstalled_only` (host) or
  `user_mounted_preinstalled_only` (docker).
- Rank-1 score JSON is a formal run artifact (S04 hashes, manifest, ZIP);
  missing, ambiguous, or invalid score JSON fails closed.
- FASTA without a `:` separator fails closed in the container entrypoint.
- Hardened prediction output discovery against symbolic links and
  out-of-directory PDBs, bounded stdout/stderr metadata while retaining
  path-redacted logs, surfaced recovered GPU allocation warnings, and changed
  concrete backend package exports to lazy loading to prevent fresh-process
  workflow import cycles.

### Real software-integration validation

- D1: LightDock 0.9.4 CPU worker container verified (setup/run/generate,
  non-root, read-only rootfs, real fixture smoke).
- D3: ColabFold 1.6.2 GPU worker container verified on an NVIDIA RTX 5070 Ti
  (12,227 MiB): `version` / `gpu-check` / `predict` with exact VH/VL sequence
  match and `network_mode: none`.
- D4: Docker Compose Live Local verified end to end with a host orchestrator
  plus containerized ColabFold/LightDock workers on one CC0 synthetic
  candidate (final run `RUN-20260803-121251-784e9fd5`, all stages succeeded).
- One real, host-side WSL2 ColabFold 1.6.2 prediction-only smoke using a
  single VH/VL pair, preinstalled weights, one model, one recycle, and no
  relaxation. It produced one non-empty two-chain PDB through the new wrapper.
- One real local IgFold 0.4.0 prediction-only smoke through an explicit
  external-interpreter bridge: the Python 3.11 Labmate process invoked an
  isolated Python 3.10 legacy worker, which produced a non-empty H/L-chain PDB
  with exact input-sequence preservation.
- All of the above are bounded local software-integration evidence only; they
  are not scientific, docking, benchmark, production, Docker-GPU (beyond the
  recorded D3/D4 scope), remote-worker, or experimental validation.

### Compatibility

- Default `host` Live Local behavior is unchanged from v0.3.0; existing
  project files remain fully compatible.
- Replay, Benchmark Local, and the RFantibody design CLI are unaffected.
- The Replay-only `docker-compose.yml` is unchanged; Live Local containers
  live in the separate `docker-compose.live-local.yml`.

### Known limitations

- Docker Compose Live Local `verified_live` covers only the recorded software
  versions, this single-machine environment, the synthetic/CC0 smoke inputs,
  the fixed parameters, and the software-integration scope.
- D5 third-party-machine reproduction is not completed and is future work.
- Not included: RFantibody container, RF2, IgCraft integration, Live Remote,
  public Streamlit compute, production deployment, scientific benchmark
  validation, docking-accuracy validation, binder validation, affinity or
  binding free-energy prediction, therapeutic validity, experimental
  validation.

## v0.3.0 — Benchmark Local (2026-07-28)

### Local docking execution adapter

- Added an explicit, local-only LightDock execution handoff for validated
  `DockingInput` JSON. It runs the user-supplied 0.9.x setup, sampling and
  conformation executables with bounded subprocesses and run-relative
  provenance. It remains separate from Replay ranking and prediction-native
  metrics.
- One minimal public-fixture LightDock 0.9.4 engineering smoke completed with
  an IgFold prediction artifact as ligand. This verifies software integration,
  not pose correctness, affinity, epitope, DB5.5 performance, or experiments.

### Benchmark metrics and cross-swarm provenance

- Added a separate `capri_dockq_2016_v1` implementation of Fnat, interface
  RMSD and ligand RMSD plus the traditional CAPRI four-category criteria.
  The legacy `compute_reference_metrics` implementation and all existing
  Replay/Live Local ranking behavior remain unchanged.
- Cross-validated Fnat/I-RMSD/L-RMSD against official DockQ v2.1.3
  (`d9cbb1940bb0f42db3257f7da3b0e96f162b94d9`) on five synthetic cases and
  its official 1A2K example. This validates implementation agreement only; it
  is not a public scientific benchmark.
- Extended the independent LightDock executor to collect all current-run
  `swarm_<id>` outputs and derive `global_tool_score_rank` from one native
  scoring function with deterministic swarm/row tie breaks. LightDock does
  not supply this cross-swarm global rank, and Labmate does not describe it as
  one. Failed and duplicate poses retain their original derived rank.
- Added a frozen benchmark run configuration and tool-ranked top-1/top-5/
  top-10 aggregation with a separately labelled reference-selected oracle.
  No DB5.5 data or public benchmark result is bundled.
- Ran and froze one 1AHW local docking engineering pilot with 10 swarms and
  10 validated tool-ranked poses after an earlier bounded timeout. Its rank-1
  Labmate grouped CAPRI result was `incorrect`. DockQ v2.1.3 pairwise outputs
  are retained only as diagnostics: its chain-group conversion changes the
  receptor/ligand semantic L-RMSD for this conventional H/L case. Therefore no
  rank-2–10 evaluation, top-k result, oracle, benchmark success rate, affinity,
  or general-performance claim is emitted.

### RFantibody sequence-design workflow

- Added a local-only external-interpreter bridge for the official RFantibody
  VHH sequence workflow. It retains RFdiffusion output only as a
  `backbone_generated` intermediate and requires official ProteinMPNN output,
  sequence threading, exact FASTA/PDB agreement, finite-coordinate checks and
  fixed-framework backbone validation before a candidate is prediction-ready.
- The bridge records RFdiffusion and ProteinMPNN checkpoint provenance,
  controlled candidate FASTA/PDB paths and unscaled ProteinMPNN negative
  log-likelihood. It does not create affinity, binder, therapeutic, unified
  quality, or cross-stage scores.
- RFantibody and ProteinMPNN remain external user-managed software; no source,
  environment, checkpoint, cache, or generated candidate is distributed.
- Completed one local VHH engineering handoff from a sequence-validated
  RFantibody/ProteinMPNN candidate through offline ColabFold and independent
  LightDock execution. The resulting ten tool-ranked poses verify engineering
  provenance and output validation only; no binder, affinity, epitope, or
  experimental-validation claim is made.

### Input-contract hardening (uncommitted branch)

- Clarified that six CDR strings are only a fixed Replay demonstration input;
  they do not generate complete VH/VL during local computation.
- Live Local requires complete VH/VL FASTA plus region annotations and antigen;
  the modular path requires complete VH/VL or a validated PredictionArtifact.
- IgCraft was audited but not integrated because its available grafting API
  requires a complete antibody PDB rather than six CDR strings. No reference
  framework or substitute generator is used to bridge that mismatch.

- Replay remains the stable hash-exact synthetic demonstration mode.
- Live Local remains the previously validated one-candidate synthetic WSL2
  software-integration configuration. Its bounded `verified_live` label does
  not extend to other tools, configurations, performance, or scientific
  validity.
- Added CLI-only `benchmark_local`, which skips ColabFold and accepts existing
  antibody and antigen PDB structures plus an optional reference complex. It
  supports VH/VL, VHH, multiple antigen chains, explicit chain mappings, pose
  ranking, interface residues, optional reference metrics, Top 1/5/10
  summaries, self-contained offline HTML, manifests, and run ZIPs.
- A real external LightDock 0.9.4 CC0 synthetic software-integration smoke
  completed successfully. LightDock remains a separately installed GPL-3.0
  tool and is not bundled.
- Benchmark Local remains `implemented_unverified`: no DB5.5 or other real
  scientific benchmark, Schrödinger/PIPER comparison, ranking-quality study,
  affinity claim, or experimental validation has been completed.
- Live Remote remains unavailable and is not implemented.
- All workflow results remain computational artifacts only; they do not prove
  binding, affinity, binding free energy, specificity, safety, efficacy, or
  experimental outcomes.

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

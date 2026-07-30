# Phase 2a Live Local validation

- Date: 2026-07-27
- Final status: **`verified_live` (bounded software-integration scope)**

`verified_live` means that the exact local pipeline and configuration below
completed with real ColabFold and LightDock executions and passed independent
artifact checks. It does **not** validate binding, affinity, binding free
energy, specificity, safety, efficacy, developability, or any experimental
conclusion.

## Source and repository state

- Supplied source ZIP SHA-256:
  `d844c41975b37bc7603e0179e1d12a7916c4e8ef97da4ddd796492989d90f8e7`
- The SHA matched before extraction. All 100 archive entries passed the safe
  path check, and the original ZIP was not modified.
- The extracted source did not contain Git metadata. The workspace `.git`
  directory contained no valid repository metadata, so a truthful `git
  status` was not available. No user Git changes were overwritten or deleted.
- The project version after validation is `0.2.0`.

## Machine and external tools

| Item | Observed value |
|---|---|
| Host | Windows 11 24H2, build 26100 |
| WSL | WSL2, Ubuntu 26.04, kernel 6.18.33.2 |
| GPU | NVIDIA GeForce RTX 5070 Ti Laptop GPU, 12,227 MiB |
| NVIDIA driver / WSL CUDA report | 591.91 / CUDA 13.1 |
| Project Python | 3.11.15 |
| Conda | 26.5.3 |
| ColabFold | 1.6.2 (`alphafold-colabfold` 2.3.18) |
| LightDock | 0.9.4, GPL-3.0, separately installed |
| PyMOL | Not found; `skipped_optional` |

For this public record, `$PROJECT_ROOT` denotes the repository root,
`$COLABFOLD_ROOT` the separately installed ColabFold environment,
`$LIGHTDOCK_ROOT` the separately installed LightDock environment,
`$COLABFOLD_MODEL_ROOT` the preinstalled model-data directory, and
`$LIVE_LOCAL_SMOKE_ROOT` / `$RUNS_ROOT` the external input/output locations.
The real executable locations, normalized only to remove machine-specific
directory prefixes, were:

```text
$COLABFOLD_ROOT/bin/colabfold_batch
$LIGHTDOCK_ROOT/bin/lightdock3_setup.py
$LIGHTDOCK_ROOT/bin/lightdock3.py
$LIGHTDOCK_ROOT/bin/lgd_generate_conformations.py
```

The LightDock environment is outside the MIT source tree and is excluded from
the release ZIP. No LightDock source, binary, environment, or dependency is
bundled with Antibody Labmate.

## MSA and model-network decision

The installed ColabFold default is `mmseqs2_uniref_env` with
`https://api.colabfold.com`; installed code contains the HTTP POST path that
would submit a query sequence. That default was inspected but **never run**.

Every executed smoke run instead used:

```text
--msa-mode single_sequence
--data $COLABFOLD_MODEL_ROOT
--model-type alphafold2_multimer_v3
--num-models 1
--num-recycle 1
--disable-unified-memory
--compile-mode fast
```

The application verified all five multimer-v3 parameter files before starting.
It did not download models. The resulting ColabFold `config.json` retains the
program's unused default `host_url` field, but `msa_mode` is
`single_sequence`, the A3M contains only the two input chains, the log contains
no MSA query stage, and no public MSA service was used. No sequence was
uploaded by this application.

## Synthetic smoke input and parameters

The input is project-authored deterministic synthetic data under CC0-1.0. It
does not contain a patent example, confidential sequence, IgCraft output, or a
Replay calculation presented as Live output.

| Input | SHA-256 |
|---|---|
| Complete VH/VL FASTA | `4411041490ae514ccbf71a8959135b9d9de5bd32653bb6d0fc12774354742d68` |
| Region CSV | `c9ee134179fc8de95be1dd2d961840e17bc3c1f9272602400a515b2c4d408f82` |
| Single-chain antigen PDB | `3057b61ef8bcda42c79bb822b3307cb6c32b940f03011fa9ae84c21b493e6f03` |

The region CSV has seven ordered regions per chain; each H/L concatenation is
an exact character-for-character match to its FASTA sequence.

Docking parameters:

```text
candidates=1
steps=20
swarms=4
glowworms=50
cores=2
top_poses=3
scoring=fastdfire
score_direction=higher_is_better
```

Installed LightDock 0.9.4 defines `fastdfire` as the default and its scoring
ranking sorts in descending order (`reverse=True`). Thus
`higher_is_better` is supported by the exact installed implementation, not
guessed. It is meaningful only within this run and scoring configuration.

## Actual command and final run

The exact command was:

```bash
cd "$PROJECT_ROOT"
.venv311/bin/labmate run \
  "$LIVE_LOCAL_SMOKE_ROOT/project.json" \
  --mode live_local \
  --output "$RUNS_ROOT"
```

Final run ID: **`RUN-20260727-004729-3afe82ca`**

## Independent output checks

- Raw ColabFold chains A/B exactly matched the 112-aa VH and 110-aa VL.
  Normalized chains H/L retained the exact sequences, residue numbers,
  insertion codes, residue names, coordinates, occupancies, and B-factors.
- All 222 residue pLDDT values in the score JSON matched PDB B-factors.
  Independently recomputed mean pLDDT was `27.8397`; CDR pLDDT was `28.5804`.
  These low synthetic-smoke values are not scientific validation.
- Four `gso_20.out` files contained 50 data rows each (200 solutions total).
  The global higher-is-better top three were:

  1. swarm 2, 0-based GSO row/glowworm ID 18, score `7.97317969`;
  2. swarm 3, row/ID 42, score `7.13793176`;
  3. swarm 1, row/ID 49, score `6.98778249`.

- Each selected source row was materialized into an explicit three-line
  selected GSO in ranking order. The generator's line index was mapped to
  `lightdock_0.pdb`, `lightdock_1.pdb`, and `lightdock_2.pdb`; filenames were
  never sorted to infer scores.
- All three poses had exactly A/H/L chains and exact antigen/VH/VL sequence,
  residue-number, insertion-code, and residue-name contracts.
- Interface analysis processed 3/3 poses. `pose_consensus.csv` records
  `poses_analyzed=3`.
- Ranking contains one candidate, so every min-max normalized component and
  final heuristic score is 50. It has no between-candidate discriminatory
  meaning.
- All 72 manifest artifacts matched their recorded size and SHA-256. All 74
  run-ZIP members matched the run directory byte-for-byte.
- The final HTML shows all required stages as `succeeded`, except S09 PyMOL as
  `skipped_optional`; its S10 state agrees with the manifest.
- Binary/text privacy scanning found no local absolute path, username, token,
  secret, API key, password, actual environment-variable name/value, or
  environment dump in the report, logs, manifest, or ZIP.

## Final artifact hashes

| Artifact | SHA-256 |
|---|---|
| `candidate_ranking.csv` | `8c8b173048cd676b878ea7d5e532cc2e0f0ed145b57f6db8ca6430d36e12d55b` |
| `interface_residues.csv` | `f2db52321ab5e7006752efb236fb5a4ca4d08160a3c3174ba06e55dcd875d374` |
| `report.html` | `cc196ce6059afc2570a80462caec6747807d35306e9532a6a3bd3c3b0d53a52a` |
| `manifest.json` | `f5c253aa733516e219454870c5a985c4347098eb45031c7e93bba05c0dcb552c` |
| Run ZIP | `109db1f3269d5129a355904d1e7185300c13c6dd53a43742678869d820f95880` |

## Failures found and fixes applied

1. The supplied test suite initially had one Windows failure because a POSIX
   absolute path was accepted on Windows. Path validation now rejects POSIX
   and Windows absolute paths on either host.
2. LightDock 0.9.4 installation first encountered an interrupted PyPI transfer,
   NumPy 2.x incompatibility in old C extensions, and GCC 15 treating an old
   pointer warning as an error. It was installed only in the separate conda
   prefix using NumPy 1.26.4, no build isolation, and a one-build warning
   override. No system package was installed and no LightDock code was edited.
3. An inline preflight attempt had shell quoting syntax failure; it executed no
   scientific tool. A checked Python preflight script replaced it.
4. The first ColabFold run
   (`RUN-20260726-144307-65823985`) exhausted WSL unified memory. The adapter
   stopped because no official rank-001 PDB existed and did not fabricate any
   downstream output. The retry used ColabFold's
   `--disable-unified-memory --compile-mode fast`.
5. The first complete run
   (`RUN-20260726-144530-4fb0bf99`) exposed four audit defects: only 2/3 poses
   were analyzed, HTML rendered S10 as `running`, Live stage names still said
   `artifact replay`, and a JAX warning retained an environment-variable name.
   Code and regression tests were corrected, and the full computation was
   rerun rather than editing old artifacts.
6. Windows release packaging attempted to traverse the WSL venv `lib64`
   symlink before applying exclusions. Directory traversal now prunes excluded
   environments first while still rejecting any symlink in release scope.

## Regression results

- Windows Python 3.11.15: **76 passed**.
- WSL Python 3.11.15: **76 passed**.
- Final Replay CLI run:
  `RUN-20260727-005240-dd6f1e51`; 10 stages `succeeded`, S09
  `skipped_optional`, every stage `execution_kind=replay`, 78 artifact hashes
  verified, run ZIP SHA-256
  `02f96b6f2889fc9ad1a64fde0a766d14c3c6388bdf45293a53358e06ecd692df`.
- Streamlit headless startup: health endpoint returned HTTP 200 / `ok`; the
  process was then stopped.

## ColabFold Prediction Backend Smoke Test

- Date: 2026-07-29
- Operating system: WSL2, Ubuntu 26.04
- GPU: NVIDIA GeForce RTX 5070 Ti Laptop GPU, 12,227 MiB
- Backend: `ColabFoldBackend` (`prediction-only`)
- ColabFold: 1.6.2 (`alphafold-colabfold` 2.3.18)
- Environment Python: 3.11.15
- Input type: one complete VH/VL pair, encoded as a two-chain
  `VH:VL` ColabFold multimer FASTA
- Output root: `$PROJECT_ROOT/runs/validation/`

The project CLI invoked the real external executable through
`python -m labmate.run`; no mock, Replay fixture, antigen, or docking stage was
used. Machine-specific prefixes are normalized below:

```bash
$PROJECT_ROOT/.venv311/bin/python -m labmate.run \
  --prediction-backend colabfold \
  --heavy-chain "<complete VH>" \
  --light-chain "<complete VL>" \
  --colabfold-executable "$COLABFOLD_ROOT/bin/colabfold_batch" \
  --colabfold-model-data "$COLABFOLD_MODEL_ROOT" \
  --output "$PROJECT_ROOT/runs/validation/colabfold_backend_smoke_20260729_1625"
```

Parameters were `single_sequence`, preinstalled model data,
`alphafold2_multimer_v3`, one model, one recycle, zero relaxation, random seed
0, unified-memory disabled, and `compile-mode=fast`. The installed help
confirmed every option. Although ColabFold's generated `config.json` retains
an unused default `host_url`, the recorded mode is `single_sequence`, the A3M
contains only the two supplied chains, and no MSA query stage appears in the
execution log.

Observed execution:

- Start: 2026-07-29 16:25:09 +08:00
- ColabFold completion: 2026-07-29 16:27:29 +08:00
- Exit code: 0
- GPU execution was reported by ColabFold and independently observed with
  `nvidia-smi`.
- Three read-only samples observed approximately 5,453–5,685 MiB GPU memory;
  these samples are not a measured peak.
- JAX initially logged several failed large-memory allocation attempts before
  falling back and completing. The PDB was produced successfully. Post-run
  hardening makes future `PredictionResult` objects surface this condition as
  a non-fatal warning.

Result validation:

- `backend_name`: `colabfold`
- `status`: `succeeded`
- `return_code`: 0
- Original run `warnings`: empty; the allocation-warning surfacing fix was
  added after inspecting this run and regression-tested without repeating the
  scientific computation.
- Output PDB:
  `colabfold/antibody_unrelaxed_rank_001_alphafold2_multimer_v3_model_1_seed_000.pdb`
- Output PDB size: 149,202 bytes
- Output PDB SHA-256:
  `a00efa82242ab3d5fb80bbdf1949b113cf8e46a432333f7e95a759f9f2371fe6`
- The PDB contains 1,837 `ATOM`/`HETATM` rows and exactly chains A/B.
- Independently parsed chain A exactly matches the 125-residue VH; chain B
  exactly matches the 117-residue VL.
- The canonical PDB path remains inside the requested output directory.
- Output discovery found exactly one rank-1 PDB and no symbolic links.
- The input FASTA SHA-256 is
  `4d803605c11f3b8edd617fd2da6fcab0be30250d011f36a898c30b1e0f7cc751`.
- Score JSON, predicted-aligned-error JSON, A3M, plots, config, citation,
  stdout log, and stderr log were also produced. Logs were path-redacted and
  kept outside the source/release scope under ignored `runs/`.

This is a **local ColabFold prediction backend software-integration smoke
test**. It verifies one wrapper invocation, GPU use, two-chain FASTA handling,
bounded output discovery, and production of a non-empty PDB. It is not a
DB5.5 scientific benchmark, docking validation, accuracy proof, production
readiness statement, affinity/free-energy result, or experimental validation.

## IgFold Prediction Backend Smoke Test

- Date: 2026-07-29
- Operating system: WSL2, Ubuntu 26.04
- GPU: NVIDIA GeForce RTX 5070 Ti Laptop GPU, 12,227 MiB
- Backend: `IgFoldBackend` (`prediction-only`)
- Status: **succeeded — bounded local software-integration smoke**
- IgFold: official PyPI release 0.4.0
- AntiBERTy: official PyPI release 0.1.3
- Environment: separate `antibody-labmate-igfold-legacy` conda environment
- Main-process Python: 3.11.15; worker Python: 3.10.20
- PyTorch: 1.13.1+cpu; CUDA runtime: none; `torch.cuda.is_available()`: `False`
- Transformers: 4.24.0; AntiBERTy: 0.1.3; Biopython: 1.79
- Device used: CPU
- Input: one paired complete VH/VL input, passed as independent `H` and `L`
  dictionary entries; no antigen, scFv concatenation, Replay, ColabFold, mock,
  refinement, renumbering, or docking; one IgFold model

The legacy environment is isolated from the project Python 3.11 environment,
the existing ColabFold environment, base Python, and system Python. It follows
the relevant official IgFold 0.4.0 dependency era (notably PyTorch 1.13.1,
Transformers 4.24.0, AntiBERTy 0.1.3, and Biopython 1.79); `pip check` passed.
No PyRosetta was installed, and refinement and renumbering were both disabled.

The successful invocation uses a fail-closed bridge. The Python 3.11 process
validates input and creates a new empty output directory, then invokes a fixed,
Python-3.10-compatible worker file with a parameter list and `shell=False`.
The VH/VL values are stored in a private request JSON rather than process
arguments. The worker accepts only schema version 1, exactly one model,
relative PDB filename, standard paired sequences, and false refinement/
renumbering flags. It returns a bounded response JSON with a relative filename;
the parent rejects a nonzero exit, missing/invalid response, symbolic links,
path escape, no-ATOM output, wrong chains, or sequence mismatch. Sensitive
environment variables are not passed to the worker; stdout/stderr are retained
only as path- and token-redacted logs under ignored `runs/`.

```bash
$PROJECT_ROOT/.venv311/bin/python -m labmate.run \
  --prediction-backend igfold \
  --igfold-python "$IGFOLD_PYTHON" \
  --heavy-chain-file "$SMOKE_INPUT_ROOT/heavy.txt" \
  --light-chain-file "$SMOKE_INPUT_ROOT/light.txt" \
  --output "$RUNS_ROOT/igfold_bridge_backend_smoke_<UTC timestamp>/output"
```

The legacy environment used its already installed official-package weights;
the bridge ran with offline Hugging Face/Transformers mode and performed no
model download. Its cache, environment, request/response JSON, logs, and PDB
remain outside source control, Docker, and the release ZIP. IgFold displayed
the JHU Academic Software License non-commercial-use notice during startup.

The direct API preflight and formal bridge command both completed with exit
code 0. IgFold reported 2.14 seconds for folding; the end-to-end bridge smoke
completed in about 11 seconds including process startup and validation. The
formal `PredictionResult` was `backend_name: igfold`, `status: succeeded`,
with no warnings. It produced `igfold_prediction.pdb` (96,075 bytes; SHA-256
`71c73e3dc958cf54171bd51590073eafc9c66b581e9007baa3c5d08869e7f1e5`),
1,184 ATOM records, no HETATM or hydrogen atoms, and exactly H/L chains with
125/117 residues. Recovered sequences exactly matched the paired inputs; no
residues were missing and no non-standard residues were observed. The worker's
only recorded native field was `prmsd` with shape `[1, 242, 4]`, retained as
`metadata.native_metrics` with semantics `backend_native_unscaled`; it is not
pLDDT, PAE, ipTM, pTM, or a cross-backend confidence score.

An earlier separate Python 3.11 attempt remains part of the compatibility
record: PyTorch 2.7.1 safe checkpoint loading then Transformers 5.14.1 legacy
tokenizer removal blocked two initialization-only runs before any PDB was
written. The successful legacy worker does not change that incompatibility
boundary.

This is a **local IgFold prediction-backend software-integration smoke test**.
It verifies one isolated-worker invocation, H/L handling, output discovery,
and chain-sequence preservation. It does not verify structure accuracy,
predicted-error interpretation, docking, DB5.5, production readiness,
affinity, binding energy, experimental validity, Docker GPU execution, cloud
compute, or Live Remote.

## Not validated

## Input contract boundary

The verified Live Local path accepts complete paired VH/VL sequences, a region
annotation CSV, and antigen PDB input. The CSV annotates existing sequences; it
does not generate frameworks. Six CDR strings are only supported by the fixed
Replay fixture and cannot initiate a local prediction/docking run. IgCraft was
audited but not integrated because the available grafting interface requires a
complete antibody PDB rather than six CDR strings.

## Independent LightDock Execution Adapter Smoke Test

An isolated local execution smoke used a validated IgFold VH/VL artifact as
the ligand and `fixtures/demo_001/input/antigen.pdb` as the receptor. The
separately installed LightDock 0.9.4 command sequence was setup, sampling,
explicit GSO-row selection, then conformation generation. Parameters were one
swarm, five glowworms, five GSO steps and seed 0. It produced one non-empty
ATOM PDB pose and a run-relative manifest. This is an engineering integration
smoke only: the native `fastdfire` score is not affinity, and no scientific
docking, binding, epitope, experimental, or therapeutic claim follows.

- IgCraft execution inside the application;
- general antibody accuracy or real-dataset structure benchmarking;
- general IgFold accuracy or real-dataset scientific benchmarking (one local
  prediction-only integration smoke succeeded);
- antigen docking from the prediction-only ColabFold result;
- Docker GPU/ColabFold execution;
- concurrent users or long-running recovery;
- public or local MSA-backed ColabFold modes, templates, other model/tool
  versions, larger batches, performance, or reproducibility across machines;
- other LightDock scoring functions or production-scale docking;
- Live Remote, authentication, isolation, cancellation, timeout, retention, or
  cleanup services;
- PyMOL rendering (not installed; correctly `skipped_optional`);
- ElliDock, HDOCK, Schrödinger, or any other docking provider;
- experimental or clinical meaning of any structure, score, contact, or rank.

Within this explicit boundary, the current state is **`verified_live`**.

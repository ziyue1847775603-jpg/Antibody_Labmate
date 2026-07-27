# Devpost Project Description

> Archived Phase 1 submission copy. Current Phase 2a status and evidence are
> documented in `README.md` and `LIVE_LOCAL_VALIDATION.md`.

## Project name

Antibody Labmate

## Tagline

An honest, hash-verified Replay workflow for auditable antibody candidate
artifacts—without pretending fixed outputs are Live computation.

## Inspiration

Early antibody-computation workflows often span disconnected tools, fragile
file conventions, and results that are difficult to audit. For a competition
prototype, an additional risk is overstating what has actually been validated.
We built Antibody Labmate to demonstrate the workflow contract first: explicit
inputs, strict provenance, visible execution status, reproducible outputs, and
clear scientific limits.

## What it does

The Phase 1 Replay MVP accepts six separately labeled IMGT CDR sequences and an
antigen PDB. It validates the inputs, performs basic bounded PDB parsing, and
runs only when the inputs exactly match a bundled project-authored CC0
synthetic fixture. The backend then parses fixed candidate, structure, and
docking schemas; recomputes interface-contact heuristics and a transparent
within-run ranking; records every state transition; and produces:

- `candidate_ranking.csv`
- `interface_residues.csv`
- a self-contained offline `report.html`
- a provenance-rich `manifest.json`
- a downloadable run ZIP

A persistent red **REPLAY · NOT LIVE COMPUTE** banner appears throughout the
UI. Changing any normalized CDR, any antigen PDB byte, or any fixture artifact
causes a fail-closed hash rejection. Live Local and Live Remote are visibly
unavailable.

## How we built it

We used Python 3.11, Streamlit, Pydantic, Jinja2, and pytest. Pydantic defines
the job and artifact contracts. A ReplayBackend implements an explicit staged
state machine. The PDB parser is intentionally bounded and deterministic. The
report uses autoescaped templates and local assets only. Provenance records
input and artifact SHA-256 values, versions, licenses, warnings, stage status,
and relative paths. Packaging excludes development environments, caches, Git
metadata, local runs, secrets, and machine-specific paths.

LightDock is the default `DockingProvider` contract, but this release only
parses a verified fixed output schema. It does not install, call, or imitate
LightDock—or any other scientific model or binary.

## Challenges

The hardest design challenge was making a polished demo without crossing the
line between reproducible replay and unverified Live capability. We addressed
that with persistent labeling, strict input and fixture hashes, fail-closed
capability gates, per-stage execution metadata, and tests that reject altered
inputs instead of silently attaching canned results.

## Accomplishments we are proud of

- A complete Replay run is reproducible and independently inspectable.
- Six CDR fields and the antigen PDB have explicit validation boundaries.
- Reports, logs, manifests, and ZIP entries avoid secrets and absolute paths.
- Ranking preserves raw metrics, normalization directions, weights, ties, and
  sensitivity information rather than presenting an opaque score.
- The synthetic fixture has clear CC0 rights and no third-party scientific
  output or confidential sequence data.
- The project ships with cross-platform setup documentation, locked
  dependencies, a Streamlit deployment profile, and automated tests.

## What we learned

Provenance and capability truthfulness are product features, not cleanup work.
A Replay demo becomes useful when users can see exactly what was fixed, what
was recomputed, what was skipped, and why a changed input is rejected. We also
learned that scientific UX should preserve uncertainty and original metrics,
not hide them behind a single leaderboard number.

## What's next

Future work is deliberately conditional. Each real provider must first pass a
separate license, installation, schema, resource, and end-to-end validation
spike. Only then would we add Live Local or isolated Live Remote execution,
cancellation, timeouts, authentication, retention controls, and real provider
provenance. Those capabilities are not part of this submission.

## Built with

Python 3.11 · Streamlit · Pydantic · Jinja2 · pytest · HTML/CSS · SHA-256

## AI assistance disclosure

Codex assisted with implementation, tests, documentation, and submission
hardening based on a human-specified execution route and product constraints.
The project owner remains responsible for scientific wording, fixture rights,
competition eligibility, the accuracy of the submitted materials, and any
future provider validation.

## Scientific disclaimer

This software-test fixture and its ranking do not demonstrate binding,
affinity, specificity, safety, efficacy, or therapeutic effect. Experimental
validation is required for real scientific use.

# Submission Hardening Audit

Audit date: 2026-07-19  
Release: v0.1.1  
Scope: Phase 1 Replay MVP only

> **REPLAY ONLY · FIXED HASH-VERIFIED DEMO · NOT LIVE COMPUTE**

## Result

The source deliverable is ready for competition submission as a Replay MVP.
No scientific algorithm, fixture, golden result, provider parser, ranking
formula, or state transition was changed during hardening. No Live capability
was added.

| Audit area | Result | Evidence |
|---|---|---|
| Fresh Python 3.11 install | Pass | Isolated Python 3.11.15 environment installed `requirements.lock` and the editable project; 39 tests passed; `pip check` found no broken requirements |
| Windows install path | Pass with host limitation | PowerShell instructions use explicit `.venv` executables and relative paths; all 46 runtime-lock distributions resolved as CPython 3.11 `win_amd64` or pure-Python wheels |
| Cross-platform paths | Pass | Runtime paths use `pathlib`; fixture and archive paths are safe relative POSIX paths that map to Windows path parts; tests reject absolute, traversal, and backslash archive entries |
| Output privacy | Pass | A full Replay scanned 80 artifact files plus every run-ZIP member; no environment sentinel, local absolute path, private-key marker, or high-confidence API token pattern was found |
| REPLAY truth labels | Pass | UI sticky banner, report banner, log, CLI payload, manifest `replay_label`, and all 11 stage `execution_kind` values are Replay |
| Hash rejection | Pass | Tests reject a valid-but-different CDR, a one-byte antigen change, and a tampered fixture artifact before result reuse |
| Documentation/legal | Pass | README, MIT LICENSE, direct dependency and non-bundled scientific-tool notices, deployment guide, release notes, demo script, and Devpost copy are present |
| Streamlit startup | Pass | Fresh environment started `app.py`; `/_stcore/health` returned HTTP 200 with `ok` |
| Release archive | Pass | Deterministic archive builder rejects excluded/development/private content and verifies every `SOURCE_CHECKSUMS.sha256` entry |

## Replay output verification

- Mode: `replay`; label: `REPLAY`.
- Stages: 11; all succeeded except the truthful optional visualization skip.
- Candidate ranking rows: 4.
- Interface residue rows: 42.
- LightDock provider: `replay_only`; executable not installed or invoked.
- Live Local and Live Remote: `unavailable`.
- Offline report, manifest, CSV files, and complete run ZIP generated.

## Release ZIP exclusions

The packaging gate excludes or rejects:

- Git metadata and IDE metadata;
- virtual environments, package build metadata, test/coverage caches, and local
  run directories;
- bytecode, nested ZIP files, and symbolic links;
- common secret filenames and private-key/certificate suffixes;
- high-confidence OpenAI, GitHub, AWS, Slack, and PEM private-key patterns;
- machine-specific workspace, temporary, and Windows user paths;
- duplicate, absolute, traversal, or backslash ZIP entries.

## Documentation and license review

- Project source license: MIT.
- Synthetic fixture: project-authored CC0-1.0 rights statement and fixture
  gate.
- Direct runtime/test dependencies and their locked versions/licenses are
  identified in `THIRD_PARTY_NOTICES.md`.
- Referenced scientific tools are explicitly described as not bundled and not
  executed. LightDock GPL obligations are flagged for any future distribution
  that actually includes it.

## Remaining external submission work

These steps require competition-owner accounts or a different operating-system
host and were not fabricated as completed:

- Execute the documented commands on an actual Windows 10/11 machine. The
  dependency-wheel audit verifies availability but is not a substitute for a
  physical Windows UI run.
- Push the clean source to the intended public repository.
- Deploy `app.py` on Streamlit Community Cloud with Python 3.11 and verify the
  public URL.
- Record and upload the sub-three-minute demo video.
- Paste the English project description into Devpost and complete team,
  eligibility, session-ID, and submission fields.


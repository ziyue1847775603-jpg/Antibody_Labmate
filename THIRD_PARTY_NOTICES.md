# Third-Party Notices

This file distinguishes runtime Python dependencies from scientific tools that
are installed and invoked separately. No scientific model, checkpoint,
database, docking source/binary, or PyMOL distribution is bundled in the MIT
project archive.

## Direct runtime and test dependencies

Exact resolved package versions are recorded in `requirements.lock`.

| Component | Locked version | Use in Phase 1 | Upstream license | Project handling |
|---|---|---|---|
| [Streamlit](https://github.com/streamlit/streamlit) | 1.59.2 | Local UI | Apache License 2.0 | Installed from Python package index; not vendored |
| [Pydantic](https://github.com/pydantic/pydantic) | 2.13.4 | Data contracts and validation | MIT | Installed dependency; not vendored |
| [Jinja2](https://github.com/pallets/jinja) | 3.1.6 | Autoescaped offline HTML | BSD 3-Clause | Installed dependency; not vendored |
| [pytest](https://github.com/pytest-dev/pytest) | 8.4.2 | Test runner, development only | MIT | Installed test dependency; not vendored |

Streamlit installs transitive dependencies listed in `requirements.lock`. They are not copied into the source archive. A binary/container redistribution must regenerate a complete dependency license inventory for the exact build; this source notice is not a substitute for that release audit.

## External scientific tools and execution by mode

| Component | Upstream license/status noted by project route v1.1 | Replay mode | Phase 2a Live Local validation |
|---|---|---|---|
| IgCraft | MIT for code/official weights page at route audit time | Not installed or run; fixture is not IgCraft output | Not run by the application |
| ColabFold | MIT for code; AlphaFold model/data dependencies require separate review | Not run; fixture metrics are synthetic | External ColabFold 1.6.2 executed with preinstalled `alphafold2_multimer_v3` weights and `single_sequence`; not bundled |
| IgFold / AntiBERTy | JHU Academic Software License; non-commercial use terms apply to the official code, data, and weights | Not installed or run by Replay | A separate user-managed legacy Python environment completed one prediction-only VH/VL software-integration smoke; no environment, package, checkpoint, cache, or output is bundled |
| LightDock | GPL-3.0 | `LightDockProvider` remains `replay_only`; no execution | External LightDock 0.9.4 executed through CLI/file interfaces; no source, binary, environment, or GPL output is included in the source ZIP. Benchmark Local also requires a separate user installation and remains `implemented_unverified`. |
| RFantibody / ProteinMPNN | MIT for the audited RFantibody code route; exact upstream model/data terms require user review | Not run | External user-managed RFantibody 1.0.0 and its official ProteinMPNN stage may be invoked only through the local CLI; code, checkpoints, environments, caches and generated candidates are not bundled. |
| ElliDock | MIT at route audit time | Not implemented or run | Not implemented or run |
| HDOCKlite | Academic/non-commercial with redistribution restrictions noted by route | Not included | Not used or implemented |
| Schrödinger | Proprietary | Not included | Not used or implemented |
| Open-Source PyMOL | BSD-like | `skipped_optional` | Not installed; `skipped_optional` |

Before enabling or distributing another Live provider/version, re-check the
license corresponding to the exact release/commit. LightDock must remain a
separate user installation for this MIT source distribution. If a distributor
instead includes it in a container or installer, that distributor must
separately satisfy GPL-3.0 license, notice, and corresponding-source
obligations. This project notice does not provide legal advice.

IgFold and AntiBERTy are also external, user-installed tools. Their official
packages display JHU Academic Software License terms that restrict use to
non-commercial purposes (including use at commercial entities). Antibody
Labmate does not redistribute their code, environment, weights, cache, or
generated output; users must review and satisfy the upstream terms themselves.

Schrödinger/PIPER is permitted only as a user-run external commercial
comparison under that user's license. Antibody Labmate does not call or bundle
it and does not distribute proprietary project files, scripts, license
material, credentials, or outputs.

## Synthetic fixture

`fixtures/demo_001` contains only project-authored synthetic sequences, coordinates, scores, poses, and metadata dedicated under CC0-1.0. It contains no third-party tool output, binary, patented demo CDR, or confidential input. The values have no biological meaning.

`examples/benchmark_local` likewise contains only project-authored CC0
synthetic coordinates and configuration text. Its PDB files are inputs, not
outputs from LightDock, PIPER, Schrödinger, or another scientific package.

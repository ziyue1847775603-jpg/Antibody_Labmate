# Third-Party Notices

This file distinguishes runtime Python dependencies from scientific tools that are only referenced by the architecture. No scientific model, checkpoint, database, docking binary, or PyMOL distribution is bundled.

## Direct runtime and test dependencies

Exact resolved package versions are recorded in `requirements.lock`.

| Component | Locked version | Use in Phase 1 | Upstream license | Project handling |
|---|---|---|---|
| [Streamlit](https://github.com/streamlit/streamlit) | 1.59.2 | Local UI | Apache License 2.0 | Installed from Python package index; not vendored |
| [Pydantic](https://github.com/pydantic/pydantic) | 2.13.4 | Data contracts and validation | MIT | Installed dependency; not vendored |
| [Jinja2](https://github.com/pallets/jinja) | 3.1.6 | Autoescaped offline HTML | BSD 3-Clause | Installed dependency; not vendored |
| [pytest](https://github.com/pytest-dev/pytest) | 8.4.2 | Test runner, development only | MIT | Installed test dependency; not vendored |

Streamlit installs transitive dependencies listed in `requirements.lock`. They are not copied into the source archive. A binary/container redistribution must regenerate a complete dependency license inventory for the exact build; this source notice is not a substitute for that release audit.

## Scientific tools referenced but not bundled or executed

| Component | Upstream license/status noted by project route v1.1 | Phase 1 status |
|---|---|---|
| IgCraft | MIT for code/official weights page at route audit time | Not installed, not run; fixture is not IgCraft output |
| ColabFold | MIT for code; model/database dependencies require separate review | Not installed, not run; fixture metrics are synthetic |
| LightDock | GPL-3.0 | Default provider contract is `replay_only`; no source, binary, or LightDock output bundled; no `dock()` execution |
| ElliDock | MIT at route audit time | Not implemented or run |
| HDOCKlite | Academic/non-commercial with redistribution restrictions noted by route | Not included; unavailable without a separate written-license gate |
| Open-Source PyMOL | BSD-like | Optional visualization is `skipped_optional`; not included or run |

Before enabling or distributing any Live provider, re-check the license corresponding to the exact locked release/commit. If LightDock is included in a container or installer, the distributor must separately satisfy GPL-3.0 license, notice, and corresponding-source obligations. This project notice does not provide legal advice.

## Synthetic fixture

`fixtures/demo_001` contains only project-authored synthetic sequences, coordinates, scores, poses, and metadata dedicated under CC0-1.0. It contains no third-party tool output, binary, patented demo CDR, or confidential input. The values have no biological meaning.

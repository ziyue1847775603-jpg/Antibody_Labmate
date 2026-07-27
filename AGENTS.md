# Antibody Labmate engineering constraints

The primary technical specification is `Antibody Labmate 最终执行路线 v1.1` supplied by the project owner. Replay remains the hash-verified demo; Phase 2a adds a Local CLI adapter whose `verified_live` status is limited to the exact real run documented in `LIVE_LOCAL_VALIDATION.md`.

## Non-negotiable scope

- Keep Replay visibly labeled `REPLAY` in UI, report, manifest, logs, and CLI output.
- Reject input when normalized CDR, antigen byte, or bundle hash differs from `demo_001`.
- Never return fixture results for custom input.
- Do not add Live Remote, public MSA calls initiated by this application, model downloads, placeholder scientific results, or simulated delays. Phase 2a Live Local is allowed only through the explicit user-installed command adapter.
- Replay keeps LightDock replay-only. Phase 2a Live Local may invoke a separately installed LightDock CLI through `labmate.live_local`; never bundle LightDock source/binaries. `verified_live` may describe only a completed, audited software integration run—never docking quality, affinity, free energy, efficacy, safety, or scientific validity.
- Do not add ordinary DiffDock as an antibody–antigen backend.
- Do not include HDOCK binaries/outputs or enable HDOCK without a written-license gate.
- Keep interface analysis independent of PyMOL.
- Call distance-only polar/ionic labels heuristics, never confirmed hydrogen bonds.
- Never describe docking score, pLDDT, PAE, ipTM, or FinalScore as affinity, binding free energy, efficacy, or safety.
- Do not write secrets, uploaded private content, environment variables, or absolute paths into public reports.

## Required checks for every change

```bash
python -m pytest
labmate run fixtures/demo_001/project.yaml --mode replay --fixture demo_001
streamlit run app.py --server.headless true
```

If `scripts/build_demo_fixture.py` is changed, regenerate the fixture, inspect the golden result intentionally, and run all tests. Never update expected order or row counts merely to make a failing test pass.

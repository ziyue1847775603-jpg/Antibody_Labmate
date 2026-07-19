# Antibody Labmate engineering constraints

The primary technical specification is `Antibody Labmate 最终执行路线 v1.1` supplied by the project owner. This repository is currently Phase 1 Replay MVP only.

## Non-negotiable scope

- Keep Replay visibly labeled `REPLAY` in UI, report, manifest, logs, and CLI output.
- Reject input when normalized CDR, antigen byte, or bundle hash differs from `demo_001`.
- Never return fixture results for custom input.
- Do not add Live Local, Live Remote, external executables, public MSA calls, model downloads, placeholder scientific results, or simulated delays without a separately approved phase.
- LightDock is the default provider contract, but its capability remains `replay_only`; `dock()` must fail closed.
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


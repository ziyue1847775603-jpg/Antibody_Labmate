# Deployment Guide

> **REPLAY ONLY · FIXED HASH-VERIFIED DEMO · NOT LIVE COMPUTE**

Antibody Labmate v0.1.1 requires Python 3.11. It has no system-level scientific
tools, GPU runtime, database download, API key, or secret configuration.

## Fresh Windows 10/11 installation

Install the 64-bit Python 3.11 release from Python.org with Python Launcher
enabled. Open PowerShell in the extracted project directory and run:

```powershell
py -3.11 --version
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe -m pip install -e . --no-deps
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m labmate.cli capabilities
.\.venv\Scripts\labmate.exe run fixtures\demo_001\project.yaml --mode replay --fixture demo_001
.\.venv\Scripts\python.exe -m streamlit run app.py
```

The explicit interpreter paths avoid PowerShell activation-policy issues. The
commands use only paths relative to the project directory and do not assume a
drive letter or username. The UI is then available at the local URL printed by
Streamlit, normally `http://localhost:8501`.

If installation fails, first verify that `py -3.11 --version` reports Python
3.11 and that the release archive was fully extracted. Do not install LightDock
or any other scientific tool for this Replay release.

## macOS and Linux

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pip install -e . --no-deps
.venv/bin/python -m pytest
.venv/bin/python -m labmate.cli run fixtures/demo_001/project.yaml --mode replay --fixture demo_001
.venv/bin/python -m streamlit run app.py
```

## Streamlit Community Cloud

1. Put the clean release contents in a GitHub repository.
2. Create a Community Cloud app with `app.py` as the entrypoint.
3. In Advanced settings, select Python 3.11.
4. Leave Secrets empty. No `packages.txt` is required.
5. Deploy and confirm that the persistent red REPLAY banner is visible before
   running the verified demo.

The root `requirements.txt` delegates to the exact runtime-only lock. Project
settings live in `.streamlit/config.toml`: headless mode, a 2 MiB upload limit,
CORS and XSRF protections enabled, browser usage stats disabled, and browser
error details hidden. Community Cloud storage is ephemeral, so generated runs
are download artifacts rather than durable storage.

Official references:

- <https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/app-dependencies>
- <https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy>
- <https://docs.streamlit.io/develop/api-reference/configuration/config.toml>

## Deployment boundary

This UI intentionally accepts only the exact six CDRs and antigen PDB bytes in
the bundled CC0 fixture. A changed CDR, changed PDB byte, or changed fixture
artifact is rejected. Public deployment does not turn this release into a Live
service and should not be presented as one. Do not upload confidential or
third-party-controlled sequences to a public demo.


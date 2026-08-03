# Docker

The repository image is a reproducible Python 3.11 environment for the
hash-verified Replay demo. It does not contain ColabFold, IgFold, LightDock,
model weights, sequence databases, or other scientific executables.

## Replay mode

Replay does not require a GPU. From the repository root:

```bash
docker compose up --build
```

Open <http://localhost:8501>. Runtime artifacts are written to the ignored
repository-relative `runs/` directory. Stop the service with:

```bash
docker compose down
```

The CLI can also be invoked in the built image:

```bash
docker compose run --rm labmate \
  python -m labmate.cli run fixtures/demo_001/project.yaml \
  --mode replay \
  --prediction-backend replay \
  --fixture demo_001
```

## Local prediction and docking

The base image intentionally supports Replay only. ColabFold, IgFold, and
LightDock remain user-installed external tools and are not downloaded during
the image build.

The recorded 2026-07-29 ColabFold and isolated-interpreter IgFold
prediction-backend smokes ran directly in the host WSL2 environment, not in
this image. Docker GPU prediction remains
unverified.

A custom live-compute image or host installation must separately provide:

- a compatible NVIDIA GPU and driver;
- NVIDIA Container Toolkit when GPU execution happens in Docker;
- the selected prediction package and executable;
- locally installed model weights and databases;
- LightDock when running a docking workflow; and
- all applicable licenses and input-data rights.

Mounting those resources or creating a derivative image does not make a result
scientifically validated. The recorded synthetic integrations are software
integration checks only; they are not affinity, free-energy, specificity,
safety, efficacy, or experimental validation.

## Replay container validation

On 2026-07-29 the Replay image was built from this working tree with Docker
Engine 29.6.2. The transmitted build context was approximately 1.77 MB; the
ignored host `runs/`, conda environments, model data, caches, and external
scientific tools were not sent. The resulting image:

- started Streamlit as the non-root `labmate` user;
- returned HTTP 200 / `ok` from the Streamlit health endpoint;
- retained the `REPLAY · FIXED HASH-VERIFIED DEMO · NOT LIVE COMPUTE` UI
  boundary;
- contained neither `colabfold_batch` nor `lightdock3.py`; and
- completed the hash-exact Replay CLI workflow using container-temporary
  output.

The container and compose network were then stopped and removed. This verifies
the Replay container path only. GPU passthrough, ColabFold, IgFold, LightDock,
and any live-compute Docker configuration remain unverified.

## Phase D1 — LightDock worker container

An isolated LightDock 0.9.4 CPU worker container has been added (Phase D1 of
the Live Local Docker roadmap).  This container communicates with Labmate
solely through fixed CLI commands, exit codes, and a shared work volume.

**Current status:** Built but not yet integrated into the Live Local workflow.
No scientific validation.

- Source: [`docker/live/lightdock/Dockerfile`](../docker/live/lightdock/Dockerfile)
- Compose: [`docker-compose.live-local.yml`](../docker-compose.live-local.yml)
  (separate from the Replay `docker-compose.yml`)
- Adapter: [`labmate/backends/lightdock_container.py`](../labmate/backends/lightdock_container.py)
- Docs: [`docs/live_local_docker_d1.md`](live_local_docker_d1.md)

**Build and smoke:**

```bash
docker compose -f docker-compose.live-local.yml build lightdock
docker compose -f docker-compose.live-local.yml run --rm lightdock version
```

**Constraints:**
- GPL-3.0 — the LightDock container contains an unmodified pip installation.
  When distributing the image, the corresponding source must be made available.
  This document is not legal advice.

## Phase D3 — ColabFold GPU worker

An isolated ColabFold 1.6.2 GPU worker container has been added (Phase D3)
and verified with a real GPU smoke (RTX 5070 Ti, JAX GPU backend, rank-1
H/L PDB with exact sequence match).

- Base: official `ghcr.io/sokrypton/colabfold:1.6.2-cuda13` (digest
  `sha256:c9eab025...`); project image `antibody-labmate-colabfold:1.6.2`
- Source: [`docker/live/colabfold/Dockerfile`](../docker/live/colabfold/Dockerfile)
- Adapter: [`labmate/backends/colabfold_container.py`](../labmate/backends/colabfold_container.py)
- Docs: [`docs/live_local_docker_d3.md`](live_local_docker_d3.md)
- GPU granted only to this service; `network_mode: none`; fixed
  scientific parameters; no caller override.

```bash
docker compose -f docker-compose.live-local.yml build colabfold
docker compose -f docker-compose.live-local.yml run --rm colabfold gpu-check
```

## Phase D4 — Docker Compose Live Local (end to end)

Phase D4 verified the full chain with host Labmate orchestrator +
containerized ColabFold/LightDock workers on a CC0 synthetic candidate
(run `RUN-20260803-113314-b2cd5ea1`).

- Docs: [`docs/live_local_docker_d4.md`](live_local_docker_d4.md)
- Explicit opt-in mode: `--tool-execution-provider docker_compose`
  (default remains `host`; no auto-detection, no silent fallback)
- Old project.json files remain fully compatible (default host).

```bash
python -m labmate.cli run project.json --mode live_local \
  --tool-execution-provider docker_compose \
  --docker-work-root runs/docker-live/work \
  --docker-data-root <model-data-dir> \
  --docker-cache-root runs/docker-live/cache \
  --output runs/docker-live/runs
```

**Boundaries:**
- This is NOT a fully containerized web application; the Labmate
  orchestrator runs on the host and the public Streamlit remains
  Replay-only.
- This is NOT Live Remote, a production deployment, or a scientific
  validation.
- No Docker socket is mounted to any web container.
- Not validated: third-party-machine reproduction (D5), image registry
  distribution, RFantibody container, RF2, IgCraft.

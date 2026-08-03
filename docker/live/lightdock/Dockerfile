# LightDock 0.9.4 CPU worker
#
# This image installs the separately-licensed GPL-3.0 LightDock package.
# No model weights, databases, secrets, or user sequences are embedded.
# LightDock communicates with Labmate solely through the CLI, exit codes,
# and regular file artifacts written to a shared work volume.
#
# GPL-3.0 obligation: when distributing this image you must also make the
# corresponding source available.  See THIRD_PARTY_NOTICES in the build
# context for the exact routes and versions.

# Pinned base image (Python 3.11-slim, Debian Bookworm)
# digest: sha256:... — record after first build
FROM python:3.11-slim@sha256:af14252ce0a80e3b47917c3e99a61b8c9dd394ecfdb5e141b4e2f742e30f2ce6

LABEL org.opencontainers.image.title="antibody-labmate-lightdock-worker"
LABEL org.opencontainers.image.description="Isolated LightDock 0.9.4 CPU worker for Antibody Labmate Phase D1"
LABEL org.opencontainers.image.licenses="GPL-3.0"
LABEL org.opencontainers.image.source="https://github.com/ziyue1847775603-jpg/Antibody_Labmate"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    LIGHTDOCK_VERSION=0.9.4

# System dependencies: ProDy needs libgomp1 for OpenMP; MPI is optional
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Install pinned LightDock and its dependency chain.
# NumPy is listed first because older LightDock setup.py imports it at build time
# (fixed in 0.9.1, but we pin the order defensively).
RUN python -m pip install --no-cache-dir \
        "numpy<2" \
        "scipy<2" \
        "cython<4" \
        "biopython<2" \
        "mpi4py<4" \
        "ProDy<3" \
    && python -m pip install --no-cache-dir "lightdock==${LIGHTDOCK_VERSION}"

# Verify the installed executables are regular files on PATH
RUN lightdock3_setup.py --help > /dev/null 2>&1 \
    && lightdock3.py --help > /dev/null 2>&1 \
    && lgd_generate_conformations.py --help > /dev/null 2>&1

# Create non-root user
RUN useradd --create-home --uid 10001 lightdock \
    && mkdir -p /work /work/inputs /work/outputs \
    && chown -R lightdock:lightdock /work

# Copy entrypoint and license notice
COPY entrypoint.sh /usr/local/bin/entrypoint
COPY THIRD_PARTY_NOTICES_LightDock.md /usr/local/share/lightdock/
RUN chmod 755 /usr/local/bin/entrypoint

USER lightdock
WORKDIR /work

# Entrypoint enforces a subcommand whitelist; no arbitrary shell.
ENTRYPOINT ["/usr/local/bin/entrypoint"]
CMD ["version"]

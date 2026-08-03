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

# Pinned base image (Python 3.11-slim, Debian Trixie).
# Digest from first verified D1 build (2026-08-03).
FROM python:3.11-slim@sha256:db3ff2e1800a8581e2c48a27c3995339d47bdf046da21c7627accd3d51053a93

LABEL org.opencontainers.image.title="antibody-labmate-lightdock-worker"
LABEL org.opencontainers.image.description="Isolated LightDock 0.9.4 CPU worker for Antibody Labmate Phase D1"
LABEL org.opencontainers.image.licenses="GPL-3.0"
LABEL org.opencontainers.image.source="https://github.com/ziyue1847775603-jpg/Antibody_Labmate"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    LIGHTDOCK_VERSION=0.9.4

# System dependencies: ProDy needs libgomp1.  C compiler for building
# ProDy and freesasa C extensions from source.
# python3-mpi4py is installed from apt to avoid the mpi4py source build
# (mpi4py 3.1.6's mpidistutils is incompatible with setuptools >=75).
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        libgomp1 \
        libopenmpi-dev \
        openmpi-bin \
        python3-mpi4py \
    && rm -rf /var/lib/apt/lists/*

# Install LightDock and its dependency chain.
# Dependencies are installed first because lightdock's setup.py imports
# numpy at build time (see lightdock GitHub issue #14, fixed in 0.9.1).
# mpi4py is provided by apt (python3-mpi4py) so we use --no-deps to
# prevent pip from trying to build it from source.
#
# LightDock 0.9.4's setup.py uses deprecated setuptools APIs
# (setuptools.command.test, fetch_build_eggs) that are removed in
# setuptools >= 70.  We pin setuptools just for the lightdock build
# and then restore the system version.
RUN python -m pip install --no-cache-dir "setuptools>=65,<70" \
    && python -m pip install --no-cache-dir \
        "numpy>=1.24,<1.25" \
        "scipy<2" \
        "cython<3.1" \
        "biopython>=1.80,<2" \
        "ProDy<3" \
        "freesasa<3" \
    && SETUPTOOLS_USE_DISTUTILS=stdlib \
       CFLAGS="-Wno-incompatible-pointer-types" \
       python -m pip install --no-cache-dir --no-deps --no-build-isolation \
        "lightdock==${LIGHTDOCK_VERSION}" \
    && python -m pip install --no-cache-dir --upgrade "setuptools>=75"

# Remove build-time dependencies to shrink the image
RUN apt-get remove -y build-essential libopenmpi-dev \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

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

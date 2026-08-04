# ColabFold 1.6.2 GPU worker (Phase D3 — AMD/ROCm)
#
# Self-built image for AMD ROCm GPUs.  No official ColabFold ROCm image
# exists (only CUDA 12/13), so we build on the official AMD ROCm JAX
# community image and install ColabFold via pip.
#
# Base: rocm/jax-community (official AMD ROCm JAX image)
#   - Provides: JAX with ROCm backend, rocm-smi, device access
#   - Python: as shipped in the ROCm image
#
# This wrapper adds:
# - pip install colabfold with jax[rocm] already satisfied by the base
# - a strict whitelist entrypoint (version / gpu-check / predict)
#   using rocm-smi instead of nvidia-smi
# - a non-root user
# - pinned model/cache volume layout
#
# No model weights, databases, user sequences, or secrets are embedded.
#
# Licenses:
#   - ColabFold: MIT (code)
#   - ROCm base image: MIT (AMD ROCm)
#   - AlphaFold model weights: separately licensed, user-supplied

# Digest recorded at first successful build.
FROM rocm/jax-community:latest

LABEL org.opencontainers.image.title="antibody-labmate-colabfold-worker-amd"
LABEL org.opencontainers.image.description="Isolated ColabFold 1.6.2 AMD/ROCm GPU worker for Antibody Labmate Phase D3"
LABEL org.opencontainers.image.licenses="MIT AND (AlphaFold-model-terms) AND (ROCm-terms)"
LABEL org.opencontainers.image.source="https://github.com/ziyue1847775603-jpg/Antibody_Labmate"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    JAX_PLATFORMS=rocm \
    JAX_COMPILATION_CACHE_DIR=/work/cache/jax

# System dependencies: colabfold_batch needs kalign even in single_sequence
# mode (for the single-sequence alignment object).  hhsuite and mmseqs2 are
# required for MSA-backed modes but NOT for single_sequence; they are
# included for completeness in case the user switches modes (which the
# entrypoint currently forbids).  The rocm/jax-community base does not
# include these; the official colabfold CUDA image does.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        kalign \
        hhsuite \
        mmseqs2 \
    && rm -rf /var/lib/apt/lists/*

# Install ColabFold on top of the ROCm JAX base.
# The base image already provides jax[rocm]; we only add colabfold.
# --no-deps prevents pip from pulling jax[cuda] as a dependency override.
RUN python -m pip install --no-cache-dir --no-deps \
        "colabfold==1.6.2" \
    && python -m pip install --no-cache-dir \
        "alphafold-colabfold==2.3.18" \
        "openmm" \
    && python -c "import jax; print('jax', jax.__version__, 'backend', jax.default_backend())" \
    && python -c "from importlib.metadata import version; print('colabfold', version('colabfold'))"

# Verify rocm-smi and JAX GPU devices (may fail during build if no GPU;
# || true keeps the build going — the runtime gpu-check subcommand will
# enforce GPU on actual use)
RUN rocm-smi --showproductname > /dev/null 2>&1 || true

# Create non-root user (uid 10003; 10001 = lightdock, 10002 = colabfold-nvidia)
RUN useradd --create-home --uid 10003 colabfold \
    && mkdir -p /work/input /work/output /work/cache \
    && chown -R colabfold:colabfold /work

COPY entrypoint.sh /usr/local/bin/entrypoint
COPY THIRD_PARTY_NOTICES.md /usr/local/share/colabfold-amd/
RUN chmod 755 /usr/local/bin/entrypoint

USER colabfold
WORKDIR /work

ENTRYPOINT ["/usr/local/bin/entrypoint"]
CMD ["version"]

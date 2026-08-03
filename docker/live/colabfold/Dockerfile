# ColabFold 1.6.2 GPU worker (Phase D3)
#
# Thin wrapper around the OFFICIAL ColabFold container published by the
# ColabFold project on GitHub Container Registry.  We do not build a
# from-scratch ColabFold environment; the official image provides the
# verified conda-free environment (ColabFold 1.6.2, JAX GPU, CUDA).
#
# This wrapper adds:
# - a strict whitelist entrypoint (version / gpu-check / predict)
# - a non-root user
# - pinned model/cache volume layout
#
# No model weights, databases, user sequences, or secrets are embedded.
#
# License: ColabFold MIT (code); AlphaFold model weights are separately
# licensed and supplied by the user via read-only mounts.

# Digest recorded from the official GitHub Container Registry pull on
# 2026-08-03:
#   ghcr.io/sokrypton/colabfold:1.6.2-cuda13
#   sha256:c9eab0253fe324b7ec2ec644607141539d7580a4e88d1d3788abba8c92d61ef1
# Environment inside the image: ColabFold 1.6.2, jaxlib 0.10.2
# (jax-cuda13), Python 3.12, OpenMM 8.5.2.
FROM ghcr.io/sokrypton/colabfold:1.6.2-cuda13@sha256:c9eab0253fe324b7ec2ec644607141539d7580a4e88d1d3788abba8c92d61ef1

LABEL org.opencontainers.image.title="antibody-labmate-colabfold-worker"
LABEL org.opencontainers.image.description="Isolated ColabFold 1.6.2 GPU worker for Antibody Labmate Phase D3"
LABEL org.opencontainers.image.licenses="MIT AND (AlphaFold-model-terms)"
LABEL org.opencontainers.image.source="https://github.com/ziyue1847775603-jpg/Antibody_Labmate"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    # JAX compilation cache lives in a dedicated writable volume.
    JAX_COMPILATION_CACHE_DIR=/work/cache/jax \
    XLA_PYTHON_CLIENT_PREALLOCATE=1

# Create non-root user (uid 10002; 10001 is used by the LightDock worker).
RUN useradd --create-home --uid 10002 colabfold \
    && mkdir -p /work/input /work/output /work/cache \
    && chown -R colabfold:colabfold /work

# Copy entrypoint and license notice
COPY entrypoint.sh /usr/local/bin/entrypoint
COPY THIRD_PARTY_NOTICES_ColabFold.md /usr/local/share/colabfold/
RUN chmod 755 /usr/local/bin/entrypoint

USER colabfold
WORKDIR /work

# Entrypoint enforces a subcommand whitelist; no arbitrary shell.
ENTRYPOINT ["/usr/local/bin/entrypoint"]
CMD ["version"]

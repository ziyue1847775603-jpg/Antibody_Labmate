# ColabFold (AMD/ROCm) — Third-Party Notice

This worker builds on the official AMD ROCm JAX community image and
installs ColabFold via pip.  It does NOT use the official ColabFold
CUDA Docker image (no official ColabFold ROCm image exists).

## Base image

- `rocm/jax-community:latest` (AMD ROCm JAX community image)
- Official source: https://github.com/ROCm/rocm-jax
- Docker Hub: https://hub.docker.com/r/rocm/jax-community
- License: MIT (AMD ROCm)

## ColabFold

- Version: 1.6.2 (`alphafold-colabfold` 2.3.18)
- Official source: https://github.com/sokrypton/ColabFold
- License: MIT (code)
- Installation: `pip install --no-deps colabfold==1.6.2` on top of
  the ROCm JAX base (jax[rocm] already provided by the base image)

## JAX / ROCm

- JAX with ROCm backend, provided by the base image
- No CUDA/NVIDIA libraries are present in this image
- JAX_PLATFORMS=rocm

## AlphaFold model weights

- `params_model_*_multimer_v3.npz` are governed by the AlphaFold model
  parameters license (CC BY 4.0 / AlphaFold terms)
- Must be obtained by the user and mounted read-only as `/models/colabfold`
- Not embedded in this image

## No bundled data

No model weights, sequence databases, user sequences, API keys, or
secrets are present in this image.

## Not legal advice

Verify your obligations under the ColabFold, ROCm, and AlphaFold
licenses before redistributing.

# ColabFold — Third-Party Notice

This worker uses the official ColabFold container published by the ColabFold
project (sokrypton/ColabFold) on GitHub Container Registry:

- Image: `ghcr.io/sokrypton/colabfold:1.6.2-cuda13`
- Official source: https://github.com/sokrypton/ColabFold
- Container registry: https://github.com/sokrypton/ColabFold/pkgs/container/colabfold

## Version and environment

- ColabFold: 1.6.2 (`alphafold-colabfold` 2.3.18)
- JAX: GPU build (CUDA 12/13 backend), version reported by `colabfold version`
- Python: as shipped in the official image

## Licensing

- ColabFold code is MIT-licensed (see the official repository LICENSE).
- AlphaFold2 model weights (`params_model_*_multimer_v3.npz`) are governed by
  the AlphaFold model parameters license (CC BY 4.0 / AlphaFold terms) and
  must be obtained by the user. This worker does NOT embed or download them;
  they are mounted read-only from a user-supplied host directory.
- No sequence database is embedded or downloaded. `single_sequence` mode
  performs no public MSA queries.

## No bundled data

This image contains no model weights, sequence databases, user sequences,
API keys, or secrets. All scientific data is supplied by the user at run
time via read-only volume mounts.

## Not legal advice

This notice is informational. Verify your obligations under the ColabFold
and AlphaFold licenses before redistributing this image or derived images.

# Project-authored Live Local smoke input

This directory contains one deterministic, project-authored synthetic candidate and a CC0 synthetic single-chain antigen input. It exists only to exercise the Live Local software contract with real, separately installed ColabFold and LightDock executables.

The VH and VL records are 112 and 110 amino acids long. They were generated from the fixed seed `Antibody Labmate Phase 2a CC0 deterministic synthetic smoke v1`, using SHA-256 rejection sampling over `ADEFGHIKLMNPQRSTVWY`, followed by four fixed cysteine substitutions. They were not copied or adapted from a natural, clinical, commercial, published, patented, or confidential antibody sequence. No sequence-database similarity search or patent-clearance opinion was performed.

The labels VH, VL, FWR, and CDR exercise file parsing and interface annotation only. They do not assert IMGT correctness, antibody folding, expression, stability, binding, affinity, specificity, safety, efficacy, or therapeutic relevance.

`candidate_regions.csv` has seven ordered regions per chain; their sequences concatenate exactly to the corresponding FASTA record. The antigen is copied from the project-authored CC0 Replay fixture input, but no Replay structure prediction, docking pose, score, or scientific output is reused.

Before running, copy this directory outside the source tree and replace:

- all four tool commands with their explicit locally installed executable paths;
- `REPLACE_WITH_PREINSTALLED_COLABFOLD_DATA` with a local ColabFold data directory containing all five `alphafold2_multimer_v3` parameter files.

The supplied policy is `offline_single_sequence`. It does not call the public ColabFold MSA service. The application refuses missing model parameters instead of downloading them.

The default LightDock 0.9.4 `fastdfire` ranking orders scoring values in descending order, so the smoke configuration explicitly declares `higher_is_better`. This is a within-run docking priority only.

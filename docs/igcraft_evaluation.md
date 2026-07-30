# IgCraft evaluation: not integrated

On 2026-07-30, the available external local IgCraft checkout was audited but
not executed or modified. It identified package version `0.0.1`, source commit
`4a053de8ed049f930679c91ac0bba0de3bb60296`, and MIT source licensing. The
available `final.ckpt` checkpoint was 2,539,158,372 bytes with SHA-256
`b7c4dcdd31be676d70fd1467f58feab3aab1cc955771e90468edb5b523274311`.

Its documented `graft_cdrs.py` contract requires a complete antibody PDB (and
optionally CDR structure), from which it extracts CDRs before generating
framework regions. It does not expose a paired six-CDR-string-to-VH/VL API or
CLI. Using a known VH/VL or a PDB constructed from it as a hidden input would
be template backfilling, not CDR-only generation. Installing another
environment cannot correct that input-contract mismatch.

Accordingly IgCraft is `audited_not_integrated`; no code, checkpoint, source,
environment, or output is distributed by Antibody Labmate. RFdiffusion and ESM
are not equivalent replacements for this missing contract. Re-evaluation
requires an official interface explicitly supporting paired generation from
six CDR strings. This finding says nothing about biological quality: no model
was run.

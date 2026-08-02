# 1AHW benchmark pilot: frozen engineering record

This is a narrow local software-and-evaluation record. It is not a scientific
benchmark result, docking-accuracy validation, affinity prediction, or
experimental claim.

## Metric boundary

`capri_dockq_2016_v1` is Labmate's primary antigen-receptor versus antibody
H/L-ligand-group geometry definition. Its Fnat, I-RMSD, and L-RMSD agreed with
official DockQ v2.1.3 on synthetic and pairwise-comparable validation cases
within strict numerical tolerances.

DockQ v2.1.3 reports interfaces pairwise. For a conventional H/L antibody it
does not expose one antigen-versus-H/L-group metric. A deterministic,
evaluation-only chain-group transformation preserved selected atom counts and
coordinates and worked on synthetic H/L group fixtures. On 1AHW, however,
DockQ selected the larger merged H/L group as receptor, reversing the benchmark
semantic receptor/ligand role for L-RMSD. Its group-converted L-RMSD was thus
not equivalent to Labmate's semantic L-RMSD. DockQ is retained only as
pairwise diagnostic output for this benchmark scope.

## Frozen 1AHW record

- The first local 1AHW run reached the bounded 1,800-second sampling timeout;
  its partial output remains retained as failure evidence.
- A single execution-only retry used the same scientific configuration with
  three verified LightDock worker cores and a 3,600-second timeout.
- The retry completed, produced ten valid poses, and froze their tool-derived
  cross-swarm order and hashes before any bound-reference evaluation.
- Rank 1 had a Labmate grouped CAPRI category of `incorrect`.
- Evaluation stopped after rank 1 because the DockQ group scope was not
  comparable. Ranks 2–10 were not evaluated; no top-k success rate or
  reference-selected oracle was emitted.

The frozen run data, poses, GSO files, diagnostic JSON, and local tool
installations are intentionally excluded from Git and release archives.

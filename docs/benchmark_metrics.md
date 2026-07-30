# Benchmark metrics

The existing optional `benchmark_local.compute_reference_metrics` remains
`legacy_reference_metrics`. It uses receptor C-alpha Horn alignment and ligand
heavy-atom RMSD, so changing it in place would silently alter existing reports.
The public benchmark contract instead uses the independent definition
`capri_dockq_2016_v1`.

Authoritative sources:

- CAPRI original assessment: <https://doi.org/10.1002/prot.10393>
- DockQ original paper: <https://doi.org/10.1371/journal.pone.0161879>
- Official implementation: <https://github.com/wallnerlab/DockQ>

Fnat uses native residue contacts defined by any non-hydrogen atom pair at
distance <=5 Å. Extra non-native contacts do not increase the numerator.
I-RMSD uses native interface residues defined at <=10 Å and superposes the
corresponding N/CA/C/O atoms of model and native interface. L-RMSD first
superposes corresponding receptor N/CA/C/O atoms, then measures RMSD over
corresponding ligand N/CA/C/O atoms. Antigen/receptor and antibody/ligand are
explicit semantic groups; chain length and letters are not used to guess roles.

The traditional category definition
`capri_quality_dockq_paper_2016_v1` implements the Boolean rules printed in
the DockQ paper, evaluating high, then medium, then acceptable, then incorrect
to resolve overlapping branches. DockQ continuous-score thresholds are not
substituted for the traditional categories.

Official DockQ v2.1.3 at commit
`d9cbb1940bb0f42db3257f7da3b0e96f162b94d9` was installed only in a temporary
environment and was not added as a project dependency. Five synthetic
model/native pairs and DockQ's official 1A2K example produced identical Fnat.
The largest I-RMSD absolute difference was
`9.752369551849963e-07 Å`; the largest L-RMSD difference was
`4.21717377369287e-07 Å`. This is implementation cross-validation, not
scientific performance evidence. DockQ's continuous score remains external
comparison metadata and is never combined with LightDock score.

PDB evaluation is fail-closed for unsafe paths, symlinks, non-finite
coordinates, ambiguous residue alignment, missing native interface residues,
overlapping semantic roles, and empty atom sets. Blank altloc is preferred to
A; other alternate locations are ignored and reported. Standard amino acids
in ATOM or HETATM are accepted; unsupported polymer residues fail. Insertion
codes remain part of residue identity. Implicit symmetry optimization is not
performed.

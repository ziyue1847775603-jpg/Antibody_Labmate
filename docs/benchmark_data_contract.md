# Public docking benchmark data contract

`BenchmarkDatasetManifest` records public bound/unbound cases without bundling
their PDB files. Each case declares source reference and license, manifest-
relative unbound receptor and ligand paths, a distinct bound reference used
only after docking, explicit chain roles, residue mapping, and SHA-256 values.

`labmate benchmark validate --manifest manifest.json` only revalidates this
metadata and hashes. It neither downloads data nor invokes docking. A bound
reference cannot be the same file as either docking input. `validated` is not
trusted from JSON; each file is rechecked locally.

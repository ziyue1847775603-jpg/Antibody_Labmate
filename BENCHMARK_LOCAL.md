# Phase 2b Benchmark Local

`benchmark_local` directly docks a local antibody PDB against a local antigen
PDB with a separately installed LightDock CLI. It does not accept VH/VL FASTA,
does not invoke ColabFold, does not download data, and does not use a network.

## Fixed scientific definitions

- The normalized antibody (`H/L` for VH/VL or `H` for VHH) is the receptor.
- All normalized antigen chains are the ligand.
- Receptor alignment is a least-squares Horn quaternion fit over exact-key
  matched receptor CA atoms.
- Exact atom keys are normalized chain ID, residue number, insertion code,
  residue name, and atom name.
- Ligand RMSD uses matched ligand heavy atoms after receptor alignment.
- Interface RMSD uses matched `N`, `CA`, `C`, and `O` atoms belonging to native
  interface residues after receptor alignment.
- A native contact is a receptor–ligand residue pair with any heavy-atom
  distance at or below 5.0 Å.
- Fnat is the fraction of native residue contacts recovered by the pose.
- Interface precision, recall, and F1 compare predicted and native interface
  residue identity sets across both partners.
- Unmatched atoms are omitted and counts are recorded. Evaluation fails if no
  required atom match remains. Every selected input residue must contain CA.
- Multi-antigen-chain mappings are supported. Reference mappings must normalize
  to exactly the same antibody and antigen chain set.

Top 1, Top 5, and Top 10 summaries operate on score-ranked poses from the same
case and declared score direction. They report the best observed metric within
each available prefix; they are not affinity or success claims.

## Fail-closed behavior

The mode rejects missing rights confirmation, URLs, path traversal, missing or
empty structures, multiple MODELs, altloc atoms, missing chains, overlapping
normalized chains, missing CA, duplicate atom/residue identities, invalid reference mappings, missing
executables, nonzero tool exits, incomplete swarm outputs, malformed GSO rows,
and score/pose count or chain/sequence/residue-key mismatches. It never
overwrites source inputs.

LightDock score direction is supplied by the user and is never inferred.
Selected GSO rows are written in explicit rank order, then mapped to
`lightdock_<zero-based-row-index>.pdb`. Filename sorting is never used to infer
score identity.

The setup, optimization, and conformation-generation executables are invoked.
The fourth explicit clustering executable is checked as part of the external
installation contract but is not invoked: benchmark ranking preserves the
declared raw score order and does not substitute a clustering-derived order.

## Outputs and status

A successful case produces `job.json`, `manifest.json`, `manifest.sha256`,
`poses.csv`, `interface_residues.csv`, optional `benchmark_metrics.csv`,
`case_summary.csv`, a self-contained `report.html`, logs, normalized input
copies, top pose PDBs, and a ZIP.

Reports are continuously labeled:

```text
BENCHMARK LOCAL
COMPUTATIONAL DOCKING BENCHMARK
NOT BINDING OR AFFINITY EVIDENCE
```

Current capability status is `implemented_unverified`. Synthetic/test-double
tests validate software contracts only. A separate real LightDock 0.9.4
synthetic software-integration smoke is recorded in
[`BENCHMARK_LOCAL_VALIDATION.md`](BENCHMARK_LOCAL_VALIDATION.md); it is not a
DB5.5 scientific benchmark and does not change the status to `verified_live`.

## Licensing and data boundaries

LightDock is GPL-3.0 software installed separately by the user. This MIT
repository neither bundles nor downloads it. PDB data licensing and patent
freedom to operate are separate questions; users remain responsible for both
input rights and software authorization.

Schrödinger/PIPER may be run independently by a licensed user as an external
commercial comparison. This repository does not invoke, bundle, parse
proprietary project files, or distribute any Schrödinger program, license,
secret, or output.

Computational docking results do not establish affinity, binding free energy,
specificity, safety, efficacy, therapeutic value, or experimental validation.

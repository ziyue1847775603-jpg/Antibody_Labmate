# Prediction-to-Docking Adapter

`PredictionArtifact` is a validated, backend-neutral antibody-structure
handoff. It records a run-relative PDB path and SHA-256, semantic heavy/light
chain map, exact observed sequences, residue/ATOM counts, provenance and only
backend-native metrics. `DockingInput` adds a separately validated antigen,
explicit antigen-receptor/antibody-ligand roles and docking parameters.

The adapter accepts a structure only after it is a regular non-symlink file
under the allowed root, has ATOM records, has exactly one unambiguous heavy and
light sequence match, and retains the input sequences. It rejects stale hash
claims, path escape, HTML/error files and unexpected extra protein chains.

ColabFold chain labels may be A/B and IgFold labels H/L: labels are mapped by
exact sequence, never guessed from filenames. IgFold `prmsd` remains
`backend_native_unscaled`; it is not pLDDT. ColabFold and IgFold metrics are
not compared or normalized.

The adapter does not alter Replay fixtures, run IDs or ranking. Existing Live
Local ranking remains ColabFold-specific because it uses pLDDT/PAE/ipTM.
Consequently the adapter proves an engineering handoff only: it does not
provide a cross-backend ranking, docking quality, binding affinity, scientific
accuracy or experimental validation. Docker remains Replay-only and Live
Remote is unavailable.

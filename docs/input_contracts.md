# Input contracts and capability boundaries

## ReplayInput

Six IMGT CDR strings plus the fixture antigen are accepted only for the fixed,
hash-verified Replay demonstration. The result is deterministic fixture replay:
no VH/VL framework is generated and no IgCraft, ColabFold, IgFold, or LightDock
process runs.

## LiveLocalInput

The existing Live Local workflow requires complete paired VH/VL FASTA, a region
annotation CSV, and an antigen PDB. The CSV labels regions for validation,
analysis, and the established ranking; it does not generate a framework and
CDR strings cannot replace complete VH/VL sequences.

## PredictionInput and DockingInput

Modular local prediction requires complete VH/VL, or docking may begin from a
locally revalidated `PredictionArtifact`, together with an antigen PDB. It may
produce a `DockingInput`, a tool-ranked pose and a manifest. It does not offer
CDR-only sequence generation or cross-backend ranking.

`CDR annotations` are not complete antibody sequences. `CDR preservation` is
not framework generation. Prediction-native metrics are not docking scores,
and a docking score is not affinity. A Replay result is not a new live
scientific computation.

## Missing contract

`six CDR strings -> complete paired VH/VL` is **not implemented**. No fixed
framework, reference sequence, RFdiffusion, RFantibody, ESM, or other tool is
substituted for that missing contract.

# RFantibody integration

Antibody Labmate invokes a user-managed installation of the official
RosettaCommons RFantibody pipeline through an isolated external interpreter.
It does not bundle RFantibody source, checkpoints, environments, caches, or
generated structures.

The verified local VHH route has three explicit stages: RFdiffusion antibody
backbone generation, official ProteinMPNN sequence design, and official
sequence-threaded PDB preparation. A previously hash-verified H/T backbone may
be resumed at ProteinMPNN; it is still recorded as a `backbone_generated`
intermediate and never treated as a final sequence.

The current bridge supports VHH only. It requires explicit local target chain
and hotspot inputs, a new output directory, a fixed external interpreter and
root, list-form subprocess calls, a bounded timeout, sanitized logs, and no
fallback to Replay, a reference antibody, or a fixed sequence. The generated
candidate is only format/provenance validated. It is not a binder prediction,
affinity result, epitope result, quality ranking, or therapeutic claim.

Streamlit Cloud remains Replay-only. Docker Replay does not contain
RFantibody, ProteinMPNN, models, or checkpoints.

One local engineering handoff has verified the VHH route from a
sequence-validated RFantibody candidate through offline ColabFold prediction
and the independent LightDock executor.  A VHH is represented as one explicit
antibody ligand chain; pose validation checks the exact validated antigen and
VHH chain, sequence, and residue-key contracts rather than imposing the
legacy paired H/L chain names.  This smoke verifies artifact handoff,
provenance, output discovery, and pose validation only.  LightDock's
tool-native score is not affinity, and the result does not establish binding,
epitope accuracy, or scientific validity.

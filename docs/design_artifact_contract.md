# DesignArtifact contract

`DesignArtifact` records the local engineering handoff from an official
RFantibody backbone intermediate to a sequence-validated design candidate.
It is an engineering provenance contract, not a scientific validation.

## Stages

- `backbone_generated` is an RFdiffusion structural intermediate. Its residue
  names, including any placeholder-looking loop residues, are not a final
  antibody sequence. It has `prediction_ready=false` and cannot enter a
  `PredictionArtifact`.
- `sequence_designed` is reserved for an official sequence-design output that
  has not yet passed all checks.
- `sequence_validated` requires official ProteinMPNN output, a controlled
  FASTA, a sequence-threaded PDB, exact PDB/FASTA sequence agreement, finite
  coordinates and native metrics, verified fixed-framework backbone atoms,
  and complete stage provenance. Only this stage has `prediction_ready=true`.

For the verified VHH route, a candidate contains one explicit heavy chain and
no light chain. `generation_index` is generation order only; it is not a
quality rank. ProteinMPNN's native negative log-likelihood remains an
unscaled tool-native value and is neither affinity nor a cross-stage score.

The artifact retains the backbone intermediate separately from final
candidates. Any required stage failure produces no prediction-ready candidate.
The contract makes no claim about binding, affinity, expression, stability,
specificity, therapeutic suitability, or experimental validity.

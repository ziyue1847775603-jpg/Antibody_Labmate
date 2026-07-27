# Live Local input template

Copy this directory outside the repository and replace the placeholder files.

`candidates.fasta` must contain paired complete variable-domain sequences:

```text
>CAND-001|VH
FULL_VH_SEQUENCE
>CAND-001|VL
FULL_VL_SEQUENCE
```

`candidate_regions.csv` must have `candidate_id,chain,region,sequence`. For each candidate and each H/L chain, the row sequences must concatenate exactly to the FASTA sequence. This lets the interface report identify CDR contacts without guessing numbering.

Set `rights_confirmed` to `true` only after confirming that you may process the sequences and structure. `score_direction` is mandatory because LightDock score semantics depend on the configured scoring function.

Live Local now fails closed unless ColabFold has an explicit MSA/network policy, an explicit `--msa-mode`, an explicit `--model-type alphafold2_multimer_v3`, and a `--data` directory containing all five preinstalled multimer-v3 parameter files. The template uses `single_sequence`, which does not contact the public ColabFold MSA service. Replace `REPLACE_WITH_PREINSTALLED_COLABFOLD_DATA` with the local ColabFold data directory. The application will not download missing model parameters.

The default LightDock 0.9.4 `fastdfire` ranking sorts scoring values in descending order, so this template declares `higher_is_better`. If you select another scoring function, verify and explicitly change both `score_name` and `score_direction`; the application never guesses the direction.

Prefer explicit executable paths in `project.json`. Bare command names are
accepted only when all four commands genuinely resolve on the process `PATH`:

```bash
labmate run project.json --mode live_local --output runs
```

A fully successful run is marked `LIVE LOCAL · VERIFIED LIVE`. This means only
that the recorded local integration completed and passed its mapping/privacy
checks. It is a within-run computational priority, not binding evidence,
affinity, binding free energy, efficacy, or a therapeutic claim. See
[`LIVE_LOCAL_VALIDATION.md`](../../LIVE_LOCAL_VALIDATION.md) for the exact
validated scope.

# Multi-pose benchmark execution contract

The independent LightDock executor can retain 1–100 rows across every
current-run `swarm_<non-negative integer>` directory. Each GSO file is parsed
strictly and hashed. The executor rejects missing, extra, malformed, symlinked,
or escaping swarm paths and non-finite scores.

LightDock provides a native score and a row identity inside each swarm, but it
does not provide one cross-swarm global rank. Labmate therefore derives
`global_tool_score_rank` using:

1. one declared native score name and direction for every swarm;
2. native score (descending for `fastdfire` / `higher_is_better`);
3. numeric `swarm_id`;
4. original `gso_row_id`.

The definition ID is `lightdock_native_score_cross_swarm_sort_v1`.
`tool_native_rank` remains only as a backward-compatible alias and must not be
described as a LightDock-native global rank. Each pose records the score,
direction, swarm-local rank, GSO row, GSO hash, derived global rank, generation
and validation status, and duplicate-hash group.

Failure does not close rank gaps or renumber later rows. If derived rank 1
fails validation, selection uses
`first_validated_global_tool_score_rank`; if no pose validates, execution fails.
Duplicate hashes remain as separate ranked records and are reported rather than
removed.

Tool-ranked top-k asks whether an acceptable-or-better pose occurs among the
first k derived ranks. A separately labelled `oracle_best_of_n` may use bound
reference metrics to describe sampling potential, but it is not deployment
ranking. The bound reference is never an execution input. Synthetic
fake-executable tests verify mechanics only and are not LightDock or scientific
benchmark results.

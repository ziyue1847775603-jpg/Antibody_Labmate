# Demo Script — Under Three Minutes

> Archived Phase 1 Replay demo script. The Streamlit demo remains Replay-only;
> current Live Local CLI status is documented in `LIVE_LOCAL_VALIDATION.md`.

Target runtime: **2:35–2:50**. Spoken copy: approximately 330 words.

## 0:00–0:20 — Truthful scope

**Action:** Open the Streamlit app at the New Run tab. Keep the red banner in
frame.

**Say:** “Antibody Labmate is a transparent workflow prototype for turning six
IMGT CDR inputs and an antigen PDB into auditable candidate artifacts. This is
the Phase 1 Replay MVP. The red REPLAY label remains visible throughout, and no
Live model or docking tool is running.”

## 0:20–0:45 — Inputs and capability boundary

**Action:** Point to the six CDR fields, antigen parser result, and three
capability cards.

**Say:** “The demo uses project-authored CC0 synthetic data. Pydantic validates
the six CDRs separately, while the PDB parser enforces size, atom, chain, model,
and alternate-location rules. Replay is available; Live Local and Live Remote
are explicitly unavailable. LightDock is only the default provider contract
for parsing a verified fixed schema—it is not executed.”

## 0:45–1:10 — Fail-closed provenance

**Action:** Briefly edit one CDR and click Run to show rejection. Click Load
verified demo to restore the input.

**Say:** “A fixed result is never applied to arbitrary input. Replay verifies
the normalized antibody hash, the antigen’s raw-byte hash, the configuration
bundle hash, and every fixture file hash. Even a valid but different CDR is
rejected before results are materialized.”

## 1:10–1:35 — Verified run

**Action:** Click Run verified REPLAY, then open Run Status.

**Say:** “With the exact fixture restored, the backend advances through an
explicit stage state machine. Every stage records Replay execution. The app
parses fixed candidate, structure, and docking artifacts, then reruns its own
interface geometry, ranking, provenance, and report generation.”

## 1:35–2:15 — Results and artifacts

**Action:** Open Results. Scroll across ranking and interface rows; show the
download buttons.

**Say:** “The ranking retains raw metrics, normalization directions, component
scores, weights, ties, clash checks, and sensitivity analysis. The interface
CSV records the residue-level contact evidence. Judges can download the
candidate ranking, interface residues, a self-contained offline HTML report,
the provenance manifest, and the complete run ZIP.”

## 2:15–2:45 — Close

**Action:** Open the report in a separate tab and show its REPLAY disclosure and
manifest section.

**Say:** “The report and manifest use relative artifact paths and contain no
secrets or machine-specific paths. This release demonstrates reproducible
workflow orchestration and honest capability reporting—not experimental
binding, affinity, safety, or therapeutic claims. The next phase starts only
after real providers are independently licensed and validated.”

## Recording checklist

- Record the browser only; do not expose terminal usernames or local folders.
- Keep the REPLAY banner visible in every app view.
- Do not say that LightDock, IgCraft, or ColabFold ran.
- Keep the final video below 3:00 and verify audio before upload.

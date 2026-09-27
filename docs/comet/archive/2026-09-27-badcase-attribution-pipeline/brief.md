# Outcome

Turn the decision traces (Phase 1) into a **bad-case lifecycle with
deterministic attribution**: a human annotation marks a trace as a mismatch;
the pipeline attributes the failure to one of five root-cause categories and
emits a review artifact (a bad-case candidate following architecture §10.2
plus a suggested patch target), **never applying anything automatically**.
After ratification the existing flow continues: fix → paired eval gate (Phase
0) → regression set.

# Scope

1. **New `agent/sap_nexus_agent/badcase_attribution.py`.**
   - `attribute_failure(observed, expected) -> AttributionResult` with
     categories: `registry-alias`, `extraction`, `caliber`, `binding`,
     `governance`; each result carries `rationale`, `evidenceRefs`, and
     `patchTarget` (a concrete pointer, e.g.
     `registry/capabilities.yaml#MM.Inventory.GetAvailability.aliases`).
   - Deterministic rules keyed on expected vs actual decision, `errorType`,
     `missingParameters`, and whether intent matched.
2. **New `agent/sap_nexus_agent/badcase_pipeline.py`.**
   - Load trace JSONL + a human annotation file
     (`[{traceId, expectedDecision, expectedCapabilityId?}]`); traces flagged
     `userCorrection: true` are also listed as review candidates.
   - For each confirmed mismatch produce one review artifact: bad-case
     candidate (§10.2 shape, `status: candidate`, `sourceTraceId`,
     `utteranceHash`, utterance left for ratification) + attribution +
     suggested patch; deterministic clustering groups same
     `(category, capabilityId, errorType)` cases.
   - Write artifacts to `runtime/badcase-review/<caseId>.json`; nothing is
     applied or written into `evals/` automatically.
3. **`scripts/attribute_badcases.py` thin CLI:**
   `.venv/bin/python scripts/attribute_badcases.py --traces <file>
   --annotations <file> [--output-dir <path>]`.
4. **Tests under `agent/tests/`.**

# Non-goals

- No LLM calls; clustering is deterministic (LLM-assisted clustering is a
  future enhancement).
- No auto-apply of patches, no writes to `evals/` or `registry/`, no
  modification of shipped behavior.
- No runtime feedback UI; annotations come from a file.
- No ontology/spec schema changes.

# Acceptance examples

1. Annotate a trace where an inventory SELECT was expected but REJECT came
   back with `UNKNOWN_INTENT` → artifact attributes `registry-alias`,
   suggests patching inventory aliases/keywords; case is `candidate` with
   `sourceTraceId` and no utterance text.
2. Annotate "expected SELECT, got CLARIFY(missing plant)" where the trace
   shows the intent capability matched → attributes `extraction`.
3. Same-category cases land in one cluster group; running the script is
   side-effect free outside the output dir; new tests and full agent suite
   green.

# Constraints and invariants

- Attribution is deterministic and explainable: every category comes with the
  rule/evidence that produced it.
- Human gate: artifacts are proposals; the bad case only becomes a regression
  case after ratification and a passing paired-eval run.
- No credentials/secrets; artifacts reuse trace privacy rules (no raw
  utterance).

# Decisions

- **D1 (2026-09-27):** Five categories and fixed rule order (intent-match
  first) so attribution is stable; ambiguous signals attribute to the most
  specific applicable rule and list secondary signals.
- **D2 (2026-09-27):** Review artifacts live under gitignored `runtime/`;
  ratification promotes them manually into `evals/`.

# Open questions

- Resolved 2026-09-27 via autonomous `/goal` directive.

# Verification expectations

- New unit tests cover each attribution rule and the pipeline/CLI; full agent
  pytest green.
- End-to-end: build traces, annotate, run script, inspect artifacts.
- `git status --short` before/after.

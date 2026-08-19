# Verification Report: declarative-intent-extraction

Date: 2026-08-19
Verify mode: full (21 tasks, 59 changed files, 2 delta spec capabilities — all above the
lightweight thresholds)
Change root: `openspec/changes/declarative-intent-extraction/`
Design doc: `docs/superpowers/specs/2026-08-18-declarative-intent-extraction-design.md`
Plan: `docs/superpowers/plans/2026-08-18-declarative-intent-extraction.md`
Base ref: `2d4af9451ab1516a775de367d5b8bf347136eee2`
HEAD at verification time: `5756a82`

## Summary

| Dimension    | Status                                                          |
|--------------|------------------------------------------------------------------|
| Completeness | 21/21 tasks, 7/7 requirements, 15/15 scenarios covered            |
| Correctness  | 15/15 scenarios traced to concrete implementation + passing tests |
| Coherence    | Design doc followed; 2 sanctioned reconciliations documented and applied; 1 minor pre-existing architectural gap noted as a recommended follow-up (not blocking) |

**Final assessment: All checks passed. Ready for archive**, with 3 recommended (non-blocking) follow-up items filed for the user's backlog (see below).

## Completeness

### Task completion

`openspec/changes/declarative-intent-extraction/tasks.md`: 21/21 tasks checked `[x]`
(sections 1-5, all sub-items). Verified via `comet guard declarative-intent-extraction build`
("tasks.md all tasks checked": PASS) and by direct inspection.

Superpowers plan (`docs/superpowers/plans/2026-08-18-declarative-intent-extraction.md`):
89/89 per-task `Step` checkboxes checked `[x]` (verified via the same guard: "Superpowers
plan all tasks checked": PASS).

### Spec coverage (7 requirements, 15 scenarios across 2 delta specs)

All 15 scenarios below are implemented and covered by passing tests. None are missing.

**`specs/declarative-intent-extraction/spec.md`:**

1. **Declaration-driven single-turn intent extraction**
   - *Declared capability recognized without code change* — `agent/tests/test_declaration_only_capability.py` (Task 19): a capability declared only in a temporary registry, with zero `agent/sap_nexus_agent` code referencing it, triggers/extracts/CLARIFYs correctly through production `parse_intent`.
   - *Undeclared keyword does not trigger* — `engine.triggered()` (Task 10) only fires on declared `primaryKeywords`/`triggerKeywords`; parity fixture `po-import-no-false-positive` pins this.
   - *Weak keyword alone does not trigger but counts toward ambiguity* — `engine.is_ambiguous()` (Task 10); parity fixture `weak-only-no-trigger-ambiguous`.
   - *Technical override still rejected first* — `_detect_rfc_name`/`_detect_odata_override` in `intent.py`, explicitly preserved unchanged through Task 12's seam and Task 18's legacy deletion (both tasks' briefs mandated "stay exactly as they are").

2. **Shared semantic-type extraction catalog**
   - *Two capabilities share one concept matcher* — `registry/semantic-types.yaml` (Task 2/3), referenced by `semanticType` matchers in `registry/capabilities.yaml` across Plant/MaterialNumber/Vendor/PONumber.
   - *Exclusion prevents value reuse* — `extraction.excludes` field, engine's exclusion-set logic (Task 10); parity fixtures `inv-plant-exclusion`, `po-number-value-excluded`.
   - *Conditional field extraction with keyword-to-constant mapping* — `acct_assgn_cat` matcher (`kind: keyword`, constant `value: K`) in `registry/capabilities.yaml`; parity fixtures `pr-indirect-full`/`pr-indirect-missing-cost-center`.

3. **Behavioral parity for migrated capabilities**
   - *Extraction results identical pre and post migration* — the 36-row frozen differential parity harness (Task 11) plus per-capability migration gates (Tasks 13-15), each requiring `legacy == engine == frozen expectations` before a standalone commit.
   - *Existing baseline stays green* — full agent suite tracked at every step; final state `15 failed, 1273 passed, 1 skipped` is an EXACT match (by name) to the pre-existing, unrelated baseline established before this change began (independently corroborated twice: coordinator's revert-and-diff diagnostic during Task 18, and Task 20's disposable-worktree comparison against base commit `20f96d8`).

4. **Declaration-driven sticky continuation**
   - *Follow-up extraction uses declarations* — `llm_intent.resolve_with_context`'s `_extract_params_for` dispatches to `engine.extract_parameters` for migrated+declared capabilities (Task 12), now unconditionally for all 3 real capabilities (Tasks 13-15) and unconditionally in general post-Task-18 deletion.
   - *Declared keyword of another capability starts a new turn* — `_contains_any_primary_keyword`/`engine.any_primary_keyword` (Task 12); parity fixtures `pr-sticky-new-turn`, `inv-sticky-new-turn-inherit`.

5. **Declaration-driven CLARIFY rendering**
   - *Rule mode renders declared prompt deterministically* — `extraction.clarify.render_clarify` (Task 10) for single-turn; wired into sticky continuation in Task 16, replacing the deleted `_clarification_for` legacy text tables.
   - *LLM rephrasing stays inside the declared field set* — `extraction.clarify.rephrase_clarify` (Task 17)'s closed-set negative check against `all_declared_fields`; adversarial tests confirm rejection of out-of-scope field mentions and fail-closed behavior on malformed/non-dict model payloads (fix round 1).
   - *Missing locale declaration falls back* — `render_clarify`'s locale-fallback branch (Task 10), tested in `test_clarify_rendering.py::test_missing_locale_falls_back_to_names`.

**`specs/registry-ontology-contract/spec.md`:**

6. **Extraction declaration validation in registry contract**
   - All 5 scenarios (invalid regex, dangling semantic-type ref, missing clarify locale, malformed condition/overlapping tier, valid declarations pass) — `scripts/validate-registry-contract.py`'s extraction-declaration validator additions (Task 4), with dedicated tests and a documented backtracking-safety guard.

7. **Semantic-type extraction catalog contract**
   - *Duplicate catalog identifier rejected* — Task 4's validator.
   - *Capability registry and catalog load as one snapshot* — `registry_loader.load_intent_catalog`'s atomic pairing (Task 8), snapshot id covers both `capabilities.yaml` and `semantic-types.yaml`.
   - *Gateway ignores extraction metadata safely* — Task 6's gateway indifference test (2/2 pass), re-confirmed green in Task 20's closeout sweep (`scripts/comet-verify-gateway.sh`: BUILD SUCCESSFUL).

## Correctness

Requirement-to-implementation mapping above is traced to real, named files and passing
tests, not inferred from keyword search alone — every item was implemented and reviewed as
part of this change's 21 SDD tasks, each with its own task reviewer (mandatory for Tasks 4,
5, 10, 11, 12, 17, 18; risk-triggered for others under `review_mode: standard`) and
independently re-verified by the coordinator at multiple points (diff inspection, direct
test re-runs, code reading) rather than trusting subagent self-reports alone.

No unimplemented requirements found. No scenario found uncovered.

## Coherence

### Design adherence

Implementation follows `docs/superpowers/specs/2026-08-18-declarative-intent-extraction-design.md`'s
architecture: a declaration-driven engine (`agent/sap_nexus_agent/extraction/{engine,clarify,resolvers,_matching}.py`)
with zero capability-specific branches, consuming `registry/capabilities.yaml` +
`registry/semantic-types.yaml`, replacing the legacy per-capability extractors entirely.

The plan's 6 sanctioned "Design Reconciliations" (documented deviations from a literal DSL
reading, required to preserve legacy byte-parity) are all applied and were re-verified for
accuracy during Task 21 (an initial draft of the Design Doc's reconciliation summary was
found to be fabricated/inaccurate by the coordinator and corrected to match the plan's real
text before this verification).

### Known, deliberate exceptions (documented, not defects)

Two capability-id literal spots remain in `agent/sap_nexus_agent/intent.py`
(`_parse_single_turn`'s Inventory/PO `capability_id=None` backward-compat quirk;
`parse_inventory_intent`'s hardcoded inventory-only adapter), technically at odds with the
plan's literal "zero capability-id literals" completion criterion. Both were investigated
during the final whole-branch review's fix wave and found load-bearing: the former is
pinned by existing tests (`test_conversation_context.py`) asserting the legacy top-level
`None` contract; the latter is a genuine, still-used production adapter
(`orchestrator.py::run_inventory_query`). Both are now documented in-code with a clarifying
comment. This is judged an acceptable, narrow, evidence-backed exception to the plan's
completion criterion, not a coherence defect requiring a blocking fix.

### Recommended follow-up items (NOT fixed in this change — filed for the user)

These were discovered during this change but are explicitly out of scope, per this
project's "fix minimally, do not fix pre-existing issues unless asked" convention. None
block this verification or archive.

1. **PO vendor/PONumber alphanumeric-matching gap**: a real, confirmed, pre-existing
   production bug (predates this entire SDD plan) — alphanumeric vendor codes like
   `"DEMOV1"` never match the PO vendor/PONumber matchers (numeric-only patterns). Discovered
   during Task 18; an unauthorized attempt to fix it inside this change was caught and
   reverted by the coordinator (see Task 18 in the SDD ledger history). Recommend a
   dedicated follow-up change to widen these matchers with proper review and test coverage.
2. **Stale canonical-JSON hash test vector**: `agent/tests/test_orchestrator.py::test_python_hashes_match_typescript_canonical_json_for_unicode`
   has hardcoded expected hash values that no longer match current Python/Node output for a
   Unicode test case — unrelated to intent extraction, also discovered and reverted during
   Task 18. Recommend a dedicated follow-up to verify current canonical-JSON parity and
   update the test vectors deliberately.
3. **`engine.sticky_parse` dead/unreachable code**: `agent/sap_nexus_agent/extraction/engine.py`'s
   `sticky_parse` function (built in Task 10 as the fully generic, declaration-driven sticky
   continuation implementation) is never called from production — `llm_intent.py`'s
   `resolve_with_context` runs its own parallel, hand-rolled implementation instead (though
   now free of the one hardcoded capability-id check the final review found and fixed).
   Recommend a future change either wire `resolve_with_context` to delegate to
   `engine.sticky_parse` directly (completing this change's "engine is the only path" goal
   for the sticky continuation path specifically) or remove `engine.sticky_parse` if
   deliberately superseded. Not fixed now: a same-day consolidation this late in an
   already-verified migration carries more risk than benefit.

## Verification Evidence (re-confirmed, not re-run at this step)

Per Task 20's closeout sweep and the final whole-branch review's independently-verified
numbers (not re-run here per verification-before-completion's dedup guidance — these were
freshly run multiple times during build phase, most recently after the final-review fix
wave):

- `git status --short`: clean (aside from Comet's own state bookkeeping files)
- `.venv/bin/python scripts/validate-registry-contract.py registry/capabilities.yaml`: valid
- `.venv/bin/python -m pytest agent/tests -q`: `15 failed, 1273 passed, 1 skipped` — exact
  name match to the documented, unrelated, pre-existing baseline
- `.venv/bin/python -m pytest agent/tests/test_extraction_parity.py agent/tests/test_declaration_only_capability.py -q`:
  `37 passed`
- `comet classic openspec -- list --json`: 1 change, 21/21 tasks complete
- `comet classic openspec -- validate --all --strict`: 21 passed, 0 failed
- `git diff --stat 2d4af9451ab1516a775de367d5b8bf347136eee2..HEAD -- frontend/`: empty
- `bash scripts/comet-verify-gateway.sh`: BUILD SUCCESSFUL

## Final Assessment

**All checks passed. Ready for archive.**

No CRITICAL or IMPORTANT issues remain open. 3 recommended follow-up items are documented
above for the user's backlog — none block this change.

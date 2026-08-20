# Verification Report: declarative-intent-hardening

Date: 2026-08-20
Verify mode: **full** (16 tasks, 1 delta spec, 27 changed source files — above the lightweight thresholds)
Change root: `openspec/changes/declarative-intent-hardening/`
Design doc of record: `docs/superpowers/specs/2026-08-19-declarative-intent-hardening-design.md`
Plan: `docs/superpowers/plans/2026-08-19-declarative-intent-hardening.md`
Base ref: `c28288425dc...` (`.comet.yaml`); plan frontmatter cites `06966c7`, a descendant — the
44-vs-27 file gap between them is entirely Comet/OpenSpec artifacts and the design doc, no source
code, so every source-level conclusion below holds from either base.
HEAD at verification time: `e1a7a6e` + uncommitted frontend gate fix (see Divergence 3).

All evidence in this report was produced fresh in the verify phase. Build-phase evidence was not
reused; where this report agrees with `openspec/changes/declarative-intent-hardening/verification.md`
(the build-phase task-4.2 audit) the claim was independently re-established, and two of that
document's conclusions are revised below.

## Summary

| Dimension    | Status |
|--------------|--------|
| Completeness | 16/16 tasks checked; 21/21 delta-spec scenarios enumerated and traced |
| Correctness  | 6/6 executable gates green; the one live defect found in build review re-verified fixed at HEAD |
| Coherence    | Design decisions §3.1–§3.7 followed; 4 divergences found, all **resolved** by artifact correction under explicit user ruling |

**Final assessment: verification passes.** Four divergences were found and are recorded below with
their resolutions. All were closed by correcting artifacts to match what shipped — no implementation
was modified during verify. The user ruled on each: narrow the spec to what shipped (Divergences 1
and 2), keep the frontend gate fix and correct the artifacts that excluded it (Divergence 3). The
design-of-record safety correction (Divergence 4) was applied as documentation.

Fourteen items are carried forward in the deferred ledger; items 13 and 14 were filed during verify
as the follow-ups to Divergences 1 and 2. Two of them are gates on future work rather
than on this change and must be closed before the actions that would make them live.

## Completeness

### Tasks

`openspec/changes/declarative-intent-hardening/tasks.md`: 16 `- [x]`, 0 unchecked.
Two tasks (3.4, 4.1) are verification-only and carry checkoff commits without implementation
commits — a documented coordinator ruling
(`docs/superpowers/plans/2026-08-19-declarative-intent-hardening.md:2513`), not an ordering anomaly.

### Delta-spec scenario coverage

`specs/declarative-intent-extraction/spec.md` carries **21 scenarios** across 5 requirements
(2 ADDED, 3 MODIFIED, 0 REMOVED). The plan's traceability table enumerates only 17 — it omits all
four scenarios of the MODIFIED requirement "Declaration-driven single-turn intent extraction". Those
four are covered in the tree (`agent/tests/test_declaration_only_capability.py:100`,
`agent/tests/test_extraction_engine.py:50`/`:58`/`:65`/`:122`,
`agent/tests/test_capability_selector.py:45`/`:61`/`:74`), so the omission is a gap in the plan's
table, not in the suite.

Coverage at the scenario level: **15 GENUINE, 5 PARTIAL, 1 GAP** as measured before the spec
narrowing described in Divergences 1 and 2. After that narrowing, the two escalated scenarios ("Named
shape consolidates duplicated patterns", "Regex escape hatch requires justification") are pinned
genuinely by tests that already existed, giving **17 GENUINE, 3 PARTIAL, 1 GAP**. The narrowing
changed the spec to match shipped behavior and its existing pins; it did not add or weaken any test.

- **GAP — "Two capabilities share one concept matcher".** No test loads two capabilities whose
  inputs reference the same `semanticType`, and the real registry cannot supply the coverage: the
  six `semanticType` refs are pairwise distinct (`MaterialNumber`, `Plant` on
  `MM.Inventory.GetAvailability`; `Quantity`, `Unit`, `Date`, `PurchasingGroup` on
  `MM.PR.CreateDraft`; `MM.PurchaseOrder.GetList` uses inline regex matchers only).
  **Verified not a regression of this change:** `git show c28288425dc:registry/capabilities.yaml`
  yields the identical six refs, so the disjointness is inherited. The predecessor report
  `docs/superpowers/reports/2026-08-19-declarative-intent-extraction-verify.md:47` claimed this
  scenario covered "across Plant/MaterialNumber/Vendor/PONumber"; that claim did not hold at its own
  base either. Carried as a deferred item, not attributed to this change.
- **PARTIAL (5)** — scenarios 1, 5, 13, 14, 18, 20 in the build audit's numbering: the named pin is
  weaker than the scenario text. Two of these are more than weak pins and are escalated to
  Divergences 1 and 2 below.

## Correctness

### Executable gates (all re-run fresh in verify)

| Gate | Result |
|---|---|
| `.venv/bin/python -m pytest -q` (repo root) | **1374 passed, 7 skipped, 2 xfailed, 0 failed** |
| `.venv/bin/python -m pytest agent/tests -q` | 1345 passed, 1 skipped, 2 xfailed, 0 failed |
| `scripts/validate-registry-contract.py registry/capabilities.yaml` | exit 0 — `regex matchers in use: 17 (semantic-type catalog 9 + capability-level 8)`, 15 deprecation warnings |
| `openspec validate --all --strict` | 22 passed, 0 failed |
| `run_eval_file(evals/matcher_cases.yaml)` | **23/23** — design §4 equivalence gate |
| `npm --prefix frontend run verify` | exit 0 — 52 files, 525 tests, `next build` ✓ |

The root-level count (1374) exceeds the agent-only count (1345) because collection from the repo root
also picks up `services/odata-service/tests/`; the 6 extra skips are `SAP_ODATA_LIVE`-gated. Verified
by `--collect-only` (1383 collected). Not a regression.

**Honest caveat on 23/23, carried from the build audit and re-confirmed.** The figure comes from
*running* the eval. `agent/tests/test_eval_runner.py:114` asserts `summary.failed == 0` and
`summary.passed == summary.total` but only `summary.total >= 5`, so deleting cases from
`evals/matcher_cases.yaml` keeps the test green. The design §4 "matcher_cases stays 23/23"
equivalence gate is therefore half-enforced by the suite: regressions in extraction are caught,
silent shrinkage of the case file is not.

### The one live defect from build review — re-verified fixed at HEAD

The final review found that `prefixed`/`suffixed` named kinds carved a 4-character value window out
of the middle of a longer adjacent alphanumeric token, because
`agent/sap_nexus_agent/extraction/_matching.py` compiled a lookaround guard only on the bare
`valueShape` kind. Combined with the B1.3/B1.5 loosening of `valueShapes.plantCode` to
`^[A-Z0-9]{4}$`, this produced a **wrong plant reaching SAP with `missing=[]` and no
clarification** — the carved value satisfies the input's declared `pattern`, so the gateway
validator accepts it. This is a silently-wrong READ result, not a validation error.

Re-measured against the real registry at HEAD via `engine.extract_parameters` on
`MM.Inventory.GetAvailability`:

| utterance | expected (post-fix) | measured at HEAD |
|---|---|---|
| `查询库存 DEMOA2 工厂 1000` | `1000` | `1000` ✓ |
| `查询 DEMOA2 在 5100 的库存` | `5100` | `5100` ✓ |
| `物料 1000 工厂库存` | `1000` | `1000` ✓ |
| `查询在 DEMOA2 的库存` | `None` | `None` ✓ |

End-to-end state on the first row: `params = {'plant': '1000', 'material': 'DEMOA2'}`,
`missing = []`. The fix holds. The AB12 contract of design §3.2 also holds on the named-kind path
(`在 AB12 的库存` → `AB12`, `AB12 工厂库存` → `AB12`).

### B2 durable round budget (goal-level check)

`ConversationReadState.clarify_rounds` (`agent/sap_nexus_agent/read_context.py:471`) verified
behaviorally:

- `to_dict`/`from_dict` round-trip of `{"MM.PR.CreateDraft": 2}` preserves the mapping;
- a legacy payload with no `clarifyRounds` key deserializes to `{}` — the schema-compatible
  migration design §3.5 requires;
- an empty mapping is omitted from the payload entirely (no schema noise).

Increment sites: `agent/sap_nexus_agent/extraction/engine.py:245-251`,
`agent/sap_nexus_agent/llm_intent.py:623-641`; propagation
`agent/sap_nexus_agent/orchestrator.py:970-976`.

## Coherence

### Design decisions §3.1–§3.7

Followed, with one deliberate deviation (Divergence 4) and one naming imprecision:

- **§3.1** named-kind compilation — implemented in `_compile_named_kind`, **but the compiled patterns
  now differ from the design text on purpose**; see Divergence 4.
- **§3.2** AB12 boundary — held on the named-kind path; the PR capability's legacy matcher does not
  reach it (deferred item 6).
- **§3.3** validator metric — the count line is implemented (`regex matchers in use: 17`); the
  justification error is enforced for catalog matchers only; see Divergence 2.
- **§3.4** `PR.CreateDraft.plant` pattern — `pattern: '^[A-Z0-9]{4}$'` present
  (`registry/capabilities.yaml:394`).
- **§3.5** clarify strategy and round budget — implemented and verified above.
- **§3.6** binding model and alias normalization — implemented; the xfail placeholder named in the
  design (`test_binding_capability_output_not_implemented`,
  `agent/tests/test_binding_sources.py:250`) xfails with `DID NOT RAISE`, i.e. it pins the *unwired*
  state rather than the not-implemented reason. The design's actual requirement — a strict xfail on
  `NotImplementedError` naming the dependency-edge landing point — is met by the sibling
  `test_capability_output_source_resolution_is_not_implemented_yet` (`:172`,
  `match="dependency-edge binding"`). Satisfied in substance, misattributed by name.
- **§3.7** testing matrix — the ten rows map to existing tests; two rows are the PARTIAL pins
  escalated below.

### Design doc locatable (check item 7)

`docs/superpowers/specs/2026-08-19-declarative-intent-hardening-design.md` exists (9982 bytes) with
explicit numbered sections §1–§6 and subsections §3.1–§3.7. The build audit's routed finding B
("Design §3.7 is a stale reference") is **not confirmed**: §3.7 exists as "Testing matrix", and every
tracked `Design §3.x` citation resolves against this document.
`openspec/changes/declarative-intent-hardening/design.md` is a condensed sibling with unnumbered
decisions 1–6; its Decision 6 corresponds to design **§3.6**, not §3.7.

---

## Divergences and their resolutions

All four were found by measurement in the verify phase and resolved by artifact correction. No
implementation file was modified during verify; the delta spec, proposal, both design documents, and
this report were.

### Divergence 1 — delta spec required `valueShape` references that do not exist (RESOLVED: spec narrowed)

Scenario "Named shape consolidates duplicated patterns"
(`specs/declarative-intent-extraction/spec.md:162-167`):

> **THEN** the pattern is defined once in the catalog `valueShapes` section **and both inputs
> reference that named shape**

and the owning requirement states normatively:

> Named shapes duplicated across capability inputs SHALL be consolidated into `valueShapes` entries.

Measured: `registry/capabilities.yaml` contains **zero** occurrences of `valueShape`, and all three
plant inputs still declare the literal pattern (`:79`, `:265`, `:394` — `^[A-Z0-9]{4}$`). The change
*aligned* the three duplicated patterns to the catalog shape's value; it did not replace them with a
reference. `test_pr_declaration_parity_constants`
(`agent/tests/test_extraction_declarations.py:521`) pins string equality with the shape's value, not
a reference to the named shape.

No runtime defect follows (the values are identical today), but the scenario's second THEN clause was
unimplemented, and archiving would have published it as satisfied.

**Resolution (user ruling: narrow the spec to what shipped).** The scenario's THEN now reads "the
pattern is defined once in the catalog `valueShapes` section and the duplicated input patterns are
aligned to that shape", and the owning requirement's normative sentence was changed from
"consolidated into `valueShapes` entries" to "defined once as a `valueShapes` entry, and the
duplicated input patterns SHALL be aligned to that shape". This is exactly what
`test_pr_declaration_parity_constants` (`agent/tests/test_extraction_declarations.py:497`) and
`test_catalog_value_shapes_plant_code` (`:216`) pin, so the scenario moves from PARTIAL to GENUINE.
The reference mechanism is filed as deferred item 13 — it needs schema and loader support that does
not exist today, which is why implementing it here would have been new mechanism rather than a fix.

### Divergence 2 — 8 capability-level regex matchers escaped the justification gate (RESOLVED: scenario scoped to the catalog)

Scenario "Regex escape hatch requires justification" (`spec.md:156-160`) is written unqualified:

> **WHEN** the registry is validated and a matcher uses the `regex` kind without a non-empty
> `justification` — **THEN** validation fails with an error naming the matcher

and the requirement text says "**every** regex matcher MUST carry a `justification` field".

Measured: `require_justification=True` is passed at exactly one call site,
`scripts/validate_registry_contract.py:127` (catalog entries). The capability-level sites at `:213`
(`binding source`) and `:224` (`extraction`) use the default `False`. Enumerating the live registry
yields **8 capability-level regex matchers, all without `justification`**, and validation exits 0:

| capability.input | pattern |
|---|---|
| `MM.PurchaseOrder.GetList.poNumber` | `(?<!\d)(\d{10})(?!\d)` |
| `MM.PurchaseOrder.GetList.poNumber` | `采购订单\s*([A-Z0-9]{4,10})` |
| `MM.PurchaseOrder.GetList.vendor` | `供应商\s*([A-Z0-9]{1,10})` |
| `MM.PurchaseOrder.GetList.plant` | `(?:工厂\s*(\d{4}\|[A-Z]\d{3}))\|(?:(\d{4}\|[A-Z]\d{3})\s*工厂)` |
| `MM.PurchaseOrder.GetList.material` | `物料\s*([A-Za-z0-9][A-Za-z0-9\-/]+)` |
| `MM.PR.CreateDraft.material` | `物料\s*([A-Za-z0-9][A-Za-z0-9\-/]+)` |
| `MM.PR.CreateDraft.plant` | `工厂\s*(\d{4}\|[A-Z]\d{3})` |
| `MM.PR.CreateDraft.cost_center` | `成本中心\s*(\d+)` |

The scope is genuinely ambiguous in the artifact: the sentence sits inside a paragraph that opens
"**Catalog matchers** SHALL use named kinds…", so a catalog-scoped reading is defensible and is
satisfied. Under the plain reading of "every regex matcher", the live registry falsified the
scenario.

**Resolution (user ruling: narrow the scenario to catalog matchers).** The requirement now reads
"every regex matcher in the semantic-type catalog MUST carry a `justification`", the validator clause
now says the count reports "catalog and capability-level counted separately", and the scenario's WHEN
is scoped to "a semantic-type catalog matcher". An AND clause was added to make the shipped behavior
explicit instead of silent: capability-level regex matchers are included in the reported count without
being rejected, so the metric stays reducible as they migrate to named kinds.

Pin status after narrowing: the WHEN/THEN pair is now pinned genuinely rather than weakly by
`test_catalog_schema_rejects_regex_without_justification`
(`agent/tests/test_extraction_declarations.py:684`) and `test_unjustified_catalog_regex_rejected`
(`:692`), which exercise exactly the catalog path. The new AND clause is pinned for inclusion by
`test_regex_matcher_count_is_observable_metric` (`:710`) and for non-rejection by
`test_real_registry_validates_with_catalog` (`:317`). **Honest caveat:** that count test asserts
`catalog_count == 9` but only `capability_count >= 1`, so a silent drop from 8 to 1 would not fail it.
The floor-pin is deliberate — the count is a reducible metric and "never a gate" per design §3.3 — but
it is weaker than the catalog half. Carried as deferred item 14; the test was deliberately not
strengthened during verify, since narrowing the spec does not license hardening tests in the same
phase.

### Divergence 3 — frontend was changed against an explicit Non-Goal (RESOLVED: kept, artifacts corrected)

`proposal.md` Impact states verbatim "Not touched: frontend, Gateway, approval semantics, SAP
execution paths", and design §2 Non-Goals repeats "frontend/Gateway changes". Both are contradicted
by the release-gate fix applied during build:

- `frontend/src/runtime/release-gate/scenario-runner.ts` (M) — `runProcess` now passes
  `env: { ...process.env, LLM_API_KEY: "", LLM_BASE_URL: "" }` so the offline gate stops inheriting
  live credentials from the parent vitest process and making real LLM HTTP calls.
- `frontend/src/runtime/release-gate/scenario-runner.offline-env.test.ts` (??) — new pin asserting
  both variables are blanked on every spawn **and** that `PATH` still propagates.

Effect: the offline scenario test went from ~83.5s (93% of its inline 90s budget) to 10.7s. The fix
was authorized by explicit user ruling after the original "insufficient test budget" diagnosis was
retracted; the root cause is pre-existing (`llm_client.py`, `eval.py`, `narrator.py` are unchanged
base..HEAD, and the only `orchestrator.py` change is `clarify_rounds` propagation), so this change
did not cause the slowness — it exposed it. Vacuity was checked: blanking the credentials still
yields eval exit 0 with all 13 evidence cases, and the consumer at `scenario-runner.ts:209-215` is
fail-closed (`status: "missing"`, `errorType: "CONTEXT_EVIDENCE_MISSING"`), so the gate is not
hollowed out.

Both files remain **uncommitted**: the verify phase forbids committing implementation, and no commit
authorization was given.

**Resolution (user ruling: keep the fix, correct the artifacts).** `proposal.md` Impact now records
the frontend change as a sanctioned exception with its rationale, and both design documents were
updated: `openspec/changes/declarative-intent-hardening/design.md` Non-Goals and design §2 now state
"No Gateway changes" plus the named frontend exception rather than a blanket "no frontend or Gateway
changes". The two frontend files are committed at archive, not during verify.

### Divergence 4 — design §3.1 prescribed the compilation that caused the defect (RESOLVED: design corrected)

Design §3.1 (`…-design.md:52-55`) specifies that `valueShape`, used as a component of
`prefixed`/`suffixed`, "supplies the capture shape **without boundary guards** (guards come from the
prefix/suffix anchors)". The DEMOA2 defect above is precisely the falsification of that belief — the
affix anchor does not guard the value's *free* side. The implementation now compiles:

```
prefixed:   (?:{tokens})\s*({inner})(?![A-Za-z0-9])
suffixed:   (?<![A-Za-z0-9])({inner})\s*(?:{tokens})
valueShape: (?<![A-Za-z0-9])({inner})(?![A-Za-z0-9])
```

(verified at `agent/sap_nexus_agent/extraction/_matching.py:91-102`). The `_compile_named_kind`
docstring was corrected in the fix commit; **design §3.1 was not**.

**Resolution.** Design §3.1 now specifies the three compiled forms with their guards and carries an
explicit "Corrected 2026-08-20" note stating that the previous "guards come from the prefix/suffix
anchors" claim is false, why (the affix anchors only one side), and what it cost (`DEMOA2 工厂` →
`MOA2`, a wrong plant reaching SAP with `missing=[]`). Design §3.3 was aligned with Divergence 2's
narrowing in the same pass. The stale text was the highest-severity documentation defect in the change
— it prescribed the unsafe compilation as the design of record — so it was corrected regardless of the
other rulings.

---

## Deferred ledger (carried forward, not fixed in this change)

Ranked by risk. Items 1–2 must be closed before the actions that would make them live.

1. **Migration-parity trap — explicit `binding:` silently drops six keys.**
   `schemas/capability.schema.json` `$defs.inputBindingBlock` and
   `schemas/extraction-declaration.schema.json` `$defs.inputBinding` both accept `priority`,
   `excludes`, `resolver`, `when`, `requiredWhen`, `reaskSuspect` inside `binding`, and the validator
   even validates `binding.when`/`binding.requiredWhen` field references
   (`scripts/validate_registry_contract.py:226-232`). But
   `registry_loader.py:_parse_input_binding` reads only `sources` and `elicitIfMissing` in the
   explicit branch (`:274-284`) while carrying all six in the deprecated alias branch (`:285-296`)
   — re-verified by reading both branches. Since the validator rejects declaring both shapes on one
   input, the only validator-legal migration is to move the whole block into `binding:`, which
   silently drops `excludes` (Inventory.material, PO.poNumber), `priority` (all 15), `resolver`
   (all 15), `when`/`requiredWhen` (PR.cost_center) and `reaskSuspect` (Inventory.material).
   Latent today (15 inputs use `extraction:`, **0** use `binding:`), but `design.md:77` calls binding
   "a superset shape with a deprecated alias, not a rename", which the explicit branch does not
   satisfy. **Close before any capability migrates off the alias, and before alias removal.**
2. **`elicitIfMissing: false` is strictly worse than not declaring it.**
   `engine.missing_parameters()` honours the flag, but
   `capability_selector.py:226-242` branches on an *empty* `missing_parameters` list, reloads the
   descriptor, recomputes missing from `inp.required` alone with no `elicit_if_missing` consultation,
   and re-adds the suppressed field — then falls back to the hard-coded `请补充缺失的参数` (`:254`)
   instead of the declared `clarifyPrompt`. Suppression is inverted into its own trigger, with worse
   copy. Latent: zero `elicitIfMissing` declarations exist in `registry/`.
   **Treat `elicitIfMissing: false` as unsupported until the selector consults one source of truth.**
3. **Scenario "Two capabilities share one concept matcher" is unpinned** and not exercisable from the
   real registry (refs pairwise distinct). Inherited from the predecessor change, not introduced
   here.
4. **`MM.PR.CreateDraft.plant` extraction and validation disagree at the AB12 boundary.** Its input
   `pattern` is `^[A-Z0-9]{4}$` but its extraction matcher is still the legacy
   `工厂\s*(\d{4}|[A-Z]\d{3})`. Re-measured: `工厂 1000` → `1000`, **`工厂 AB12` → `None`**, while
   `MM.Inventory.GetAvailability` extracts `AB12` via the named kinds. Fail-safe (produces a
   clarification, not a wrong value), but the two capabilities now disagree about what a plant is.
5. **`count_regex_matchers` self-destructs on migration** — the observable metric is keyed on the
   declaration shapes it is meant to drive down; migrating to `binding.sources[]` changes what it
   counts.
6. **`maxRounds: true` parses as `1`** — boolean is not rejected by the schema path.
7. **`clarify_rounds` is propagated by 1 of 6 `ConversationReadState` construction sites** — the
   durable path verified above is correct; other construction sites can silently reset the budget.
8. **Budget-exhaustion fallback is text-indistinguishable.** For `MM.PR.CreateDraft` the
   `groupByBindingKind` copy and the declared `fallback` template render the identical string, so the
   scenario is pinned as a round-counter behavior, not a template switch. Needs a synthetic
   capability whose `fallback` text differs.
9. **`test_missing_locale_falls_back_to_names` asserts only `is not None`** — the derivation from
   missing input names is unchecked.
10. **`test_named_kind_compiled_patterns_pinned` is a pattern-text snapshot.** It went red on the
    DEMOA2 fix and was rebaselined, but a text snapshot cannot fail on a wrong *extraction*, so it
    did not and cannot flag the next guard regression. The behavioral pins added in the fix round
    (`test_named_kinds_do_not_carve_shape_window_out_of_longer_adjacent_token`,
    `test_inventory_plant_ignores_material_tail_adjacent_to_suffix_token`) are the real defence.
11. **No parity assertion between the two validator spellings** —
    `scripts/validate-registry-contract.py` (41-line CLI) and
    `scripts/validate_registry_contract.py` (693-line library) can drift.
12. **Dangling `valueShape` references are silently inert** — `_compile_named_kind` returns `None`
    when the shape is absent, so a typo disables a matcher without any validation error.
13. **Input-level `valueShape:` reference mechanism does not exist** (from Divergence 1). Removing the
    duplicated `^[A-Z0-9]{4}$` from the three plant inputs requires schema support for a shape
    reference on an input plus loader resolution. Until then the patterns are *aligned* to
    `valueShapes.plantCode`, not *derived* from it, so the duplication can drift silently — nothing
    fails if one of the three is edited alone. A cheap interim guard is a contract test asserting all
    three equal the catalog shape.
14. **Capability-level regex count is floor-pinned at `>= 1`** (from Divergence 2).
    `test_regex_matcher_count_is_observable_metric`
    (`agent/tests/test_extraction_declarations.py:710`) pins `catalog_count == 9` exactly but accepts
    any `capability_count >= 1`, so the 8 could silently become 1. Ratcheting it to `== 8` with a
    "lower this as matchers migrate" comment would make the reduction visible without turning the
    metric into a gate.

## Evidence

Recorded against the active snapshot via `comet state record-check … verify --exit-code 0`:

```
.venv/bin/python -m pytest -q
.venv/bin/python -m pytest agent/tests -q
PYTHONPATH=scripts .venv/bin/python scripts/validate-registry-contract.py registry/capabilities.yaml
comet classic openspec -- validate --all --strict
PYTHONPATH=agent .venv/bin/python -c '… run_eval_file("evals/matcher_cases.yaml") …'
npm --prefix frontend run verify
```

Worktree at verification time (dirty, attributed to this change — verification input, not modified
during verify):

```
 M frontend/src/runtime/release-gate/scenario-runner.ts
?? frontend/src/runtime/release-gate/scenario-runner.offline-env.test.ts
 M openspec/changes/declarative-intent-hardening/.comet*        (workflow state)
?? openspec/changes/declarative-intent-hardening/.comet/subagent-progress.md
```

Artifacts corrected during verify to resolve the four divergences (documentation only — no
implementation, test, schema, or registry file was modified):

```
 M openspec/changes/declarative-intent-hardening/specs/declarative-intent-extraction/spec.md
 M openspec/changes/declarative-intent-hardening/proposal.md
 M openspec/changes/declarative-intent-hardening/design.md
 M docs/superpowers/specs/2026-08-19-declarative-intent-hardening-design.md
?? docs/superpowers/reports/2026-08-20-declarative-intent-hardening-verify.md
```

`openspec validate --all --strict` and the registry validator were **re-run after** the spec edits:
22 passed / 0 failed, and `regex matchers in use: 17 (semantic-type catalog 9 + capability-level 8)`
with exit 0 — unchanged, confirming the narrowing is descriptive rather than behavior-altering.

`branch_status`: pending.

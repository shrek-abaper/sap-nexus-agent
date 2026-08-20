# Verification: declarative-intent-hardening

Audit performed at HEAD `6aff915`, change base ref `c2828842`.
Scope: task 4.2 (spec-delta traceability + commit-series audit). Audit only —
no source, test, schema, or registry file was modified in producing this note.

---

## 1. Spec-delta scenario → test mapping

The delta spec
(`openspec/changes/declarative-intent-hardening/specs/declarative-intent-extraction/spec.md`)
contains **21 scenarios**, not 17. The plan's table
(`docs/superpowers/plans/2026-08-19-declarative-intent-hardening.md:2559-2577`)
enumerates 17 rows and omits all four scenarios of the MODIFIED requirement
"Declaration-driven single-turn intent extraction" (rows 6-9 below). Those four
are covered in the tree; the omission is a gap in the plan's table, not a
coverage gap.

Two verdict columns are used deliberately:

- **Row verdict** — does the test the plan named actually pin the scenario it is
  mapped to?
- **Scenario coverage** — is the scenario pinned by *some* test in the tree,
  named by the plan or not?

All file:line references are relative to the repository root.

| # | Spec scenario | Test named by the plan (file:line) | Row verdict | Scenario coverage |
|---|---|---|---|---|
| 1 | capabilityOutput beats user utterance | `test_capability_output_beats_user_utterance_when_wired` — `agent/tests/test_binding_sources.py:120` | **WEAK** | PARTIAL |
| 2 | default only fills when no other source produces | `test_default_fills_only_when_no_other_source_produces` — `agent/tests/test_binding_sources.py:114`; `test_default_source_suppresses_clarify_for_the_field` — `:179` | **GENUINE** | GENUINE |
| 3 | unimplemented capabilityOutput has a failing placeholder | `test_binding_capability_output_not_implemented` — `agent/tests/test_binding_sources.py:250` | **WEAK** | GENUINE (via `:172`) |
| 4 | extraction alias still works with a warning | `test_extraction_alias_emits_deprecation_warning_with_migration_text` — `agent/tests/test_extraction_declarations.py:805` | **GENUINE** | GENUINE |
| 5 | binding shape validates without warnings | `test_binding_shape_validates_without_warnings` — `agent/tests/test_extraction_declarations.py:816` | **WEAK** | PARTIAL |
| 6 | Declared capability recognized without code change | *(no row in the plan's table)* | **UNMAPPED** | GENUINE — `agent/tests/test_declaration_only_capability.py:100` |
| 7 | Undeclared keyword does not trigger | *(no row in the plan's table)* | **UNMAPPED** | GENUINE — `agent/tests/test_extraction_engine.py:58`, `:50`; eval case `reject-unknown-intent` |
| 8 | Weak keyword alone does not trigger but counts toward ambiguity | *(no row in the plan's table)* | **UNMAPPED** | GENUINE — `agent/tests/test_extraction_engine.py:65`, `:122` |
| 9 | Technical override still rejected first | *(no row in the plan's table)* | **UNMAPPED** | GENUINE — `agent/tests/test_capability_selector.py:45`, `:61`, `:74` |
| 10 | Two capabilities share one concept matcher | `test_semantic_type_wrapper_merges_named_kind_fields` — `agent/tests/test_named_kind_matching.py:80`; "matcher_cases 23/23" | **FALSE** | **GAP — no test pins it** |
| 11 | Exclusion prevents value reuse | `test_user_utterance_beats_default_when_matcher_hits` — `agent/tests/test_binding_sources.py:107`; "existing matcher_cases" | **FALSE** | GENUINE — `agent/tests/test_extraction_engine.py:78`, `:71` |
| 12 | Conditional field extraction with keyword-to-constant mapping | `test_extraction_alias_normalizes_to_single_user_utterance_source` — `agent/tests/test_binding_sources.py:62` | **WEAK** (parse-only) | GENUINE — `agent/tests/test_extraction_engine.py:85`, `:98` |
| 13 | Regex escape hatch requires justification | `test_catalog_schema_rejects_regex_without_justification` — `agent/tests/test_extraction_declarations.py:684`; `test_unjustified_catalog_regex_rejected` — `:692` | **WEAK** (catalog only) | PARTIAL — see New finding 1 |
| 14 | Named shape consolidates duplicated patterns | `test_catalog_value_shapes_plant_code` — `agent/tests/test_extraction_declarations.py:216`; `test_catalog_value_shapes_parsed_from_document` — `agent/tests/test_registry_loader.py:239`; `test_pr_declaration_parity_constants` — `agent/tests/test_extraction_declarations.py:521` | **WEAK** | PARTIAL — see New finding 2 |
| 15 | Named kinds rewrite preserves matcher behavior | `test_plant_named_kinds_preserve_legacy_alternation` — `agent/tests/test_named_kind_matching.py:69`; `test_matcher_eval_file_passes` — `agent/tests/test_eval_runner.py:114` | **GENUINE** | GENUINE (count caveat in §5) |
| 16 | Rule mode renders declared prompt deterministically | `test_pr_strategy_renders_one_prompt_per_group` — `agent/tests/test_clarify_rendering.py:186` | **GENUINE** (with note) | GENUINE |
| 17 | LLM rephrasing stays inside the declared field set | `test_rephrase_rejects_out_of_scope_field` — `agent/tests/test_clarify_rendering.py:113` (+ `:99`, `:127`, `:141`, `:156`, `:171`); `test_hybrid_clarify_falls_back_to_template_on_model_failure` — `:294` | **GENUINE** | GENUINE |
| 18 | Missing locale declaration falls back | `test_missing_locale_falls_back_to_names` — `agent/tests/test_clarify_rendering.py:30` | **WEAK** | PARTIAL |
| 19 | Grouped prompt carries all missing fields of one group | `test_pr_strategy_renders_one_prompt_per_group` — `agent/tests/test_clarify_rendering.py:186`; `test_pr_missing_1_2_3_plus_fields_rounds_never_exceed_max_rounds` — `:343` | **GENUINE** | GENUINE |
| 20 | Budget exhaustion degrades to fallback | `test_strategy_round_budget_respected_and_degrades_to_fallback` — `agent/tests/test_clarify_rendering.py:196`; `test_sticky_clarify_rounds_capped_via_read_state` — `:307` | **WEAK** | PARTIAL |
| 21 | Explicit cases still override strategy rendering | `test_inventory_cases_exact_missing_sets` — `agent/tests/test_clarify_rendering.py:16` (**FALSE**); `test_inventory_cases_still_override_strategy_path` — `:362` (**FALSE**); `test_strategy_groups_by_binding_source_kind` — `:221` (**GENUINE**) | **GENUINE via 1 of 3** | GENUINE |

Totals — row verdicts: GENUINE 8, WEAK 7, FALSE 2, UNMAPPED 4, MISSING 0.
Every test named by the plan exists; no row is MISSING.
Scenario coverage: GENUINE 15, PARTIAL 5, GAP 1.

### 1.1 Substantiation of the non-GENUINE rows

**Row 1 — WEAK.** `test_capability_output_beats_user_utterance_when_wired`
monkeypatches both `engine._WIRED_SOURCE_KINDS` and `engine._resolve_source`
(replaced by `_fake_resolve_source`, a three-entry dict at
`agent/tests/test_binding_sources.py:131`). No real resolution runs — acceptable,
since the spec allows the execution path to stay unimplemented. Two gaps remain:
(a) in `BINDING_PRIORITY_YAML` the declared source order already equals
`_SOURCE_PRIORITY`, so the test also passes if sources are iterated in
declaration order; the priority claim is actually pinned by
`test_source_priority_beats_declaration_order` (`:153`), which reverses the
fixture order and guards the reversal. (b) The scenario's second THEN — "no
clarification question for that field is raised" — is not asserted by this test.

**Row 3 — WEAK.** The scenario requires an xfail-marked test that "fails with a
clear not-implemented reason". `test_binding_capability_output_not_implemented`
(`:250`) is marked `xfail(raises=pytest.fail.Exception, strict=True)` and xfails
with `DID NOT RAISE`, i.e. it pins the *unwired* state of the public path, not a
not-implemented reason. The scenario is pinned literally by the sibling
`test_capability_output_source_resolution_is_not_implemented_yet` (`:172`),
marked `xfail(raises=NotImplementedError, strict=True)` with
`match="dependency-edge binding"` — which the plan's table does not name. The
row should cite both.

**Row 5 — WEAK.** The fixture is knowingly invalid on unrelated registry rules
(the test's own comment at `agent/tests/test_extraction_declarations.py:833-836`
says so), so "validation succeeds" is not asserted; the assertion is filtered to
binding-specific substrings (`.binding:`, `binding source`, `declares both`). The
no-deprecation-warning half (`collect_deprecation_warnings(contract) == []`) is
genuine. The "validation succeeds" clause for the *real* registry is pinned
separately by `test_real_registry_validates_with_catalog`
(`agent/tests/test_extraction_declarations.py:317`).

**Row 10 — FALSE, and a coverage gap.**
`test_semantic_type_wrapper_merges_named_kind_fields` constructs a single
`MatcherConfig(kind="semanticType", ref="Plant")` and merges it with one catalog
matcher. No capability is involved, let alone two. If the "two capabilities
resolve through one catalog entry" behavior regressed, this test would stay
green. The real registry cannot supply the missing coverage either: the
`semanticType` reference sets are disjoint —
`MM.Inventory.GetAvailability` refs `{MaterialNumber, Plant}`,
`MM.PR.CreateDraft` refs `{Quantity, Unit, Date, PurchasingGroup}`,
`MM.PurchaseOrder.GetList` uses inline regex matchers only. No test anywhere in
`agent/tests/` loads two capabilities whose inputs reference the same semantic
type. This scenario is unpinned.

**Row 11 — FALSE (named test), GENUINE elsewhere.**
`test_user_utterance_beats_default_when_matcher_hits` passes `set()` as
`excluded_values`; exclusion is never exercised. The scenario is genuinely
pinned by `test_extract_parameters_po_number_value_exclusion`
(`agent/tests/test_extraction_engine.py:78`), which asserts
`extract_parameters("采购订单 4500000001 供应商 4500000001", po, catalog) ==
{"vendor": "4500000001"}` — the poNumber candidate is rejected on value equality
— and by `test_extract_parameters_inventory_exclusion_and_priority` (`:71`).
Neither is named by the plan.

**Row 12 — WEAK (parse-only), GENUINE elsewhere.**
`test_extraction_alias_normalizes_to_single_user_utterance_source` asserts that
the deprecated alias *parses* `when`/`requiredWhen` into `BindingConfig`. Neither
runtime THEN clause of the scenario is exercised. Both are pinned by
`test_extract_parameters_pr_conditional_cost_center`
(`agent/tests/test_extraction_engine.py:85`, which asserts `cost_center` is
extracted when `acct_assgn_cat == "K"` and absent when the condition does not
hold) and `test_missing_parameters_pr_required_when` (`:98`). Neither is named by
the plan.

**Row 13 — WEAK.** Both named tests exercise the *catalog* path only.
`_validate_matcher(..., require_justification=True)` is passed at exactly one
call site — `scripts/validate_registry_contract.py:127` (catalog entries). The
capability-level call sites at `:213` (`binding source`) and `:224`
(`extraction`) use the default `require_justification=False`. The live registry
contains **8 capability-level regex matchers, all without `justification`**
(`MM.PurchaseOrder.GetList` poNumber ×2, vendor, plant, material;
`MM.PR.CreateDraft` material, plant, cost_center), and
`test_real_registry_validates_with_catalog` pins that validation *passes*. See
New finding 1.

**Row 14 — WEAK.** The first half of the scenario ("the pattern is defined once
in the catalog `valueShapes` section") is pinned. The second half ("both inputs
reference that named shape") is not implemented: `registry/capabilities.yaml`
contains **zero** `valueShape` references, and all three plant inputs still
repeat the literal pattern
(`MM.Inventory.GetAvailability.plant`, `MM.PurchaseOrder.GetList.plant`,
`MM.PR.CreateDraft.plant` each declare `pattern: '^[A-Z0-9]{4}$'`).
`test_pr_declaration_parity_constants:521` pins string equality with the catalog
shape's value, not a reference to the named shape. See New finding 2.

**Row 18 — WEAK.** The whole test body is
`assert render_clarify(pr, ["material"], locale="en-US") is not None`. The
scenario's "a default locale prompt derived from the missing input names" is not
checked; any non-empty string passes, including one unrelated to the missing
input names.

**Row 20 — WEAK.** For `MM.PR.CreateDraft` the strategy copy and the declared
fallback template render the *same* string: the declaration is
`{strategy: groupByBindingKind, maxRounds: 2, fallback: {template: '请提供: {fields}'}}`,
so both tests assert the identical text before and after budget exhaustion
(`请提供: 工厂, 单位, 交货日期` at `:202`, `:205` and `:209`; likewise
`请提供: 单位, 交货日期, 采购组` at `:331` and `:339`). The only discriminator is
`rounds is None`. The scenario's THEN — "renders the declared `fallback`
template instead of starting another clarify round" — is therefore pinned as a
round-counter behavior, not as a template switch. Closing this needs a synthetic
capability whose `fallback` text differs from its strategy copy.
`test_strategy_groups_by_binding_source_kind` (`:221`) does not close it either:
it never exhausts the budget.

**Row 21 — two of three named tests are FALSE.**
`MM.Inventory.GetAvailability` declares `cases` + `fallback` and **no**
`strategy` (the test's own comment at `agent/tests/test_clarify_rendering.py:364`
states this). There is therefore no strategy rendering for its `cases` to
override, and `test_inventory_cases_exact_missing_sets` /
`test_inventory_cases_still_override_strategy_path` would both stay green if the
cases-before-strategy ordering were inverted. The scenario is genuinely pinned by
the third named test, `test_strategy_groups_by_binding_source_kind` (`:221`),
whose synthetic `Test.Groups` capability declares **both** `strategy:
groupByBindingKind` and a `cases` entry and asserts
`(text, kind) == ("请提供供应商。", "cases")` at `:290-291`.

**Row 16 — GENUINE with a note.** Rendering from the declaration is pinned.
"without any model call" is structural rather than asserted: `render_clarify`
takes no model argument, so no call is possible, but no test counts calls.

## 2. Unmapped spec scenarios

Four scenarios of the MODIFIED requirement "Declaration-driven single-turn
intent extraction" have no row in the plan's table (rows 6-9 above). All four are
covered in the tree; the plan's 17-row table is incomplete, not the test suite.
The 1:1 traceability claim holds for **21 of 21** scenarios at the
scenario-coverage level with **one exception**: scenario 10 ("Two capabilities
share one concept matcher") is unpinned.

## 3. Routed finding A — explicit `binding:` silently drops six keys

**Confirmed.** `schemas/capability.schema.json` `$defs.inputBindingBlock`
(lines 406-431) and `schemas/extraction-declaration.schema.json`
`$defs.inputBinding` (lines 159-182) both accept `priority`, `excludes`,
`resolver`, `when`, `requiredWhen`, `reaskSuspect` inside `binding`.
`agent/sap_nexus_agent/registry_loader.py:_parse_input_binding` reads only
`sources` and `elicitIfMissing` in the explicit `binding:` branch (lines 274-284)
and carries all six in the deprecated `extraction:` branch (lines 285-296).

**What the spec delta promises.** Nothing about those six keys inside `binding`.
The full text of the relevant requirement is:

> Per-input declarations SHALL support a `binding` block with a `sources[]`
> list of three kinds: `userUtterance` ..., `capabilityOutput` ..., and
> `default` (a constant fallback value). Source priority SHALL be
> `capabilityOutput > userUtterance > default` ...

and the alias requirement says:

> The pre-existing `extraction:` declaration shape SHALL remain valid as a
> deprecated alias of `binding:` with a single `userUtterance` source.

The priority/exclusion/conditional obligations are stated against "input binding
declarations" generically, in the catalog requirement:

> Matchers SHALL support an ordering priority across a capability's inputs.
> Cross-field exclusion SHALL be value-based: a field's extracted value SHALL be
> rejected when it equals an extracted value of a field listed in its `excludes`
> declaration.

The design of record is explicit that these are not per-source concerns
(`docs/superpowers/specs/2026-08-19-declarative-intent-hardening-design.md:145-148`):

> The loader normalizes a legacy `extraction:` block into a single
> `userUtterance` source carrying the existing matchers/priority/resolver/
> excludes/when/requiredWhen semantics (priority and excludes remain
> input-level extraction concerns, not per-source).

**Classification: (b) — out of the spec delta's scope. The schema is permissive
ahead of the loader; no spec scenario is falsified and no test launders a false
claim.** No scenario in the delta asserts that an explicit `binding:` block
honours those keys, and every scenario that depends on them (11, 12) is pinned
through the alias path, which does carry them.

Three facts, however, make this a reachable latent defect that should be carried
as a deferred item rather than closed:

1. All 15 real registry inputs still use `extraction:`; **zero** use `binding:`
   (`grep -c 'extraction:' registry/capabilities.yaml` → 15;
   `grep -c '        binding:'` → 0). Nothing is lost today; the explicit branch
   is exercised only by synthetic test fixtures.
2. The validator emits migration guidance on all 15
   (`scripts/validate_registry_contract.py:284-288`) and rejects declaring both
   shapes on one input (`:167`, pinned by
   `test_binding_and_extraction_together_rejected`,
   `agent/tests/test_extraction_declarations.py:838`). The only
   validator-legal migration is therefore to move the whole block into
   `binding:` — which silently drops `excludes` (Inventory.material,
   PO.poNumber), `priority` (all 15), `resolver` (all 15), `when`/`requiredWhen`
   (PR.cost_center) and `reaskSuspect` (Inventory.material).
3. The validator already *validates* `binding.when` / `binding.requiredWhen`
   field references (`scripts/validate_registry_contract.py:226-232`; the
   condition loop runs for both branches), i.e. it validates keys the loader
   then discards.

`openspec/changes/declarative-intent-hardening/design.md:77` additionally calls
binding "a superset shape with a deprecated alias, not a rename", which the
current explicit branch does not satisfy. That is a design-vs-implementation
mismatch, not a spec-vs-implementation one.

## 4. Routed finding B — "Design §3.7"

**Not confirmed — the premise is wrong. Design §3.7 exists and no tracked
artifact carries a stale reference.**

`docs/superpowers/specs/2026-08-19-declarative-intent-hardening-design.md:172`
is `### 3.7 Testing matrix`. That document — which is tracked, and which the plan
names as the design of record at
`docs/superpowers/plans/2026-08-19-declarative-intent-hardening.md:19`
("Follow the design doc exactly (`docs/superpowers/specs/2026-08-19-declarative-intent-hardening-design.md`):
decisions §3.1–§3.7, migration order §5") — uses explicit numbered sections:
§1 Context, §2 Goals / Non-Goals, §3 Decisions with subsections §3.1–§3.7,
§4 Risks / Trade-offs, §5 Migration Plan, §6 Open Questions.

`openspec/changes/declarative-intent-hardening/design.md` is a condensed sibling
with unnumbered decisions 1-6; its Decision 6 (lines 77-85) is the OpenSpec-side
counterpart of design **§3.6** (Binding model and alias normalization,
lines 141-171), not §3.7. The confusion came from reading "§3.7" against the
condensed sibling.

Tracked files citing `Design §3.x`, all of which resolve correctly against the
Superpowers design doc:

- `docs/superpowers/plans/2026-08-19-declarative-intent-hardening.md:19`, `:320`, `:2496`
- `agent/tests/test_named_kind_matching.py:1` (§3.1, §3.2), `:18` (§3.7), `:60` (§3.2), `:70` (§3.1)
- `agent/tests/test_binding_sources.py:1`, `:251` (§3.6)
- `agent/sap_nexus_agent/extraction/clarify.py:62` (§3.5)
- `agent/sap_nexus_agent/extraction/engine.py:99` (§3.6)

Correct citation for the binding claims: design **§3.6**
(`docs/superpowers/specs/2026-08-19-declarative-intent-hardening-design.md:141-171`),
mirrored by `openspec/changes/declarative-intent-hardening/design.md:77-85`
(Decision 6).

One minor imprecision, not a stale reference: `agent/tests/test_named_kind_matching.py:18`
cites §3.7 for "unit tests pin the compiled regex per kind"; that exact sentence
is a mitigation in §4 Risks, while §3.7 is the testing matrix that lists the
corresponding B1 parity rows. Nothing to fix.

**Nothing needs fixing for this finding.** The task briefs and plan live under
`docs/superpowers/` (tracked) and `.superpowers/sdd/2026-08-19-declarative-intent-hardening/`
(git-ignored via `.superpowers/sdd/.gitignore`), and both cite a section that
exists.

## 5. Commit-series audit

`git log --oneline c2828842..HEAD` → **38 commits**, matching the expected count.

**Ordering: correct.** Strictly monotonic with no interleaving across B-item
boundaries:

| Segment | Commits | Count |
|---|---|---|
| change artifacts + plan | `06966c7`, `aa74d71` | 2 |
| B1.1 | `ba6697a`, `94840ce` | 2 |
| B1.2 | `67f93a7`, `40208dc`, `004430f`, `9e52a52` | 4 |
| B1.3 | `80f8a1d`, `5e5f281`, `7556f7b` | 3 |
| B1.4 | `1887f25`, `b3f0a6b` | 2 |
| B1.5 | `54c9791`, `e2e935b`, `825b84b`, `4b4e197`, `d60b654` | 5 |
| B2.1 | `abf639f`, `8df3d76` | 2 |
| B2.2 | `4ab4d73`, `ee72e80`, `c4b005e` | 3 |
| B2.3 | `5832486`, `fb6a040` | 2 |
| B2.4 | `93fda40`, `3f9c826` | 2 |
| B2.5 | `3e72593`, `df66647` | 2 |
| B3.1 | `fee5cdf`, `08f6391` | 2 |
| B3.2 | `e5e9d43`, `3453e26`, `6a12c33` | 3 |
| B3.3 | `baaef2d`, `b348692` | 2 |
| B3.4 | `c013d5c` (checkoff only) | 1 |
| 4.1 | `6aff915` (checkoff only) | 1 |

**Rider work: none.** Every commit's file set traces to its owning task. The 16
`chore(...): check off task N` commits touch only
`docs/superpowers/plans/2026-08-19-declarative-intent-hardening.md` and
`openspec/changes/declarative-intent-hardening/tasks.md`. The one commit that
reaches outside its immediate code files, `40208dc`, also edits
`docs/superpowers/specs/...-design.md` — a design-doc sync for the same user
ruling it implements, in scope.

**B3.4 has no implementation commit**, only its checkoff `c013d5c`. This is a
documented coordinator ruling recorded in the plan at
`docs/superpowers/plans/2026-08-19-declarative-intent-hardening.md:2513`: task
3.4 was a verification-only step whose test files were already committed by
3.1-3.3, `git add` staged nothing, and an empty commit was refused. Task 4.1 is
verification-only for the same reason. Not an ordering anomaly.

**Message convention** (`<type>(scope): <what> — <test names>; root cause: <why>`)
— exceptions:

| Commit | Deviation |
|---|---|
| `40208dc` | names two tests, no explicit `root cause:` clause (the rationale is given inline: "per user ruling (x1000x must not match; design §3.1 alnum-guard intent)") |
| `004430f` | `docs(...)` plan-sync commit: no test names, no root cause |
| `5e5f281`, `825b84b`, `ee72e80` | snapshot rebaselines: root cause present, no test names ("14 hash pins only, zero case changes") |
| 16 `chore(...)` checkoff commits | no test names, no root cause — by design, they are checkoff markers |

No commit is unattributable and no commit mixes two B items.

## 6. Verification battery of record (task 4.1 gates)

| Gate | Result | Re-run in 4.2 |
|---|---|---|
| `.venv/bin/python -m pytest agent/tests` (from repo root) | `1343 passed, 1 skipped, 2 xfailed in 114.99s` — 0 failed | yes, unchanged |
| `openspec validate --all --strict` | `Totals: 22 passed, 0 failed (22 items)` | yes, unchanged, re-run after this file was created |
| `scripts/validate-registry-contract.py registry/capabilities.yaml` | `regex matchers in use: 17 (semantic-type catalog 9 + capability-level 8)`, 15 deprecation warnings (= 15 `extraction:` blocks), `Registry contract valid: registry/capabilities.yaml`, exit 0 | yes, unchanged |
| `run_eval_file(Path("evals/matcher_cases.yaml"))` | total 23, passed 23, failed 0 | yes, unchanged |
| `npm --prefix frontend run verify` | green in 4.1 (51 files, 524 tests, `next build` ✓, exit 0); no frontend file is touched by this change | not re-run in 4.2 |

**Honest caveat on matcher_cases 23/23.** The 23/23 figure was obtained by
*running* the eval, not by a pinned assertion.
`agent/tests/test_eval_runner.py:114` (`test_matcher_eval_file_passes`) asserts
`summary.total >= 5`, `summary.failed == 0`, `summary.passed == summary.total`.
That does pin "every case present in the file passes", so an extraction
regression would be caught. It does **not** pin the case *count*: deleting cases
from `evals/matcher_cases.yaml` keeps the test green. The "matcher_cases stays
23/23" equivalence gate named in design §4 is therefore only half-enforced by the
suite. `test_matcher_eval_file_covers_five_decision_classes` (`:126`) pins that
all five decision classes remain represented, which limits but does not remove
the exposure.

## 7. New findings for the deferred ledger

1. **Capability-level regex matchers escape the justification gate.**
   `require_justification=True` is passed only for catalog entries
   (`scripts/validate_registry_contract.py:127`); the capability-level call sites
   (`:213` for `binding source`, `:224` for `extraction`) use the default
   `False`. Eight capability-level regex matchers in `registry/capabilities.yaml`
   carry no `justification` and validation passes. The spec scenario "Regex
   escape hatch requires justification" is written unqualified ("**a matcher**
   uses the `regex` kind without a non-empty `justification` → validation
   fails"), so it is satisfied for the catalog half only. Either the scenario
   should be narrowed to catalog matchers or the gate should be extended.
2. **`valueShapes` consolidation is not referenced from capability inputs.**
   Zero `valueShape` references exist in `registry/capabilities.yaml`; all three
   plant inputs still repeat `pattern: '^[A-Z0-9]{4}$'` literally. The delta
   spec's "both inputs reference that named shape" is unimplemented; the change
   aligned the duplicated patterns instead of removing the duplication.
3. **Scenario "Two capabilities share one concept matcher" is unpinned** (row 10
   above). No test loads two capabilities referencing the same `semanticType`,
   and the real registry's reference sets are disjoint, so the eval cannot supply
   the coverage either.
4. **Budget-exhaustion fallback is text-indistinguishable** (row 20 above). A
   synthetic capability whose `fallback` template differs from its
   `groupByBindingKind` copy is needed to pin the template switch rather than the
   round counter.
5. **`test_missing_locale_falls_back_to_names` asserts only `is not None`**
   (row 18 above); the derivation from missing input names is unchecked.
6. **`PR.CreateDraft.plant` extraction was not migrated to the shared shape.**
   Its `pattern` is `^[A-Z0-9]{4}$` (aligned with `valueShapes.plantCode` by
   B1.5) while its extraction matcher is still the legacy regex
   `工厂\s*(\d{4}|[A-Z]\d{3})`, which cannot extract the letter-mixed codes the
   input pattern now admits (e.g. `AB12`). Extraction and input validation
   disagree at the edge that B1.3/B1.5 deliberately widened.
7. **Routed finding A carried forward as a migration-parity trap** (§3 above):
   the only validator-legal migration off `extraction:` silently drops six keys
   the schema accepts and the validator partly validates. Out of this change's
   spec scope, but it should be closed before the alias is removed.

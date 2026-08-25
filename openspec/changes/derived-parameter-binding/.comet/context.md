# Comet Design Handoff

- Change: derived-parameter-binding
- Phase: design
- Mode: compact
- Context hash: 565867878d275f962a77b4d6b454f5e8a93db0e64829642593730f9d2de5a684

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/derived-parameter-binding/proposal.md

- Source: openspec/changes/derived-parameter-binding/proposal.md
- Lines: 1-222
- SHA256: 9f61f7348a7a9e93739336fdee9c50a811d6720e4a92b9fe64a1ae93a3d80ac3

[TRUNCATED]

```md
## Why

`provenance = capability_derived` is permanently `0` in this system. It is not merely
unimplemented — it is **unreachable**. Two verified structural facts block it:

1. Every capability input in `registry/capabilities.yaml` declares `bindingKind: identifier`,
   so the guard at `agent/sap_nexus_agent/planner/plan_compiler_v2.py:253`
   (`if inp.binding_kind != "fact" or not inp.required: continue`) always skips. No `factField`
   parameter source and no `data` edge is ever authored, therefore no parameter can ever be
   derived from an upstream capability's output.
2. `FactType` is an opaque label. `ontology/fact-types.yaml` carries only
   `factTypeId / name / description / businessObject / predicate / semanticType / keyedBy` —
   zero field-level definition — and `schemas/fact-type-catalog.schema.json` is
   `additionalProperties: false` with no `fields` property, so a field list cannot even be
   authored. Without field-level semantic typing, "who can feed whom" cannot be computed
   mechanically, so a data-dependency edge could only ever be hand-written, which project
   invariant 3 forbids.

The consequence is that the product's central claim — parameters are *derived from governed
facts*, not interrogated out of the user — has no physical mechanism behind it. This change
builds that mechanism and proves it with one real dependency edge and a computed (not copied)
parameter-reduction number.

## What Changes

- **T0′ — binding-source migration.** Migrate the `MM.PR.CreateDraft` inputs `unit` and
  `purchasing_group` off the deprecated `extraction:` alias onto
  `binding.sources[{kind: userUtterance, matchers: [...]}]`. These two are prerequisites for
  T3; the remaining 13 deprecated inputs are optional debt whose treatment `design.md` decides.
  The prime marks this as an item the task brief does not contain: the brief numbers work T1–T5
  and assumes the consuming inputs already declare `binding.sources[]`, but the two inputs T3
  must feed still use the deprecated alias, so `capabilityOutput` has no declaration site to be
  added to. It is a discovered prerequisite of T1, not a renumbering of any brief item.
- **T1 — FactType field-level schema (BREAKING for the governed snapshot).** Extend
  `schemas/fact-type-catalog.schema.json` with a `fields` array (per field:
  `name / semanticType / cardinality(one|many) / optional / description`), where `semanticType`
  is drawn from the `sapnexus:*` ontology vocabulary — the same vocabulary as capability
  input/output `semanticType` and Fact Type `keyedBy` — and MUST appear as the `semanticType` of
  some capability input or output; a genuinely new semantic type is listed for user review, never
  invented inline. Add a one-way `extracts: sapnexus:*` mapping to each matcher entry in
  `registry/semantic-types.yaml` and a header comment recording that the file is the extraction
  matcher catalog, not the semantic-type authority. Author field lists for the three
  existing FactTypes. Make `narrative.fieldMapping.itemFields` **derived from** the FactType
  schema instead of a parallel second list. Four field-list copies exist today and copies #1/#2
  have **already drifted** (`purchaseOrderUnit` vs `PurchaseOrderQuantityUnit`):
  `registry/capabilities.yaml:316`, `registry/executor-bindings.yaml:26-32`,
  `frontend/src/runtime/projection/fact-builder.ts:130-140`,
  `frontend/src/runtime/plan-evidence/event-projector.ts:69`. Each copy either becomes derived
  or is locked by a conformance test that goes red on divergence.
  **BREAKING**: `ontology/fact-types.yaml` is one of the four governed RegistrySnapshot sources,
  so `snapshotId` changes and pinned fixtures must be recomputed with a stated semantic reason.
- **T2 — deterministic producer/consumer edge deriver.** A non-LLM deriver matches producer
  FactType fields against consumer input `semanticType` under three conservative rules:
  strict **equality only** (no similarity, no approximation); a producer field with
  `cardinality: many` feeding a scalar consumer parameter **never matches** and emits a
  `needsReduction` diagnostic (no reduction operator is implemented in this change); multiple
  candidate producers for one parameter emit an `ambiguous` diagnostic and the deriver never
  self-selects. Deliverables: a derived-edge view artifact under `runtime/`, a printable CLI
  subcommand for human review, and a validator rule that **errors** when a derivable
  data-dependency edge is hand-authored in `ontology/capability-relations.yaml`.
  Per finding F1 the deriver is not report-only: it becomes the field-selection mechanism inside
  the v2 compiler.
- **T3 — register the 4th capability `MM.Material.GetInfo`.** Registration-only
  (`JCO_RFC` / `BAPI_MATERIAL_GET_DETAIL`, inputs `MATNR` + `WERKS`, because base unit of
  measure is `MARA-MEINS` at client level while purchasing group is `MARC-EKGRP` on the material
  **plant-level** view). All BAPI import/export parameter names, structure names and field names
  are confirmed by executing it live in SE37 and transcribed from real metadata. `MM.PR.CreateDraft`'s
  `unit` and `purchasing_group` gain the `capabilityOutput` source; the resulting PlanGraph
  `data` edge is produced by PlanExecutor orchestration and **never** by a synchronous fetch
  inside the intent layer. READ capability: `sideEffect: none`, no
  `BAPI_TRANSACTION_COMMIT` / `BAPI_TRANSACTION_ROLLBACK`. Live SAP smoke evidence is retained
  in `traces.jsonl`.
- **T4 — measured parameter reduction.** `MM.PR.CreateDraft` has exactly six required inputs
  today (`material`, `plant`, `quantity`, `unit`, `delivery_date`, `purchasing_group`;
  `acct_assgn_cat` and `cost_center` are `required: false`). `GetInfo` eliminates exactly two,
  so the honest answer is **6 → 4**, not the 6 → 3 circulating in design docs. Deliver a
  per-parameter table (parameter / post-change source kind / still asked?) plus the prerequisite
  the missing item would need.
- **T5 — sequence-level eval.** The existing `matcher_cases` / `seed_cases` are single-utterance
  and structurally cannot test multi-source binding or ask-behaviour. Add conversation-sequence

```

Full source: openspec/changes/derived-parameter-binding/proposal.md

## openspec/changes/derived-parameter-binding/design.md

- Source: openspec/changes/derived-parameter-binding/design.md
- Lines: 1-533
- SHA256: 6c1f277ee392f0839360b320d7f36b66ccc83eb3fee5dd632ff3112b5822651d

[TRUNCATED]

```md
## Context

See `proposal.md` — Why for motivation. This section records only the constraints that shape the
approach, all verified against the current tree.

**Two distinct semantic-type vocabularies exist, and the brief assumed one.**
Capability inputs and outputs declare ontology semantic types (`registry/capabilities.yaml:89`
`semanticType: sapnexus:UnitOfMeasure`, `:444` `sapnexus:PurchasingGroup`), while
`registry/semantic-types.yaml` is the *extraction matcher* catalog whose ids are bare
(`Unit`, `PurchasingGroup`, `MaterialNumber`, …) and are referenced from matchers as
`{kind: semanticType, ref: PurchasingGroup}` (`registry/capabilities.yaml:454`). The two are not
the same namespace and are not in one-to-one correspondence: `sapnexus:UnitOfMeasure` has no
matcher entry named `UnitOfMeasure`, and `sapnexus:AvailableQuantity` has no matcher entry at all.
`ontology/fact-types.yaml`'s existing `keyedBy` already uses the ontology vocabulary
(`sapnexus:MaterialNumber`, `sapnexus:Plant`, `sapnexus:PrNumber`). This directly determines
whether T2's strict-equality matching can ever produce a match — see Decision 1.

**A FactType's payload shape is not its capability's output list.** The inventory capability
declares three outputs (`availableQuantity`, `mrpElementLines`, `returnMessages`) while its
narrative renders `{material}`, `{plant}`, `{value}`, `{unit}`
(`registry/capabilities.yaml:167-171`). `value` and `unit` are fact payload fields with no
declaration anywhere. The four already-drifted field-list copies named in the proposal are copies
of the *payload* shape, not of the output list — so only a payload-shaped field model can lock
them. See Decision 3.

**The compiler's current field selection ignores which input it is binding.**
`plan_compiler_v2.py:265` calls `_first_fact_field()` (`:497-511`), which returns the first output
whose `factTypeRef` matches, and `semantic_planning/validation.py:459-461` asserts that value
equals a producer *output* name. Two inputs fed by one producer therefore receive the same field.
See Decision 2.

**Omitting the `narrative` block does not avoid the narration guard.**
`orchestrator.py:1819` reads `descriptor.narrative.fact_shape if descriptor and
descriptor.narrative else "single-value"` — an absent block defaults to `single-value`, which
routes into `narrate_single_value` (`narrator.py:235-246`), which raises `NarrativeGuardError`
unless `material` / `plant` / `value` / `unit` are all non-empty. This retires the mitigation the
proposal listed as a candidate. See Decision 6.

**`visibility` is not registry-driven.** `planner/capability_card.py:189` hardcodes
`visibility="VISIBLE_DRY_RUN"`; there is no capability-level `visibility` field in
`schemas/capability.schema.json`. Declaring the new capability "upstream-only so it is never
narrated" is therefore not available without Python changes, which also retires that mitigation.

**`promptTemplate` is a free string with a generic fallback.** `narrator.py:51` resolves an
unknown `promptTemplate` id to `_GENERIC_GUIDANCE` (`:45`), and `detailFormatter` already accepts
`none`. A new capability can therefore declare a template id that no Python dictionary knows,
with zero Python change.

## Goals / Non-Goals

**Goals**

- One authoritative field-level definition per FactType, with every restatement either derived
  from it or failing a conformance check on divergence.
- Data dependency edges that are *computed*, with a reviewable derived view and conservative
  diagnostics instead of silent guesses.
- One real derived edge in production use, with `provenance=capability_derived` reaching the
  narrative and the approval surface.
- An honest, computed parameter-reduction number and sequence-level eval coverage of the
  degradation, conflict, and unreachable-upstream paths.

**Non-Goals (design-level, beyond the proposal's out-of-scope list)**

- No change to the four-governed-source definition of `RegistrySnapshot`. This change adds fields
  *inside* an existing governed source; it does not add a fifth source.
- No disambiguation mechanism. `ambiguous` and `needsReduction` stay diagnostics; nothing in this
  change resolves them automatically.
- No generalization of the narrator beyond the minimum needed to stop it from crashing on a
  non-inventory-shaped fact.
- No `visibility` field, no upstream-only capability class.

## Decisions

### Decision 1 — FactType field `semanticType` uses the ontology vocabulary, not the matcher catalog

**[CONFIRMED by the user; the corresponding instruction in the task brief is void]**

The brief stated that a FactType field's `semanticType` must reference an existing entry in
`registry/semantic-types.yaml`. Per Context, that file is the extraction matcher catalog with bare
ids, whereas the consumer side of every match — a capability input's `semanticType` — is the

```

Full source: openspec/changes/derived-parameter-binding/design.md

## openspec/changes/derived-parameter-binding/tasks.md

- Source: openspec/changes/derived-parameter-binding/tasks.md
- Lines: 1-67
- SHA256: def7bdab4ee107fe911bd440cc7e4f6e9e178e424f6d5af531189d3d54ee74a1

```md
## 1. T0′ — Binding-source prerequisite

- [ ] 1.1 Add `satisfiableByFactType: sapnexus:MaterialInfoFact` to the two `MM.PR.CreateDraft` inputs that T3 will feed (`unit` at `registry/capabilities.yaml:415`, `purchasing_group` at `:442`), leaving both at `bindingKind: identifier`. The `extraction:` → `binding.sources[]` migration originally scoped here is **dropped**: `registry_loader` already normalizes the alias into a single `userUtterance` source (pinned by `test_extraction_alias_normalizes_to_single_user_utterance_source`), so migrating buys no behaviour. Record it as orthogonal cleanup and do not perform it; verify the deprecation warning count is unchanged and no input's parsed binding changes
- [ ] 1.2 Relax the `bindingKind`/`satisfiableByFactType` coupling at all six sites so an `identifier` input may declare `satisfiableByFactType` (design Decision 14, ruling 1): `schemas/capability.schema.json` `$defs/ioField/allOf[1]` (drop the `not.required`; leave `allOf[0]` intact), `scripts/validate_registry_contract.py:491-495`, `semantic_planning/validation.py:438-441`, `validation.py:1426-1433`, `semantic_planning/graph.py:68`, `planner/plan_compiler_v2.py:253`. Every check keeps its factType/semantic-type equality assertion — only the `bindingKind` test is dropped, so no check becomes weaker; verify a `fact` input still *requires* `satisfiableByFactType`, an `identifier` input without it still validates, and `graph.py` now records `consumesFactType` for the two T0′ inputs (that edge is what the T-auto-pull closure walks)
- [ ] 1.3 Implement compiler-layer precedence — user-supplied beats upstream-derived (design Decision 7, ruling 2): in `plan_compiler_v2._build_plan_graph_v2`'s second pass, do not author a `factField` source for a parameter that already carries a `literal` or `goalConstraint` binding. Because precedence applies at authoring time, exactly one source is authored per parameter and the duplicate-`parameterBindings` hazard is dissolved mechanically; verify a supplied value yields `literal` with no `factField` and no producer node, and that `extraction/engine.py:24` `_SOURCE_PRIORITY` and `agent/tests/test_binding_sources.py:112-166` are **not** modified — the `binding.sources[]` priority contract governs the extraction layer, is not exercised by this change, and no published requirement is overturned
- [ ] 1.4 Confirm no `sessionContext` source kind is introduced and the source-kind enum stays exactly `userUtterance | capabilityOutput | default`; verify by schema enum assertion. `capabilityOutput` remains deliberately unwired — its existing xfail placeholder keeps its role as the fixed landing point and is not enabled by this change (design Decision 15, ruling 4)

## 2. T1 — Authoritative Fact Type field schema

- [ ] 2.1 Extend the Fact Type catalog schema with a required field list (`name`, `semanticType`, `cardinality`, `optional`, `description`), added explicitly to `$defs/factType.properties` because `schemas/fact-type-catalog.schema.json` is `additionalProperties: false` with a 7-key `required` list. `fields` is **required** for every Fact Type, so the catalog `version` bumps to `2` and the schema's `"version": {"const": 1}` changes with it — a required key is a breaking catalog change and the version is the mechanism that lets a consumer rely on `fields` existing (`registry/semantic-types.yaml` already sets the v2 precedent). `semanticType` is drawn from the `sapnexus:*` ontology vocabulary and validated against the set of semantic types declared by capability inputs/outputs (design Decision 1); verify a matcher-catalog bare id and an unknown semantic type each fail validation with the offending Fact Type and field named, and that `snapshot.py`'s `document_version` still reads the bumped version without error
- [ ] 2.2 Add a header comment to `registry/semantic-types.yaml` recording that it is the extraction matcher catalog and not the semantic-type authority; do not rename the file, so no `ref` site changes
- [ ] 2.3 Add `extracts: sapnexus:<Type>` to each matcher entry as the one-way mapping onto the ontology vocabulary; verify several matchers may extract one ontology type, a matcher declaring two different ontology types is rejected, and `sapnexus:AvailableQuantity` having no matcher entry passes without any back-fill prompt
- [ ] 2.4 Add the two validator rules: every `sapnexus:*` reference must exist in the ontology vocabulary, and every `extracts:` target must exist in the ontology vocabulary; verify each rule fails with the offending reference and its declaring entry named
- [ ] 2.5 Declare field lists for the three existing Fact Types using the payload-shape model and the depth rule (design Decision 3): `PurchaseOrderSupplyFact` decomposes the six item-level fields as `cardinality: many`; `InventoryAvailabilityFact` keeps `mrpElementLines` as one opaque `many` field; the array container output name is not declared as a field
- [ ] 2.6 Derive `narrative.fieldMapping.itemFields` from the authoritative field list rather than restating it, or — if full derivation is not reachable without changing narration behaviour — add a conformance test that fails on any divergence; verify by mutating one declared field name and observing the failure
- [ ] 2.7 Cross-check every other field-list restatement site (projection layer, TS types, Java DTOs) and record for each whether it is now derived or conformance-locked; verify each locked site fails when the authoritative list changes, and that no site remains an unchecked independent copy
- [ ] 2.8 Recompute the snapshot pins. `semantic_planning/snapshot.py:38,45` hash the **whole document** with no key filtering, so adding `fields:` necessarily changes both the fact-types per-source digest and `snapshot_id`. Verified inventory: **`evals/matcher_cases.yaml` pins the real digest `sha256:e6d329bc…e599ed95` in 14 places** and is the only file that must be recomputed; `agent/tests/fixtures/semantic_planning/plan-material-supply.yaml:5` pins an all-zeros placeholder (not a real digest) and needs no change; `evals/recommendation_decision_cases.json:74` uses the symbolic `"snapshot-2"` and is unaffected. Record the semantic change that caused the recomputation in the commit body — silently refreshing a snapshot is forbidden (invariant 9); verify no approval subject hash in `test_approval.py` / `test_orchestrator.py` is touched (invariant 5)

## 3. T2 — Derived data dependency edges

- [ ] 3.1 Implement the deterministic deriver: candidate set scoped by the consuming input's `satisfiableByFactType` and the active producers of that Fact Type, match by strict semantic-type equality, no model call, no Gateway call, no SAP call (design Decision 2); verify determinism by repeated runs and verify a same-semantic-type field in an undeclared Fact Type is not a candidate
- [ ] 3.2 Build the **positive control** fixture — two fabricated capabilities whose fields make exactly one edge derivable — and assert the deriver produces that edge (design Decision 13); verify the fixture contributes nothing to the Registry Snapshot and its capabilities are absent from the active set
- [ ] 3.3 Emit derived edges in `dependsOn` shape with `origin: derived` so `plan_compiler_v2.py:299-312` consumes them unchanged; verify no new relation-type name is introduced for derivedness
- [ ] 3.4 Implement the `needsReduction` and `ambiguous` diagnostics with no operator selection and no self-selection; verify `needsReduction` against the real `mrpElementLines` case and `ambiguous` against both trigger shapes (two matching fields in the declared Fact Type; two active producers of it). The second shape is where `plan_compiler_v2.py:217`'s `producers[0]` silently-picks-one defect lands — latent today because each Fact Type has exactly one producer, but auto-pull makes it load-bearing, so it must surface as `ambiguous` rather than resolve by list order; verify by a fixture with two producers of one Fact Type
- [ ] 3.5 Expose the derived view as a `runtime/` artifact plus a thin printable wrapper `scripts/derive-data-dependencies.py` carrying full provenance per edge and per diagnostic. Follow the established one-script-one-command pattern (`scripts/validate-registry-contract.py`: hyphenated thin wrapper over the underscored module, `main(argv) -> int`, errors to stderr, exit 1) — there are no argparse subparsers anywhere in `agent/` or `scripts/`, so do not introduce one. The logic itself lives in `agent/sap_nexus_agent/semantic_planning/derivation.py` as a pure function over `SemanticSourceDocuments`, shared by three consumers: the `build_goal_spec` closure, the `plan_compiler_v2` second pass, and the validator rule of 3.6; verify the empty view is reported as empty rather than as an error
- [ ] 3.6 Add the `origin: derived | manual` field to relation edges, require `justification` on `manual`, and add the validator rule rejecting an `origin: manual` edge the deriver can compute (design Decision 8); verify a manual-without-justification edge and a manual-but-derivable edge each fail, and that `dependsOn` / `precondition` authoring still validates
- [ ] 3.7 Run the derived view against the current three capabilities and record the result; an empty real view is the expected outcome at this point **only if the positive control from 3.2 is green** — empty plus a red positive control is a deriver defect, not a legitimate empty result

## 4. T5 skeleton — eval case identifiers

- [ ] 4.1 Create **five** conversation-sequence eval case skeletons so their case ids exist before registration, per design Decision 9: (1) *derived-not-asked* — omits both `unit` and `purchasing_group`; (2) *user-supplied-wins* — supplies `unit`; (3) *mixed* — supplies `unit`, omits `purchasing_group`; (4) upstream empty/error degrades to elicitation; (5) upstream unreachable emits `CapabilityGap` and errors. Cases 1 and 2 are a **mandatory pair**: without case 2 the outcomes "the user's value won" and "we never derived anything" are indistinguishable, so a green case 1 alone cannot demonstrate the feature. Case 3 is the only path that exercises Defect 1 (5.5) and must be a test, not a hope; verify the eval harness discovers all five and reports them as pending with attribution rather than as passing

## 5. T3 — Register `MM.Material.GetInfo` and author the first derived edge

- [ ] 5.1 Execute `BAPI_MATERIAL_GET_DETAIL` live in SE37 and transcribe the real import/export parameter names, structure names, and field names for `MARA-MEINS` and `MARC-EKGRP`; use SE11 where table structure is in doubt; paste the verification output into the report. **Stop and ask the user if the live metadata contradicts the registry expectation.**
- [ ] 5.2 Register the capability by registry declaration only — capability entry with `kind: Function` (which the schema binds to `sideEffect: none` + `requiresApproval: false` + `approvalPolicy: not_required`, and which is the precondition for 5.4's auto-pull being safe), executor binding, `sapnexus:MaterialInfoFact` with its four fields (`material`/`sapnexus:MaterialNumber`, `plant`/`sapnexus:Plant`, `baseUnitOfMeasure`/`sapnexus:UnitOfMeasure`, `purchasingGroup`/`sapnexus:PurchasingGroup` — **zero new semantic types**) and provenance fields `asOf` / `snapshotId` (design Decision 11), `evalLinkage` pointing at the 4.1 case ids, and a full `narrative` block using an unrecognised template id and `detailFormatter: none` (design Decision 6); verify contract validation passes and `git diff --stat` shows zero Python lines for this step
- [ ] 5.3 Confirm the derived view now contains the two candidate edges (`MaterialInfoFact.baseUnitOfMeasure` → `MM.PR.CreateDraft.unit`; `MaterialInfoFact.purchasingGroup` → `MM.PR.CreateDraft.purchasing_group`) as derived output, not as authored relations; **stop and ask the user if either edge comes out `needsReduction` or `ambiguous`**
- [ ] 5.4 Implement producer auto-pull as a **closure over `goal.desired_fact_types`** in `build_goal_spec` (design Decision 16, ruling 3): when a consumer's `required` input is not bound by the user and declares `satisfiableByFactType: F`, and `F` is not already desired, add `F` to `desired_fact_types`. `plan_compiler_v2.py:213-233` already builds one node per desired Fact Type, so the node-creation loop needs **zero** changes. The closure lives in `build_goal_spec`, not inside `_build_plan_graph_v2`, so the GoalSpec records *why* the extra node exists and the extra read is auditable rather than a silent planner side effect. Restrict the pull to producers whose capability is `kind: Function`: `capability.schema.json` `$defs/capability/allOf[0]` binds `Function` ⇒ `sideEffect: none` + `requiresApproval: false`, so the restriction **structurally cannot** drag in a WRITE or bypass Human Approval — invariant 5 is protected by the schema, not by reviewer discipline. The two PR inputs stay `bindingKind: identifier` and declare `satisfiableByFactType` only; **no `capabilityOutput` source is added** (ruling 4), so derivation is computed at runtime by semantic-type equality and nothing restates the derived field, making field-level drift structurally impossible; verify the closure adds `MaterialInfoFact` when `unit` is unbound, refuses to pull an `Action` producer, does not elicit either value when the upstream value is available, and that the resolved value carries `provenance=capability_derived`
- [ ] 5.4a Add the mandatory disclosure that pays for the auto-pull: the narration states that an extra read occurred, and the approval card marks a derived value as derived rather than user-entered; verify both surfaces show the disclosure and that no approval step is skipped or shortened because a value was derived (invariant 5)
- [ ] 5.5 Fix the duplicate-`data`-edge defect (design Decision 5, defect 1). This is **on the critical path, not a pre-existing item to tally**: when the user supplies `unit` but omits `purchasing_group`, one (producer → consumer) pair yields two `factField` bindings that must share one data edge — `validation.py:483-496` tolerates N sources per edge, but `plan_compiler_v2.py:277` appends one edge per binding and `validation.py:528-545` then rejects the duplicate, blocking T3's headline edge. Emit one edge keyed `(producer, consumer, factType)` carrying both `factField` sources; verify existing single-binding plans still emit exactly one edge, verify the two-binding case emits exactly one edge with two sources, and attribute the changed lines to figure (b)
- [ ] 5.6 Make the compiler select the producer field per bound input by semantic type instead of `_first_fact_field()`; verify the two PR inputs receive different fields and that the emitted plan's `topologicalOrder` places GetInfo before `MM.PR.CreateDraft`
- [ ] 5.7 Make `narrate_single_value`'s required-field guard `fieldMapping`-driven and stop hardcoding the inventory value label (design Decision 6, defect 2); verify the inventory narration is unchanged and that a template referencing a missing field still raises `NarrativeGuardError`
- [ ] 5.8 Confirm no synchronous data fetch exists anywhere under `agent/` — derivation happens only through PlanExecutor node ordering (invariant 2); verify by inspecting the intent path for any Gateway/RFC/OData call and by the eval assertion that intent parsing performs zero execute calls
- [ ] 5.9 Carry `provenance=capability_derived` and its source node through projection into the narrative and the approval payload, including the two frontend allow-list edits; verify the derived value is traceable to its producing node in both surfaces
- [ ] 5.10 Run the live READ smoke against real SAP and retain `traces.jsonl` evidence; verify `BAPI_TRANSACTION_COMMIT` / `BAPI_TRANSACTION_ROLLBACK` are absent from the trace, and that fail-closed executors (`CDS_ADT` / `REST_JSON` / `SQL_READ`) still refuse; troubleshoot via SE37 / SLG1, and `/IWFND/ERROR_LOG` for the OData path
- [ ] 5.11 Confirm approval semantics are byte-identical for the WRITE capability — no change to subject construction, subject hash, or anti-replay — and flag in the report that the new upstream nodes' `asOf` / `snapshotId` are inputs to the deferred D4 joint-hash work (invariant 5)

## 6. T4 — Computed parameter reduction

- [ ] 6.1 Produce the required-parameter table for `MM.PR.CreateDraft` by computation, one row per required input with its post-change source kind and whether it still needs asking; do not copy any figure from a design document. **Report the computed number even if it is 4 rather than 3, and state the missing item's prerequisite. Stop and ask the user if the computed number differs from the target.**

## 7. T5 full — Conversation-sequence assertions

- [ ] 7.1 Turn case 1 real (*derived-not-asked*): material + plant only → neither `unit` nor `purchasing_group` is elicited, both carry `provenance=capability_derived`, the `MM.Material.GetInfo` node exists in the plan, the `data` edge carrying `sapnexus:MaterialInfoFact` exists, and `topologicalOrder` places GetInfo before `MM.PR.CreateDraft`
- [ ] 7.2 Turn case 2 real (*user-supplied-wins*): the user supplies `unit` → the parameter binds from `literal`, **no** `factField` source is authored for it, the producer is **not** pulled into `desired_fact_types`, and no extra READ is executed. This is the half of the pair that makes case 1 meaningful; verify by asserting the absence of the producer node, not merely the presence of the literal
- [ ] 7.3 Turn case 3 real (*mixed*): the user supplies `unit` and omits `purchasing_group` → exactly **one** `data` edge is emitted for the (GetInfo → CreateDraft, `MaterialInfoFact`) pair, `purchasing_group` binds from `factField`, `unit` binds from `literal`. This is the assertion that proves 5.5's duplicate-edge fix
- [ ] 7.4 Turn case 4 real: upstream GetInfo empty or erroring → degrades to elicitation, never to a default or a fabricated value
- [ ] 7.5 Turn case 5 real: upstream capability unreachable → `CapabilityGap` is emitted and the run errors rather than degrading into an attempt (governance red line)
- [ ] 7.6 Add the dry-run coverage the specs now require: the missing-producer gap exercised against the governed capability set, and unbound inputs plus derivation diagnostics surfaced as gaps; verify the previously `pending: true` dry-run case is no longer pending

## 8. Batch T exit verification and reporting

- [ ] 8.1 Run and capture raw output for: `.venv/bin/python scripts/validate-registry-contract.py registry/capabilities.yaml`; `.venv/bin/python -m pytest agent/tests/test_registry_contract.py -v`; `.venv/bin/python -m pytest agent/tests -q`; `PYTHONPATH=agent scripts/verify-agent-callplan-evidence.sh`; `npm --prefix frontend run verify`; `npm --prefix frontend run release-gate -- --profile all`
- [ ] 8.2 Confirm the release gate still reports 22/22 and `L3_ACTION_GOVERNED`, and that all four eval suites are fully green
- [ ] 8.3 Report the two Python line counts separately from a file-partitioned `git diff --stat` (design Decision 5): figure (a) registration lines, target 0; figure (b) pre-existing-defect lines with each line attributed to a named defect
- [ ] 8.4 Deliver the changed-file list with a one-sentence note per file, and the unresolved-item list naming each specific test plus its attribution and reason — no item may be summarised as a known issue, a pre-existing failure, or unrelated to core functionality (invariant 10)
- [ ] 8.5 Confirm the batch T exit conditions are all met — including a green positive control alongside whatever the real-capability derived view reports — before any batch L work is proposed; batch L is a separate change and does not begin in this one

```

## openspec/changes/derived-parameter-binding/specs/agent-callplan-evidence/spec.md

- Source: openspec/changes/derived-parameter-binding/specs/agent-callplan-evidence/spec.md
- Lines: 1-43
- SHA256: 57cd2c1d331445ce47f9389ecb4a560dbf06050f1034f890b319a5319fec3553

```md
## ADDED Requirements

### Requirement: Conversation-sequence eval cases cover multi-source parameter binding
The eval suite SHALL include conversation-sequence cases whose input is an ordered sequence of turns and whose assertions cover the resulting decision trajectory, not only a single utterance mapped to a single decision. A sequence case SHALL be able to assert, per turn, the decision type, which fields were elicited, which fields were not elicited, and the provenance of each resolved parameter. Single-utterance cases SHALL remain valid and MUST NOT be deleted or weakened to accommodate the new case shape.

#### Scenario: Derived fields are not elicited

- **WHEN** a sequence case supplies only the identifiers needed by the upstream capability
- **THEN** the fields obtainable from the upstream capability's output are absent from the elicited-field set
- **AND** each such resolved parameter carries `provenance=capability_derived`

#### Scenario: Upstream failure degrades to elicitation

- **WHEN** a sequence case makes the upstream capability return an empty result or fail
- **THEN** the trajectory shows the affected fields being elicited from the user
- **AND** no assertion accepts a fabricated value or an undeclared default in their place

#### Scenario: Conflicting user value follows declared priority

- **WHEN** a sequence case supplies a user value that differs from the value derivable upstream
- **THEN** the resolved value follows the declared source priority
- **AND** the case asserts that the conflict was recorded

#### Scenario: Unreachable upstream capability errors instead of degrading

- **WHEN** a sequence case removes the upstream capability from the governed capability set
- **THEN** the trajectory reports a capability gap and fails closed
- **AND** the case asserts that no degraded attempt at the consuming capability occurred

### Requirement: Eval evidence reports pending cases as unresolved with attribution
Eval evidence SHALL NOT report a case that did not execute as passing. A case that cannot execute SHALL be reported as unresolved together with its case identifier, the reason it cannot execute, and what would make it executable. Verification output MUST NOT summarize an unresolved case as a known issue, a pre-existing failure, or unrelated to core functionality.

#### Scenario: Unresolved case names itself and its cause

- **WHEN** an eval case cannot execute against the governed sources
- **THEN** the evidence output names the case identifier and the concrete reason
- **AND** the case is counted as unresolved rather than passed or silently omitted

#### Scenario: Executable case must not remain pending

- **WHEN** the governed sources allow a previously unexecutable case to be constructed
- **THEN** the case executes and is asserted
- **AND** it is no longer reported as pending

```

## openspec/changes/derived-parameter-binding/specs/declarative-intent-extraction/spec.md

- Source: openspec/changes/derived-parameter-binding/specs/declarative-intent-extraction/spec.md
- Lines: 1-102
- SHA256: 5d03ab109f5349d9f50c89a35ff5d928cc8deb581285867e1e8d7bd897d3afae

[TRUNCATED]

```md
## ADDED Requirements

### Requirement: A user-supplied value takes precedence over a value derivable from an upstream Fact

When a required input can be satisfied both by a value the user supplied and by a field of an
upstream Fact, the system SHALL bind the user-supplied value and SHALL NOT bind the derived one.
Precedence SHALL be applied at plan-authoring time: the planner SHALL NOT author an upstream-Fact
parameter source for a parameter that already carries a user-supplied source, so exactly one source
is authored per parameter. When a required input is *not* supplied by the user and an upstream Fact
can supply it, the system SHALL bind the derived value and SHALL NOT elicit the field from the user.
A derived value SHALL carry `provenance=capability_derived` and SHALL remain traceable to the
upstream node that produced it.

This requirement governs the planning layer. It does not alter the published source priority of
`binding.sources[]`, which governs resolution inside the extraction layer.

#### Scenario: User-supplied value suppresses derivation

- **WHEN** a required input declares an upstream Fact as an alternative source and the user supplies
  a value for that input
- **THEN** the parameter is bound from the user-supplied value
- **AND** no upstream-Fact parameter source is authored for that parameter
- **AND** the producing capability is not pulled into the plan on that input's account
- **AND** no additional read is executed for that input

#### Scenario: Unsupplied input is derived rather than elicited

- **WHEN** a required input declares an upstream Fact as an alternative source and the user supplies
  no value for it
- **THEN** the parameter is bound from the upstream Fact field
- **AND** no clarification question for that field is raised
- **AND** the bound value carries `provenance=capability_derived` together with the identity of the
  upstream node it came from

#### Scenario: Conflict between a user value and an available derived value is recorded

- **WHEN** the user supplies a value for an input, and an upstream node present in the plan for
  another reason also produces a differing value for that same input
- **THEN** the user-supplied value is the resolved value
- **AND** the evidence records the input name, the user-supplied value, the available derived value,
  and that the user-supplied source won
- **AND** the conflict is not resolved silently

#### Scenario: Matching values record no conflict

- **WHEN** a user-supplied value and an available derived value for the same input are equal
- **THEN** the resolved value is that value
- **AND** no conflict is recorded

### Requirement: Unavailable upstream value degrades to elicitation, never to fabrication

When an upstream-Fact parameter source cannot produce a value — the upstream node returned no value,
returned an empty value, or failed — the system SHALL elicit the field from the user. The system MUST
NOT substitute a value that was not declared as a source, MUST NOT reuse a value from a different
field or a different business object instance, and MUST NOT silently apply a default that the input
did not declare. When the upstream capability itself is unavailable or cannot be planned, the system
SHALL surface a capability gap and fail closed rather than attempt a degraded execution.

#### Scenario: Empty upstream value falls back to asking the user

- **WHEN** an input's only non-user source is an upstream Fact field and the upstream node produced
  no value for that field
- **THEN** the system elicits that field from the user
- **AND** the input is not filled with a fabricated or borrowed value

#### Scenario: Failed upstream node does not invent a default

- **WHEN** the upstream node that would supply the derived value fails
- **AND** the consuming input declares no `default` source
- **THEN** the system elicits that field from the user
- **AND** no default value is applied for that input

#### Scenario: Unreachable upstream capability fails closed

- **WHEN** an input depends on an upstream Fact whose producing capability is not available in the
  governed capability set
- **THEN** the system reports a capability gap
- **AND** it does not attempt a degraded execution of the consuming capability

### Requirement: The capabilityOutput binding source remains unwired

```

Full source: openspec/changes/derived-parameter-binding/specs/declarative-intent-extraction/spec.md

## openspec/changes/derived-parameter-binding/specs/output-projection/spec.md

- Source: openspec/changes/derived-parameter-binding/specs/output-projection/spec.md
- Lines: 1-29
- SHA256: 2cb122e02772363241da363b6420b3a03d54e0716352e6f13bf917ad9344554d

```md
## ADDED Requirements

### Requirement: Projection field names conform to the authoritative Fact Type field list
Every projection-layer or presentation-layer restatement of a Fact Type's field names SHALL be conformance-checked against the authoritative Fact Type field list. The check SHALL fail when a restated field name does not exist in the authoritative list, and when a restatement drifts from the authoritative list by rename. A restatement MUST NOT introduce a field name that the Fact Type does not declare.

#### Scenario: Renamed authoritative field breaks the restatement

- **WHEN** a field is renamed in the authoritative Fact Type field list
- **THEN** the conformance check fails for every restatement that still carries the old name

#### Scenario: Unknown restated field name is rejected

- **WHEN** a projection-layer restatement names a field that the Fact Type does not declare
- **THEN** the conformance check fails and names the offending field and artifact

### Requirement: Every active primary-fact capability resolves a projection builder
The projection layer SHALL resolve a fact builder for every active capability that declares a primary Fact output. When a capability declares a primary Fact output and no builder resolves for it, the projection layer SHALL fail closed with a structured failure naming the capability, rather than silently producing no fact. A capability whose node produces no fact MUST NOT be treated as a successfully projected node.

#### Scenario: Registered capability without a builder fails closed

- **WHEN** an active capability declares a primary Fact output and the projection layer cannot resolve a builder for it
- **THEN** the projection reports a structured failure naming that capability
- **AND** the node is not reported as having produced a fact

#### Scenario: Derived parameter provenance survives projection

- **WHEN** a consuming node's parameter was resolved from an upstream node's fact field
- **THEN** the projected evidence retains the resolved value, its provenance, and the identity of the upstream node
- **AND** the value is not stripped from the payload presented for human approval

```

## openspec/changes/derived-parameter-binding/specs/planner-dry-run/spec.md

- Source: openspec/changes/derived-parameter-binding/specs/planner-dry-run/spec.md
- Lines: 1-31
- SHA256: 4b9511c1b0a6c59b820109201c5aaec9870f6c971123aceb93880c389316466f

```md
## ADDED Requirements

### Requirement: Missing-producer dry-run gap is exercised against the governed capability set
The dry-run evidence suite SHALL exercise the missing-producer gap against the governed capability set rather than defer it. When a goal or a consuming capability input requires a value that no active capability can produce, the dry-run output SHALL report a capability gap identifying the unproducible requirement. This case SHALL be an executed, asserted case; it MUST NOT be carried as a pending or skipped entry, and it MUST NOT be considered covered solely by a lower-level unit test.

#### Scenario: Unproducible requirement yields a capability gap

- **WHEN** a dry-run is compiled for a goal whose required value no active capability produces
- **THEN** the dry-run output contains a capability gap naming that requirement
- **AND** no Gateway validate or execute call is made

#### Scenario: Missing-producer case executes rather than skips

- **WHEN** the dry-run evidence suite runs
- **THEN** the missing-producer case executes and its assertions are evaluated
- **AND** the evidence output does not report it as pending or skipped

### Requirement: Dry-run reports unbound inputs and derivation diagnostics as gaps
When a consuming capability input cannot be bound because the only candidate producer field requires cardinality reduction, or because more than one candidate producer exists, the dry-run output SHALL report the input as a gap carrying the diagnostic kind. The compiler MUST NOT bind the input by choosing a candidate, applying a reduction, or inserting a default.

#### Scenario: Reduction-required candidate is reported as a gap

- **WHEN** the only candidate producer field for a required scalar input has `cardinality: many`
- **THEN** the dry-run output reports that input as a gap carrying the `needsReduction` diagnostic kind
- **AND** the input is not bound to any parameter source

#### Scenario: Ambiguous candidates are reported as a gap

- **WHEN** more than one candidate producer field could bind the same required input
- **THEN** the dry-run output reports that input as a gap carrying the `ambiguous` diagnostic kind
- **AND** the compiler selects none of the candidates

```

## openspec/changes/derived-parameter-binding/specs/registry-ontology-contract/spec.md

- Source: openspec/changes/derived-parameter-binding/specs/registry-ontology-contract/spec.md
- Lines: 1-106
- SHA256: 957d514f27d1470253e3dea817db79f66016fd93d874aed83f930f0d894656ec

[TRUNCATED]

```md
## MODIFIED Requirements

### Requirement: Registry schema validates semantic capability contract
The system SHALL validate `registry/capabilities.yaml` version `2` against a deterministic Registry contract that covers capability identity, semantic metadata, typed inputs, Fact-producing outputs, governance, and executor binding references. Every input MUST declare `bindingKind=identifier|fact`. `bindingKind` SHALL describe what the parameter is, and `satisfiableByFactType` SHALL describe where it may additionally come from: a fact-bound input MUST reference one published `satisfiableByFactType`, and an identifier input MAY also reference one published `satisfiableByFactType` to declare that an upstream Fact can supply it. Every output with `evidenceRole=primaryFact` MUST reference one published `factTypeRef`.

#### Scenario: All active capabilities pass Registry v2 contract
- **WHEN** the contract validator checks the active `MM.Inventory.GetAvailability`, `MM.PurchaseOrder.GetList`, `MM.PR.CreateDraft`, and `MM.Material.GetInfo` entries
- **THEN** validation succeeds for their stable identity, semantic IO, governance, eval linkage, and executor binding references
- **AND** each input is classified as either `bindingKind=identifier` or `bindingKind=fact`, and any input carrying `satisfiableByFactType` references exactly one published Fact Type
- **AND** their primary outputs reference `sapnexus:InventoryAvailabilityFact`, `sapnexus:PurchaseOrderSupplyFact`, `sapnexus:PurchaseRequisitionCreatedFact`, and `sapnexus:MaterialInfoFact` respectively
- **AND** the capabilities remain available to existing Agent and Gateway flows by the same `capabilityId`

#### Scenario: Fact-bound input lacks Fact Type reference
- **WHEN** an input declares `bindingKind=fact` without `satisfiableByFactType`
- **THEN** contract validation fails before graph compilation or runtime execution

#### Scenario: Identifier input declares Fact Type reference
- **WHEN** an input declares `bindingKind=identifier` together with one published `satisfiableByFactType`
- **THEN** contract validation succeeds, and the input is treated as user-suppliable with an upstream Fact as an alternative source
- **AND** a user-supplied value for that input still binds as an identifier rather than as a Fact

#### Scenario: Identifier input references an unpublished Fact Type
- **WHEN** an input declares `bindingKind=identifier` together with a `satisfiableByFactType` that no published Fact Type matches
- **THEN** contract validation fails and names the offending capability and input

#### Scenario: Primary Fact output lacks Fact Type reference
- **WHEN** a primary Fact output omits `factTypeRef` or references an unpublished Fact Type
- **THEN** contract validation fails before the capability can enter the semantic graph

#### Scenario: Malformed capability is rejected before runtime execution
- **WHEN** a Registry entry is missing required identity, semantic fields, governance fields, v2 input/output metadata, eval linkage, or executor binding reference
- **THEN** contract validation fails with a deterministic error
- **AND** the invalid entry is not treated as an executable SAP or external-system capability

### Requirement: Registry v2 migration is atomic and runtime-compatible
The repository SHALL publish capability schema v2, capability Registry v2, Fact Type catalog, and semantic validators as one atomic change. It MUST NOT support a mixed v1/v2 Registry state or alter current technical executor ownership.

#### Scenario: Existing runtime loader reads migrated Registry
- **WHEN** the current Agent Registry loader reads the v2 document
- **THEN** it returns exactly the set of active capability IDs declared in the Registry and their current input descriptors
- **AND** the returned set and count are asserted against the Registry content rather than against a hardcoded number, so registering a capability changes the assertion input and not the assertion logic
- **AND** it does not copy planning metadata into the current CallPlan

#### Scenario: Technical binding ownership remains unchanged
- **WHEN** a migrated capability is validated or later selected by the current runtime
- **THEN** callers still provide only registered `capabilityId` and governed parameters
- **AND** `bindingId`, RFC/OData details, credentials, and executor mappings remain owned by allowlisted Registry/binding artifacts

## ADDED Requirements

### Requirement: Fact Type declares a field-level schema with resolved semantic types
The Fact Type catalog SHALL declare, for every published Fact Type, a field list in which each field declares `name`, `semanticType`, `cardinality` (`one` or `many`), `optional`, and `description`. A field's `semanticType` SHALL be drawn from the same ontology semantic-type vocabulary as capability input and output `semanticType` declarations and as the Fact Type `keyedBy` declaration, and SHALL NOT be drawn from the extraction matcher catalog, whose identifiers occupy a separate namespace. A field's `semanticType` MUST appear as the `semanticType` of at least one capability input or output in the same governed source set; a Fact Type field declaring a semantic type no capability speaks SHALL fail contract validation, because such a field can never participate in a derived data dependency. The field list SHALL be the single authoritative definition of that Fact Type's shape: no other artifact may introduce, rename, or remove a Fact Type field, and any artifact that restates the field list SHALL be validated against the authoritative list.

#### Scenario: Field list with resolved semantic types validates
- **WHEN** the contract validator checks a published Fact Type whose every field declares a `name`, a `semanticType` that some capability input or output also declares, a `cardinality` of `one` or `many`, an `optional` flag, and a `description`
- **THEN** contract validation succeeds for that Fact Type

#### Scenario: Semantic type unknown to every capability fails validation
- **WHEN** a Fact Type field declares a `semanticType` that no capability input or output declares
- **THEN** contract validation fails and names the offending Fact Type and field
- **AND** no semantic graph or Registry Snapshot is published from that catalog

#### Scenario: Matcher catalog identifier on a field fails validation
- **WHEN** a Fact Type field declares a `semanticType` taken from the extraction matcher catalog namespace instead of the ontology vocabulary
- **THEN** contract validation fails and names the offending Fact Type and field
- **AND** the failure is not silently tolerated as an unmatched-but-valid declaration

#### Scenario: Field list without required attributes fails validation
- **WHEN** a Fact Type field omits `name`, `semanticType`, `cardinality`, `optional`, or `description`, or declares a `cardinality` outside `one|many`
- **THEN** contract validation fails with a deterministic error identifying the field

#### Scenario: Restated field list must match the authoritative definition
- **WHEN** another governed or presentation artifact restates the field names of a published Fact Type
- **THEN** a conformance check compares the restatement against the authoritative field list
- **AND** the check fails when a restated name is absent from, or missing relative to, the authoritative list

### Requirement: The extraction matcher catalog maps one-way onto the ontology vocabulary
The extraction matcher catalog is the source of utterance-extraction matchers, not the authority for semantic types. Each matcher entry SHALL declare `extracts` naming exactly one ontology semantic type, and SHALL NOT declare that it extracts two or more different ontology types. One ontology semantic type MAY be extracted by several matcher entries, and MAY be extracted by none — a value obtainable only from the system legitimately has no extractor, and the absence of a matcher entry SHALL NOT be treated as a catalog defect to be back-filled. The mapping is one-way: the ontology vocabulary SHALL NOT reference matcher identifiers. Contract validation SHALL reject any `sapnexus:` reference that does not exist in the ontology vocabulary, and SHALL reject any `extracts` target that does not exist in the ontology vocabulary.

#### Scenario: One-way mapping validates

```

Full source: openspec/changes/derived-parameter-binding/specs/registry-ontology-contract/spec.md

## openspec/changes/derived-parameter-binding/specs/semantic-plan-authoring-v2/spec.md

- Source: openspec/changes/derived-parameter-binding/specs/semantic-plan-authoring-v2/spec.md
- Lines: 1-127
- SHA256: d7a23b631da6992dce9d50add6c4c5f95e9f9106f49ec552cff953145f7e8230

[TRUNCATED]

```md
## MODIFIED Requirements

### Requirement: v2 compiler authors full parameter provenance and relations

The system SHALL provide a deterministic v2 compiler that compiles `GoalSpec` / `PlanDraft` plus the `RegistrySnapshot`-bound `SemanticSourceDocuments` into a PlanGraph v2. The compiler SHALL author `literal` and `factField` parameter sources in addition to `goalConstraint`, SHALL author `data` and `dependency` edges derived from the snapshot, and SHALL partition nodes into `readPartition` / `actionPartition`. Eligibility for a `factField` source SHALL be determined by the consuming input declaring `satisfiableByFactType`, not by its `bindingKind`. A `factField` source SHALL identify the producer field selected for that specific consuming input by semantic-type equality; the compiler MUST NOT select the producer's first matching field irrespective of which input is being bound, and MUST NOT resolve a Fact Type's producer by position when more than one capability produces it. The compiler SHALL NOT author a `factField` source for a parameter that already carries a `goalConstraint` or `literal` source. When one producer node supplies more than one input of the same consumer node from the same Fact Type, the compiler SHALL author one `factField` source per bound input and exactly one `data` edge for that producer/consumer/Fact Type triple. The `registeredDefault` source kind is defined in the v2 schema as part of the 4-source closed set but SHALL NOT be authored this phase (no capability input declares a registered default); it is reserved for future activation. The compiler MUST NOT call the LLM, the Gateway, or SAP.

#### Scenario: Identifier input bound by goalConstraint

- **WHEN** a required identifier input matches a GoalConstraint by name and semantic type
- **THEN** the v2 compiler authors a `goalConstraint` parameter source

#### Scenario: Fact input bound by factField produces a data edge

- **WHEN** a required fact-bound input carrying no user-supplied source is bound by a `factField` source from a producer node
- **THEN** the v2 compiler authors a `factField` parameter source and a matching `data` edge

#### Scenario: Identifier input declaring a Fact Type is bound by factField

- **WHEN** a required input with `bindingKind=identifier` declares `satisfiableByFactType` and carries no user-supplied source
- **THEN** the v2 compiler authors a `factField` parameter source and a matching `data` edge for it
- **AND** eligibility is determined by the `satisfiableByFactType` declaration rather than by `bindingKind`

#### Scenario: A user-supplied source suppresses the factField source

- **WHEN** a required input declaring `satisfiableByFactType` already carries a `goalConstraint` or `literal` parameter source
- **THEN** the v2 compiler authors no `factField` source for that parameter
- **AND** exactly one parameter source exists for that parameter name

#### Scenario: Field selection is per consuming input

- **WHEN** one producer node can supply two different inputs of the same consumer node from the same Fact Type
- **THEN** each authored `factField` source identifies the producer field whose semantic type equals that input's semantic type
- **AND** the two sources do not identify the same producer field

#### Scenario: Multiple bound inputs share one data edge

- **WHEN** two `factField` sources on one consumer node reference the same producer node and the same Fact Type
- **THEN** the compiler authors exactly one `data` edge for that producer/consumer/Fact Type triple
- **AND** validation does not report a duplicate data edge

#### Scenario: registeredDefault source is reserved this phase

- **WHEN** the v2 schema defines `registeredDefault` as part of the 4-source closed set
- **THEN** the v2 compiler does not author a `registeredDefault` source this phase (no capability input declares a registered default)
- **AND** the source kind is reserved for future activation when capability inputs declare registered defaults

#### Scenario: Dependency relation produces a dependency edge

- **WHEN** the snapshot relation catalog declares a `dependsOn` relation between two capabilities present in the plan
- **THEN** the v2 compiler authors a `dependency` edge from prerequisite to dependent

#### Scenario: Compiler is deterministic and non-executing

- **WHEN** the v2 compiler runs on the same GoalSpec and snapshot repeatedly
- **THEN** it returns the same PlanGraph v2
- **AND** it calls no LLM, Gateway validate, Gateway execute, or SAP

## ADDED Requirements

### Requirement: A derived parameter is produced by plan execution, never by intent-time fetching

A parameter value derived from another capability's output SHALL be produced by executing the upstream node as part of the plan, in the order the plan declares. The intent and planning layers SHALL only author the upstream node, the consuming binding, and the edge between them. The intent layer MUST NOT call the Gateway, an RFC, an OData service, or any other data source while parsing an utterance or resolving a parameter, and MUST NOT obtain the value by any path other than the executed upstream node.

#### Scenario: Derived parameter requires an upstream node and an edge

- **WHEN** a consuming capability input is to be satisfied from another capability's output
- **THEN** the plan contains the producing capability as an upstream node, a `factField` source on the consuming node, and a `data` edge from producer to consumer
- **AND** the producing node precedes the consuming node in topological order

#### Scenario: Intent-time data fetching is not a source of derived values

- **WHEN** the intent layer resolves a parameter whose declared source is another capability's output
- **THEN** it produces a plan declaration and no Gateway validate, Gateway execute, RFC, OData, or SQL call is made during parsing
- **AND** the value appears only after the upstream node has executed

#### Scenario: Derived parameter does not bypass approval

- **WHEN** a write capability's parameter is derived from an upstream node's output
- **THEN** the write node still requires a recorded human confirmation before execution
- **AND** the derivation does not alter, weaken, or pre-satisfy the approval requirement

```

Full source: openspec/changes/derived-parameter-binding/specs/semantic-plan-authoring-v2/spec.md

## openspec/changes/derived-parameter-binding/specs/semantic-planning-foundation/spec.md

- Source: openspec/changes/derived-parameter-binding/specs/semantic-planning-foundation/spec.md
- Lines: 1-103
- SHA256: 002604f5d2d36694678b546757e9b004c864441316b03af5b13550e22d61f542

[TRUNCATED]

```md
## MODIFIED Requirements

### Requirement: Canonical Fact Types and capability relations have single owners
The system SHALL publish a versioned Fact Type catalog and a versioned capability relation catalog. Capability output `factTypeRef` SHALL be the only authored source for `producesFactType`; fact-bound input `satisfiableByFactType` SHALL be the only authored source for `consumesFactType`; the relation catalog SHALL author only `dependsOn` and `precondition`. Every relation SHALL declare `origin` as either `derived` or `manual`, and an `origin: manual` relation SHALL declare a `justification` stating why the relation cannot be computed. A relation declared `origin: manual` that the deriver can compute from Fact Type field semantic types SHALL fail contract validation: the prohibition on hand-authoring a derivable data dependency is enforced by running the deriver, not by review. The acceptance criterion for a data dependency being present is that the derived view contains it, never that the relation catalog is non-empty.

#### Scenario: Compiler derives production edges
- **WHEN** a primary capability output references a published Fact Type
- **THEN** the semantic graph contains one `producesFactType` edge from the capability to that Fact Type
- **AND** the relation catalog does not repeat that derived edge

#### Scenario: Authored derived edge is rejected
- **WHEN** the relation catalog declares `producesFactType` or `consumesFactType`
- **THEN** contract validation fails before a semantic graph is published

#### Scenario: Manually authored derivable data dependency is rejected
- **WHEN** the relation catalog authors an `origin: manual` relation that reproduces a data dependency the deriver can compute from Fact Type field semantic types
- **THEN** contract validation fails and names the relation and the derivable edge it duplicates
- **AND** no semantic graph or Registry Snapshot is published from that catalog

#### Scenario: Manual relation without justification is rejected
- **WHEN** a relation declares `origin: manual` without a `justification`
- **THEN** contract validation fails and names the relation

#### Scenario: Missing relation endpoint is rejected
- **WHEN** a `dependsOn` capability or `precondition` Fact Type does not exist
- **THEN** contract validation reports `RELATION_ENDPOINT_NOT_FOUND` at the exact JSON Pointer path

## ADDED Requirements

### Requirement: Data dependency edges are derived from field semantic types by strict equality
The system SHALL derive candidate data dependency edges deterministically, without any model call, by matching a producer Fact Type field's `semanticType` against a consuming capability input's `semanticType`. The candidate set for a consuming input SHALL be scoped to the fields of the single Fact Type that input declares as `satisfiableByFactType`, and to the active capabilities that produce that Fact Type; the deriver SHALL NOT search Fact Types the consuming input has not declared. A match SHALL require string equality of the semantic type identifiers. The deriver MUST NOT use similarity, prefix, substring, fuzzy, or embedding comparison, and MUST NOT consult field names, descriptions, or ordering to establish a match. Given the same governed sources the deriver SHALL return the same result.

#### Scenario: Equal semantic types produce a candidate edge
- **WHEN** a consuming capability input declares a `satisfiableByFactType`, and exactly one field of that Fact Type declares the same `semanticType` as the input, and that field is scalar
- **THEN** the derived view contains one candidate edge from that producer field to that consuming input

#### Scenario: Different semantic types produce no edge
- **WHEN** a producer Fact Type field and a consuming capability input declare different `semanticType` values, however similar their names
- **THEN** the derived view contains no candidate edge between them
- **AND** no approximate or partial match is reported as a candidate

#### Scenario: A field of an undeclared Fact Type is not a candidate
- **WHEN** a Fact Type the consuming input does not declare as `satisfiableByFactType` contains a field of the same `semanticType` as that input
- **THEN** that field is not reported as a candidate for that input
- **AND** its presence does not make the input ambiguous

#### Scenario: Derivation is deterministic and non-executing
- **WHEN** the deriver runs repeatedly against the same governed sources
- **THEN** it returns the same candidate edges and the same diagnostics in the same order
- **AND** it performs no model call, Gateway call, or SAP call

### Requirement: Cardinality mismatch and ambiguity are reported, never resolved silently
The deriver SHALL NOT match a producer field whose `cardinality` is `many` to a scalar consuming input; it SHALL instead emit a `needsReduction` diagnostic naming the producer field and the consuming input. No reduction operator SHALL be applied, chosen, or defaulted. When more than one field within the consuming input's declared Fact Type matches that input's `semanticType`, or when more than one active capability produces that Fact Type, the deriver SHALL NOT select one; it SHALL emit an `ambiguous` diagnostic listing every candidate for human resolution. A diagnostic SHALL NOT be silently downgraded into a match, and a diagnosed input SHALL be reported as unbound rather than bound.

#### Scenario: Many-cardinality producer feeding a scalar input needs reduction
- **WHEN** a producer Fact Type field declares `cardinality: many` and a consuming input of the same `semanticType` is scalar
- **THEN** the derived view contains no candidate edge between them
- **AND** a `needsReduction` diagnostic names the producer field and the consuming input

#### Scenario: No reduction operator is applied
- **WHEN** a `needsReduction` diagnostic is emitted
- **THEN** no aggregation, first-element selection, single-element requirement, or extremum is applied to produce a value
- **AND** the consuming input remains unbound by that candidate

#### Scenario: Multiple matching fields within the declared Fact Type are ambiguous
- **WHEN** two or more fields of the consuming input's declared Fact Type match that input's `semanticType`
- **THEN** the derived view contains no candidate edge for that input
- **AND** an `ambiguous` diagnostic lists every candidate producer field

#### Scenario: Multiple producers of the declared Fact Type are ambiguous
- **WHEN** two or more active capabilities produce the Fact Type a consuming input declares
- **THEN** the derived view contains no candidate edge for that input
- **AND** an `ambiguous` diagnostic lists every producing capability

### Requirement: The derived data dependency view is reviewable
The system SHALL expose the derived candidate edges and diagnostics as an inspectable artifact and as a printable command output, so a human can review what the deriver concluded before it is relied upon. The view SHALL identify, for each candidate edge, the producing capability, the producing Fact Type field, the consuming capability, the consuming input, and the matched `semanticType`; and for each diagnostic, its kind and the entities involved. A derived edge SHALL be emitted in the same shape as an authored `dependsOn` relation, so the existing plan compiler consumes it without a new relation type being introduced for derivedness. An empty view SHALL be reported as empty rather than as an error.

#### Scenario: View reports candidate edges with full provenance
- **WHEN** the derived view is produced from the governed sources
- **THEN** each candidate edge names its producing capability, producing Fact Type field, consuming capability, consuming input, and matched `semanticType`

```

Full source: openspec/changes/derived-parameter-binding/specs/semantic-planning-foundation/spec.md

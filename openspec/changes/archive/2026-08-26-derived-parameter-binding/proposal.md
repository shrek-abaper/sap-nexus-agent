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
  cases for: derived values are **not** asked and carry `provenance=capability_derived`; an empty
  or failing upstream degrades to **asking**, never to a silent default or a fabricated value; a
  user-supplied value conflicting with a derived value follows the declared priority and the
  conflict is recorded; an unreachable upstream capability emits a `CapabilityGap` and **errors
  instead of attempting a degraded fallback** (governance red line). Also convert the existing
  `SKIP (pending): dry-run-missing-producer` in `scripts/verify-agent-callplan-evidence.sh` into
  a real case.

**Fixed design decision (not re-opened here):** the planner layer is the single source of truth —
`inputs[].bindingKind: fact` + `inputs[].satisfiableByFactType`. The intent layer's
`binding.sources[{kind: capabilityOutput, ...}]` is **derived** from it and must never be
hand-authored in YAML.

**No-split decision.** The PRD split preflight was evaluated and splitting is **not**
recommended: T0′ → T1 → T2 → T3 → T4/T5 is a strictly linear dependency chain (finding F7 pulls
T5's case skeleton ahead of T3), all six items share a single acceptance surface (the six
verification commands plus the release gate at 22/22), and the exit condition "the derived-edge
view is non-empty" can only be evaluated after T3 exists. This batch is a single hard gate; the
follow-on decision-log batch is a separate change committed independently.

## Capabilities

### New Capabilities

None. Every behavioural delta lands on an existing spec below; no new capability path is
introduced. T1's field-level schema and T2's deriver are requirement additions to the existing
registry-contract and planning-foundation capabilities rather than new capabilities, because
they refine an already-specified contract (the RegistrySnapshot's four governed sources and the
relation-catalog ownership rule) instead of introducing a new governed surface.

### Modified Capabilities

- `registry-ontology-contract`: FactType gains a field-level schema whose `semanticType` values
  must resolve against `registry/semantic-types.yaml`; the active capability set becomes four,
  not three; inputs may be classified `bindingKind=fact`. Two existing scenarios contradict this
  change and are MODIFIED rather than extended — `spec.md:12` ("each existing input is classified
  as `bindingKind=identifier`") and `spec.md:114` ("it returns the same three active capability
  IDs").
- `declarative-intent-extraction`: the `capabilityOutput` execution path stops being allowed to
  remain unimplemented. `spec.md:243-247` and `spec.md:262-266` currently *require* a failing
  xfail placeholder; those become real passing behaviour
  (`agent/tests/test_binding_sources.py:167` and `:242`). The three-tier priority
  `capabilityOutput > userUtterance > default` from `spec.md:240-241` is what gets implemented.
- `semantic-planning-foundation`: relation-catalog ownership is restated (open question 1 below),
  and `producesFactType` / `consumesFactType` derivation is extended down to the field level so a
  data-dependency edge is computed from field `semanticType` rather than from a capability-level
  FactType match alone.
- `semantic-plan-authoring-v2`: `factField.field` selection becomes semanticType-driven per
  consumer parameter. Today the field means the producer **capability output name** and
  `_first_fact_field()` ignores which parameter is being bound, so one producer feeding two
  parameters would give both the same field — one of them wrong (finding F1).
- `agent-callplan-evidence`: sequence-type eval cases are added as a governed evidence class,
  alongside the existing single-utterance cases.
- `planner-dry-run`: `dry-run-missing-producer` becomes a real executed case rather than a
  pending skip.
- `output-projection`: the frontend field list becomes conformance-locked against the
  authoritative FactType field definition, and the projection registry must resolve a builder for
  every active capability that produces a primary fact.

## Impact

**Registry and schema (authoritative surfaces)**
- `schemas/fact-type-catalog.schema.json` — new `fields` array.
- `ontology/fact-types.yaml` — field lists for the three existing FactTypes.
- `registry/capabilities.yaml` — `MM.Material.GetInfo` added; PR `unit` / `purchasing_group`
  switch to `bindingKind: fact` + `satisfiableByFactType`; T0′ binding-source migration.
- `registry/executor-bindings.yaml` — the new `BAPI_MATERIAL_GET_DETAIL` binding, transcribed
  from live SE37 metadata.
- `ontology/capability-relations.yaml` — no derivable data edge may be authored here.

**Governed snapshot churn (F6)**
`ontology/fact-types.yaml` is a governed snapshot source
(`agent/sap_nexus_agent/semantic_planning/loader.py:34-35`,
`contracts.py:107-108`), and `semantic-planning-foundation/spec.md:41-44` requires `snapshotId`
to change when any governed source's content changes. Non-archive fixtures needing recomputation:
`agent/tests/fixtures/semantic_planning/plan-material-supply.yaml` and `evals/matcher_cases.yaml`.
The `sha256:` values in `test_approval.py` / `test_orchestrator.py` are approval **subject**
hashes and are unrelated — they are not touched. Hardcoded assertions that will break and must be
updated with a stated semantic reason: `agent/tests/test_registry_loader.py:23`
(`len(catalog.capabilities) == 3`) and `agent/tests/test_recall.py:64,74,84,95,117`
(full three-capability tuples).

**Python (invariant 6 — must be reported as two separate numbers, F2)**
`validation.py:483-496` tolerates N `factField` sources sharing one `data` edge, but
`plan_compiler_v2.py:277` appends one edge per binding, so the first producer feeding two
parameters yields two same-key edges and `validation.py:533-540` rejects them as a
`duplicate semantic data edge`. This is a **pre-existing compiler defect that only the first
multi-field producer can expose**. Fixing it requires Python changes, so the final report must
carry two distinct figures: *(a)* Python lines required to **register** the capability — target 0
— and *(b)* Python lines to fix pre-existing compiler defects exposed by the first multi-field
producer. The convention is fixed here, in `open`, not discovered at `verify`.

**Frontend (TypeScript may change; the line count is reported truthfully)**
- `frontend/src/runtime/projection/fact-builder.ts:9-16` is a registry keyed by `capabilityId`
  with only two builders registered, and `resolve()` returns `null` when absent — so
  `MM.Material.GetInfo` needs a builder declaration or its node produces no fact and the whole
  edge breaks.
- `frontend/src/runtime/plan-evidence/event-projector.ts:69`'s `fact` payload-key allow-list does
  not contain the new field names; without them the values are stripped and the derived parameter
  is not traceable in the approval UI, which T3 requires.

**Narration (F3)**
`narrate_single_value` (`agent/sap_nexus_agent/narrator.py:235-246`) raises `NarrativeGuardError`
unless `material` / `plant` / `value` / `unit` are all non-empty, its LLM prompt labels
`fact.value` as an inventory quantity (`narrator.py:203-207`), and its fallback appends MRP
element detail (`narrator.py:260`). The `narrative.factShape` enum
(`single-value | list | action-receipt`) has no member for "two scalar attributes".
`narrative` is **not** in `capability.schema.json`'s required list, so omitting the block for a
pure upstream capability is a candidate mitigation that preserves zero Python lines — `design.md`
must first confirm no code path requires `narrative` for every capability. Note
`agent-callplan-evidence/spec.md:238-243` already promises template-free LLM narration for a
newly registered capability; that promise currently holds only for inventory-shaped facts, and
T3 is its first real test.

**Approval / D4 coupling (invariant 5 — marked, not changed)**
No approval / subject-hash / anti-replay semantics change in this batch. The upstream nodes added
here become inputs to defect D4 (extending the approval subject to a joint hash over WRITE
parameters plus upstream Fact `asOf` plus `snapshotId`), so every Fact retains `asOf` and
`snapshotId`, and the coupling points are recorded:
`parameterSnapshotHash` / `factSetHash` / `subjectHash` in `event-projector.ts`'s `approval`
allow-list. A parameter being derived is never a reason to skip or simplify human approval.

**Explicitly out of scope**
Defect D3 (editable plans / `PlanDraft` exposed for user review); defect D4 (approval-subject
joint hash — coupling marked only); defect D6 (`TraceSpan` → OpenTelemetry); cardinality
reduction operators (`sum` / `first` / `requireSingle` / `max`) and `freshnessTolerance`
(thresholds must come from `asOf` drift measured in a live composition smoke, not guessed);
multi-WRITE / Saga / automatic compensation; graph database and OWL reasoning runtime; semantic
recall via embeddings or multi-signal fusion (its trigger is AMBIGUOUS share above 5% for two
consecutive weeks, which is not the case now); the 5th and later capabilities; and the entire
follow-on decision-log batch (`IntentDecisionRecord` persistence, `user_corrected` →
regression-case pipeline, SLI report, ratchet), which is gated behind this change's exit
conditions. Note: `Dx` identifiers are **defect** numbers from the architecture assessment, never
task numbers.

**No new dependencies.** No pip or npm dependency is added. No second agent runtime
(LangChain / LangGraph / DeerFlow / OpenHarness / DeepSeek Harness / Microsoft Agent Framework) is
introduced — only design shapes may be borrowed. Consistency stays with JSON Schema plus the
Registry Validator; no graph database, no OWL reasoning runtime. Execution authority stays in the
Java Gateway; the Agent proposes intents and plan candidates through registered `capabilityId`
values only. The fail-closed executors (`CDS_ADT` / `REST_JSON` / `SQL_READ`) remain in their
refusing state.

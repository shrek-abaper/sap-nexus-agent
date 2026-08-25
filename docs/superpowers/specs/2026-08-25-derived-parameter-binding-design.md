---
comet_change: derived-parameter-binding
role: technical-design
canonical_spec: openspec
---

# Derived Parameter Binding — Technical Design

Make it physically possible for a capability parameter to be *derived* from an upstream Fact instead of
asked of the user, so that `provenance.capability_derived` can be non-zero for a legitimate reason.

The canonical requirement source is `openspec/changes/derived-parameter-binding/specs/`. This document
records **how**, not **what**. Where the two disagree, the OpenSpec delta wins.

---

## 1. Root cause — one layer below the brief's diagnosis

The brief attributes the permanent `capability_derived == 0` to "FactType is an opaque label with no
field list". That is true and it is the *second* blocker. The first is that `bindingKind` is an
**exclusive switch**:

| Evidence | Fact |
| --- | --- |
| `schemas/capability.schema.json` `$defs/ioField/allOf[1]` | `bindingKind: identifier` **forbids** `satisfiableByFactType` |
| `$defs/ioField/allOf[0]` | `bindingKind: fact` **requires** `satisfiableByFactType` |
| `agent/sap_nexus_agent/planner/plan_compiler_v2.py:253` | only a `fact` + `required` input gets a `factField` source and a data edge |
| `plan_compiler_v2.py:366-395` | only an `identifier` input gets a `goalConstraint` / `literal` source |
| `registry/capabilities.yaml` | all 15 inputs are `bindingKind: identifier`; `satisfiableByFactType` occurs 0 times; `binding.sources[]` occurs 0 times |
| `ontology/capability-relations.yaml` | the entire file is `version: 1` + `relations: []` |
| `ontology/fact-types.yaml` | 3 entries, none with a `fields:` key |

An `identifier` value can only come from the user; a `fact` value can only come from upstream. No input
can be both, so no parameter can *become* derivable without ceasing to be user-suppliable. Unlocking
the field list alone would not have produced a single derived edge.

Also latent and relevant: `capabilityOutput` is already schema-complete
(`$defs/bindingSource`, requiring `factType` + `field`, described as *"reserved for future dependency
edges; accepted and validated, execution unimplemented"*), and `extraction/engine.py:24` excludes it
from `_WIRED_SOURCE_KINDS` with `:129-136` naming its landing point *"dependency-edge binding (D2)"*.
The design was anticipated and parked.

---

## 2. Decoupling `bindingKind` from source eligibility

`bindingKind` returns to meaning **what the parameter is** (a scalar identifier). `satisfiableByFactType`
means **where it may also come from**. An `identifier` input MAY declare `satisfiableByFactType`.

Every affected check keeps its semantic-type / factType equality assertion; only the `bindingKind`
coupling is dropped. No check becomes weaker.

| Site | Change |
| --- | --- |
| `schemas/capability.schema.json` `$defs/ioField/allOf[1]` | drop `not.required` on `satisfiableByFactType`; `allOf[0]` unchanged |
| `scripts/validate_registry_contract.py:491-495` | drop the identifier prohibition |
| `agent/sap_nexus_agent/semantic_planning/validation.py:438-441` | `factField` validity keyed on `satisfiableByFactType` equality, not on `bindingKind == "fact"` |
| `semantic_planning/validation.py:1426-1433` | same, at registry-contract level |
| `semantic_planning/graph.py:68` | build `consumesFactType` on `satisfiableByFactType` presence |
| `planner/plan_compiler_v2.py:253` | second-pass gate keyed on `satisfiableByFactType` presence |

`graph.py:68` is load-bearing rather than cosmetic: the planner's closure (§4) walks the
`consumesFactType` edge. Left keyed on `bindingKind == "fact"`, the semantic graph would never record
that `MM.PR.CreateDraft` consumes `MaterialInfoFact` and the closure would find nothing.

**Deliberately untouched, and still correct**: `planner/handoff.py:84`,
`plan_compiler_v2.py:97/112/367/381`, `planner/plan_compiler.py:213`, `validation.py:409/424`. The two
target inputs remain `identifier`, so a user-supplied value still becomes a GoalConstraint or literal —
which is exactly what §5 requires.

None of the six sites is per-capability. **Invariant 6 holds: adding the 4th capability changes 0 lines
of Python.**

### Rejected alternatives

- **Flip the two inputs to `bindingKind: fact`.** A required WRITE input would get *zero* parameter
  sources whenever no upstream node is planned: `:253` enters the second pass, `:258-259` finds no
  producer and `continue`s, and `:366`/`:381` skip it for not being `identifier`. Cheapest in code,
  worst in behaviour.
- **Add a third `bindingKind`.** Touches every `identifier` comparison
  (`plan_compiler_v2.py:97/112/367/381`, `plan_compiler.py:213`, `handoff.py:84`, `graph.py:68`,
  `validation.py:409/424/439`), and derivedness is a property of an edge's provenance, not a kind of
  parameter.

---

## 3. Fact Type field schema

`schemas/fact-type-catalog.schema.json` is `additionalProperties: false` with a 7-key `required` list, so
`fields` must be added explicitly to `$defs/factType`.

Each field declares `name`, `semanticType` (ontology vocabulary), and `cardinality` (`one` | `many`).

**`fields` is required for every Fact Type, and the catalog `version` bumps to `2`.** Adding a required
key is a breaking catalog change; the version is the mechanism that tells a consumer it may rely on
`fields` existing. `registry/semantic-types.yaml` already sets the `version: 2` precedent. This requires
changing the schema's `"version": {"const": 1}` accordingly.

Per design Decision 1, a field's `semanticType` uses the **ontology vocabulary** (`sapnexus:*`), the same
vocabulary as capability `inputs[]`/`outputs[]` `semanticType` and `keyedBy` — *not* the bare-id matcher
catalog. The closed set is the set of semantic types used by capability inputs/outputs, which today is:

`sapnexus:` `AcctAssignmentCat`, `AvailableQuantity`, `CostCenter`, `DeliveryDate`,
`InventoryAvailabilityReadFunction`, `MaterialNumber`, `MrpElementLine`, `Plant`, `PrNumber`,
`PurchaseOrderItem`, `PurchaseOrderListReadFunction`, `PurchaseOrderNumber`,
`PurchaseRequisitionCreateAction`, `PurchasingGroup`, `Quantity`, `SapReturnMessage`, `Supplier`,
`UnitOfMeasure`.

`registry/semantic-types.yaml` keeps its extraction-matcher job, gains a header comment stating that
job, and is **not** renamed. Each entry gains a one-way `extracts: sapnexus:<Type>`. `extracts` is a
single string, not a list: one entry is one extractor and yields one ontology type. Two entries MAY
declare the same target; an ontology type obtainable only from the system legitimately has no extractor,
so `sapnexus:AvailableQuantity` having no matcher entry is correct and is not to be back-filled.

`scripts/validate_registry_contract.py` already loads this catalog via `load_semantic_type_catalog`,
which is where the two new rules land: every `sapnexus:*` reference must exist in the ontology
vocabulary, and every `extracts:` target must exist in the ontology vocabulary.

### Snapshot churn is unavoidable and must be explained, not absorbed

`semantic_planning/snapshot.py:38` and `:45` hash the **whole document** with no key filtering
(`_sha256_id(document)`, `_sha256_id(dict(documents))`). Adding `fields:` therefore changes the
fact-types digest **and** `snapshot_id`. Every fixture pinning a `snapshot_id` must be recomputed with
its semantic reason stated in the commit body. Silently refreshing a snapshot is forbidden by
invariant 9.

**Approval subject hashes are not touched.** See §8.

---

## 4. Producer auto-pull as a closure over `desired_fact_types`

The node set is **not** built from `matched_intents`. `plan_compiler_v2.py:213-233` builds one node per
entry in `goal.desired_fact_types`, resolving the producer through `_index_producers_by_fact_type(cards)`.

So auto-pull needs no new node-construction code. It is a **closure**: when a consumer's `required`
input is **not bound by the user** and declares `satisfiableByFactType: F`, and `F` is not already
desired, add `F` to `desired_fact_types`. The existing loop then materializes the producer node and
`producers_by_fact` resolves it.

The closure lives in `build_goal_spec`, not inside `_build_plan_graph_v2`, so the PlanGraph's own
GoalSpec records **why** the extra node exists. That is what makes the extra read auditable instead of a
silent planner side effect.

### The safety constraint is a schema invariant, not a policy

Only a producer whose capability is **`kind: Function`** may be pulled in.
`capability.schema.json` `$defs/capability/allOf[0]` requires `kind: Function` ⇒ `sideEffect: none` +
`requiresApproval: false` + `approvalPolicy: not_required`; `allOf[1]` requires `kind: Action` ⇒
`sideEffect: sap_write` + `requiresApproval: true` + `approvalPolicy: human_required`.

An auto-pull restricted to `kind: Function` therefore **structurally cannot** drag in a WRITE and cannot
bypass Human Approval. Invariant 5 is protected by the schema rather than by reviewer discipline. The 4th
capability must be declared `kind: Function`.

Disclosure is mandatory: the narration states that an extra read occurred, and the approval card marks a
derived value as derived rather than user-entered.

### Rejected alternatives

- **Confirm the extra READ with the user first.** Raises a `sideEffect: none` read to WRITE-level
  ceremony and adds a round trip to every PR.
- **Only pull when the utterance itself recalled the producer.** Then the demo case derives nothing and
  the PlanGraph data edge stays empty — the change would pass its own acceptance while delivering nothing.

---

## 5. Precedence: user-supplied beats upstream-derived

When the user explicitly supplies a value and an upstream producer could also supply it, the **user's
value wins**. Implemented in the compiler's second pass: do not author a `factField` source for a
parameter that already carries a `literal` or `goalConstraint` binding.

Because precedence is applied **at authoring time**, exactly one source is authored per parameter, so the
"two parameterBindings for one parameterName" hazard is dissolved mechanically rather than by a dedup
rule.

The trigger conditions of §4 and §5 are complementary, so there is no conflict and no wasted call:

- input already bound by the user → no closure entry, no producer node, no extra READ, `literal` wins;
- input not bound → closure adds the fact type, producer node appears, the parameter is not elicited,
  `factField` wins.

### `satisfiableByFactType` is the only declaration

Derivation is computed at runtime by semantic-type equality — which is what `plan_compiler_v2.py:253-286`
already does. The registry does **not** restate the derived field via a `capabilityOutput` source.
Nothing restates the derived field, so field-level drift is structurally impossible and no draft→publish
flow is needed.

Accepted cost: reading `registry/capabilities.yaml` does not reveal that `unit` will be derived. The
reviewable derived view is the compensating control, which is why its positive control (§7) is
load-bearing rather than decorative.

### No published requirement is overturned

The `binding.sources[]` priority contract governs source resolution **inside the extraction layer**.
Since this change declares no `capabilityOutput` source, that contract is never exercised. The following
were priced in earlier and are **not** needed — recorded as void rather than quietly dropped:

| Previously priced | Actual |
| --- | --- |
| MODIFIED requirement `Input binding sources and priority` (`openspec/specs/declarative-intent-extraction/spec.md:234-254`) | not needed — governs a different layer |
| reorder `extraction/engine.py:24` `_SOURCE_PRIORITY` | not needed |
| the priority sentence in `capability.schema.json:430` and `extraction-declaration.schema.json:238` | not needed |
| reverse `agent/tests/test_binding_sources.py:120-128` `test_capability_output_beats_user_utterance_when_wired` | not needed — stays green, untouched |

Replaced by one **additive** requirement: a parameter already bound from a user-supplied value SHALL NOT
be re-bound from an upstream Fact. Both layers state their own precedence and do not contradict.

`capabilityOutput` remains deliberately unwired; its existing xfail placeholder keeps its role as the
fixed landing point.

---

## 6. Deriver shape

The established repository pattern is **one script = one command** — `scripts/validate-registry-contract.py`
is a hyphenated thin wrapper over the underscored module with `main(argv) -> int`, errors to stderr,
exit 1. There are no argparse subparsers anywhere in `agent/` or `scripts/`.

- **Logic**: `agent/sap_nexus_agent/semantic_planning/derivation.py` — a pure function over
  `SemanticSourceDocuments` returning derived edges. Three consumers: the `build_goal_spec` closure (§4),
  the `plan_compiler_v2` second pass (§5), and the validator rule that rejects a manually authored
  derivable relation.
- **View**: `scripts/derive-data-dependencies.py` — thin wrapper printing the derived view for review.

Matching rule (design Decision 2): the consumer's `satisfiableByFactType` **scopes** the candidate set to
one Fact Type's fields; within that scope the field is selected by **semantic-type equality**. Scoping
first is what prevents a spurious global ambiguity from killing T3's edge.

A derived edge is emitted in the same shape as an authored `dependsOn` relation, so
`plan_compiler_v2.py:299-312` consumes it unchanged. No new relation-type name is invented; derivedness
is carried by `origin: derived | manual` (`justification` required on `manual`), and the prohibition on
hand-writing a derivable edge is enforced by **running the deriver**, not by reviewer discipline.

### Two defects of the same family must be fixed, not counted

- **F1 / `_first_fact_field` (`plan_compiler_v2.py:265`)** selects the producer output by *first whose
  `factTypeRef` matches*. Replaced by semantic-type equality.
- **`producers[0]` (`plan_compiler_v2.py:217`)** silently picks one capability when several produce the
  same Fact Type. Latent today (one producer per Fact Type) but auto-pull makes it load-bearing, so it
  belongs in the ambiguity diagnostics rather than being left to chance.

### Defect 1 is on the critical path, not a pre-existing item to tally

When the user supplies `unit` but not `purchasing_group`, one (producer → consumer) pair yields **two**
`factField` bindings that must share **one** data edge. `validation.py:483-496` tolerates N sources per
edge, but `plan_compiler_v2.py:277` appends one edge per binding and duplicates are then rejected.
This blocks T3's headline edge and must be fixed in this change. Its line count is still reported
separately per design Decision 5, attributed to Defect 1.

---

## 7. T3's headline edge, concretely

**Producer** — the 4th capability, `kind: Function`, producing `sapnexus:MaterialInfoFact` with four
fields and **zero new semantic types**:

| Field | semanticType | cardinality | SAP origin |
| --- | --- | --- | --- |
| `material` | `sapnexus:MaterialNumber` | one | key |
| `plant` | `sapnexus:Plant` | one | key |
| `baseUnitOfMeasure` | `sapnexus:UnitOfMeasure` | one | `MARA-MEINS` (client level) |
| `purchasingGroup` | `sapnexus:PurchasingGroup` | one | `MARC-EKGRP` (material plant view) |

Field names follow the existing fact-payload convention (`material`, not `materialNumber` — the
inventory narrative already renders `{material}`), per in-change design Decision 11. Both keys are
required because the two values live at different SAP levels, so a material-only call cannot yield the
purchasing group.

**Consumers** — `MM.PR.CreateDraft` inputs `unit` (`registry/capabilities.yaml:415-429`,
`sapnexus:UnitOfMeasure`) and `purchasing_group` (`:442-456`, `sapnexus:PurchasingGroup`).

**T0′ reduces to one edit per input.** `registry_loader` already normalizes the deprecated `extraction:`
alias into a single `userUtterance` source (pinned by
`test_extraction_alias_normalizes_to_single_user_utterance_source`), so migrating the two inputs to an
explicit `binding.sources[]` block buys no behaviour. T0′ is: **add `satisfiableByFactType` to `unit` and
`purchasing_group`**. The alias migration is orthogonal cleanup, flagged and not performed.

### Testing strategy

- **Positive control** (design Decision 13) — two synthetic capabilities with a pair of fields that must
  match; assert the deriver produces that edge. It must be green even when the real derived view is
  empty, because "an empty view is a legitimate result" and "the deriver can never match anything" are
  otherwise indistinguishable at the output. It lives in test fixtures, never in `registry/`.
- **Paired eval cases** — one utterance that **omits** `unit`/`purchasing_group` (assert derivation
  happened, the producer node exists, the data edge exists, `capability_derived > 0`), and one that
  **supplies** `unit` (assert `literal` wins, no producer is pulled, no extra READ). Without the second,
  "user wins" is indistinguishable from "we never derived anything".
- **Mixed case** — supplies `unit`, omits `purchasing_group`. The only path that exercises Defect 1.
  It must be a test, not a hope.
- **Field-list lock** — the four known restatement copies of the Fact payload field list
  (`registry/capabilities.yaml:316`, `registry/executor-bindings.yaml:26-32`,
  `frontend/src/runtime/projection/fact-builder.ts:130-140`,
  `frontend/src/runtime/plan-evidence/event-projector.ts:69`) must be conformance-tested against the
  catalog. Copies #1 and #2 have already drifted (`purchaseOrderUnit` vs `PurchaseOrderQuantityUnit`).

---

## 8. Coupling to defect D4, and what stays untouched

Approval, subject hash, and anti-replay semantics are **unchanged** this round. Defect D4 — extending the
approval subject to a joint hash of *WRITE parameters + upstream Fact `asOf` + snapshot id* — is a
separate batch.

But the upstream nodes introduced here become **inputs to D4**, so:

- every Fact retains its `asOf` and `snapshotId` fields;
- the coupling point is flagged explicitly in the change report;
- **a parameter being derived from upstream is never a reason to skip or simplify Human Approval.** The
  approval card gains disclosure (derived vs user-entered), never a shortcut.

Also unchanged: the fail-closed executors `CDS_ADT` / `REST_JSON` / `SQL_READ` stay refusing; execution
authority stays in the Java Gateway; nothing in `agent/` performs a synchronous data fetch — the closure
of §4 only *authors* a node, and the read happens later, in order, in the Composition Runtime's
PlanExecutor. No new pip or npm dependency is introduced; no graph database and no OWL reasoning runtime.

---

## 9. Open items carried into Build

- The exact lock mechanism for the two TypeScript restatement copies (conformance test vs generated
  file) depends on whether the frontend has an existing YAML→TS codegen step. To be settled at the start
  of T1 by inspection, not by assumption.
- The eval harness's conversation-sequence case shape for the paired cases in §7, likewise settled by
  inspection of `evals/` and `scripts/verify-agent-callplan-evidence.sh`.

Neither affects the architecture above; both are mechanical and local to their task.

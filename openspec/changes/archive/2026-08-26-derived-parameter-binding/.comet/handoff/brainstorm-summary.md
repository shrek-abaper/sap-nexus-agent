# Brainstorm Summary — derived-parameter-binding

Status: **in progress** (design phase). Items marked `pending` are not yet confirmed by the user.

---

## Confirmed Technical Approach

### Finding that reframes the change (evidence-backed)

The brief states the blocker is "FactType is an opaque label with no field list". That is true but not
the innermost blocker. `schemas/capability.schema.json` already defines a `capabilityOutput` binding
source requiring `factType` + `field`, described as *"reserved for future dependency edges; accepted
and validated, execution unimplemented"*. `extraction/engine.py:24` excludes it from
`_WIRED_SOURCE_KINDS` and `:129-136` names its landing point *"dependency-edge binding (D2)"*.

The mechanical reason `provenance.capability_derived` is always 0 is one layer lower:

| Evidence | Fact |
| --- | --- |
| `schemas/capability.schema.json` `$defs/ioField/allOf[1]` | `bindingKind: identifier` **forbids** `satisfiableByFactType` |
| `$defs/ioField/allOf[0]` | `bindingKind: fact` **requires** `satisfiableByFactType` |
| `plan_compiler_v2.py:253` | only `bindingKind == "fact"` + `required` inputs get a `factField` source and a data edge |
| `plan_compiler_v2.py:366-395` | only `bindingKind == "identifier"` inputs get `goalConstraint` / `literal` sources |
| `registry/capabilities.yaml` | all 15 inputs are `bindingKind: identifier`; `satisfiableByFactType` appears 0 times; `binding.sources[]` appears 0 times |

`bindingKind` is an exclusive switch: an `identifier` value can only come from the user, a `fact` value
can only come from upstream. No input can be both. That conditional is the actual blocker.

### Ruling 1 — relax the schema conditional (confirmed)

`bindingKind` returns to meaning *what the parameter is* (a scalar identifier); `satisfiableByFactType`
means *where it may also come from*. An `identifier` input MAY declare `satisfiableByFactType`.

Surface: `capability.schema.json` `$defs/ioField/allOf[1]`, `scripts/validate_registry_contract.py:491-495`,
`agent/sap_nexus_agent/semantic_planning/validation.py:1426-1433`, and the `plan_compiler_v2.py:253` gate.

Rejected: flipping the two inputs to `bindingKind: fact` (a required WRITE input would get **zero**
parameter sources whenever no upstream node is planned — `:253` enters the second pass, `:258-259`
finds no producer and `continue`s, and `:366/:381` skip it for not being `identifier`);
adding a third `bindingKind` (touches every `identifier` comparison — `plan_compiler_v2.py:97/112/367/381`,
`plan_compiler.py:213`, `handoff.py:84`, `graph.py:68`, `validation.py:409/424/439` — and derivedness is
a property of an edge's provenance, not a kind of parameter).

### Ruling 2 — user-supplied beats upstream-derived (confirmed; realized at the compiler layer)

When the user explicitly supplies a value AND an upstream producer could supply it, the **user's value
wins**. Master data does not silently overwrite what a human typed on a WRITE path.

### Ruling 4 — `satisfiableByFactType` is the only declaration; no `capabilityOutput` source (confirmed)

Derivation is computed at runtime by semantic-type equality — which is what
`plan_compiler_v2.py:253-286` already does. The registry declares only `satisfiableByFactType`. Nothing
restates the derived field, so field-level drift is structurally impossible and no draft→publish flow is
needed. Accepted cost: reading `capabilities.yaml` does not reveal that `unit` will be derived; the
deriver must be run to see it.

Rejected: restating `capabilityOutput.factType` + `field` in the registry with a validator asserting
declaration == derivation (self-describing registry, but the same fact in two places); declaring
`factType` only and inferring `field` (needs a `$defs/bindingSource` `allOf[1]` change and contradicts
the published description).

### Rulings 2 + 4 interact to eliminate the spec reversal originally priced in

The `binding.sources[]` priority contract governs source resolution **inside the extraction layer**.
Under ruling 4 this change declares no `capabilityOutput` source, so that contract is never exercised
and does not need reversing. Ruling 2's semantics live in a different layer and a different mechanism:
the compiler's second pass must skip authoring a `factField` source for a parameter that already carries
a `literal` or `goalConstraint` binding.

Therefore the following costs quoted earlier are **void**, and are recorded as void rather than quietly
dropped:

| Previously priced | Actual |
| --- | --- |
| reverse published requirement `Input binding sources and priority` (`specs/declarative-intent-extraction/spec.md:234-254`) | **not needed** — governs a different layer |
| reorder `extraction/engine.py:24` `_SOURCE_PRIORITY` | **not needed** |
| edit the priority sentence in `capability.schema.json:430` and `extraction-declaration.schema.json:238` | **not needed** |
| reverse `test_binding_sources.py:120-128` `test_capability_output_beats_user_utterance_when_wired` | **not needed** — stays green, untouched |

Replaced by one **additive** requirement in the semantic-planning capability: a parameter already bound
from a user-supplied value SHALL NOT be re-bound from an upstream Fact. Both layers state their own
precedence; no published contract is overturned.

`capabilityOutput` therefore remains deliberately unwired, and its existing xfail placeholder test keeps
its role as the fixed landing point.

### T0′ shrinks to one edit per input

`registry_loader` already normalizes the deprecated `extraction:` alias into a single `userUtterance`
source (pinned by `test_extraction_alias_normalizes_to_single_user_utterance_source`), so migrating the
two inputs to an explicit `binding.sources[]` block buys no behaviour. T0′ reduces to **adding
`satisfiableByFactType` to `unit` and `purchasing_group`**. The alias migration is orthogonal cleanup and
is out of this change's scope — flagged, not performed.

### Ruling 3 — the planner auto-pulls the producer (confirmed)

Trigger: a consumer's **required** input is **not bound by the user** AND declares
`satisfiableByFactType`. Then the planner pulls the producer capability in per the derived-edge view,
authors the data edge, and does **not** elicit that parameter.

- Safety constraint: only a `READ` capability with `sideEffect: none` may be auto-pulled. **This reduces
  to a single predicate — `kind: Function` — backed by a schema invariant, not by reviewer discipline.**
  `capability.schema.json` `$defs/capability/allOf[0]` requires `kind: Function` ⇒ `sideEffect: none` +
  `requiresApproval: false` + `approvalPolicy: not_required`; `allOf[1]` requires `kind: Action` ⇒
  `sideEffect: sap_write` + `requiresApproval: true` + `approvalPolicy: human_required`. So an auto-pull
  restricted to `kind: Function` **structurally cannot** drag in a WRITE and therefore cannot bypass
  Human Approval. Invariant 5 is protected by the schema, not by policy. The 4th capability must be
  declared `kind: Function`.
- Disclosure: the narration must state that an extra read happened ("为获取基本单位与采购组，额外读取了物料主数据").
- Approval card must mark a derived value as derived rather than user-entered (this is how invariant 5
  is satisfied — by disclosure, not by precedence).

Rejected: requiring user confirmation before the extra READ (raises a `sideEffect: none` read to
WRITE-level ceremony and adds a round trip to every PR); relying on the user's utterance to recall the
producer (then the demo case never derives anything and the PlanGraph data edge stays empty).

**Ruling 3 has an existing structural home — the node set is not built from `matched_intents`.**
`plan_compiler_v2.py:213-233` builds one node per entry in `goal.desired_fact_types`, resolving the
producer through `_index_producers_by_fact_type(cards)`. So auto-pull is implemented as a **closure over
`desired_fact_types`**: when a consumer's required, user-unbound input declares
`satisfiableByFactType: F` and `F` is not already desired, add `F`. The node-creation loop then produces
the producer node with **zero changes**, and `producers_by_fact` already resolves it.

Placing the closure in `build_goal_spec` (rather than inside `_build_plan_graph_v2`) keeps the GoalSpec
self-describing: the PlanGraph's own goal records why the extra node exists, which is what makes the
extra READ auditable rather than a silent planner side effect. The closure admits a producer only when
its capability is `kind: Function`.

**Latent defect of the same family as F1**, surfaced by this reading: `plan_compiler_v2.py:217` takes
`producers[0]` — when two capabilities produce the same Fact Type it silently picks one, exactly as
`_first_fact_field` silently picks the first matching output. It is latent today (each Fact Type has one
producer) but auto-pull makes it load-bearing, so it belongs in the ambiguity diagnostics of Decision 4
rather than being left to chance.

### How the three rulings compose

The trigger conditions are complementary, so there is no conflict and no wasted call:

- Input already bound by the user → no pull, no extra READ, `literal` wins (ruling 2).
- Input not bound → pull, no elicitation, `factField` wins (ruling 3).

Because precedence is applied **at authoring time**, exactly one source is authored per parameter, so
the "two parameterBindings for one parameterName" hazard is mechanically dissolved rather than needing
a dedup rule.

### Consequence: Defect 1 is on the critical path, not incidental

If the user supplies `unit` but not `purchasing_group`, one (producer → consumer) pair yields **two**
`factField` bindings that must share **one** data edge. `validation.py:483-496` tolerates N sources per
edge, but `plan_compiler_v2.py:277` appends one edge per binding and then duplicates are rejected.
Defect 1 must therefore be fixed in this change — it is a prerequisite of T3's headline edge, not a
pre-existing defect to be counted and deferred.

### T3's headline edge — concrete shape

Producer: the 4th capability, producing `sapnexus:MaterialInfoFact` with fields
`materialNumber` / `plant` / `baseUnit` / `purchasingGroup` — four fields, **zero new semantic types**
(`sapnexus:MaterialNumber`, `sapnexus:Plant`, `sapnexus:UnitOfMeasure`, `sapnexus:PurchasingGroup` all
already appear in `registry/capabilities.yaml`).

Consumers: `MM.PR.CreateDraft` inputs `unit` (`registry/capabilities.yaml:415-429`,
`sapnexus:UnitOfMeasure`) and `purchasing_group` (`:442-456`, `sapnexus:PurchasingGroup`). Both
currently carry the deprecated `extraction:` alias with a `semanticType` matcher ref, which is what
T0′ migrates to `binding.sources[]`.

`ontology/fact-types.yaml` today has no `fields:` key on any of its 3 entries, and
`ontology/capability-relations.yaml` is literally `relations: []`.

Also confirmed: `_first_fact_field` at `plan_compiler_v2.py:265` selects the producer output by
"first whose factTypeRef matches", which is F1 — the defect Decision 2 replaces with semantic-type
equality.

---

## Key Trade-offs and Risks

- No published requirement is overturned by this change (see rulings 2 + 4). The largest remaining
  governance cost is that auto-pulling a producer means the system executes an SAP READ the user did not
  explicitly request. Mitigated structurally by the `kind: Function` restriction and behaviourally by
  mandatory narration disclosure.
- Reading `registry/capabilities.yaml` no longer reveals that a parameter will be derived (accepted cost
  of ruling 4). The reviewable derived view is the compensating control, which is why its positive
  control (Decision 13) is load-bearing rather than decorative.
- **Resolved (was pending): relaxing `allOf[1]` weakens no existing guarantee.** Every check that
  couples a source kind to `bindingKind` retains its semantic-type / factType equality assertion; only
  the `bindingKind` coupling is dropped. Verified blast radius:

  | Site | Change | Why |
  | --- | --- | --- |
  | `capability.schema.json` `$defs/ioField/allOf[1]` | drop the `not.required` on `satisfiableByFactType`; `allOf[0]` unchanged | ruling 1 |
  | `scripts/validate_registry_contract.py:491-495` | drop the identifier prohibition | ruling 1 |
  | `semantic_planning/validation.py:438-441` | `factField` validity keyed on `satisfiableByFactType` equality, not on `bindingKind == "fact"` | otherwise an `identifier` input receiving a `factField` source is rejected as `PARAMETER_SOURCE_MISSING` |
  | `semantic_planning/validation.py:1426-1433` | same, at registry-contract level | ruling 1 |
  | `semantic_planning/graph.py:68` | build `consumesFactType` on `satisfiableByFactType` presence | **ruling 3's命门**: the planner's auto-pull walks this edge; left as `bindingKind == "fact"` the graph never records that `MM.PR.CreateDraft` consumes `MaterialInfoFact` |
  | `plan_compiler_v2.py:253` | second-pass gate keyed on `satisfiableByFactType` presence | ruling 1 |

  Deliberately **untouched** and still correct: `handoff.py:84` and `plan_compiler_v2.py:97/112/367/381`
  and `plan_compiler.py:213` (the two inputs stay `identifier`, so a user-supplied value still becomes a
  GoalConstraint / literal — which is exactly what ruling 2 requires), and `validation.py:409/424`.

  None of the six sites is per-capability, so invariant 6 (adding the 4th capability changes 0 lines of
  Python) is preserved.

## Testing Strategy

`pending` — to be written after the approach sections are approved. Known fixed points so far:

- The positive control fixture (design Decision 13) must be green even when the real derived view is
  empty; it lives in test fixtures, never in `registry/`.
- An eval case must **omit** `unit` and `purchasing_group` from the utterance. Under ruling 2 a
  user-supplied value wins, so an utterance that mentions them yields `literal` bindings and
  `provenance.capability_derived` stays 0.
- A companion case that **does** supply `unit` must assert the opposite: `literal` wins, no producer is
  auto-pulled (ruling 3's trigger is "not bound by the user"), and no extra READ is executed. Without
  this pair, "user wins" and "we never derived anything" are indistinguishable.
- The mixed case — user supplies `unit` but not `purchasing_group` — is the one that exercises Defect 1
  (two `factField` bindings sharing one data edge) and must be a test, not a hope.

## Spec Patches

- **New, additive**: a requirement in the semantic-planning capability stating the compiler-layer
  precedence — a parameter already bound from a user-supplied value SHALL NOT be re-bound from an
  upstream Fact (ruling 2, realized per rulings 2 + 4).
- **New, additive**: a requirement that the planner MAY close `desired_fact_types` over unbound
  fact-satisfiable required inputs, restricted to `kind: Function` producers, and MUST disclose the
  resulting extra read in the narration (ruling 3).
- **Amend in-change only** (`design.md` / `tasks.md`, not published specs): Decision 7's priority framing,
  Decision 2's scoping, Decision 5's Defect 1 promotion to critical path, Decision 12's T0′ reduction.
- No MODIFIED requirement against `specs/declarative-intent-extraction/` is required. This was expected
  before ruling 4 and is now explicitly not needed.

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
ontology vocabulary `sapnexus:*`. Following the brief literally would mean matching
`Unit` against `sapnexus:UnitOfMeasure` under strict equality, which never matches. The derived
view would be permanently empty, and because "an empty view is a valid result" is a legitimate
outcome of this design, the failure would masquerade as success.

Decision, as ruled:

- A FactType field's `semanticType` uses the `sapnexus:*` ontology vocabulary — the same
  vocabulary as capability input/output `semanticType` and Fact Type `keyedBy`. Its closed set is
  the set of `semanticType` values used by capability inputs and outputs in the same snapshot, so
  a field's semantic type is valid exactly when it is a type some capability actually speaks.
- `registry/semantic-types.yaml` keeps its real job — the extraction matcher catalog — and is
  **not** the semantic-type authority. This change records that job in a header comment and does
  not rename the file; renaming would touch every `matchers: [{kind: semanticType, ref: …}]`
  reference site for no behavioural gain.
- A **one-way** mapping links the two vocabularies: each matcher entry declares
  `extracts: sapnexus:<Type>`. One ontology type may have several extractors, or none — a value
  obtainable only from the system legitimately has no extractor, so `sapnexus:AvailableQuantity`
  having no matcher entry is the correct state and is not to be back-filled. One matcher entry
  MUST NOT declare that it extracts two different ontology types.
- Two validator rules are added: every `sapnexus:*` reference must exist in the ontology
  vocabulary, and every `extracts:` target must exist in the ontology vocabulary.

- *Alternative A — publish a fifth governed artifact for ontology semantic types.* Rejected:
  `semantic-planning-foundation/spec.md:36` pins the snapshot to exactly four governed sources;
  adding a fifth is a larger contract change than this batch's scope, and the closed set is
  already derivable from the registry.
- *Alternative B — extend `registry/semantic-types.yaml` with matcher-less ontology entries.*
  Rejected: its schema exists to describe matchers, and conflating the extraction namespace with
  the ontology namespace would make `{kind: semanticType, ref: …}` resolution ambiguous. The
  `extracts:` mapping gives the cross-vocabulary link without merging the namespaces.
- *Consequence:* no new semantic type is needed by this change. The new FactType's fields reuse
  `sapnexus:MaterialNumber`, `sapnexus:Plant`, `sapnexus:UnitOfMeasure`, and
  `sapnexus:PurchasingGroup`, all already spoken by existing capability inputs.

### Decision 2 — The consuming input's `satisfiableByFactType` scopes the candidate set; field selection inside that scope is by semantic-type equality

This is the fix for F1 and it also prevents a spurious ambiguity that would otherwise kill the
change. A consuming input already declares exactly one `satisfiableByFactType`, which is the sole
authored source of `consumesFactType` (`semantic-planning-foundation/spec.md:7`). The deriver
therefore considers only the fields of that one FactType, and selects the field whose
`semanticType` equals the input's `semanticType`.

Without this scoping, `MM.PR.CreateDraft`'s `unit` input would have two global candidates once
`InventoryAvailabilityFact` declares its payload `unit` field — the derived edge would be reported
`ambiguous`, the deriver would refuse to select, and T3's headline edge would never be authored.
Scoping by the consumer's own declaration is not a workaround for that: it is the existing
architectural rule, applied one level deeper than before.

Ambiguity remains reachable and testable under this scoping: two fields of the same
`semanticType` inside one FactType, or two active capabilities producing the same FactType.

- *Alternative — global candidate search across all FactTypes.* Rejected: it contradicts
  `satisfiableByFactType` being authoritative, and it converts every added capability into a
  potential ambiguity source for unrelated consumers.

### Decision 3 — A FactType field list models the fact payload, decomposed only where a restatement or a consumer exists

The field list describes the normalized fact payload (Decision context: `value` / `unit` are
payload fields with no output counterpart), because only that model can lock the four drifted
copies, which are copies of payload names.

Depth rule: decompose nested structure down to the level at which either (a) some artifact
restates those names and must be conformance-locked, or (b) some capability input could bind to
them. Below that level, the structure stays one field with `cardinality: many` and an opaque
row-level semantic type.

Applied:

- `PurchaseOrderSupplyFact` — the six item-level names in
  `registry/capabilities.yaml:316`'s `itemFields` are restated in three other places and have
  already drifted, so they become six fields with `cardinality: many`. `narrative.fieldMapping.itemFields`
  is then derived as the ordered list of `many` fields. The array container name `purchaseOrders`
  stays what it is today — a capability *output* name — and is not a FactType field.
- `InventoryAvailabilityFact` — `mrpElementLines` stays a single `cardinality: many` field of an
  opaque row type. No artifact restates MRP row field names and no input can bind to them, so
  decomposing them would add surface with no conformance value. This also yields the real
  `needsReduction` test case the proposal relies on, using existing data.

*Trade-off:* the two FactTypes are decomposed to different depths. The depth rule, not the
FactType, is what is consistent; the cost of the rule is that a future consumer of MRP row fields
must decompose that field at that time.

### Decision 4 — Diagnostics are scoped exactly as matching is

`needsReduction` is emitted when the semantic-type-equal field inside the consumer's declared
FactType has `cardinality: many` and the consuming input is scalar. `ambiguous` is emitted when
that scope contains more than one semantic-type-equal field, or when more than one active
capability produces the declared FactType. A diagnostic never degrades into a match, and a
diagnosed input is reported as a plan gap rather than bound.

### Decision 5 — Two separately reported Python line counts, with each defect named

Invariant 6 ("registering a capability requires zero Python changes") is measured by figure (a):
lines of Python required to *register* `MM.Material.GetInfo`. Figure (b) reports lines of Python
required to fix pre-existing defects that the registration exposes. Neither figure may absorb the
other, and every line in (b) is attributed to a named defect. The two defects known before Build
starts:

1. **Duplicate data edge (F2).** `validation.py:483-496` tolerates N `factField` sources sharing
   one `data` edge, but `plan_compiler_v2.py:277` appends one edge per binding, so the first
   producer feeding two inputs of one consumer emits two same-key edges and `:533-540` rejects
   them. **This defect is on the critical path, not a pre-existing item to be tallied and deferred.**
   Under Decision 15's precedence rule the mixed case — the user supplies `unit` and omits
   `purchasing_group` — is a first-class supported path, and it is exactly the two-binding shape that
   trips the defect. T3's headline edge cannot be authored until it is fixed. Its lines are still
   reported separately in figure (b), attributed to this defect.
2. **Inventory-shaped narration guard (F3, Decision 6).**
3. **Silent first-producer selection.** `plan_compiler_v2.py:217` does `card = producers[0]`,
   picking one capability when several produce the same FactType — the same failure family as F1's
   `_first_fact_field` (`:265`), which picks the first output whose `factTypeRef` matches. Latent
   today because each FactType has exactly one producer, but Decision 16's auto-pull makes the
   producer lookup load-bearing, so list order must not decide it. It is folded into Decision 4's
   `ambiguous` diagnostic rather than left to chance.

Reporting `0` for (a) while silently spending Python on (b) would be a false claim; reporting the
sum as a single number would be an equally false claim in the other direction. Both figures are
produced by `git diff --stat` partitioned by file, with the partition shown.

### Decision 6 — The new capability declares a full `narrative` block; the single-value guard becomes fieldMapping-driven

Per Context, omitting `narrative` defaults to `single-value` and still hits the guard, and
`visibility` cannot exclude the capability from narration without Python changes. So:

- `MM.Material.GetInfo` declares `narrative` with `factShape: single-value`, a `promptTemplate` /
  `fallbackTemplate` id that no Python dictionary knows (resolving to `_GENERIC_GUIDANCE` at
  `narrator.py:45,51`), a `fieldMapping` referencing only its own fields, and
  `detailFormatter: none`. This is registration-only — figure (a) stays 0 for it.
- `narrate_single_value`'s required-field guard changes from the hardcoded
  `material` / `plant` / `value` / `unit` quartet to the fields the declared `fieldMapping`
  actually references, and the value label stops being hardcoded to an inventory phrase. This is
  the pre-existing generality gap that `agent-callplan-evidence/spec.md:238-243` already promised
  was closed; T3 is its first real test. It counts in figure (b), defect 2.

*Alternative rejected — reuse `factShape: single-value` with the inventory labels by mapping
`value` to the purchasing group.* That produces narration that calls a purchasing group an
available stock quantity. Misleading narration is a worse outcome than a counted Python fix.

### Decision 7 — Three source kinds, three priority tiers; `sessionContext` is not introduced

The brief's four-tier priority `capabilityOutput > sessionContext > userUtterance > default` has
no home: the schema enum has exactly three kinds and sticky cross-turn continuation is a separate
requirement (`declarative-intent-extraction/spec.md:149`) implemented through
`ConversationContext`, not through `binding.sources[]`. This change introduces no `sessionContext`
kind and leaves sticky continuation on its existing mechanism.

**Scope correction.** The three-tier priority at `spec.md:240-241` governs source resolution *inside
the extraction layer*, and this change declares no `capabilityOutput` source (Decision 15), so that
contract is never exercised and is left exactly as published. The precedence question this change
actually answers is a different one — user-supplied value versus upstream-derived value — and it is
answered one layer up, in the compiler. See Decision 15. Task 1.4 keeps a schema-enum assertion here
purely as a no-regression guard.

### Decision 8 — The relation catalog keeps `dependsOn` + `precondition`, plus an `origin` field

**[CONFIRMED by the user — additive only, no replacement]**

`semantic-planning-foundation/spec.md:7` says the relation catalog authors only `dependsOn` and
`precondition`. The brief said it may carry only `precondition` / `authority` / `mutex` /
`compensation`. Neither list contains the other: the brief drops `dependsOn`, which is the sole
input to the dependency-edge authoring pass at `plan_compiler_v2.py:299-312` and cannot be removed
without deleting that behaviour, and it adds three relation types that do not exist in the schema
today. Decision, as ruled:

- The relation-type set stays `dependsOn` + `precondition`. `plan_compiler_v2.py:299-312` is not
  touched, and the deriver emits its result **in `dependsOn` shape** so the existing compiler
  consumes it directly. No new relation-type name is invented for "derived" — derivedness is a
  property of the edge's provenance, not a different kind of relation.
- Every relation edge carries `origin: derived | manual`. `origin: manual` MUST carry a
  `justification`, so a hand-authored edge has to state why it cannot be computed.
- The validator rejects any `origin: manual` edge that the deriver can compute. This replaces the
  weaker "a derivable data dependency SHALL NOT be authored" phrasing with a mechanical check:
  the prohibition is enforced by running the deriver, not by reviewer discipline.
- `authority` / `mutex` / `compensation` are **not** added in this change. They have no schema, no
  consumer, and no test; adding them now would create three empty fields. `tasks.md` contains no
  item for them.

### Decision 9 — Task order is T0′ → T1 → T2 → T5-skeleton → T3 → T4 → T5-full

`capability.schema.json`'s `evalLinkage` requires `caseIds` with `minItems: 1` and
`registry-ontology-contract/spec.md:105-107` fails validation on missing eval linkage, so the new
capability cannot pass schema validation before its eval case ids exist. The eval case skeleton
therefore lands before registration, inverting the brief's listing order (F7). The full sequence
assertions land after T3, when there is something to assert against.

### Decision 10 — Snapshot churn is handled per fixture with a stated semantic reason

`ontology/fact-types.yaml` is a governed source, so adding field lists changes `snapshotId`
(`semantic-planning-foundation/spec.md:42-44`). This is now confirmed mechanically rather than
inferred: `semantic_planning/snapshot.py:38,45` digest the **whole document** (`_sha256_id(document)`,
`_sha256_id(dict(documents))`) with no filtered key subset, so a new `fields:` key necessarily flows
into both the fact-types per-source digest and the composite `snapshot_id`. There is no way to add the
field list without the churn.

Verified pin inventory (corrected — an earlier draft of this decision named two fixtures):

- `evals/matcher_cases.yaml` pins the real digest `sha256:e6d329bc…e599ed95` in **14** places and is
  the only file that must be recomputed.
- `agent/tests/fixtures/semantic_planning/plan-material-supply.yaml:5` pins
  `sha256:0000…0000` — an all-zeros placeholder, not a real digest — and needs no change.
- `evals/recommendation_decision_cases.json:74` uses the symbolic `"snapshot-2"` and is unaffected.

The recomputation is accompanied by the semantic change that caused it; refreshing a snapshot without
explaining the semantic change is forbidden (invariant 9). The `sha256:` values in `test_approval.py` /
`test_orchestrator.py` are approval subject hashes and are not touched — invariant 5. Because `fields`
is required, the catalog `version` bumps to `2` and the schema's `"version": {"const": 1}` changes with
it; `snapshot.py`'s `document_version` reads that value directly, so the bump must be verified not to
break snapshot construction. Two assertion sites stop hardcoding the capability count
and instead assert against the Registry content: `agent/tests/test_registry_loader.py:23` and the
tuples at `agent/tests/test_recall.py:64,74,84,95,117`. Changing them from a literal `3` to a
Registry-derived expectation is a semantic correction, not assertion loosening; each still fails
if the Registry set is wrong.

### Decision 11 — `sapnexus:MaterialInfoFact` is added with no new semantic type

Fields: `material` (`sapnexus:MaterialNumber`, one), `plant` (`sapnexus:Plant`, one),
`baseUnitOfMeasure` (`sapnexus:UnitOfMeasure`, one), `purchasingGroup`
(`sapnexus:PurchasingGroup`, one), plus the `asOf` / snapshot provenance every fact carries
(invariant 5). Both keys are required because the two values live at different SAP levels —
`MARA-MEINS` is client-level and `MARC-EKGRP` is the material plant view — so a material-only call
cannot yield the purchasing group.

`MM.Material.GetInfo` MUST be declared `kind: Function`. This is not a stylistic choice: it is the
precondition that makes Decision 16's auto-pull safe, because `capability.schema.json`
`$defs/capability/allOf[0]` binds `Function` ⇒ `sideEffect: none` + `requiresApproval: false` +
`approvalPolicy: not_required`.

### Decision 12 — T0′ reduces to two `satisfiableByFactType` declarations; no alias migration happens

**[Reduced from the original scope after verification]**

T0′ was scoped as migrating the two `MM.PR.CreateDraft` inputs from the deprecated `extraction:`
alias to an explicit `binding.sources[]` block. That migration is **dropped**, because it buys no
behaviour: `registry_loader` already normalizes the alias into a single `userUtterance` source, pinned
by `test_extraction_alias_normalizes_to_single_user_utterance_source`. The parsed binding is identical
before and after, so the edit would have been diff without effect.

T0′ is therefore: add `satisfiableByFactType: sapnexus:MaterialInfoFact` to `unit`
(`registry/capabilities.yaml:415`) and `purchasing_group` (`:442`), both staying
`bindingKind: identifier` per Decision 14.

All 15 deprecated `extraction:` inputs — including these two — keep emitting their migration warning.
The alias migration is recorded as orthogonal cleanup and is not performed here; doing it would
inflate the diff that must prove figure (a).

### Decision 14 — `bindingKind` is decoupled from source eligibility

**[RULED by the user: relax the conditional]**

The innermost cause of `provenance.capability_derived ≡ 0` sits one layer below the brief's
diagnosis. The brief attributes it to FactType being an opaque label with no field list; that is the
*second* blocker. The first is that `bindingKind` is an **exclusive switch**:
`capability.schema.json` `$defs/ioField/allOf[1]` forbids an `identifier` input from declaring
`satisfiableByFactType`, `allOf[0]` requires it for a `fact` input, `plan_compiler_v2.py:253` gives a
`factField` source only to a `fact` input, and `:366-395` gives a `goalConstraint` / `literal` source
only to an `identifier` input. With all 15 registry inputs `identifier` and `satisfiableByFactType`
used zero times, no input can be both, so unlocking the field list alone would not have produced a
single derived edge.

Decision, as ruled: `bindingKind` means **what the parameter is** (a scalar identifier);
`satisfiableByFactType` means **where it may also come from**. An `identifier` input MAY declare
`satisfiableByFactType`. Six sites change, each dropping only its `bindingKind` test while keeping its
factType / semantic-type equality assertion, so no check becomes weaker:

| Site | Change |
| --- | --- |
| `schemas/capability.schema.json` `$defs/ioField/allOf[1]` | drop the `not.required`; `allOf[0]` intact |
| `scripts/validate_registry_contract.py:491-495` | drop the identifier prohibition |
| `semantic_planning/validation.py:438-441` | key `factField` validity on `satisfiableByFactType` equality |
| `semantic_planning/validation.py:1426-1433` | same, at registry-contract level |
| `semantic_planning/graph.py:68` | build `consumesFactType` on `satisfiableByFactType` presence |
| `planner/plan_compiler_v2.py:253` | key the second-pass gate on `satisfiableByFactType` presence |

`graph.py:68` is load-bearing rather than cosmetic: Decision 16's closure walks the
`consumesFactType` edge, so left keyed on `bindingKind == "fact"` the semantic graph would never
record that `MM.PR.CreateDraft` consumes `MaterialInfoFact` and the closure would find nothing.

Deliberately untouched and still correct: `planner/handoff.py:84`,
`plan_compiler_v2.py:97/112/367/381`, `planner/plan_compiler.py:213`, `validation.py:409/424`. The two
target inputs stay `identifier`, so a user-supplied value still becomes a GoalConstraint or literal —
which is what Decision 15 requires. None of the six sites is per-capability, so invariant 6 holds.

- *Alternative A — flip the two inputs to `bindingKind: fact`.* Rejected: a required WRITE input
  would get **zero** parameter sources whenever no upstream node is planned — `:253` enters the second
  pass, `:258-259` finds no producer and `continue`s, and `:366`/`:381` skip it for not being
  `identifier`. Cheapest in code, worst in behaviour. This is why the Migration Plan no longer speaks
  of flipping these inputs.
- *Alternative B — add a third `bindingKind`.* Rejected: it touches every `identifier` comparison
  listed above as untouched, and derivedness is a property of an edge's provenance, not a kind of
  parameter.

### Decision 15 — User-supplied beats upstream-derived, enforced at authoring time; `satisfiableByFactType` is the only declaration

**[RULED by the user on both forks, overriding the recommendation on each]**

When the user explicitly supplies a value and an upstream producer could also supply it, the **user's
value wins**. This is realized in `plan_compiler_v2._build_plan_graph_v2`'s second pass — do not author
a `factField` source for a parameter that already carries a `literal` or `goalConstraint` binding — and
**not** by reordering `extraction/engine.py:24`'s `_SOURCE_PRIORITY`.

Because precedence applies at authoring time, exactly one source is authored per parameter, so the
"two `parameterBindings` for one `parameterName`" hazard is dissolved mechanically rather than by a
dedup rule. The trigger conditions of this decision and Decision 16 are complementary, so there is no
conflict and no wasted call: an input already bound by the user produces no closure entry, no producer
node, and no extra READ; an unbound input produces the closure entry, the producer node, and a
`factField` binding.

**The registry declares `satisfiableByFactType` and nothing else.** No `capabilityOutput` source is
added. Derivation is computed at runtime by semantic-type equality, which is what
`plan_compiler_v2.py:253-286` already does. Since nothing restates the derived field, field-level drift
is structurally impossible and no draft→publish flow is needed for it. Accepted cost: reading
`registry/capabilities.yaml` does not reveal that `unit` will be derived — the reviewable derived view
is the compensating control, which is why Decision 13's positive control is load-bearing rather than
decorative.

**No published requirement is overturned.** The `binding.sources[]` priority contract governs the
extraction layer and is not exercised here. The following were priced into an earlier draft and are
recorded as void rather than quietly dropped: a MODIFIED `Input binding sources and priority`
requirement (`openspec/specs/declarative-intent-extraction/spec.md:234-254`); reordering
`_SOURCE_PRIORITY`; the priority sentences in `capability.schema.json:430` and
`extraction-declaration.schema.json:238`; and reversing
`agent/tests/test_binding_sources.py:112-166`'s `test_capability_output_beats_user_utterance_when_wired`,
which stays green and untouched. They are replaced by one **additive** requirement: a parameter already
bound from a user-supplied value SHALL NOT be re-bound from an upstream Fact. Both layers state their
own precedence and do not contradict. `capabilityOutput` remains deliberately unwired, and its existing
xfail placeholder keeps its role as the fixed landing point.

### Decision 16 — Producer auto-pull is a closure over `desired_fact_types`, restricted to `kind: Function`

**[RULED by the user: the planner pulls the producer in automatically]**

The plan's node set is **not** built from `matched_intents`. `plan_compiler_v2.py:213-233` builds one
node per entry in `goal.desired_fact_types`, resolving each producer through
`_index_producers_by_fact_type(cards)`. Auto-pull therefore needs no new node-construction code — it is
a **closure**: when a consumer's `required` input is not bound by the user and declares
`satisfiableByFactType: F`, and `F` is not already desired, add `F` to `desired_fact_types`. The
existing loop then materializes the producer node. Zero changes to `:213-233`.

The closure lives in `build_goal_spec`, not inside `_build_plan_graph_v2`, so the PlanGraph's own
GoalSpec records **why** the extra node exists. That is what makes the extra read auditable instead of a
silent planner side effect.

**The safety constraint is a schema invariant, not a policy.** Only a producer whose capability is
`kind: Function` may be pulled in. Because `$defs/capability/allOf[0]` binds `Function` ⇒
`sideEffect: none` + `requiresApproval: false` + `approvalPolicy: not_required`, and `allOf[1]` binds
`Action` ⇒ `sap_write` + `requiresApproval: true` + `approvalPolicy: human_required`, an auto-pull so
restricted **structurally cannot** drag in a WRITE or bypass Human Approval. Invariant 5 is protected by
the schema rather than by reviewer discipline.

Disclosure is mandatory and is what pays for the extra read: the narration states that an extra read
occurred, and the approval card marks a derived value as derived rather than user-entered. A value being
derived is never a reason to skip or simplify Human Approval.

- *Alternative A — confirm the extra READ with the user first.* Rejected: it raises a
  `sideEffect: none` read to WRITE-level ceremony and adds a round trip to every PR.
- *Alternative B — pull only when the utterance itself recalled the producer.* Rejected: the demo case
  would then derive nothing and the data edge would stay empty, so the change would pass its own
  acceptance while delivering nothing.

### Decision 13 — A positive control fixture proves the deriver can match at all

**[Added by the user as a gap in the original brief]**

"The derived view is empty because no real capability pair matches yet" and "the deriver is
structurally broken and can never match anything" are indistinguishable at the output. Under the
brief's original exit condition, a completely dead deriver would have passed acceptance.

Decision: T2 ships a positive control fixture — two fabricated capabilities whose fields are
constructed so that exactly one edge must be derived — and asserts the deriver produces that edge.
The fixture lives in test fixtures, not in `registry/`, so it never enters the governed source set
or the execution boundary.

T2's exit condition changes accordingly: **empty on the real capabilities is acceptable, but the
positive control must be green.** An empty real view combined with a red positive control is a
deriver defect, not a legitimate empty result.

The same reasoning applies to the diagnostics: `needsReduction` and `ambiguous` also need at least
one case that fires, which task 3.4 already covers using the real `mrpElementLines` field plus
fabricated ambiguity shapes.

## Risks / Trade-offs

- **Decision 1 is wrong about the intended vocabulary** → the derived view is empty while every
  validation passes. Mitigation: the positive control of Decision 13 fails in exactly that case,
  which is what distinguishes a legitimately empty view from a dead deriver; and the exit condition
  additionally requires ≥ 1 real edge across the four capabilities.
- **Live SAP metadata contradicts the assumed BAPI shape** (parameter, structure, or field names
  for `BAPI_MATERIAL_GET_DETAIL`) → the registered binding would be wrong in a way tests cannot
  see. Mitigation: the binding is transcribed from a real SE37 execution, not from memory, and a
  contradiction stops work and is escalated per the brief.
- **Fixing the duplicate-edge defect changes plan output for existing plans** → previously valid
  fixtures could change shape. Mitigation: the aggregation key `(producer, consumer, factType)`
  already exists in the validator; the compiler is being brought into line with it, and existing
  single-binding plans produce one edge before and after.
- **The narration guard change relaxes a check** → could mask a genuinely missing field.
  Mitigation: the guard still fails closed; the required set becomes exactly the fields the
  declared template references, so a template referencing a missing field still raises.
- **Payload-shaped field lists invite scope creep** into decomposing every nested structure.
  Mitigation: the depth rule in Decision 3 states the stopping condition, and the MRP row case is
  the recorded example of deliberately stopping.
- **`provenance=capability_derived` reaching the UI requires two frontend allow-list edits** →
  forgetting either silently strips traceability while all Python tests pass. Mitigation: the
  output-projection delta makes "derived parameter provenance survives projection" a spec
  scenario, and an unresolvable projection builder must fail closed rather than produce no fact.
- **Auto-pull issues a SAP READ the user did not ask for** (Decision 16) → surprise latency and an
  unexplained call in the trace. Mitigation: the pull is restricted to `kind: Function`, which the
  schema binds to `sideEffect: none`, so it can never be a write; the closure records the reason in the
  GoalSpec so the extra node is auditable; and narration discloses that an extra read occurred.
  Decision 15 additionally suppresses the pull whenever the user supplied the value, so the common case
  makes no extra call at all — eval case 2 (task 7.2) asserts the producer node is *absent*.
- **The registry no longer shows that a parameter will be derived** (Decision 15's accepted cost) →
  a reviewer reading `registry/capabilities.yaml` sees only `satisfiableByFactType` and cannot tell
  which field will feed it. Mitigation: the derived view is the intended review surface, and its
  positive control (Decision 13) is what keeps that surface trustworthy; a permanently dead deriver
  would otherwise present an empty view as a clean result.
- **Decision 14 relaxes a schema conditional** → an input could in principle declare an upstream
  source it never uses. Mitigation: `allOf[0]` is untouched, so a `fact` input still *requires*
  `satisfiableByFactType`; and every relaxed site keeps its factType/semantic-type equality assertion,
  so a declaration that matches no producer field surfaces as a plan gap rather than binding silently.

## Migration Plan

1. T0′ and T1 are additive to governed artifacts; the snapshot id changes once, and the 14
   `matcher_cases.yaml` pins are recomputed in the same step with the reason recorded (Decision 10).
   T0′ also lands the six-site `bindingKind` decoupling of Decision 14, which is behaviour-neutral on
   its own: with no input yet declaring `satisfiableByFactType`, every relaxed check has nothing new to
   admit.
2. T2 lands the deriver and the validator prohibition before any capability depends on it, so the
   derived view can be reviewed while it is still expected to be empty.
3. The eval case skeleton lands next (Decision 9), then T3 registers `MM.Material.GetInfo` as
   `kind: Function`, adds `satisfiableByFactType` to the two PR inputs (which stay
   `bindingKind: identifier`), and lands the `desired_fact_types` closure of Decision 16 plus the
   authoring-time precedence rule of Decision 15.
4. Rollback: reverting the registry entry and the two `satisfiableByFactType` declarations returns the
   system to a state where no input declares an upstream fact source, which is the current baseline.
   The FactType field lists, the deriver, and the Decision 14 relaxation can remain, because on their
   own they change no runtime behaviour beyond the snapshot id — a relaxed conditional admits nothing
   while no input exercises it.
5. No approval, subject-hash, or anti-replay semantics change, so no approval-store migration is
   needed. Fail-closed executors stay refusing.

## Open Questions

These are deferrable: none of them changes the specs, the approach, or the task breakdown.

1. Whether `mrpElementLines` should eventually be decomposed into row-level fields. Deferred until
   a consumer or a restatement of those names exists (Decision 3's depth rule decides it
   mechanically when that happens).
2. Whether the 15 deprecated `extraction:` inputs migrate in a later cleanup, and
   whether the deprecation warning should become an error at that point (Decision 12).
3. What `freshnessTolerance` values are defensible. Explicitly out of scope: the thresholds must
   come from `asOf` drift measured in a live composition smoke, and this change only produces the
   first composition from which that drift could later be measured.

---

## Implementation Divergence (recorded 2026-08-25, verify phase)

Written during `/comet-verify` because the implementation diverges from decisions above. Each entry
names the divergence, the reason, and the explicit decision that authorised it. Nothing here is a
silent deviation, and none of it is a defect: every item either has a user decision behind it or is a
correction found by running the code rather than reading it.

### 1. Goal not met — `provenance=capability_derived` reaching the narrative and approval surface

The **Goals** list states *"One real derived edge in production use, with `provenance=capability_derived`
reaching the narrative and the approval surface."* The derived edge exists in production use and is
verified live against SAP, but **the provenance does not reach either surface**, so this Goal is
**not met**.

Reason, traced rather than asserted. Two links are missing and the second is closed by an invariant
this change may not relax:

- **Finding G1** — `PlanExecutor.resolveParameters` handles `literal` only and silently skips a
  `factField` binding, so no derived value exists at runtime for a surface to disclose. Resolving it
  changes what `computeInputHash` hashes, and that is anti-replay machinery which **invariant 5**
  reserves to defect **D4** — declared out of scope for this batch by the task brief.
- **Finding G4** — `FactBuilderRegistry` is keyed by `capabilityId`, so projecting
  `sapnexus:MaterialInfoFact` requires per-capability TypeScript. Generalising it needs a `factShape`
  in the `ReasoningFact` model (`value` is typed `number | null` and consumers depend on that), which
  is a governed-contract change belonging to its own Classic change.

Current behaviour is **fail-closed, not under-disclosed**: a derived `purchasing_group` never reaches
`constraints.purchasingGroup`, the rule set's `requiredConstraints` is unsatisfied, and **no action
proposal is created**. An unapproved WRITE, never an under-disclosed one.

**Authorised by:** user decision at the build→verify guard — tasks 5.4a / 5.9 / 7.4 descoped to a
follow-up change `derived-parameter-runtime-disclosure`, recorded in `tasks.md` under *"Descoped from
this change"* with the original task text retained verbatim.

### 2. Decision 11's `asOf` / `snapshotId` provenance fields were not declared as Fact Type fields

Decision 11 lists the four `MaterialInfoFact` fields *"plus the `asOf` / snapshot provenance every fact
carries (invariant 5)"*. They were **not** added to `ontology/fact-types.yaml`, because Decision 11's
own title is *"added with **no new semantic type**"* and a Fact Type field must carry a tier-① value
type — the vocabulary has 16 members and none is a timestamp or a snapshot id, so declaring those two
fields requires exactly the new types the decision forbids. They would additionally need publishing as
capability outputs under the C5 rule, and **none of the three pre-existing Fact Types declares them
either**.

Verified where the provenance actually lives instead of assuming: `asOf` is **per-Fact**
(`fact-builder.ts:123,250,275`; present in `ALLOWED_PAYLOAD_KEYS.fact`) and `snapshotId` is
**per-projection** (`projection/assembler.ts:53`, `material-supply-snapshot.ts:248`; present in the
`projection` and `recommendation` allow-lists and deliberately **not** in the `fact` one). That split is
correct — a snapshot is a property of registry state, not of one fact. D4's three inputs therefore all
exist today at two levels; D4's work is to *join* them into the approval subject, not to create them.

Recorded in the plan as correction **C14**.

### 3. Mechanisms added that this design did not anticipate

All three were found by running the code or the live system, not by review, and each is covered by
tests and mutation checks recorded in the plan:

- **C13 / task 5.2a — a generic export-structure path resolver in the Gateway.** The design assumed the
  Gateway was capability-agnostic. It was not where it mattered: `outputMapping` values were read only
  as top-level export parameters, and the registry's **existing** dotted path
  (`MRP_IND_LINES.WB.AVAIL_QTY1`) was resolved by nothing — the value came from hardcoded logic, so the
  declaration was decorative. Registering `MM.Material.GetInfo` declaratively would have yielded no
  value at all. Consequence for the design's measurement: **figure (a) must be reported for Java as
  well as Python**; it is 0 in both.
- **Task 5.4b — an auto-pulled producer's key inputs are propagated from the consumer**, gated on the
  produced Fact Type's `keyedBy`. Without it the pulled producer had no bindings at all and every
  derived plan was invalid, so Decision 16's auto-pull could not execute.
- **Finding G5 — a blank structure field is treated as absent.** Live SAP returned
  `MATERIALPLANTDATA` initialised with `PUR_GROUP` blank; emitting `""` would turn *"this could not be
  derived, ask the user"* into *"an empty value was derived"*. Invisible to 1525 unit tests.

### 4. A behaviour change this design did not specify: a derivable parameter escalates

The design specifies the planner-layer mechanism but not what the **conversation** layer should do when
a required parameter is derivable and the user did not supply it. Implemented behaviour: the parameter
is dropped from `missing_parameters` and the decision becomes **`ESCALATE_TO_PLANNER`** rather than
`SELECT`, because deriving requires an upstream node plus a data edge in a PlanGraph (invariant 2),
which the single-capability `SELECT`/CallPlan path cannot express.

**Authorised by:** an explicit user decision during task 7.1, chosen over two alternatives (keep
`SELECT` and make CallPlan multi-step; or leave the conversation layer untouched). Without it the
feature was half delivered — the plan layer derived, and the user was still asked.

### 5. `proposal.md`'s T0′ bullet is stale relative to Decision 12

`proposal.md` still describes T0′ as migrating the two `MM.PR.CreateDraft` inputs off the deprecated
`extraction:` alias. **Decision 12** above dropped that migration, and the implementation follows
Decision 12: both inputs still carry `extraction:` and gained only `satisfiableByFactType`. The design
doc is correct and the proposal is the un-updated artifact. Flagged rather than edited, because
`proposal.md` records what was proposed and Decision 12 already records why it changed. The
`extraction` deprecation warning count is pinned at exactly **15** so this debt cannot grow silently.

### 6. Conflict recording: the delta spec requires it, this design removed it

`specs/declarative-intent-extraction/spec.md` carries two scenarios —
*"Conflict between user value and derived value is recorded"* and *"Matching values record no
conflict"* — and **neither is implemented**. `grep -rni conflict agent/sap_nexus_agent/planner/`
returns nothing.

That is not an omission. **Decision 7** in this document resolves precedence *at authoring time*: an
input already bound by the user produces no closure entry at all, so a second candidate value is never
computed and there is nothing to compare. Recording a conflict would mean performing the upstream read
anyway, purely to compare and log — which directly contradicts ruling ④ (用户明说优先) and would send an
avoidable request to SAP for the sake of a log line.

**User decision, verify phase: record as a design divergence (Option A).** The two scenarios are
therefore classified as **designed away, not unimplemented**. They remain in the delta spec as the
record of what was proposed; this section is the record of why the implementation does not satisfy them
and must not be made to.

What *is* asserted, so the precedence half of the requirement is not lost:
`test_user_supplied_value_suppresses_the_fact_field_source` (exactly one source, no data edge),
`test_the_closure_does_not_pull_when_the_user_supplied_the_value` (the producer is not pulled), and the
live eval case `user-supplied-wins` (`dryRun.present: false` — the absence of the producer node, not
merely the presence of a literal).

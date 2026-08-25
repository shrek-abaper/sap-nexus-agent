---
change: derived-parameter-binding
design-doc: docs/superpowers/specs/2026-08-25-derived-parameter-binding-design.md
base-ref: ee46a98d3f6335115b0a0672ddef13b7d2727a70
batch: T
---

# Derived Parameter Binding — Batch T Implementation Plan

## Goal

Make it *physically possible* for a capability parameter to be **derived from an upstream
capability's Fact** instead of being asked of the user. Today `provenance.capability_derived`
is always 0 because no mechanism exists to produce it: no Fact Type declares its fields, no
component derives producer→consumer data dependencies, and the planner never pulls a producer
into the plan on a consumer's behalf.

The observable end state — the single sentence that defines done:

> A user says *"给物料 M-1001 在工厂 1010 建一张采购申请"*. The plan contains a
> `MM.Material.GetInfo` node ordered **before** `MM.PR.CreateDraft`, a `data` edge carrying
> `sapnexus:MaterialInfoFact` between them, and `unit` + `purchasing_group` both resolve with
> `provenance=capability_derived` **without being elicited** — while a user who states the unit
> explicitly still wins, and the producer is then never pulled at all.

Two counts are reported at exit and are part of the definition of done:

- **Figure (a)** — Python lines changed to register the 4th capability (`MM.Material.GetInfo`).
  **Target: 0.** The registry is the sole authority (invariant 6).
- **Figure (b)** — Python lines changed to fix pre-existing defects that block (a), each line
  attributed to a named defect. Non-zero and expected; it must stay small and itemised.

Batch L is **out of scope**. It is a separate change and must not start until batch T's exit
conditions are met; the two batches commit independently and are never mixed into one commit.

## Architecture

Four layers, unchanged by this plan:

```
Python Agent            intent parsing · capability recall · CallPlan/PlanGraph authoring · 中文叙述
  ↓ (authors a plan; never executes)
Composition Runtime     Next.js/TS: PlanExecutor · node ledger · Projection · Narrative
  ↓
Java Gateway            Spring Boot — the only component with execution authority
  ↓
SAP                     JCo 3 RFC + OData
```

Where this change lands:

| Concern | Component | Nature of change |
|---|---|---|
| Fact Type field authority | `ontology/fact-types.yaml` + `schemas/fact-type-catalog.schema.json` | new required `fields[]`, catalog `version` 1→2 |
| Semantic-type vocabulary reconciliation | `registry/semantic-types.yaml` | header comment + one-way `extracts:` mapping |
| Data-dependency derivation | `agent/sap_nexus_agent/semantic_planning/derivation.py` (**new**) | pure function over `SemanticSourceDocuments` |
| Derived-view surface | `scripts/derive-data-dependencies.py` (**new**) | thin printable wrapper |
| Producer auto-pull | `agent/sap_nexus_agent/planner/goal_spec.py` | closure over `desired_fact_types` |
| Field selection + one-edge-per-pair | `agent/sap_nexus_agent/planner/plan_compiler_v2.py` | defect fixes → figure (b) |
| `bindingKind` coupling relaxation | 6 sites (schema + 2 validators + graph + compiler) | drop one test each, keep every equality assertion |
| The 4th capability | `registry/capabilities.yaml` | declaration only → figure (a) = 0 |

### The mechanism, stated once

The whole feature is one closure plus one match rule:

1. `MM.PR.CreateDraft.unit` is `bindingKind: identifier` and declares
   `satisfiableByFactType: sapnexus:MaterialInfoFact` (T0′ 1.1).
2. `build_goal_spec` sees `unit` is `required` and **not user-bound**, so it adds
   `sapnexus:MaterialInfoFact` to `goal.desired_fact_types` — but only if the Fact Type's
   producer is `kind: Function` (T3 5.4).
3. `_build_plan_graph_v2`'s existing desired-fact-type loop then creates the `MM.Material.GetInfo`
   node with **zero changes** (`plan_compiler_v2.py:213-233`).
4. The second pass authors a `factField` source for `unit`, picking the producer output whose
   `semanticType` equals the consumer input's — `sapnexus:UnitOfMeasure` → `baseUnitOfMeasure`
   (T3 5.6).
5. `PlanExecutor` executes in `topologicalOrder`. **The Agent never fetches anything.**

### Invariant 2 is the load-bearing architectural constraint

`capabilityOutput` as a parameter source manifests **only** as an upstream node + edge in the
PlanGraph, executed in order by `PlanExecutor`. It is strictly forbidden to call the Gateway or
fire an RFC/OData during intent parsing to "look the unit up first". The intent layer authors;
it never executes. **If any synchronous data-fetch call appears anywhere under `agent/`, that is
wrong — roll back and redo.** Task 5.8 is the explicit audit, but every task must respect it.

## Tech Stack

- **Python 3** — `agent/sap_nexus_agent/`, PyYAML present, `jsonschema` present. `.venv/bin/python`.
- **TypeScript / Next.js** — `frontend/`, vitest. No YAML parser dependency (verified).
- **No new pip / npm dependencies** without explicit user approval (invariant 7).
- **No second agent runtime.** LangChain / LangGraph / DeerFlow / OpenHarness / DeepSeek Harness /
  Microsoft Agent Framework must not become dependencies; only their design shapes may be borrowed.
- **No graph database. No OWL reasoning runtime.** Consistency is carried by JSON Schema +
  Registry Validator (invariant 8).
- OpenSpec CLI is reached only via `comet classic openspec -- <args...>`.

## Global Constraints

Violation of any of these is a rollback, not a review comment.

1. **Execution authority lives in the Java Gateway.** The Agent proposes intents / plan candidates
   via registered `capabilityId` only; it never initiates RFC / OData / SQL.
2. **`capabilityOutput` = upstream node + edge, never a synchronous fetch.** See above.
3. **Data dependency edges must be *derived*** — computed mechanically by matching FactType fields
   against `semanticType`. Hand-writing data dependency edges to make `capability-relations.yaml`
   look non-empty is forbidden. That file carries only relations that cannot be inferred from data
   shape. The acceptance criterion is "**the derived-edge view is non-empty**", not "the file is
   non-empty".
4. **fail-closed executors (`CDS_ADT` / `REST_JSON` / `SQL_READ`) stay in refusing state.**
5. **No change to any semantics of approval / subject hash / anti-replay.** Defect D4 (extending
   the subject to a joint hash of WRITE parameters + upstream Fact `asOf` + snapshot id) is a
   **separate batch**. But the upstream nodes added here become D4's inputs, so every Fact must
   retain `asOf` and `snapshotId`, and the coupling point must be flagged in the report.
   **A parameter being derived is never a reason to skip or simplify Human Approval.**
6. **The registry is the sole authority.** Adding the 4th capability requires **zero** Python
   changes. Report figure (a); target 0.
7. **No second agent runtime; no new pip/npm dependency without explicit approval.**
8. **No graph database; no OWL reasoning runtime.**
9. **Forbidden green-washing:** changing assertions so they are always true, deleting or skipping
   tests, relaxing gate thresholds, updating snapshots without explaining the semantic change,
   swallowing failures with `try/except`.
10. **No unresolved item may be summarised** as 已知问题 / 既有失败 / 与核心功能无关. Every
    unresolved item states the **specific test name + attribution + reason**.

Plus the project's standing rules:

- READ capabilities: `sideEffect: none`, and must not trigger `BAPI_TRANSACTION_COMMIT` /
  `BAPI_TRANSACTION_ROLLBACK`.
- WRITE capabilities must not execute until Human Approval is confirmed **for that capability**,
  recorded as a checkable acceptance item.
- Masking: material number / plant code are business identifiers and may stay; supplier names,
  person names, contact details follow the existing Gateway masking. Credentials / tokens /
  connection strings never enter any log or document — "it's only a log" is not a pass.
- Artifacts are **draft + manual publish only**. Never auto-write `registry/`.
- Numbering: task items are **T1–T5** / **L1–L4**. Any `Dx` (D2, D4) is a **defect number** from
  the architecture assessment, never a task number. Never mix the two systems; if a `Dx` is
  ambiguous, **stop and ask**.

## Baseline (measured, all green — this is invariant 10's attribution basis)

| Check | Result |
|---|---|
| `validate-registry-contract.py registry/capabilities.yaml` | valid; **15** `extraction` deprecation warnings |
| `pytest agent/tests -q` | **1345 passed / 1 skipped / 2 xfailed**, 103.09s |
| `npm --prefix frontend run verify` | exit 0 (typecheck + **52 files / 525 tests** + build) |
| `verify-agent-callplan-evidence.sh` | **22 passed / 0 failed** |

Named baseline non-passes — these are **pre-existing and must stay honest**, not tallied away:

- XFAIL `agent/tests/test_binding_sources.py::test_capability_output_source_resolution_is_not_implemented_yet`
  — the fixed landing point for defect **D2**. Must be **preserved** (ruling ④, task 1.4).
- XFAIL `agent/tests/test_binding_sources.py::test_binding_capability_output_not_implemented`
  — must be preserved. **Caveat resolved by task 1.4.3 (verified by reading the body, not the
  reason string alone):** the DID-NOT-RAISE outcome is *deliberate and documented*. The marker pins
  `raises=pytest.fail.Exception` so **only** that exact mode is absorbed, and the body opens with
  `assert "capabilityOutput" not in engine._WIRED_SOURCE_KINDS`, which raises `AssertionError` —
  not the pinned type — the moment the source is wired, converting the test into a real failure.
  So it is xfail for a reason that is true and stated. My earlier note that it was "xfail for the
  wrong reason" was based on the reason string in isolation and is **withdrawn**. Nothing to
  correct; the placeholder is preserved as-is.
- SKIPPED `agent/tests/test_llm_live.py:9` — env-gated on `SAP_NEXUS_LLM_LIVE=1`.

## Corrections to `openspec/changes/derived-parameter-binding/tasks.md`

Six findings from the pre-build fact check (C1–C6 before build, **C7 found at T1 entry, C8 found at
task 2.2 entry, C9 and C10 found at task 2.7 entry**).
**Where tasks.md and this plan disagree, this plan wins**, because these were verified against
source.

| # | tasks.md says | Verified truth | Consequence |
|---|---|---|---|
| C1 | 1.2 cites `validation.py:1426-1433` and `validate_registry_contract.py:491-495` as the sites to relax | Those ranges are the **`fact`-branch** rules that must be **KEPT**. The `identifier`-branch rules to drop are `validation.py:1433-1439` and `validate_registry_contract.py:495-499` | Following tasks.md literally would delete the wrong check, weakening validation and violating 1.2's own "no check becomes weaker" clause |
| C2 | (implicit) `factField.field` names a Fact Type field | `validation.py:459-464` requires `field` to equal a producer **capability output `name`** *and* `factTypeRef` to match | Determines T3's registry shape: the Fact Type field names and the output names must coincide |
| C3 | 5.2 "四个字段" | Multiple outputs sharing one `factTypeRef` is the **established** pattern (`MM.Inventory.GetAvailability` already has two) | `MM.Material.GetInfo` declares **four outputs**, all `factTypeRef: sapnexus:MaterialInfoFact`, with distinct `semanticType`s. 5.6 becomes "pick the producer output whose `semanticType` equals the consumer input's" — **zero validator change** |
| C4 | 5.5 implies validator work | `validation.py:483-496` keys `expected_data` to a **list**, so N sources per edge are already tolerated; only `validation.py:528-545` rejects duplicate *edges* | Defect 1 needs **zero** `validation.py` change. Only `plan_compiler_v2.py:277` moves. Keeps figure (b) small |
| C5 | 2.5 "fields vs outputs" tension unresolved | Derived invariant, verified against all 3 existing facts + the planned one | **A Fact Type field with `cardinality: one` must be published as a same-named, same-`semanticType` output by at least one active producer; `cardinality: many` fields are exempt.** `PurchaseOrderSupplyFact`'s six item-level fields are all `many` (container output is `purchaseOrders`) → exempt, land in `needsReduction`. `InventoryAvailabilityFact.availableQuantity` (one) is published; `mrpElementLines` (many) exempt. `MaterialInfoFact`'s four `one` fields map 1:1 to four outputs |
| C6 | 1.1 lands `satisfiableByFactType: sapnexus:MaterialInfoFact` in the registry during T0′ | That Fact Type is not published until 5.2, and the `UNKNOWN_FACT_TYPE` rule already exists (pinned by `test_semantic_planning_contract.py:3322-3324`). The spec delta mandates it: *"Identifier input references an unpublished Fact Type → contract validation fails and names the offending capability and input"* | **1.1's registry edit moves into 5.2 as one atomic registry change** (Fact Type + capability + the two `satisfiableByFactType` references together). T0′ becomes mechanism-only (1.2/1.3/1.4), tested against **fixtures**. Publishing `MaterialInfoFact` early is *not* an alternative: its four fields are all `cardinality: one`, so C5 would reject it for having no active producer. This is the only arrangement where every intermediate commit has a valid registry |
| C7 | 2.1 bumps `ontology/fact-types.yaml` to `version: 2` with "fields land in 2.5", and 2.8 recomputes the snapshot pins as a separate step | Two verified couplings make that split impossible. (a) 2.1.2 adds `fields` to `$defs/factType.required`, so the instant the schema lands, a catalog without `fields` is **invalid** — the 2.1→2.5 window would leave `ontology/fact-types.yaml` failing its own schema. (b) `snapshot.py:44` hashes `dict(documents)` — the **whole** document set — so the `version: 1 → 2` bump *alone* invalidates all **14** `sha256:e6d329bc…e599ed95` pins in `evals/matcher_cases.yaml` (count verified), independently of the field content | **2.1 + 2.5 + 2.8 are one atomic commit.** Same class of defect as C6, same fix: never leave an intermediate commit whose governed sources fail validation or whose pins are stale |
| C7a | (my own C7 first draft claimed `registry/semantic-types.yaml` is **not** a snapshot source, so 2.2/2.3 could not move the digest) | **That was wrong and is withdrawn.** `contracts.py:105-113` `documents_by_path()` returns **five** paths: the matcher catalog is included whenever `semantic_types` is non-empty, and the live snapshot lists it at `document_version: 2`, digest `sha256:173b31f2…cc8f406e` | 2.3's `extracts:` keys **do** move the digest, so T1 needs **two** documented pin recomputes: one for the fact-types change (2.1/2.5), one for the matcher-catalog change (2.3). Two documented recomputes are preferable to one giant commit — invariant 9 forbids *silent* refreshes, not documented ones. 2.2 is digest-neutral: `yaml.safe_load` discards comments |
| C8 | 2.4.1 reads "every `sapnexus:*` reference **anywhere** must exist in the ontology vocabulary" | Not implementable as written. Enumerating every reference site shows the `sapnexus:` namespace holds **five disjoint tiers**: ① value types (the Decision-1 vocabulary, 15 members, declared by capability `inputs`/`outputs.semanticType`); ② Fact Type ids (`*Fact`, declared by `factType.factTypeId`, already governed by `UNKNOWN_FACT_TYPE`); ③ Fact class types (`factType.semanticType` — `sapnexus:InventoryAvailability` etc., **not** in ① and self-declaring); ④ predicates (`factType.predicate` — `sapnexus:hasInventoryAvailability`, self-declaring); ⑤ capability individuals / function classes (`ontologyIri`, `capability.semanticType` — `ontologyIri` is already validated against the OWL skeleton by the registry validator). A literal tier-blind rule would reject tiers ③④⑤ | 2.4.1 is scoped to **tier ①**. Its only *uncovered* reference site is `factType.keyedBy` (`fields.semanticType` landed in 2.1.4), so 2.4.1's real deliverable is extending the tier-① check there. Tiers ③④ stay unvalidated by design — nothing declares them, so a rule could only be vacuous or wrong. Record that as a known limit rather than inventing a registry to check against |
| C9 | 2.7's **Files** list names `frontend/src/runtime/plan-evidence/event-projector.ts:69` as a Fact field-list restatement site | It is **not one**. Line 69 is `ALLOWED_PAYLOAD_KEYS.fact` — a ReasoningFact **envelope** key allowlist (it contains `factId`, `factTypeId`, `agentTraceId`, `traceRef`, `sourceSummary`, `asOf` alongside `availableQuantity`/`orderQuantity`/`unit`, and does **not** contain `purchaseOrder` or `supplier`). It governs which keys survive projection into a reasoning payload, a different vocabulary from a Fact Type's field list | Locking it against `ontology/fact-types.yaml` would be a category error — a `⊆`/`==` assertion between two unrelated sets. 2.7.4 records it as **"not a restatement site"** with that evidence instead of locking it. The genuine restatement family is: `ontology/fact-types.yaml` (authority) · `registry/capabilities.yaml:316` `itemFields` · `narrator.py:55` `_PO_REQUIRED_EVIDENCE` · the hardcoded label lines in `narrator.py` `_build_list_messages` / `_list_fallback` · `fact-builder.ts:246-278` evidence literal |
| C10 | 2.5 reported "**zero** new semantic types", and 2.7 assumed the TS evidence literal and the declared field list are the same set | Both are wrong, and the second exposes a real gap in Decision 1. `fact-builder.ts`'s evidence object has **seven** keys; the seventh, `purchaseOrderItem`, is load-bearing on the TS side (a member of `PurchaseOrderRow` at `:130` **and** a component of `rowSortKey` at `:232`, so it affects deterministic ordering) yet is absent from `ontology/fact-types.yaml`, from `itemFields`, and from `_PO_REQUIRED_EVIDENCE`. It is a genuine seventh item-level field that 2.5 missed. It cannot be declared under Decision 1 as written: tier ① is *"the set declared by capability `inputs`/`outputs.semanticType`"*, and the six existing PO field types pass that check **only by coincidence** — each happens to also be a PO or PR `input`. `purchaseOrderItem` is the first field type with no such coincidence, and `sapnexus:PurchaseOrderItem` is already taken by the container output `purchaseOrders` (the item *object*, not its *number*) | **User decisions at 2.7 entry: (a) extend the ontology with a new value type; (b) delete `itemFields` from the registry.** Both edit governed sources, so they land as **one atomic commit** with **one** documented snapshot recompute (#3). Three rejected alternatives, recorded because each is a green-washing trap: *declaring `purchaseOrderItem` as a sibling top-level output of PO* misrepresents the shape (it is a per-row field inside the array, not an output of the capability); *widening the vocabulary to include Fact Type `fields[].semanticType`* would make `_validate_fact_type_fields`' own semanticType check **vacuous** (invariant 9); *a sixth governed source file* is disproportionate. The chosen channel is a new **optional top-level `valueTypes:` block in `ontology/fact-types.yaml`**, with the vocabulary redefined as *capability-declared ∪ `valueTypes[].id`*, kept tight by two new rules so it cannot become a dumping ground: `VALUE_TYPE_SHADOWS_CAPABILITY` (an id already declared by a capability is rejected) and `VALUE_TYPE_NOT_USED` (an id no Fact Type references is rejected). A typo still fails closed, because a typo is in neither set |

## Task order

`T0′ → T1 → T2 → T5-skeleton → T3 → T4 → T5-full → exit verification`

**Why T5-skeleton before T3:** `MM.Material.GetInfo`'s registry entry declares `evalLinkage`
pointing at eval case ids. If T3 ran first, those ids would not yet exist and the entry could not
be authored without a forward reference — so the five case *skeletons* must exist first, pending
and attributed, before registration.

**T0′ vs the original T0:** the original T0 bundled an `extraction:` → `binding.sources[]`
migration for all 15 warning sites. That migration is **dropped** (see 1.1): `registry_loader`
already normalizes the alias into a single `userUtterance` source, pinned by
`test_extraction_alias_normalizes_to_single_user_utterance_source`, so migrating buys no
behaviour change and would inflate the diff. T0′ is the residue that T3 actually needs: two
`satisfiableByFactType` declarations plus the coupling relaxation.

---

# T0′ — Binding-source prerequisite

## Task 1.1 — Deferred to 5.2 (see correction C6)

The original 1.1 declared `satisfiableByFactType: sapnexus:MaterialInfoFact` on the two
`MM.PR.CreateDraft` inputs during T0′. **That cannot land here**: the Fact Type is not published
until 5.2, and the spec delta mandates that an identifier input referencing an unpublished Fact
Type **fails** contract validation. The edit therefore moves into 5.2 as part of one atomic
registry change.

**Interfaces** — the two inputs as they exist today, unchanged by T0′ (verified):

```yaml
      - name: unit
        semanticName: unitOfMeasure
        semanticType: sapnexus:UnitOfMeasure
        bindingKind: identifier
        required: true
        type: string
        minLength: 1
        maxLength: 3
        sapParameter: PRITEM.UNIT
        matchers:
          - kind: semanticType
            ref: Unit
            priority: 25
```

`purchasing_group` is the same shape: `semanticName: purchasingGroup`,
`semanticType: sapnexus:PurchasingGroup`, `sapParameter: PRITEM.PUR_GROUP`,
matcher `ref: PurchasingGroup`, priority 15.

**Steps**

- [x] 1.1.1 Confirm `registry/capabilities.yaml` is **not** modified in T0′. Assert `git diff` on it
  is empty at the end of task 1.
- [x] 1.1.2 Record that the `extraction:` → `binding.sources[]` migration originally scoped to T0
  is **dropped**: `registry_loader` already normalizes the alias into a single `userUtterance`
  source, pinned by `test_extraction_alias_normalizes_to_single_user_utterance_source`, so
  migrating buys no behaviour and would inflate the diff. It is orthogonal cleanup, deliberately
  not performed.
- [x] 1.1.3 Verify the `extraction` deprecation warning count is still **exactly 15** — i.e. T0′
  changed no registry declaration at all.

## Task 1.2 — Relax the `bindingKind` / `satisfiableByFactType` coupling at six sites

Design Decision 14, ruling ①. **Read C1 above before touching any line.**

**Files** (all six, with corrected targets)

| Site | Action |
|---|---|
| `schemas/capability.schema.json` `$defs/ioField/allOf[1]` | drop the `not.required: [satisfiableByFactType]`; **leave `allOf[0]` intact** |
| `scripts/validate_registry_contract.py:495-499` | drop the identifier-branch rule (**not** `:491-494`, which is the fact rule) |
| `agent/sap_nexus_agent/semantic_planning/validation.py:438-441` | drop the identifier-branch rule |
| `agent/sap_nexus_agent/semantic_planning/validation.py:1433-1439` | drop the identifier-branch rule (**not** `:1426-1433`) |
| `agent/sap_nexus_agent/semantic_planning/graph.py:68` | relax so an identifier input with `satisfiableByFactType` also records `consumesFactType` |
| `agent/sap_nexus_agent/planner/plan_compiler_v2.py:253` | relax the `bindingKind != "fact"` gate |

**Interfaces** — the two adjacent rules in `validation.py`, showing exactly which is which:

```python
1426	            elif binding_kind == "fact" and not fact_type_ref:      # KEEP — a fact input
1427	                _add_issue(                                          #   still REQUIRES the field
...
1433	            elif binding_kind == "identifier" and "satisfiableByFactType" in input_field:   # DROP
1434	                _add_issue(
1435	                    issues,
1436	                    f"{base_path}/satisfiableByFactType",
1437	                    "SCHEMA_INVALID",
1438	                    "identifier input must not declare satisfiableByFactType",
1439	                )
```

`graph.py` today (`:67-75`):

```python
            for input_field in capability["inputs"]:
                if input_field["bindingKind"] == "fact":
                    edges.add(
                        SemanticEdge(
                            "consumesFactType",
                            capability_id,
                            input_field["satisfiableByFactType"],
                        )
                    )
```

becomes keyed on the *declaration*, not the kind:

```python
            for input_field in capability["inputs"]:
                satisfiable_by = input_field.get("satisfiableByFactType")
                if satisfiable_by:
                    edges.add(
                        SemanticEdge("consumesFactType", capability_id, satisfiable_by),
                    )
```

`plan_compiler_v2.py:252-253` today:

```python
        for inp in card.inputs:
            if inp.binding_kind != "fact" or not inp.required:
                continue
```

becomes:

```python
        for inp in card.inputs:
            if not inp.satisfiable_by_fact_type or not inp.required:
                continue
```

**Existing tests that pin the OLD rule — these must be *inverted*, not deleted**

The spec delta already published the replacement requirement
(`openspec/changes/derived-parameter-binding/specs/registry-ontology-contract/spec.md:4,18,23`:
*"an identifier input MAY also reference one published `satisfiableByFactType`"*), so inverting
these assertions is **spec-driven**, not green-washing. Each inversion must be recorded with the
requirement that authorises it.

| Site | Today | After |
|---|---|---|
| `agent/tests/test_contract_files.py:412-417` | `identifier_with_fact` expects `jsonschema.ValidationError` | expects **successful** validation |
| `agent/tests/test_semantic_planning_contract.py:2449` | `("identifier-with-fact-reference", "SCHEMA_INVALID")` in the negative matrix | removed from the negative matrix, added as a **positive** case |
| `agent/tests/test_semantic_planning_contract.py:2468-2471` | legacy-validator matrix expects `"identifier must not declare satisfiableByFactType"` | removed from that matrix, added as a positive case |
| `agent/tests/test_semantic_planning_contract.py:3313-3316` | `identifier-has-fact-reference` in the fail-closed matrix | removed from fail-closed, added as a positive case |

The mutation helpers at `:2390` and `:3190-3193` stay — they are reused by the new positive cases.

Note `unknown-input-fact-reference` (`:3196-3198`, expecting `UNKNOWN_FACT_TYPE`) sets
`bindingKind: fact`, so it is untouched **and becomes more meaningful** after relaxation.

**Steps**

- [x] 1.2.1 Write five failing tests before editing: (a) a `fact` input **without**
  `satisfiableByFactType` still fails validation — the regression guard proving no check became
  weaker; (b) an `identifier` input **without** `satisfiableByFactType` still validates;
  (c) an `identifier` input **with** a *published* `satisfiableByFactType` validates
  (spec scenario "Identifier input declares Fact Type reference"); (d) an `identifier` input with
  an **unpublished** `satisfiableByFactType` fails with `UNKNOWN_FACT_TYPE` naming the capability
  and input (spec scenario "Identifier input references an unpublished Fact Type" — this test does
  **not** exist today; the existing unknown-fact case uses `bindingKind: fact`); (e) `graph.py`
  records a `consumesFactType` edge for an `identifier` input declaring `satisfiableByFactType`.
  (a) and (b) pass now; (c), (d), (e) fail now.
- [x] 1.2.2 Edit `schemas/capability.schema.json` — remove only the `allOf[1]` `not.required`
  clause. Confirm `allOf[0]` (the `kind: Function` ⇒ governance binding) is byte-identical
  afterwards; T3 5.4's safety argument rests entirely on it.
- [x] 1.2.3 Edit `scripts/validate_registry_contract.py`, dropping the identifier rule at
  `:495-499`. Confirm the fact rule at `:491-494` is unchanged.
- [x] 1.2.4 Edit `validation.py` at both sites, dropping the identifier branches only. Confirm
  every remaining branch keeps its factType / semantic-type equality assertion.
- [x] 1.2.5 Edit `graph.py` and `plan_compiler_v2.py` per the snippets above.
- [x] 1.2.6 Invert the four existing tests per the table above, each with a comment naming the
  authorising spec requirement.
- [x] 1.2.7 Run 1.2.1's five tests — all green.
- [x] 1.2.8 Run `pytest agent/tests -q`. Expect 1345 passed / 1 skipped / 2 xfailed **plus** the
  new tests, with the four inverted tests still present and passing. Any *other* delta is a real
  regression: stop, diagnose, do not proceed.
- [x] 1.2.9 Attribute these lines to **figure (b), "bindingKind coupling relaxation (Decision 14)"**.

## Task 1.3 — Compiler-layer precedence: user-supplied beats upstream-derived

Design Decision 7, ruling ② (*用户明说优先* — the user overrode my recommendation here).

**Files**

- `agent/sap_nexus_agent/planner/plan_compiler_v2.py` — `_build_plan_graph_v2`, second pass

**Explicitly NOT touched** — and this is a checked acceptance item, not a preference:

- `agent/sap_nexus_agent/extraction/engine.py:24` `_SOURCE_PRIORITY`
- `agent/tests/test_binding_sources.py:112-166`

The `binding.sources[]` priority contract governs the **extraction** layer. It is not exercised by
this change and no published requirement is overturned. Precedence here is an **authoring-time**
decision in the compiler.

**Steps**

- [x] 1.3.1 Failing test: a goal where the user supplied `unit` explicitly →
  `unit`'s `parameterBindings` entry has `source.kind == "literal"` (or `goalConstraint`),
  **no** `factField` source, and **no** `MM.Material.GetInfo` node in the plan.
- [x] 1.3.2 In the second pass, skip authoring a `factField` source when the parameter already
  carries a `literal` or `goalConstraint` binding.
- [x] 1.3.3 Note the structural payoff in the task record: because precedence applies at
  *authoring* time, **exactly one source is authored per parameter**, so the
  duplicate-`parameterBindings` hazard is dissolved mechanically rather than validated against.
- [x] 1.3.4 Assert `git diff` touches neither `extraction/engine.py` nor
  `test_binding_sources.py:112-166`.

## Task 1.4 — Pin the source-kind enum and preserve the `capabilityOutput` placeholder

Design Decision 15, ruling ④.

**Steps**

- [x] 1.4.1 Add a schema-enum assertion test: the `binding.sources[].kind` enum is **exactly**
  `["userUtterance", "capabilityOutput", "default"]`. No `sessionContext` kind exists or is
  introduced.
- [x] 1.4.2 Assert both `test_binding_sources.py` xfail placeholders still exist and are still
  xfail. `capabilityOutput` remains deliberately unwired — it is defect **D2**'s fixed landing
  point and this change does not enable it.
- [x] 1.4.3 **Honesty check** (see Baseline): `test_binding_capability_output_not_implemented` is
  currently xfail because its raise-assertion "DID NOT RAISE" — i.e. xfail for the wrong reason.
  Once `factField` authoring is real, re-read it and confirm it is *still xfail for a reason that
  is true*. If it becomes coincidentally-xfail, correct the test's assertion or its reason string.
  Do **not** leave a test passing-as-xfail on a false premise (invariant 9).

---

# T1 — Authoritative Fact Type field schema

## Decision point at T1 start — the TS restatement lock

Design Doc §9 open item #1 says this is settled at the start of T1, so resolve it here rather
than as a mid-task placeholder.

Verified facts: the frontend has **no** codegen markers and **no** YAML parser dependency
(`scenario-runner.ts`'s `yaml` occurrences are path string literals passed to the Python eval
module); there are no `.json` imports under `frontend/src`; and there is **no cross-language
conformance-test precedent** in the repo (`test_orchestrator.py:1186` only *mentions*
`frontend/src/runtime/durable/canonical-json.ts` in a comment).

Two TS sites restate field lists: `frontend/src/runtime/projection/fact-builder.ts:130-140` and
`frontend/src/runtime/plan-evidence/event-projector.ts:69`.

| Option | Mechanism | New dependency |
|---|---|---|
| **A (chosen)** | Python-side conformance test reads the TS source text and asserts it matches the authoritative field list | none (PyYAML present) |
| B | Python emits a JSON projection the frontend imports natively | none, but adds a committed generated artifact |
| C | Add a frontend YAML dependency | **yes — requires explicit user approval (invariant 7)** |

**Choose A.** It adds no dependency and no generated artifact, and it satisfies 2.7's requirement
that each site be either derived or conformance-locked. If A proves unworkable during 2.7, **stop
and ask** before considering C.

## Task 2.1 — Extend the Fact Type catalog schema with a required field list

**Landing rule (correction C7): 2.1, 2.5 and 2.8 land as ONE commit.** The schema change makes
`fields` required, so the catalog is invalid until 2.5 declares them; and the `version` bump alone
moves the whole-documents digest, so 2.8's 14 pins are stale in the same instant. Steps below are
still numbered per task, but the commit boundary is after 2.8.

**Files**

- `schemas/fact-type-catalog.schema.json`
- `ontology/fact-types.yaml` (version bump only; fields land in 2.5)
- `agent/sap_nexus_agent/semantic_planning/validation.py` (new rule)

**Interfaces** — the schema today (verified, 46 lines): `additionalProperties: false`,
`required: ["version", "factTypes"]`, `"version": {"const": 1}`, and `$defs/factType` with
`additionalProperties: false` plus a 7-key `required` list
(`factTypeId`, `name`, `description`, `businessObject`, `predicate`, `semanticType`, `keyedBy`).
`ontology/fact-types.yaml` is `version: 1` with three fact types and **no `fields` key**.

Target field shape:

```yaml
    fields:
      - name: baseUnitOfMeasure
        semanticType: sapnexus:UnitOfMeasure
        cardinality: one          # one | many
        optional: false
        description: 基本计量单位（MARA-MEINS）
```

**Steps**

- [x] 2.1.1 Failing test: `ontology/fact-types.yaml` validates and every Fact Type has a non-empty
  `fields[]` whose entries carry all five keys.
- [x] 2.1.2 Add `fields` to `$defs/factType.properties` with its own `$defs/factTypeField`
  (`additionalProperties: false`, `required: [name, semanticType, cardinality, optional, description]`,
  `cardinality` enum `[one, many]`). Add `fields` to `$defs/factType.required` — it is **required
  for every Fact Type**, which is what lets a consumer rely on it existing.
- [x] 2.1.3 Bump the catalog: `"version": {"const": 2}` in the schema and `version: 2` in
  `ontology/fact-types.yaml`. A newly-required key is a breaking catalog change and the version is
  the mechanism that communicates it — `registry/semantic-types.yaml` already set the v2 precedent.
- [x] 2.1.4 Add the validator rule: each field's `semanticType` must be drawn from the `sapnexus:*`
  ontology vocabulary, validated against the set of semantic types declared by capability
  inputs/outputs (Decision 1).
- [x] 2.1.5 Verify a **matcher-catalog bare id** (e.g. `Unit`) fails, and an unknown
  `sapnexus:Nonexistent` fails, each naming the offending Fact Type **and** field.
- [x] 2.1.6 Verify `snapshot.py:37` `document_version=int(document["version"])` reads `2` without
  error. (It is an unconstrained `int()`, so it will — assert it rather than assume it.)

## Task 2.2 — Label `registry/semantic-types.yaml` as the matcher catalog

**Steps**

- [x] 2.2.1 Add a header comment stating this file is the **extraction matcher catalog**, not the
  semantic-type authority; the authority is the `sapnexus:*` ontology vocabulary.
- [x] 2.2.2 Do **not** rename the file — no `matchers: [{kind: semanticType, ref: <bare id>}]` site
  changes. Verify by grepping that every `ref:` still resolves.

## Task 2.3 — Add the one-way `extracts:` mapping

**Interfaces** — entries are shaped `id` / `description` / `priority` / `matchers[]`
(kinds `prefixed` / `suffixed` / `regex`, with `valueShape`, `pattern`, `justification`, `scan`).

```yaml
  - id: Unit
    extracts: sapnexus:UnitOfMeasure     # one-way: matcher id → ontology vocabulary
```

**Steps**

- [x] 2.3.1 Failing tests for the three properties below, then add `extracts:` to each entry.
- [x] 2.3.2 Verify **several matchers may extract one ontology type** (many-to-one is legal).
- [x] 2.3.3 Verify a matcher declaring **two different** ontology types is rejected.
- [x] 2.3.4 Verify `sapnexus:AvailableQuantity` having **no** matcher entry passes with no
  back-fill prompt — the mapping is one-way; not every ontology type is user-extractable.

## Task 2.4 — Two vocabulary-integrity validator rules

**Steps**

- [x] 2.4.1 Rule: every `sapnexus:*` reference anywhere must exist in the ontology vocabulary.
- [x] 2.4.2 Rule: every `extracts:` target must exist in the ontology vocabulary.
- [x] 2.4.3 Verify each rule fails naming **the offending reference and its declaring entry**.

## Task 2.5 — Declare field lists for the three existing Fact Types

Design Decision 3 (payload-shape model + depth rule) and **C5** (the `cardinality: one`
publication invariant).

**Interfaces** — the three existing Fact Types: `sapnexus:InventoryAvailabilityFact`,
`sapnexus:PurchaseOrderSupplyFact`, `sapnexus:PurchaseRequisitionCreatedFact`.

Current producer outputs (verified):

```
MM.Inventory.GetAvailability (Function): availableQuantity / sapnexus:AvailableQuantity / InventoryAvailabilityFact / primaryFact
                                         mrpElementLines   / sapnexus:MrpElementLine    / InventoryAvailabilityFact / primaryFact
                                         returnMessages    / sapnexus:SapReturnMessage  / —                         / executionEvidence
MM.PurchaseOrder.GetList (Function):     purchaseOrders    / sapnexus:PurchaseOrderItem / PurchaseOrderSupplyFact   / primaryFact
MM.PR.CreateDraft (Action):              prNumber          / sapnexus:PrNumber          / PurchaseRequisitionCreatedFact / primaryFact
                                         returnMessages    / sapnexus:SapReturnMessage  / —                         / executionEvidence
```

**Steps**

- [x] 2.5.1 `PurchaseOrderSupplyFact`: decompose the six item-level fields as
  `cardinality: many`. The array **container output name (`purchaseOrders`) is not declared as a
  field**. Under C5 these `many` fields are exempt from the publication rule and land in
  `needsReduction` — they are never emitted as bindable edges.
- [x] 2.5.2 `InventoryAvailabilityFact`: `availableQuantity` as `cardinality: one`;
  `mrpElementLines` as **one opaque `many` field** (do not decompose it — the depth rule).
- [x] 2.5.3 `PurchaseRequisitionCreatedFact`: `prNumber` as `cardinality: one`.
- [x] 2.5.4 Add the C5 invariant as a validator rule + test: **a `cardinality: one` field must be
  published as a same-named, same-`semanticType` output by at least one active producer;
  `cardinality: many` fields are exempt.** Verify it holds for all three existing Fact Types
  *before* T3 adds a fourth.

## Task 2.6 — Delete `narrative.fieldMapping.itemFields` (user decision at 2.7 entry)

**Verified before deciding:** `itemFields` has **no consumer**. `field_mapping` is read at exactly one
place, `narrator.py:157` `_resolve_template_vars`, which is called from exactly one place,
`narrator.py:187` `_inventory_narrative_body` — the `factShape: single-value` path. The
`factShape: list` path (`_build_list_messages` / `_list_fallback`) hardcodes the six names with
Chinese labels and never reads `config.field_mapping`. So "deriving" `itemFields` would be pure
ceremony: a derived value nothing reads. Conformance-locking it would lock a dead copy in place.
The user chose deletion; that is the only option that actually removes the restatement.

**Steps**

- [x] 2.6.1 Remove the whole `narrative.fieldMapping` block from `MM.PurchaseOrder.GetList`
  (`itemFields` is its only key, and `fieldMapping` carries `minProperties: 1`, so an empty object
  is invalid — the block goes, not just the key).
- [x] 2.6.2 `schemas/capability.schema.json`: drop `fieldMapping` from `narrative.required` and add
  an `if factShape == single-value then required: [fieldMapping]` guard. This is **stricter than
  plain-optional** and matches the consumer reality exactly: only the single-value path reads it.
- [x] 2.6.3 **Do not bump `registry/capabilities.yaml` `version`.** The rule, stated so it is
  reviewable: *bump when a document gains or requires a key a reader must newly understand; do not
  bump when a key merely becomes omittable and every reader already handles its absence.*
  `registry_loader.py:200` was written tolerant (`raw.get("fieldMapping") or {}` → `()`), so no
  reader needs a lockstep update. Contrast 2.6a below, which **does** bump, because `valueTypes` is
  a new top-level key the validator must read.
- [x] 2.6.4 Fix the now-stale parenthetical at `narrator.py:168` naming `po itemFields` as the
  example of a comma-separated expression. Orphaned by this change, so in scope.
- [x] 2.6.5 `receiptId` in `MM.PR.CreateDraft`'s `fieldMapping` is **also** dead by the same
  analysis (`action-receipt` never reaches `_resolve_template_vars`). **Out of scope** — not asked
  for. Record it as a figure-(b) cleanup candidate, do not delete it.

## Task 2.6a — Declare `purchaseOrderItem` and open the `valueTypes` channel (correction C10)

**Steps**

- [x] 2.6a.1 `schemas/fact-type-catalog.schema.json`: `version` const `2 → 3`; add an optional
  top-level `valueTypes` array (`uniqueItems`, items `{id, description}`, both required,
  `additionalProperties: false`).
- [x] 2.6a.2 `ontology/fact-types.yaml`: `version: 2 → 3`; add
  `valueTypes: [{id: sapnexus:PurchaseOrderItemNumber, description: …}]`; add `purchaseOrderItem`
  as the **seventh** `cardinality: many` field of `sapnexus:PurchaseOrderSupplyFact`, positioned
  after `purchaseOrder` to match the TS evidence order.
- [x] 2.6a.3 `validation.py`: rename `_semantic_types_declared_by_capabilities` →
  `_ontology_value_type_vocabulary` (the old name becomes a lie once `valueTypes` is a source) and
  union in `valueTypes[].id`. Two call sites: `_validate_fact_type_fields`,
  `_validate_vocabulary_references`.
- [x] 2.6a.4 `validation.py`: new `_validate_value_type_declarations` emitting
  `VALUE_TYPE_SHADOWS_CAPABILITY` and `VALUE_TYPE_NOT_USED` at `/valueTypes/{i}/id`. Wire it into
  `build_semantic_contracts`. **Verified non-blockers:** the OWL skeleton check at
  `validate_registry_contract.py:421` applies only to `ontologyIri`, never to a `semanticType`, so
  the new value type needs no `.owl` entry; the registry validator has no `narrative` requirement.
- [x] 2.6a.5 Update the `fact_types` exact-version case in `test_semantic_planning_contract.py`:
  it currently mutates `version` to **3** to force a failure, which becomes a **no-op** once 3 is
  the valid version. It must become 4, or the test silently stops testing anything.
- [x] 2.6a.6 Update the `ontology/fact-types.yaml` version pin in `test_contract_files.py`
  `_registry_snapshot` (`2 → 3`) and the isolated `factTypes` fixture at
  `test_registry_contract.py:100`.

## Task 2.7 — Cross-check every other field-list restatement site

**Files** — corrected by C9; `event-projector.ts:69` is **not** a restatement site.

- `frontend/src/runtime/projection/fact-builder.ts:246-278` (evidence literal, 7 keys)
- `agent/sap_nexus_agent/narrator.py:55` `_PO_REQUIRED_EVIDENCE`
- `agent/sap_nexus_agent/narrator.py` `_build_list_messages` / `_list_fallback` hardcoded labels
- any Java DTO restating a Fact field list

**Steps**

- [x] 2.7.1 Implement the **option A** lock: a Python conformance test reading the TS source as text
  and asserting its field list matches `ontology/fact-types.yaml`. With 2.6a landed the assertion
  is **exact equality**, not `⊆` — that was the whole point of declaring the seventh field.
- [x] 2.7.2 Lock `_PO_REQUIRED_EVIDENCE` as a **set** equality (it orders `plant` before `material`
  while the old `itemFields` ordered `material` before `plant` — real drift between two restatements
  of the same list; the ordering is not itself governed, so only the set is locked).
- [x] 2.7.3 Enumerate Java DTOs restating a Fact field list; for each, record **derived** or
  **conformance-locked**.
- [x] 2.7.4 Verify each locked site **fails** when the authoritative list changes (mutate, observe,
  restore).
- [x] 2.7.5 Produce the table: every site, its lock mechanism, its failing evidence. **No site may
  remain an unchecked independent copy.**

**2.7.5 result** — all locks live in `agent/tests/test_fact_field_restatement_locks.py` (12 tests).
Lock strength follows producer/consumer role, not convenience: the producer must publish *precisely*
the declared set, a consumer may legitimately read fewer.

| Site | Role | Lock mechanism | Failing evidence |
|---|---|---|---|
| `ontology/fact-types.yaml` `sapnexus:PurchaseOrderSupplyFact.fields` | **authority** (7 fields) | none needed — it is the source | `test_purchase_order_item_is_a_declared_field` |
| `frontend/src/runtime/projection/fact-builder.ts:246-278` evidence literal | producer | **exact set equality** with the authority, parsed from TS source text | `test_ts_evidence_lock_fails_when_the_authority_renames_a_field` — rename `supplier` in the authority → lock fails |
| `narrator.py:55` `_PO_REQUIRED_EVIDENCE` | consumer (narration **precondition**) | **subset** of the authority | `test_narrator_locks_fail_when_the_authority_renames_a_consumed_field[_PO_REQUIRED_EVIDENCE]` |
| `narrator.py:274-278` `_build_list_messages` (`ev.get('…')`) | consumer | **subset**, parsed from source | same test, `_build_list_messages` case |
| `narrator.py:318-322` `_list_fallback` (`evidence['…']`) | consumer | **subset**, parsed from source | same test, `_list_fallback` case |
| `event-projector.ts:69` `ALLOWED_PAYLOAD_KEYS.fact` | **not a restatement site** (C9) | asserted positively: it is a ReasoningFact *envelope* allowlist (`factId`, `factTypeId`, `agentTraceId`, `traceRef`, `sourceSummary`, `asOf`) and contains neither `purchaseOrder` nor `supplier` | `test_event_projector_fact_allowlist_is_not_a_field_list_restatement` |
| Java `src/main/java/**/*.java` | — | **tripwire**: no main source may name a PO-only Fact field. The exclusion set is *derived* from registry `inputs`/`outputs` names, never hand-picked | `test_no_java_main_source_restates_a_purchase_order_only_field` (asserts the derived `fact_only` set is non-empty first, so the tripwire cannot go vacuous) |
| `registry/capabilities.yaml` `MM.PurchaseOrder.GetList` `narrative.fieldMapping.itemFields` | dead copy | **deleted** (task 2.6) | `test_purchase_order_narrative_declares_no_field_mapping` |

Why `PurchaseOrderSupplyFact` needed its own locks while the other two Fact Types did not: every one
of its fields is `cardinality: many`, so the C5 rule ("a `cardinality: one` field must be published
as a same-named capability output") exempts all of them. The Java main sources name only
`availableQuantity`, `mrpElementLines` and `prNumber` — all declared outputs, already bound by C5.

**Subset, not equality, for the three narrator sites** — deliberate. `_PO_REQUIRED_EVIDENCE` is not a
description of the Fact, it is a precondition: `_assert_po_evidence_complete` and `_list_fallback`
both raise `NarrativeGuardError` when a listed field is absent or `None`. Adding `purchaseOrderItem`
to it to satisfy an equality assertion would make narration *reject* facts lacking that field —
changing runtime behaviour to satisfy a test (invariant 9).

## Task 2.8 — Recompute the snapshot pins, with the semantic reason recorded

**Interfaces** — `semantic_planning/snapshot.py` hashes **whole documents** with no key filtering:

```python
34	    source_entries = tuple(
35	        SnapshotSource(
36	            path=path,
37	            document_version=int(document["version"]),
38	            digest=_sha256_id(document),
...
45	        snapshot_id=_sha256_id(dict(documents)),
```

So adding `fields:` **necessarily** changes both the fact-types per-source digest and `snapshot_id`.
This is a mechanical consequence, not a choice.

**Verified pin inventory:**

| File | Pin | Action |
|---|---|---|
| `evals/matcher_cases.yaml` | real digest `sha256:e6d329bc…e599ed95` in **14 places** | **recompute** — the only file that must change |
| `agent/tests/fixtures/semantic_planning/plan-material-supply.yaml:5` | all-zeros **placeholder**, not a real digest | no change |
| `evals/recommendation_decision_cases.json:74` | symbolic `"snapshot-2"` | unaffected |

**Steps**

- [x] 2.8.1 Recompute and update the 14 `evals/matcher_cases.yaml` pins.
- [x] 2.8.2 Write the semantic reason into the **commit body**: *"fact-types.yaml v1→v2 adds
  required `fields[]`; snapshot.py hashes whole documents, so the per-source digest and
  snapshot_id necessarily change."* Silently refreshing a snapshot is forbidden (invariant 9).
- [x] 2.8.3 Verify **no approval subject hash** in `agent/tests/test_approval.py` or
  `agent/tests/test_orchestrator.py` is touched (invariant 5). Assert via `git diff` on those files
  being empty.

---

# T2 — Derived data dependency edges

## Task 3.1 — The deterministic deriver

Design Decision 2. **Invariant 3 lives here**: edges are *computed*, never hand-written.

**Files**

- `agent/sap_nexus_agent/semantic_planning/derivation.py` (**new**)

**Interfaces** — a pure function over `SemanticSourceDocuments`, with **three** consumers:
the `build_goal_spec` closure (5.4), the `plan_compiler_v2` second pass (5.6), and the validator
rule (3.6).

```python
def derive_data_dependencies(documents: SemanticSourceDocuments) -> DerivedDependencyView:
    """Derive producer→consumer data edges by strict semantic-type equality.

    No model call. No Gateway call. No SAP call. Deterministic.
    """
```

Candidate scoping, in order:

1. The consuming input's `satisfiableByFactType` names Fact Type `F`.
2. The candidate set is the **active producers of `F`** — capabilities with an output whose
   `factTypeRef == F`.
3. Match by **strict semantic-type equality**: producer output `semanticType` == consumer input
   `semanticType`.

**Steps**

- [x] 3.1.1 Failing test for determinism: run the deriver twice on the same documents, assert
  byte-identical output (including ordering).
- [x] 3.1.2 Implement the pure function.
- [x] 3.1.3 Verify a field with a **matching semantic type in an undeclared Fact Type** is **not**
  a candidate — the `satisfiableByFactType` scoping is load-bearing, not decorative.
- [x] 3.1.4 Assert by source inspection that `derivation.py` imports nothing that can perform I/O
  to the Gateway or SAP (invariant 2).

## Task 3.2 — The positive control fixture

Design Decision 13, ruling ③ (the user made this **mandatory**).

**Steps**

- [x] 3.2.1 Build two **fabricated** capabilities whose fields make **exactly one** edge derivable.
- [x] 3.2.2 Assert the deriver produces that edge.
- [x] 3.2.3 Verify the fixture contributes **nothing** to the Registry Snapshot and its
  capabilities are **absent** from the active set. A test fixture must never enter the execution
  boundary.
- [x] 3.2.4 Record why this exists: an empty real view is only meaningful if the deriver is proven
  capable of producing a non-empty one. Empty + red positive control = deriver defect (3.7).

## Task 3.3 — Emit derived edges in `dependsOn` shape with `origin: derived`

**Steps**

- [x] 3.3.1 Emit derived edges in `dependsOn` shape carrying `origin: derived`, so
  `plan_compiler_v2.py:299-312` consumes them **unchanged**.
- [x] 3.3.2 Verify **no new relation-type name** is introduced for derivedness — `origin` is a
  field, not a new relation kind (ruling ①: the relation catalog stays `dependsOn` + `precondition`,
  additive only).

**Result — 3.3.1 is checked by running the readers, not by comparing key names**

`DerivedDataEdge.to_relation()` renders `{relationId, relationType: dependsOn, capabilityId:
<consumer>, dependsOnCapabilityId: <producer>, origin: derived}`;
`DerivedDependencyView.to_relations()` collapses per capability pair, because a dependsOn relation
is capability-level and two derived parameters from one producer are one dependency (the S1
validator expects exactly one `dependency` edge per dependsOn). `plan_compiler_v2.py` has **zero
changed lines** in this task.

| Reader | Test | Consumes the rendered relation |
| --- | --- | --- |
| `plan_compiler_v2.py:299-312` third pass | `test_compile_plan_v2_consumes_derived_relations_without_a_compiler_change` | authors one `dependency` edge, direction cross-checked against the `data` edge it computed independently |
| `graph.py:77-85` relation reader | `test_the_semantic_graph_reads_a_derived_relation_as_a_depends_on_edge` | emits a `dependsOn` `SemanticEdge`; the unknown `origin` field passes through |

**Result — 3.3.2, and why `origin` is a field**

The vocabulary is read out of `schemas/capability-relation.schema.json` rather than restated, so a
third kind added to the schema fails the test. Mutating `DERIVED_RELATION_TYPE` to
`"derivedDependsOn"` shows a new kind is **not** additive at all: `graph.py:77-85` treats the
vocabulary as closed — anything that is not `dependsOn` falls into the precondition branch and reads
`requiredFactType`, so the mutation raises `KeyError` at `graph.py:81`. An unknown *field* costs both
readers nothing.

`origin` is not schema-legal in the catalog file yet; task 3.6 admits it. That is consistent, not a
gap: the rendering is an in-memory projection, and writing it back into
`ontology/capability-relations.yaml` is what invariant 3 forbids.

**Mutations run, each caught by exactly the test that claims it**

| Mutation | Caught by |
| --- | --- |
| `setdefault` → per-parameter key (dedup removed) | `test_two_derived_parameters_from_one_producer_are_one_relation` |
| consumer/producer swapped in the rendered relation | the shape test, the two-pairs test, and the compiler test (direction disagrees with the data edge) |
| `dependsOn` → `derivedDependsOn` | the 3.3.2 test, the graph test, and the compiler test |

## Task 3.4 — `needsReduction` and `ambiguous` diagnostics

**Steps**

- [x] 3.4.1 Implement both diagnostics with **no operator selection and no self-selection** — the
  deriver reports, it never resolves.
- [x] 3.4.2 Verify `needsReduction` against the **real** `mrpElementLines` case.
- [x] 3.4.3 Verify `ambiguous` against **both** trigger shapes: (i) two matching fields in the
  declared Fact Type; (ii) two active producers of it.
- [x] 3.4.4 Fix the `producers[0]` silently-picks-one defect. Today (`plan_compiler_v2.py:213-217`):

```python
213	    for fact_type in goal.desired_fact_types:
214	        producers = producers_by_fact.get(fact_type)
215	        if not producers:
216	            continue
217	        card = producers[0]
```

  Latent today because each Fact Type has exactly one producer — but auto-pull (5.4) makes it
  load-bearing. Two producers must surface as **`ambiguous`**, never resolve by list order.
  Verify with a fixture having two producers of one Fact Type. Attribute to **figure (b),
  "producers[0] silently-picks-one"**.

**Result** — `1447 passed, 1 skipped, 2 xfailed`; registry validator exit 0;
`verify-agent-callplan-evidence.sh` `22 passed, 0 failed`.

The diagnostic vocabulary is **exactly two kinds**, and the boundary is deliberate:

| Shape | Treatment | Why |
| --- | --- | --- |
| only `cardinality: many` fields match | `needsReduction` | a reduction operator is needed and choosing one is a modelling decision |
| >1 matching field in the declared Fact Type | `ambiguous` (`candidateKind: field`) | the registry has not said which |
| >1 active producer output | `ambiguous` (`candidateKind: producerOutput`) | ditto, one level up |
| no matching field at all | silent skip | not a source is not an ambiguity — no author decision is pending |
| matching field, no producer | silent skip | ditto |

A third kind for the last two rows would make every unrelated input a finding. `DerivationDiagnostic`
carries **no** `selected_*` and **no** `operator` field, locked as field-set equality by
`test_a_diagnostic_records_no_selection_and_no_operator` — that is the mechanical form of 3.4.1.
Candidates are named at `<capabilityId>.<outputName>` granularity so one capability publishing two
matching outputs is reported as the ambiguity it is instead of collapsing to one id.

**3.4.4 mechanism.** A new gap kind `ambiguous_producer`, not a new `PlannerErrorType`:
`PlannerErrorType` is a closed `Literal`, so adding to it widens a contract three modules read,
while `DryRunGap.kind` is an open `string` in `view-model.ts:77` and
`runtime/composition/handoff.ts:34` already throws `COMPOSITION_PLAN_GAPS` on **any** non-empty
`gaps` array. So the gap is fail-closed at the composition boundary with **zero frontend change**.
Recorded in `compile_plan_v2`, not in the shared `_compute_gaps`, because v1 shares that function
and would otherwise report a gap next to the arbitrary node it still authors.

Refusing the node and recording the gap had to land together: `_compute_gaps` derives
`producible_fact_types` from **cards**, not nodes, so an ambiguous Fact Type has producers and
raises no `missing_capability` — skipping alone would have yielded a plan quietly missing a node,
worse than the defect.

| Mutation | Caught by |
| --- | --- |
| `needsReduction` never emitted | the positive-control and the real `mrpElementLines` test |
| field ambiguity resolved by declaration order | both trigger-(i) tests |
| producer ambiguity resolved by list order | trigger-(ii) + `renders_no_relation` |
| only the first producer candidate reported | trigger-(ii) test |
| diagnostics not sorted | the determinism test |
| `producers[0]` restored (node authored anyway) | `test_two_producers_of_one_fact_type_are_a_gap_not_a_list_index` |
| node refused but gap not recorded | same test |
| gap detail names only the first candidate | same test |
| `_index_producers_by_fact_type`'s sort removed | `test_the_ambiguous_producer_gap_is_independent_of_declaration_order` |

The last row is a correction, not a pass. My first ordering test compared **two runs of one
fixture**, which cannot distinguish "sorted" from "stably wrong" — a `reversed(producers)` mutation
passed it. Two findings followed: `_index_producers_by_fact_type` (`plan_compiler.py:353`) already
sorts by `capability_id`, so the `sorted()` I had added in the helper was a second authority for the
same ordering that **no** test could distinguish; it was removed. The test now compares two fixtures
differing **only** in declaration order, and fails when that single sort is removed.

**Untouched, named per invariant 10** — not "unrelated", not "known issues":

- `plan_compiler.py:168-172` carries the **identical** `producers[0]`. Left as is because v1 is on
  no production path (`orchestrator.py:1963` calls `compile_plan_v2_from_handoff` only; v1's
  `compile_dry_run` is referenced from tests alone), and because fixing it would require v1 to grow
  a gap kind it has no consumer for. It is a figure-(b) line.
- `_first_fact_field` (`plan_compiler_v2.py:507-521`) is a **second** silent-pick site — it returns
  the first output matching a Fact Type and `""` when none match. Task 3.4.4 does not name it, so it
  is reported here rather than fixed silently. Also a figure-(b) line.

## Task 3.5 — Expose the derived view

**Files**

- `agent/sap_nexus_agent/semantic_planning/derivation.py` — the logic (already created in 3.1)
- `scripts/derive-data-dependencies.py` (**new**) — thin printable wrapper
- a `runtime/` artifact

**Interfaces** — follow the established one-script-one-command pattern
(`scripts/validate-registry-contract.py`): hyphenated thin wrapper over the underscored module,
`main(argv) -> int`, errors to **stderr**, exit **1** on failure. **There are no argparse
subparsers anywhere in `agent/` or `scripts/` — do not introduce one.**

**Steps**

- [x] 3.5.1 Emit the `runtime/` artifact carrying **full provenance per edge and per diagnostic**.
- [x] 3.5.2 Add the thin wrapper matching the existing pattern exactly.
- [x] 3.5.3 Verify the **empty view is reported as empty**, exit 0 — not as an error. Emptiness is
  a legitimate state at 3.7.

**Result**

`scripts/derive-data-dependencies.py` writes `runtime/derived-data-dependencies.json`:

```
$ .venv/bin/python scripts/derive-data-dependencies.py
derived 0 edge(s), 0 relation(s), 0 diagnostic(s)
Derived data dependency view written: runtime/derived-data-dependencies.json
EXIT=0
```

The artifact carries `snapshotId` beside the view. A derived view is only meaningful against one
registry state, and the upstream nodes this batch enables are inputs to defect D4's approval
subject — so the view must say which registry it was derived from, not just what it found.

Artifact assembly (`build_artifact`) lives in the script, **not** in `derivation.py`. That module's
import set is asserted against an allowlist (`__future__`, `dataclasses`, `typing`, `.contracts`)
so nothing can smuggle an execution path into the deriver per invariant 2; importing the snapshot
builder there would widen the allowlist for a formatting concern.

Each edge dict leads with `relationId` (`derived.dependsOn.<consumer>~<producer>`) so a reader can
match a derived edge against an authored relation without recomputing the id — which is what task
3.6's validator does.

`agent/tests/test_derived_dependency_cli.py`, 11 tests. Two are about invariant 3 by *content*
rather than intent:

| Test | What it would catch |
| --- | --- |
| `test_the_cli_writes_under_runtime_and_never_into_registry_or_ontology` | sha256 of every file under `registry/` and `ontology/` compared before and after a run — a write that preserved mtime is still caught |
| `test_the_default_output_path_is_gitignored` | `git check-ignore` on the default output — a committed derived artifact invites diff review of a file no human authors |

Plus: exit 0 on the empty view (via subprocess, so the real exit code is asserted), snapshot
binding, edge key-set locked against `dataclasses.fields(DerivedDataEdge)` ∪ `{"relationId"}`,
diagnostic key-set lock, the summary names every candidate, `relations` present beside `edges` with
`origin == "derived"`, usage error → 2, `SourceLoadError` → 1 with no artifact written, and
byte-identical output across runs.

8 mutations applied and reverted; each was caught by the intended test.

## Task 3.6 — `origin: derived | manual` on relation edges

Design Decision 8. This is invariant 3's enforcement mechanism.

**Steps**

- [x] 3.6.1 Add the `origin: derived | manual` field to relation edges; require `justification` on
  `manual`.
- [x] 3.6.2 Add the validator rule **rejecting an `origin: manual` edge the deriver can compute** —
  this is what structurally prevents hand-writing derivable edges to make the file look non-empty.
- [x] 3.6.3 Verify a manual-without-justification edge fails, and a manual-but-derivable edge fails.
- [x] 3.6.4 Verify existing `dependsOn` / `precondition` authoring still validates (additive only).

**Result**

`origin` is **required**, not optional, and `schemas/capability-relation.schema.json` bumps
`version` 1 → 2 accordingly (`ontology/capability-relations.yaml` → `version: 2`,
`_validate_source_schemas`'s own `expected_version` → 2 — both must move together). Plan step 3.6.4
says "additive only", and I first designed `origin` as optional to honour that. The spec settles it:
*"Every relation SHALL declare `origin`"*. Optional `origin` would make an unlabelled edge
indistinguishable from a derived one and leave the derivability rule nothing to attach to, so the
version bump is the correct reading of "a document requires a key a reader must newly understand".
3.6.4 still holds in the sense that matters: both relation types remain hand-authorable.

`_validate_derivable_relations` in `validation.py` emits `RELATION_IS_DERIVABLE` when an authored
`dependsOn` names a pair `derive_data_dependencies` already computes. Two scope decisions:

- **Applied regardless of `origin`** — a deliberate superset of the spec, which names
  `origin: manual`. Enforcing only `manual` would leave a one-word escape: relabel the same
  hand-written edge `origin: derived` and the claim moves without the file changing. The deriver is
  the authority on what is derivable; the label cannot buy admission either way.
- **`precondition` out of scope** — the deriver computes data dependencies only. A precondition is
  not a data edge, so there is nothing to compare it against.

| Mutation | Caught by |
| --- | --- |
| M1 remove `origin` from `dependsOn.required` | `test_relation_without_origin_is_rejected` |
| M2 neuter `manualRequiresJustification` | `test_manual_relation_without_justification_is_rejected` |
| M3 scope the rule to `origin == "manual"` | `test_relabelling_a_derivable_relation_as_derived_does_not_admit_it` |
| M4 make `_validate_derivable_relations` a no-op | both derivable tests |
| M5 relations `expected_version` back to 1 | the source-schema matrix (fails at collection) |

**The rule fired on an existing fixture, and that was the right outcome.** `_fact_plan_inputs(
with_dependency=True)` in `test_semantic_planning_contract.py` hand-authored
`MM.Supply.Summarize dependsOn MM.Inventory.GetAvailability` for a consumer whose input declares
`bindingKind: fact` + `satisfiableByFactType` — i.e. exactly the derivable shape invariant 3
forbids authoring. Five PlanGraph tests depended on it. I did not weaken the rule or delete the
tests. The fixture now clones the producer under `with_dependency`, making the Fact Type ambiguous:
the deriver refuses to pick one and emits no edge, so a hand-asserted ordering becomes legitimate
and all five tests keep testing authored-dependency validation unchanged. First attempt — dropping
`satisfiableByFactType` — was reverted: plan validation then reported
`fact source cannot satisfy parameter Fact Type`, so it changed what the tests test.

**Snapshot id changed, with a stated cause.** `ontology/capability-relations.yaml` is one of the
five sources hashed by RegistrySnapshot v1, so bumping its `version` changes the snapshot id:
`sha256:9694cc4b…` → `sha256:51cbf410…`. 14 pinned occurrences in `evals/matcher_cases.yaml` were
updated. This is a document-version change to a hashed governed source, not a re-baselined
assertion.

Suite: `1463 passed, 1 skipped, 2 xfailed`.

## Task 3.7 — Run the derived view against the current three capabilities

**Steps**

- [x] 3.7.1 Run it and record the raw result verbatim.
- [x] 3.7.2 An **empty real view is the expected outcome at this point** — the fourth capability
  does not exist yet — **but only if 3.2's positive control is green**. Assert both facts together
  in one record. Empty + red positive control is a deriver defect, not a legitimate empty result.

**Result**

Raw run, verbatim:

```
$ .venv/bin/python scripts/derive-data-dependencies.py
derived 0 edge(s), 0 relation(s), 0 diagnostic(s)
Derived data dependency view written: runtime/derived-data-dependencies.json
EXIT=0
```

```json
{
  "artifact": "derived-data-dependencies",
  "version": 1,
  "snapshotId": "sha256:51cbf4100c9c1d8ca47b732f3a3d9eaad38596912868dc3125ac056cbf255a15",
  "edges": [],
  "diagnostics": [],
  "relations": []
}
```

Empty is correct: no input in `registry/capabilities.yaml` declares `satisfiableByFactType` yet.
`MM.Material.GetInfo` (task 5.2) is the first consumer that will.

`test_the_empty_real_view_is_only_valid_beside_a_green_positive_control` asserts both halves through
the same `derive_data_dependencies` call site. Each half was already pinned separately
(`test_the_real_registry_derives_no_edges_yet`, `test_a_declared_field_and_an_active_producer_
yield_one_edge`), but separate tests **cannot fail as a pair**: a deriver broken into always
returning nothing turns the control red and leaves the emptiness assertion green, so a reader
looking only at "the real view is empty" would read a defect as the expected state.

Verified by mutation: an early `return DerivedDependencyView(edges=(), diagnostics=())` in
`derive_data_dependencies` — the exact shape of "the deriver reports nothing" — leaves
`test_the_real_registry_derives_no_edges_yet` **green** and fails this test. Restored.

The control's own `needsReduction` diagnostic for `tags` is named rather than asserted absent, so a
control that grew a *new* unresolved input would not pass unnoticed.

---

# T5 skeleton — eval case identifiers

## Task 4.1 — Create five conversation-sequence eval case skeletons

Design Decision 9. These must exist before T3 5.2 can reference them via `evalLinkage`.

**Steps**

- [x] 4.1.1 Create the five skeletons with stable case ids:

| # | Case | Shape |
|---|---|---|
| 1 | *derived-not-asked* | omits **both** `unit` and `purchasing_group` |
| 2 | *user-supplied-wins* | supplies `unit` |
| 3 | *mixed* | supplies `unit`, omits `purchasing_group` |
| 4 | upstream empty/error | degrades to elicitation |
| 5 | upstream unreachable | emits `CapabilityGap`, run errors |

- [x] 4.1.2 Record why **1 and 2 are a mandatory pair**: without case 2, "the user's value won" and
  "we never derived anything" are indistinguishable, so a green case 1 **alone cannot demonstrate
  the feature**.
- [x] 4.1.3 Record that **case 3 is the only path exercising Defect 1 (task 5.5)** — it must be a
  test, not a hope.
- [x] 4.1.4 Verify the eval harness **discovers all five** and reports them as **pending with
  attribution** — not as passing (invariant 9).

**Result**

`evals/derived_parameter_cases.yaml`, five stable ids: `derived-not-asked`, `user-supplied-wins`,
`derived-and-user-supplied-mixed`, `upstream-empty-degrades-to-elicitation`,
`upstream-unreachable-emits-capability-gap`. Wired into
`scripts/verify-agent-callplan-evidence.sh` (and its pinned command list in
`test_semantic_planning_contract.py`) — a suite the project's own evidence gate does not run is not
discovered, it is just a file.

Verbatim harness output:

```
$ .venv/bin/python -m sap_nexus_agent.eval evals/derived_parameter_cases.yaml
SKIP (pending): derived-not-asked: Blocked on task 5.2 …
SKIP (pending): user-supplied-wins: Blocked on task 5.2 and on task 7.2 …
SKIP (pending): derived-and-user-supplied-mixed: Blocked on task 5.2 and on task 7.3 …
SKIP (pending): upstream-empty-degrades-to-elicitation: Blocked on task 5.2 and on task 7.4 …
SKIP (pending): upstream-unreachable-emits-capability-gap: Blocked on task 5.2 and on task 7.5 …
Eval passed: 0/0
EXIT=0
```

**A trap closed while writing these.** The natural way to author a skeleton is to write the target
assertions into `expected` — `parameterProvenance`, `dataEdgeCount`, and so on. But
`_assert_matcher_*` ignores any key it does not know, so once `pending` came off, such a case would
go **green while asserting nothing**. Every `expected` block therefore uses only keys the harness
reads today, and each case's `todo` states the not-yet-assertable expectations in prose.
`HARNESS_ASSERTED_KEYS` in `test_eval_runner.py` locks this: an unknown key fails the test, so
turning a case real forces adding the assertion rather than deleting `pending`.

4.1.2 and 4.1.3 are recorded in the case files themselves, not only here — the reason case 2 exists
lives in case 2's `todo`, where anyone tempted to delete it will read it. Case 3's `todo` states
that a case where *all* parameters are derived, or none are, cannot produce Defect 1's second edge
at all, so case 3 is the only path that exercises it.

Case 5's `todo` also records a harness gap of its own: today's `FakeGatewayClient` answers every
capability identically, so "one node of the plan is unreachable" is not yet constructible. Task 7.5
owns that.

| Mutation | Caught by |
| --- | --- |
| M7 drop `pending` from case 1 | `..._exist_and_are_pending`, `..._reports_zeros_not_passing` |
| M8 add `expected.parameterProvenance` (a key the harness ignores) | `..._exist_and_are_pending` |
| M9 rename `derived-and-user-supplied-mixed` → `mixed` | `..._exist_and_are_pending` |
| M10 replace a `todo` with `"TODO"` | `..._exist_and_are_pending` |

**Known limitation, stated rather than papered over:** the CLI prints `Eval passed: 0/0` because
`EvalSummary` does not carry a skipped count. The numbers are accurate (0 passed, 0 total, 0 failed)
and the five `SKIP` lines with attribution precede them, but the summary line alone does not say
five cases are waiting. `test_derived_parameter_eval_reports_zeros_not_passing` pins the zeros so
this can never drift into `5/5` without the assertions existing. Extending `EvalSummary` with a
skipped count is not in this batch's scope.

---

# T3 — Register `MM.Material.GetInfo` and author the first derived edge

## Task 5.1 — Transcribe real SAP metadata

**Steps**

- [ ] 5.1.1 Execute `BAPI_MATERIAL_GET_DETAIL` live in SE37.
- [ ] 5.1.2 Transcribe the **real** import/export parameter names, structure names, and field names
  for `MARA-MEINS` (base unit, client level) and `MARC-EKGRP` (purchasing group, material plant
  view). Use SE11 where table structure is in doubt.
- [ ] 5.1.3 Paste the verification output into the report.
- [ ] 5.1.4 **Stop and ask the user if the live metadata contradicts the registry expectation.**
  Do not "adjust" the registry to match a guess.

**BLOCKED (2026-08-25) — stale SAP credential, not a design problem.**

Everything needed to run 5.1 without SAP GUI is in place and proven, except the password:

- Tooling: `services/gateway/jco/lib/sapjco3.jar` + `lib/linux/libsapjco3.so` + JDK 17 all present.
  A throwaway read-only metadata probe was written to `/tmp/sapmeta/MetaProbe.java` (deliberately
  outside the repo — it adds zero project lines) and compiles clean. It reads
  `BAPI_MATERIAL_GET_DETAIL`'s interface from the JCo repository and `MARA-MEINS` / `MARC-EKGRP`
  from `DDIF_FIELDINFO_GET`, which is the non-interactive equivalent of SE37 + SE11 and is still a
  *real* execution, not memory.
- Reachability: TCP 3310 / 3210 / 8000 / 8010 all OPEN (`SAP_SYSNR=10`, so 3310 is the RFC
  dispatcher — an earlier 3300 probe was refused because of my own wrong port derivation).
- Logon: the probe reached the SAP kernel and was rejected by the application server —
  `JCO_ERROR_LOGON_FAILURE (103): Name or password is incorrect (repeat logon)`, raised by
  `system [SAT|NEVSSAS4HX01|10]` for the `.env` user. Host / sysnr / client / user are therefore
  all resolving correctly; only the password is wrong or expired.
- **Exactly one logon attempt was made and then stopped deliberately.** SAP locks a user after a
  small number of failed logons, so no retry and no credential guessing happened. No credential
  value was printed to any log, file, or this document.

5.2's executor binding needs the real RFC import/export parameter and structure names, so 5.2
onward genuinely cannot proceed — writing the binding from remembered BAPI shape is exactly what
`design.md:467-470` forbids. Once the password in `.env` is refreshed, re-run:

```bash
cd /tmp/sapmeta && . ./loadenv.sh /home/shrek/projects/GitHub_Projects/sap-nexus-agent/.env \
  && java -Djava.library.path=/home/shrek/projects/GitHub_Projects/sap-nexus-agent/services/gateway/jco/lib/linux \
     -cp ".:/home/shrek/projects/GitHub_Projects/sap-nexus-agent/services/gateway/jco/lib/sapjco3.jar" MetaProbe
```

Note for whoever refreshes it: `.env`'s `SAP_PASSWORD` value contains a character that plain
`set -a; . .env` mangles into an empty string — `loadenv.sh` exists because of that, and any other
consumer that sources `.env` with the shell has the same latent bug.

## Task 5.2 — Register the capability by declaration only

**This is figure (a). Target: zero Python lines.**

**Files**

- `registry/capabilities.yaml` — new `MM.Material.GetInfo` entry
- `ontology/fact-types.yaml` — new `sapnexus:MaterialInfoFact`

**Interfaces** — the four outputs (per **C3**, all sharing one `factTypeRef`, distinct semantic
types, **zero new semantic types**):

| output `name` | `semanticType` | `factTypeRef` | `evidenceRole` |
|---|---|---|---|
| `material` | `sapnexus:MaterialNumber` | `sapnexus:MaterialInfoFact` | `primaryFact` |
| `plant` | `sapnexus:Plant` | `sapnexus:MaterialInfoFact` | `primaryFact` |
| `baseUnitOfMeasure` | `sapnexus:UnitOfMeasure` | `sapnexus:MaterialInfoFact` | `primaryFact` |
| `purchasingGroup` | `sapnexus:PurchasingGroup` | `sapnexus:MaterialInfoFact` | `primaryFact` |

Governance — real key paths are top-level `kind` plus `governance.sideEffect` /
`governance.requiresApproval` / `governance.approvalPolicy`:

```yaml
    kind: Function
    governance:
      sideEffect: none
      requiresApproval: false
      approvalPolicy: not_required
      dataClassification: <per existing READ capability>
      auditRequired: <per existing READ capability>
```

`kind: Function` is **the precondition for 5.4's auto-pull being safe** — verified:
`capability.schema.json` `$defs/capability/allOf[0]` genuinely binds it, and it cannot pass
vacuously because `$defs/governance.required` contains all three keys:

```json
{"if": {"properties": {"kind": {"const": "Function"}}, "required": ["kind"]},
 "then": {"properties": {"governance": {"properties": {
   "sideEffect": {"const": "none"},
   "requiresApproval": {"const": false},
   "approvalPolicy": {"const": "not_required"}}}}}}
```

The `narrative` block, modelled on the Inventory template (Decision 6 — deliberately an
**unrecognised template id** and `detailFormatter: none`, to prove the narrator generalisation
holds without bespoke code):

```yaml
    narrative:
      factShape: single-value
      promptTemplate: material-info
      fallbackTemplate: material-info
      fieldMapping:
        title: "物料 {material} 在工厂 {plant}"
        primary: "{baseUnitOfMeasure} / {purchasingGroup}"
      detailFormatter: none
```

**Steps**

- [ ] 5.2.1 Declare `sapnexus:MaterialInfoFact` in `ontology/fact-types.yaml` with the four
  `cardinality: one` fields (matching the output names 1:1 per **C2** and **C5**) plus provenance
  fields `asOf` and `snapshotId` (Decision 11 — these are defect **D4**'s inputs; do not omit them).
- [ ] 5.2.2 Add the capability entry: `kind: Function`, governance as above, executor binding,
  inputs (`material`, `plant`), the four outputs, `evalLinkage` pointing at 4.1's case ids, and the
  `narrative` block.
- [ ] 5.2.2a **The deferred 1.1 edit (correction C6)**, in the *same* commit as 5.2.1 and 5.2.2 so
  the registry is never invalid: add `satisfiableByFactType: sapnexus:MaterialInfoFact` to
  `MM.PR.CreateDraft`'s `unit` and `purchasing_group` inputs, leaving both at
  `bindingKind: identifier` with matchers and priorities untouched. Verify the `extraction`
  deprecation warning count is still exactly 15 and neither input's parsed `binding.sources[]`
  changed.
- [ ] 5.2.3 Run `.venv/bin/python scripts/validate-registry-contract.py registry/capabilities.yaml`
  — must pass.
- [ ] 5.2.4 **Run `git diff --stat` scoped to `*.py` for this step and confirm it is empty.** This
  is figure (a) = 0. If it is non-zero, that is invariant 6 failing: stop and report the reason
  rather than absorbing the lines.

## Task 5.3 — Confirm the derived view now contains the two candidate edges

**Steps**

- [ ] 5.3.1 Run `scripts/derive-data-dependencies.py`. Expect **two** edges:

```
sapnexus:MaterialInfoFact.baseUnitOfMeasure → MM.PR.CreateDraft.unit
sapnexus:MaterialInfoFact.purchasingGroup   → MM.PR.CreateDraft.purchasing_group
```

- [ ] 5.3.2 Confirm they appear as **derived output**, not as authored relations in
  `capability-relations.yaml` (invariant 3). Assert that file is unchanged.
- [ ] 5.3.3 **Stop and ask the user if either edge comes out `needsReduction` or `ambiguous`.**

## Task 5.4 — Producer auto-pull as a closure over `desired_fact_types`

Design Decision 16, ruling ③ (*规划器自动拉入*). **This is the feature's core.**

**Files**

- `agent/sap_nexus_agent/planner/goal_spec.py` — `build_goal_spec(handoff, cards) -> GoalSpec` at `:84`

**Interfaces** — `GoalSpec` is a frozen dataclass with `desired_fact_types: tuple[str, ...]`.
Blast radius: **17** callers of `GoalSpec`, **11** of `build_goal_spec`.

```python
def _auto_pulled_fact_types(
    cards: Sequence[CapabilityCard],
    bound_parameters: Mapping[str, object],
    desired: tuple[str, ...],
) -> tuple[str, ...]:
    """Close `desired` under unbound required inputs' satisfiableByFactType.

    Restricted to producers whose capability is `kind: Function`: the schema binds
    Function => sideEffect none + requiresApproval false, so this restriction
    structurally cannot drag in a WRITE or bypass Human Approval (invariant 5).
    """
```

**Why the closure lives in `build_goal_spec`, not in `_build_plan_graph_v2`:** the `GoalSpec`
then records *why* the extra node exists, so the extra read is **auditable** rather than a silent
planner side effect.

**Why the node-creation loop needs zero changes:** `plan_compiler_v2.py:213-233` already builds
one node per desired Fact Type. Adding to `desired_fact_types` is sufficient.

**Steps**

- [x] 5.4.1 Four failing tests: (a) the closure adds `sapnexus:MaterialInfoFact` when `unit` is
  unbound; (b) it **refuses to pull an `Action` producer**; (c) neither value is elicited when the
  upstream value is available; (d) the resolved value carries `provenance=capability_derived`.
- [x] 5.4.2 Implement the closure in `build_goal_spec`. Restrict to `kind: Function` producers.
- [x] 5.4.3 Assert `plan_compiler_v2.py:213-233` is **unchanged** by this task.
- [ ] 5.4.4 Confirm the two PR inputs stay `bindingKind: identifier` declaring
  `satisfiableByFactType` only — **no `capabilityOutput` source is added** (ruling ④). Derivation
  is computed at runtime by semantic-type equality, so **nothing restates the derived field** and
  field-level drift is structurally impossible.
- [x] 5.4.5 Attribute to **figure (b), "producer auto-pull (Decision 16)"** — this is feature work
  enabled by the registry, but the lines are Python and must be counted honestly, not hidden in (a).

### Result (2026-08-25) — executed out of order; 5.4.1(d) and 5.4.4 split out

`_auto_pulled_fact_types(cards, matched_cards, bound_parameters, desired)` +
`_is_auto_pullable(card)` in `goal_spec.py`; `build_goal_spec` extends `desired` with the closure.
**95 Python lines, all in `goal_spec.py`.** `git diff --stat` on `plan_compiler_v2.py` is **empty**
for this task (5.4.3 ✓) — adding to `desired_fact_types` was indeed sufficient.

**The closure is inert until the registry declares the coupling.** `grep satisfiableByFactType
registry/capabilities.yaml` returns **nothing** today, so no existing plan changes and the full
suite needed no adjustment. The behaviour switches on when 5.2.2a adds `satisfiableByFactType` to
`MM.PR.CreateDraft`'s two inputs — i.e. by declaration, which is invariant 6's shape.

**Deviation from the written interface, stated rather than hidden.** The plan's signature restricts
to `kind: Function`. `CapabilityCard` does not project `kind` (it projects the two governance
fields), and the registry schema binds `kind: Function` ⇒ `sideEffect: none` +
`requiresApproval: false`. `_is_auto_pullable` therefore checks **both governance fields** — the
fields that actually gate execution — instead of the label that implies them. This is strictly
stronger: a capability mis-declared as `Function` while carrying a side effect is still refused.
Projecting `kind` onto the card would have been extra Python for a weaker check.

**It is a real closure, not a single hop.** A pulled producer's own unbound required derivable
inputs are closed too, via a worklist. Termination is by construction (each Fact Type is added at
most once), proven by a registry-cycle fixture rather than argued.

**5.4.1(d) is split out and NOT claimed here.** `provenance=capability_derived` is not a value the
slot vocabulary admits: `read_context._SLOT_PROVENANCES` is
`{EXPLICIT, CONFIRMED, INHERITED, MODEL_CANDIDATE, INHERITED_LEGACY}`. Adding a sixth token touches
`read_context.py`, `context_reducer.py`, `context_decision_gate.py`, `eval.py` and the frontend
allow-lists — none of which are in 5.4's declared file list. Implementing it inside 5.4 would have
silently widened 5.4's blast radius from 1 file to 6. It belongs with **task 5.9**, which owns the
provenance token and both surfaces, and is listed in 8.4 as an open item with that attribution.
5.4.1(c) is covered here at the level 5.4 can observe — *the producer is never pulled*, so the extra
SAP read does not happen — which is the stronger half of "not elicited".

**5.4.4 stays open** because it asserts a property of `registry/capabilities.yaml` after 5.2.2a,
which has not been written yet. Not a defect, a dependency.

| Check | Result |
| --- | --- |
| `pytest agent/tests/test_planner_capability_card.py -q` | 44 passed (was 37) |
| `pytest agent/tests -q` | 1511 passed, 1 skipped, 2 xfailed |
| Failing-test-first | (a) and the transitive case failed with `('sapnexus:PrCreateFact',)`; the four negative tests passed vacuously before the feature and are proven non-vacuous by M24–M26 below |
| `git diff --stat -- plan_compiler_v2.py` | empty (5.4.3 ✓) |
| Mutation M24 (drop `_is_auto_pullable`) | 2 FAILED — both invariant-5 refusal tests; restored, green |
| Mutation M25 (drop the `bound_parameters` skip) | 1 FAILED — 用户明说优先; restored, green |
| Mutation M26 (drop the `required` check) | 1 FAILED — optional input; restored, green |
| Mutation M27 (drop the already-added guard) | **non-termination** — killed at 25 s. The cycle fixture is the catch: the guard is what makes the closure terminate, not a redundancy. Restored, green |

Attribution: **figure (b) — "producer auto-pull (Decision 16)", 95 lines in `goal_spec.py`.**


## Task 5.4a — The mandatory disclosure that pays for the auto-pull

**Auto-pull silently executes an extra SAP read on the user's behalf. Disclosure is the price.**

**Steps**

- [ ] 5.4a.1 The **narration** states that an extra read occurred.
- [ ] 5.4a.2 The **approval card** marks a derived value as **derived**, not user-entered.
- [ ] 5.4a.3 Verify both surfaces show the disclosure.
- [ ] 5.4a.4 Verify **no approval step is skipped or shortened** because a value was derived
  (invariant 5). A derived parameter goes through byte-identical approval.

## Task 5.5 — Fix the duplicate-`data`-edge defect

Design Decision 5, **defect 1**. **On the critical path** — it blocks T3's headline edge, so it is
not a pre-existing item to tally away.

**The failure**: user supplies `unit`, omits `purchasing_group` → one
`(producer → consumer, factType)` pair yields **two** `factField` bindings.

**Interfaces** — per **C4**, the validator already tolerates N sources per edge because
`expected_data[key]` is a **list**:

```python
483	    expected_data: dict[tuple[str, str, str], list[str]] = defaultdict(list)
...
494	            expected_data[key].append(
495	                f"/nodes/{node_position}/parameterBindings/{binding_index}/source"
496	            )
```

but `:528-545` rejects duplicate **edges**:

```python
532	        for edge_index in edge_indexes[1:]:
533	            issues.append(
534	                ValidationIssue(f"/edges/{edge_index}", "EDGE_INCONSISTENT",
535	                                "duplicate semantic data edge"))
```

and `plan_compiler_v2.py:277` appends one edge **per binding**:

```python
277	            data_edges.append(
278	                {
279	                    "edgeId": f"edge.data.{edge_counter}",
280	                    "kind": "data",
281	                    "fromNodeId": producer_node_id,
282	                    "toNodeId": node["nodeId"],
283	                    "factTypeId": fact_type,
284	                }
285	            )
```

**So `validation.py` needs zero changes.** Only the compiler moves.

**Steps**

- [x] 5.5.1 Failing test: two `factField` bindings on one pair → exactly **one** `data` edge with
  **two** sources.
- [x] 5.5.2 Change `plan_compiler_v2.py:277` to emit one edge keyed `(producer, consumer, factType)`
  carrying both sources.
- [x] 5.5.3 Verify existing **single-binding** plans still emit exactly one edge (regression guard).
- [x] 5.5.4 Assert `git diff` on `validation.py` is empty for this task.
- [x] 5.5.5 Attribute to **figure (b), "defect 1: duplicate data edge"**.

**Result (5.5).** Done **out of plan order**: 5.1 is blocked on a stale SAP credential (see above) and
5.5 does not depend on the live metadata, so it was taken next rather than idling.

Test: `test_two_derivable_inputs_share_one_data_edge` with the new
`_sources_with_two_derivable_inputs()` fixture — a consumer whose two required inputs both declare
`satisfiableByFactType: sapnexus:InventoryAvailabilityFact`, neither supplied. This is exactly T3's
headline shape (user states the material, omits both `unit` and `purchasing_group`).

Reproduced before fixing: `assert 2 == 1`, both edges `edge.data.0` / `edge.data.1` carrying the
same `(node.MM.Inventory.GetAvailability → node.Test.Consumer.UseTwoFields,
sapnexus:InventoryAvailabilityFact)` triple. The test also asserts no `invalid_plan_graph` flag,
which is the half that matters: the duplicate made `validate_plan_graph_v2` emit
`EDGE_INCONSISTENT` "duplicate semantic data edge", so the plan T3 needs could not compile at all.

Fix: `data_edge_keys: set[tuple[str, str, str]]` guards the append. The **binding** is still
authored for every derived parameter — only the edge is deduplicated — so `expected_data[key]`
legitimately collects two source paths against one edge, which is the list shape `validation.py`
already had.

| Check | Result |
|---|---|
| `pytest agent/tests/test_planner_plan_compiler_v2.py` | 26 passed (was 25) |
| `pytest agent/tests -q` | **1467 passed, 1 skipped, 2 xfailed** |
| 5.5.3 single-binding regression | `test_unsupplied_derivable_identifier_is_authored_as_fact_field`, `test_compile_plan_v2_authors_fact_field_source_and_data_edge`, `test_fact_field_fixture_produces_data_edge_and_stable` all green — still exactly one edge |
| 5.5.4 `git diff --stat -- …/validation.py` | empty ✅ |
| Mutation M11 (`if data_edge_key in data_edge_keys` → `if False`) | new test FAILED (`assert 2 == 1`); restored, green |

Attribution: **figure (b) — "defect 1: duplicate data edge"**.

## Task 5.6 — Select the producer field by semantic type

**Interfaces** — replace `_first_fact_field` (`plan_compiler_v2.py:497-511`):

```python
497	def _first_fact_field(producer_raw: Mapping[str, Any], fact_type: str) -> str:
...
508	    for output in producer_raw.get("outputs", []):
509	        if output.get("factTypeRef") == fact_type and output.get("name"):
510	            return output["name"]
511	    return ""
```

with semantic-type-aware selection. Per **C2**, the returned name must be a producer **output
name** (that is what `validation.py:459-464` checks), and per **C3** several outputs share one
`factTypeRef`, so the discriminator is `semanticType`:

```python
def _fact_field_for_input(
    producer_raw: Mapping[str, Any], fact_type: str, semantic_type: str
) -> str:
    """Among producer outputs with matching factTypeRef, pick the one whose
    semanticType equals the consumer input's. Returns "" when none matches."""
    for output in producer_raw.get("outputs", []):
        if (
            output.get("factTypeRef") == fact_type
            and output.get("semanticType") == semantic_type
            and output.get("name")
        ):
            return output["name"]
    return ""
```

**Zero validator change** — the emitted `field` is still an output name.

**Steps**

- [x] 5.6.1 Failing test: the two PR inputs receive **different** fields
  (`unit` → `baseUnitOfMeasure`, `purchasing_group` → `purchasingGroup`).
- [x] 5.6.2 Implement the replacement and update its call site.
- [x] 5.6.3 Verify the emitted plan's `topologicalOrder` places `MM.Material.GetInfo` **before**
  `MM.PR.CreateDraft`.
- [x] 5.6.4 Attribute to **figure (b), "defect: `_first_fact_field` ignores semantic type"**.

### Result (2026-08-25) — executed out of order, ahead of 5.1/5.2

Task 5.1 is BLOCKED (see its note), so `MM.Material.GetInfo` is not registered yet and 5.6.1/5.6.3
cannot name the real PR inputs. The defect and the fix are entirely independent of the live SAP
metadata, so 5.6 was executed against a **real-registry producer** instead of a hypothetical one:
`MM.Inventory.GetAvailability` already has exactly the C3 shape — two outputs sharing
`factTypeRef: sapnexus:InventoryAvailabilityFact` with distinct `semanticType`s
(`availableQuantity`/`sapnexus:AvailableQuantity`, `mrpElementLines`/`sapnexus:MrpElementLine`).
**No semantic type was invented**; only the consumer side is a fixture.

Two follow-ups remain bound to 5.2 and are listed in 8.4, not closed here:

1. 5.6.1's real-registry form — assert `unit` → `baseUnitOfMeasure` and
   `purchasing_group` → `purchasingGroup` on the actual `MM.PR.CreateDraft`.
2. 5.6.3's real-registry form — assert `MM.Material.GetInfo` precedes `MM.PR.CreateDraft`.

`_first_fact_field` → `_fact_field_for_input(producer_raw, fact_type, semantic_type, binding_kind)`
(`plan_compiler_v2.py`). The discriminator is `semanticType`, but it is applied **per
`bindingKind` tier**, because the same field means different things in the two tiers (C8):

| `bindingKind` | its `semanticType` is | rule | no match |
| --- | --- | --- | --- |
| `identifier` | tier ① value type | strict `semanticType` equality | `""` → `FACT_TYPE_MISMATCH` |
| `fact` | tier ② Fact Type id | nothing to discriminate → first matching output | `""` |

Keying the rule on `semanticType` **without** the tier split would have broken every whole-Fact
consumer — mutation M21 proves that, and it breaks a *pre-existing* test, not only a new one.

`git diff --stat` on `validation.py` / `validation_v2.py` is **empty** — the emitted `field` is
still a producer output name, so "zero validator change" holds as designed.

| Check | Result |
| --- | --- |
| `pytest agent/tests/test_planner_plan_compiler_v2.py -q` | 30 passed (26 before 5.5, 29 before 5.6.3's lock) |
| `pytest agent/tests -q` | 1504 passed, 1 skipped, 2 xfailed |
| Failing-test-first | `lines` bound `availableQuantity` — a wrong **value**, not a validator error |
| Mutation M20 (identifier branch reverts to first-match) | 2 FAILED (the typed-fields test + the no-match test); restored, green |
| Mutation M21 (`fact` branch loses its fallback) | 2 FAILED, one of them **pre-existing** (`test_compile_plan_v2_authors_fact_field_source_and_data_edge`); restored, green |
| Mutation M22 (`_topological_order` skips `data` edges) | 2 FAILED; restored, green — **but see the vacuity finding below** |

**Vacuity found and fixed in my own test.** M22's first run passed 30/30. Cause: the fixture
consumer was `Test.Consumer.UseTypedFields`, and `node.MM.Inventory...` sorts before
`node.Test.Consumer...`, so the deterministic id tie-break produced the correct order by
coincidence and the assertion never exercised the edge. Renamed the fixture consumer to
`MM.Consumer.UseTypedFields` so its node id sorts **before** the producer's; the test now asserts
that inequality explicitly, so the ordering can only come from following the `data` edge. M22 then
failed as intended.

**Observation for figure (b) — not fixed, not filed as a "known issue".** Probe mutation M23
replaced the whole sort with `return sorted(node_ids)` and ran the full suite: exactly **two** of
1504 tests failed, and both are the ones added by this task
(`test_two_typed_inputs_bind_different_producer_fields`,
`test_the_data_edge_orders_the_producer_first_regardless_of_input_order`). Every pre-existing
ordering assertion in `agent/tests/` is therefore satisfied by plain alphabetical node-id order and
never discriminates the topological sort. Attribution: pre-existing test weakness in the Task 9
dependency-edge tests, not introduced by batch T. Left untouched because the brief forbids editing
existing tests without instruction; recorded here and in 8.4 so it is a named item with a named
cause, not a category.

Attribution: **figure (b) — "defect: `_first_fact_field` ignores semantic type"**.

## Task 5.7 — Make `narrate_single_value`'s guard `fieldMapping`-driven

Design Decision 6, **defect 2**.

**Steps**

- [x] 5.7.1 Failing test: a `single-value` narrative whose `fieldMapping` does not mention the
  inventory value label still narrates.
- [x] 5.7.2 Make the required-field guard `fieldMapping`-driven; stop hardcoding the inventory
  value label.
- [x] 5.7.3 Verify the **inventory narration is unchanged** (regression guard — the existing
  `narrative` block is the reference):

```yaml
      factShape: single-value
      promptTemplate: inventory-md04
      fallbackTemplate: inventory-md04
      fieldMapping:
        title: "{material} 在工厂 {plant}"
        primary: "{value} {unit}"
        detailRows: mrpElementLines
      detailFormatter: mrp-table
```

- [x] 5.7.4 Verify a template referencing a **missing** field still raises `NarrativeGuardError` —
  the guard must get more general, not weaker (invariant 9).
- [x] 5.7.5 Attribute to **figure (b), "defect 2: hardcoded inventory value label"**.

**Result (5.7).** Also taken out of plan order — independent of 5.1's blocked metadata.

`narrate_single_value` demanded `material` / `plant` / `value` / `unit` from every `single-value`
fact regardless of what the declaration asked for, so a `single-value` capability narrating anything
other than a quantity could not use the generic framework at all.

Three pieces, all in `agent/sap_nexus_agent/narrator.py`:

- `_fact_field_values(fact)` — **one** lookup: the leading evidence record's keys, overlaid by the
  fact's fixed fields. The guard and `_resolve_one_var` both read it, which is what makes the guard
  `fieldMapping`-driven rather than fact-field-driven: a placeholder is checkable exactly when it is
  renderable.
- `_declared_placeholders(config)` — the `{name}`s the `fieldMapping` actually references, in
  first-appearance order so guard messages are deterministic. A bare expression such as
  `detailRows: mrpElementLines` is not a placeholder, so it is never required.
- The guard: `required = declared or _UNDECLARED_SINGLE_VALUE_FIELDS`. Callers with **no**
  `narrative` block have nothing to read, so they keep the inventory-shaped set they always had —
  the generalisation does not loosen them.

`_resolve_one_var` moved from `str.format(material=…, plant=…, value=…, unit=…)` to
`format_map(_fact_field_values(fact))`. Before the change `{sourceField}` raised a raw `KeyError`
from inside the narrator; now an unresolvable placeholder is refused by the guard with the field
name in the message.

**5.7.3 is enforced, not asserted by eye.** `test_the_real_inventory_declaration_still_requires_exactly_the_old_four`
reads `registry/capabilities.yaml` and derives the required set from the live
`MM.Inventory.GetAvailability` declaration, so it equals exactly the four fields the code used to
hardcode. Editing the declaration to demand less now fails a test instead of quietly loosening a
guard.

| Check | Result |
|---|---|
| `pytest agent/tests/test_reasoning_narrator.py` | 59 passed (was 53) |
| `pytest agent/tests -q` | **1473 passed, 1 skipped, 2 xfailed** |
| M12 `required = ()` | 4 FAILED, incl. the **pre-existing** `test_narrator_rejects_missing_quantity` |
| M13 `required = _UNDECLARED_SINGLE_VALUE_FIELDS` (back to hardcoded) | 2 FAILED: `…omits_the_value_label`, `…placeholder_nothing_can_resolve` |
| M15 evidence keys dropped from the lookup | 1 FAILED: `…resolves_a_placeholder_from_evidence` |
| M16 real registry stops naming `{value}` | 2 FAILED, incl. the pre-existing `test_narrator_rejects_missing_quantity` |

All four restored; `git diff --stat` on `registry/capabilities.yaml` empty afterwards.

Attribution: **figure (b) — "defect 2: hardcoded inventory value label"**.

**Finding carried forward to 5.2 / 5.9, not a known issue.** `_fact_field_values` resolves
placeholders from the leading **evidence** record, but the `ReasoningFact` builders are still
per-capability (`build_availability_fact` / `build_purchase_order_facts` /
`build_pr_create_fact`). So 5.2's declared `primary: "{baseUnitOfMeasure} / {purchasingGroup}"`
resolves only if whatever produces the `MaterialInfoFact` puts those keys in evidence. This is
exactly what 5.2.4's "`git diff --stat` on `*.py` is empty" measures — if a new Python fact builder
turns out to be required, that is figure (a) ≠ 0 and must be reported as such, not absorbed.

## Task 5.8 — Audit: no synchronous data fetch under `agent/`

**Invariant 2's explicit checkpoint.**

**Steps**

- [x] 5.8.1 Inspect the entire intent path for any Gateway / RFC / OData call. Grep for the
  Gateway client, `requests`, `httpx`, `urllib`, and any execute entry point under `agent/`.
- [x] 5.8.2 Add the eval assertion that **intent parsing performs zero execute calls**.
- [x] 5.8.3 Record the audit result explicitly. If anything is found, **roll back and redo** — this
  is not a fixable finding, it is a design violation.

**Result (5.8). Audit outcome: clean. Nothing found, so nothing was rolled back.**

A grep is a snapshot, so the audit was written as `agent/tests/test_intent_path_no_data_fetch.py`
(27 tests) — three independent locks:

1. **Transitive static audit.** For each of the 24 intent-path modules, a *fresh interpreter*
   imports it and reports which of `sap_nexus_agent.gateway_client` / `requests` / `httpx` /
   `urllib.request` / `http.client` ended up in `sys.modules`. A grep sees one file; an import sees
   the whole closure. All 24 clean.
2. **File-level lock.** Exactly three modules import `gateway_client`: `cli.py`,
   `orchestrator.py`, `workbench_output.py` — the runtime entry points. The set is asserted for
   equality in both directions, so a new importer fails a test rather than merging silently.
   `eval.py` is deliberately absent: it drives the runtime through its own `FakeGatewayClient` and
   never imports the real one.
3. **Behavioural lock at the point of temptation.**
   `test_authoring_a_derived_parameter_performs_zero_gateway_calls` compiles a plan whose consumer
   parameter is available *only* from an upstream capability's output — the exact case where "just
   look the unit up first" would be written. It asserts the parameter really was derived (a
   `factField` source **and** a `data` edge exist, so the zero-call assertion cannot be vacuous),
   that both call lists on a recording Gateway double are empty, and that no `GatewayClient` was
   constructed.

Manual findings recorded for completeness:

| Grep | Finding |
|---|---|
| HTTP libraries under `agent/sap_nexus_agent/` | Only `gateway_client.py` (`urllib.request` / `urllib.parse`). Nothing else. |
| `rfcName` outside the runtime entry points | Every occurrence is **rejection** logic — `intent.py` / `capability_selector.py` / `discard.py` detect a technical override and refuse it (`UNSUPPORTED_RFC_NAME`), and `llm_intent.py` instructs the model never to emit one. `reasoning_fact.py` only reads `rfcName` back off an `ExecutionResult` for provenance. **No RFC name is ever generated.** |
| `socket` / `subprocess` / `os.system` / `Popen` under `agent/sap_nexus_agent/` | None. |

Positive control: `test_the_probe_itself_is_not_vacuous` asserts the probe *does* report
`gateway_client` for `sap_nexus_agent.orchestrator`, which legitimately reaches the Gateway. Without
it the 24 green results would prove nothing.

| Check | Result |
|---|---|
| `pytest agent/tests/test_intent_path_no_data_fetch.py` | 27 passed |
| `pytest agent/tests -q` | **1500 passed, 1 skipped, 2 xfailed** |
| M17 `recall.py` imports `gateway_client` | 2 FAILED (the `recall` probe + the file-level lock) |
| M18 `derivation.py` imports `gateway_client` | caught — every module that transitively imports `derivation` failed |
| M19 `derivation.py` adds `import urllib.request` | **16 FAILED** — the clean demonstration that detection is transitive, not per-file |

All three mutations restored; `git diff --stat` empty on both mutated files afterwards.

Note on M17/M18: both fail with an *import error* rather than a forbidden-module report, because
`gateway_client` imports back into the intent path and the cycle breaks the import. The audit still
fails closed, and M19 is the mutation that demonstrates the detection itself.

## Task 5.9 — Carry `provenance=capability_derived` through to both surfaces

**Steps**

- [ ] 5.9.1 Carry `provenance=capability_derived` **and its source node** through projection into
  the narrative and the approval payload.
- [ ] 5.9.2 Make the two frontend allow-list edits.
- [ ] 5.9.3 Verify the derived value is **traceable to its producing node** in both surfaces — not
  merely labelled "derived" with no provenance chain.

## Task 5.10 — Live READ smoke against real SAP

**Steps**

- [ ] 5.10.1 Run the live READ smoke; retain `traces.jsonl` evidence.
- [ ] 5.10.2 Verify `BAPI_TRANSACTION_COMMIT` and `BAPI_TRANSACTION_ROLLBACK` are **absent** from
  the trace (READ capability, `sideEffect: none`).
- [ ] 5.10.3 Verify fail-closed executors (`CDS_ADT` / `REST_JSON` / `SQL_READ`) **still refuse**
  (invariant 4).
- [ ] 5.10.4 Confirm the trace carries **no credential / token / connection string**, and that
  supplier/person/contact fields follow existing Gateway masking. Material number and plant code
  may stay (business identifiers). "It's only a log" is not a pass.
- [ ] 5.10.5 Troubleshoot via SE37 / SLG1, and `/IWFND/ERROR_LOG` for the OData path.

## Task 5.11 — Confirm approval semantics are byte-identical

**Steps**

- [ ] 5.11.1 Confirm **no change** to subject construction, subject hash, or anti-replay for the
  WRITE capability. Evidence: `git diff` on the approval modules and on
  `test_approval.py` / `test_orchestrator.py` subject-hash assertions is empty.
- [ ] 5.11.2 Flag in the report that the new upstream nodes' `asOf` / `snapshotId` are **inputs to
  the deferred defect D4** (joint hash of WRITE parameters + upstream Fact `asOf` + snapshot id).
  Name it as a **coupling point**, not as a known issue (invariant 10). **D4 is a defect number,
  not a task number.**

---

# T4 — Computed parameter reduction

## Task 6.1 — The required-parameter table, by computation

**Steps**

- [ ] 6.1.1 Produce the required-parameter table for `MM.PR.CreateDraft` **by computation** — one
  row per required input, with its post-change source kind and whether it still needs asking.
- [ ] 6.1.2 **Do not copy any figure from a design document.** The number must come from running
  the code.
- [ ] 6.1.3 **Report the computed number even if it is 4 rather than 3**, and state the missing
  item's prerequisite.
- [ ] 6.1.4 **Stop and ask the user if the computed number differs from the target.**

---

# T5 full — Conversation-sequence assertions

## Task 7.1 — Case 1 real: *derived-not-asked*

- [ ] 7.1.1 Input: material + plant only. Assert **all five**: neither `unit` nor
  `purchasing_group` is elicited; both carry `provenance=capability_derived`; the
  `MM.Material.GetInfo` node exists in the plan; the `data` edge carrying
  `sapnexus:MaterialInfoFact` exists; `topologicalOrder` places GetInfo before `MM.PR.CreateDraft`.

## Task 7.2 — Case 2 real: *user-supplied-wins*

- [ ] 7.2.1 The user supplies `unit` → it binds from `literal`; **no** `factField` source is
  authored for it; the producer is **not** pulled into `desired_fact_types`; **no extra READ** is
  executed.
- [ ] 7.2.2 Verify by asserting the **absence of the producer node**, not merely the presence of
  the literal. This is the half of the pair that makes case 1 meaningful.

## Task 7.3 — Case 3 real: *mixed*

- [ ] 7.3.1 The user supplies `unit`, omits `purchasing_group` → **exactly one** `data` edge for
  the (GetInfo → CreateDraft, `MaterialInfoFact`) pair; `purchasing_group` binds from `factField`;
  `unit` binds from `literal`. **This is the assertion that proves 5.5's fix.**

## Task 7.4 — Case 4 real: upstream empty or erroring

- [ ] 7.4.1 Degrades to **elicitation** — never to a default, never to a fabricated value.

## Task 7.5 — Case 5 real: upstream unreachable

- [ ] 7.5.1 `CapabilityGap` is emitted and the run **errors** rather than degrading into an
  attempt. Governance red line.

## Task 7.6 — Dry-run coverage the specs now require

- [ ] 7.6.1 Exercise the missing-producer gap against the **governed** capability set.
- [ ] 7.6.2 Surface unbound inputs plus derivation diagnostics as gaps.
- [ ] 7.6.3 Verify the previously `pending: true` dry-run case is **no longer pending**.

---

# Batch T exit verification and reporting

## Task 8.1 — Run and capture raw output

- [ ] 8.1.1 `.venv/bin/python scripts/validate-registry-contract.py registry/capabilities.yaml`
- [ ] 8.1.2 `.venv/bin/python -m pytest agent/tests/test_registry_contract.py -v`
- [ ] 8.1.3 `.venv/bin/python -m pytest agent/tests -q`
- [ ] 8.1.4 `PYTHONPATH=agent scripts/verify-agent-callplan-evidence.sh`
- [ ] 8.1.5 `npm --prefix frontend run verify`
- [ ] 8.1.6 `npm --prefix frontend run release-gate -- --profile all`

**Never pipe these through `tail`/`head`.** A truncated log destroys its own evidence — this
already happened once during baselining and cost a re-run.

## Task 8.2 — Gate confirmation

- [ ] 8.2.1 Release gate still reports **22/22** and `L3_ACTION_GOVERNED`.
- [ ] 8.2.2 All four eval suites fully green.

## Task 8.3 — The two Python line counts

- [ ] 8.3.1 Produce a **file-partitioned** `git diff --stat`.
- [ ] 8.3.2 **Figure (a)** — registration lines. Target **0**.
- [ ] 8.3.3 **Figure (b)** — pre-existing-defect lines, **each line attributed to a named defect**:
  bindingKind coupling relaxation (Decision 14) · `producers[0]` silently-picks-one · defect 1
  duplicate data edge · `_first_fact_field` ignores semantic type · defect 2 hardcoded inventory
  value label · producer auto-pull (Decision 16).

## Task 8.4 — Changed-file list and unresolved-item list

- [ ] 8.4.1 Changed-file list with a one-sentence note per file.
- [ ] 8.4.2 Unresolved-item list naming **each specific test + its attribution + its reason**.
  **No item may be summarised as 已知问题 / 既有失败 / 与核心功能无关** (invariant 10). The three
  baseline non-passes named in the Baseline section are the starting content of this list.

## Task 8.5 — Batch T exit gate

- [ ] 8.5.1 Confirm every batch T exit condition is met — **including a green positive control
  (3.2) alongside whatever the real-capability derived view reports**.
- [ ] 8.5.2 Confirm batch L has **not** begun. It is a separate change; it does not start in this
  one; it commits independently and is never mixed into this commit.

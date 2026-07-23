# Capability Composition Contract Runbook

## Document Version

| Field | Value |
|---|---|
| Runbook | `10-capability-composition-contract` |
| Version | `v0.3.1` |
| Status | `S1 Implemented / Verified; Runtime Reserved` |
| Created | `2026-07-14` |
| Updated | `2026-07-19` |
| Workstream | S1 semantic planning contracts, immutable graph, snapshot, GoalSpec and PlanGraph validation implemented and verified |
| Related Change | `sap-nexus-semantic-planning-foundation` (active; verify/archive pending user confirmation); `sap-nexus-planner-dry-run` (next design) |
| Current Phase | S1 verified; S2 dry-run design is next; current runtime remains single-capability |

---

## 1. Session Goal

This runbook is the continuation entry for semantic planning and capability composition. S1 is now implemented and verified as a contract-only foundation: published Fact Types and Capability Relations compile into an immutable in-memory graph bound to a deterministic Registry snapshot; GoalSpec and caller-authored PlanGraph validation return structured reports. The first scenario remains "material inventory + purchase-order supply overview". Atomic capabilities (`Skill` / `Function` / `Action`) remain the only runtime execution unit until S3 passes its own design and verification gates.

Composition is not a single concept. It has three forms with different semantics and preconditions (see architecture §5.4):

| Composition form | Semantics | Layer | Landing precondition |
|---|---|---|---|
| Fact-level aggregation | Multiple `Function`s each produce `ReasoningFact`, synthesized by reasoning / narrative | L6 / L7 | `ReasoningFact[] -> RecommendationPlan` direction exists; orchestration missing |
| Composite Capability | A fixed multi-step flow registered as one `capabilityId` with an internal deterministic DAG | L3 | Same governance / approval / eval / replay as atomic capabilities; no free orchestration |
| Dynamic Planner | Runtime orchestration of atomic capabilities by intent | L2 | Requires capability relation ontology first; works only inside the ontology dependency graph |

Hard precondition: capability relations (`producesFactType` / `consumesFactType` / `dependsOn` / `precondition`) must be modeled before executable composition. Until the read-only pilot is implemented and verified, multi-capability requests still go through `ESCALATE_TO_PLANNER` (record + explain), never auto-orchestration. The planner orchestrates the published ontology dependency graph, not free LLM tool-calling -- this is consistent with "Harness != LLM + tool calling".

---

## 2. Source Of Truth

Read these before opening or implementing the change:

```text
AGENTS.md
docs/runbooks/README.md
docs/runbooks/10-capability-composition-contract.md
docs/wiki/sap-nexus-agent-technical-architecture.md
docs/wiki/sap-nexus-agent-implementation-roadmap.md
docs/wiki/sap-nexus-agent-technology-selection.md
docs/wiki/sap-nexus-agent-openharness-semantic-orchestration.md
openspec/specs/registry-ontology-contract/spec.md
openspec/specs/gateway-execution-contract/spec.md
registry/README.md
registry/capabilities.yaml
```

Verified S1 baseline:

- Atomic capabilities remain the only runtime execution unit; composition is Reserved.
- Multi-capability requests currently produce `ESCALATE_TO_PLANNER` (record + explain), never auto-orchestration.
- Three first-class Fact Types and the Capability Relation contract are published; the authored relation catalog is empty for the first independent two-node pilot.
- The immutable graph exports exactly three derived producer edges and is never an execution authority.
- `RegistrySnapshot` deterministically covers the four semantic source files; the fresh verified snapshot is `sha256:bf0ac12a482d719725bf888feb9d3e10e60e583aa91c999a819a49001ce92092`.
- `ContractValidationReport`, `GoalReachabilityReport`, and `PlanValidationReport` provide deterministic fail-closed evidence without generating or executing a plan.
- Graph database is not introduced; capability relations use triple model + file edge list + in-memory graph.
- `capabilities.yaml` + validator remain the single gated source; relation files do referential-integrity checks against it.
- OpenHarness is a design reference only; no OpenHarness runtime, plugin loader, or permission runtime dependency is added.
- The first scenario is fixed as `MM.Inventory.GetAvailability + MM.PurchaseOrder.GetList -> MaterialSupplySnapshot`.
- The first scenario does not claim shortage prediction, purchase quantity calculation, or automatic PR creation.

---

## 3. Staged Scope

### S1: `sap-nexus-semantic-planning-foundation` (implemented / verified)

1. Published Fact Type and Capability Relation schemas/catalogs plus v2 semantic Registry IO contracts.
2. Compiled an immutable in-memory graph with derived producer edges and authored relation validation.
3. Published deterministic four-source `RegistrySnapshot` canonicalization.
4. Added independently validatable GoalSpec reachability and caller-authored PlanGraph validation reports.
5. Verified referential integrity, cycles, type compatibility, parameter provenance, governance, topology, Goal outputs, and snapshot drift fail closed.
6. Kept the file edge list + in-memory read-only graph boundary; no LLM, Gateway, SAP, OpenHarness, graph database, or runtime orchestration was added.

### S2: `sap-nexus-planner-dry-run`

1. Produce `GoalSpec` / `PlanDraft` candidates from natural language.
2. Compile candidates with a deterministic `PlanCompiler`.
3. Preview nodes, edges, parameter sources, missing inputs, capability gaps, side effects, and approval barriers.
4. Do not execute Gateway or SAP.

### S3: `sap-nexus-read-composition-pilot`

First scenario:

```text
MM.Inventory.GetAvailability
+ MM.PurchaseOrder.GetList
-> MaterialSupplySnapshot
```

The two nodes may run in parallel only after PlanGraph proves they are independent and both are active `sideEffect=none` Functions. Each node still uses the existing Gateway `validate -> execute` path. The output must retain per-Fact lineage and must not claim shortage prediction or purchase quantity.

### Still out of near-term scope

- General Dynamic Planner runtime.
- Composite Capability execution engine beyond the confirmed read-only pilot.
- LLM free-form multi-capability orchestration.
- Auto-publish of capability, ontology, relation, or executor binding.
- Write composition or composite approval.
- Graph database runtime.

### Stage gates

- S1 implementation and verification evidence has passed; Comet verify/archive remains pending user-confirmed closeout.
- S2 may enter design next because S1 schemas and validators passed the local release gate. S2 remains dry-run only and must not call Gateway or SAP.
- S3 starts only after dry-run bad cases prove fail-closed behavior and both atomic Read capabilities retain their existing regression baselines.
- Dynamic Planner remains gated by completed S1-S3 plus `active capability > 50` OR `business domains > 3` OR `multi-capability request share > 15%`.

---

## 4. Safety Boundaries

Mandatory rules:

- S1 implementation verification is complete and closeout remains pending; S2 dry-run design is the open next design. Executable composition remains blocked until the S3 stage gates above are met.
- OpenHarness is a design reference only; do not add it as a runtime dependency or second execution authority.
- The planner orchestrates the ontology dependency graph only; LLM must not freely orchestrate atomic capabilities.
- Current multi-capability requests must produce `ESCALATE_TO_PLANNER` (record + explain), not auto-execution, until S3 is implemented and verified.
- `GoalSpec` / `PlanDraft` are advisory candidates; only deterministic compilation may produce a PlanGraph.
- `READ_ONLY` PlanGraph containing an Action must fail closed.
- `Composite Capability`, if ever landed, must be a registered `capabilityId` with a deterministic, evaluable, replayable internal DAG, governed by the same governance / approval / eval / replay as atomic capabilities.
- Write steps inside a composition chain still require Human Approval; "composite" does not bypass per-step approval.
- Composition chains containing write must explicitly declare `compensationPolicy` and `partialFailurePolicy`; partial success must not silently diverge.
- `TraceSpan` reserves `parentPlanId` / `subSpan` so composition chains replay fully by `traceId` and locate failed steps and compensation actions.
- Capability relations (`dependsOn` / `precondition`) live in a separate relation layer, not inlined into atomic capabilities.
- The graph is always a derived read-only index, never the execution authority; on unavailability, fall back to the published Registry snapshot.

---

## 5. Acceptance Criteria

| Area | Acceptance |
|---|---|
| Foundation | Fact Type, relation, GoalSpec and PlanGraph contracts are versioned and independently validatable |
| Closed set | PlanGraph never contains an unregistered capability or executor override |
| Compiler | Cycle, type mismatch, missing parameter provenance and Registry Snapshot drift fail closed |
| Dry-run | Shows nodes, edges, parameter sources, gaps, governance and approval barriers without calling SAP |
| Pilot | Inventory and PO Read nodes use existing Gateway validation/execution and emit Fact lineage |
| Business boundary | MaterialSupplySnapshot does not claim shortage prediction, purchase quantity or automatic PR |
| Planner boundary | Dynamic Planner works only inside the published ontology dependency graph; no free LLM orchestration |
| Escalation | Multi-capability requests produce `ESCALATE_TO_PLANNER` until S3 is implemented and verified |
| Approval | Write steps in composition chains require Human Approval per step |
| Transactionality | Composition chains with write declare `compensationPolicy` and `partialFailurePolicy` |
| Trace | `TraceSpan.parentPlanId` / `subSpan` allow full replay by `traceId` |
| Relation layer | `dependsOn` / `precondition` live in a separate relation layer, not inlined into atomic capabilities |
| Graph | Graph is derived read-only; falls back to Registry snapshot when unavailable |
| Dependency | OpenHarness is not added as a runtime dependency |

Recommended verification after implementation:

```bash
.venv/bin/python scripts/validate-registry-contract.py registry/capabilities.yaml
.venv/bin/python -m pytest agent/tests/test_registry_contract.py -v
scripts/verify-agent-callplan-evidence.sh
openspec validate --all --strict
# plus future composition contract tests/evals documented by the change
```

### S1 verification record

- Report: `docs/superpowers/reports/2026-07-19-sap-nexus-semantic-planning-foundation-verify.md`
- Legacy Registry: exit `0`.
- Semantic contract: exit `0`; snapshotId `sha256:bf0ac12a482d719725bf888feb9d3e10e60e583aa91c999a819a49001ce92092`.
- Focused semantic tests: `287 passed in 6.78s`.
- Full evidence: `550 passed, 1 skipped`; inventory eval `7/7`; seed eval `13/13`; PR eval `9/9`.
- OpenSpec strict: `Totals: 8 passed, 0 failed (8 items)`.
- Archive: pending user-confirmed Comet verify/archive; no archive link exists yet.

---

## 6. Next Start Here

1. Re-read the four wiki source-of-truth documents, the S1 verification report, and this runbook.
2. Check `git status --short` and `openspec list --json`; do not assume S1 is archived until the archive directory exists.
3. After user-confirmed S1 verify/archive closeout, start the design for `sap-nexus-planner-dry-run`.
4. Keep S2 limited to natural-language GoalSpec/PlanDraft candidates, deterministic PlanCompiler output, validation evidence, and dry-run preview; do not call Gateway or SAP.
5. Keep S3 Read-only Pilot as a separate follow-up change with explicit lineage, Gateway regression, and no-write gates.

Do not start from OpenHarness integration, graph database selection, Dynamic Planner, read-only execution, or Write composition. Those are not the S2 design workstream.

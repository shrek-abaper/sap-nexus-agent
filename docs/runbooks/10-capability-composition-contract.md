# Capability Composition Contract Runbook

## Document Version

| Field | Value |
|---|---|
| Runbook | `10-capability-composition-contract` |
| Version | `v0.3.3` |
| Status | `S1 Archived; S2 Next; Runtime Reserved` |
| Created | `2026-07-14` |
| Updated | `2026-07-24` |
| Workstream | Archived S1 semantic planning foundation, immediate source-of-truth hygiene, S2 dry-run next, S3 execution gated |
| Related Change | `sap-nexus-semantic-planning-foundation` (archived `2026-07-19`); `sap-nexus-planner-dry-run` (next business design) |
| Current Phase | P0A documentation/repository hygiene then S2 dry-run; current runtime remains single-capability |

---

## 1. Session Goal

This runbook is the continuation entry for semantic planning and capability composition. S1 is implemented, verified, and archived as a contract-only foundation: published Fact Types and Capability Relations compile into an immutable in-memory graph bound to a deterministic Registry snapshot; GoalSpec and caller-authored PlanGraph validation return structured reports. The first scenario remains "material inventory + purchase-order supply overview". Atomic capabilities (`Skill` / `Function` / `Action`) remain the only runtime execution unit until S3 passes its own design and verification gates.

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
docs/wiki/sap-nexus-agent-deerflow-adoption-analysis.md
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
- DeerFlow is a design reference only; no `deerflow-harness`, DeerFlow Gateway/frontend, default lead agent, task graph, or memory runtime dependency is added.
- S2 may adapt metadata-first progressive `CapabilityCard` discovery, but candidate search, Skill activation and LLM output never become `MatchDecision` or `PlanGraph` authority.
- S3 may adapt ready-node, concurrency limit, timeout, cancel, node ledger and trace lifecycle mechanics only after deterministic PlanGraph validation.
- Conversation summary, Memory, Tool calls and sub-agent output are advisory data; they never become plan, approval, execution or evidence authority.
- The first scenario is fixed as `MM.Inventory.GetAvailability + MM.PurchaseOrder.GetList -> MaterialSupplySnapshot`.
- The first scenario does not claim shortage prediction, purchase quantity calculation, or automatic PR creation.

---

## 3. Staged Scope

### S1: `sap-nexus-semantic-planning-foundation` (implemented / verified / archived)

1. Published Fact Type and Capability Relation schemas/catalogs plus v2 semantic Registry IO contracts.
2. Compiled an immutable in-memory graph with derived producer edges and authored relation validation.
3. Published deterministic four-source `RegistrySnapshot` canonicalization.
4. Added independently validatable GoalSpec reachability and caller-authored PlanGraph validation reports.
5. Verified referential integrity, cycles, type compatibility, parameter provenance, governance, topology, Goal outputs, and snapshot drift fail closed.
6. Kept the file edge list + in-memory read-only graph boundary; no LLM, Gateway, SAP, OpenHarness, graph database, or runtime orchestration was added.

### S2: `sap-nexus-planner-dry-run`

1. Produce a small candidate set through progressive `CapabilityCard` discovery, then generate `GoalSpec` / `PlanDraft` candidates from natural language.
2. Keep candidate discovery advisory; compile candidates with a deterministic `PlanCompiler`.
3. Preview candidates, nodes, edges, parameter sources, missing inputs, capability gaps, side effects, and approval barriers.
4. Do not execute Gateway or SAP, and do not add DeerFlow as a dependency.

### S3: `sap-nexus-read-composition-pilot`

First scenario:

```text
MM.Inventory.GetAvailability
+ MM.PurchaseOrder.GetList
-> MaterialSupplySnapshot
```

The two nodes may run in parallel only after PlanGraph proves they are independent and both are active `sideEffect=none` Functions. The PlanExecutor may then use a ready-node queue, concurrency limits, timeout/cancel, node ledger and trace correlation. Each node still uses the existing Gateway `validate -> execute` path. A deterministic `OutputProjection` must produce `MaterialSupplySnapshot` with `asOf` / freshness, completeness, limitations and per-Fact lineage; a failed, timed-out or cancelled required node yields `incomplete`, never a complete supply claim.

### Still out of near-term scope

- General Dynamic Planner runtime.
- Composite Capability execution engine beyond the confirmed read-only pilot.
- LLM free-form multi-capability orchestration.
- Auto-publish of capability, ontology, relation, or executor binding.
- Write composition or composite approval.
- Graph database runtime.
- DeerFlow integration, default lead agent, generic task/sub-agent execution, or model-directed memory.
- Durable runtime implementation inside S2 and Governed User Memory. Trusted/durable runtime remains a separate conditional gate before shared S3, long approval, multi-worker/HA or non-sandbox WRITE.

### Stage gates

- S1 implementation, verification and archive are complete at `openspec/changes/archive/2026-07-19-sap-nexus-semantic-planning-foundation/`.
- P0A source-of-truth/repository hygiene must close current status, moved-path, stale editable-install and tracked-runtime-artifact drift without changing runtime behavior.
- S2 may enter design next because S1 schemas and validators passed the local release gate. S2 remains dry-run only and must not call Gateway or SAP.
- S3 starts only after dry-run bad cases prove fail-closed behavior, both atomic Read capabilities retain their existing regression baselines, and deterministic OutputProjection / incomplete semantics are designed.
- Shared S3, long approval, multi-worker/HA or non-sandbox WRITE additionally requires trusted principal context, durable Run/Approval, ownership/lease, incremental SSE with cursor/replay and idempotent continuation.
- Dynamic Planner remains gated by completed S1-S3 plus `active capability > 50` OR `business domains > 3` OR `multi-capability request share > 15%`.

---

## 4. Safety Boundaries

Mandatory rules:

- S1 is archived; P0A hygiene then S2 dry-run design is the open next sequence. Executable composition remains blocked until the S3 stage gates above are met.
- OpenHarness is a design reference only; do not add it as a runtime dependency or second execution authority.
- DeerFlow is a design reference only; do not add it as a runtime dependency, second Agent loop, or second execution authority.
- The planner orchestrates the ontology dependency graph only; LLM must not freely orchestrate atomic capabilities.
- Current multi-capability requests must produce `ESCALATE_TO_PLANNER` (record + explain), not auto-execution, until S3 is implemented and verified.
- `GoalSpec` / `PlanDraft` are advisory candidates; only deterministic compilation may produce a PlanGraph.
- `CapabilityCard`, Tool search, Skill activation, summary, Memory and sub-agent output are also advisory; none can grant execution authority.
- `READ_ONLY` PlanGraph containing an Action must fail closed.
- `Composite Capability`, if ever landed, must be a registered `capabilityId` with a deterministic, evaluable, replayable internal DAG, governed by the same governance / approval / eval / replay as atomic capabilities.
- Write steps inside a composition chain still require Human Approval; "composite" does not bypass per-step approval.
- Composition chains containing write must explicitly declare `compensationPolicy` and `partialFailurePolicy`; partial success must not silently diverge.
- `TraceSpan` reserves `parentPlanId` / `subSpan` so composition chains replay fully by `traceId` and locate failed steps and compensation actions.
- Capability relations (`dependsOn` / `precondition`) live in a separate relation layer, not inlined into atomic capabilities.
- The graph is always a derived read-only index, never the execution authority; on unavailability, fall back to the published Registry snapshot.
- Ready-node parallelism requires a validated PlanGraph, no dependency edge and `sideEffect=none`; model-emitted parallel Tool Calls are not a valid execution plan.
- Principal, tenant, role, data scope and ApprovalActor are server-owned context; request, prompt, summary, Memory and sub-agent output cannot supply execution identity.
- Current buffered SSE-format response and process-local Run/Approval stores are local MVP mechanisms, not shared-runtime readiness evidence.

---

## 5. Acceptance Criteria

| Area | Acceptance |
|---|---|
| Foundation | Fact Type, relation, GoalSpec and PlanGraph contracts are versioned and independently validatable |
| Closed set | PlanGraph never contains an unregistered capability or executor override |
| Compiler | Cycle, type mismatch, missing parameter provenance and Registry Snapshot drift fail closed |
| Dry-run | Shows nodes, edges, parameter sources, gaps, governance and approval barriers without calling SAP |
| Candidate discovery | S2 exposes bounded `CapabilityCard` candidates without technical binding details; deterministic MatchDecision / PlanCompiler remains authoritative |
| Pilot | Inventory and PO Read nodes use existing Gateway validation/execution, governed ready-node lifecycle and Fact lineage |
| Scheduling | S3 enforces dependency, side-effect, concurrency, timeout/cancel, node ledger and trace rules before parallel execution |
| Output projection | Deterministic `OutputProjection` declares input Facts, output schema, freshness, completeness, limitations and lineage; partial failure remains explicit |
| Trusted runtime | Shared S3/long approval/non-sandbox WRITE has authenticated ownership, durable Run/Approval, incremental SSE cursor/replay and idempotent continuation |
| Business boundary | MaterialSupplySnapshot does not claim shortage prediction, purchase quantity or automatic PR |
| Planner boundary | Dynamic Planner works only inside the published ontology dependency graph; no free LLM orchestration |
| Escalation | Multi-capability requests produce `ESCALATE_TO_PLANNER` until S3 is implemented and verified |
| Approval | Write steps in composition chains require Human Approval per step |
| Transactionality | Composition chains with write declare `compensationPolicy` and `partialFailurePolicy` |
| Trace | `TraceSpan.parentPlanId` / `subSpan` allow full replay by `traceId` |
| Relation layer | `dependsOn` / `precondition` live in a separate relation layer, not inlined into atomic capabilities |
| Graph | Graph is derived read-only; falls back to Registry snapshot when unavailable |
| Dependency | OpenHarness is not added as a runtime dependency |
| DeerFlow dependency | DeerFlow is not added as a runtime dependency; only the documented mechanisms are adapted |
| Context authority | Summary, Memory, Tool calls and sub-agent output never replace PlanGraph, ApprovalRecord or Evidence |

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
- Archive: `openspec/changes/archive/2026-07-19-sap-nexus-semantic-planning-foundation/`.

---

## 6. Next Start Here

1. Re-read the four wiki source-of-truth documents, the S1 verification report, and this runbook.
2. Check `git status --short` and `openspec list --json`; S1 archive path must remain present and no active change is assumed.
3. Close P0A source-of-truth and repository-hygiene drift without changing runtime behavior.
4. Start `sap-nexus-planner-dry-run` and keep it limited to progressive `CapabilityCard` discovery, natural-language GoalSpec/PlanDraft candidates, deterministic PlanCompiler output, validation evidence, and dry-run preview; do not call Gateway or SAP.
5. Keep S3 Read-only Pilot as a separate follow-up change with PlanGraph-governed lifecycle, deterministic OutputProjection, explicit incomplete/freshness/lineage semantics, Gateway regression, and no-write gates.
6. Before shared S3, long approval, multi-worker/HA or non-sandbox WRITE, open the separate trusted/durable runtime change; do not select its store inside S2.
7. Do not start DeerFlow integration or user memory work unless separately evidenced and approved.

Do not start S2 from OpenHarness / DeerFlow integration, durable store selection, user memory, graph database selection, Dynamic Planner, read-only execution, or Write composition. Those are not the S2 design workstream.

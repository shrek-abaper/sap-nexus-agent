# Capability Composition Contract Runbook

## Document Version

| Field | Value |
|---|---|
| Runbook | `10-capability-composition-contract` |
| Version | `v0.3.10` |
| Status | `Completed / Archived` |
| Created | `2026-07-14` |
| Updated | `2026-08-03` |
| Last Change | Lifecycle closeout correction: S1/S2-A/S2-B contract work is complete; the former S3 continuation is decomposed into successor runbooks 13-22 |
| Workstream | Completed semantic planning foundation, MatchDecision hardening and Planner dry-run contract |
| Related Change | `sap-nexus-semantic-planning-foundation` (archived `2026-07-19`); `sap-nexus-planner-dry-run` (S2-A + S2-B archived `2026-07-25` at openspec/changes/archive/2026-07-25-sap-nexus-planner-dry-run/) |
| Current Phase | Closed; do not resume S3 implementation from this runbook |
| Successor | Runbooks 13-22 own governed context through complete Agent release gates |
| Reopen Policy | Do not reopen; update successor runbooks instead |

---

## 1. Session Goal

This archived runbook records the completed S1/S2 semantic planning and capability-composition contract. Published Fact Types and Capability Relations compile into an immutable in-memory graph bound to a deterministic Registry snapshot; GoalSpec and caller-authored PlanGraph validation return structured reports. The first scenario remains "material inventory + purchase-order supply overview". Successor runbooks 13-22 own all further implementation.

Composition is not a single concept. It has three forms with different semantics and preconditions (see architecture §5.4):

| Composition form | Semantics | Layer | Landing precondition |
|---|---|---|---|
| Fact-level aggregation | Multiple `Function`s each produce `ReasoningFact`, synthesized by reasoning / narrative | L6 / L7 | `ReasoningFact[] -> RecommendationPlan` direction exists; orchestration missing |
| Composite Capability | A fixed multi-step flow registered as one `capabilityId` with an internal deterministic DAG | L3 | Same governance / approval / eval / replay as atomic capabilities; no free orchestration |
| Dynamic Planner | Runtime orchestration of atomic capabilities by intent | L2 | Requires capability relation ontology first; works only inside the ontology dependency graph |

Hard precondition: capability relations (`producesFactType` / `consumesFactType` / `dependsOn` / `precondition`) must be modeled before executable composition. Multi-capability requests now reach `ESCALATE_TO_PLANNER` and deterministic dry-run, but must not auto-execute until runbooks 13-17 establish same-snapshot governance, PlanGraph v2, READ execution and OutputProjection. The planner orchestrates the published ontology dependency graph, not free LLM tool-calling -- this is consistent with "Harness != LLM + tool calling".

---

## 2. Archive Sources and Verified Baseline

These sources formed the archived delivery. Do not open a new implementation from this section:

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

- Atomic capabilities remain the only runtime execution unit; executable composition is still planned.
- Multi-capability requests produce `ESCALATE_TO_PLANNER` and dry-run, but these artifacts have no execution authority until the new runbook chain is implemented.
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

### Pre-S2 Baseline to Complete Agent Evolution

> Moved from `docs/wiki/sap-nexus-agent-technical-architecture.md` §4.3. Architecture retains only the MVP contract definition and fail-closed boundaries; this matrix is the single home for current-vs-target status across capability dimensions.

当前状态必须与目标契约分开描述：现有 runtime 已支持 LLM-first intent、五态 `MatchDecision`、multi-intent escalation 和 deterministic PlanGraph dry-run；但没有 `PlanExecutor`、组合 `OutputProjection`、规则建议或多能力 WRITE proposal 闭环。因此只能声称“已规划预览”，不能声称“已编排执行”。

| 能力 | Pre-S2 Baseline | S2-A MatchDecision Hardening | S2-B Planner Dry-run | Runbooks 13-22 Target |
|---|---|---|---|---|
| 单能力规则 / LLM 闭集选择 | 已实现 | 保留并纳入统一决策 | 作为候选入口 | 作为原子节点入口 |
| 五态 `MatchDecision` runtime | 未完整实现 | 实现并记录候选、理由、snapshot 和 trace | 作为 Planner 入口 | 作为执行前决策证据 |
| 多意图 / 歧义检测 | 未实现；存在首命中降级风险 | 实现 `SHOW_OPTIONS` / `ESCALATE_TO_PLANNER` | 转换为 GoalSpec / PlanDraft candidate | 只执行已编译 PlanGraph |
| Progressive `CapabilityCard` discovery | 未实现 | 固化安全投影与 visibility contract | 实现有界候选发现 | 消费已选 capability |
| deterministic `PlanCompiler` | 未实现 | 固化输入边界 | 只产 dry-run PlanGraph | 执行前重新校验 |
| PlanGraph execution | 未实现 | 不执行 | 不执行 | READ DAG 执行；WRITE 仅 proposal + Human Approval |

### S1: `sap-nexus-semantic-planning-foundation` (implemented / verified / archived)

1. Published Fact Type and Capability Relation schemas/catalogs plus v2 semantic Registry IO contracts.
2. Compiled an immutable in-memory graph with derived producer edges and authored relation validation.
3. Published deterministic four-source `RegistrySnapshot` canonicalization.
4. Added independently validatable GoalSpec reachability and caller-authored PlanGraph validation reports.
5. Verified referential integrity, cycles, type compatibility, parameter provenance, governance, topology, Goal outputs, and snapshot drift fail closed.
6. Kept the file edge list + in-memory read-only graph boundary; no LLM, Gateway, SAP, OpenHarness, graph database, or runtime orchestration was added.

### S2-A: Semantic MatchDecision Hardening

1. Implement the first-class five-state `MatchDecision`: `SELECT`, `CLARIFY`, `SHOW_OPTIONS`, `REJECT`, `ESCALATE_TO_PLANNER`.
2. Detect multi-intent and ambiguous candidates before single-capability selection; never reduce multiple goals to the first keyword match.
3. Apply server-owned governed context and capability visibility before candidate cards enter model context.
4. Bind decision evidence to candidate reasons, Registry Snapshot and trace.
5. Add matcher Eval for multi-intent, ambiguity, capability gap, parameter grounding, visibility leakage, prompt injection and false `SELECT`.

### S2-B: `sap-nexus-planner-dry-run`

1. Produce a small candidate set through progressive `CapabilityCard` discovery, then generate `GoalSpec` / `PlanDraft` candidates from natural language.
2. Keep candidate discovery advisory; compile candidates with a deterministic `PlanCompiler`.
3. Preview candidates, nodes, edges, parameter sources, missing inputs, capability gaps, side effects, and approval barriers.
4. Do not execute Gateway or SAP, and do not add DeerFlow as a dependency.

### Former S3 Scope - Superseded by Runbooks 13-17

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
- Governed User Memory remains Later/Triggered. P0B durable runtime is complete and must be reused by PlanExecution.

### Stage gates

- S1 implementation, verification and archive are complete at `openspec/changes/archive/2026-07-19-sap-nexus-semantic-planning-foundation/`.
- P0A source-of-truth/repository hygiene closed (2026-07-25): status/path drift, stale editable-install and tracked-runtime-artifact issues resolved without changing runtime behavior.
- S2-A/S2-B are complete and remain non-executing; their dry-run artifacts do not grant Gateway authority.
- P0B trusted/durable prerequisites are complete.
- Implementation starts with runbook 13 same-snapshot governance, then follows runbooks 14-22 in order; runbook 16 cannot precede PlanGraph v2 and runbook 18 cannot precede OutputProjection.
- Dynamic Planner remains gated by completed S1-S3 plus `active capability > 50` OR `business domains > 3` OR `multi-capability request share > 15%`.

---

## 4. Safety Boundaries

Mandatory rules:

- S1, P0A, S2-A/S2-B and P0B are archived. Executable composition remains blocked until runbooks 13-17 pass their gates.
- OpenHarness is a design reference only; do not add it as a runtime dependency or second execution authority.
- DeerFlow is a design reference only; do not add it as a runtime dependency, second Agent loop, or second execution authority.
- The planner orchestrates the ontology dependency graph only; LLM must not freely orchestrate atomic capabilities.
- Multi-capability requests reliably produce `ESCALATE_TO_PLANNER`; this proves escalation and dry-run only, not execution.
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
- Incremental SSE/reconnect and durable Run/Approval foundations are complete; they must be extended, not duplicated, for PlanExecution events.

---

## 5. Archived Acceptance Criteria

| Area | Acceptance |
|---|---|
| Foundation | Fact Type, relation, GoalSpec and PlanGraph contracts are versioned and independently validatable |
| Closed set | PlanGraph never contains an unregistered capability or executor override |
| Compiler | Cycle, type mismatch, missing parameter provenance and Registry Snapshot drift fail closed |
| Dry-run | Shows nodes, edges, parameter sources, gaps, governance and approval barriers without calling SAP |
| Candidate discovery | S2 exposes bounded `CapabilityCard` candidates without technical binding details; deterministic MatchDecision / PlanCompiler remains authoritative |
| Baseline decision | S2-A implements five-state `MatchDecision`, multi-intent/ambiguity handling, candidate visibility and decision trace without embedding or executable planning |
| Pilot | Inventory and PO Read nodes use existing Gateway validation/execution, governed ready-node lifecycle and Fact lineage |
| Scheduling | S3 enforces dependency, side-effect, concurrency, timeout/cancel, node ledger and trace rules before parallel execution |
| Output projection | Deterministic `OutputProjection` declares input Facts, output schema, freshness, completeness, limitations and lineage; partial failure remains explicit |
| Trusted runtime | Shared S3/long approval/non-sandbox WRITE has authenticated ownership, durable Run/Approval, incremental SSE cursor/replay and idempotent continuation |
| Business boundary | MaterialSupplySnapshot does not claim shortage prediction, purchase quantity or automatic PR |
| Planner boundary | Dynamic Planner works only inside the published ontology dependency graph; no free LLM orchestration |
| Escalation | S2-A proves multi-capability requests produce `ESCALATE_TO_PLANNER`; false first-match `SELECT` fails regression |
| Approval | Write steps in composition chains require Human Approval per step |
| Transactionality | Composition chains with write declare `compensationPolicy` and `partialFailurePolicy` |
| Trace | `TraceSpan.parentPlanId` / `subSpan` allow full replay by `traceId` |
| Relation layer | `dependsOn` / `precondition` live in a separate relation layer, not inlined into atomic capabilities |
| Graph | Graph is derived read-only; falls back to Registry snapshot when unavailable |
| Dependency | OpenHarness is not added as a runtime dependency |
| DeerFlow dependency | DeerFlow is not added as a runtime dependency; only the documented mechanisms are adapted |
| Context authority | Summary, Memory, Tool calls and sub-agent output never replace PlanGraph, ApprovalRecord or Evidence |

Archived verification commands:

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

## 6. Archive Handoff - Do Not Reopen

1. Re-read the four wiki source-of-truth documents, the S1 verification report, and this runbook.
2. Check `git status --short` and `openspec list --json`; S1 archive path must remain present and no active change is assumed.
3. P0A source-of-truth and repository-hygiene drift is closed (2026-07-25); no action needed.
4. S2-A and S2-B are complete (2026-07-25): five-state `MatchDecision`, multi-intent/ambiguity detection, visibility pre-filter, matcher Eval 6/6, progressive `CapabilityCard` discovery, `GoalSpec`/`PlanDraft` candidates, deterministic `PlanCompiler` dry-run (eval 3/3 + 1 pending covered by unit test); S2 does not call Gateway or SAP.
5. Start from runbook 13, then follow the `13 -> 14 -> 15 -> 16 -> 17 -> 18 -> 19 -> 20 -> 21 -> 22` dependency chain.
6. Reuse P0B durable state, principal, approval and SSE foundations; do not create parallel stores or event channels.
7. Keep Knowledge/RAG, DeerFlow integration, Dynamic Planner, multi-WRITE/Saga and user memory out of this MVP.

Do not skip directly to PlanExecutor or WRITE. Same-snapshot governance, intent/recall and PlanGraph v2 contracts are mandatory predecessors.

---

## Session Closeout - 2026-07-25

### Completed

- S2-A Semantic MatchDecision Hardening: first-class five-state `MatchDecision` (`SELECT` / `CLARIFY` / `REJECT` / `SHOW_OPTIONS` / `ESCALATE_TO_PLANNER`); multi-intent and ambiguity detection (D-1 fix: rule parser no longer returns first-match on multi-goal utterances); server-owned governed context and capability visibility pre-filter before candidate cards enter model context; decision evidence bound to candidate reasons, Registry Snapshot and trace; matcher Eval covering all five decision classes plus false-`SELECT` regression.
- S2-B Planner Dry-run: planner module skeleton; progressive `CapabilityCard` discovery projecting `producesFactTypes` from `outputs.factTypeRef`; `GoalSpec` / `PlanDraft` candidate generation from `ESCALATE_TO_PLANNER` handoff; deterministic `PlanCompiler` dry-run producing `PlanGraph` + gaps + governance flags (reuses S1 `semantic-planning-foundation` validator; does not call Gateway or SAP); handoff wiring + dry-run preview in frontend.
- Spec Patches applied in design phase and verified present this session: `semantic-match-decision` SHOW_OPTIONS keyword-ambiguity scenario (threshold anchored by matcher Eval); `planner-dry-run` `CapabilityCard` `producesFactTypes` field (enables PlanCompiler to match candidates against GoalSpec desired Fact Types).
- P0A source-of-truth/repository hygiene closed (2026-07-25): editable-install finder + .venv shebangs repointed to GitHub_Projects; runtime traces gitignored; runbook index synced.

### Verified

- Command: `npm --prefix frontend run verify`
- Result: typecheck clean; 58 tests passed (10 files, including `dry-run-view.test.ts` 11 and `match-decision-view.test.ts` 14); Next.js 15.3.6 production build succeeded (6/6 static pages).
- Command: `scripts/verify-agent-callplan-evidence.sh`
- Result: semantic planning contract valid (snapshotId `sha256:bf0ac12a482d719725bf888feb9d3e10e60e583aa91c999a819a49001ce92092`); pytest `701 passed, 1 skipped` (test_llm_live); inventory eval `7/7`; seed eval `13/13`; PR eval `9/9`; matcher eval `6/6`; dry-run eval `3/3` + 1 SKIP (pending `dry-run-missing-producer` - all active capabilities have `produces_fact_types`; branch covered by `agent/tests/test_planner_plan_compiler.py`); `openspec validate --all --strict` `9 passed, 0 failed (9 items)`.

### Blockers

- None. S2-A + S2-B verification gates all pass; no Gateway/SAP execution performed.

### Historical Handoff - Superseded

> Superseded by runbooks 13-22. Retained only as the `2026-07-25` closeout record.

1. Coordinator runs `comet-guard sap-nexus-planner-dry-run build --apply` and proceeds to the verify phase (`comet-state scale sap-nexus-planner-dry-run` determines verification level).
2. After verify passes, archive `sap-nexus-planner-dry-run` to `openspec/changes/archive/`.
3. Open S3 Read-only Composition Pilot as a separate change: PlanGraph-governed ready-node lifecycle, deterministic `OutputProjection` with freshness/completeness/limitations/lineage, Gateway regression for both atomic Read capabilities, no-write gates.
4. Before shared S3, long approval, multi-worker/HA or non-sandbox WRITE, open the separate trusted/durable runtime change (`sap-nexus-trusted-durable-runtime-foundation`); do not select its store inside S3 read-only pilot design.

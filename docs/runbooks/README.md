# SAP Nexus Agent Runbooks

This directory stores on-demand reference guides for SAP Nexus Agent work across workstreams and sessions.

These runbooks are **not** auto-loaded at session start, and they are **not** the source of truth. Consult one only when a task touches the subsystem it covers, to recover that subsystem's historical scope, design rationale, and safety constraints — then confirm the current position from the source of truth listed below. For the on-demand loading policy, see `AGENTS.md` §1.

---

## How To Use This Directory

All 22 workstream runbooks are now `Archived`, `Implemented`, or `Reserved` (see the index below). There is **no active workstream runbook** to continue, and this directory is **not a source of truth**. It is a supplementary lookup: each archived runbook preserves its subsystem's historical scope, verification targets, safety boundaries, and design rationale, which makes it a fast way to recover *why* a subsystem looks the way it does (e.g. runbook 05 for the Gateway execution path, runbook 11/21 for the SAP WRITE path, runbook 16 for the READ PlanExecutor). Any load-bearing conclusion drawn from a runbook MUST be re-verified against the current source of truth below before you act on it — archived content drifts and is not maintained.

When a task does require a runbook:

1. Find the matching workstream in the index below, cross-referenced by name, not by number.
2. Read only that runbook.
3. Check `git status --short` and `openspec list --json` for active changes before editing.
4. Do **not** write the runbook back. Runbooks are no longer maintained, so closing a Comet change
   does not update one. Closeout is tiered in `AGENTS.md` §3.8; spec deltas land in
   `openspec/specs/` via the workflow's own Archive step.

---

## Current Source Of Truth

Read these docs before changing architecture, implementation plan, or scope:

```text
AGENTS.md
docs/wiki/sap-nexus-agent-technical-architecture.md
docs/wiki/sap-nexus-agent-implementation-roadmap.md
docs/wiki/sap-nexus-agent-technology-selection.md
docs/wiki/sap-nexus-agent-openharness-semantic-orchestration.md
docs/wiki/sap-nexus-agent-deerflow-adoption-analysis.md
docs/wiki/archive/sap-nexus-agent-mm-mvp-notion.md
docs/superpowers/specs/2026-08-03-sap-nexus-complete-agent-roadmap-design.md
```

Key current scope (current-state snapshot; structured maturity overview in the "Architecture Maturity & Current Status" table below). Per-change archive paths, test counts and dates live in the Runbook Index and roadmap version table - not repeated here:

```text
Live capability baseline = 2 READ Functions (MM.Inventory.GetAvailability via BAPI_MATERIAL_STOCK_REQ_LIST, MM.PurchaseOrder.GetList via ODATA) + 1 sandbox-governed Action (MM.PR.CreateDraft)
Gateway = Java JCo Gateway included in first MVP
Current composition runtime = production TypeScript CompositionCoordinator wires validated PlanGraph v2 READ execution to deterministic OutputProjection, RecommendationDecision, grounded Narrative, durable event/replay, Workbench state and Runbook 21 plan-aware single Action HITL continuation; offline fake/sandbox L1/L2/L3 evidence passes, but live SAP composition and live WRITE remain `not_run`
Live blocker = none for PO OData read; SAP SICF reactivated, PO live smoke passed
Complete Agent sequence = runbooks 13-22 archived; there is no automatic next implementation entry
Confirmed first composition scenario = MM.Inventory.GetAvailability + MM.PurchaseOrder.GetList -> MaterialSupplySnapshot
OpenHarness comparison decision = design reference only; no runtime dependency or free SAP tool-calling
DeerFlow adoption decision = design reference only; no deerflow-harness, DeerFlow Gateway/frontend, or second Agent runtime
S3 scheduling constraint = borrow ready-node/concurrency/timeout/cancel/ledger/trace mechanics only after PlanGraph validation; never infer execution from LLM Tool Calls
Deferred Phase 3+ workstream = sap-nexus-capability-matching-contract
Reserved executor workstream = sap-nexus-sql-read-executor-contract
MVP Knowledge/RAG = reserved interface only; no knowledge source, vector store, embedding retrieval or cross-session similar-question retrieval
Reserved composition scope = general Dynamic Planner, multi-WRITE/Saga, automatic compensation and free LLM Tool Calling
Triggered memory candidate = sap-nexus-governed-user-memory-pilot; user preferences only, never business facts, approval, policy, or execution authority
No branch creation unless user explicitly asks
```

### Architecture Maturity & Current Status

> Moved from `docs/wiki/sap-nexus-agent-technical-architecture.md` §1.1. Architecture retains only the maturity-level definitions and fail-closed boundaries; this table is the structured maturity overview and the single home for current maturity attribution and next-step status, so the baseline does not re-version on every progress change. The "Key current scope" notes above supplement it with current decisions, blockers, and scope boundaries not captured in the table.

| 成熟度 | 内容 | 当前处理 |
|---|---|---|
| `Live` | `JCO_RFC` read path、`MM.Inventory.GetAvailability`、`ODATA` read path（PO 列表）、`MM.PurchaseOrder.GetList`（status=active）、CallPlan、Gateway validate / execute、ExecutionResult、ReasoningFact、TraceSpan、Eval Harness seed cases | 继续作为 MVP live baseline |
| `Completed Pilot` | sandbox-only write vertical slice | 已完成并归档；保留外部审批、参数快照、反重放和 stateful JCo LUW 基线 |
| `Completed Foundation` | `sap-nexus-semantic-planning-foundation` | S1 Fact Type、Capability Relation、GoalSpec、PlanGraph、Registry Snapshot、immutable graph 和 deterministic validator 已实现、验证并归档到 `openspec/changes/archive/2026-07-19-sap-nexus-semantic-planning-foundation/` |
| `Completed Design` | `sap-nexus-planner-dry-run` (S2-A + S2-B) | 五态 `MatchDecision`、多意图/歧义检测、visibility pre-filter、matcher Eval 6/6、progressive `CapabilityCard` + deterministic `PlanCompiler` dry-run 已实现、验证并归档到 `openspec/changes/archive/2026-07-25-sap-nexus-planner-dry-run/`；不执行 Gateway / SAP |
| `Completed Capability` | `sap-nexus-agent-conversational-context`、`sap-nexus-multi-value-batch-query` | 即时多轮对话上下文和 READ-only 多值批量查询已实现；durable Run/Session 已由 P0B 接管；详见 runbook 12 |
| `Completed Foundation` | P0B trusted/durable runtime four-part delivery | durable Run/Session、trusted principal、durable approval、ownership/lease、incremental SSE + reconnect 均已归档；它们是完整 Agent 的运行基础，不等于多能力执行 |
| `Completed Foundation` | `sap-nexus-governed-context-registry-snapshot` (Runbook 13) | GovernedContext/SnapshotLease/VisibleCapabilitySet/PlannerFailure 数据结构、同 snapshotId 端到端绑定、principal 透传 + visibility pre-filter、CapabilityCard 安全投影、5 种 PlannerFailure error_type 结构化 fail-closed 已实现、验证并归档到 `openspec/changes/archive/2026-08-03-sap-nexus-governed-context-registry-snapshot/`；不执行多能力 PlanExecutor |
| `Completed Foundation` | 完整 Agent Runbooks 14-19 | LLM-first recall、PlanGraph v2、READ PlanExecutor、deterministic OutputProjection、RecommendationDecision 与 grounded Narrative 已实现、验证并归档；这些 runbook 各自仅交付 component/Eval，后由 Runbook 22 完成 offline coordinator 接线 |
| `Completed Capability` | Runbook 20 Workbench plan/evidence experience | Governed event projection、durable replay integrity 与八分区 Workbench component/UI integration 已实现、验证并归档；fixtures/UI 不构成 live execution、Human Approval 或 SAP WRITE 证据 |
| `Completed Capability` | Runbook 21 read-to-write Action governance | 单 run owner HITL confirmation、完整 subject revalidation、durable exactly-once continuation 与 Gateway atomic claim 已实现、验证并归档；仅证明 fake/sandbox boundary，未执行 live SAP WRITE |
| `Completed / Archived Offline` | Runbook 22 | production composition coordinator 与 L1/L2/L3 offline release gate 已实现、验证并归档；`9/9`、`42/42` Native acceptance、`L3_ACTION_GOVERNED`，但 live SAP READ/WRITE 均为 `not_run` |
| `Reserved` | Knowledge/RAG、跨会话相似问题检索、Phase 3+ embedding retrieval/rerank、Graph Registry、通用 Dynamic Planner、多 WRITE/Saga | 保留接口和安全边界，不进入本轮 MVP；不得将预留描述为已实现 |
| `Not In Scope` | 任意 RFC / URL / SQL 执行、生产 write action 自动提交、GraphDB / OWL 运行时主链路 | 明确拒绝或另立 change |

近期约束：

- 第二条 live read capability、sandbox write pilot、S1、S2-A/S2-B、会话/批量能力、P0B 和 Runbooks 13-22 均已完成并归档；live WRITE smoke 仍须针对精确 Action subject 另行取得 Human Approval。
- 版本记录和路线图优先体现能力落地、评测回归和 write 纵切，而不是继续增加低成本架构占位。
- 已有 reserved executor 只保留 fail-closed 边界，不能被解读为当前实现承诺。

---

## Runbook Index

Runbooks are numbered by workstream creation order, not by roadmap row or calendar day. The numeric prefix is stable and is NOT resequenced when a workstream's status later changes - an Archived runbook may therefore appear after Deferred/Reserved ones (e.g., 11 after 08-10). Cross-reference workstreams by name, not by runbook number. Track session dates and status in the runbook version table and session closeout sections.

| Order | Runbook | Version | Status | Last Updated | Purpose |
|---|---|---|---|---|---|
| `01` | `01-capability-registry-gateway.md` | `v0.3.0` | Archived | `2026-06-20` | Completed Gateway/Registry baseline; archived `sap-nexus-capability-registry-gateway` |
| `02` | `02-agent-callplan-evidence.md` | `v1.0.0` | Archived | `2026-06-20` | Completed Python Agent CallPlan, Gateway client, ReasoningFact, Narrator, and evals |
| `03` | `03-agent-workbench-console.md` | `v1.0.5` | Archived | `2026-07-25` | Internal Agent Workbench Console baseline, live Agent runtime correction, MD04 inventory BAPI correction, Notion-style chat layout evolution (2026-07-09), Hero copy/visual tweak + JCo native-lib troubleshooting note (2026-07-25) |
| `04` | `04-registry-ontology-contract.md` | `v0.6.1` | Archived | `2026-06-25` | Completed Registry schema, OWL skeleton, multi-executor binding including `REST_JSON`, capability contract validation, and eval linkage after Workbench Console |
| `05` | `05-gateway-execution-contract.md` | `v0.2.1` | Archived | `2026-06-28` | Completed and archived unified technical execution request/result, binding dispatcher contract, JCo compatibility, and Gateway redaction / trace consistency |
| `06` | `06-eval-harness-seed.md` | `v0.2.0` | Implemented | `2026-07-04` | First Eval Harness seed cases and bad case regression contract implemented directly |
| `07` | `07-odata-gateway-read-pilot.md` | `v0.2.1` | Implemented / Active | `2026-07-09` | OData Gateway Read Pilot plus archived PO item detail/filter activation; live PO smoke passed after SICF reactivation |
| `08` | `08-capability-matching-contract.md` | `v0.3.2` | Completed / Archived | `2026-08-03` | S2-A five-state matching contract is closed; runbooks 13-14 are successors, while Phase 3+ scale-up remains a separate trigger-based workstream |
| `09` | `09-sql-read-executor-contract.md` | `v0.2.0` | Reserved | `2026-06-28` | Reserved `SQL_READ` safety boundary; not a near-term runtime priority before Eval seed, second read, and sandbox write pilot |
| `10` | `10-capability-composition-contract.md` | `v0.3.10` | Completed / Archived | `2026-08-03` | S1/S2 composition contract is closed at deterministic PlanGraph dry-run; runbooks 13-22 exclusively own the implementation continuation |
| `11` | `11-sandbox-write-vertical-slice.md` | `v0.2.26` | Completed / Archived | `2026-07-17` | Sandbox PR `10137471` committed; external approval, Gateway anti-replay/hash/atomic claim, stateful JCo LUW and replay-complete trace verified; main spec `pr-create-action` merged; no additional SAP WRITE |
| `12` | `12-conversational-context-and-multi-value-batch.md` | `v0.1.2` | Completed / Archived | `2026-08-03` | Conversation and READ-only batch workstream is closed; P0B supersedes its storage baseline and runbook 14 is the next Agent entry |
| `13` | `13-governed-context-registry-snapshot.md` | `v0.1.1` | Completed / Archived | `2026-08-03` | Bind principal, visibility, matcher, planner, executor and approval to one RegistrySnapshot; archived `sap-nexus-governed-context-registry-snapshot` |
| `14` | `14-governed-intent-capability-recall.md` | `v0.2.0` | Completed / Archived | `2026-08-03` | LLM-first IntentEnvelope, closed-set recall, bounded rerank, discard detection, decision replay fields, cross-turn SHOW_OPTIONS/ESCALATE continuation; IntentParseResult removal deferred (bridge); archived `sap-nexus-governed-intent-capability-recall` |
| `15` | `15-semantic-plan-authoring-v2.md` | `v0.2.0` | Implemented / Archived | `2026-08-04` | Compile advisory goals into deterministic PlanGraph v2 with parameter provenance and READ/WRITE partition; 330 pytest (v1 298 + v2 32) / 18 openspec pass |
| `16` | `16-read-plan-executor.md` | `v0.1.0` | Implemented / Archived | `2026-08-04` | Execute validated READ nodes with ready-node scheduling and durable ledger; archived change `openspec/changes/archive/2026-08-04-sap-nexus-read-plan-executor/`; 954 pytest / 174 frontend tests / 19 openspec pass |
| `17` | `17-composite-fact-output-projection.md` | `v0.2.0` | Implemented / Archived | `2026-08-05` | Versioned deterministic OutputProjection and MaterialSupplySnapshot at component/Eval scope; archived `sap-nexus-output-projection-registry`; 251 frontend tests / build / 20 openspec pass |
| `18` | `18-recommendation-decision-plan.md` | `v0.2.0` | Implemented / Archived | `2026-08-05` | Snapshot-bound RuleSet + deterministic input sufficiency -> replayable RecommendationPlan and at most one pending ActionProposal; component/Eval only |
| `19` | `19-grounded-narrative-orchestration.md` | `v0.2.0` | Implemented / Archived | `2026-08-05` | Deterministic grounded NarrativeEnvelope, strict lossless LLM rewrite validator, timeout/invalid template fallback and grounding Eval; component/Eval only |
| `20` | `20-workbench-plan-evidence-experience.md` | `v0.2.0` | Implemented / Archived | `2026-08-05` | Governed event/replay contract and responsive plan/evidence Workbench; proposal-only is read-only; no orchestrator, new approval or SAP WRITE |
| `21` | `21-read-to-write-action-governance.md` | `v0.2.0` | Completed / Archived | `2026-08-05` | Human-approved, exactly-once single Action after multi-READ reasoning; fake/sandbox evidence only |
| `22` | `22-end-to-end-agent-eval-release-gate.md` | `v0.2.0` | Completed / Archived | `2026-08-05` | Production composition coordinator plus offline L1/L2/L3 release gates; Native archive `docs/comet/archive/2026-08-05-sap-nexus-end-to-end-agent-eval-release-gate/`; live SAP smoke not run |

Versioning rules (**historical** — they applied while runbooks were maintained, and apply again only
if a new workstream runbook is ever deliberately opened):

- Increment the runbook version when the source-of-truth status, next action, or verification evidence changes.
- Append session closeout notes inside the same workstream runbook when the work continues in that stream.
- Create a new numbered runbook only for a new workstream or recommended OpenSpec / Comet change.
- Do not encode `day1`, `day2`, or future calendar assumptions in file names.

---

## Session Closeout Template

**Historical.** Closing a Comet change no longer writes a runbook (see "How To Use This Directory").
This structure is retained only for the case where a new workstream runbook is deliberately opened:

```markdown
## Session Closeout - YYYY-MM-DD

### Completed

- ...

### Verified

- Command: `...`
- Result: ...

### Blockers

- ...

### Next Start Here

1. ...
2. ...
3. ...
```

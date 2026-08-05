# SAP Nexus Agent Runbooks

This directory stores session-start guides for continuing SAP Nexus Agent work across workstreams and sessions.

Use these runbooks before coding so each session starts from the same source of truth, current scope, verification targets, and safety constraints.

---

## How To Use This Directory

At the start of each work session:

1. Read this file.
2. Read the current workstream runbook from the index below.
3. Check `git status --short`.
4. Confirm whether there are active OpenSpec changes with `openspec list --json`.
5. Continue from the next unchecked or unverified milestone in the runbook.
6. At the end of the session, update the current runbook version or create the next numbered workstream runbook with:
   - what changed
   - what was verified
   - blockers
   - exact next action

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

Key current scope (session-start details; structured maturity overview in the "Architecture Maturity & Current Status" table below):

```text
Live capability baseline = 2 READ Functions + 1 sandbox-governed Action
Current inventory BAPI = BAPI_MATERIAL_STOCK_REQ_LIST (MD04 stock/requirements list)
Gateway = Java JCo Gateway included in first MVP
Current completed change = sap-nexus-capability-registry-gateway archived
Current completed change = sap-nexus-agent-callplan-evidence archived
Current completed change = sap-nexus-agent-llm-intent-adapter archived
Current completed change = sap-nexus-agent-workbench-console archived
Current completed correction = sap-nexus-workbench-live-agent-runtime archived
Current completed change = sap-nexus-inventory-md04-stock-req-list archived
Current completed change = sap-nexus-registry-ontology-contract archived
Current completed change = sap-nexus-gateway-execution-contract archived
Current completed workstream = sap-nexus-eval-harness-seed implemented directly
Current completed change = sap-nexus-odata-gateway-read-pilot implemented and PO OData activated
Current completed change = po-odata-item-detail-filter archived at openspec/changes/archive/2026-07-09-po-odata-item-detail-filter/
Current completed change = workbench-notion-chat-layout archived at openspec/changes/archive/2026-07-09-workbench-notion-chat-layout/ (Notion-style two-column chat layout, tweak workflow, verify passed)
Current completed change = sap-nexus-sandbox-write-vertical-slice archived at openspec/changes/archive/2026-07-17-sap-nexus-sandbox-write-vertical-slice/; sandbox PR 10137471 committed; external approval, immutable snapshot, single execution, stateful JCo LUW and replay-complete trace verified
OpenHarness comparison decision = use as design reference only; do not add runtime dependency or free SAP tool-calling
DeerFlow adoption decision = use as design reference only; do not add deerflow-harness, DeerFlow Gateway/frontend, or a second Agent runtime
Confirmed first composition scenario = MM.Inventory.GetAvailability + MM.PurchaseOrder.GetList -> MaterialSupplySnapshot
Current semantic planning verification = docs/superpowers/reports/2026-07-19-sap-nexus-semantic-planning-foundation-verify.md
P0A source-of-truth/repository hygiene = completed (2026-07-25): docs/status/paths synchronized, editable-install finder + .venv shebangs repointed from stale zl-projects to GitHub_Projects, runtime traces gitignored (runtime/* only .gitkeep tracked); no runtime behavior change
Current completed change = sap-nexus-planner-dry-run (S2-A + S2-B implemented + verified + archived 2026-07-25 at openspec/changes/archive/2026-07-25-sap-nexus-planner-dry-run/): five-state MatchDecision, multi-intent/ambiguity/visibility, matcher Eval 6/6, progressive CapabilityCard + deterministic PlanCompiler dry-run (3/3 + 1 pending); no Gateway/SAP execution
Current completed change = sap-nexus-agent-conversational-context (row 19A archived 2026-07-26 at openspec/changes/archive/2026-07-26-sap-nexus-agent-conversational-context/): instant multi-turn sticky-CLARIFY, ConversationContext signature, authority/untrusted-data history re-injection, frontend conversationId + CLI --context; process-local, pre-P0B, CLARIFY cross-turn only
Current completed change = sap-nexus-multi-value-batch-query (row 19B archived 2026-07-27): multi_parameters split + expand_combinations + awaiting_batch_confirm (no execute) + continue_batch per-combo execution + narrate_inventory_facts aggregation; workbench/CLI/API/SSE end-to-end; READ-only v1 (Actions fall to awaiting_approval); includes llm-intent-enhancement + fix-batch-confirm-loop
Current completed change = sap-nexus-durable-state-foundation (P0B 项1 archived 2026-08-02 at openspec/changes/archive/2026-08-02-sap-nexus-durable-state-foundation/): durable Run/Sessions JSONL store replacing process-local Maps, run ownership/lease fail-closed, structured checkpoint reference, idempotent continuation (3-segment key), three-layer state stratification (§4.2.1); single-worker durable, store-agnostic interface reserved for multi-worker; 57 tests pass. P0B row 22 split into 4 changes: 项2 trusted-principal-model 已归档（见下行）/ 项3 durable-approval-store / 项4 incremental-sse-reconnect 待续
Current completed change = sap-nexus-trusted-principal-model (P0B 项2 archived 2026-08-02 at openspec/changes/archive/2026-08-02-sap-nexus-trusted-principal-model/): TrustedPrincipal/PrincipalRole/DataScope server-owned model, PrincipalInjector + LocalPlaceholderPrincipalInjector (injectPrincipal ignores request body, anti-prompt-injection), durable Run/Sessions bind principalId (required, backfill local-user-0001 for legacy), cross-principal fail-closed (read getAgentRunEvents returns [] / write decide+confirm throw not-found, ownership check before lease claim §4.1, getSession + conversationStore.load fail-closed), 4 route handlers server-owned injection (POST/approval/batch/stream); 76 tests pass; main spec merge trusted-principal-scope (ADDED 4) + durable-run-state (MODIFIED principalId binding + list/load filter). 项3 durable-approval-store 已归档（见下行）/ 项4 incremental-sse-reconnect 待续
Current completed change = sap-nexus-durable-approval-store (P0B 项3 archived 2026-08-02 at openspec/changes/archive/2026-08-02-sap-nexus-durable-approval-store/): FileDurableApprovalStore replacing InMemoryApprovalStore (durable ApprovalRecord persistence + cross-restart recoverAll/reconcile + cross-worker claim/lease anti-replay + LeaseOutcome three-state Claimed/Rejected/ForceClaimed + striped ReentrantLock + FileChannel.lock + atomic tmp+rename + @Primary wiring + @PostConstruct startup recovery); 176 tests pass; main spec merge durable-approval-store (ADDED 4 requirements). 项4 incremental-sse-reconnect 已归档（见下行）
Current completed change = sap-nexus-incremental-sse-reconnect (P0B 项4 archived 2026-08-02 at openspec/changes/archive/2026-08-02-sap-nexus-incremental-sse-reconnect/): incremental SSE + cursor reconnect (event builders -> async emitter emitEventsFromOutcome/emitApprovalEvents/emitBatchEvents + createAgentRun/decideAgentRunApproval/confirmAgentRunBatch fire-and-forget background executeRunnerInBackground/executeApprovalInBackground/executeBatchInBackground + stream route ReadableStream polling cursor/terminal/backpressure desiredSize + client AgentConsole lastSequence onerror ?cursor=N reconnect + §4.4 rejection run_failed terminal fix + principal auth preserved); 88 tests pass; main spec merge sse-cursor-reconnect (ADDED 4 requirements). P0B row 22 全部 4 项归档完成
Current completed change = sap-nexus-governed-context-registry-snapshot (Runbook 13 archived 2026-08-03 at openspec/changes/archive/2026-08-03-sap-nexus-governed-context-registry-snapshot/): GovernedContext + SnapshotLease + VisibleCapabilitySet + PlannerFailure 数据结构；同一 run 的 intent/matcher/planner/approval 共享非空 snapshotId；principal 透传 + visibility pre-filter（进入 LLM prompt 前移除）+ CapabilityCard 安全投影；snapshot 漂移/source load 失败/visibility denial 结构化 fail-closed（5 种 error_type）；ApprovalRecord 携带 registry_snapshot_id。pytest 836 passed/1 skipped；main spec merge governed-context-registry-snapshot (ADDED 6) + planner-dry-run (MODIFIED 3) + pr-create-action (MODIFIED 1) + semantic-match-decision (ADDED 1 + MODIFIED 1) + trusted-principal-scope (ADDED 1)。
Current completed change = sap-nexus-governed-intent-capability-recall (Runbook 14 archived 2026-08-03 at openspec/changes/archive/2026-08-03-sap-nexus-governed-intent-capability-recall/): LLM-first IntentEnvelope, closed-set recall, bounded rerank, discard detection and replayable five-state decision; 950 pytest / 10 eval / 17 openspec pass
Current completed change = sap-nexus-semantic-plan-authoring-v2 (Runbook 15 archived 2026-08-04): deterministic PlanGraph v2 with parameter provenance and READ/WRITE partition; 330 focused pytest / 953+1 skipped full pytest / 18 openspec pass
Current completed change = sap-nexus-read-plan-executor (Runbook 16 archived 2026-08-04 at openspec/changes/archive/2026-08-04-sap-nexus-read-plan-executor/): READ-only PlanExecutor consuming validated PlanGraph v2 readPartition; PlanGraphV2Parser + NodeStateMachine + DurableNodeLedger + DagScheduler + FakeGateway + SseEmitter + PlanExecutor with timeout/cancel/restart-recovery/idempotent-replay/dependency-blocking/lease-conflict-fail-closed; Action nodes BLOCKED_APPROVAL; 954 pytest / 174 frontend tests / 19 openspec pass
Current completed change = sap-nexus-output-projection-registry (Runbook 17 archived 2026-08-05 at openspec/changes/archive/2026-08-05-sap-nexus-output-projection-registry/): versioned OutputProjectionRegistry, ProjectionInputAssembler, capability FactBuilder, MaterialSupplySnapshot, deterministic completeness/freshness/lineage/limitations/hash and executor projection payload recovery; 251 frontend tests / production build / 20 openspec pass; production orchestrator and projectionRef wiring remain deferred
Current completed change = sap-nexus-recommendation-decision-plan (Runbook 18 Native archived 2026-08-05): snapshot-bound exact RuleSetRegistry, deterministic RecommendationDecisionEngine, input sufficiency/freshness/governance gates, replayable RecommendationPlan and at most one pending_approval ActionProposal; 316 frontend tests / production build / 954+1 skipped Agent tests / PR Eval 9/9 / call-plan Eval 7/7 / 20 openspec pass; component/Eval only, no orchestrator or SAP WRITE
Current completed change = sap-nexus-grounded-narrative-orchestration (Runbook 19 Native archived 2026-08-05): deterministic NarrativeInputProjection, strict lossless LLM JSON rewrite validation, timeout/invalid fallback, traceable NarrativeEnvelope, zh/en status rendering and grounding Eval; 352 frontend tests / production build / 45 narrator tests / 954+1 skipped Agent gate / 20 openspec pass; component/Eval only, no orchestrator, Human Approval or SAP WRITE
Planned sequence = runbooks 13-19 implemented and archived -> runbooks 20-22 complete Workbench, governed Action and release-gate delivery
S3 scheduling input = borrow ready-node/concurrency/timeout/cancel/ledger/trace mechanics only after PlanGraph validation; never infer execution from LLM Tool Calls
S3 output foundation = deterministic OutputProjection with freshness, completeness, limitations and Fact lineage implemented at component/Eval scope; partial failure remains incomplete
Completed platform gate = sap-nexus-trusted-durable-runtime-foundation; all four P0B changes archived 2026-08-02
Triggered memory candidate = sap-nexus-governed-user-memory-pilot; user preferences only, never business facts, approval, policy, or execution authority
Live blocker = none for PO OData read; SAP SICF was reactivated and PO live smoke passed
Deferred Phase 3+ workstream = sap-nexus-capability-matching-contract
Reserved executor workstream = sap-nexus-sql-read-executor-contract
Current composition runtime = PlanExecutor, deterministic OutputProjection, RecommendationDecision and grounded Narrative implemented at component/Eval scope; production orchestrator/projectionRef wiring and end-to-end multi-capability business composition are not yet live; next implementation entrypoint is Runbook 20
Complete Agent target = runbooks 13-22: governed context -> LLM-first recall -> PlanGraph v2 -> READ executor -> projection -> recommendation -> grounded narrative -> Workbench -> single approved Action -> release gate
MVP Knowledge/RAG = reserved interface only; no knowledge source, vector store, embedding retrieval or cross-session similar-question retrieval
Reserved composition scope = general Dynamic Planner, multi-WRITE/Saga, automatic compensation and free LLM Tool Calling
No branch creation unless user explicitly asks
```

### Architecture Maturity & Current Status

> Moved from `docs/wiki/sap-nexus-agent-technical-architecture.md` §1.1. Architecture retains only the maturity-level definitions and fail-closed boundaries; this table is the structured maturity overview and the single home for current maturity attribution and next-step status, so the baseline does not re-version on every progress change. The "Key current scope" notes below supplement it with archive paths, blockers, sequence and other session-start details not captured in the table.

| 成熟度 | 内容 | 当前处理 |
|---|---|---|
| `Live` | `JCO_RFC` read path、`MM.Inventory.GetAvailability`、`ODATA` read path（PO 列表）、`MM.PurchaseOrder.GetList`（status=active）、CallPlan、Gateway validate / execute、ExecutionResult、ReasoningFact、TraceSpan、Eval Harness seed cases | 继续作为 MVP live baseline |
| `Completed Pilot` | sandbox-only write vertical slice | 已完成并归档；保留外部审批、参数快照、反重放和 stateful JCo LUW 基线 |
| `Completed Foundation` | `sap-nexus-semantic-planning-foundation` | S1 Fact Type、Capability Relation、GoalSpec、PlanGraph、Registry Snapshot、immutable graph 和 deterministic validator 已实现、验证并归档到 `openspec/changes/archive/2026-07-19-sap-nexus-semantic-planning-foundation/` |
| `Completed Design` | `sap-nexus-planner-dry-run` (S2-A + S2-B) | 五态 `MatchDecision`、多意图/歧义检测、visibility pre-filter、matcher Eval 6/6、progressive `CapabilityCard` + deterministic `PlanCompiler` dry-run 已实现、验证并归档到 `openspec/changes/archive/2026-07-25-sap-nexus-planner-dry-run/`；不执行 Gateway / SAP |
| `Completed Capability` | `sap-nexus-agent-conversational-context`、`sap-nexus-multi-value-batch-query` | 即时多轮对话上下文和 READ-only 多值批量查询已实现；durable Run/Session 已由 P0B 接管；详见 runbook 12 |
| `Completed Foundation` | P0B trusted/durable runtime four-part delivery | durable Run/Session、trusted principal、durable approval、ownership/lease、incremental SSE + reconnect 均已归档；它们是完整 Agent 的运行基础，不等于多能力执行 |
| `Completed Foundation` | `sap-nexus-governed-context-registry-snapshot` (Runbook 13) | GovernedContext/SnapshotLease/VisibleCapabilitySet/PlannerFailure 数据结构、同 snapshotId 端到端绑定、principal 透传 + visibility pre-filter、CapabilityCard 安全投影、5 种 PlannerFailure error_type 结构化 fail-closed 已实现、验证并归档到 `openspec/changes/archive/2026-08-03-sap-nexus-governed-context-registry-snapshot/`；不执行多能力 PlanExecutor |
| `Completed Foundation` | 完整 Agent Runbooks 14-19 | LLM-first recall、PlanGraph v2、READ PlanExecutor、deterministic OutputProjection、RecommendationDecision 与 grounded Narrative 已实现、验证并归档；composition/recommendation/narrative 仅完成 component/Eval 范围，生产 orchestrator 接线仍未完成 |
| `Planned` | 完整 Agent Runbooks 20-22 | Workbench、单 Action 人审闭环和 E2E release gate |
| `Reserved` | Knowledge/RAG、跨会话相似问题检索、Phase 3+ embedding retrieval/rerank、Graph Registry、通用 Dynamic Planner、多 WRITE/Saga | 保留接口和安全边界，不进入本轮 MVP；不得将预留描述为已实现 |
| `Not In Scope` | 任意 RFC / URL / SQL 执行、生产 write action 自动提交、GraphDB / OWL 运行时主链路 | 明确拒绝或另立 change |

近期约束：

- 第二条 live read capability、sandbox write pilot、S1、S2-A/S2-B、会话/批量能力、P0B 和 Runbooks 13-19 均已完成；下一实施入口固定为 Runbook 20，不直接跳到 WRITE。
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
| `20` | `20-workbench-plan-evidence-experience.md` | `v0.1.0` | Planned / Current Entry | `2026-08-03` | Full plan, node, fact, recommendation, narrative, approval and replay UX |
| `21` | `21-read-to-write-action-governance.md` | `v0.1.0` | Planned | `2026-08-03` | Human-approved, exactly-once single Action after multi-READ reasoning |
| `22` | `22-end-to-end-agent-eval-release-gate.md` | `v0.1.0` | Planned | `2026-08-03` | L1 single-capability, L2 multi-READ and L3 READ-to-WRITE release gates |

Versioning rules:

- Increment the runbook version when the source-of-truth status, next action, or verification evidence changes.
- Append session closeout notes inside the same workstream runbook when the work continues in that stream.
- Create a new numbered runbook only for a new workstream or recommended OpenSpec / Comet change.
- Do not encode `day1`, `day2`, or future calendar assumptions in file names.

---

## Session Closeout Template

Use this structure when writing the next runbook or appending session notes:

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

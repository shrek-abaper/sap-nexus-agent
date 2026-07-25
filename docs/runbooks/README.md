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
Planned sequence = archived semantic planning foundation -> [P0A hygiene completed] -> S2-A semantic decision hardening (archived) -> S2-B planner dry-run (archived) -> conditional trusted/durable runtime gate -> PlanGraph-governed read-only composition pilot -> recommendation integration
S3 scheduling input = borrow ready-node/concurrency/timeout/cancel/ledger/trace mechanics only after PlanGraph validation; never infer execution from LLM Tool Calls
S3 output input = deterministic OutputProjection with freshness, completeness, limitations and Fact lineage; partial failure remains incomplete
Conditional platform gate = sap-nexus-trusted-durable-runtime-foundation; not required for local S2, required before shared S3, long approval, multi-worker/HA, or non-sandbox WRITE
Triggered memory candidate = sap-nexus-governed-user-memory-pilot; user preferences only, never business facts, approval, policy, or execution authority
Live blocker = none for PO OData read; SAP SICF was reactivated and PO live smoke passed
Deferred Phase 3+ workstream = sap-nexus-capability-matching-contract
Reserved executor workstream = sap-nexus-sql-read-executor-contract
Current composition runtime = not implemented; architecture requires multi-capability requests to ESCALATE_TO_PLANNER, and S2-A now reliably produces ESCALATE_TO_PLANNER on multi-goal utterances (matcher Eval 6/6); S3 read-only composition pilot remains gated
Reserved composition scope = Dynamic Planner and Write composition; S3 read-only execution remains planned, not implemented
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
| `Next Design` | `sap-nexus-trusted-durable-runtime-foundation` (P0B Conditional Gate) | 共享 S3、长审批、multi-worker/HA 或非 sandbox WRITE 前的硬门禁：trusted principal、durable Run/Approval、ownership/lease、incremental SSE + reconnect；不阻塞本地 S2 |
| `Planned Pilot` | 只读多能力组合“物料库存 + 采购订单供给概览” | S2 验证后分 change 实施；只允许 `sideEffect=none` Function 和 PlanGraph-governed ready-node scheduling |
| `Reserved` | `CDS_ADT`、`CDS_ODATA`、`REST_JSON`、`SQL_READ`、Phase 3+ retrieval / rerank、Graph Registry、Dynamic Planner、Write composition | 保留边界和安全约束；Dynamic Planner 仍需关系本体、Dry-run、Read pilot 和规模/需求证据 |
| `Not In Scope` | 任意 RFC / URL / SQL 执行、生产 write action 自动提交、GraphDB / OWL 运行时主链路 | 明确拒绝或另立 change |

近期约束：

- 第二条 live read capability、sandbox write pilot、S1 semantic planning foundation 和 P0A source-of-truth/repository hygiene 均已完成；现在进入 S2-A Semantic MatchDecision Hardening 和 S2-B Planner Dry-run，不继续增加低价值 executor family 预留。
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
| `08` | `08-capability-matching-contract.md` | `v0.3.0` | S2-A Done / Phase 3+ Scale-up Deferred | `2026-07-25` | S2-A baseline five-state MatchDecision, multi-intent/ambiguity, visibility and matcher Eval done (archived in planner-dry-run); embedding/retrieval/rerank remain Phase 3+ |
| `09` | `09-sql-read-executor-contract.md` | `v0.2.0` | Reserved | `2026-06-28` | Reserved `SQL_READ` safety boundary; not a near-term runtime priority before Eval seed, second read, and sandbox write pilot |
| `10` | `10-capability-composition-contract.md` | `v0.3.8` | S2-A/S2-B Archived; S3 Gate Next | `2026-07-25` | S1 archived; P0A hygiene closed; S2-A/S2-B archived in sap-nexus-planner-dry-run (matcher Eval 6/6, dry-run eval 3/3 + 1 pending); shared S3 is gated by trusted/durable runtime and deterministic OutputProjection |
| `11` | `11-sandbox-write-vertical-slice.md` | `v0.2.26` | Completed / Archived | `2026-07-17` | Sandbox PR `10137471` committed; external approval, Gateway anti-replay/hash/atomic claim, stateful JCo LUW and replay-complete trace verified; main spec `pr-create-action` merged; no additional SAP WRITE |

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

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
Immediate prerequisite = P0A source-of-truth/repository hygiene; synchronize docs/status/paths, repair stale editable-install path, and stop tracking real runtime traces without changing runtime behavior
Next recommended design = sap-nexus-planner-dry-run (roadmap row 19; S2-A five-state MatchDecision + multi-intent/ambiguity/visibility/Eval, then S2-B progressive CapabilityCard + deterministic dry-run; no Gateway/SAP execution)
Planned sequence = archived semantic planning foundation -> P0A hygiene -> S2-A semantic decision hardening -> S2-B planner dry-run -> conditional trusted/durable runtime gate -> PlanGraph-governed read-only composition pilot -> recommendation integration
S3 scheduling input = borrow ready-node/concurrency/timeout/cancel/ledger/trace mechanics only after PlanGraph validation; never infer execution from LLM Tool Calls
S3 output input = deterministic OutputProjection with freshness, completeness, limitations and Fact lineage; partial failure remains incomplete
Conditional platform gate = sap-nexus-trusted-durable-runtime-foundation; not required for local S2, required before shared S3, long approval, multi-worker/HA, or non-sandbox WRITE
Triggered memory candidate = sap-nexus-governed-user-memory-pilot; user preferences only, never business facts, approval, policy, or execution authority
Live blocker = none for PO OData read; SAP SICF was reactivated and PO live smoke passed
Deferred Phase 3+ workstream = sap-nexus-capability-matching-contract
Reserved executor workstream = sap-nexus-sql-read-executor-contract
Current composition runtime = not implemented; architecture requires multi-capability requests to ESCALATE_TO_PLANNER, but current parser/selector does not yet reliably detect every multi-goal utterance; S2-A closes this gap
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
| `Next Design` | `sap-nexus-planner-dry-run` | S2-A 先实现五态 `MatchDecision`、多意图/歧义检测和候选可见性边界；S2-B 再用 progressive `CapabilityCard` discovery 生成候选，由 deterministic PlanCompiler 输出 dry-run；两者均不执行 Gateway / SAP |
| `Planned Pilot` | 只读多能力组合“物料库存 + 采购订单供给概览” | S2 验证后分 change 实施；只允许 `sideEffect=none` Function 和 PlanGraph-governed ready-node scheduling |
| `Reserved` | `CDS_ADT`、`CDS_ODATA`、`REST_JSON`、`SQL_READ`、Phase 3+ retrieval / rerank、Graph Registry、Dynamic Planner、Write composition | 保留边界和安全约束；Dynamic Planner 仍需关系本体、Dry-run、Read pilot 和规模/需求证据 |
| `Not In Scope` | 任意 RFC / URL / SQL 执行、生产 write action 自动提交、GraphDB / OWL 运行时主链路 | 明确拒绝或另立 change |

近期约束：

- 第二条 live read capability、sandbox write pilot 和 S1 semantic planning foundation 均已完成；当前先收敛 P0A 文档/仓库卫生，再进入 S2-A Semantic MatchDecision Hardening 和 S2-B Planner Dry-run，不继续增加低价值 executor family 预留。
- 版本记录和路线图优先体现能力落地、评测回归和 write 纵切，而不是继续增加低成本架构占位。
- 已有 reserved executor 只保留 fail-closed 边界，不能被解读为当前实现承诺。

---

## Runbook Index

Runbooks are ordered by a numeric prefix following the implementation roadmap order and status (implemented/archived first, Reserved/Deferred after), not by calendar day. The prefix is stable in normal operation but may be resequenced when it diverges from the roadmap and actual status, with all cross-references updated in the same change. Track session dates in the runbook version table and session closeout sections.

| Order | Runbook | Version | Status | Last Updated | Purpose |
|---|---|---|---|---|---|
| `01` | `01-capability-registry-gateway.md` | `v0.3.0` | Archived | `2026-06-20` | Completed Gateway/Registry baseline; archived `sap-nexus-capability-registry-gateway` |
| `02` | `02-agent-callplan-evidence.md` | `v1.0.0` | Archived | `2026-06-20` | Completed Python Agent CallPlan, Gateway client, ReasoningFact, Narrator, and evals |
| `03` | `03-agent-workbench-console.md` | `v1.0.4` | Archived | `2026-07-14` | Completed internal Agent Workbench Console, live Agent runtime correction, MD04 inventory BAPI correction, and Notion-style chat layout evolution (archived 2026-07-09) |
| `04` | `04-registry-ontology-contract.md` | `v0.6.1` | Archived | `2026-06-25` | Completed Registry schema, OWL skeleton, multi-executor binding including `REST_JSON`, capability contract validation, and eval linkage after Workbench Console |
| `05` | `05-gateway-execution-contract.md` | `v0.2.1` | Archived | `2026-06-28` | Completed and archived unified technical execution request/result, binding dispatcher contract, JCo compatibility, and Gateway redaction / trace consistency |
| `06` | `06-eval-harness-seed.md` | `v0.2.0` | Implemented | `2026-07-04` | First Eval Harness seed cases and bad case regression contract implemented directly |
| `07` | `07-odata-gateway-read-pilot.md` | `v0.2.1` | Implemented / Active | `2026-07-09` | OData Gateway Read Pilot plus archived PO item detail/filter activation; live PO smoke passed after SICF reactivation |
| `08` | `08-capability-matching-contract.md` | `v0.3.0` | S2-A Next / Scale-up Deferred | `2026-07-24` | Baseline five-state MatchDecision, multi-intent/ambiguity, visibility and matcher Eval now; embedding/retrieval/rerank remain Phase 3+ |
| `09` | `09-sql-read-executor-contract.md` | `v0.2.0` | Reserved | `2026-06-28` | Reserved `SQL_READ` safety boundary; not a near-term runtime priority before Eval seed, second read, and sandbox write pilot |
| `10` | `10-capability-composition-contract.md` | `v0.3.5` | S1 Archived; S2-A Next; Runtime Reserved | `2026-07-25` | S1 archived; P0A, S2-A decision hardening and S2-B dry-run are next; shared S3 is gated by trusted/durable runtime and deterministic OutputProjection |
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

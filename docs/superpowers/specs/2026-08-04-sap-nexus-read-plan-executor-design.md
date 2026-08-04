---
comet_change: sap-nexus-read-plan-executor
role: technical-design
canonical_spec: openspec
status: draft
---

# READ PlanExecutor 技术设计（sap-nexus-read-plan-executor）

> 本 Design Doc 深化 open 阶段 `design.md` 的高层框架（D1-D6），并落实 brainstorming 确认的 6 个 Open Questions（Q1-Q6）方案。OpenSpec delta spec（`specs/read-plan-executor/spec.md`）是上游事实源；本文不重写需求，仅细化实现、契约与边界。所有代码引用均为当前磁盘事实（2026-08-04 codegraph 核实）。

## 1. Context（现状与缺口）

### 1.1 已交付基础

- **PlanGraph v2**（Runbook 15，已归档）：`plan_compiler_v2.py::compile_plan_v2` 产出 `PlanCompileResult`，携带 v2 `plan_graph` dict（`readPartition` / `actionPartition` / `projectionRef` / `ruleSetRefs` + `registeredDefault` 源）。`validate_plan_graph_v2`（`semantic_planning/validation_v2.py`）复用 S1 validator + 分区/ref 校验。
- **P0B durable runtime**（`frontend/src/runtime/durable/`，TypeScript/Node）：`JsonlRunStore` 实现 `DurableRunStore` 接口；lease（`claim`/`renew`/`release`/force-claim，`jsonl-run-store.ts:71-98`）；events（`appendEvent`:182，每行 fsync）；`CheckpointRef`（`types.ts`，`nodeState: Record<string, unknown>` 当前为预留占位，未填充）；幂等（`markExecuted`:225 / `lookupExecuted`:232，`idempotency/<safekey>.json`）。
- **Gateway execution contract**（Java + Python OData）：per-capability `validate` -> `execute`。
- **单能力执行模型**（当前生产路径）：`agent-runtime-adapter.ts::runLocalPythonAgent`（:727）单次 spawn Python CLI 子进程，返回一个 `WorkbenchOutcome`；`emitEventsFromOutcome`（:359）发单能力 SSE 事件链。

### 1.2 缺口

当前 Agent 链路是**单能力单次**模型：Node 单次 spawn Python，返回一个 `WorkbenchOutcome`。多 READ 节点场景（如 `MM.Inventory.GetAvailability` + `MM.PurchaseOrder.GetList`）无法并发执行、无 durable 节点账本、无恢复/幂等重放。Runbook 15 冻结了 PlanGraph v2 产出但**未接线**到执行链路（Runbook 15 non-goal 明确把 v2 接线留给「Runbook 16 消费时」）。完整 Agent 链路需要消费 PlanGraph v2 的 READ `PlanExecutor`，填补「已验证计划」到「多节点 durable 执行」之间的缺口。

### 1.3 约束（roadmap 红线）

- Runbook 16 **必须直接复用** durable run/lease/event 基础，**不得再建设第二套进程内 PlanExecution store**。
- 不执行 Action 节点、不 replan、不绕过 Gateway。
- 老单能力 SELECT 路径零回归（双链路并存）。

## 2. Goals / Non-Goals

**Goals**

- Node 层 READ `PlanExecutor` 消费已验证 PlanGraph v2 `readPartition`，做 ready-node 调度 + 有限并发。
- durable node ledger 复用 `DurableRunStore`（扩展 `CheckpointRef.nodeState` + 现有 events 流），节点状态机 9 态。
- 超时 / 取消 / 恢复 / 幂等重放：restart 后 `SUCCEEDED` 不重复执行。
- per-node Gateway `validate -> execute`，不绕过。
- fail-closed：Action-in-readPartition、snapshot drift、非法状态转换、lease conflict。
- Q6：把 v2 compiler 接入 orchestrator ESCALATE 路径，使 `WorkbenchOutcome.dryRun` 携带 v2 plan_graph。

**Non-Goals**

- 不执行 Action 节点（保持 `BLOCKED_APPROVAL`）。
- 不自动 replan、不做 Saga/补偿。
- 不改 PlanGraph v2 compiler（Runbook 15 冻结，仅接线）。
- 不实现 OutputProjection（Runbook 17）/ Recommendation（Runbook 18）。
- 不改 Python `orchestrator.run_query` SELECT 单能力路径（D5 双链路）。

## 3. Decisions（D1-D6 + Q1-Q6 落实）

### D1: Executor 位于 Node 层（非 Python）

**选择**：PlanExecutor 在 `frontend/src/runtime/`，读 PlanGraph v2 序列化输出，驱动 ready-node 调度 + per-node Gateway 调用，直接复用 `DurableRunStore`。

**理由**：durable runtime（lease/events/checkpoint/idempotency）在 Node；Python 侧建 durable 适配器会触发「第二套 store」红线或需跨进程 IPC。Python 角色收敛为产 PlanGraph v2（Runbook 15 已交付）。

**备选（拒绝）**：Python 层 executor（durable store 跨进程/第二套 store 代价）；混合（executor 逻辑分裂）。

### D2: node ledger 复用 DurableRunStore（扩展 CheckpointRef.nodeState）

**选择**：节点状态落盘复用 `CheckpointRef.nodeState` + 现有 events 流，不新建 store。`CheckpointRef.nodeState: Record<string, unknown>`（`types.ts`）已为节点状态留位。

**理由**：roadmap 禁止第二套 store。

**备选（拒绝）**：新建 `NodeLedgerStore`（红线）。

### D3: per-node Gateway validate/execute（复用现有 Gateway）

**选择**：每个 READY 节点按 `capabilityId` + 参数走现有 Gateway `/capabilities/{id}/validate` + `/execute`，不绕过、不批量端点。

**理由**：Gateway execution contract 已稳定；不绕过安全边界。

**备选（拒绝）**：批量 Gateway 端点（scope 蔓延 + 改 Gateway contract）。

### D4: 节点状态机 9 态

**选择**：`READY` / `VALIDATING` / `EXECUTING` / `SUCCEEDED` / `FAILED` / `TIMED_OUT` / `CANCELLED` / `BLOCKED_DEPENDENCY` / `BLOCKED_APPROVAL`。非法转换 fail-closed。

**理由**：覆盖 ready 调度、并发、超时、取消、依赖阻塞、审批阻塞、恢复全路径。

### D5: 双链路并存

**选择**：单能力 SELECT 走老路径（`orchestrator.run_query` -> CallPlan -> Gateway）；ESCALATE_TO_PLANNER + 多 READ 走新 Node executor。老路径零回归。

**理由**：避免一次性 rewire 生产 orchestrator；新 executor 独立验证。

### D6: TDD - fake Gateway 先行

**选择**：先用 fake Gateway 完成状态机 + 恢复测试，再接现有 READ integration。

**理由**：状态机/恢复逻辑与 Gateway 解耦验证；runbook §8 起步要求。

### Q6 落实：Python<->Node PlanGraph v2 契约（接线点）

**发现（codegraph 核实）**：orchestrator ESCALATE 路径当前经 `_compile_dry_run_safely`（`orchestrator.py:799-839`）在 line 826 调 v1 `compile_dry_run_from_handoff`（`handoff.py:39`），产出 `DryRunResult`（v1，`plan_compiler.py:77`，`plan_graph` 无 `readPartition`）。v2 `compile_plan_v2_from_handoff`（`handoff.py:110`）已存在且注释明说「v1 untouched」，但**未接线**。

**方案**：把 `_compile_dry_run_safely` 的 v1 调用（line 826）切到 v2 `compile_plan_v2_from_handoff`，使 `AgentOutcome.dry_run`（`orchestrator.py:88`，当前类型 `DryRunResult | None`）携带 v2 `PlanCompileResult`。SELECT 单能力路径不动（D5 成立）。

**超集/向后兼容（已核实）**：
- `PlanCompileResult`（`plan_compiler_v2.py:49`）= `plan_graph` + `gaps` + `governance_flags` + `rationale`（与 v1 `DryRunResult` 同 4 字段）**+ `projection_ref` + `rule_set_refs` + `snapshot_id`**（3 新字段）。v2 是 v1 的字段超集。
- 两者的 `plan_graph` 均为 `dict[str, Any]` camelCase JSON；v2 `plan_graph` 在 v1 键基础上新增 `readPartition`/`actionPartition` 等分区键。
- 前端 `DryRunPlanGraph`（`view-model.ts:66`）只读 `planId`/`goalId`/`executionMode`/`snapshotId?`/`nodes`/`edges`/`topologicalOrder`/`goalOutputs` 子集键 -> v2 保留 v1 键即向后兼容（Task 1.2 核实 v2 `plan_graph` 确实保留这些键）。
- `emitMatchDecisionEventIfPresent`（`agent-runtime-adapter.ts:596`）已把 `outcome.dryRun` 放进 `match_decision_created` SSE payload（:611/:623），Node executor 可直接消费 `outcome.dryRun.plan_graph`。

**类型层面**：`AgentOutcome.dry_run` 由 `DryRunResult | None` 改为 `PlanCompileResult | None`（或 union）；`WorkbenchOutcome.dryRun`（前端 `types.ts:28`）对应放宽/更新。序列化经 `sap_nexus_agent.cli --json` -> Node `JSON.parse`。

### Q1 落实：node ledger 形状

扩展 `CheckpointRef.nodeState` 为结构化 per-node 状态：

```typescript
// CheckpointRef.nodeState: Record<NodeId, NodeLedgerEntry>
type NodeLedgerEntry = {
  state: NodeState;            // 9 态之一
  attempt: number;             // 尝试序号（显式 retry 递增）
  inputHash: string;           // 节点输入参数 hash（幂等键组成）
  resultRef: string | null;    // SUCCEEDED 后的结果引用
  traceSpan: string | null;    // trace 关联
  updatedAt: string;           // ISO 时间戳
};
```

**双写**：nodeState = 权威快照（恢复用，先写）；events = 审计流（SSE 重放用，后 append）。恢复以 nodeState 为准；短期不一致可接受（nodeState 先持久化）。复用 `appendCheckpointRef`（`jsonl-run-store.ts:195`）+ `appendEvent`（:182），不建第二套 store。

### Q2 落实：并发模型

DAG 独立性决定可并发集 + 可配置安全上限（默认 4，env `READ_PLAN_EXECUTOR_MAX_CONCURRENCY` 可调）。runbook「并发只由 DAG 独立性决定」指**调度逻辑**（不靠模型 tool calls 决定能否并发）；上限是 backpressure 保护，避免单 run 占满 worker。复用 PlanGraph v2 edges 做依赖闭包，判定错误 fail-closed。

### Q3 落实：FAILED 恢复策略

- restart 后 FAILED 节点**不自动重试**，保持 FAILED；需显式 retry（新 attempt）。
- 幂等键 = `runId + nodeId + attempt + inputHash`（含 attempt，允许多次尝试）。
- SUCCEEDED 跳过；READY/未完成续跑。

### Q4 落实：per-node SSE 事件

新增**一个**通用事件 `node_state_changed`（携带 `nodeId` / `fromState` / `toState` / `attempt`），覆盖 9 态转换。复用现有 SSE 框架；不新增 7 种细粒度事件类型。与 `emitEventsFromOutcome` 单能力事件正交（新 executor 路径发 node 事件，老路径不变）。

### Q5 落实：plan lease vs run lease

复用 run 级 lease（`DurableRunStore.claim`，`jsonl-run-store.ts:71`），不新增 plan 子 lease。plan 执行是 run 的一个阶段；run lease 已有 claim/renew/release/force-claim 语义。lease conflict（另一 worker 持有）fail-closed。

## 4. 架构与数据流

### 4.1 跨语言边界

```
Python (agent/)                          Node (frontend/src/runtime/)
┌─────────────────────────────┐          ┌──────────────────────────────────┐
│ orchestrator.run_query      │          │ agent-runtime-adapter.ts          │
│  ESCALATE_TO_PLANNER branch │          │  runLocalPythonAgent (spawn CLI)  │
│   └─ _compile_dry_run_safely│── JSON ──│  -> WorkbenchOutcome              │
│       └─ compile_plan_v2_   │  (v2)    │     .dryRun.plan_graph (v2)       │
│          from_handoff (v2)  │          │  PlanExecutor (NEW)               │
│                             │          │   ├─ 反序列化 readPartition        │
│ SELECT path (v1, 不动)      │          │   ├─ ready-node 调度 + DAG 并发    │
│                             │          │   ├─ per-node Gateway validate/exec│
└─────────────────────────────┘          │   ├─ node ledger (CheckpointRef)   │
                                         │   └─ node_state_changed SSE        │
                                         │ DurableRunStore (reuse, P0B)       │
                                         └──────────────────────────────────┘
```

### 4.2 Node executor 执行流

1. 从 `WorkbenchOutcome.dryRun.plan_graph`（v2）反序列化 `readPartition` / 节点 / edges / `snapshotId`。
2. 校验 PlanGraph v2 有效 + `snapshotId` 未漂移；无效/漂移 fail-closed（记录结构化失败，不调 Gateway）。
3. claim run lease（`DurableRunStore.claim`）；lease conflict fail-closed。
4. 从 `CheckpointRef.nodeState` 加载已有节点状态（恢复）；SUCCEEDED 跳过，READY/未完成续跑。
5. ready-node 选择：依赖闭包（基于 edges）全部 SUCCEEDED 才 READY，否则 `BLOCKED_DEPENDENCY`。
6. 有限并发（DAG 独立性 + 安全上限）调度 READY 节点：`validate -> execute`，每节点走 per-node Gateway。
7. 每次状态转换：双写 nodeState（权威）+ events（审计/SSE）+ 发 `node_state_changed` SSE。
8. 超时 -> `TIMED_OUT`（不阻塞独立节点）；取消 -> 未完成 `CANCELLED`（SUCCEEDED 保留）。
9. Action / 非 read-only 节点保持 `BLOCKED_APPROVAL`，不执行、不调 Gateway execute。

## 5. 关键契约（可溯源）

| 契约 | 源位置 | 说明 |
|------|--------|------|
| v2 compiler 入口 | `handoff.py:110 compile_plan_v2_from_handoff` | 薄封装 `compile_plan_v2`，复用 `_build_goal_with_constraints` |
| v1 接线点（待替换） | `orchestrator.py:826 compile_dry_run_from_handoff` | 在 `_compile_dry_run_safely:799` 内 |
| `PlanCompileResult` | `plan_compiler_v2.py:49` | v1 超集（+projection_ref/rule_set_refs/snapshot_id） |
| `DryRunResult` (v1) | `plan_compiler.py:77` | plan_graph/gaps/governance_flags/rationale |
| `AgentOutcome.dry_run` | `orchestrator.py:88` | 类型 DryRunResult\|None -> PlanCompileResult\|None |
| `CheckpointRef.nodeState` | `frontend/src/runtime/durable/types.ts` | Record<string,unknown> -> Record<NodeId,NodeLedgerEntry> |
| lease | `jsonl-run-store.ts:71 claim` / `:92 renew` / `:85 release` | run 级，复用不建子 lease |
| events | `jsonl-run-store.ts:182 appendEvent` / `:195 appendCheckpointRef` | 每行 fsync |
| 幂等 | `jsonl-run-store.ts:225 markExecuted` / `:232 lookupExecuted` | idempotency/<safekey>.json |
| 前端 dryRun 消费 | `view-model.ts:66 DryRunPlanGraph` | 读 v1 子集键，v2 超集向后兼容 |
| SSE dryRun | `agent-runtime-adapter.ts:596 emitMatchDecisionEventIfPresent` | 已在 match_decision_created payload |
| SSE 单能力 | `agent-runtime-adapter.ts:359 emitEventsFromOutcome` | 老路径不变，node 事件正交 |

## 6. Risks / Trade-offs

- **[Q6 Python 侧改动一刀]** ESCALATE 路径 v1->v2 切换 -> 仅改 ESCALATE 路径，SELECT 零回归；v2 已有 Runbook 15 契约测试覆盖。风险：v2 `plan_graph` 是否逐键保留 v1 字段（Task 1.2 核实，若缺失则前端 `DryRunPlanGraph` 解析需适配）。
- **[nodeState + events 双写一致性]** 权威快照与审计流可能短期不一致 -> nodeState 先写（恢复权威），events 后 append（SSE 重放）；恢复以 nodeState 为准。
- **[并发安全]** DAG 独立性判定错误导致错误并发 -> 复用 PlanGraph v2 edges 做依赖闭包，fail-closed。
- **[FAILED 不自动重试]** 可能需要用户/上游显式触发 retry -> 显式 retry 更可控，幂等键含 attempt 支持重试。
- **[v1/v2 双版本 dry-run]** 切换后老 v1 `DryRunResult` 不再产出 -> v2 是 v1 超集，前端解析器兼容；v1 退役交后续。
- **[双链路维护成本]** 老路径冻结，新 executor 为唯一演进面 -> 老路径退役交后续 runbook。

## 7. Migration Plan

- 双链路并存，无需迁移：老单能力 SELECT 路径原样保留；新 executor 处理 ESCALATE + 多 READ。
- 老路径测试（`test_orchestrator.py` 等）保持通过（SELECT 路径不动）。
- 新 executor 独立契约测试 + fake Gateway 状态机/恢复测试 + 现有 READ integration。
- 生产 orchestrator 切换到新 executor 延后至 Runbook 17 消费时评估。

## 8. Test Strategy

TDD：fake Gateway 先行（D6）：
- **状态机**：9 态转换 + 非法转换 fail-closed。
- **恢复**：restart 跳过 SUCCEEDED、续跑 READY、FAILED 保持、幂等重放（相同 key 不重复执行）。
- **调度**：双 READ 并发、dependency 阻塞、超时、取消、partial failure、lease conflict、并发安全上限。
- **integration**：接现有 READ（真实 Gateway validate/execute，受控 capability）。
- **v1 回归**：orchestrator/call_plan/durable 测试不改动仍通过（SELECT 路径不动）。
- **v2 接线回归**：Runbook 15 的 v2 契约测试（`test_planner_plan_compiler_v2.py`）保持通过。

## 9. Build 阶段待核实项（Task 1.1/1.2）

- v2 `plan_graph` dict 是否逐键保留 v1 字段（`planId`/`goalId`/`nodes`/`edges`/`topologicalOrder`/`goalOutputs`）-> 决定前端 `DryRunPlanGraph` 是否需适配。Task 1.2 首先核实。
- `AgentOutcome.dry_run` 类型切换（`DryRunResult` -> `PlanCompileResult`）的下游影响：`orchestrator.py` 5 处引用、`handoff.py`、前端 `WorkbenchOutcome.dryRun` 类型。
- `node_state_changed` SSE 事件在现有 `AgentRunEvent` 类型上的扩展方式（不改 `emitEventsFromOutcome` 单能力事件）。

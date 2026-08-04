## Context

Runbook 15 已冻结 PlanGraph v2（Python `plan_compiler_v2.py` 产出 `readPartition` / 节点 / edges / 分区 / `snapshotId`）。P0B 已交付 durable runtime（Node `frontend/src/runtime/durable/`：`DurableRunStore` / `JsonlRunStore`、lease/claim、events、`CheckpointRef.nodeState`、idempotency）。Gateway（Java + Python OData）提供 per-capability `validate` / `execute`。

当前执行模型：Node `agent-runtime-adapter.ts` 单次 spawn Python CLI 子进程，返回一个 `WorkbenchOutcome`，由 `emitEventsFromOutcome` 发单能力事件。这是**单能力单次**模型，无多节点调度、无 durable 节点账本、无恢复/重放。

约束（roadmap 红线）：Runbook 16 必须直接复用 durable run/lease/event 基础，**不得再建设第二套进程内 PlanExecution store**。不执行 Action、不 replan、不绕过 Gateway。

## Goals / Non-Goals

**Goals:**
- Node 层 READ `PlanExecutor` 消费已验证 PlanGraph v2 `readPartition`，做 ready-node 调度 + 有限并发
- durable node ledger 复用 `DurableRunStore`（节点状态机 9 态 + sequence/attempt/input hash/result ref/trace span）
- 超时 / 取消 / 恢复 / 幂等重放：restart 后 `SUCCEEDED` 不重复执行
- per-node Gateway `validate -> execute`，不绕过
- fail-closed：Action-in-readPartition、snapshot drift、非法状态转换、lease conflict

**Non-Goals:**
- 不执行 Action 节点（保持 `BLOCKED_APPROVAL`）
- 不自动 replan、不做 Saga/补偿
- 不改 PlanGraph v2 compiler（Runbook 15 冻结）
- 不实现 OutputProjection（Runbook 17）/ Recommendation（Runbook 18）
- 不改 Python `orchestrator.run_query` 单能力路径（双链路并存）

## Decisions

### D1: Executor 位于 Node 层（非 Python）
**选择**：PlanExecutor 在 `frontend/src/runtime/`，读 PlanGraph v2 序列化输出，驱动 ready-node 调度 + per-node Gateway 调用，直接复用 `DurableRunStore`。
**理由**：durable runtime（lease/events/checkpoint/idempotency）在 Node；Python 侧建 durable 适配器会触发「第二套 store」红线或需跨进程 IPC。Python 角色收敛为产 PlanGraph v2（Runbook 15 已交付）。
**备选**：Python 层 executor（拒绝，durable store 跨进程/第二套 store代价）/ 混合（拒绝，executor 逻辑分裂）。

### D2: node ledger 复用 `DurableRunStore`（扩展 `CheckpointRef.nodeState`）
**选择**：节点状态落盘复用 `CheckpointRef.nodeState` + 现有 events 流，不新建 store。
**理由**：`CheckpointRef.nodeState: Record<string, unknown>` 已为节点状态留位；roadmap 禁止第二套 store。
**备选**：新建 `NodeLedgerStore`（拒绝，红线）。

### D3: per-node Gateway validate/execute（复用现有 Gateway）
**选择**：每个 READY 节点按 `capabilityId` + 参数走现有 Gateway `/capabilities/{id}/validate` + `/execute`，不绕过。
**理由**：Gateway execution contract 已稳定；不绕过安全边界。
**备选**：批量 Gateway 端点（拒绝，scope 蔓延 + 改 Gateway contract）。

### D4: 节点状态机 9 态
**选择**：`READY` / `VALIDATING` / `EXECUTING` / `SUCCEEDED` / `FAILED` / `TIMED_OUT` / `CANCELLED` / `BLOCKED_DEPENDENCY` / `BLOCKED_APPROVAL`。非法转换 fail-closed。
**理由**：覆盖 ready 调度、并发、超时、取消、依赖阻塞、审批阻塞、恢复全路径。

### D5: 双链路并存
**选择**：单能力 SELECT 走老路径（`orchestrator.run_query`）；ESCALATE_TO_PLANNER + 多 READ 走新 Node executor。老路径零回归。
**理由**：避免一次性 rewire 生产 orchestrator；新 executor 独立验证。

### D6: TDD - fake Gateway 先行
**选择**：先用 fake Gateway 完成状态机 + 恢复测试，再接现有 READ integration。
**理由**：状态机/恢复逻辑与 Gateway 解耦验证；runbook §8 起步要求。

## Risks / Trade-offs

- **[Node 消费 PlanGraph v2 契约]** Python 产出的 PlanGraph v2 dict 如何稳定传给 Node -> design 阶段定契约（现有 dry-run outcome 是否已携带 plan_graph，或新增）
- **[per-node SSE 与单能力事件共存]** 新增节点级事件不能破坏现有 `emitEventsFromOutcome` -> 复用 SSE 框架，事件类型正交
- **[并发安全]** DAG 独立性判定错误会导致错误并发 -> 复用 PlanGraph v2 edges 做依赖闭包，fail-closed
- **[恢复语义]** FAILED 节点恢复策略未定 -> design 阶段定（auto-retry vs 显式 retry）
- **[双链路维护成本]** 老路径冻结，新 executor 为唯一演进面 -> 老路径退役交后续 runbook

## Migration Plan

- 双链路并存，无需迁移：老单能力路径原样保留；新 executor 处理多 READ
- 老路径测试（`test_orchestrator.py` 等）保持通过
- 新 executor 独立契约测试 + fake Gateway 状态机/恢复测试 + 现有 READ integration
- 生产 orchestrator 切换到新 executor 延后至 Runbook 17 消费时评估

## Open Questions

> 以下交由 design 阶段 Design Doc 细化（comet-open 不在此定稿）：

1. `node ledger` 形状：扩展 `CheckpointRef.nodeState` 的具体结构（节点状态 + sequence/attempt/input hash/result ref/trace span）vs 新增 per-node event 类型
2. 并发模型：纯 DAG 独立性还是有可配置安全上限（cap）
3. `FAILED` 恢复策略：restart 后自动重试还是要求显式 retry；retry 复用幂等键的语义
4. per-node SSE 事件类型清单（node_ready / node_validating / node_executing / node_succeeded / node_failed / node_timed_out / node_cancelled 等）与现有事件的去重/共存
5. plan lease vs run lease：复用 run 级 lease 还是在 run 下新增 plan 子 lease
6. Python<->Node PlanGraph v2 契约：现有 dry-run outcome 是否已携带可消费的 plan_graph，还是新增 executor 输入契约

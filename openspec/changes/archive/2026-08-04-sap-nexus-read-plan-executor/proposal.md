## Why

Runbook 15 已交付可执行前验证的 PlanGraph v2（`readPartition` / 节点 / edges / 分区），但当前 Agent 链路仍是单能力单次执行：Node 单次 spawn Python 子进程返回一个 `WorkbenchOutcome`。多 READ 节点场景（如 `MM.Inventory.GetAvailability` + `MM.PurchaseOrder.GetList`）无法并发执行、无 durable 节点账本、无恢复/幂等重放。完整 Agent 链路需要一个消费 PlanGraph v2 的 READ `PlanExecutor`，填补「已验证计划」到「多节点 durable 执行」之间的缺口。

## What Changes

- 新增 **Node 层** READ `PlanExecutor`：消费已验证 PlanGraph v2 的 `readPartition`，做 ready-node 调度 + 有限并发 + per-node Gateway `validate -> execute`
- 新增 **durable node ledger**：复用 P0B `DurableRunStore`（lease/claim、events、`CheckpointRef.nodeState`、idempotency），记录节点状态机转换（sequence / attempt / input hash / result ref / trace span），**不建第二套 store**（roadmap 红线）
- 节点状态机：`READY` / `VALIDATING` / `EXECUTING` / `SUCCEEDED` / `FAILED` / `TIMED_OUT` / `CANCELLED` / `BLOCKED_DEPENDENCY` / `BLOCKED_APPROVAL`
- 超时 / 取消 / 恢复 / 幂等重放：restart 后 `SUCCEEDED` 节点不重复执行；retry 复用幂等键
- 安全边界：Action 节点 / snapshot drift / 非法状态转换在 Gateway 前 fail-closed；并发只由 DAG 独立性决定
- per-node SSE 事件：复用现有 SSE 框架新增节点级事件类型
- 双链路并存：单能力 SELECT 走老路径，ESCALATE_TO_PLANNER + 多 READ 走新 executor

## Capabilities

### New Capabilities

- `read-plan-executor`: Node 层 READ PlanExecutor；消费已验证 PlanGraph v2 `readPartition`；ready-node 调度 + 有限并发 + per-node Gateway validate/execute；durable node ledger（复用 `DurableRunStore`，节点状态机 9 态）；超时 / 取消 / 恢复 / 幂等重放；fail-closed 覆盖 Action-in-readPartition、snapshot drift、非法状态转换、lease conflict；不执行 Action、不 replan、不绕过 Gateway

### Modified Capabilities

<!-- 无 spec 级 requirement 变更。复用 durable-run-state（store 接口不变）、gateway-execution-contract（per-node 调用不变）、semantic-plan-authoring-v2（compiler 不变）。per-node SSE 事件在现有 sse-cursor-reconnect 框架内新增类型，不改其 spec 要求。 -->

## Impact

- 代码：`frontend/src/runtime/`（新增 PlanExecutor + node ledger 组件）、复用 `frontend/src/runtime/durable/`（`DurableRunStore` / `JsonlRunStore` / lease / idempotency）；Python 侧仅暴露 PlanGraph v2 序列化输出（Runbook 15 已交付，不改 compiler）
- 依赖：消费 Runbook 15 PlanGraph v2、P0B durable runtime（`durable-run-state`）、Gateway execution contract
- 双链路：Python `orchestrator.run_query` 单能力路径不改动；新 executor 处理 ESCALATE_TO_PLANNER + 多 READ 场景
- SSE：现有 `emitEventsFromOutcome` 单能力事件保留；新增 per-node 事件类型
- 下游：为 Runbook 17（OutputProjection）提供已执行 READ 节点的 durable 结果

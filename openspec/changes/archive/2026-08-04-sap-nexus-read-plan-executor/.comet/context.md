# Comet Design Handoff

- Change: sap-nexus-read-plan-executor
- Phase: design
- Mode: compact
- Context hash: 3dc32080c6876aa7200d4c3aac75e85ac0022c68ff2dac86d571b0a747f955fa

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/sap-nexus-read-plan-executor/proposal.md

- Source: openspec/changes/sap-nexus-read-plan-executor/proposal.md
- Lines: 1-31
- SHA256: 4ac63ffb3f85745ce144e6d5ceb2b7c166ef39bb89c956e569f8d01f42363633

```md
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

```

## openspec/changes/sap-nexus-read-plan-executor/design.md

- Source: openspec/changes/sap-nexus-read-plan-executor/design.md
- Lines: 1-78
- SHA256: b00ce884d1ad5f7706d094bcd62b7be44fb2b1a539b095140ff924608bef86a1

```md
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

```

## openspec/changes/sap-nexus-read-plan-executor/tasks.md

- Source: openspec/changes/sap-nexus-read-plan-executor/tasks.md
- Lines: 1-54
- SHA256: da19d00fe50fe66b803ca0ef6cfbb06ea6ddff847848162b4905dd4b49530a15

```md
## 1. PlanGraph v2 消费契约（Python -> Node）

- [ ] 1.1 确定并实现 Python -> Node 的 PlanGraph v2 传递契约（现有 dry-run outcome 是否已携带可消费 plan_graph，或新增 executor 输入契约）
- [ ] 1.2 Node 侧实现 PlanGraph v2 反序列化与 `readPartition` / 节点 / edges / `snapshotId` 解析
- [ ] 1.3 校验 PlanGraph v2 有效性 + `snapshotId` 未漂移，无效/漂移 fail-closed 并记录结构化失败

## 2. 节点状态机 + durable node ledger

- [ ] 2.1 实现 9 态节点状态机（`READY` / `VALIDATING` / `EXECUTING` / `SUCCEEDED` / `FAILED` / `TIMED_OUT` / `CANCELLED` / `BLOCKED_DEPENDENCY` / `BLOCKED_APPROVAL`）与合法转换表
- [ ] 2.2 扩展 `CheckpointRef.nodeState` 落盘节点状态（sequence / attempt / input hash / result ref / trace span），复用 `DurableRunStore`，不建第二套 store
- [ ] 2.3 非法状态转换 fail-closed 并记录非法尝试

## 3. Ready-node 调度 + DAG 并发

- [ ] 3.1 实现 ready-node 选择：依赖闭包（基于 edges）全部 `SUCCEEDED` 才 `READY`，否则 `BLOCKED_DEPENDENCY`
- [ ] 3.2 实现 DAG 独立性决定的有限并发调度
- [ ] 3.3 双 READ 节点（`MM.Inventory.GetAvailability` + `MM.PurchaseOrder.GetList`）并发执行场景验证

## 4. Per-node Gateway validate/execute

- [ ] 4.1 实现 per-node Gateway `validate -> execute`（复用现有 Gateway，不绕过、不批量端点）
- [ ] 4.2 validate 失败节点转 `FAILED`，不调 execute，独立节点继续
- [ ] 4.3 Action / 非 read-only 节点保持 `BLOCKED_APPROVAL`，不执行、不调 Gateway execute

## 5. 超时与取消

- [ ] 5.1 实现节点级超时 -> `TIMED_OUT`，不阻塞独立节点
- [ ] 5.2 实现用户取消 -> 未完成节点 `CANCELLED`，`SUCCEEDED` 保留

## 6. 恢复与幂等重放

- [ ] 6.1 实现 restart 恢复：从 durable ledger 加载，`SUCCEEDED` 不重复执行，`READY`/未完成续跑
- [ ] 6.2 实现幂等重放：相同 idempotency key 不重复执行节点，返回已记录结果
- [ ] 6.3 lease conflict fail-closed（另一 worker 持有 lease 时拒绝操作并记录）

## 7. Per-node SSE 事件

- [ ] 7.1 新增 per-node SSE 事件类型（`node_ready` / `node_validating` / `node_executing` / `node_succeeded` / `node_failed` / `node_timed_out` / `node_cancelled` 等）
- [ ] 7.2 复用现有 SSE 框架，不破坏 `emitEventsFromOutcome` 单能力事件

## 8. 测试（TDD：fake Gateway 先行）

- [ ] 8.1 fake Gateway 完成状态机转换测试（9 态 + 非法转换 fail-closed）
- [ ] 8.2 fake Gateway 完成恢复测试（restart 跳过 `SUCCEEDED`、续跑 `READY`、幂等重放）
- [ ] 8.3 fake Gateway 完成调度测试（双 READ 并发、dependency 阻塞、超时、取消、partial failure、lease conflict）
- [ ] 8.4 接现有 READ integration（真实 Gateway validate/execute，受控 capability）
- [ ] 8.5 v1 回归：现有 orchestrator / call_plan / durable 测试不改动仍通过

## 9. 验证与文档

- [ ] 9.1 `.venv/bin/python -m pytest agent/tests -q` + `npm --prefix frontend run verify` 全绿
- [ ] 9.2 `scripts/verify-agent-callplan-evidence.sh` 通过
- [ ] 9.3 `openspec validate --all --strict` 通过
- [ ] 9.4 更新 Runbook 16 状态/版本 + `docs/runbooks/README.md` + roadmap row 27

```

## openspec/changes/sap-nexus-read-plan-executor/specs/read-plan-executor/spec.md

- Source: openspec/changes/sap-nexus-read-plan-executor/specs/read-plan-executor/spec.md
- Lines: 1-140
- SHA256: 1dc421e490cd95426a8ee845692f0c5ba4cc35c39c1f81d86a63c9734c711c33

[TRUNCATED]

```md
## ADDED Requirements

### Requirement: PlanExecutor consumes validated PlanGraph v2 readPartition

The system SHALL provide a READ PlanExecutor that consumes a validated PlanGraph v2 `readPartition` and executes only READ nodes. The executor SHALL reject any PlanGraph that is not validator-valid or whose `snapshotId` has drifted from the bound RegistrySnapshot. The executor MUST NOT call the LLM, replan, or bypass the Gateway.

#### Scenario: Valid PlanGraph readPartition consumed

- **WHEN** the executor receives a validator-valid PlanGraph v2 with a readPartition of READ nodes
- **THEN** the executor schedules the readPartition nodes for execution
- **AND** binds the same `snapshotId` as the PlanGraph

#### Scenario: Invalid or drifted PlanGraph rejected

- **WHEN** the executor receives a PlanGraph that fails validation or whose `snapshotId` drifts
- **THEN** the executor rejects the plan fail-closed before any Gateway call
- **AND** records a structured failure

### Requirement: Ready-node scheduling bounded by DAG independence

The system SHALL select dependency-free READY nodes from the readPartition and execute them with bounded concurrency determined solely by DAG independence (edges). A configurable safety cap (default 4, overridable via the `READ_PLAN_EXECUTOR_MAX_CONCURRENCY` environment variable) SHALL bound the maximum number of in-flight nodes as backpressure protection. A node whose dependencies are not all SUCCEEDED SHALL remain `BLOCKED_DEPENDENCY`.

#### Scenario: Two independent READ nodes execute concurrently

- **WHEN** the readPartition contains two READ nodes with no dependency edge between them
- **THEN** both nodes are scheduled as READY and execute concurrently
- **AND** each independently passes through Gateway validate/execute

#### Scenario: Dependent node blocks until prerequisite succeeds

- **WHEN** a node has an unsatisfied dependency (prerequisite not `SUCCEEDED`)
- **THEN** the node stays `BLOCKED_DEPENDENCY`
- **AND** becomes `READY` only after the prerequisite node is `SUCCEEDED`

#### Scenario: Configurable safety cap bounds in-flight nodes

- **WHEN** the readPartition contains more READY nodes than the configured `READ_PLAN_EXECUTOR_MAX_CONCURRENCY` cap (default 4)
- **THEN** the executor schedules at most the cap number of nodes concurrently
- **AND** remaining READY nodes are scheduled as in-flight nodes complete

### Requirement: Per-node Gateway validate and execute without bypass

The system SHALL execute each READ node by calling the existing Gateway `validate` then `execute` per capability. The executor MUST NOT bypass the Gateway, call SAP directly, or use a batch endpoint.

#### Scenario: Node passes validate then execute

- **WHEN** a READY node is executed
- **THEN** the executor calls Gateway validate with the node's `capabilityId` and parameters
- **AND** only on validation success calls Gateway execute

#### Scenario: Validation failure fails the node

- **WHEN** Gateway validate fails for a node
- **THEN** the node transitions to `FAILED` without calling execute
- **AND** independent nodes continue execution

### Requirement: Durable node ledger reuses DurableRunStore

The system SHALL persist a durable node ledger by reusing the P0B `DurableRunStore` (extending `CheckpointRef.nodeState` and the event stream). The system MUST NOT create a second process-local PlanExecution store. Each node state transition SHALL record sequence, attempt, input hash, result ref, and trace span.

#### Scenario: Node state transitions persisted to durable ledger

- **WHEN** a node transitions through `READY` -> `VALIDATING` -> `EXECUTING` -> `SUCCEEDED`
- **THEN** each transition is persisted to the durable ledger with sequence, attempt, input hash, result ref, and trace span
- **AND** the ledger is recoverable across process restarts

#### Scenario: Illegal state transition fail-closed

- **WHEN** a node attempts an illegal state transition (e.g., `SUCCEEDED` -> `EXECUTING`)
- **THEN** the executor rejects the transition fail-closed
- **AND** records the illegal attempt

### Requirement: Action nodes blocked

The system SHALL NOT execute Action nodes or any node whose governance is not read-only. Such nodes SHALL remain `BLOCKED_APPROVAL` and MUST NOT be executed.

#### Scenario: Action node stays BLOCKED_APPROVAL

- **WHEN** a plan includes an Action or non-read-only node
- **THEN** the node stays `BLOCKED_APPROVAL` and is not executed

```

Full source: openspec/changes/sap-nexus-read-plan-executor/specs/read-plan-executor/spec.md

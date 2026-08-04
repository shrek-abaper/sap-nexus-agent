# Brainstorm Summary

- Change: sap-nexus-read-plan-executor
- Date: 2026-08-04

## 确认的技术方案

基于 design.md 高层决策 D1-D6，深化 6 个 Open Questions：

### Q6（关键）：Python<->Node PlanGraph v2 契约
- **发现**：orchestrator ESCALATE 路径当前调用 v1 `compile_dry_run_from_handoff`（产出 PlanGraph v1，无 `readPartition`）；v2 `compile_plan_v2_from_handoff`（Runbook 15 交付）未接线。Runbook 15 non-goal 明确把 v2 接线留给「Runbook 16 消费时」。
- **方案**：把 v2 compiler 接入 orchestrator 的 `ESCALATE_TO_PLANNER` 路径（替换 v1 调用），使 `WorkbenchOutcome.dryRun` 携带 v2 plan_graph（含 `readPartition`/`actionPartition`）。Node executor 直接消费。
- SELECT 单能力路径不动（D5 成立）；前端 `DryRunPlanGraph` 读 v1 字段，v2 额外字段被忽略 -> 向后兼容。

### Q1：node ledger 形状
- 扩展 `CheckpointRef.nodeState` 为结构化 per-node 状态（`{nodeId: {state, attempt, inputHash, resultRef, traceSpan, updatedAt}}`）+ 每次转换 append 一条 event。
- nodeState = 权威快照（恢复用）；events = 审计流（SSE 重放用）。双写复用 `DurableRunStore`，不建第二套 store。

### Q2：并发模型
- DAG 独立性决定可并发集 + 可配置安全上限（默认 4，env `READ_PLAN_EXECUTOR_MAX_CONCURRENCY` 可调）。
- runbook「并发只由 DAG 独立性决定」指调度逻辑（不靠模型 tool calls）；上限是 backpressure 保护。

### Q3：FAILED 恢复策略
- restart 后 FAILED 节点**不自动重试**，保持 FAILED；需显式 retry（新 attempt）。
- 幂等键 = `runId + nodeId + attempt + inputHash`（含 attempt，允许多次尝试）。
- SUCCEEDED 跳过；READY/未完成续跑。

### Q4：per-node SSE 事件
- 新增**一个**通用事件 `node_state_changed`（携带 `nodeId`/`fromState`/`toState`/`attempt`），覆盖 9 态转换。
- 复用现有 SSE 框架；不新增 7 种细粒度事件类型。
- 与 `emitEventsFromOutcome` 单能力事件正交（新 executor 路径发 node 事件，老路径不变）。

### Q5：plan lease vs run lease
- 复用 run 级 lease（`DurableRunStore.claim`），不新增 plan 子 lease。
- plan 执行是 run 的一个阶段；run lease 已有 claim/renew/release/force-claim 语义。

## 关键取舍与风险

- **[Python 侧改动]** Q6 需把 orchestrator ESCALATE 路径从 v1 切到 v2 compiler（Python 改动一刀）-> 仅改 ESCALATE 路径，SELECT 路径零回归；v2 已有契约测试覆盖。
- **[nodeState + events 双写一致性]** 权威快照与审计流可能短期不一致 -> nodeState 先写（恢复权威），events 后 append（SSE 重放）；恢复以 nodeState 为准。
- **[并发安全]** DAG 独立性判定错误导致错误并发 -> 复用 PlanGraph v2 edges 做依赖闭包，fail-closed。
- **[FAILED 不自动重试]** 可能需要用户/上游显式触发 retry -> 显式 retry 更可控，幂等键含 attempt 支持重试。
- **[v1/v2 双版本 dry-run]** 切换后老 v1 DryRunResult 不再产出 -> v2 是 v1 超集，前端解析器兼容；v1 退役交后续。
- **[双链路维护成本]** 老路径冻结，新 executor 为唯一演进面 -> 老路径退役交后续 runbook。

## 测试策略

- TDD：fake Gateway 先行
  - 状态机 9 态转换 + 非法转换 fail-closed
  - 恢复：restart 跳过 SUCCEEDED、续跑 READY、FAILED 保持、幂等重放
  - 调度：双 READ 并发、dependency 阻塞、超时、取消、partial failure、lease conflict
- 接现有 READ integration（真实 Gateway validate/execute，受控 capability）
- v1 回归：orchestrator/call_plan/durable 测试不改动仍通过
- v2 compiler 接线后：Runbook 15 的 v2 契约测试保持通过

## Spec Patch

对照 `specs/read-plan-executor/spec.md` 检查，确认以下补充：
1. **`node_state_changed` SSE 事件场景**：当前 spec 的「Per-node SSE events」requirement 已覆盖「per-node events emitted on transitions」，但可明确事件类型为 `node_state_changed`（单个通用事件 + state 字段）。
2. **FAILED 显式 retry 场景**：当前 spec 的「Restart recovery and idempotent replay」已覆盖 recovery + idempotent replay，但 FAILED 节点「不自动重试、需显式 retry」语义可补充为 scenario。
3. **并发安全上限**：当前 spec 的「Ready-node scheduling」说「bounded concurrency determined solely by DAG independence」，可补充「configurable safety cap」场景。

均为补充验收场景/明确歧义，不大改 spec 结构。

## Context

当前 Workbench backend 用两个 `globalThis` 进程级 Map 承载运行时状态：

- `runs`（`frontend/src/runtime/agent-runtime-adapter.ts:109`）：agent run 事件流 + `pendingOutcome` + approval decision。
- `sessions`（`agent-runtime-adapter.ts:112`）：多轮对话 `lastContext` + `history`。

进程重启即丢失，multi-worker 不共享。`conversational-context`（row 19A）已把 `ConversationState` 接口对齐技术架构 §4.2.1 三层分层（`ConversationState` advisory / `PlanExecutionState` execution authority / `EvidenceState` evidence authority），为 P0B durable 替换预留。本 change 是 P0B 拆分项 1/4，提供 durable state 基础设施，是项 2/3/4 的前提。

## Goals / Non-Goals

**Goals:**

- durable Run/Thread + Sessions：cross-restart 恢复 + multi-worker 共享。
- run ownership/lease：fail-closed 接管保护。
- structured checkpoint reference：恢复时加载原始 `RegistrySnapshot` 和结构化节点状态，不靠 summary / Memory 重建。
- 幂等 continuation：approval / batch continuation 重复请求不重复执行。
- store 无关契约：接口先行，实现可插拔。

**Non-Goals:**

- store 选型预决（SQLite / PostgreSQL / Redis 在 comet-design 阶段决定）。
- trusted principal / tenant / role / data scope（拆分项 2）。
- durable ApprovalStore（拆分项 3，Gateway `InMemoryApprovalStore` 替换）。
- incremental SSE cursor / reconnect（拆分项 4）。
- DeerFlow lead agent、自由 Tool execution、WRITE 批量审批语义。

## Decisions

- **D1 store 无关接口**：定义 `DurableRunStore` / `DurableConversationStore` 抽象接口（save / load / list / lease / claim），实现可插拔；本 change 提供一个本地参考实现（comet-design 选型），生产实现可替换。理由：解耦契约与选型，避免 open 阶段预决。
- **D2 ownership/lease**：run 绑定 `workerId` + lease（TTL + 续期）；lease 未释放时其他 worker 接管 fail-closed；lease 过期后允许带审计的强制接管。对齐 §4.2.1 "run ownership / lease"。
- **D3 checkpoint reference**：checkpoint 持久化结构化引用（`RegistrySnapshotId` + 节点状态 + 已批准 `ApprovalRecord` 引用），不持久化 summary；恢复时加载原始 snapshot + 节点状态。对齐 §4.2.1 "恢复计划时必须加载原始 RegistrySnapshot 和结构化节点状态，不能依靠 summary 或 Memory 重建"。
- **D4 幂等 continuation**：continuation 请求带 idempotency key（`runId` + continuation type + 参数 hash）；重复 key 返回已记录结果，不重复执行。
- **D5 三层状态分层**：durable store 按 §4.2.1 三层分层持久化：`ConversationState`（advisory，可压缩）、`PlanExecutionState`（authority，不可压缩）、`EvidenceState`（authority，不可压缩）。压缩失败只保留原 checkpoint 或关闭压缩，不破坏 run。

## Risks / Trade-offs

- [store 选型延迟] -> comet-design 阶段必须先选型再 build；open 阶段仅定契约，build 不开始。
- [multi-worker 并发复杂] -> ownership/lease + fail-closed 接管；先单 worker durable，再验证 multi-worker。
- [checkpoint 一致性] -> checkpoint 与 `RegistrySnapshot` 绑定；snapshot 漂移 fail-closed（复用 S1 validator）。
- [durable 引入运维依赖] -> 本地参考实现零依赖（如 SQLite / file），生产实现可替换。

## Open Questions

- store 选型（comet-design 阶段决定）。
- lease 续期策略（主动续期 vs 活动驱动）。
- checkpoint 粒度（每事件 vs 每状态变更）。
- idempotency key schema。

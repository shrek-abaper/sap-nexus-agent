## Why

当前 Workbench backend 的 agent run state（`runs Map`）和会话上下文（`sessions Map`）都是 `globalThis` 进程级 Map（`frontend/src/runtime/agent-runtime-adapter.ts:109/112`），进程重启即丢失，multi-worker 不共享。这阻塞了 P0B 条件门禁：共享 S3、长审批、multi-worker/HA、非 sandbox WRITE 都要求 durable Run/Approval + ownership/lease + checkpoint + 幂等 continuation。`conversational-context`（row 19A）已把 `ConversationState` 接口对齐技术架构 §4.2.1 三层分层为 P0B 预留，本 change 把进程内 Map 替换为 durable store，是 P0B 拆分项 1/4（核心基础设施）。

## What Changes

- 把 `runs Map`（`globalThis.__SAP_NEXUS_AGENT_RUNS__`）替换为 durable Run/Thread store，支持 cross-restart 恢复（pending / awaiting_approval / awaiting_batch_confirm 的 run 重启后可继续）。
- 把 `sessions Map`（`globalThis.__SAP_NEXUS_AGENT_SESSIONS__`）替换为 durable ConversationState store，多轮对话 context（lastContext + history）跨重启不丢。
- 建立 run ownership/lease：run 被一个 worker 持有，lease 未释放时其他 worker 不能接管（fail-closed）。
- structured checkpoint reference：run 的 `PlanExecutionState` / `EvidenceState` checkpoint 可持久化引用；恢复时加载原始 `RegistrySnapshot` 和结构化节点状态，不依靠 summary 或 Memory 重建（对齐 §4.2.1）。
- 幂等 continuation：approval / batch continuation 重复请求不重复执行（idempotency key）。
- store 无关契约：先定义 durable Run / Thread / Sessions 的 store 无关接口；store 选型（SQLite / PostgreSQL / Redis 等）在 design 阶段决定，不在 open 阶段预决。

## Capabilities

### New Capabilities

- `durable-run-state`: durable agent Run/Thread 持久化、cross-restart 恢复、run ownership/lease、structured checkpoint reference、幂等 continuation。

### Modified Capabilities

- `conversational-context`: `ConversationState` 存储语义从 process-local Map（不跨重启）变更为 durable store（跨重启恢复）；接口已对齐 §4.2.1 三层分层，本 change 替换其底层存储实现。spec 级变更：v1 "MUST NOT persist across process restarts" 约束解除，改为 durable 持久化契约。

## Impact

- `frontend/src/runtime/agent-runtime-adapter.ts`：`runs` / `sessions` Map 替换为 durable store 接口；`AgentRunRecord` / `SessionState` 持久化序列化。
- 新增 durable store 模块（store 无关接口 + design 阶段选型实现）。
- agent run lifecycle：cross-restart 恢复、ownership/lease、checkpoint replay、幂等 continuation。
- 不触 Gateway approval（拆分项 3）、不触 SSE（拆分项 4）、不触 trusted principal/tenant（拆分项 2）。
- 依赖：`conversational-context`（row 19A）已预留接口；技术架构 §4.2.1 三层状态分层。
- 非目标：store 选型预决（design 阶段）、principal/tenant/role/data scope（项 2）、durable ApprovalStore（项 3）、incremental SSE cursor/reconnect（项 4）、DeerFlow lead agent、自由 Tool execution。

## Why

当前 Workbench 的 SSE 传输是 buffered SSE-format：`frontend/src/runtime/agent-runtime-adapter.ts` 在 Agent 子进程结束后读取进程内事件并一次性返回 SSE-formatted body（`buildEventsFromOutcome` 在 runner 完成后才构建全部事件，所有事件共享 run 起始 timestamp），既非增量发布、也非断线续传。这阻塞了 P0B 门禁：长审批、cross-restart、multi-worker 场景都要求客户端断线后能带 cursor 重连并续传缺失事件。技术架构 §4.2 已定义目标 SSE runtime（事件序号、增量发布、reconnect cursor、terminal state、replay），`AgentRunEvent.sequence` 字段已存在但未被 cursor 机制使用。本 change 是 P0B 拆分项 4/4（已确认拆分）。

## What Changes

- 把 buffered SSE-format 升级为 incremental 发布：事件产生即推送到 SSE stream，不再等 Agent 子进程结束后一次性返回。
- 引入 event cursor：每个发布的 AgentRunEvent 携带其 `sequence` 作为 cursor，客户端可记录最后收到事件的 sequence 用于重连。
- 引入 reconnect replay：客户端断线后带 cursor 重连，服务端从该 cursor 之后续传所有缺失事件，不丢失、不乱序。
- 引入 terminal state 收敛：`run_completed` / `run_failed` 后关闭 SSE stream，后续重连只补发 terminal 事件即关闭，cursor 在 terminal 后不再产生新事件。
- 显式声明对拆分项 1（durable-state-foundation）的依赖：事件必须先持久化才能支持 cursor 续传与跨重启 replay。

## Capabilities

### New Capabilities

- `sse-cursor-reconnect`: 增量 SSE 发布、event cursor、断线 reconnect replay、terminal state 收敛。覆盖 AgentRunEvent 从 buffered 一次性返回升级为增量流式推送 + 带 cursor 断线续传的契约。

### Modified Capabilities

<!-- 无。当前 openspec/specs/ 下无 SSE 相关 capability，sse-cursor-reconnect 是全新 capability。agent-workbench-console 的 SSE 渲染属实现细节，不在 spec 级变更范围。 -->

## Impact

- `frontend/src/runtime/agent-runtime-adapter.ts`：`createAgentRun` 当前 await runner 完成后一次性 `buildEventsFromOutcome`，需改为事件产生即增量推送；`AgentRunEvent.sequence` 从单纯计数升级为 cursor 来源。
- SSE route handlers（`frontend/src/pages/api/` 下 agent run / events 路由）：从 buffered body 改为增量 stream + cursor 查询参数 + reconnect replay 端点。
- 依赖拆分项 1 `durable-state-foundation`：事件持久化（durable events）是 cursor/replay 的前提，cursor 存储位置与 replay 窗口由项1 durable events 落地后复用。
- 非目标：WebSocket、双向 HITL 协作、durable state foundation 本身（项1）、durable ApprovalStore（项3）、trusted principal/tenant（项2）。

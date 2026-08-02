## Context

当前 Workbench SSE 传输是 buffered SSE-format：`frontend/src/runtime/agent-runtime-adapter.ts` 的 `createAgentRun` 在 `await runner(...)` 完成后才调用 `buildEventsFromOutcome` 一次性构建全部 `AgentRunEvent`（所有事件共享 run 起始 timestamp，`sequence` 仅作进程内计数），SSE route handler 再把这些事件格式化为一次性 SSE body 返回。客户端断线即丢失整个 run，无重连能力。

技术架构 §4.2 已定义目标 SSE runtime："第一版传输协议继续采用 SSE first，但必须区分协议格式与运行能力：当前 Workbench 是 buffered SSE-format，不是增量发布、断线续传或 durable stream。目标 SSE runtime 必须支持事件序号、增量发布、reconnect cursor、terminal state 和 replay。"

`AgentRunEvent.sequence`（`run-event-schema.ts:51`）字段已存在，但当前未被任何 cursor/replay 机制使用。本 design 只记录 open 阶段高层决策，实现深度（cursor 编码格式、replay 缓冲区数据结构、背压窗口参数等）留待 comet-design 阶段细化。

## Goals / Non-Goals

**Goals:**

- 增量发布（incremental delivery）：AgentRunEvent 产生即推送到 SSE stream，不等子进程结束。
- event cursor：每个发布事件携带其 `sequence` 作为重连 cursor。
- reconnect replay：客户端带 cursor 重连，服务端从 cursor 之后续传缺失事件，不丢失、不乱序。
- terminal state 收敛：`run_completed` / `run_failed` 后关闭 stream，后续重连补发 terminal 事件即关闭。

**Non-Goals:**

- durable state foundation 本身（拆分项 1）：事件持久化存储、cross-restart 恢复、ownership/lease 归项1；本项只定义 cursor/replay 对 durable events 的消费契约。
- WebSocket / 双向流：本项仍是 SSE first（单向 server push）。
- 双向 HITL 协作协议：approval/batch continuation 的交互通道不在本项。
- cursor 存储选型与 replay 窗口长度的最终定值：留 comet-design。

## Decisions

**D1 — event cursor 复用 AgentRunEvent.sequence**

每个发布的 AgentRunEvent 携带其 `sequence` 作为 cursor。客户端记录最后收到事件的 sequence，重连时带上该 sequence。复用已有字段，不引入新 ID。

- 备选：独立 cursor token（如 `runId + offset` 编码）。否决：`sequence` 已是单调递增且语义清晰，额外 token 增加状态管理负担。

**D2 — incremental 发布替代 buffered**

`createAgentRun` 不再 await runner 完成后一次性 `buildEventsFromOutcome`，改为事件产生即推送到 SSE stream。

- 备选：保留 buffered 作 fallback。否决：buffered 与增量并存增加双路径维护成本，且无法满足 P0B 门禁的增量发布要求。

**D3 — reconnect replay 从 cursor 续传**

客户端断线后带 `?cursor=<sequence>` 重连，服务端从 durable events 中查询该 sequence 之后的事件并续传，保证不丢失、不乱序。

- 备选：客户端全量重拉。否决：长 run 重拉成本高且可能重复推送已收到事件。

**D4 — terminal state 关闭 stream + cursor 收敛**

`run_completed` / `run_failed` 发出后关闭 SSE stream。terminal 之后的重连只补发 terminal 事件即关闭，cursor 在 terminal 后不再产生新事件。

- 备选：stream 保持开启等待客户端关闭。否决：长连接占用资源，terminal 即终态语义应收敛。

**D5 — 显式依赖拆分项 1 durable events**

事件必须先持久化（durable events）才能支持 cursor 续传与跨重启 replay。本项 cursor/replay 契约建立在项1 durable events 之上，cursor 存储位置复用项1 落地的持久化层。

## Risks / Trade-offs

- 事件丢失 -> 缓解：cursor + durable events 持久化，replay 从持久层补发。
- reconnect 窗口过期 -> 缓解：保留 terminal 前事件供 replay；窗口长度待 comet-design 定参。
- 增量发布背压 -> 缓解：增量发布需流控（客户端消费慢时服务端不能无限缓冲），策略待 comet-design。
- 增量发布改造影响现有 buffered 测试 -> 缓解：tasks 中纳入 frontend verify + 回归测试。

## Open Questions

- cursor 存储位置：复用项1 durable events 落地的持久化层，具体接口待项1 design 定型后对接。
- reconnect 窗口长度：terminal 前事件保留多久可供 replay，待 comet-design 定参。
- 背压策略：增量发布流控的具体机制（缓冲上限 / 丢弃策略 / 慢消费者处理），待 comet-design。

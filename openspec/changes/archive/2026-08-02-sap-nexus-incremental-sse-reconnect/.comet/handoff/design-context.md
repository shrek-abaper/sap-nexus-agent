# Comet Design Handoff

- Change: sap-nexus-incremental-sse-reconnect
- Phase: design
- Mode: compact
- Context hash: bb4af331d528ab0d08212d0c0135c8428713d2033502101826ef8448ee2cf0d5

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/sap-nexus-incremental-sse-reconnect/proposal.md

- Source: openspec/changes/sap-nexus-incremental-sse-reconnect/proposal.md
- Lines: 1-28
- SHA256: 3b1d6be59a2efdebf0a434f5bb103e989727162c752b0c046092d6678e07653a

```md
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

```

## openspec/changes/sap-nexus-incremental-sse-reconnect/design.md

- Source: openspec/changes/sap-nexus-incremental-sse-reconnect/design.md
- Lines: 1-66
- SHA256: 5114ea115128ee44f68a17d2a518e477ccaed22a16a73bb99c5a0b27c98fa768

```md
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

```

## openspec/changes/sap-nexus-incremental-sse-reconnect/tasks.md

- Source: openspec/changes/sap-nexus-incremental-sse-reconnect/tasks.md
- Lines: 1-37
- SHA256: 8a173a63d412fc1bb2a827bd3b09e0f898a03c2e87b05860d648440f475ac58c

```md
## 1. Event cursor

- [ ] 1.1 在 SSE route handler 中为每个发布的 AgentRunEvent 暴露其 `sequence` 作为 cursor 字段
- [ ] 1.2 实现 cursor 查询参数解析（`?cursor=<sequence>`），校验 cursor 合法性（非负整数、属于当前 run）
- [ ] 1.3 对接拆分项 1 durable events 持久化层，确认 cursor 读取自 durable 事件存储而非进程内 Map

## 2. Incremental 发布

- [ ] 2.1 改造 `createAgentRun`：移除 await runner 完成后一次性 `buildEventsFromOutcome` 的 buffered 路径，改为事件产生即推送到 SSE stream
- [ ] 2.2 将 `buildEventsFromOutcome` 拆分为增量事件发射器，每个事件产生时立即写入 stream 并分配递增 `sequence`
- [ ] 2.3 确保 `run_started` 事件在 run 开始时立即推送（不等后续事件）

## 3. Reconnect replay

- [ ] 3.1 实现 reconnect 端点：客户端带 `cursor=N` 重连时，服务端从 durable events 查询 sequence > N 的事件
- [ ] 3.2 replay 按 `sequence` 升序续传，保证不丢失、不乱序
- [ ] 3.3 处理 cursor 超出已知事件范围的情况（无效 cursor 的错误响应）

## 4. Terminal state 收敛

- [ ] 4.1 `run_completed` / `run_failed` 事件发出后关闭 SSE stream
- [ ] 4.2 terminal 之后的重连：补发 terminal 事件后立即关闭 stream，cursor 不再产生新事件
- [ ] 4.3 验证 approval/batch continuation 路径下的 terminal 收敛（awaiting_approval 后续 approve/reject 仍能正确进入 terminal）

## 5. 背压流控

- [ ] 5.1 增量发布流控机制：客户端消费慢时服务端缓冲上限与处理策略（具体参数留 comet-design 定值）
- [ ] 5.2 慢消费者处理：超限时不得丢失已持久化事件，可通过 cursor 重连补发

## 6. 测试验证

- [ ] 6.1 增量发布单元测试：`run_started` 后客户端立即收到事件，不等 `run_completed`
- [ ] 6.2 reconnect replay 测试：断线后带 cursor 重连收到全部缺失事件且顺序正确
- [ ] 6.3 terminal state 测试：terminal 事件送达后 stream 关闭，后续重连补发 terminal 即关闭
- [ ] 6.4 回归测试：现有 buffered SSE 测试适配增量路径，不破坏 approval/batch continuation 流程
- [ ] 6.5 `npm --prefix frontend run verify` 通过
- [ ] 6.6 `openspec validate --all --strict` 通过

```

## openspec/changes/sap-nexus-incremental-sse-reconnect/specs/sse-cursor-reconnect/spec.md

- Source: openspec/changes/sap-nexus-incremental-sse-reconnect/specs/sse-cursor-reconnect/spec.md
- Lines: 1-53
- SHA256: ca2be7ac141230e1bb1e3d0bbde399e8b570728d203719433756d53a44baf5a7

```md
## ADDED Requirements

### Requirement: Incremental SSE delivery

The system SHALL publish each AgentRunEvent to the SSE stream incrementally as it is produced, not buffered until the Agent subprocess completes. Each published event SHALL carry its `sequence` field so the client can track the last received event.

#### Scenario: events stream incrementally

- **WHEN** an agent run emits a `run_started` event before the run reaches `run_completed`
- **THEN** the client connected to the SSE stream SHALL receive the `run_started` event immediately
- **AND** the client SHALL NOT have to wait until `run_completed` to receive any event

### Requirement: Event cursor for reconnect

The system SHALL support a reconnect cursor based on the event `sequence`. A client reconnecting with a cursor SHALL receive all events whose sequence is strictly greater than the cursor value.

#### Scenario: reconnect resumes from cursor

- **WHEN** a client disconnects after receiving an event with sequence N and reconnects with `cursor=N`
- **THEN** the server SHALL resume delivery starting from the event with sequence N+1
- **AND** the client SHALL receive every event it missed during the disconnection

#### Scenario: cursor at terminal state

- **WHEN** a run has reached terminal state (`run_completed` or `run_failed`) and a client reconnects with a cursor that points to an event before the terminal event
- **THEN** the server SHALL deliver the terminal event
- **AND** the cursor SHALL NOT produce any new events after the terminal event

### Requirement: Reconnect replay completeness

The system SHALL replay all events after the cursor without loss. Replay SHALL preserve the original event order by `sequence`.

#### Scenario: no event loss on reconnect

- **WHEN** a client reconnects with a cursor and multiple events were produced after that cursor
- **THEN** the server SHALL replay every event after the cursor
- **AND** no event produced after the cursor SHALL be omitted from the replay

#### Scenario: event order preserved

- **WHEN** the server replays events after a cursor
- **THEN** the events SHALL be delivered to the client in ascending `sequence` order
- **AND** no event SHALL be delivered out of order relative to its `sequence`

### Requirement: Terminal state closes stream

The system SHALL close the SSE stream after emitting a terminal state event (`run_completed` or `run_failed`). A subsequent reconnect SHALL receive the terminal event and then have its stream closed.

#### Scenario: terminal event delivered then stream closes

- **WHEN** the server emits a `run_completed` or `run_failed` terminal event on an active stream
- **THEN** the server SHALL deliver the terminal event to the client
- **AND** the server SHALL close the SSE stream after delivering the terminal event

```

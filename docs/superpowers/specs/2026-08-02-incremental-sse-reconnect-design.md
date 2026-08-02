---
comet_change: sap-nexus-incremental-sse-reconnect
role: technical-design
canonical_spec: openspec
status: final
archived-with: 2026-08-02-sap-nexus-incremental-sse-reconnect
status: final
---

# Design: Incremental SSE with Cursor Reconnect (P0B 项4)

> Comet change: `sap-nexus-incremental-sse-reconnect` (phase: design)
> Canonical spec: `openspec/changes/sap-nexus-incremental-sse-reconnect/specs/sse-cursor-reconnect/spec.md`
> 本文档把 change `design.md` 的 D1-D5 与 3 个 Open Question 决策展开为可实施的技术设计。

## Context

当前 Workbench SSE 传输是 **buffered SSE-format**，存在两个层面的问题：

**1. `createAgentRun` 阻塞式执行（`agent-runtime-adapter.ts:101-166`）**

POST `/api/agent-runs` 调用 `createAgentRun`，该函数 `await runner(...)`（Python 子进程）完成后才调用 `buildEventsFromOutcome` 一次性构建全部 `AgentRunEvent`，再逐条 `appendEvent` 到 durable store。POST 响应在 runner 完成后才返回 `{ runId }`。所有事件共享 run 起始 timestamp（`sequence` 仅作进程内计数），客户端无法在 runner 执行期间收到任何事件。

**2. SSE route 一次性返回（`stream/route.ts:1-15`）**

客户端收到 `runId` 后打开 `EventSource`。stream route 调用 `getAgentRunEvents(runId)` -> `runStore.load(runId)` 一次性读取全部事件，拼成 SSE body 返回。这不是真正的流式响应，而是一个 buffered string。客户端断线即丢失整个 run，无重连能力。

**项1 已落地的基础**

项1 `sap-nexus-durable-state-foundation` 已实现 `JsonlRunStore`：
- `appendEvent(runId, event)`：每事件 append + fsync 到 `runs/<runId>.jsonl`（`jsonl-run-store.ts:180-183`）。
- `load(runId)`：重放 JSONL，返回 `AgentRunRecord`，其中 `events` 按 `sequence` 升序排序（`jsonl-run-store.ts:173`）。
- `AgentRunEvent.sequence` 字段已存在（`run-event-schema.ts:51`），已由 `appendEvent` 持久化。

本 change 复用项1 的 `appendEvent`（增量落盘）+ `load`（replay 读取）+ `sequence`（cursor），**不向 `DurableRunStore` 添加任何新接口**。

## Goals / Non-Goals

**Goals:**

- 增量发布：`createAgentRun` 返回 `runId` 后 runner 在后台执行，事件产生即 `appendEvent` 落盘；SSE stream 轮询 durable store，发现新事件即推送到客户端。
- event cursor：每个发布事件携带其 `sequence` 作为重连 cursor。
- reconnect replay：客户端带 `?cursor=N` 重连，服务端 `load()` 全量重放 + 内存过滤 `sequence > cursor` 续传缺失事件。
- terminal state 收敛：`run_completed` / `run_failed` 后关闭 stream；terminal 后重连只补发 terminal 事件即关闭。
- 客户端 reconnect：`AgentConsole.tsx` 记录 last sequence，`onerror` 时 `?cursor=N` 重连。

**Non-Goals:**

- durable state foundation 本身（项1）：事件持久化存储、cross-restart 恢复、ownership/lease 归项1。
- WebSocket / 双向流：本项仍是 SSE first（单向 server push）。
- 双向 HITL 协作协议：approval/batch continuation 的交互通道不在本项。
- Gateway（Java 侧）、trusted principal / tenant（项2）、durable ApprovalStore（项3）。
- 向 `DurableRunStore` 添加新接口（如 `subscribe` / `getEventsAfter`）。

## Decisions

D1-D5 来自 `design.md`，保持不变。3 个 Open Question 于 2026-08-02 brainstorming 确认：

| Open Question | 决策 | 理由 |
|---|---|---|
| cursor 存储位置 | **复用 `DurableRunStore.load(runId)` 全量重放 + 内存过滤 `sequence > cursor`** | 项1 `load()` 已返回 sequence 排序事件；零新接口、零新存储；单 run 事件量有限，全量重放足够快 |
| reconnect 窗口长度 | **永久保留至 run 文件被外部清理（无 TTL）** | 跟随 run 文件生命周期；不新增 TTL 参数和清理逻辑；terminal 后重连只补发 terminal 即关闭 |
| 背压策略 | **不丢策略：Node stream 背压传导 + cursor 重连兜底** | `res.write` 返回 false 时暂停轮询；事件已 per-event fsync 不丢；客户端 `?cursor=N` 重连补发 |

**补充决策（brainstorm 衍生）：**

| 决策 | 内容 | 理由 |
|---|---|---|
| D6 - stream route 轮询模式 | stream route 用短间隔轮询 `load()` 发现新事件，不用 pub/sub | 复用 `load()` 零新接口；runner 是秒级 subprocess，轮询足够响应 |
| D7 - 客户端 reconnect 纳入 | `AgentConsole.tsx` 记录 last sequence + `onerror` 重连 | 后端 cursor 无前端配合则无法端到端验证 |
| D8 - `createAgentRun` 后台执行 | `createAgentRun` 保存 `run_started` + claim lease 后立即返回 `runId`，runner 在后台 fire-and-forget 执行 | 客户端需在 runner 执行期间就能打开 stream 收到增量事件 |

## 详细设计

### §1 增量发布

#### 1.1 `createAgentRun` 改造

当前流程（`agent-runtime-adapter.ts:101-166`）：

```
POST -> createAgentRun:
  save(run_started) -> claim -> await runner() -> buildEventsFromOutcome() -> appendEvent loop
  -> handle pendingOutcome/session -> release lease -> return { runId }
```

POST 响应阻塞到 runner 完成，客户端无法在 runner 执行期间打开 stream。

改造后流程：

```
POST -> createAgentRun:
  save(run_started) -> claim -> void executeRunnerInBackground(runId, query, input, timestamp)
  -> return { runId }                    // 立即返回

executeRunnerInBackground (fire-and-forget):
  await runner() -> emitEventsFromOutcome(appendEvent per event) -> handle pendingOutcome/session
  -> release lease (completed) or release lease (awaiting)
  catch -> appendFailureEvents -> release lease
```

关键变更：
- `createAgentRun` 在 `runStore.save(runId, record)`（保存 `run_started` 事件）+ `runStore.claim(...)` 之后，用 `void executeRunnerInBackground(...)` 启动后台执行，立即 `return { runId }`。
- `run_started` 事件（sequence=1）在返回前已落盘，客户端打开 stream 时立即可收到。
- 后台执行的错误处理与当前 `try/catch` 一致：runner 抛错时 append `run_failed` 事件 + release lease。

#### 1.2 `buildEventsFromOutcome` 改造为 emitter

当前 `buildEventsFromOutcome` 返回完整 `AgentRunEvent[]`，调用方再循环 `appendEvent`。改造为接受 `emit` 回调，每个事件构建后立即调用 `emit`（即 `appendEvent`）：

```
emitEventsFromOutcome(runId, query, outcome, timestamp, emit: (event) => Promise<void>):
  emit(run_started)                      // sequence=1，已在 createAgentRun 中 save
  emit(intent_parsed)                    // sequence=2
  ... 每个事件构建后立即 emit + fsync ...
  if (awaiting_approval) { emit(approval events); return }  // 早退，无 terminal
  if (awaiting_batch_confirm) { emit(batch event); return } // 早退，无 terminal
  if (validation failed) { emit(run_failed); return }        // terminal
  ...
  emit(run_completed) or emit(run_failed)                    // terminal
```

`push` 辅助函数从同步 push-to-array 改为 async emit-callback。`sequence` 分配逻辑不变（`events.length + 1` 或 `base + events.length + 1`）。

`buildApprovalEvents` / `buildBatchEvents` 同理改造为 emitter 模式，用于 continuation 路径。

#### 1.3 continuation 路径同步改造

`decideAgentRunApproval` / `confirmAgentRunBatch` 当前也是 `await runner()` 后批量 append。改造为后台执行模式：
- POST `/approval` 和 `/batch` 在校验 + claim lease + appendDecision 后立即返回 `{ runId }`。
- runner 在后台执行，事件产生即 `appendEvent`。
- 客户端用 `?cursor=N` 重连获取 continuation 事件。

#### 1.4 SSE stream route 改造为轮询 live stream

当前 `stream/route.ts` 一次性 `getAgentRunEvents` + 拼接 body 返回。改造为 `ReadableStream` 轮询模式：

```
GET /api/agent-runs/[runId]/stream?cursor=N:
  validate cursor (non-negative integer, default 0)
  const stream = new ReadableStream({
    start(controller) {
      poll(controller, runId, cursor)
    },
    cancel() { /* client disconnected, stop polling */ }
  })
  return new Response(stream, { headers: SSE headers })

  poll(controller, runId, lastCursor):
    record = await runStore.load(runId)
    if (!record) { controller.error(404); return }
    newEvents = record.events.filter(e => e.sequence > lastCursor)
    for (event of newEvents) {
      chunk = `event: ${event.type}\ndata: ${JSON.stringify(event)}\n\n`
      if (!controller.write(chunk)) {
        // backpressure: wait for drain before continuing
        await waitForDrain
      }
      lastCursor = event.sequence
    }
    lastEvent = record.events[record.events.length - 1]
    if (isTerminal(lastEvent)) { controller.close(); return }
    setTimeout(() => poll(controller, runId, lastCursor), POLL_INTERVAL)
```

- 轮询间隔 `POLL_INTERVAL`：50ms（非规范性，runner 是秒级 subprocess，50ms 轮询足够响应且不过度读盘）。
- `isTerminal(event)`：`event.type === "run_completed" || event.type === "run_failed"`。
- 背压处理：`controller.write` 返回 false 时暂停轮询，等待 drain 后恢复（详见 §5）。

### §2 Event cursor

**复用 `AgentRunEvent.sequence`（`run-event-schema.ts:51`），不引入新字段。**

- `sequence` 已由 `buildEventsFromOutcome` 的 `push` 辅助函数分配（`events.length + 1`），已由 `appendEvent` 持久化到 JSONL。
- SSE 事件 payload 中已包含 `sequence` 字段（`JSON.stringify(event)` 序列化全部字段）。
- 客户端从每个收到的事件中读取 `event.sequence`，记录最后收到事件的 sequence 作为重连 cursor。
- 无需额外的 cursor token、cursor 编码、cursor 存储。`sequence` 是单调递增整数，语义清晰。

### §3 Reconnect replay

**stream route 加 `?cursor=<sequence>` 查询参数，`load()` 全量重放 + 内存过滤 `sequence > cursor`。**

#### 3.1 cursor 参数解析与校验

```
cursor = searchParams.get("cursor")
if cursor is null -> cursor = 0 (从头发送)
if cursor is not a non-negative integer -> 400 Bad Request
```

- `cursor=0`：从 `run_started`（sequence=1）开始发送全部事件（首次连接）。
- `cursor=N`（N > 0）：只发送 `sequence > N` 的事件（重连续传）。

#### 3.2 replay 流程

```
record = await runStore.load(runId)
// load() 重放 JSONL，返回 events 按 sequence 升序排序
events = record.events.filter(e => e.sequence > cursor)
for (event of events) { emit SSE chunk }
lastCursor = events.length > 0 ? events[events.length - 1].sequence : cursor
```

- `load()` 是项1 已实现的接口（`jsonl-run-store.ts:132-178`）：读取 `runs/<runId>.jsonl`，重放全部行，`events.sort((a, b) => a.sequence - b.sequence)`。
- 过滤在内存完成，零新存储接口。
- replay 读取的是 durable 已 fsync 的事件子集，保证不丢失。

#### 3.3 cursor 超出已知事件范围

- `cursor` >= 当前最大 sequence 且 run 未 terminal：无事件可发，进入轮询等待新事件。
- `cursor` >= 当前最大 sequence 且 run 已 terminal：无事件可发，stream 立即关闭（terminal 后无新事件）。
- `cursor` 指向不存在的事件（如 cursor=999 但 run 只有 5 个事件）：等同于 cursor >= 最大 sequence，按上述处理。不返回错误（cursor 是客户端记录的最后收到 sequence，可能超前于服务端当前状态，如客户端收到了事件但服务端还在 fsync 中）。

### §4 Terminal 收敛

#### 4.1 terminal 事件定义

Per spec，terminal 事件为 `run_completed` 和 `run_failed`（`AgentRunEventType`）。其他事件类型（`approval_state_changed`、`batch_confirm_requested` 等）不是 terminal。

#### 4.2 stream 关闭时序

当 stream route 在轮询中发现最后一条事件是 terminal：

```
if (isTerminal(lastEvent)) {
  // terminal 事件已通过 §3 replay 发送给客户端
  controller.close()   // 关闭 SSE stream
  return               // 停止轮询
}
```

- terminal 事件先发送给客户端，再关闭 stream。客户端收到 terminal 后知道 run 已终态。
- cursor 在 terminal 后收敛：`run_completed` / `run_failed` 之后不再产生新事件，cursor 停在 terminal 事件的 sequence。

#### 4.3 terminal 后重连

客户端在 terminal 后断线重连（`?cursor=N`，N < terminal sequence）：

```
load() -> events 包含 terminal 事件
filter(sequence > N) -> 包含 terminal 事件
emit terminal 事件 -> 关闭 stream
```

客户端在 terminal 后重连（`?cursor=N`，N >= terminal sequence）：

```
load() -> events 包含 terminal 事件
filter(sequence > N) -> 空集（terminal sequence 不 > N）
检查最后事件是 terminal -> 关闭 stream
```

两种情况都正确收敛：前者补发 terminal 后关闭，后者无事件可发直接关闭。

#### 4.4 rejection 路径补齐 terminal 事件

**当前 gap**：`buildApprovalEvents` 在 `outcome.status === "rejected"` 时只 emit `approval_state_changed`（state: "rejected"），不 emit `run_failed` 或 `run_completed`（`agent-runtime-adapter.ts:614-618`）。这导致 stream 无法基于 terminal 事件类型关闭。

**修复**：`buildApprovalEvents` 的 rejection 分支在 `approval_state_changed` 事件之后追加 `run_failed` terminal 事件：

```
if (outcome.status === "rejected") {
  pushAll({ type: "approval_state_changed", state: "rejected", hitlState: "rejected", ... })
  pushAll({ type: "run_failed", state: "failed", error: { errorType: "APPROVAL_REJECTED", message: "...", stage: "approval_checked" } })
  return events
}
```

这样 stream 在 rejection 后也能基于 `run_failed` terminal 事件正确关闭。客户端现有 `state === "rejected"` 的 terminal 判断保留作为兼容，但服务端以 `run_failed` 事件类型为准。

### §5 背压策略

**不丢策略：Node stream 背压传导 + cursor 重连兜底。**

#### 5.1 背压传导

stream route 用 `ReadableStream` + `controller.write(chunk)` 推送 SSE chunk。当客户端消费慢时：

1. `controller.write(chunk)` 返回 `false`（写缓冲区满）。
2. stream route 暂停轮询：不调用 `load()` 读取新事件，不追加新 chunk。
3. 等待 `ReadableStream` 的 drain 信号（通过 `controller` 的背压机制或 `writer.ready` Promise）。
4. drain 后恢复轮询。

背压传导链：客户端慢 -> `controller.write` 返回 false -> 暂停轮询 -> 不读新事件 -> durable store 中事件继续累积（runner 不受影响，继续 `appendEvent`）-> 客户端恢复后轮询补发。

#### 5.2 不丢保证

- 事件在 `appendEvent` 时已 per-event fsync 到 `runs/<runId>.jsonl`（项1 `jsonl-run-store.ts:101-109`）。
- 背压只延迟 delivery，不影响 persistence。
- 客户端断线时，已 fsync 的事件在 `load()` 重放中完整可用。
- 客户端用 `?cursor=N` 重连，`load()` + 过滤 `sequence > cursor` 补发全部缺失事件。

#### 5.3 不引入参数

- 不设缓冲上限参数（Node stream 内部缓冲由 runtime 管理）。
- 不设丢弃策略参数（不丢策略，无丢弃）。
- 不设慢消费者超时参数（客户端慢时无限等待 drain 或断线后 cursor 重连）。

### §6 客户端 reconnect

#### 6.1 last sequence 记录

`AgentConsole.tsx` 的 `streamAgentRun` 函数当前用 `nextSnapshot.events` 做去重。改造为额外维护 `lastSequence` 变量：

```
function streamAgentRun(localRunId, serverRunId, initialSnapshot, cursor = 0) {
  let nextSnapshot = initialSnapshot
  let lastSequence = cursor
  let intentionallyClosed = false
  const url = `/api/agent-runs/${serverRunId}/stream?cursor=${cursor}`
  const stream = new EventSource(url)

  const handleRunEvent = (message: MessageEvent<string>) => {
    const event = JSON.parse(message.data) as AgentRunEvent
    if (nextSnapshot.events.some(e => e.sequence === event.sequence)) {
      return  // 去重：重连后可能收到已处理的事件
    }
    lastSequence = event.sequence
    nextSnapshot = applyRunEvent(nextSnapshot, event)
    // ... 更新 turns ...
    // ... terminal/paused 关闭逻辑不变 ...
  }

  stream.onmessage = handleRunEvent
  agentRunEventTypes.forEach(t => stream.addEventListener(t, handleRunEvent))

  stream.onerror = () => {
    stream.close()
    if (intentionallyClosed) return
    // 重连：用 lastSequence 作为 cursor
    setTimeout(() => {
      streamAgentRun(localRunId, serverRunId, nextSnapshot, lastSequence)
    }, RECONNECT_DELAY)
  }
}
```

#### 6.2 重连参数

- `RECONNECT_DELAY`：500ms（非规范性，避免断线后立即重连风暴）。
- 重连 URL 带上 `?cursor=<lastSequence>`，服务端从该 cursor 之后续传。
- 重连后的事件通过现有 `sequence` 去重逻辑（`nextSnapshot.events.some(e => e.sequence === event.sequence)`）处理可能的重叠。

#### 6.3 重连退出条件

- 收到 terminal 事件（`run_completed` / `run_failed`）后 `intentionallyClosed = true`，不再重连。
- 收到 `awaiting_approval` 后 `intentionallyClosed = true`，不再重连（等待用户审批后手动开新 stream）。
- 用户主动导航离开或切换 session 时不再重连（由 React 组件生命周期管理）。

#### 6.4 continuation 后重连

`decideApproval` 函数在 POST 完成后调用 `streamAgentRun`。改造后 POST 立即返回（runner 后台执行），`streamAgentRun` 带上 `cursor = lastSequence`（approval 前最后收到事件的 sequence），获取 continuation 事件。

### §7 `buildEventsFromOutcome` 早退分支处理

`buildEventsFromOutcome` 有多个早退分支，每个分支的 stream 关闭时序如下：

| 分支 | 触发条件 | 最后事件 | 是否 terminal | stream 行为 |
|---|---|---|---|---|
| 无 callPlan | `!callPlan` | `run_failed` 或 `run_completed`（clarification） | 是 | emit terminal -> 关闭 stream |
| awaiting_approval | `isAction && status === "awaiting_approval"` | `approval_state_changed`（awaiting） | 否 | emit 后继续轮询；客户端可选关闭等审批 |
| awaiting_batch_confirm | `status === "awaiting_batch_confirm"` | `batch_confirm_requested` | 否 | emit 后继续轮询；客户端可选关闭等确认 |
| validation 失败 | `validation.success === false` | `run_failed` | 是 | emit terminal -> 关闭 stream |
| execution 失败 | `execution.success === false` | `run_failed` | 是 | emit terminal -> 关闭 stream |
| 正常完成 | `status === "success"` / `"clarification"` | `run_completed` | 是 | emit terminal -> 关闭 stream |
| 其他失败 | 其他非 success 状态 | `run_failed` | 是 | emit terminal -> 关闭 stream |

**paused 状态（awaiting_approval / awaiting_batch_confirm）的 stream 时序：**

1. `buildEventsFromOutcome` emit 完 paused 事件后早退，无 terminal 事件。
2. stream route 轮询 `load()`，发现最后事件不是 terminal，继续轮询。
3. 但 runner 已早退，不会有新事件产生。stream route 持续轮询直到客户端关闭。
4. 客户端在收到 `awaiting_approval` 事件后 `intentionallyClosed = true` 并关闭 stream（现有行为）。
5. 用户审批后，客户端用 `?cursor=N` 开新 stream，获取 continuation 事件（`buildApprovalEvents` / `buildBatchEvents` 产生的事件）。
6. continuation 事件中包含 terminal（`run_completed` / `run_failed`），stream 正常关闭。

**optimization：paused 状态时服务端可降低轮询频率**（如从 50ms 降到 1s），减少无效读盘。此为实现优化，不影响契约。

**rejection 路径（§4.4 修复后）：**

1. `buildApprovalEvents` emit `approval_state_changed`（rejected）+ `run_failed`（terminal）。
2. stream route emit 两个事件后检测到 `run_failed`，关闭 stream。
3. 客户端收到 `rejected` state 后 `intentionallyClosed = true` 并关闭 stream（现有行为兼容）。

## 替换点

| 当前 | 替换为 |
|---|---|
| `createAgentRun` await runner 后批量构建（`:129-163`） | `createAgentRun` 立即返回 runId + 后台 `executeRunnerInBackground` |
| `buildEventsFromOutcome` 返回 `AgentRunEvent[]`（`:304-494`） | `emitEventsFromOutcome` 接受 `emit` 回调，每事件立即 `appendEvent` |
| `buildApprovalEvents` / `buildBatchEvents` 返回数组（`:601-672`） | 同理改造为 emitter 模式 |
| stream route 一次性 `getAgentRunEvents` + 拼接 body（`stream/route.ts:3-15`） | stream route `ReadableStream` 轮询 `load()` + `?cursor=N` 过滤 |
| `AgentConsole.tsx` `onerror` 显示错误不重连（`:89-101`） | `onerror` 记录 `lastSequence` + `?cursor=N` 重连 |
| `AgentConsole.tsx` EventSource 无 cursor 参数（`:67`） | EventSource URL 带 `?cursor=<lastSequence>` |
| `buildApprovalEvents` rejection 无 terminal 事件（`:614-618`） | rejection 后追加 `run_failed` terminal 事件 |
| `decideAgentRunApproval` / `confirmAgentRunBatch` await runner（`:173-294`） | 校验 + claim + appendDecision 后立即返回，runner 后台执行 |

**不替换：**
- `DurableRunStore` 接口（`types.ts:82-97`）：不添加新方法。
- `JsonlRunStore` 实现（`jsonl-run-store.ts`）：不修改。
- `AgentRunEvent` schema（`run-event-schema.ts`）：不添加新字段。
- `run-state-machine.ts` / `applyRunEvent`：客户端状态机不变。
- `getAgentRunEvents` 函数：保留（可用于非流式一次性读取场景，如测试）。

## 项1 依赖

本 change 消费项1 已落地的接口，不要求项1 新增任何接口：

| 项1 接口 | 本 change 用途 | 位置 |
|---|---|---|
| `DurableRunStore.appendEvent(runId, event)` | 增量发布：每个事件产生即落盘（per-event fsync） | `types.ts:86` / `jsonl-run-store.ts:180-183` |
| `DurableRunStore.load(runId)` | reconnect replay：全量重放 + 内存过滤 `sequence > cursor` | `types.ts:84` / `jsonl-run-store.ts:132-178` |
| `AgentRunEvent.sequence` | event cursor：每个事件携带 sequence 作为重连 cursor | `run-event-schema.ts:51` |
| `DurableRunStore.claim` / `release` | continuation 后台执行时的 lease 管理（现有用法不变） | `types.ts:90-92` |
| `DurableRunStore.appendDecision` | continuation 路径 appendDecision（现有用法不变） | `types.ts:88` |

## Risks / Trade-offs

- **轮询 vs pub/sub** -> 轮询 `load()` 有 50ms 延迟和重复读盘开销。缓解：runner 是秒级 subprocess，50ms 延迟可忽略；`load()` 是单文件读 + JSONL parse，典型 run 几十-几百事件，足够快。不引入 pub/sub 避免新增 store 接口和订阅状态管理。
- **后台执行错误可见性** -> `createAgentRun` 立即返回后，runner 后台执行失败时客户端只能通过 stream 收到 `run_failed` 事件。缓解：`run_failed` 事件携带 error message；stream route 在 `load()` 返回 null 时返回 404。
- **轮询空转（paused 状态）** -> `awaiting_approval` / `awaiting_batch_confirm` 时 runner 已早退，stream route 持续轮询无新事件。缓解：客户端在 paused 状态关闭 stream（现有行为）；服务端可降低轮询频率（实现优化）。
- **rejection terminal gap** -> 当前 `buildApprovalEvents` rejection 路径无 terminal 事件。缓解：本 design §4.4 明确追加 `run_failed` terminal 事件。
- **客户端重连风暴** -> 网络抖动时客户端频繁重连。缓解：`RECONNECT_DELAY` 500ms 间隔；terminal 后不再重连。
- **增量发布改造影响现有 buffered 测试** -> 缓解：tasks 中纳入 `npm --prefix frontend run verify` + 回归测试；`getAgentRunEvents` 保留供测试一次性读取。
- **后台执行与 Next.js 请求生命周期** -> Next.js route handler 返回后后台 Promise 可能被 runtime 回收。缓解：用 `void` fire-and-forget 模式执行，durable store 的 `appendEvent` 是同步 fs 操作，不依赖请求上下文；若 Next.js runtime 限制，可改用 `waitUntil`（Next.js 15+）或独立 worker。

## 与 spec 的映射

| Spec Requirement（`sse-cursor-reconnect`） | Design 章节 |
|---|---|
| Incremental SSE delivery | §1 增量发布（createAgentRun 后台执行 + stream route 轮询） |
| Event cursor for reconnect | §2 event cursor（复用 `AgentRunEvent.sequence`） |
| Reconnect replay completeness | §3 reconnect replay（`load()` + 过滤 `sequence > cursor`） |
| Terminal state closes stream | §4 terminal 收敛（`run_completed` / `run_failed` 后关闭 stream） |
| (client reconnect) | §6 客户端 reconnect（AgentConsole.tsx last sequence + `?cursor=N`） |
| (backpressure no-loss) | §5 背压策略（Node stream 背压 + cursor 重连兜底） |
| (early-exit branch handling) | §7 buildEventsFromOutcome 早退分支处理 |


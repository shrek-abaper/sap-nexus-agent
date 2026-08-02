# Brainstorm Summary - sap-nexus-incremental-sse-reconnect

> Phase: design | Status: finalized | Date: 2026-08-02
> Recovery checkpoint: all decisions below are user-confirmed; no pending/candidate items.

## Context

本 change 将 Workbench 的 buffered SSE-format 升级为增量发布 + cursor 断线续传。open 阶段 `design.md` 留下 3 个 Open Questions（cursor 存储位置、reconnect 窗口长度、背压策略），本 brainstorm 逐项确认决策。项1 `sap-nexus-durable-state-foundation` 已落地 `JsonlRunStore`（`appendEvent` per-event fsync + `load()` 全量重放返回 sequence 排序事件），为本 change 提供持久化基础。

## Open Question 决策

### OQ1 - cursor 存储位置

**决策：A - 直接复用 `DurableRunStore.load(runId)` 全量重放 + 内存过滤 `sequence > cursor`。**

- 项1 已落地 `JsonlRunStore.load()`：读取 `<runId>.jsonl`，重放全部行，返回 `AgentRunRecord`，其中 `events` 已按 `sequence` 升序排序（`jsonl-run-store.ts:173`）。
- replay 读取的是 durable 已 fsync 的事件子集，cursor 过滤在内存完成：`events.filter(e => e.sequence > cursor)`。
- 零新接口、零新存储。不向 `DurableRunStore` 添加 `getEventsAfter(runId, cursor)` 之类的方法。
- 理由：单 run 事件量有限（几十-几百事件），全量重放 + 内存过滤足够快；引入新接口增加 store 契约面积，违背项1 "store 无关接口先行、实现可插拔"的最小化原则。

### OQ2 - reconnect 窗口长度

**决策：A - 永久保留至 run 文件被外部清理（无 TTL）。**

- 事件保留在 `runs/<runId>.jsonl` 中，跟随 run 文件生命周期。不新增 TTL 清理逻辑、不新增过期参数。
- terminal 后重连：`load()` 返回全部事件（含 terminal），过滤 `sequence > cursor` 后只补发缺失事件；若 cursor 已覆盖 terminal，则无事件可补发，stream 立即关闭。
- 理由：Workbench 非高频场景，run 文件由外部清理（如手动删除、磁盘管理）；引入 TTL 增加配置参数和清理逻辑，超出本 change 范围。

### OQ3 - 背压策略

**决策：A - 不丢策略。客户端慢时服务端阻塞写入（背压传导到 runner），Node stream 自带背压 + cursor 重连兜底。**

- Node.js `res.write(chunk)` 返回 `false` 时表示写缓冲区满（背压信号）。stream route 暂停轮询，等待 `drain` 事件后恢复。
- 事件已 per-event fsync 落盘（项1 `appendEvent` 每事件 `fsyncSync`），不会因背压丢失。
- 客户端断线时 stream route 检测到连接关闭，停止轮询。客户端用 `?cursor=N` 重连补发缺失事件。
- 不引入缓冲上限参数、不引入丢弃策略参数。
- 理由：Workbench 场景下客户端消费速度远超事件产生速度（runner 是秒级 subprocess），背压是兜底而非常态；cursor 重连是最终一致性保证。

## 客户端 reconnect 改造范围

**纳入本 change。** 后端 cursor/replay + 前端 `AgentConsole.tsx` 记录 last sequence + `?cursor=N` 重连。

- `AgentConsole.tsx` 当前 `stream.onerror` 直接显示"连接中断"错误，不重连。
- 改造后：`stream.onerror` 时记录最后收到事件的 sequence，用 `?cursor=<lastSequence>` 重连。
- 现有 sequence 去重逻辑（`nextSnapshot.events.some(e => e.sequence === event.sequence)`）复用，处理重连后可能的事件重叠。

## 共同取向

三个 OQ 全部收敛到"**复用项1 durable events + 复用本 change cursor 机制**"：

| 维度 | 决策 | 复用项 |
|---|---|---|
| cursor 存储 | `load()` 全量重放 + 内存过滤 | 项1 `JsonlRunStore.load()` |
| replay 窗口 | run 文件生命周期（无 TTL） | 项1 `runs/<runId>.jsonl` |
| 背压兜底 | cursor 重连补发 | 本 change `?cursor=N` |
| 客户端重连 | `?cursor=N` + sequence 去重 | 本 change cursor + 现有去重 |

不引入新存储、不引入 TTL 参数、不引入缓冲参数、不引入新 store 接口。项1 依赖仅：`appendEvent`（增量发布落盘）+ `load`（replay 读取）+ `sequence` 字段（cursor），无需项1 新增任何接口。

## 越界声明

- 不触 Gateway（Java 侧）
- 不触 trusted principal / tenant / role（项2）
- 不触 durable ApprovalStore（项3）
- 不触 WebSocket 双向通道
- 不触项1 durable store 接口本身（只消费已有 `appendEvent` / `load`）

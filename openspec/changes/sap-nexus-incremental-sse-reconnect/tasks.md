## 1. Event cursor

- [ ] 1.1 在 SSE route handler 中为每个发布的 AgentRunEvent 暴露其 `sequence` 作为 cursor 字段
- [ ] 1.2 实现 cursor 查询参数解析（`?cursor=<sequence>`），校验 cursor 合法性（非负整数、属于当前 run）
- [ ] 1.3 对接拆分项 1 durable events 持久化层，确认 cursor 读取自 durable 事件存储而非进程内 Map

## 2. Incremental 发布

- [ ] 2.1 改造 `createAgentRun`：移除 await runner 完成后一次性 `buildEventsFromOutcome` 的 buffered 路径，改为事件产生即推送到 SSE stream
- [x] 2.2 将 `buildEventsFromOutcome` 拆分为增量事件发射器，每个事件产生时立即写入 stream 并分配递增 `sequence`
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

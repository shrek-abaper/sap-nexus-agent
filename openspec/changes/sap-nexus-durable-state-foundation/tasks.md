## 1. Store-agnostic 接口契约

- [x] 1.1 定义 `DurableRunStore` 接口（save / load / list / lease / claim / markExecuted）
- [x] 1.2 定义 `DurableConversationStore` 接口（save / load / clear）
- [x] 1.3 定义 structured checkpoint reference 数据结构（`RegistrySnapshotId` + 节点状态 + `ApprovalRecord` 引用）
- [x] 1.4 定义 idempotency key schema（`runId` + continuation type + 参数 hash）

## 2. 本地参考实现（store 选型在 comet-design 阶段决定）

- [ ] 2.1 comet-design 阶段选型本地 store（候选：SQLite / file-based）
- [x] 2.2 实现 `DurableRunStore` 本地参考实现
- [x] 2.3 实现 `DurableConversationStore` 本地参考实现

## 3. 替换进程内 Map

- [x] 3.1 替换 `agent-runtime-adapter.ts` 的 `runs Map`（`globalThis.__SAP_NEXUS_AGENT_RUNS__`）为 `DurableRunStore`
- [x] 3.2 替换 `sessions Map`（`globalThis.__SAP_NEXUS_AGENT_SESSIONS__`）为 `DurableConversationStore`
- [x] 3.3 `AgentRunRecord` / `SessionState` 序列化与反序列化

## 4. Run ownership / lease

- [x] 4.1 实现 run ownership lease（`workerId` + TTL + 续期）
- [x] 4.2 lease 持有期间其他 worker 接管 fail-closed
- [x] 4.3 lease 过期后带审计的强制接管

## 5. Structured checkpoint + 恢复

- [x] 5.1 持久化 structured checkpoint reference（绑定 `RegistrySnapshot` + 节点状态）
- [x] 5.2 恢复时加载原始 `RegistrySnapshot` + 结构化节点状态（不靠 summary / Memory）
- [x] 5.3 snapshot 漂移 fail-closed（复用 S1 validator）
- [ ] 5.4 `ConversationState` 压缩失败保留原 checkpoint 或关闭压缩

## 6. 幂等 continuation

- [x] 6.1 approval / batch continuation 请求带 idempotency key
- [x] 6.2 重复 key 返回已记录结果，不重复执行

## 7. 三层状态分层持久化

- [ ] 7.1 按 §4.2.1 三层分层持久化（`ConversationState` advisory / `PlanExecutionState` authority / `EvidenceState` authority）
- [ ] 7.2 仅 `ConversationState` 可压缩；`PlanExecutionState` / `EvidenceState` 不可压缩

## 8. 测试与验证

- [ ] 8.1 cross-restart 恢复测试（pending / awaiting_approval / awaiting_batch_confirm run 重启后可继续）
- [ ] 8.2 multi-worker 共享 + ownership/lease fail-closed 测试
- [ ] 8.3 checkpoint replay 一致性测试
- [ ] 8.4 幂等 continuation 测试
- [ ] 8.5 `conversational-context` spec 回归（process-local -> durable 语义变更）
- [ ] 8.6 `openspec validate --all --strict` 通过
- [ ] 8.7 `npm --prefix frontend run verify` + agent pytest 回归通过

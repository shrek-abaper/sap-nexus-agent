## 1. DurableApprovalStore 接口契约

- [x] 1.1 扩展 `ApprovalStore` 接口，定义 `DurableApprovalStore` durable 语义（保留 `save` / `find` / `claimForExecution` / `markExecuted` 四方法契约，增加 cross-restart 恢复、cross-worker claim/lease 语义）
- [x] 1.2 定义 `ApprovalRecord` 序列化与反序列化契约（持久化到 durable store，字段：`approvalId` / `capabilityId` / `parameterSnapshotHash` / `parameters` / `approver` / `approvedAt` / `expiresAt` / `status`）
- [x] 1.3 定义 claim/lease 数据结构（`workerId` + lease TTL + 续期），对齐项 1 store 无关接口

## 2. 替换 InMemoryApprovalStore

- [x] 2.1 实现 `DurableApprovalStore`（`save` / `find` / `claimForExecution` / `markExecuted`），复用项 1（`durable-state-foundation`）store 无关接口
- [ ] 2.2 将 `@Component` 绑定从 `InMemoryApprovalStore` 切换到 `DurableApprovalStore`（`ApprovalGuard` 消费 `ApprovalStore` 契约不变）
- [ ] 2.3 移除 `InMemoryApprovalStore` 进程级 `ConcurrentMap` 实现（或保留为测试桩，按 comet-design 决策）

## 3. cross-restart approval 恢复

- [ ] 3.1 重启时从 durable store 恢复 `pending` / `approved` / `executing` 状态 approval，可继续 approve / claim / execute
- [ ] 3.2 `executed` / `rejected` 终态恢复后只读（仅审计查询，不可再迁移）
- [ ] 3.3 恢复时以 JSONL 审计为准对账，durable store 漂移 fail-closed

## 4. cross-worker anti-replay

- [x] 4.1 实现 claim/lease 原子性（durable store 提供等价 `ConcurrentMap.compute` 的跨 worker 原子原语，如 CAS / 行锁）
- [x] 4.2 `claimForExecution` 幂等：已 `executing` / `executed` 的 approval 重复 claim 返回空
- [x] 4.3 lease 过期后允许带审计的重新 claim（worker 崩溃后 lease 过期可被其他 worker 接管）

## 5. JSONL 审计保留

- [ ] 5.1 JSONL trace 保留为 authoritative 审计源，durable store swap 不动 JSONL 审计语义
- [ ] 5.2 durable store 作为 operational index（save / find / claimForExecution / markExecuted），崩溃恢复以 JSONL 为准

## 6. Approval TTL 跨重启校验

- [ ] 6.1 恢复时重新校验 `expiresAt`（`ApprovalRecord.isExpired(Instant)`）
- [ ] 6.2 `claimForExecution` 拒绝过期 approval（返回空），过期 approval 保持恢复态供审计
- [ ] 6.3 TTL 基准时间（`approvedAt` 固定 vs 恢复时刻重置）按 comet-design 决策实现

## 7. 测试与验证

- [ ] 7.1 cross-restart 恢复测试（`pending` / `approved` / `executing` approval 重启后可继续）
- [ ] 7.2 cross-worker anti-replay 测试（重复 claim denied + 并发 claim 原子）
- [ ] 7.3 JSONL 审计保留测试（durable store swap 后 JSONL 仍 authoritative）
- [ ] 7.4 TTL 跨重启校验测试（过期 approval 重启后不可 execute）
- [ ] 7.5 `gradle test`（Gateway core）通过
- [ ] 7.6 `openspec validate --all --strict` 通过

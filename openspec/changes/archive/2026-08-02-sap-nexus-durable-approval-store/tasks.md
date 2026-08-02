## 1. DurableApprovalStore 接口契约

- [x] 1.1 扩展 `ApprovalStore` 接口，定义 `DurableApprovalStore` durable 语义（保留 `save` / `find` / `claimForExecution` / `markExecuted` 四方法契约，增加 cross-restart 恢复、cross-worker claim/lease 语义）
- [x] 1.2 定义 `ApprovalRecord` 序列化与反序列化契约（持久化到 durable store，字段：`approvalId` / `capabilityId` / `parameterSnapshotHash` / `parameters` / `approver` / `approvedAt` / `expiresAt` / `status`）
- [x] 1.3 定义 claim/lease 数据结构（`workerId` + lease TTL + 续期），对齐项 1 store 无关接口

## 2. 替换 InMemoryApprovalStore

- [x] 2.1 实现 `DurableApprovalStore`（`save` / `find` / `claimForExecution` / `markExecuted`），复用项 1（`durable-state-foundation`）store 无关接口
- [x] 2.2 将 `@Component` 绑定从 `InMemoryApprovalStore` 切换到 `DurableApprovalStore`（`ApprovalGuard` 消费 `ApprovalStore` 契约不变）
- [x] 2.3 移除 `InMemoryApprovalStore` 进程级 `ConcurrentMap` 实现（或保留为测试桩，按 comet-design 决策）

## 3. cross-restart approval 恢复

- [x] 3.1 重启时从 durable store 恢复 `pending` / `approved` / `executing` 状态 approval，可继续 approve / claim / execute
- [x] 3.2 `executed` / `rejected` 终态恢复后只读（仅审计查询，不可再迁移）
- ~3.3 恢复时以 JSONL 审计为准对账，durable store 漂移 fail-closed~ - **延后 verify：spec 文本「以 JSONL 为准」与设计 D4（durable store only, 不读 agent JSONL）矛盾；实现遵 D4（reconcile 仅校验 durable store 内部一致性，漂移 fail-closed 已实现）；verify 阶段裁定 spec 修订**

## 4. cross-worker anti-replay

- [x] 4.1 实现 claim/lease 原子性（durable store 提供等价 `ConcurrentMap.compute` 的跨 worker 原子原语，如 CAS / 行锁）
- [x] 4.2 `claimForExecution` 幂等：已 `executing` / `executed` 的 approval 重复 claim 返回空
- [x] 4.3 lease 过期后允许带审计的重新 claim（worker 崩溃后 lease 过期可被其他 worker 接管）

## 5. JSONL 审计保留

- [x] 5.1 JSONL trace 保留为 authoritative 审计源，durable store swap 不动 JSONL 审计语义
- ~5.2 durable store 作为 operational index（save / find / claimForExecution / markExecuted），崩溃恢复以 JSONL 为准~ - **延后 verify：operational index（save/find/claim/markExecuted）已实现（Task 2-4）；「崩溃恢复以 JSONL 为准」与 D4 矛盾，实现遵 D4（durable store 为 authoritative operational index）；verify 裁定 spec 修订**

## 6. Approval TTL 跨重启校验

- [x] 6.1 恢复时重新校验 `expiresAt`（`ApprovalRecord.isExpired(Instant)`）
- ~6.2 `claimForExecution` 拒绝过期 approval（返回空），过期 approval 保持恢复态供审计~ - **延后 verify：store claimForExecution 不检查 expiry（仅查 status==approved，设计分层 store=持久化原语）；TTL 由 ApprovalGuard 4 不变量强制（ApprovalGuard.java:26-28 拒绝过期，do-not-modify）；过期 approval 系统级被拒；verify 裁定归属**
- [x] 6.3 TTL 基准时间（`approvedAt` 固定 vs 恢复时刻重置）按 comet-design 决策实现

## 7. 测试与验证

- [x] 7.1 cross-restart 恢复测试（`pending` / `approved` / `executing` approval 重启后可继续）
- [x] 7.2 cross-worker anti-replay 测试（重复 claim denied + 并发 claim 原子）
- ~7.3 JSONL 审计保留测试（durable store swap 后 JSONL 仍 authoritative）~ - **延后 verify：JSONL 审计语义未改（5.1 已保，无 TraceWriter 改动）；独立 JSONL 测试缺失，verify 裁定是否需补测试**
- [x] 7.4 TTL 跨重启校验测试（过期 approval 重启后不可 execute）
- [x] 7.5 `gradle test`（Gateway core）通过
- [x] 7.6 `openspec validate --all --strict` 通过

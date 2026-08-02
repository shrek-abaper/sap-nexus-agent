## Context

Gateway approval 子系统当前由两层构成：

- `InMemoryApprovalStore`（`services/gateway/core/src/main/java/com/sapnexus/gateway/approval/InMemoryApprovalStore.java`）：`ConcurrentMap<String, ApprovalRecord>` 进程级索引，提供 `save` / `find` / `claimForExecution` / `markExecuted`。状态迁移通过 `ConcurrentMap.compute` 原子化，并发 `markExecuted` 不会观察到半更新记录。接口注释明确："JSONL trace remains the authoritative durable store; this in-memory store provides the process-local index for duplicate protection (per design doc: MVP accepts index loss on restart)"。
- JSONL trace：authoritative durable 审计源，记录 approval 决策链。

`ApprovalGuard`（Task 5）查询此 store 执行 4 种 approval 不变量（presence / TTL / snapshot-hash / duplicate-submit）。`ApprovalRecord` 为 immutable record（`approvalId` / `capabilityId` / `parameterSnapshotHash` / `parameters` / `approver` / `approvedAt` / `expiresAt` / `status`），生命周期 `pending -> approved -> executed`（或 `rejected`）。

P0B 条件门禁要求 approval 跨重启/跨 worker 可恢复且防重放；当前进程级索引重启丢失、multi-worker 不共享。本 change 是 P0B 拆分项 3/4，把进程级索引升级为 durable store，依赖拆分项 1（`durable-state-foundation`）的 store 无关接口与拆分项 2 的 principal 绑定。

## Goals / Non-Goals

**Goals:**

- durable `ApprovalStore`：`ApprovalRecord` 持久化，替换 `InMemoryApprovalStore`，cross-restart 不丢。
- cross-restart approval 恢复：重启后恢复 `pending` / `approved` / `executing` 状态 approval，可继续 approve / claim / execute。
- cross-worker anti-replay：claim/lease 防止多 worker 重复执行同一 approval；`claimForExecution` 对同一 `approvalId` 幂等。
- JSONL 审计保留：JSONL trace 仍是 authoritative 审计源；durable store 是 operational index。

**Non-Goals:**

- durable state foundation（拆分项 1）：store 无关接口与选型由项 1 提供，本 change 消费。
- approval 语义变更：`pr-create-action` 4 种拒绝场景（presence / TTL / snapshot-hash / duplicate-submit）不变。
- trusted principal / tenant / role / data scope（拆分项 2）：approval 绑定 approver principal 由项 2 提供。
- incremental SSE cursor / reconnect（拆分项 4）。
- store 选型预决：复用项 1 的 store 接口与选型，不在本 change open 阶段预决。
- line-by-line 实现：实现细节留 comet-design / build。

## Decisions

- **D1 DurableApprovalStore 接口**：扩展 `ApprovalStore` 接口（保留 `save` / `find` / `claimForExecution` / `markExecuted` 四方法契约），新增 `DurableApprovalStore` 实现 durable 语义，替换 `InMemoryApprovalStore`。复用 JSONL 审计作为 authoritative 审计源。理由：保留 `ApprovalGuard` 消费契约不变，仅替换底层存储；JSONL 审计已 durable，避免双写不一致。备选：新建独立 `DurableApprovalStore` 接口不复用 `ApprovalStore`——拒绝，因 `ApprovalGuard` 已依赖 `ApprovalStore` 契约，复用最小化改动。
- **D2 cross-restart approval 恢复**：重启时从 durable store 恢复 `pending` / `approved` / `executing` 状态 approval；`executed` / `rejected` 终态恢复后只读。理由：未终态 approval 需可继续，终态 approval 仅审计查询。备选：仅恢复 `approved`——拒绝，因 `executing` 状态 approval 在崩溃后需可重放 claim 决策。
- **D3 cross-worker anti-replay**：claim/lease 机制——`claimForExecution` 原子地把 `approved -> executing` 并绑定 worker lease；已 `executing`/`executed` 的 approval 重复 claim 返回空（幂等拒绝）。理由：`InMemoryApprovalStore` 已用 `ConcurrentMap.compute` 保证进程内原子，durable store 需提供跨 worker 等价原子性。备选：纯 idempotency key——拒绝，因 claim/lease 同时覆盖 lease 持有语义（worker 崩溃后 lease 过期可重新 claim）。
- **D4 JSONL 审计保留 authoritative**：JSONL trace 仍是 authoritative 审计源；durable store 是 operational index，崩溃恢复以 JSONL 为准校验。理由：JSONL 审计已 durable 且为既有契约，避免引入第二权威源导致不一致。备选：durable store 升为 authoritative——拒绝，因审计源变更 blast radius 大，超出本 change scope。
- **D5 依赖项 1 store + 项 2 principal 绑定**：`DurableApprovalStore` 复用项 1（`durable-state-foundation`）的 store 无关接口；approval 绑定 approver principal 由项 2 提供。理由：避免重复造 store 抽象；principal 绑定跨拆分项解耦。open 阶段仅定依赖契约，store 选型与 principal schema 留项 1/项 2 design。

## Risks / Trade-offs

- [approval TTL 跨重启语义] -> 恢复时重新校验 `expiresAt`（`ApprovalRecord.isExpired(Instant)`），过期 approval 不可 execute；TTL 基准时间（`approvedAt` vs 恢复时刻）留 comet-design。
- [claim/lease 竞态] -> `InMemoryApprovalStore` 用 `ConcurrentMap.compute` 保证进程内原子；durable store 需等价原子原语（如 store 层 CAS / 行锁），具体留 comet-design。
- [durable 引入运维依赖] -> 复用项 1 store 接口；本地参考实现零依赖，生产实现可替换。
- [JSONL 与 durable store 一致性] -> JSONL 为 authoritative；durable store 崩溃恢复以 JSONL 校验对账，漂移 fail-closed。

## Open Questions

- approval TTL 跨重启语义：TTL 基准时间（`approvedAt` 固定 vs 恢复时刻重置）。
- claim/lease 粒度：per-approval vs per-run；lease TTL 与续期策略。
- store 选型：复用项 1（`durable-state-foundation`）comet-design 阶段选型。

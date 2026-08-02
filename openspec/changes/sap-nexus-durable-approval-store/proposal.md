## Why

Gateway 的 `InMemoryApprovalStore`（`services/gateway/core/src/main/java/com/sapnexus/gateway/approval/InMemoryApprovalStore.java`）是 `ConcurrentMap<String, ApprovalRecord>` 进程级索引，进程重启即丢失，multi-worker 不共享。其接口 `ApprovalStore` 注释明确："JSONL trace remains the authoritative durable store; this in-memory store provides the process-local index... MVP accepts index loss on restart"。P0B 条件门禁要求 approval 跨重启/跨 worker 可恢复且防重放；JSONL trace 已是 durable 审计源，本 change 把进程级索引升级为 durable store + cross-restart 恢复 + cross-worker anti-replay。本 change 是 P0B 拆分项 3/4（已确认拆分项）。

## What Changes

- 把 `InMemoryApprovalStore`（`ConcurrentMap<String, ApprovalRecord>` 进程级索引）替换为 `DurableApprovalStore`：`ApprovalRecord` 持久化到 durable store，approval state 跨进程重启不丢。
- 复用 JSONL 审计：JSONL trace 仍是 authoritative 审计源；durable store 作为 operational index（save / find / claimForExecution / markExecuted）。
- cross-restart approval 恢复：重启后恢复 `pending` / `approved` / `executing` 状态的 approval，可继续 approve / claim / execute。
- cross-worker anti-replay：claim/lease 防止多 worker 重复执行同一 approval；`claimForExecution` 对同一 `approvalId` 幂等。
- `ApprovalStore` 接口扩展：在保留现有四方法契约的前提下，增加 durable 语义（cross-restart 恢复、cross-worker claim/lease）。
- approval 语义不变：`pr-create-action` 的 4 种拒绝场景（presence / TTL / snapshot-hash / duplicate-submit）不变。

## Capabilities

### New Capabilities

- `durable-approval-store`: durable ApprovalRecord 持久化、cross-restart approval 恢复、cross-worker anti-replay（claim/lease + idempotent claimForExecution）、JSONL 审计保留为 authoritative 审计源。

### Modified Capabilities

<!-- 现有 capability 的 REQUIREMENT 不变更。approval 4 种拒绝场景（presence / TTL / snapshot-hash / duplicate-submit）由 pr-create-action / gateway-execution-contract 约束，本 change 仅替换 InMemoryApprovalStore 实现层，不改 spec 级行为。Leave empty. -->

## Impact

- `services/gateway/core/src/main/java/com/sapnexus/gateway/approval/`：`InMemoryApprovalStore` 替换为 `DurableApprovalStore`；`ApprovalStore` 接口扩展 durable 语义；`ApprovalGuard`（Task 5）消费 store 的方式不变。
- `ApprovalRecord`（record，含 `approvalId` / `capabilityId` / `parameterSnapshotHash` / `parameters` / `approver` / `approvedAt` / `expiresAt` / `status`）：序列化与反序列化以持久化到 durable store。
- JSONL 审计 trace：保留为 authoritative 审计源，不动其语义。
- 依赖：拆分项 1（`durable-state-foundation`）的 store 无关接口；拆分项 2 的 principal 绑定（approval 绑定 approver principal）。
- 非目标：durable state foundation（项 1）、approval 语义变更（4 种拒绝场景不变）、principal/tenant/role（项 2）、incremental SSE（项 4）、store 选型预决（comet-design 阶段）。

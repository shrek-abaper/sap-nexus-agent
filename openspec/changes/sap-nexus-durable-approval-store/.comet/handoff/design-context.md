# Comet Design Handoff

- Change: sap-nexus-durable-approval-store
- Phase: design
- Mode: compact
- Context hash: 21347cc49ac46635dce387ef1f2a10b63f41e1bf2c2d8c6a4199f81c315a2dda

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/sap-nexus-durable-approval-store/proposal.md

- Source: openspec/changes/sap-nexus-durable-approval-store/proposal.md
- Lines: 1-30
- SHA256: 8f706acf76946720889a1433c3a96d4358865ad5d21196045ee43250d1ac392b

```md
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

```

## openspec/changes/sap-nexus-durable-approval-store/design.md

- Source: openspec/changes/sap-nexus-durable-approval-store/design.md
- Lines: 1-49
- SHA256: 9e266fd552f3d848dbb94f38cc81eff5e7b3bc8db808230144ddc42bf5a3578e

```md
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

```

## openspec/changes/sap-nexus-durable-approval-store/tasks.md

- Source: openspec/changes/sap-nexus-durable-approval-store/tasks.md
- Lines: 1-43
- SHA256: ed0d27818f544a070cb5bb1f2c4217d015ee3fef102a79d29d268d582fbf8c88

```md
## 1. DurableApprovalStore 接口契约

- [ ] 1.1 扩展 `ApprovalStore` 接口，定义 `DurableApprovalStore` durable 语义（保留 `save` / `find` / `claimForExecution` / `markExecuted` 四方法契约，增加 cross-restart 恢复、cross-worker claim/lease 语义）
- [ ] 1.2 定义 `ApprovalRecord` 序列化与反序列化契约（持久化到 durable store，字段：`approvalId` / `capabilityId` / `parameterSnapshotHash` / `parameters` / `approver` / `approvedAt` / `expiresAt` / `status`）
- [ ] 1.3 定义 claim/lease 数据结构（`workerId` + lease TTL + 续期），对齐项 1 store 无关接口

## 2. 替换 InMemoryApprovalStore

- [ ] 2.1 实现 `DurableApprovalStore`（`save` / `find` / `claimForExecution` / `markExecuted`），复用项 1（`durable-state-foundation`）store 无关接口
- [ ] 2.2 将 `@Component` 绑定从 `InMemoryApprovalStore` 切换到 `DurableApprovalStore`（`ApprovalGuard` 消费 `ApprovalStore` 契约不变）
- [ ] 2.3 移除 `InMemoryApprovalStore` 进程级 `ConcurrentMap` 实现（或保留为测试桩，按 comet-design 决策）

## 3. cross-restart approval 恢复

- [ ] 3.1 重启时从 durable store 恢复 `pending` / `approved` / `executing` 状态 approval，可继续 approve / claim / execute
- [ ] 3.2 `executed` / `rejected` 终态恢复后只读（仅审计查询，不可再迁移）
- [ ] 3.3 恢复时以 JSONL 审计为准对账，durable store 漂移 fail-closed

## 4. cross-worker anti-replay

- [ ] 4.1 实现 claim/lease 原子性（durable store 提供等价 `ConcurrentMap.compute` 的跨 worker 原子原语，如 CAS / 行锁）
- [ ] 4.2 `claimForExecution` 幂等：已 `executing` / `executed` 的 approval 重复 claim 返回空
- [ ] 4.3 lease 过期后允许带审计的重新 claim（worker 崩溃后 lease 过期可被其他 worker 接管）

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

```

## openspec/changes/sap-nexus-durable-approval-store/specs/durable-approval-store/spec.md

- Source: openspec/changes/sap-nexus-durable-approval-store/specs/durable-approval-store/spec.md
- Lines: 1-43
- SHA256: 297e04225ae7851b34a5cb77a37e25aa0eeeb20d852a943839810c5e2995c7c6

```md
## ADDED Requirements

### Requirement: Durable approval persistence
The system SHALL persist `ApprovalRecord` in a durable store replacing the `InMemoryApprovalStore` (`ConcurrentMap<String, ApprovalRecord>` process-local index). Approval state SHALL survive process restart. The durable store SHALL provide the operational index (save / find / claimForExecution / markExecuted).

#### Scenario: Approval recovers across process restart
- **WHEN** an approval is in `pending` or `approved` state and the Gateway process restarts
- **THEN** the approval is recovered from the durable store with its full `ApprovalRecord`
- **AND** the user can continue to approve / claim / execute the approval after restart

#### Scenario: Executing state recovers across restart
- **WHEN** an approval is in `executing` state (claimed but not yet `executed`) and the Gateway process restarts
- **THEN** the approval is recovered with its `executing` status from the durable store
- **AND** the approval can be re-claimed or marked executed per recovery policy

### Requirement: Cross-worker anti-replay
The system SHALL prevent duplicate approval execution across workers via claim/lease. `claimForExecution` SHALL be idempotent per `approvalId`: a second claim for an already-`executing` or `executed` approval SHALL return empty. The durable store SHALL provide atomicity equivalent to `InMemoryApprovalStore`'s `ConcurrentMap.compute`.

#### Scenario: Cross-worker duplicate claim denied
- **WHEN** worker A claims approval X for execution (transitions `approved -> executing`) and worker B attempts to claim the same approval X
- **THEN** worker B's claim returns empty (idempotent rejection)
- **AND** approval X is not doubly-executed

#### Scenario: Concurrent claim is atomic
- **WHEN** two workers concurrently call `claimForExecution` for the same `approvalId`
- **THEN** exactly one claim succeeds atomically (transitions `approved -> executing`)
- **AND** the other claim returns empty

### Requirement: JSONL audit retained as authoritative
The JSONL trace SHALL remain the authoritative audit source for approval decisions. The durable store SHALL be the operational index. On recovery, the durable store SHALL be reconciled against the JSONL audit; drift SHALL fail closed.

#### Scenario: JSONL audit preserved after durable store swap
- **WHEN** `InMemoryApprovalStore` is replaced by `DurableApprovalStore`
- **THEN** the JSONL audit trace continues to record approval decisions as the authoritative audit source
- **AND** the durable store serves as the operational index (save / find / claimForExecution / markExecuted)

### Requirement: Approval TTL re-validation across restart
The system SHALL re-validate `expiresAt` on recovery. Expired approvals SHALL NOT be executable. `claimForExecution` SHALL reject an approval whose `expiresAt` is in the past (per `ApprovalRecord.isExpired(Instant)`).

#### Scenario: Expired approval rejected after restart
- **WHEN** an approval whose `expiresAt` is in the past is recovered after restart
- **THEN** `claimForExecution` rejects the expired approval (returns empty)
- **AND** the approval remains in its recovered state for audit

```

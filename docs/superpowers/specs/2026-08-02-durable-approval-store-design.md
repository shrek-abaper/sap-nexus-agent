---
comet_change: sap-nexus-durable-approval-store
role: technical-design
canonical_spec: openspec
archived-with: 2026-08-02-sap-nexus-durable-approval-store
status: final
---

# Design: Durable Approval Store (P0B 项3)

> Comet change: `sap-nexus-durable-approval-store` (phase: design)
> Canonical spec: `openspec/changes/sap-nexus-durable-approval-store/specs/`
> 本文档把 change `design.md` 的 D1-D5 与 3 个 Open Question 决策展开为可实施的技术设计。

## Context

Gateway approval 子系统当前由两层构成：

- `InMemoryApprovalStore`（`services/gateway/core/src/main/java/com/sapnexus/gateway/approval/InMemoryApprovalStore.java`）：`ConcurrentMap<String, ApprovalRecord>` 进程级索引，提供 `save` / `find` / `claimForExecution` / `markExecuted`。状态迁移通过 `ConcurrentMap.compute` 原子化（`InMemoryApprovalStore:33` `computeIfPresent`），并发 `markExecuted` 不会观察到半更新记录。接口注释明确："JSONL trace remains the authoritative durable store; this in-memory store provides the process-local index... MVP accepts index loss on restart"。
- JSONL trace：authoritative durable 审计源（agent 侧写的 `approval.jsonl`），记录 approval 决策链。

`ApprovalGuard`（`ApprovalGuard.java`）查询此 store 执行 4 种 approval 不变量（presence / TTL / snapshot-hash / duplicate-submit）。`CapabilityController.execute()`（`CapabilityController.java:137-258`）的执行流程为：`find` -> `guard.check` -> `claimForExecution` -> `dispatch` -> `markExecuted`（finally 块，行 246-248）。

`ApprovalRecord`（`ApprovalRecord.java`）为 immutable record（`approvalId` / `capabilityId` / `parameterSnapshotHash` / `parameters` / `approver` / `approvedAt` / `expiresAt` / `status`），生命周期 `pending -> approved -> executed`（或 `rejected`）。`isExpired(Instant)` 是墙钟校验（`now.isAfter(expiresAt)`）。`CapabilityController.isValidApprovedRecord`（行 114-134）硬校验 `ttlSeconds <= 600`。

P0B 条件门禁要求 approval 跨重启/跨 worker 可恢复且防重放；当前进程级索引重启丢失、multi-worker 不共享。本 change 是 P0B 拆分项 3/4，把进程级索引升级为 durable store。

**与项1 的关系**：项1（`durable-state-foundation`）的 store 接口是 TypeScript（`frontend/src/runtime/durable/types.ts:82-104` `DurableRunStore`），Gateway 是 Java，跨语言无法直接复用。本 change 借鉴项1 的设计模式（lease 三态 `LeaseOutcome`、tmp+rename 原子写、idempotency），Java 侧独立实现。

## Goals / Non-Goals

**Goals:**

- durable `ApprovalStore`：`ApprovalRecord` 持久化，替换 `InMemoryApprovalStore`，cross-restart 不丢。
- cross-restart approval 恢复：重启后恢复 `pending` / `approved` / `executing` 状态 approval，可继续 approve / claim / execute。
- cross-worker anti-replay：claim/lease 防止多 worker 重复执行同一 approval；`claimForExecution` 对同一 `approvalId` 幂等。
- JSONL 审计保留：JSONL trace 仍是审计源；durable store 是 Gateway 侧权威操作索引。

**Non-Goals:**

- durable state foundation（拆分项 1）：项1 提供 TypeScript 侧 durable run/session store，本 change 借鉴其设计模式但 Java 侧独立实现。
- approval 语义变更：`pr-create-action` 4 种拒绝场景（presence / TTL / snapshot-hash / duplicate-submit）不变。
- trusted principal / tenant / role / data scope（拆分项 2）：approval 绑定 approver principal 由项 2 提供；本 change 弱依赖 `approver` 字段（当前是 String，只持久化不关心语义）。
- incremental SSE cursor / reconnect（拆分项 4）。
- multi-worker 并发的生产级实现：本 change 单 worker durable + lease 接口为 multi-worker 预留；生产级 multi-worker 文件锁/Postgres 实现留后续。

## Decisions

D1-D5 来自 `design.md`，D4/D5 经 brainstorming 修正。3 个 Open Question 于 2026-08-02 用户确认：

| 编号 | 决策 | 理由 |
|---|---|---|
| D1 | `DurableApprovalStore extends ApprovalStore` | 保留 `ApprovalGuard` / `CapabilityController` 消费契约不变，仅替换底层存储 |
| D2 | 恢复 `pending`/`approved`/`executing` 状态 approval | 未终态 approval 需可继续；`executed`/`rejected` 终态恢复后只读 |
| D3 | claim/lease 防重放 | `claimForExecution` 原子迁移 `approved->executing` + 绑定 lease；重复 claim 返回空 |
| D4（修正） | durable store 为权威操作索引，JSONL trace 为审计源 | 不跨服务读 agent JSONL；恢复以 durable store 内部一致性校验为准，漂移 fail-closed |
| D5（修正） | 借鉴项1 store 设计模式，Java 侧独立实现 | 项1 是 TypeScript，Gateway 是 Java，跨语言无法直接复用；独立实现 lease/tmp+rename/idempotency |

| Open Question | 决策 | 理由 |
|---|---|---|
| OQ-1 TTL 基准 | A: `approvedAt` 固定基准 | 墙钟 `isExpired(now)` 直接计算，保 600s 安全窗口，重置会突破安全窗口 |
| OQ-2 claim/lease 粒度 | C: per-approval + lease 三态 | 对齐 `claimForExecution(approvalId)`；lease TTL 60s；借鉴项1 `LeaseOutcome` 三态 |
| OQ-3 store 选型 | B+C: Java 独立 + 借鉴项1 | `DurableApprovalStore` 接口扩展 `ApprovalStore`；文件参考实现；生产可插拔 |

## 详细设计

### 1. DurableApprovalStore Java 接口

定义 `DurableApprovalStore` 扩展 `ApprovalStore`，保留四方法契约（`save` / `find` / `claimForExecution` / `markExecuted`），新增 durable 恢复 + lease 管理语义。

```java
package com.sapnexus.gateway.approval;

import java.time.Instant;
import java.util.List;

/**
 * Lease operation outcome (three states, inspired by item-1 TypeScript LeaseOutcome).
 */
public sealed interface LeaseOutcome {
    /** Normal claim succeeded. */
    record Claimed() implements LeaseOutcome {}
    /** Lease not expired and held by a different worker (fail-closed). */
    record Rejected(String holder, Instant expiresAt) implements LeaseOutcome {}
    /** Lease expired, forcibly taken over (previousHolder recorded for audit). */
    record ForceClaimed(String previousHolder) implements LeaseOutcome {}
}
```

```java
package com.sapnexus.gateway.approval;

import java.util.List;

/**
 * Durable extension of {@link ApprovalStore}.
 *
 * <p>Preserves the four-method contract (save / find / claimForExecution / markExecuted)
 * and adds durable recovery + lease management semantics. The four inherited methods
 * are implemented with durable persistence + lease integration:
 * <ul>
 *   <li>{@link #claimForExecution} atomically transitions approved -> executing
 *       and binds a lease (default workerId = worker-${PID}, TTL 60s).</li>
 *   <li>{@link #markExecuted} atomically transitions executing -> executed
 *       and releases the lease.</li>
 * </ul>
 */
public interface DurableApprovalStore extends ApprovalStore {

    // --- durable recovery ---

    /**
     * Recover all approvals from the durable store on restart.
     * Non-terminal states (pending / approved / executing) are recoverable;
     * terminal states (executed / rejected) are loaded for audit queries only.
     */
    List<ApprovalRecord> recoverAll();

    /**
     * Reconcile durable store internal consistency on recovery.
     * Validates lease <-> record status consistency; drift fails closed.
     */
    void reconcile();

    // --- lease management (recovery / force-claim scenarios) ---

    /**
     * Claim lease for an approval (three states: claimed / rejected / force-claimed).
     * Used in recovery scenarios where a worker takes over an expired lease.
     */
    LeaseOutcome claimLease(String approvalId, String workerId, long ttlMs);

    /**
     * Release lease (only if workerId matches the current holder).
     */
    void releaseLease(String approvalId, String workerId);

    /**
     * Renew lease (only if workerId matches the current holder).
     */
    void renewLease(String approvalId, String workerId, long ttlMs);
}
```

**四方法契约的 durable 语义**（实现层，签名不变）：

| 方法 | `InMemoryApprovalStore` | `DurableApprovalStore` |
|---|---|---|
| `save(record)` | `putIfAbsent` | 持久化到 durable store（tmp+rename 原子写） |
| `find(approvalId)` | `ConcurrentMap.get` | 从 durable store 读取 |
| `claimForExecution(approvalId)` | `computeIfPresent` 迁移 `approved->executing` | 原子迁移 `approved->executing` + 绑定 lease（workerId=`worker-${PID}`，TTL 60s） |
| `markExecuted(approvalId)` | `compute` 迁移 `executing->executed` | 原子迁移 `executing->executed` + 释放 lease |

**`CapabilityController` 消费方式不变**：`approvalStore` 注入点（`CapabilityController:46`）从 `InMemoryApprovalStore` 切换到 `DurableApprovalStore`，调用代码（`find` -> `check` -> `claimForExecution` -> `dispatch` -> `markExecuted`）无需改动。

### 2. 本地参考实现（文件）

借鉴项1 `jsonl-run-store.ts` 的 tmp+rename 原子写 + lease 文件管理模式，Java 侧独立实现。

**文件布局**（`${SAP_NEXUS_GATEWAY_DATA_DIR:-.gateway-data}/durable/`）：

| 路径 | 内容 | 写策略 |
|---|---|---|
| `approvals/<approvalId>.json` | `ApprovalRecord` 全量 JSON（Jackson + JavaTimeModule，`Instant` 序列化为 ISO 字符串） | tmp + rename 原子覆写 |
| `leases/<approvalId>.json` | `{ "workerId": "...", "expiresAt": "..." }` | tmp + rename 原子覆写 |

**原子性保证**：

状态迁移（`claimForExecution` / `markExecuted`）需要读-改-写的原子性。文件实现用 `FileChannel.lock()` 文件锁保护：

1. 获取 `approvals/<approvalId>.json` 的独占文件锁（`FileChannel.tryLock()`）
2. 读 `ApprovalRecord` JSON
3. 检查 status + 迁移状态
4. 写 `approvals/<approvalId>.json`（tmp + `Files.move(REPLACE_EXISTING, ATOMIC_MOVE)`）
5. 写/删 `leases/<approvalId>.json`（tmp + rename / `Files.deleteIfExists`）
6. 释放文件锁

**`save(record)`**：
- 直接写 `approvals/<approvalId>.json`（tmp + rename）
- `putIfAbsent` 语义：如果文件已存在，返回 `false`（重复 approvalId 拒绝）

**`find(approvalId)`**：
- 读 `approvals/<approvalId>.json`，反序列化为 `ApprovalRecord`
- 文件不存在 -> `Optional.empty()`

**`claimForExecution(approvalId)`**：
1. 文件锁
2. 读 record
3. `status != "approved"` -> 返回 `Optional.empty()`（幂等拒绝）
4. 迁移 `approved -> executing`，写 record（tmp + rename）
5. 写 lease（`worker-${PID}`, `Instant.now().plusMillis(60_000)`，tmp + rename）
6. 释放锁
7. 返回 `Optional.of(executingRecord)`

**`markExecuted(approvalId)`**：
1. 文件锁
2. 读 record
3. `status != "executing"` -> no-op（幂等）
4. 迁移 `executing -> executed`，写 record（tmp + rename）
5. 删除 lease 文件（`Files.deleteIfExists`）
6. 释放锁

**`claimLease(approvalId, workerId, ttlMs)`**（恢复场景）：
1. 读 lease 文件
2. lease 未过期且 `workerId != holder` -> `Rejected(holder, expiresAt)`
3. lease 过期且 `workerId != holder` -> 写新 lease -> `ForceClaimed(previousHolder)`
4. 无 lease 或 `workerId == holder` -> 写新 lease -> `Claimed()`

**`releaseLease(approvalId, workerId)`**：
- 读 lease，`workerId == holder` -> 删除 lease 文件

**`renewLease(approvalId, workerId, ttlMs)`**：
- 读 lease，`workerId == holder` -> 重写 lease（tmp + rename）

**`recoverAll()`**：
- 扫描 `approvals/` 目录，逐文件反序列化 `ApprovalRecord`
- 返回全部 record（调用方按 status 过滤）

**`reconcile()`**：
- 扫描 `approvals/` + `leases/`
- 校验一致性（见 §5）

**序列化**：`ApprovalRecord` 是 Java record，用 Jackson + `jackson-datatype-jsr310`（JavaTimeModule）序列化为 JSON。`Instant` 序列化为 ISO 字符串（`2026-08-02T10:30:00Z`），反序列化还原。`Map<String, String> parameters` 直接 JSON 序列化。

**生产可插拔**：接口先行，生产实现可换 SQLite（事务原子性）或 Postgres（行锁 + 事务）。SQLite 表结构示例：

```sql
CREATE TABLE approvals (
    approval_id  TEXT PRIMARY KEY,
    record_json  TEXT NOT NULL,
    status       TEXT NOT NULL
);
CREATE TABLE leases (
    approval_id  TEXT PRIMARY KEY REFERENCES approvals(approval_id),
    worker_id    TEXT NOT NULL,
    expires_at   TEXT NOT NULL
);
```

SQLite 实现用 `BEGIN TRANSACTION` ... `COMMIT` 替代文件锁，原子性由数据库事务保证。

### 3. TTL 基准（approvedAt 固定）

**决策**：`approvedAt` 是固定基准，重启恢复后 TTL 用墙钟 `isExpired(now)` 直接计算，不重置。

**依据**：

- `CapabilityController.isValidApprovedRecord`（行 128-133）在 approve 时硬校验 `ttlSeconds <= 600`，即 approval 的安全窗口在 approve 时就确定了（`approvedAt + ttlSeconds = expiresAt`）。
- `expiresAt` 持久化到 durable store 后不可变。恢复后 `ApprovalRecord.isExpired(Instant.now())` 直接用持久化的 `expiresAt` 做墙钟校验（`now.isAfter(expiresAt)`）。
- 重置 `approvedAt` 会重新计算 `expiresAt = newApprovedAt + ttlSeconds`，导致安全窗口被延长超过 600s，违反 P0B 防重放要求。

**执行路径校验**：

`ApprovalGuard.check`（`ApprovalGuard.java:26`）在 execute 时校验 `record.isExpired(now)`。durable store 替换后，`find(approvalId)` 返回的 `ApprovalRecord` 携带持久化的 `expiresAt`，`ApprovalGuard` 的 TTL 校验逻辑不变。

**过期 approval 处置**：
- `claimForExecution` 拒绝过期 approval（`ApprovalGuard.check` 在 claim 之前已拒绝，返回 `APPROVAL_EXPIRED`）。
- 过期 approval 保持恢复态（`approved` / `executing`），供审计查询，不可再 execute。

### 4. claim/lease per-approval

**claim 粒度**：per-approval，对齐 `ApprovalStore.claimForExecution(approvalId)` 现有契约。

**lease 模型**：

| 操作 | 触发方 | 行为 |
|---|---|---|
| 绑定 lease | `claimForExecution` | 原子迁移 `approved -> executing` + 写 lease（`worker-${PID}`, TTL 60s） |
| 释放 lease | `markExecuted` | 原子迁移 `executing -> executed` + 删 lease |
| force-claim | `claimLease`（恢复场景） | lease 过期后，其他 worker 强制接管（`ForceClaimed`） |

**lease TTL**：60s。理由：
- Gateway execute 一个 WRITE capability 通常在几秒内完成（SAP RFC 调用）。
- 60s 足够覆盖正常执行时间 + 网络延迟（对齐项1 `defaultTtlMs: 60_000`）。
- execute 超过 60s（异常情况）时 lease 过期，其他 worker 可 force-claim。

**LeaseOutcome 三态**（借鉴项1 `frontend/src/runtime/durable/types.ts:55-58`）：

| 状态 | 条件 | 审计 |
|---|---|---|
| `Claimed` | 无 lease 或 `workerId == holder` | 无特殊审计 |
| `Rejected` | lease 未过期且 `workerId != holder` | 记录 holder + expiresAt（fail-closed） |
| `ForceClaimed` | lease 过期且 `workerId != holder` | 记录 previousHolder（强制接管审计） |

**正常执行路径**（`CapabilityController.execute()`）：
1. `find(approvalId)` -> `ApprovalGuard.check(...)` -> 校验 4 种拒绝场景
2. `claimForExecution(approvalId)` -> 原子迁移 `approved -> executing` + 绑定 lease
3. claim 返回空 -> `APPROVAL_DUPLICATE`（幂等拒绝重复执行）
4. `dispatcher.dispatch(...)` -> SAP RFC 调用
5. `markExecuted(approvalId)`（finally 块，行 246-248）-> 原子迁移 `executing -> executed` + 释放 lease

**`claimForExecution` 幂等**：已 `executing` / `executed` 的 approval 重复 claim 返回 `Optional.empty()`，`CapabilityController` 返回 `APPROVAL_DUPLICATE`。这与 `InMemoryApprovalStore:34` 的 `!"approved".equals(existing.status())` 逻辑一致。

**恢复场景的 force-claim**：
- worker 崩溃后，`executing` 状态的 approval 的 lease 仍在但已过期。
- 恢复时 `claimLease(approvalId, newWorkerId, 60_000)` 返回 `ForceClaimed(previousHolder)`。
- force-claim 后可重新执行或标记需人工介入（取决于崩溃点语义）。

### 5. 跨重启恢复

**权威源**：durable store 是 Gateway 侧权威操作索引。JSONL trace（agent 侧写的 `approval.jsonl`）是审计源，不在 Gateway 恢复路径中跨服务读取（避免跨服务文件依赖）。

**恢复流程**：

1. **进程启动**：`DurableApprovalStore` 初始化，调用 `recoverAll()` 扫描 `approvals/` 目录，加载全部 `ApprovalRecord`。
2. **一致性校验**：调用 `reconcile()` 校验 durable store 内部一致性。
3. **按状态恢复**：

| 恢复状态 | 处置 |
|---|---|
| `pending` | 可继续 approve（`save` 已完成，等待 approve 端点调用） |
| `approved` | 可继续 claim / execute（lease 不存在，正常路径可用） |
| `executing` | 检查 lease：未过期 -> 等待原 worker 恢复或 lease 过期；已过期 -> `claimLease` force-claim，可重新执行或标记需人工介入 |
| `executed` | 终态，仅审计查询 |
| `rejected` | 终态，仅审计查询 |

**`reconcile()` 内部一致性校验规则**：

| 检测到 | 判定 | 动作 |
|---|---|---|
| `executing` record + 无 lease | 漂移（崩溃时 lease 未清理或丢失） | fail-closed：标记需人工介入，不允许自动 claim |
| `approved` / `pending` record + 有 lease | 漂移（状态迁移与 lease 操作不一致） | fail-closed：清理残留 lease，记录审计 |
| `executed` / `rejected` record + 有 lease | 残留（`markExecuted` 未清理 lease） | 清理残留 lease，记录审计 |
| lease 文件无对应 approval 文件 | 孤儿 lease | 删除孤儿 lease，记录审计 |

**不跨服务读 agent JSONL**：
- durable store 自身持久化了 `ApprovalRecord` 的全部字段（包括 `approvalId` / `capabilityId` / `parameterSnapshotHash` / `parameters` / `approver` / `approvedAt` / `expiresAt` / `status`），恢复时无需从 agent JSONL 补数据。
- JSONL trace 保留为审计源，人工审计时可跨源对照，但 Gateway 自动恢复路径不依赖它。

### 6. InMemoryApprovalStore 处置

**决策**：保留为测试桩，不删除。

**配置**：

| Bean | 注解 | 角色 |
|---|---|---|
| `DurableApprovalStore` | `@Component` + `@Primary` | 生产默认实现 |
| `InMemoryApprovalStore` | `@Component`（保留现有，不加 `@Primary`） | 测试桩 |

**Spring 注入行为**：
- `CapabilityController` 注入 `ApprovalStore`（`CapabilityController:46`），Spring 优先选择 `@Primary` 的 `DurableApprovalStore`。
- 测试时通过 `@Qualifier("inMemoryApprovalStore")` 或 `@TestConfiguration` + `@Bean` 覆盖，注入 `InMemoryApprovalStore`（零 I/O，快速测试）。

**`InMemoryApprovalStore` 代码不改**：保留现有 `ConcurrentMap` 实现 + `@Component` 注解，仅在生产配置中由 `@Primary` 覆盖。

## 替换点

| 当前 | 替换为 |
|---|---|
| `InMemoryApprovalStore`（`@Component`，`ConcurrentMap`） | `DurableApprovalStore`（`@Primary` + `@Component`，文件/SQLite） |
| `ConcurrentMap.compute` 进程内原子 | 文件锁 + tmp+rename 跨重启原子（或 SQLite 事务） |
| 进程重启丢失 approval index | durable store 持久化，`recoverAll()` 恢复 |
| 无 lease（单进程内 `compute` 原子） | per-approval lease（TTL 60s + `LeaseOutcome` 三态） |
| `ApprovalStore` 注入 `InMemoryApprovalStore` | `ApprovalStore` 注入 `DurableApprovalStore`（`@Primary`） |
| `claimForExecution`：`computeIfPresent` 迁移 | `claimForExecution`：文件锁 + tmp+rename 迁移 + 绑定 lease |
| `markExecuted`：`compute` 迁移 | `markExecuted`：文件锁 + tmp+rename 迁移 + 删除 lease |

**不改的部分**：
- `ApprovalStore` 接口（4 方法签名不变）
- `ApprovalRecord` record（字段不变）
- `ApprovalGuard`（4 种拒绝场景不变）
- `CapabilityController` 执行流程（`find` -> `check` -> `claimForExecution` -> `dispatch` -> `markExecuted` 不变）
- JSONL trace 语义（审计源不变）

## Risks / Trade-offs

- [文件锁性能] -> `FileChannel.lock()` 有系统调用开销；approval 操作非高频（人工审批后执行），可接受。生产可换 SQLite/Postgres。
- [文件实现 multi-worker] -> 本 change 单 worker durable；multi-worker 留生产实现（文件锁已提供跨进程原子性，但 lease TTL 60s 的 multi-worker 竞态需生产级测试）。
- [lease TTL 误判] -> TTL 60s 执行级；长 SAP RFC 调用可能超 60s。execute 超时后 lease 过期，其他 worker 可 force-claim。force-claim 审计记录 previousHolder，人工可追溯。
- [durable store 磁盘 I/O] -> 每次 `claimForExecution` / `markExecuted` 有文件锁 + tmp+rename 开销；可接受（approval 操作非高频）。生产可调 fsync 策略或换 SQLite。
- [序列化兼容性] -> `ApprovalRecord` 用 Jackson 序列化；字段增减需向前兼容。项2 增强 `approver` 字段时，Jackson 默认兼容（未知字段忽略，新增字段需 `@JsonCreator` 适配）。
- [恢复时 executing 状态的 force-claim 安全性] -> force-claim 允许重新执行，但 `claimForExecution` 幂等保证不会双重执行（已 `executed` 的 approval 重复 claim 返回空）。

## 安全契约

- **WRITE capabilities MUST NOT execute until Human Approval confirmed**：强化为 durable + cross-restart + cross-worker anti-replay。`ApprovalGuard` 的 4 种拒绝场景（presence / TTL / snapshot-hash / duplicate-submit）在 durable store 替换后不变。
- **`claimForExecution` 幂等拒绝重复执行**：已 `executing` / `executed` 的 approval 重复 claim 返回 `Optional.empty()`，`CapabilityController` 返回 `APPROVAL_DUPLICATE`。
- **过期 approval 不可 execute**：`ApprovalGuard.check` 校验 `isExpired(now)`，过期 approval 返回 `APPROVAL_EXPIRED`。`expiresAt` 持久化后不可变（`approvedAt` 固定基准）。
- **`ApprovalRecord` 不存 SAP credentials**：record 仅含 `parameterSnapshotHash` + `parameters`（业务参数）+ `approver` + 时间戳 + 状态。SAP credentials 不出现在 record 中（`ApprovalRecord.java` 注释已声明）。
- **force-claim 审计**：`LeaseOutcome.ForceClaimed` 记录 `previousHolder`，强制接管可追溯。

## 越界

本 change **不触**以下范围：

- **SSE / incremental cursor**（拆分项 4）：approval store 替换不涉及 SSE 推送或 cursor 重连。
- **trusted principal 模型本身**（拆分项 2）：`approver` 字段当前是 String，durable store 只持久化不关心语义。项2 增强 principal schema 时向后兼容。
- **Gateway WRITE 执行语义**：`CapabilityController.execute()` 的执行流程（`find` -> `check` -> `claim` -> `dispatch` -> `markExecuted`）不变，`TechnicalExecutionDispatcher` 不变。
- **ApprovalGuard 4 种拒绝场景**：presence / TTL / snapshot-hash / duplicate-submit 的校验逻辑不变，`ApprovalGuard` 代码不改。

## 与 spec 的映射

| Spec Requirement（`durable-approval-store`） | Design 章节 |
|---|---|
| Durable approval persistence | §1 接口 + §2 本地参考实现 + §替换点 |
| Cross-worker anti-replay | §4 claim/lease per-approval |
| JSONL audit retained as authoritative | §5 跨重启恢复（durable store 内部一致性校验，JSONL 为审计源） |
| Approval TTL re-validation across restart | §3 TTL 基准（approvedAt 固定，isExpired 墙钟校验） |

## Implementation Divergence（verify 阶段记录）

> 本节由 verify 阶段 Check 6（delta spec vs design doc 一致性校验）追加，记录 delta spec 文本与 design doc 决策的两处偏差。实现均以 design doc 为准（正确），delta spec 文本为早期草案遗留，未同步 D4 修正与 ApprovalGuard 分层决策。用户于 verify 阶段选择 Option A（偏差记录）处理。

### 偏差 1：JSONL 恢复对账

- **delta spec**（`specs/durable-approval-store/spec.md` "JSONL audit retained as authoritative" Requirement）：「On recovery, the durable store SHALL be reconciled against the JSONL audit; drift SHALL fail closed.」
- **design doc D4（修正）**：「durable store 为权威操作索引，JSONL trace 为审计源 | 不跨服务读 agent JSONL；恢复以 durable store 内部一致性校验为准，漂移 fail-closed」
- **实现**：`FileDurableApprovalStore.reconcile()`（Task 6）仅校验 durable store 内部一致性（lease <-> record status + orphan/residual lease 清理），**不读 agent JSONL**（D4）。漂移 fail-closed（executing+无 lease 不自动恢复）。
- **结论**：以 D4 为准。delta spec「reconciled against the JSONL audit」文本被 D4 取代。

### 偏差 2：TTL 拒绝层归属

- **delta spec**（"Approval TTL re-validation across restart" Requirement + "Expired approval rejected after restart" Scenario）：「`claimForExecution` SHALL reject an approval whose `expiresAt` is in the past」/「THEN `claimForExecution` rejects the expired approval (returns empty)」
- **design doc**：`ApprovalGuard.check`（do-not-modify）执行 4 不变量（presence / TTL / snapshot-hash / duplicate-submit），执行流程 `find` -> `guard.check` -> `claimForExecution` -> `dispatch` -> `markExecuted`。TTL 由 `ApprovalGuard.check` 校验 `isExpired(now)`，过期返回 `APPROVAL_EXPIRED`，**先于** `claimForExecution`。
- **实现**：store 的 `claimForExecution`（Task 3）仅校验 `status=="approved"`，不检查 expiry（设计分层：store=持久化原语，Guard=安全不变量）。过期 approval 在 `ApprovalGuard.check` 被拒，不会到达 `claimForExecution`。
- **结论**：以 design doc 分层为准。delta spec 将 TTL 拒绝归于 `claimForExecution` 不精确；系统级「过期 approval 不可 execute」由 `ApprovalGuard` 保证（已实现、do-not-modify）。


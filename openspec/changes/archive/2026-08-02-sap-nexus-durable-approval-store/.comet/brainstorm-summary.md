# Brainstorm Summary: sap-nexus-durable-approval-store

> Phase: design | Status: finalized | Date: 2026-08-02
> Canonical spec: `openspec/changes/sap-nexus-durable-approval-store/specs/`

## 概述

本 change 把 Gateway `InMemoryApprovalStore`（`ConcurrentMap<String, ApprovalRecord>` 进程级索引）替换为 `DurableApprovalStore`，实现 cross-restart approval 恢复 + cross-worker anti-replay。brainstorming 围绕 `design.md` 的 3 个 Open Question 展开，用户已确认全部决策。本文档记录决策过程与理由，作为 Design Doc 的前置输入。

## Open Questions 决策

### OQ-1: TTL 基准时间

**问题**: approval TTL 跨重启语义 -- TTL 基准时间用 `approvedAt` 固定还是恢复时刻重置？

**候选方案**:
- A: `approvedAt` 固定基准。重启恢复后 TTL 用墙钟 `isExpired(now)` 直接计算，不重置。
- B: 恢复时刻重置 `approvedAt`，TTL 从恢复时刻重新计时。

**决策**: A

**理由**:
- 与 `CapabilityController:128` 的 `ttlSeconds <= 600` 硬校验一致：approval 的安全窗口在 approve 时就确定了（`approvedAt + ttlSeconds = expiresAt`），重启不应延长。
- 重置 `approvedAt` 会突破 600s 安全窗口，可能导致已过期的 approval 被重新激活，违反 P0B 条件门禁的防重放要求。
- `ApprovalRecord.isExpired(Instant)` 已是墙钟校验（`now.isAfter(expiresAt)`），恢复后直接调用即可，无需特殊处理。
- `expiresAt` 在 approve 时由 `approvedAt + ttlSeconds` 计算，持久化后不可变；durable store 只持久化、不重算。

### OQ-2: claim/lease 粒度

**问题**: claim/lease 的粒度是 per-approval 还是 per-run？lease TTL 与续期策略？

**候选方案**:
- A: per-run（对齐项1 `DurableRunStore.claim(runId, workerId, ttlMs)`）
- B: per-approval 但无 lease（纯 idempotency key）
- C: per-approval + lease 三态（借鉴项1 `LeaseOutcome`）

**决策**: C

**理由**:
- claim 粒度是 per-approval，对齐 `ApprovalStore.claimForExecution(approvalId)` 现有契约（`InMemoryApprovalStore:31` 用 `computeIfPresent` 原子迁移 `approved -> executing`）。
- lease TTL 60s，execute 完成即 `markExecuted` 释放（对齐项1 `defaultTtlMs: 60_000`）。
- 借鉴项1 `LeaseOutcome` 三态（`frontend/src/runtime/durable/types.ts:55-58`）：
  - `claimed`: 正常 claim 成功
  - `rejected`: lease 未过期且持有者不同（fail-closed）
  - `force-claimed`: lease 过期，强制接管（记录 previousHolder 审计）
- 纯 idempotency key（B）不覆盖 lease 持有语义：worker 崩溃后 lease 过期需可重新 claim，idempotency key 无法表达"lease 过期后允许接管"。
- per-run（A）粒度不匹配：approval 是 per-capability-invocation 的（`CapabilityController:201` 按 `approvalId` claim），不是 per-agent-run 的。

### OQ-3: store 选型

**问题**: 复用项1（`durable-state-foundation`）的 store 接口还是独立实现？

**候选方案**:
- A: 直接复用项1 store 接口
- B: Java 侧独立定义接口，不参考项1
- C: Java 侧独立定义接口 + 借鉴项1 设计模式

**决策**: B+C

**理由**:
- 项1 store 接口是 TypeScript（`DurableRunStore` / `DurableConversationStore`，`frontend/src/runtime/durable/types.ts:82-104`），Gateway 是 Java，无法直接复用。
- Java 侧定义 `DurableApprovalStore` 接口（扩展 `ApprovalStore`），借鉴项1 lease 三态 / tmp+rename 原子写 / idempotency 模式但独立实现。
- 本地参考实现用文件（JSON + tmp+rename），与项1 `.workbench-data/durable/` 目录约定对齐但独立（Gateway 侧 `.gateway-data/durable/`）。
- 生产可插拔：接口先行，实现可换 SQLite/Postgres（D1 store 无关契约的 Java 等价）。

## D5 跨语言修正

**原 D5 措辞**: "`DurableApprovalStore` 复用项1（`durable-state-foundation`）的 store 无关接口"

**问题**: 项1 store 接口是 TypeScript，Gateway 是 Java，跨语言无法直接复用。原措辞暗示接口级依赖，实际不存在。

**修正后 D5 措辞**: "借鉴项1 store 设计模式（lease 三态、tmp+rename 原子写、idempotency），Java 侧独立实现 `DurableApprovalStore` 接口"

**影响**:
- Design Doc §1 接口定义按 Java 独立实现设计，不引入对项1 TypeScript 代码的编译期或运行期依赖。
- Design Doc §2 本地参考实现借鉴项1 `jsonl-run-store.ts` 的 tmp+rename / lease 文件管理模式，但用 Java `Files.move` + `FileChannel.lock` 独立实现。

## JSONL 对账跨服务澄清

**原 D4 措辞**: "durable store 是 operational index，崩溃恢复以 JSONL 为准校验对账"

**问题**: JSONL trace 是 agent 侧写的 `approval.jsonl`，Gateway 跨服务读 agent 文件会引入跨服务文件依赖，违反服务边界。

**澄清决策**:
- durable store 自身是 Gateway 侧权威操作索引（`save` / `find` / `claimForExecution` / `markExecuted` 均在 Gateway 进程内持久化）。
- JSONL trace（agent 写的 `approval.jsonl`）保留为审计源，不在 Gateway 恢复路径中跨服务读取。
- Gateway 重启恢复以 durable store 为准。
- D4 对账改为 **durable store 内部一致性校验**：恢复时校验 lease 与 record 状态一致性（如 `executing` record 应有 lease、`approved` record 不应有 lease），漂移 fail-closed。

**影响**:
- Design Doc §5 跨重启恢复按 durable store 内部一致性校验设计。
- spec.md Requirement 3 "JSONL audit retained as authoritative" 的语义不变（JSONL 仍是审计源），但 "reconciled against the JSONL audit" 理解为 durable store 内部一致性校验，非跨服务对账。

## 项2 弱依赖说明

**问题**: approval 绑定 approver principal 由项2（trusted principal）提供，本 change 是否依赖项2？

**决策**: 弱依赖，不阻塞。

**理由**:
- `ApprovalRecord.approver` 当前已是 `String` 类型（`ApprovalRecord.java:21`），durable store 只持久化它，不关心语义。
- 项2 增强 principal schema 时向后兼容：`approver` 字段从简单 String 升级为结构化 principal，durable store 的序列化/反序列化只需适配新字段格式，接口契约不变。
- 本 change 不预决 principal schema，不阻塞项2，也不被项2 阻塞。

## 决策汇总

| 编号 | 决策 | 关键点 |
|---|---|---|
| OQ-1 | A: `approvedAt` 固定基准 | 墙钟 `isExpired(now)` 直接计算，保 600s 安全窗口，不重置 |
| OQ-2 | C: per-approval + lease 三态 | `claimForExecution` 原子迁移 `approved->executing` + lease TTL 60s + `LeaseOutcome` 三态 |
| OQ-3 | B+C: Java 独立 + 借鉴项1 | `DurableApprovalStore` 接口（扩展 `ApprovalStore`），文件参考实现，生产可插拔 |
| D5 修正 | 借鉴项1 设计模式，Java 独立 | 不引入 TypeScript 依赖，独立实现 lease/tmp+rename/idempotency |
| D4 修正 | durable store 内部一致性校验 | 不跨服务读 agent JSONL，恢复以 durable store 为准 |
| 项2 | 弱依赖，不阻塞 | `approver` 字段只持久化 String，不关心 principal 语义 |

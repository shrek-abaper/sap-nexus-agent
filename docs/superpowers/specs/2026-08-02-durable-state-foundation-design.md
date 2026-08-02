---
comet_change: sap-nexus-durable-state-foundation
role: technical-design
canonical_spec: openspec
---

# Design: Durable State Foundation (P0B 项1)

> Comet change: `sap-nexus-durable-state-foundation` (phase: design)
> Canonical spec: `openspec/changes/sap-nexus-durable-state-foundation/specs/`
> 本文档把 change `design.md` 的 D1-D5 与 4 个 Open Question 决策展开为可实施的技术设计。

## Context

当前 Workbench backend 用两个 `globalThis` 进程级 Map 承载运行时状态（`frontend/src/runtime/agent-runtime-adapter.ts`）：

- `runs`（:109）：`Map<runId, AgentRunRecord>`，agent run 事件流 + `pendingOutcome` + approval `decision`。
- `sessions`（:112）：`Map<conversationId, SessionState>`，多轮对话 `lastContext` + `lastRunId` + `history`。

进程重启即丢失，multi-worker 不共享。`conversational-context`（row 19A）已把 `ConversationState` 接口对齐技术架构 §4.2.1 三层分层（`ConversationState` advisory / `PlanExecutionState` execution authority / `EvidenceState` evidence authority），为 P0B durable 替换预留。本 change 是 P0B 拆分项 1/4，提供 durable state 基础设施，是项 2/3/4 的前提。

**既有实践**：Gateway 侧 `InMemoryApprovalStore`（Java）注释明确 "JSONL trace remains the authoritative durable store; this in-memory store provides the process-local index... MVP accepts index loss on restart" -- JSONL 已是本项目既有的 durable audit 载体，本 change 复用同一心智模型。

## Goals / Non-Goals

**Goals:**
- durable Run/Thread + Sessions：cross-restart 恢复 + multi-worker 共享（接口层）。
- run ownership/lease：fail-closed 接管保护。
- structured checkpoint reference：恢复时加载原始 `RegistrySnapshot` 和结构化节点状态，不靠 summary / Memory 重建。
- 幂等 continuation：approval / batch continuation 重复请求不重复执行。
- store 无关契约：接口先行，实现可插拔。

**Non-Goals:**
- trusted principal / tenant / role / data scope（拆分项 2）。
- durable ApprovalStore（拆分项 3，Gateway `InMemoryApprovalStore` 替换）。
- incremental SSE cursor / reconnect（拆分项 4）。
- DeerFlow lead agent、自由 Tool execution、WRITE 批量审批语义。
- multi-worker 并发的生产级实现（本 change 单 worker durable；接口为 multi-worker 预留）。

## Decisions

D1-D5 来自 `design.md`（store 无关接口 / ownership-lease / checkpoint reference / 幂等 continuation / 三层状态分层），保持不变。4 个 Open Question 于 2026-08-02 brainstorming 确认：

| Open Question | 决策 | 理由 |
|---|---|---|
| store 选型 | **file-based (JSONL)** | 零新增依赖（符合 D1）；与 Gateway JSONL audit 统一；单 worker durable 充分满足本 change |
| lease 续期 | **活动驱动 + awaiting 释放** | awaiting 人工等待时长不可控，保持 lease 不合理；durable 持久化等待态，continuation 重 claim |
| checkpoint 粒度 | **每事件 append + ref 随状态变更** | JSONL append-only 即 checkpoint；单一数据源，无写放大，无 snapshot 一致性问题 |
| idempotency key | **显式三段式 `${runId}:${type}:${sha256(params)}`** | 符合 spec 服务端派生；可读可调试；type 枚举天然区分不同 continuation |

## 详细设计

### 1. Store-agnostic 接口契约

定义两个抽象接口，参考实现可插拔（生产可换 Postgres/Redis，接口不变）：

```ts
interface DurableRunStore {
  save(runId: string, record: AgentRunRecord): Promise<void>;       // 全量写（初始化/恢复）
  load(runId: string): Promise<AgentRunRecord | null>;
  list(filter?: { state?: AgentRunState }): Promise<AgentRunRecord[]>;
  appendEvent(runId: string, event: AgentRunEvent): Promise<void>;  // 增量 append（checkpoint）
  claim(runId: string, workerId: string, ttlMs: number): Promise<LeaseOutcome>;
  release(runId: string, workerId: string): Promise<void>;
  renew(runId: string, workerId: string, ttlMs: number): Promise<void>;
  markExecuted(key: string, result: WorkbenchOutcome): Promise<void>;
  lookupExecuted(key: string): Promise<WorkbenchOutcome | null>;
}

interface DurableConversationStore {
  save(conversationId: string, state: SessionState): Promise<void>;
  load(conversationId: string): Promise<SessionState | null>;
  clear(conversationId: string): Promise<void>;
}

type LeaseOutcome =
  | { status: "claimed" }
  | { status: "rejected"; holder: string; expiresAt: string }   // fail-closed
  | { status: "force-claimed"; previousHolder: string };        // lease 过期强制接管
```

### 2. File-based JSONL 参考实现（store 选型 A）

文件布局（`<workbenchDataDir>/durable/`，dev 默认 `.workbench-data/durable/`）：

| 路径 | 内容 | 写策略 |
|---|---|---|
| `runs/<runId>.jsonl` | append-only 事件流（每行一个 JSON：`AgentRunEvent` 或元数据记录） | append + fsync |
| `sessions/<conversationId>.json` | `SessionState` 全量 | tmp + rename 原子覆写 |
| `leases/<runId>.json` | `{ workerId, expiresAt }` | tmp + rename |
| `idempotency/<key>.json` | `{ result, executedAt }` | tmp + rename |

**run JSONL 行类型**（discriminated by `kind`）：
- `{ kind: "event", ...AgentRunEvent }` - 事件流。
- `{ kind: "pending_outcome", value: WorkbenchOutcome }` - 最新 pendingOutcome（状态变更时 append，恢复取最新）。
- `{ kind: "decision", value: ApprovalDecision }` - approval decision。
- `{ kind: "checkpoint_ref", registrySnapshotId, nodeState, approvalRecordRef }` - structured checkpoint reference。

**原子写**：
- 事件 append：`fs.appendFileSync` + `fs.fsyncSync`（每事件持久化 = checkpoint，对齐决策 A）。
- 元数据记录：同 append 到 JSONL。
- session/lease/idempotency：tmp file + `fs.renameSync` 原子覆写。

**恢复**：扫描 `runs/` 目录，逐文件重放 JSONL 重建 `AgentRunRecord`（按行序还原 events 数组，取最新 pendingOutcome/decision/checkpoint_ref）。

### 3. Run ownership / lease（lease 决策 A）

lease 模型：**活动驱动 + awaiting 释放**。

- run 在 worker 主动执行状态（`running` / `validating` / `executing` 等）时持有 lease；每次 `appendEvent` 触发 `renew`（活动驱动续期，TTL ~60s）。
- run 进入 `awaiting_approval` / `awaiting_batch_confirm` 时 `release` lease（durable store 已持久化等待态，run 仍可恢复，无需持有 lease）。
- continuation 入口（`decideAgentRunApproval` / `confirmAgentRunBatch`）先 `claim` lease 再执行。
- lease 未过期时其他 worker `claim` -> `status: "rejected"`（fail-closed）+ 记录拒绝审计。
- lease 过期后 `claim` -> `status: "force-claimed"`（记录 previousHolder 审计）。
- **单 worker 重启恢复**：扫描发现 `running` 等执行中状态的 run（lease 过期或 workerId 不匹配）-> 重新 claim + 加载 structured reference -> 继续/标记需人工介入。

### 4. Structured checkpoint reference（checkpoint 决策 A）

checkpoint = JSONL 事件流本身（每事件 append + fsync 即持久化）。structured reference 作为元数据记录（`kind: "checkpoint_ref"`）在状态变更时 append：

- run 创建：append 初始 `checkpoint_ref`（绑定 `RegistrySnapshotId` = PlanExecutionState 初始 snapshot）。
- 节点状态变更（如 `approval_state_changed`）：append 更新后的 `nodeState`。
- approval decision：append `approvalRecordRef`。

**恢复**：重放 JSONL 取最新 `checkpoint_ref`（RegistrySnapshotId + 节点状态 + ApprovalRecord 引用），加载原始 RegistrySnapshot，**不靠 summary / Memory 重建**（对齐 D3 + §4.2.1）。snapshot 漂移 fail-closed（复用 S1 validator）。

`ConversationState` 压缩失败：保留原 checkpoint 或关闭压缩，不破坏 run（D5）。

### 5. Idempotent continuation（idempotency 决策 A）

key schema：`${runId}:${continuationType}:${sha256(canonicalJson(params))}`

- `continuationType` 枚举：`approval_approve` / `approval_reject` / `batch_confirm`。
- `params`：approval -> `{ decision, approvalRecordId }`；batch -> `{ combinations }`。
- canonicalJson：稳定键序 + 无空格，保证相同参数同 hash。

**流程**（`decideAgentRunApproval` / `confirmAgentRunBatch` 入口）：
1. 计算 idempotency key。
2. `lookupExecuted(key)`：命中 -> 返回已记录 result，不重复执行。
3. 未命中 -> `claim` lease -> 执行 continuation -> `markExecuted(key, result)` -> `release` lease（若进入 awaiting）或保持（若 completed）。

不同 `continuationType` -> 不同 key（满足 spec "different continuation types are not idempotent to each other"）。

### 6. 三层状态分层持久化（D5）

按 §4.2.1 三层分层持久化：

| 层 | 性质 | 存储载体 | 可压缩 |
|---|---|---|---|
| `ConversationState` | advisory | `sessions/<conversationId>.json` | ✅ |
| `PlanExecutionState` | authority | run JSONL 的 `checkpoint_ref` 记录 | ❌ |
| `EvidenceState` | authority | run JSONL 的事件流（`reasoning_fact_created` 等） | ❌ |

仅 `ConversationState` 可压缩；`PlanExecutionState` / `EvidenceState` 不可压缩。

## 替换点

`agent-runtime-adapter.ts` 的进程内 Map 替换为 durable store：

| 当前 | 替换为 |
|---|---|
| `runs` Map（:109） | `DurableRunStore`（JSONL 实现） |
| `sessions` Map（:112） | `DurableConversationStore`（JSON 实现） |
| `runs.set/get` | `store.save/load/appendEvent` |
| `sessions.set/get` | `store.save/load` |
| `resetAgentRunsForTests` / `resetAgentSessionsForTests` | `store.clear()`（测试钩子，保留） |
| `decideAgentRunApproval` / `confirmAgentRunBatch` | 加 idempotency `lookupExecuted`/`markExecuted` + lease `claim`/`release` |
| `createAgentRun` Q2 门禁（`runs.get(lastRunId)` 查 pending approval） | `store.load(lastRunId)` |

`AgentRunRecord` / `SessionState` / `AgentRunEvent` / `WorkbenchOutcome` 已是可序列化 JSON 结构（见 `run-event-schema.ts` + adapter 类型定义），durable store 直接 `JSON.stringify`，无需额外序列化层。

## 恢复流程

1. **进程启动**：`DurableRunStore` 扫描 `runs/`，逐文件重放 JSONL 重建 `AgentRunRecord`；`DurableConversationStore` 按需加载 `sessions/`。
2. **每个 run**：
   - `awaiting_approval` / `awaiting_batch_confirm`：无 lease，durable 已持久化等待态，等待 continuation。
   - `running` 等执行中状态：lease 过期 -> 重新 claim + 加载 structured reference -> 继续（或标记需人工介入，取决于崩溃点语义）。
   - `completed` / `failed` / `rejected`：终态，无需恢复，仅保留历史。
3. **sessions**：按 `conversationId` 直接加载 `sessions/<conversationId>.json`。

## 并发模型

- **本 change**：单 worker。lease 机制为 multi-worker 预留接口 + 单 worker 崩溃恢复（重启后重新 claim 过期 lease）。
- **multi-worker 生产实现**（后续 change / 生产实现）：file-based 用文件锁（`flock`）或换 Postgres 实现（接口不变，D1 可插拔）。

## Risks / Trade-offs

- [JSONL 全量重放] -> 单 run 事件量有限（几十-几百事件），重放足够快；超大 run 可后续加周期 snapshot（YAGNI，本 change 不做）。
- [file-based multi-worker] -> 本 change 单 worker；multi-worker 留生产实现（文件锁/Postgres），接口已预留。
- [lease TTL 误判] -> TTL ~60s 执行级；长操作靠活动驱动续期（每事件 renew）。
- [checkpoint 一致性] -> checkpoint 与 RegistrySnapshot 绑定；snapshot 漂移 fail-closed（复用 S1 validator）。
- [durable 引入磁盘 I/O] -> 每事件 fsync 有性能开销；可接受（Workbench 非高频）；生产可调 fsync 策略（如批量 fsync）。
- [canonicalJson 稳定性] -> idempotency paramHash 依赖稳定序列化；用固定键序 + 无空格，避免 `JSON.stringify` 平台差异。

## 与 spec 的映射

| Spec Requirement（durable-run-state / conversational-context） | Design 章节 |
|---|---|
| Durable agent run state | §2 JSONL 实现 + §替换点 |
| Run ownership and lease | §3 lease 模型 |
| Structured checkpoint reference | §4 checkpoint |
| Idempotent continuation | §5 idempotency key |
| Store-agnostic durable interface | §1 接口契约 |
| Three-layer state stratification | §6 三层分层 |
| (conversational-context) Conversation session state durable + Process restart preserves sessions | §2 sessions + §恢复流程 |

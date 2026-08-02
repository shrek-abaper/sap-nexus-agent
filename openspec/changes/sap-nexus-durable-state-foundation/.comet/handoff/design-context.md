# Comet Design Handoff

- Change: sap-nexus-durable-state-foundation
- Phase: design
- Mode: compact
- Context hash: 4116f7b44f9cb5f5b4cfd7e8463c51feca2261267a4d42efb75504202a4078a3

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/sap-nexus-durable-state-foundation/proposal.md

- Source: openspec/changes/sap-nexus-durable-state-foundation/proposal.md
- Lines: 1-31
- SHA256: 83691b761b9b7e80656ed0efbf87ec2cc2f2a2c794fe86dc939a13480f46ccc9

```md
## Why

当前 Workbench backend 的 agent run state（`runs Map`）和会话上下文（`sessions Map`）都是 `globalThis` 进程级 Map（`frontend/src/runtime/agent-runtime-adapter.ts:109/112`），进程重启即丢失，multi-worker 不共享。这阻塞了 P0B 条件门禁：共享 S3、长审批、multi-worker/HA、非 sandbox WRITE 都要求 durable Run/Approval + ownership/lease + checkpoint + 幂等 continuation。`conversational-context`（row 19A）已把 `ConversationState` 接口对齐技术架构 §4.2.1 三层分层为 P0B 预留，本 change 把进程内 Map 替换为 durable store，是 P0B 拆分项 1/4（核心基础设施）。

## What Changes

- 把 `runs Map`（`globalThis.__SAP_NEXUS_AGENT_RUNS__`）替换为 durable Run/Thread store，支持 cross-restart 恢复（pending / awaiting_approval / awaiting_batch_confirm 的 run 重启后可继续）。
- 把 `sessions Map`（`globalThis.__SAP_NEXUS_AGENT_SESSIONS__`）替换为 durable ConversationState store，多轮对话 context（lastContext + history）跨重启不丢。
- 建立 run ownership/lease：run 被一个 worker 持有，lease 未释放时其他 worker 不能接管（fail-closed）。
- structured checkpoint reference：run 的 `PlanExecutionState` / `EvidenceState` checkpoint 可持久化引用；恢复时加载原始 `RegistrySnapshot` 和结构化节点状态，不依靠 summary 或 Memory 重建（对齐 §4.2.1）。
- 幂等 continuation：approval / batch continuation 重复请求不重复执行（idempotency key）。
- store 无关契约：先定义 durable Run / Thread / Sessions 的 store 无关接口；store 选型（SQLite / PostgreSQL / Redis 等）在 design 阶段决定，不在 open 阶段预决。

## Capabilities

### New Capabilities

- `durable-run-state`: durable agent Run/Thread 持久化、cross-restart 恢复、run ownership/lease、structured checkpoint reference、幂等 continuation。

### Modified Capabilities

- `conversational-context`: `ConversationState` 存储语义从 process-local Map（不跨重启）变更为 durable store（跨重启恢复）；接口已对齐 §4.2.1 三层分层，本 change 替换其底层存储实现。spec 级变更：v1 "MUST NOT persist across process restarts" 约束解除，改为 durable 持久化契约。

## Impact

- `frontend/src/runtime/agent-runtime-adapter.ts`：`runs` / `sessions` Map 替换为 durable store 接口；`AgentRunRecord` / `SessionState` 持久化序列化。
- 新增 durable store 模块（store 无关接口 + design 阶段选型实现）。
- agent run lifecycle：cross-restart 恢复、ownership/lease、checkpoint replay、幂等 continuation。
- 不触 Gateway approval（拆分项 3）、不触 SSE（拆分项 4）、不触 trusted principal/tenant（拆分项 2）。
- 依赖：`conversational-context`（row 19A）已预留接口；技术架构 §4.2.1 三层状态分层。
- 非目标：store 选型预决（design 阶段）、principal/tenant/role/data scope（项 2）、durable ApprovalStore（项 3）、incremental SSE cursor/reconnect（项 4）、DeerFlow lead agent、自由 Tool execution。

```

## openspec/changes/sap-nexus-durable-state-foundation/design.md

- Source: openspec/changes/sap-nexus-durable-state-foundation/design.md
- Lines: 1-48
- SHA256: 6216fd43a980aa24f0eed03066f67760b489385c079ea093fd953b4fa4a052ce

```md
## Context

当前 Workbench backend 用两个 `globalThis` 进程级 Map 承载运行时状态：

- `runs`（`frontend/src/runtime/agent-runtime-adapter.ts:109`）：agent run 事件流 + `pendingOutcome` + approval decision。
- `sessions`（`agent-runtime-adapter.ts:112`）：多轮对话 `lastContext` + `history`。

进程重启即丢失，multi-worker 不共享。`conversational-context`（row 19A）已把 `ConversationState` 接口对齐技术架构 §4.2.1 三层分层（`ConversationState` advisory / `PlanExecutionState` execution authority / `EvidenceState` evidence authority），为 P0B durable 替换预留。本 change 是 P0B 拆分项 1/4，提供 durable state 基础设施，是项 2/3/4 的前提。

## Goals / Non-Goals

**Goals:**

- durable Run/Thread + Sessions：cross-restart 恢复 + multi-worker 共享。
- run ownership/lease：fail-closed 接管保护。
- structured checkpoint reference：恢复时加载原始 `RegistrySnapshot` 和结构化节点状态，不靠 summary / Memory 重建。
- 幂等 continuation：approval / batch continuation 重复请求不重复执行。
- store 无关契约：接口先行，实现可插拔。

**Non-Goals:**

- store 选型预决（SQLite / PostgreSQL / Redis 在 comet-design 阶段决定）。
- trusted principal / tenant / role / data scope（拆分项 2）。
- durable ApprovalStore（拆分项 3，Gateway `InMemoryApprovalStore` 替换）。
- incremental SSE cursor / reconnect（拆分项 4）。
- DeerFlow lead agent、自由 Tool execution、WRITE 批量审批语义。

## Decisions

- **D1 store 无关接口**：定义 `DurableRunStore` / `DurableConversationStore` 抽象接口（save / load / list / lease / claim），实现可插拔；本 change 提供一个本地参考实现（comet-design 选型），生产实现可替换。理由：解耦契约与选型，避免 open 阶段预决。
- **D2 ownership/lease**：run 绑定 `workerId` + lease（TTL + 续期）；lease 未释放时其他 worker 接管 fail-closed；lease 过期后允许带审计的强制接管。对齐 §4.2.1 "run ownership / lease"。
- **D3 checkpoint reference**：checkpoint 持久化结构化引用（`RegistrySnapshotId` + 节点状态 + 已批准 `ApprovalRecord` 引用），不持久化 summary；恢复时加载原始 snapshot + 节点状态。对齐 §4.2.1 "恢复计划时必须加载原始 RegistrySnapshot 和结构化节点状态，不能依靠 summary 或 Memory 重建"。
- **D4 幂等 continuation**：continuation 请求带 idempotency key（`runId` + continuation type + 参数 hash）；重复 key 返回已记录结果，不重复执行。
- **D5 三层状态分层**：durable store 按 §4.2.1 三层分层持久化：`ConversationState`（advisory，可压缩）、`PlanExecutionState`（authority，不可压缩）、`EvidenceState`（authority，不可压缩）。压缩失败只保留原 checkpoint 或关闭压缩，不破坏 run。

## Risks / Trade-offs

- [store 选型延迟] -> comet-design 阶段必须先选型再 build；open 阶段仅定契约，build 不开始。
- [multi-worker 并发复杂] -> ownership/lease + fail-closed 接管；先单 worker durable，再验证 multi-worker。
- [checkpoint 一致性] -> checkpoint 与 `RegistrySnapshot` 绑定；snapshot 漂移 fail-closed（复用 S1 validator）。
- [durable 引入运维依赖] -> 本地参考实现零依赖（如 SQLite / file），生产实现可替换。

## Open Questions

- store 选型（comet-design 阶段决定）。
- lease 续期策略（主动续期 vs 活动驱动）。
- checkpoint 粒度（每事件 vs 每状态变更）。
- idempotency key schema。

```

## openspec/changes/sap-nexus-durable-state-foundation/tasks.md

- Source: openspec/changes/sap-nexus-durable-state-foundation/tasks.md
- Lines: 1-51
- SHA256: afbb57d1e0ed10b5ac33866bf39ba118b995b17f62e19781cd6c5a2d93f5f984

```md
## 1. Store-agnostic 接口契约

- [ ] 1.1 定义 `DurableRunStore` 接口（save / load / list / lease / claim / markExecuted）
- [ ] 1.2 定义 `DurableConversationStore` 接口（save / load / clear）
- [ ] 1.3 定义 structured checkpoint reference 数据结构（`RegistrySnapshotId` + 节点状态 + `ApprovalRecord` 引用）
- [ ] 1.4 定义 idempotency key schema（`runId` + continuation type + 参数 hash）

## 2. 本地参考实现（store 选型在 comet-design 阶段决定）

- [ ] 2.1 comet-design 阶段选型本地 store（候选：SQLite / file-based）
- [ ] 2.2 实现 `DurableRunStore` 本地参考实现
- [ ] 2.3 实现 `DurableConversationStore` 本地参考实现

## 3. 替换进程内 Map

- [ ] 3.1 替换 `agent-runtime-adapter.ts` 的 `runs Map`（`globalThis.__SAP_NEXUS_AGENT_RUNS__`）为 `DurableRunStore`
- [ ] 3.2 替换 `sessions Map`（`globalThis.__SAP_NEXUS_AGENT_SESSIONS__`）为 `DurableConversationStore`
- [ ] 3.3 `AgentRunRecord` / `SessionState` 序列化与反序列化

## 4. Run ownership / lease

- [ ] 4.1 实现 run ownership lease（`workerId` + TTL + 续期）
- [ ] 4.2 lease 持有期间其他 worker 接管 fail-closed
- [ ] 4.3 lease 过期后带审计的强制接管

## 5. Structured checkpoint + 恢复

- [ ] 5.1 持久化 structured checkpoint reference（绑定 `RegistrySnapshot` + 节点状态）
- [ ] 5.2 恢复时加载原始 `RegistrySnapshot` + 结构化节点状态（不靠 summary / Memory）
- [ ] 5.3 snapshot 漂移 fail-closed（复用 S1 validator）
- [ ] 5.4 `ConversationState` 压缩失败保留原 checkpoint 或关闭压缩

## 6. 幂等 continuation

- [ ] 6.1 approval / batch continuation 请求带 idempotency key
- [ ] 6.2 重复 key 返回已记录结果，不重复执行

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

```

## openspec/changes/sap-nexus-durable-state-foundation/specs/conversational-context/spec.md

- Source: openspec/changes/sap-nexus-durable-state-foundation/specs/conversational-context/spec.md
- Lines: 1-15
- SHA256: b16ae1e06229ec8ba8a4e27bf2fbf2907f8ae03db115e195f814ff687d1ddae0

```md
## MODIFIED Requirements

### Requirement: Conversation session state
The system SHALL maintain a per-conversation `ConversationState` in a durable store, keyed by `conversationId`, holding an optional `PendingClarification`. The state SHALL be advisory context only and MUST NOT influence `PlanExecutionState` or `EvidenceState`. The system SHALL persist this state across process restarts (durable persistence; replaces the v1 process-local `sessions` Map). The underlying storage implementation SHALL be pluggable via the store-agnostic interface defined in `durable-run-state`.

#### Scenario: New conversation starts with no pending clarification
- **WHEN** the frontend generates a new `conversationId` via the "new conversation" button
- **THEN** the backend creates an empty `ConversationState` with `pending_clarification=null`
- **AND** subsequent queries within that conversation are grouped under the same `conversationId`

#### Scenario: Process restart preserves sessions
- **WHEN** the Workbench backend process restarts
- **THEN** all `ConversationState` is recovered from the durable store
- **AND** a follow-up query with an existing `conversationId` resumes with its prior `PendingClarification` / `LastContext` intact
- **AND** multi-worker deployments share the same `ConversationState` view

```

## openspec/changes/sap-nexus-durable-state-foundation/specs/durable-run-state/spec.md

- Source: openspec/changes/sap-nexus-durable-state-foundation/specs/durable-run-state/spec.md
- Lines: 1-68
- SHA256: 9725d3b8effba09557c5291eb7de2bbf6b74c324e7e615361de20a817e41ebf1

```md
## ADDED Requirements

### Requirement: Durable agent run state
The system SHALL persist agent run state (events, `pendingOutcome`, approval decision) in a durable store keyed by `runId`, replacing the process-local `runs` Map (`globalThis.__SAP_NEXUS_AGENT_RUNS__`). The system SHALL recover run state across process restarts and share it across workers.

#### Scenario: Run recovers across process restart
- **WHEN** a run is in `awaiting_approval` or `awaiting_batch_confirm` state and the backend process restarts
- **THEN** the run is recovered from the durable store with its full event stream and `pendingOutcome`
- **AND** the user can continue the run (approve / reject / confirm) after restart

#### Scenario: Multi-worker shares run state
- **WHEN** worker A creates a run and worker B receives a continuation request for the same `runId`
- **THEN** worker B reads the run state from the durable store
- **AND** both workers observe the same run events and `pendingOutcome`

### Requirement: Run ownership and lease
The system SHALL bind each active run to a worker via an ownership lease. A run's lease SHALL prevent other workers from taking over while active. The system SHALL fail-closed when a second worker attempts to operate on a run whose lease is held by another worker.

#### Scenario: Lease prevents concurrent takeover
- **WHEN** worker A holds the lease for run R and worker B attempts to continue run R
- **THEN** the system rejects worker B's operation (fail-closed)
- **AND** records the rejected takeover attempt

#### Scenario: Expired lease allows audited takeover
- **WHEN** worker A's lease for run R has expired (worker A crashed or stopped renewing)
- **AND** worker B attempts to continue run R
- **THEN** worker B may claim the run with an audit record of the forced takeover
- **AND** the lease is rebound to worker B

### Requirement: Structured checkpoint reference
The system SHALL persist a structured checkpoint reference for each run's `PlanExecutionState` and `EvidenceState`, binding to the original `RegistrySnapshot` and structured node state. The system SHALL NOT reconstruct run state from summary or Memory. On recovery, the system SHALL load the original `RegistrySnapshot` and structured node state.

#### Scenario: Recovery loads original snapshot
- **WHEN** a run is recovered after restart
- **THEN** the system loads the original `RegistrySnapshot` referenced by the checkpoint
- **AND** loads the structured node state (not a summary)
- **AND** snapshot drift fails closed (reuses the S1 validator)

#### Scenario: Compaction failure preserves checkpoint
- **WHEN** `ConversationState` compaction fails
- **THEN** the system retains the original checkpoint or disables compaction
- **AND** the run is not corrupted

### Requirement: Idempotent continuation
The system SHALL accept an idempotency key for continuation requests (approval approve / reject, batch confirm). The key SHALL be derived from `runId` + continuation type + parameter hash. A duplicate key SHALL return the already-recorded result without re-executing.

#### Scenario: Duplicate approval continuation is idempotent
- **WHEN** an approve continuation for run R is submitted twice with the same idempotency key
- **THEN** the system executes the approval continuation once
- **AND** the second request returns the already-recorded result without re-executing

#### Scenario: Different continuation types are not idempotent to each other
- **WHEN** run R has both an approval continuation and a batch confirm continuation pending
- **THEN** the two continuations have distinct idempotency keys (different continuation type)
- **AND** both can be executed independently

### Requirement: Store-agnostic durable interface
The system SHALL define a store-agnostic interface (`DurableRunStore`, `DurableConversationStore`) for durable persistence. The interface SHALL support save / load / list / lease / claim operations. The implementation SHALL be pluggable; store selection (SQLite / PostgreSQL / Redis) is decided in the design phase, not in this change's open phase.

#### Scenario: Local reference implementation is pluggable
- **WHEN** the system is configured with the local reference implementation (zero-dependency)
- **THEN** durable state persists locally (e.g., SQLite / file)
- **AND** the implementation can be swapped to a production store without changing the interface contract

#### Scenario: Three-layer state stratification
- **WHEN** the system persists run state
- **THEN** `ConversationState` (advisory, compressible), `PlanExecutionState` (authority, incompressible), and `EvidenceState` (authority, incompressible) are persisted per §4.2.1 three-layer stratification
- **AND** only `ConversationState` may be compacted

```

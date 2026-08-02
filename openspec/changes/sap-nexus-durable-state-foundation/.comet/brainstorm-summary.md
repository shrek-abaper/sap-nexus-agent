# Brainstorm Summary - sap-nexus-durable-state-foundation

> Comet design 阶段 brainstorming 恢复检查点。未确认内容标注为「待确认/候选」。
> 定稿后将作为 Design Doc 的输入。

## 状态
- Phase: design (brainstorming 完成, 待创建 Design Doc)
- 更新: 2026-08-02

## 已探索上下文（代码事实）

### 运行时
- Workbench backend = Next.js 15 (Node.js)；状态承载在 `frontend/src/runtime/agent-runtime-adapter.ts`
- 当前依赖极简：frontend 仅 `next/react/react-dom`；根目录仅 `@fission-ai/openspec`
- **无任何 SQLite / postgres / redis 依赖**
- 注释 `// Next route handlers can load this module in separate bundles; keep runs process-wide.` → 已用 `globalThis` 保证 process-wide

### 待替换的进程内状态
- `runs` Map（`agent-runtime-adapter.ts:109`）：`Map<runId, AgentRunRecord{runId,query,events,pendingOutcome,decision}>`
- `sessions` Map（`agent-runtime-adapter.ts:112`）：`Map<conversationId, SessionState{lastContext,lastRunId,history}>`
- 测试钩子：`resetAgentRunsForTests` / `resetAgentSessionsForTests`
- `createAgentRun` Q2 门禁：同 conversation 有 pending approval 时拒绝新查询（依赖 `runs.get(lastRunId)`）

### 相关既有实践
- Gateway `InMemoryApprovalStore`（Java）注释明确 "JSONL trace remains the authoritative durable store; this in-memory store provides the process-local index... MVP accepts index loss on restart" → **JSONL 已是既有 durable audit 载体**
- `conversational-context`（row 19A）已对齐技术架构 §4.2.1 三层分层，为 P0B 预留接口

## Open Questions（来自 design.md）
1. ~~store 选型~~ — ✅ 已确认 = A. file-based (JSONL)
2. ~~lease 续期策略~~ - ✅ 已确认 = A. 活动驱动 + awaiting 释放
3. ~~checkpoint 粒度~~ - ✅ 已确认 = A. 每事件 append + ref 随状态变更
4. ~~idempotency key schema~~ - ✅ 已确认 = A. 显式三段式 key

## 约束（已确认）
- 本 change 交付：store-agnostic 接口 + 一个本地参考实现；生产实现可插拔（不在本 change）
- design.md Risks：先单 worker durable，再验证 multi-worker
- design.md D1：本地参考实现零依赖（如 SQLite / file）

## 决策记录

### [已确认] store 选型 = A. file-based (JSONL)
- 用户确认 2026-08-02
- 理由：零新增依赖（符合 D1）；与 Gateway JSONL audit 载体统一；单 worker durable 充分满足本 change；multi-worker 留生产实现
- 设计要点（候选，待 Design Doc 定稿）：
  - 每 run 一个 JSONL（`runs/<runId>.jsonl`），append-only 事件流（events + pendingOutcome + decision + checkpoint）
  - 每 session 一个 JSON（`sessions/<conversationId>.json`），lastContext + lastRunId + history
  - lease 记录（`leases/<runId>.json`）单独存 workerId + expiresAt
  - idempotency 记录（`idempotency/<key>.json`）存已执行结果
  - 恢复：扫描 runs/ 重放 JSONL 重建 AgentRunRecord
  - 原子写：append + fsync；状态变更 tmp file + rename
  - multi-worker 并发：本 change 单 worker；生产实现用文件锁或换 Postgres

### [已确认] lease 续期 = A. 活动驱动 + awaiting 释放
- 用户确认 2026-08-02
- lease 仅 running 执行时持有；awaiting_approval/awaiting_batch_confirm 释放 lease（durable 持久化等待态）；continuation 时重新 claim
- TTL 短（执行级 ~60s），活动驱动续期（每次写事件续期）
- 无定时器；fail-closed 接管只针对 running 中崩溃
- 单 worker 重启：扫描 runs/ 发现 running 状态 run（lease 过期）-> 重新 claim + checkpoint 恢复

### [已确认] checkpoint 粒度 = A. 每事件 append + structured ref 随状态变更
- 用户确认 2026-08-02
- 事件流：每 AgentRunEvent append + fsync 即持久化（JSONL 即 checkpoint）
- structured reference 作为特殊事件 append：run_created 绑定初始 RegistrySnapshotId；state_change 更新节点状态；approval_decision 记录 ApprovalRecord 引用
- 恢复：重放 JSONL 重建事件流 + 取最新 structured reference
- 单一数据源，无写放大，无 snapshot 一致性问题
### [已确认] idempotency key schema = A. 显式三段式 key
- 用户确认 2026-08-02
- key = `${runId}:${continuationType}:${sha256(canonicalJson(params))}`
- continuationType 枚举：approval_approve / approval_reject / batch_confirm
- params: approval -> {decision, approvalRecordId}；batch -> {combinations}
- 存储：`idempotency/<key>.json = {result: WorkbenchOutcome, executedAt}`
- 重复 key 返回已记录 result 不重复执行；不同 continuationType -> 不同 key

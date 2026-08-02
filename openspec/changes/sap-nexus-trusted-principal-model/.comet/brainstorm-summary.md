# Brainstorm Summary - sap-nexus-trusted-principal-model

> Comet design 阶段 brainstorming 恢复检查点。未确认内容标注为「待确认/候选」。
> 定稿后将作为 Design Doc 的输入。

## 状态
- Phase: design (brainstorming 完成, 待创建 Design Doc)
- 更新: 2026-08-02

## 已探索上下文（代码事实）

### 运行时状态承载
- Workbench backend = Next.js 15 (Node.js)；状态承载在 `frontend/src/runtime/agent-runtime-adapter.ts`
- durable state foundation（拆分项 1）已归档：`openspec/changes/archive/2026-08-02-sap-nexus-durable-state-foundation/`
- durable store 接口定义在 `frontend/src/runtime/durable/types.ts`，参考实现 `JsonlRunStore` / `JsonlConversationStore`

### 待绑定 principal 的 durable 类型（项 1 已实现）
- `AgentRunRecord`（`types.ts:45-51`）：`{ runId, query, events, pendingOutcome?, decision? }` — 无 principalId
- `SessionState`（`types.ts:19-23`）：`{ lastContext, lastRunId, history }` — 无 principalId
- `DurableRunStore.list`（`types.ts:85`）：`list(filter?: { state?: AgentRunState })` — 仅 state 过滤，无 principalId 过滤
- `DurableConversationStore.load`（`types.ts:101`）：`load(conversationId: string)` — 无 principal 过滤
- `CreateAgentRunInput`（`agent-runtime-adapter.ts:27-31`）：`{ query, rfcName?, conversationId? }` — 无 principal 字段

### 4 个 route handler（principal 注入点）
- `POST /api/agent-runs`（`route.ts`）：读 `payload.query/rfcName/conversationId`，调 `createAgentRun(...)` — 不读 principal 字段
- `POST /api/agent-runs/[runId]/approval`（`approval/route.ts`）：读 `body.decision`，调 `decideAgentRunApproval(runId, decision)` — 不读 principal 字段
- `POST /api/agent-runs/[runId]/batch`（`batch/route.ts`）：调 `confirmAgentRunBatch(runId)` — 不读 principal 字段
- `GET /api/agent-runs/[runId]/stream`（`stream/route.ts`）：调 `getAgentRunEvents(runId)` — 不读 principal 字段

### spec 现状
- 项 1 `durable-run-state` 已归档为 canonical spec：`openspec/specs/durable-run-state/spec.md`（含 5 个 Requirement：Durable agent run state / Run ownership and lease / Structured checkpoint reference / Idempotent continuation / Store-agnostic durable interface）
- 本 change `trusted-principal-scope` spec.md 已有 4 个 ADDED Requirement（Trusted principal model / Durable state binds principal / Cross-principal isolation / Local placeholder principal）
- 原设计 "Modified Capabilities: 无"（因项 1 未归档）；项 1 现已归档，可 MODIFIED durable-run-state

## Open Questions（来自 design.md）
1. ~~principal 来源（本地占位 vs 远程认证）~~ - ✅ 已确认 = A. 本地占位
2. ~~role 粒度（粗粒度 admin/operator vs 细粒度能力）~~ - ✅ 已确认 = A. 粗粒度枚举
3. ~~data scope 表达（tenant 级 vs 行级/字段级）~~ - ✅ 已确认 = A. tenant 级

## 澄清项（brainstorming 中用户补充确认）
4. ~~principal 绑定 spec 方式~~ - ✅ 已确认 = trusted-principal-scope（New）+ durable-run-state（MODIFIED 加 principalId）
5. ~~旧 run replay 兼容~~ - ✅ 已确认 = 默认回填占位 principal（local-user-0001）
6. ~~conversation 归属~~ - ✅ 已确认 = conversationId 前端生成，后端首次请求记录 conversationId -> principalId 绑定

## 约束（已确认）
- principal/tenant/role/data scope 是 server-owned context（§3.9 / §4.2.1）
- principal MUST NOT 由 request、prompt、summary 或 Memory 供给（防 prompt injection 篡权）
- v1 local-first 单用户占位 principal；authn/authz 运行时为 non-goal
- 不触 Gateway WRITE path / SSE / durable approval store / authn runtime
- design.md D1-D5 保持不变；Open Question 决策细化 D1（role/dataScope 粒度）与 D5（principal 来源接口）

## 决策记录

### [已确认] Q1 principal 来源 = A. 本地占位
- 用户确认 2026-08-02
- 理由：local-first 优先，避免过早引入 authn 复杂度；v1 单用户场景无需远程认证；接口可扩展，远程认证（OIDC/JWT）留后续
- 设计要点（候选，待 Design Doc 定稿）：
  - 定义 `PrincipalInjector` 接口：`inject(request: Request): TrustedPrincipal`
  - v1 实现 `LocalPlaceholderPrincipalInjector`：返回固定 `principalId = "local-user-0001"`
  - 远程认证（OIDC/JWT）为接口扩展点，v1 non-goal
  - injector 在 route handler 请求入口调用，principal 由后端持有，不读 request body

### [已确认] Q2 role 粒度 = A. 粗粒度枚举
- 用户确认 2026-08-02
- 理由：v1 单用户场景无需细粒度能力；粗粒度枚举足够表达 admin/operator/viewer 语义；细粒度能力映射（SAP authorization）依赖远程认证与权限引擎，显式 non-goal
- 设计要点（候选，待 Design Doc 定稿）：
  - `TrustedPrincipal.role: "admin" | "operator" | "viewer"`
  - v1 占位 `role = "operator"`
  - 细粒度能力映射（principal role -> SAP authorization）显式 non-goal

### [已确认] Q3 data scope = A. tenant 级
- 用户确认 2026-08-02
- 理由：v1 单 tenant 场景无需行级/字段级控制；tenant 级 data scope 足够支撑 cross-principal 隔离；行级/字段级依赖细粒度权限引擎，显式 non-goal
- 设计要点（候选，待 Design Doc 定稿）：
  - `dataScope = { tenantId: string }`
  - v1 单 tenant 占位 `tenantId = "default"`
  - 不预留未消费扩展字段（YAGNI；后续需要行级/字段级时再扩展 dataScope 结构）
  - D1 原列 `tenantId` 为顶层字段，brainstorm 后合并入 `dataScope.tenantId`，消除冗余

### [已确认] 澄清项 4 - principal 绑定 spec 方式 = trusted-principal-scope（New）+ durable-run-state（MODIFIED）
- 用户确认 2026-08-02
- 理由：项 1（durable-state-foundation）现已归档，durable-run-state 成为 canonical spec；principalId 绑定是对已归档 spec 的向后兼容扩展（加可选字段 + 过滤参数），适合 MODIFIED 而非另建新 spec
- 设计要点（候选，待 Design Doc 定稿）：
  - `trusted-principal-scope`（New）：定义 TrustedPrincipal 模型、PrincipalInjector 接口、server-owned 注入、cross-principal 隔离、本地占位 principal
  - `durable-run-state`（MODIFIED）：在 "Durable agent run state" 加 principalId 绑定字段；在 "Store-agnostic durable interface" 加 list/load 的 principalId 过滤参数
  - 向后兼容：principalId 为可选字段，旧记录回填占位 principal
  - 注：此决策更新 design.md 原 "Modified Capabilities: 无"（因项 1 已归档）

### [已确认] 澄清项 5 - 旧 run replay 兼容 = 默认回填占位 principal
- 用户确认 2026-08-02
- 理由：v1 单用户场景，所有旧 durable state 归属占位 principal（local-user-0001）是安全假设；无需迁移脚本
- 设计要点（候选，待 Design Doc 定稿）：
  - 加载旧 `AgentRunRecord`（无 principalId）时回填 `"local-user-0001"`
  - 加载旧 `SessionState`（无 principalId）时回填 `"local-user-0001"`
  - v1 单用户场景安全；未来多用户需迁移脚本（non-goal）

### [已确认] 澄清项 6 - conversation 归属 = conversationId 前端生成，后端记录绑定
- 用户确认 2026-08-02
- 理由：conversationId 前端生成保持现有行为不变；后端在首次请求时记录 conversationId -> principalId 绑定，后续请求校验归属（fail-closed）
- 设计要点（候选，待 Design Doc 定稿）：
  - `SessionState` 加 `principalId?: string`（可选，向后兼容）
  - `getSession(conversationId)` 首次创建时写入 `principalId = injected.principalId`
  - 后续请求加载已有 SessionState 时校验 `session.principalId === injected.principalId`，不匹配 fail-closed

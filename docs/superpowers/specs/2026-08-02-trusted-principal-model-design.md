---
comet_change: sap-nexus-trusted-principal-model
role: technical-design
canonical_spec: openspec
---

# Design: Trusted Principal Model (P0B 项2/4)

> Comet change: `sap-nexus-trusted-principal-model` (phase: design)
> Canonical spec: `openspec/changes/sap-nexus-trusted-principal-model/specs/`
> 本文档把 change `design.md` 的 D1-D5 与 3 个 Open Question 决策 + 3 个澄清项决策展开为可实施的技术设计。

## Context

当前 Workbench backend 是 local-first 单用户模型，运行时无身份/主体概念。durable state foundation（拆分项 1，已归档为 `openspec/specs/durable-run-state/spec.md`）已把 Run/Sessions 转为 durable store，但 durable state 未绑定 principal：

- `AgentRunRecord`（`frontend/src/runtime/durable/types.ts:45-51`）：`{ runId, query, events, pendingOutcome?, decision? }` - 无 principalId。
- `SessionState`（`types.ts:19-23`）：`{ lastContext, lastRunId, history }` - 无 principalId。
- `DurableRunStore.list`（`types.ts:85`）：`list(filter?: { state?: AgentRunState })` - 仅 state 过滤，无 principalId 过滤。
- `DurableConversationStore.load`（`types.ts:101`）：`load(conversationId: string)` - 无 principal 过滤。
- `CreateAgentRunInput`（`agent-runtime-adapter.ts:27-31`）：`{ query, rfcName?, conversationId? }` - 无 principal 字段。

技术架构 §3.9 "可信身份与执行主体边界" 要求 agent run、approval、conversation 绑定 trusted principal；§4.2.1 明确 principal/tenant/role/data scope 是 server-owned context，MUST NOT 由 request、prompt、summary 或 Memory 供给。本 change（拆分项 2/4）建立 principal 模型并绑定 durable state，是 cross-principal 隔离与审计的前置。

**项 1 已归档**：durable-run-state 现为 canonical spec，本 change 通过 MODIFIED 向后兼容扩展加 principalId 绑定（更新 design.md 原 "Modified Capabilities: 无" 决策）。

## Goals / Non-Goals

**Goals:**
- TrustedPrincipal 数据模型（principalId / role / dataScope），server-owned context。
- PrincipalInjector 接口 + LocalPlaceholderPrincipalInjector v1 实现。
- durable state 绑定 principal：AgentRunRecord / SessionState 记录 `principalId`。
- server-owned 注入：后端注入 principal，不来自 request/prompt/summary/Memory。
- cross-principal 隔离：principal A SHALL NOT 读取 principal B 的 durable state，fail-closed。
- 旧 run replay 兼容：回填占位 principal。

**Non-Goals:**
- durable state foundation（拆分项 1，已归档，提供 store 接口）。
- authn/authz 运行时实现（远程认证 OIDC/JWT、token 校验、权限决策引擎留后续）。
- SAP 权限映射（principal role -> SAP authorization 映射留后续）。
- durable ApprovalStore（拆分项 3）、incremental SSE（拆分项 4）。
- Gateway WRITE path、SSE cursor/reconnect、durable approval store。

## Decisions

D1-D5 来自 `design.md`，保持不变。3 个 Open Question + 3 个澄清项于 2026-08-02 brainstorming 确认：

| Open Question / 澄清项 | 决策 | 理由 |
|---|---|---|
| Q1 principal 来源 | **A. 本地占位** | local-first 优先；v1 单用户无需远程认证；接口可扩展 OIDC/JWT |
| Q2 role 粒度 | **A. 粗粒度枚举** | v1 单用户无需细粒度能力；admin/operator/viewer 足够；SAP authorization 映射 non-goal |
| Q3 data scope | **A. tenant 级** | v1 单 tenant 无需行级/字段级；tenant 级足够支撑隔离；不预留未消费扩展字段 |
| 澄清项 4 spec 绑定方式 | **trusted-principal-scope（New）+ durable-run-state（MODIFIED 加 principalId）** | 项 1 已归档；principalId 是向后兼容扩展（加可选字段 + 过滤参数） |
| 澄清项 5 旧 run replay | **回填占位 principal（local-user-0001）** | v1 单用户场景安全假设；无需迁移脚本 |
| 澄清项 6 conversation 归属 | **conversationId 前端生成，后端首次请求记录绑定** | 保持现有行为；SessionState 加 principalId；后续校验归属 fail-closed |

**D1 细化**：brainstorm 后 `tenantId` 合并入 `dataScope.tenantId`，消除顶层冗余字段。`TrustedPrincipal` 最终为 `{ principalId, role, dataScope: { tenantId } }`。

**D2 spec 策略更新**：design.md 原 "Modified Capabilities: 无"（因项 1 未归档）。项 1 现已归档，D2 更新为 MODIFIED `durable-run-state`（加 principalId 绑定字段 + list/load 过滤参数），向后兼容扩展。

## 详细设计

### 1. TrustedPrincipal 数据模型

```ts
type PrincipalRole = "admin" | "operator" | "viewer";

type DataScope = {
  tenantId: string;
};

type TrustedPrincipal = {
  principalId: string;
  role: PrincipalRole;
  dataScope: DataScope;
};
```

**字段语义：**

| 字段 | 类型 | 语义 | v1 占位值 |
|---|---|---|---|
| `principalId` | `string` | 主体唯一标识，durable state 归属键 | `"local-user-0001"` |
| `role` | `"admin" \| "operator" \| "viewer"` | 粗粒度角色枚举 | `"operator"` |
| `dataScope.tenantId` | `string` | tenant 级数据范围，隔离边界 | `"default"` |

**设计约束：**
- server-owned context：由后端在请求入口注入，对 LLM 不可见、不可篡改（D1/D3）。
- `dataScope` 仅含 `tenantId`，不预留未消费扩展字段（Q3 决策；行级/字段级控制为后续 non-goal）。
- `role` 为粗粒度枚举，细粒度能力映射（SAP authorization）为 non-goal（Q2 决策）。
- `TrustedPrincipal` 是值对象，不可变；一次请求内 principal 不变。

**v1 占位 principal 实例：**
```ts
const PLACEHOLDER_PRINCIPAL: TrustedPrincipal = {
  principalId: "local-user-0001",
  role: "operator",
  dataScope: { tenantId: "default" }
};
```

### 2. PrincipalInjector 接口 + LocalPlaceholderPrincipalInjector 实现

```ts
interface PrincipalInjector {
  inject(request: Request): TrustedPrincipal;
}
```

**接口契约：**
- 输入：Next.js `Request` 对象（route handler 入口接收的请求）。
- 输出：`TrustedPrincipal`（server-owned，不可为 null/undefined）。
- 实现 SHALL NOT 从 request body 读取 principal 字段（D3）。
- 实现 SHALL NOT 从 prompt / summary / Memory 读取 principal（D3）。
- 实现可读 server 持有的身份源（环境变量、session cookie、header token 等），v1 不消费任何远程身份源。

**v1 实现 - LocalPlaceholderPrincipalInjector：**
```ts
class LocalPlaceholderPrincipalInjector implements PrincipalInjector {
  inject(_request: Request): TrustedPrincipal {
    return PLACEHOLDER_PRINCIPAL;
  }
}
```

- 忽略 request 参数，返回固定占位 principal。
- 无远程认证时默认注入此实现。
- 单例：进程内共享一个 injector 实例（与 `runStore` / `conversationStore` 同级初始化）。

**扩展点（v1 non-goal）：**
- `RemoteAuthPrincipalInjector`（未来）：从 request header 解析 OIDC/JWT token，校验后映射为 `TrustedPrincipal`。
- 接口不变，实现可插拔（对齐项 1 D1 store-agnostic 心智模型）。
- 远程认证运行时（token 校验、JWKS 获取、权限决策引擎）为 non-goal。

**injector 初始化（与项 1 store 初始化对齐）：**
- 模块级变量 `principalInjector: PrincipalInjector`，默认 `new LocalPlaceholderPrincipalInjector()`。
- 测试钩子 `setPrincipalInjectorForTests(injector)`，与 `setDurableStoresForTests` 同级。

### 3. Durable state principalId 绑定

#### 3.1 AgentRunRecord 加 principalId

```ts
// types.ts - MODIFIED (向后兼容扩展)
type AgentRunRecord = {
  runId: string;
  query: string;
  events: AgentRunEvent[];
  pendingOutcome?: WorkbenchOutcome;
  decision?: ApprovalDecision;
  principalId: string;  // ADDED: 创建时写入，不可变
};
```

- `principalId` 在 `createAgentRun` 时写入，来自注入的 `TrustedPrincipal.principalId`。
- 不可变：创建后不可修改（spec "Durable state binds principal" - immutable for the lifetime of the run）。
- 向后兼容：旧记录无此字段 -> 加载时回填 `"local-user-0001"`（§6）。

#### 3.2 SessionState 加 principalId

```ts
// types.ts - MODIFIED (向后兼容扩展)
type SessionState = {
  lastContext: LastContext | null;
  lastRunId: string | null;
  history: Turn[];
  principalId?: string;  // ADDED: 首次请求时写入，后续校验归属
};
```

- `principalId` 在 `getSession` 首次创建 SessionState 时写入。
- 可选字段（`?`）：向后兼容旧 session 无此字段（回填 §6）。
- 后续请求加载已有 SessionState 时校验 `session.principalId === injected.principalId`，不匹配 fail-closed（§4）。

#### 3.3 DurableRunStore.list 加 principalId 过滤

```ts
// types.ts - MODIFIED (向后兼容扩展)
interface DurableRunStore {
  // ...existing methods unchanged...
  list(filter?: { state?: AgentRunState; principalId?: string }): Promise<AgentRunRecord[]>;
  //                                          ^^^^^^^^^^^^^^^^^ ADDED
}
```

- `principalId` 过滤为可选参数；传入时仅返回该 principal 的 run。
- 向后兼容：不传 `principalId` 时行为不变（项 1 契约不破坏）。
- route handler 调用 `list` 时 SHALL 传入注入的 `principalId`（§5）。

#### 3.4 DurableConversationStore.load 加 principal 过滤

```ts
// types.ts - MODIFIED (向后兼容扩展)
interface DurableConversationStore {
  // ...existing methods unchanged...
  load(conversationId: string, principalId?: string): Promise<SessionState | null>;
  //                              ^^^^^^^^^^^^^^^^^ ADDED
}
```

- `principalId` 过滤为可选参数；传入时校验 session 归属，不匹配返回 `null`（fail-closed）。
- 向后兼容：不传 `principalId` 时行为不变。
- route handler 调用 `load` 时 SHALL 传入注入的 `principalId`（§5）。

#### 3.5 CreateAgentRunInput 加 principal

```ts
// agent-runtime-adapter.ts - MODIFIED
type CreateAgentRunInput = {
  query: string;
  rfcName?: string;
  conversationId?: string;
  principal: TrustedPrincipal;  // ADDED: server-injected
};
```

- `createAgentRun` 将 `input.principal.principalId` 写入 `AgentRunRecord.principalId`（创建时绑定）。
- route handler 调用 `createAgentRun` 时 SHALL 传入注入的 principal（§5）。

### 4. Cross-principal 隔离 fail-closed

**隔离原则（D4）：** durable store 查询按 `principalId` 强制过滤；principal A 访问 principal B 的 run/approval/session SHALL fail-closed。

#### 4.1 Run 访问校验

`decideAgentRunApproval` / `confirmAgentRunBatch` / `getAgentRunEvents` 在加载 run 后、执行操作前校验归属：

```
load(runId) -> record
if record.principalId !== injected.principalId:
  -> deny (fail-closed), return RUN_NOT_FOUND or FORBIDDEN
```

- 校验在 `claim` lease 之前（先验归属，再验并发）。
- fail-closed：不返回 principal B 的任何数据，不抛"属于其他用户"等泄露性错误（返回 404 RUN_NOT_FOUND，不泄露存在性）。

#### 4.2 Session 访问校验

`getSession(conversationId, principalId)` 加载已有 SessionState 时：

```
load(conversationId, principalId) -> session | null
if session === null:
  -> 首次请求，创建新 session，写入 principalId
if session.principalId !== principalId:
  -> deny (fail-closed), return null / throw
```

- 首次请求（session 不存在）：创建新 SessionState，写入 `principalId = injected.principalId`。
- 后续请求（session 存在）：校验归属，不匹配 fail-closed。
- conversationId 前端生成不变；归属在后端首次请求时绑定（澄清项 6）。

#### 4.3 List 过滤

route handler 调用 `runStore.list` 时 SHALL 传入 `principalId`，仅返回当前 principal 的 run。不传 `principalId` 的调用仅在测试钩子中使用。

#### 4.4 JSONL 实现的过滤策略

项 1 的 `JsonlRunStore` 扫描 `runs/` 目录重放 JSONL 重建 `AgentRunRecord`。principalId 过滤在重放后按 `record.principalId` 内存过滤（单 worker 全量重放，无额外索引开销）。`principalId` 作为 `run_meta` 行的一个字段持久化到 JSONL，恢复时直接读取。

### 5. Server-owned 注入（4 个 route handler）

**注入原则（D3）：** principal 由后端在请求入口注入，不来自 request body、prompt、summary 或 Memory。request 或 LLM 输出携带的 principal 字段 SHALL be ignored/rejected。

#### 5.1 注入点

每个 route handler 在入口调用 `principalInjector.inject(request)`，将返回的 `TrustedPrincipal` 传递给 adapter 函数：

| Route handler | 文件 | 注入位置 | 传递方式 |
|---|---|---|---|
| `POST /api/agent-runs` | `frontend/app/api/agent-runs/route.ts` | `createAgentRun` 调用前 | `createAgentRun({ ..., principal })` |
| `POST /api/agent-runs/[runId]/approval` | `frontend/app/api/agent-runs/[runId]/approval/route.ts` | `decideAgentRunApproval` 调用前 | `decideAgentRunApproval(runId, decision, principal)` |
| `POST /api/agent-runs/[runId]/batch` | `frontend/app/api/agent-runs/[runId]/batch/route.ts` | `confirmAgentRunBatch` 调用前 | `confirmAgentRunBatch(runId, principal)` |
| `GET /api/agent-runs/[runId]/stream` | `frontend/app/api/agent-runs/[runId]/stream/route.ts` | `getAgentRunEvents` 调用前 | `getAgentRunEvents(runId, principal)` |

#### 5.2 adapter 函数签名变更

```ts
// agent-runtime-adapter.ts - MODIFIED signatures
export async function createAgentRun(input: CreateAgentRunInput): Promise<{ runId: string }>;
//  CreateAgentRunInput 已加 principal（§3.5）

export async function decideAgentRunApproval(
  runId: string,
  decision: ApprovalDecision,
  principal: TrustedPrincipal  // ADDED
): Promise<void>;

export async function confirmAgentRunBatch(
  runId: string,
  principal: TrustedPrincipal  // ADDED
): Promise<void>;

export async function getAgentRunEvents(
  runId: string,
  principal: TrustedPrincipal  // ADDED
): Promise<AgentRunEvent[]>;
```

每个函数内部在 `load(runId)` 后校验 `record.principalId === principal.principalId`（§4.1），不匹配 fail-closed。

#### 5.3 阻断 prompt injection 篡权

- route handler 仅从 request body 读取业务字段（`query` / `rfcName` / `conversationId` / `decision`），**不读取任何 principal 字段**。
- 即使 request body 携带 `principal` / `principalId` / `role` / `tenantId` 字段，route handler 不解析、不传递，直接忽略。
- `PrincipalInjector.inject` 实现不读 request body 的 principal 字段（v1 `LocalPlaceholderPrincipalInjector` 完全忽略 request）。
- LLM 输出 / prompt summary / Memory 携带的 principal 标识符不进入 principal 注入路径（D3：rejected）。
- principal 是 trust boundary：唯一来源是 server 持有的身份源（v1 为固定占位值）。

#### 5.4 注入流程图

```
Request -> route handler
  -> principalInjector.inject(request) -> TrustedPrincipal (server-owned)
  -> adapter function(principal)
     -> load(runId) / getSession(conversationId, principalId)
     -> 校验归属 (fail-closed)
     -> 执行操作 (create / continue / read)
```

### 6. 旧 run replay 兼容

**场景：** 项 1 已归档的 durable state（JSONL 文件 / session JSON）不含 `principalId` 字段。本 change 加载这些旧记录时回填占位 principal。

#### 6.1 回填策略

| 数据类型 | 加载位置 | 旧记录状态 | 回填值 |
|---|---|---|---|
| `AgentRunRecord` | `JsonlRunStore.load` / 恢复重放 | `principalId` 字段缺失 | `"local-user-0001"` |
| `SessionState` | `JsonlConversationStore.load` | `principalId` 字段缺失 | `"local-user-0001"` |

- 回填在 store 实现层完成（`load` 返回时确保 `principalId` 非空）。
- 回填值 = v1 占位 principal 的 `principalId`，与 `LocalPlaceholderPrincipalInjector` 返回值一致。
- v1 单用户场景安全假设：所有旧数据归属唯一占位用户。
- 回填后旧记录与新记录行为一致（cross-principal 隔离校验通过，因为注入的也是 `local-user-0001`）。

#### 6.2 持久化兼容

- 旧 JSONL 文件中 `run_meta` 行不含 `principalId` 字段 -> 重放时回填，不修改原文件。
- 新 JSONL 文件中 `run_meta` 行包含 `principalId` 字段。
- `JsonlRunStore.save` 写入新记录时 SHALL 包含 `principalId`。
- `JsonlConversationStore.save` 写入 session 时 SHALL 包含 `principalId`（若已绑定）。

#### 6.3 未来多用户迁移（non-goal）

v1 单用户场景无需迁移脚本。未来引入多用户时，需要：
1. 迁移脚本：按实际用户归属重写旧记录的 `principalId`。
2. 停用回填逻辑（`LocalPlaceholderPrincipalInjector` 替换为 `RemoteAuthPrincipalInjector`）。

以上为 non-goal，本 change 不实现。

## 替换点

| 当前 | 替换为 |
|---|---|
| `AgentRunRecord`（`types.ts:45-51`）无 principalId | 加 `principalId: string`（创建时写入，不可变） |
| `SessionState`（`types.ts:19-23`）无 principalId | 加 `principalId?: string`（首次请求写入，向后兼容） |
| `DurableRunStore.list`（`types.ts:85`）无 principalId 过滤 | filter 加 `principalId?: string` 可选参数 |
| `DurableConversationStore.load`（`types.ts:101`）无 principal 过滤 | 加 `principalId?: string` 可选参数 |
| `CreateAgentRunInput`（`adapter:27-31`）无 principal | 加 `principal: TrustedPrincipal` |
| `createAgentRun`（`adapter:101`） | 写入 `record.principalId = input.principal.principalId` |
| `decideAgentRunApproval`（`adapter:173`） | 加 `principal` 参数，load 后校验归属 |
| `confirmAgentRunBatch`（`adapter:236`） | 加 `principal` 参数，load 后校验归属 |
| `getAgentRunEvents`（`adapter:168`） | 加 `principal` 参数，load 后校验归属 |
| `getSession`（`adapter:82`） | 加 `principalId` 参数，首次创建写入，后续校验归属 |
| 4 个 route handler | 入口加 `principalInjector.inject(request)`，传递 principal |
| 无 PrincipalInjector | 新增 `PrincipalInjector` 接口 + `LocalPlaceholderPrincipalInjector` 实现 + `TrustedPrincipal` / `PrincipalRole` / `DataScope` 类型 |
| `JsonlRunStore.load` / 恢复重放 | 旧记录无 principalId 时回填 `"local-user-0001"` |
| `JsonlConversationStore.load` | 旧 session 无 principalId 时回填 `"local-user-0001"` |

**新增文件建议位置：** `frontend/src/runtime/principal/`（`types.ts` 定义 TrustedPrincipal/PrincipalRole/DataScope，`principal-injector.ts` 定义接口 + LocalPlaceholderPrincipalInjector）。与 `frontend/src/runtime/durable/` 同级。

## 安全契约

| 契约 | 设计章节 | 实现 |
|---|---|---|
| principal 由后端注入（D3） | §5 server-owned 注入 | route handler 入口 `principalInjector.inject(request)` |
| principal 不来自 request body | §5.3 阻断 prompt injection | route handler 不读 request body 的 principal 字段 |
| principal 不来自 prompt/summary/Memory | §5.3 | injector 不读 LLM 输出；principal 字段对 LLM 不可见 |
| cross-principal 隔离 fail-closed（D4） | §4 隔离 | load 后校验 `principalId` 归属，不匹配 deny |
| durable state principalId 不可变（D2） | §3.1 | 创建时写入，后续不可修改 |
| 旧记录回填占位 principal | §6 兼容 | store load 层回填 `local-user-0001` |

**不触碰的边界（Non-Goals 明确排除）：**
- Gateway WRITE path（`BAPI_TRANSACTION_COMMIT` / approval 决策不在本 change）。
- SSE cursor / reconnect（拆分项 4）。
- durable ApprovalStore（拆分项 3，Gateway `InMemoryApprovalStore` 替换）。
- authn runtime（远程认证、token 校验、权限决策引擎）。

## Risks / Trade-offs

- [principal 模型过早抽象] -> 本地占位 + 接口可扩展；role/dataScope 粒度在 brainstorm 已细化（粗粒度枚举 + tenant 级），避免过度设计。
- [cross-principal 隔离性能] -> v1 单用户全量重放 + 内存过滤，无额外索引开销；未来多用户时 JSONL 实现可加 `principalId` 目录分片或换 Postgres（接口不变）。
- [fail-closed 误拒合法请求] -> v1 单用户场景所有 principalId 一致（`local-user-0001`），不会误拒；回填保证旧记录兼容。
- [principalId 泄露存在性] -> cross-principal 访问返回 404 RUN_NOT_FOUND（不返回 403 FORBIDDEN），不泄露资源存在性。
- [spec MODIFIED 向后兼容] -> principalId 为可选字段 + 可选过滤参数，项 1 契约不破坏；旧 spec consumer 不传 principalId 时行为不变。
- [conversationId 前端生成被伪造] -> conversationId 仅作分组键；归属由后端首次请求绑定 principalId 决定；伪造 conversationId 无法越权（加载时校验 principalId 归属 fail-closed）。

## 与 spec 的映射

| Spec Requirement | Spec 文件 | 变更类型 | Design 章节 |
|---|---|---|---|
| Trusted principal model | `trusted-principal-scope/spec.md` | ADDED | §1 数据模型 |
| Durable state binds principal | `trusted-principal-scope/spec.md` | ADDED | §3 durable state 绑定 |
| Cross-principal isolation | `trusted-principal-scope/spec.md` | ADDED | §4 隔离 fail-closed |
| Local placeholder principal | `trusted-principal-scope/spec.md` | ADDED | §2 PrincipalInjector + LocalPlaceholder |
| Server-owned injection | `trusted-principal-scope/spec.md` | ADDED | §5 server-owned 注入 |
| Durable agent run state（加 principalId 绑定） | `durable-run-state/spec.md` | MODIFIED | §3.1 AgentRunRecord 加 principalId |
| Store-agnostic durable interface（加 list/load principalId 过滤） | `durable-run-state/spec.md` | MODIFIED | §3.3 / §3.4 list/load 加过滤参数 |

**spec 变更说明：**
- `trusted-principal-scope`（New）：定义 TrustedPrincipal 模型、PrincipalInjector 接口、server-owned 注入契约、cross-principal 隔离、本地占位 principal。spec.md 已存在 4 个 ADDED Requirement。
- `durable-run-state`（MODIFIED）：向后兼容扩展已归档 spec。在 "Durable agent run state" Requirement 加 principalId 绑定语义（创建时写入、不可变）；在 "Store-agnostic durable interface" Requirement 加 list/load 的 principalId 过滤参数。MODIFIED spec.md 将在 build 阶段创建（spec patch）。
- 此映射更新 design.md 原 "Modified Capabilities: 无"（因项 1 已归档，D2 spec 策略更新）。

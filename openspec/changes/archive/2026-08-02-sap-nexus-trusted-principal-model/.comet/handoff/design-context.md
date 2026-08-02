# Comet Design Handoff

- Change: sap-nexus-trusted-principal-model
- Phase: design
- Mode: compact
- Context hash: d4aa67f59a71e26b79dbeba8e47763c5453da9a3e377c986253c7373a7db983c

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/sap-nexus-trusted-principal-model/proposal.md

- Source: openspec/changes/sap-nexus-trusted-principal-model/proposal.md
- Lines: 1-29
- SHA256: d9850431dab57277b5be6300df41e865e7db396a47fdfb23ebdb417e6a4f901e

```md
## Why

当前 Workbench backend 是 local-first 单用户模型，无身份/主体概念：agent run、approval、conversation session 均不绑定 principal，无 tenant/role/data scope 区分。这阻塞了 P0B 条件门禁：条件门禁要求 trusted principal/tenant/role/data scope 作为 server-owned context；durable state（拆分项 1）需要绑定 principal 才能实现 cross-principal 隔离与审计；principal MUST NOT 由 request、prompt、summary 或 Memory 供给（防止 prompt injection 篡权）。本 change 建立 trusted principal/tenant/role/data scope 模型，是 P0B 拆分项 2/4。

## What Changes

- 建立 principal/tenant/role/data scope 数据模型（server-owned context），作为 agent run、approval、conversation session 的身份绑定基座。
- durable Run/Approval/Sessions 绑定 principal：每条 durable state 记录 `principalId`，归属明确（与拆分项 1 durable state foundation 对接）。
- cross-principal 隔离：principal A SHALL NOT 读取 principal B 的 run/approval/session，fail-closed。
- server-owned 注入：principal 由后端注入，不来自 request body、prompt、summary 或 Memory；request 或 LLM 输出携带的 principal 字段 SHALL be ignored/rejected。
- 本地占位 principal + 接口：v1 提供 local-first 单用户占位 principal，authn/authz 运行时实现是 non-goal（留后续）。

## Capabilities

### New Capabilities

- `trusted-principal-scope`: trusted principal/tenant/role/data scope 模型（server-owned）、durable state 绑定 principal、server-owned 注入、cross-principal 隔离、本地占位 principal。

### Modified Capabilities

无。durable-run-state（拆分项 1）尚未归档，不作为 Modified Capabilities；principal 绑定关系在 design.md 说明，待项 1 归档后在 build 阶段对接。

## Impact

- durable state 绑定 principal：Run/Approval/Sessions 记录 `principalId`（依赖拆分项 1 durable store 接口）。
- server-owned 注入：后端在请求入口注入 principal，request/prompt/summary/Memory 携带的 principal 字段被忽略或拒绝。
- cross-principal 隔离：durable store 查询按 `principalId` 过滤，索引 `principalId`。
- 不实现 authn/authz 运行时（non-goal）；不触 Gateway approval（拆分项 3）、不触 SSE（拆分项 4）。
- 依赖：技术架构 §3.9 "可信身份与执行主体边界"、§4.2.1 "principal/tenant/role/data scope 是 server-owned context"。

```

## openspec/changes/sap-nexus-trusted-principal-model/design.md

- Source: openspec/changes/sap-nexus-trusted-principal-model/design.md
- Lines: 1-39
- SHA256: 0a9c350baf900f97b10dbf7fda43939bf063a25cfdfec700e50114ad9bb0fbfd

```md
## Context

当前 Workbench backend 是 local-first 单用户模型，运行时无身份/主体概念：`runs`（`agent-runtime-adapter.ts:109`）、`sessions`（`agent-runtime-adapter.ts:112`）均不绑定 principal，无 tenant/role/data scope 区分。技术架构 §3.9 "可信身份与执行主体边界" 要求 agent run、approval、conversation 绑定 trusted principal；§4.2.1 明确 principal/tenant/role/data scope 是 server-owned context，MUST NOT 由 request、prompt、summary 或 Memory 供给。durable state foundation（拆分项 1）已把 Run/Sessions 转为 durable store，但未绑定 principal；本 change（拆分项 2/4）建立 principal 模型并绑定 durable state，是 cross-principal 隔离与审计的前置。

## Goals / Non-Goals

**Goals:**

- principal/tenant/role/data scope 数据模型（server-owned context）。
- durable state 绑定 principal：Run/Approval/Sessions 记录 `principalId`。
- server-owned 注入：后端注入 principal，不来自 request/prompt/summary/Memory。
- cross-principal 隔离：principal A SHALL NOT 读取 principal B 的 durable state。

**Non-Goals:**

- durable state foundation（拆分项 1，提供 store 接口）。
- authn/authz 运行时实现（远程认证、token 校验、权限决策引擎留后续）。
- SAP 权限映射（principal role -> SAP authorization 映射留后续）。
- durable ApprovalStore（拆分项 3）、incremental SSE（拆分项 4）。

## Decisions

- **D1 principal/tenant/role/data scope 数据模型（server-owned）**：定义 `TrustedPrincipal`（`principalId` / `tenantId` / `role` / `dataScope`）作为 server-owned context，由后端在请求入口注入。principal 字段对 LLM 不可见、不可篡改。理由：对齐 §3.9/§4.2.1，从源头阻断 prompt injection 篡权。备选：request 携带 principal——被否决（不可信来源）。
- **D2 durable state 绑定 principal**：durable Run/Approval/Sessions 每条记录 SHALL 绑定 `principalId`；查询按 `principalId` 过滤。与拆分项 1 durable store 接口对接（项 1 未归档，build 阶段对接）。理由：cross-principal 隔离与审计需要归属。
- **D3 server-owned 注入**：principal 由后端注入（请求入口解析 server 持有的身份源），不来自 request body、prompt、summary 或 Memory；request 或 LLM 输出携带的 principal 字段 SHALL be ignored/rejected。理由：principal 是 trust boundary，不可由不可信输入供给。
- **D4 cross-principal 隔离**：durable store 查询按 `principalId` 强制过滤；principal A 访问 principal B 的 run/approval/session SHALL fail-closed。理由：防越权。
- **D5 本地占位 principal**：v1 提供 local-first 单用户占位 principal（固定 `principalId`），authn 运行时是 non-goal。接口可扩展为远程认证。理由：local-first 优先，避免过早引入 authn 复杂度。

## Risks / Trade-offs

- [principal 模型过早抽象] -> 本地占位 + 接口可扩展；comet-design 阶段细化 role/data scope 粒度。
- [cross-principal 隔离性能] -> durable store 索引 `principalId`，查询走索引。
- [与拆分项 1 对接时序] -> 项 1 未归档；build 阶段对接 durable store 接口，spec 不 MODIFIED durable-run-state。

## Open Questions

- principal 来源（本地占位 vs 远程认证，comet-design 阶段细化接口）。
- role 粒度（粗粒度 admin/operator vs 细粒度能力）。
- data scope 表达（tenant 级 vs 行级/字段级）。

```

## openspec/changes/sap-nexus-trusted-principal-model/tasks.md

- Source: openspec/changes/sap-nexus-trusted-principal-model/tasks.md
- Lines: 1-39
- SHA256: ce57f39e2c1b1ac762ffa91ee630979b784fe2dddd546f3d17b01f6bcf9ab349

```md
## 1. Principal 模型

- [ ] 1.1 定义 `TrustedPrincipal` 数据结构（`principalId` / `tenantId` / `role` / `dataScope`，server-owned context）
- [ ] 1.2 定义 principal 注入接口（`PrincipalInjector`，请求入口解析 server 持有的身份源）
- [ ] 1.3 comet-design 阶段细化 role 粒度与 data scope 表达（粗粒度 admin/operator vs 细粒度能力）

## 2. Durable state 绑定 principal

- [ ] 2.1 durable Run 记录绑定 `principalId`（创建时写入，不可变）
- [ ] 2.2 durable Approval 记录绑定 `principalId`（与 run 归属一致）
- [ ] 2.3 durable ConversationState（Sessions）记录绑定 `principalId`
- [ ] 2.4 与拆分项 1 durable store 接口对接（项 1 归档后 build 阶段集成）

## 3. Server-owned 注入

- [ ] 3.1 后端在请求入口注入 principal（`PrincipalInjector` 实现）
- [ ] 3.2 request body 携带的 principal 字段被忽略（不信任 request 供给）
- [ ] 3.3 LLM 输出 / prompt summary / Memory 携带的 principal 被拒绝（prompt injection 防护）

## 4. Cross-principal 隔离

- [ ] 4.1 durable store 查询按 `principalId` 强制过滤
- [ ] 4.2 principal A 访问 principal B 的 run/approval/session fail-closed
- [ ] 4.3 durable store 索引 `principalId`（隔离性能）

## 5. 本地占位 principal

- [ ] 5.1 v1 本地占位 principal（local-first，固定 `principalId`）
- [ ] 5.2 无远程认证时默认注入占位 principal
- [ ] 5.3 principal 注入接口预留远程认证扩展点（authn 运行时为 non-goal）

## 6. 测试与验证

- [ ] 6.1 server-owned 注入测试（request/LLM 输出 principal 被忽略/拒绝）
- [ ] 6.2 durable state 绑定 principal 测试（Run/Approval/Sessions 记录 `principalId`）
- [ ] 6.3 cross-principal 隔离 fail-closed 测试
- [ ] 6.4 本地占位 principal 默认注入测试
- [ ] 6.5 `openspec validate --all --strict` 通过
- [ ] 6.6 `npm --prefix frontend run verify` + agent pytest 回归通过

```

## openspec/changes/sap-nexus-trusted-principal-model/specs/trusted-principal-scope/spec.md

- Source: openspec/changes/sap-nexus-trusted-principal-model/specs/trusted-principal-scope/spec.md
- Lines: 1-44
- SHA256: 2f2d0a21cd7fefe6bfa670da0ce33e6ed52293574a76d705c444a3c45d009ca5

```md
## ADDED Requirements

### Requirement: Trusted principal model
The system SHALL model trusted principal/tenant/role/data scope as server-owned context. The principal SHALL be injected by the backend at the request entry point and SHALL NOT be supplied by request body, prompt, summary, or Memory. Any principal field carried in a request body or LLM output SHALL be ignored or rejected.

#### Scenario: Principal injected server-side
- **WHEN** a request body carries a `principal` field and the backend has a server-injected principal for the session
- **THEN** the system ignores the request-supplied principal field
- **AND** uses the server-injected principal for all durable state binding and authorization context

#### Scenario: Prompt injection cannot supply principal
- **WHEN** an LLM output or prompt summary contains a principal identifier
- **THEN** the system rejects the LLM-supplied principal identifier
- **AND** the server-injected principal remains authoritative

### Requirement: Durable state binds principal
Each durable Run, Approval, and ConversationState SHALL bind to a `principalId`. The `principalId` SHALL be recorded at durable state creation time and SHALL NOT be mutable after creation.

#### Scenario: Run created with principal
- **WHEN** a new agent run is created
- **THEN** the durable Run record stores the `principalId` of the server-injected principal
- **AND** the `principalId` is immutable for the lifetime of the run

#### Scenario: Approval binds principal
- **WHEN** an approval record is created for a run
- **THEN** the durable Approval record stores the `principalId` bound to the run
- **AND** the approval is scoped to that principal

### Requirement: Cross-principal isolation
The system SHALL isolate durable state by principal. Principal A SHALL NOT read, continue, or approve principal B's runs, approvals, or sessions. Cross-principal access SHALL fail-closed.

#### Scenario: Cross-principal access denied
- **WHEN** principal A attempts to read or continue a run owned by principal B
- **THEN** the system denies the access (fail-closed)
- **AND** no principal B durable state is returned to principal A

### Requirement: Local placeholder principal
The system SHALL provide a local single-user placeholder principal for v1 local-first operation. The placeholder principal SHALL be the default server-injected principal when no remote authentication is configured. Authentication runtime (remote authn, token validation) is a non-goal for this change.

#### Scenario: Local dev uses placeholder principal
- **WHEN** the backend runs in local-first mode without remote authentication configured
- **THEN** the system injects the local placeholder principal (fixed `principalId`)
- **AND** all durable state binds to the placeholder principal
- **AND** the principal injection interface remains extensible for future remote authentication

```

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

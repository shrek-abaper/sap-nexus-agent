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

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

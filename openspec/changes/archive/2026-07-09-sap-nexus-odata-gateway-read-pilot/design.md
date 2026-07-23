## Context

当前 SAP Nexus Agent 的 read 路径只有一条能力 `MM.Inventory.GetAvailability`，executor 仅 `JCO_RFC`，`agent/capability_selector.py` 是单能力硬门（`intent != "inventory_availability"` 一律 `UNSUPPORTED_INTENT`），返回标量 `availableQuantity`。Gateway 侧（`gateway-jco/`，Spring Boot 3.3.6）已落地统一技术执行契约：`TechnicalExecutionDispatcher` 按 `bindingId` + executor type 路由到 `TechnicalAdapter`，现有 `JcoRfcTechnicalAdapter` 是唯一 adapter；`ODATA`/`CDS_ADT`/`CDS_ODATA`/`REST_JSON`/`SQL_READ` 在 dispatcher 中 fail-closed。Registry 的 ODATA binding schema 已可校验（registry-ontology-contract），但无任何 ODATA 条目。roadmap §9.3 把 OData Gateway Read Pilot 列为 Phase 4D Reserved，并指向 `sap-skill-create/skills-production/sap-sto-create` 的 OData 客户端经验（session/CSRF/`sap-client`/JSON error 归一）。

本 change 提前 Phase 4D，以采购订单列表查询 `MM.PurchaseOrder.GetList` 作为首个 ODATA 能力，验证多 executor 类型注册、多能力跨 executor 路由、列表结果归一。SAP 侧已有 live PO OData 服务可联调。

## Goals / Non-Goals

**Goals:**
- 新建 OData 只读 executor adapter，复用现有 `TechnicalExecutionDispatcher`/`TechnicalExecutionRequest`/`TechnicalExecutionResult`/`TechnicalRedactor`/trace 基建。
- 注册首个 ODATA 能力 `MM.PurchaseOrder.GetList`（4 过滤参数，列表输出）。
- `capability_selector` 从单能力硬门演进为多能力跨 executor 路由（Agent 不感知 executor 类型，仍只认 `capabilityId` 闭集）。
- 列表型 `ExecutionResult` -> 多条 `ReasoningFact` -> grounded narrative 归一。
- live SAP OData 联调可出真实执行证据（非硬编码 fake）。

**Non-Goals:**
- OData write / deep insert / STO create（read-only pilot）。
- `CDS_ADT`/`CDS_ODATA`/`REST_JSON`/`SQL_READ` executor runtime。
- SAP WRITE 路径。
- PO `GetDetail`（仅 GetList 列表）。
- OData `$skip` 翻页（第一版仅 `$top` 上限 + `$count`）。
- 不改 inventory JCO 既有路径行为。

## Decisions

### 决策 1：Gradle 多模块重构 -- `gateway-odata` 作为对等连接器网关，单端点单进程

将当前根目录单模块 `gateway-jco/` 重构为 `services/gateway/` 父目录下的 Gradle 多模块，使 OData 连接器与 JCo 连接器对等抽象：

```
gateway/
├── settings.gradle        # Gradle 根：include core, jco, odata, app；rootProject.name = 'sap-nexus-gateway'
├── build.gradle
├── core/                  # gateway-core：TechnicalExecution 契约、TechnicalExecutionDispatcher、TechnicalRedactor、Trace、Registry、CapabilityController、CapabilityValidationService
├── jco/                   # gateway-jco：JcoRfcTechnicalAdapter + JCo destination/auth（现有代码迁入）
├── odata/                 # gateway-odata：ODataTechnicalAdapter + HTTP/CSRF/session/auth/JSON 归一（新建）
└── app/                   # gateway-app：Spring Boot 启动模块，组装 core+jco+odata，单端点（:8080）暴露
```

- **路由**：Agent 仍单端点、只认 `capabilityId`（不变）；`gateway-core` 的 `TechnicalExecutionDispatcher` 按 executor type 路由到 jco/odata 连接器。
- **理由**：满足"`gateway-odata` 与 `gateway-jco` 对等、连接器抽象、鉴权通信内聚"的期望；同时保持 Agent 单端点不感知 executor 类型，不破坏既有 `gateway-execution-contract` 契约。
- **备选（rejected）**：① OData adapter 放在 `gateway-jco/` 包内--不符合"对等独立网关"期望；② `gateway-jco` 与 `gateway-odata` 各自独立进程/端口--需前置路由器或 Agent 多端点，后者会泄露 executor 类型给 Agent，破坏"只认 `capabilityId`"原则。
- **重构边界**：现有根目录 `gateway-jco/` 内容迁入 `services/gateway/jco/`；从其抽出 `services/gateway/core/`（契约/dispatcher/redactor/trace/registry/controller）；既有 JCo 行为与 `/capabilities/{capabilityId}/validate|execute` API 契约不变，既有 inventory 回归全绿。

### 决策 2：CSRF/session 策略借鉴 `sap-sto-create`

OData read 第一版以 GET 为主。SAP OData read GET 通常不要求 CSRF token（CSRF 主要约束 write）；session/destination 经环境配置注入，不进 Registry/git/trace。若 live 服务要求 CSRF，按 `sap-sto-create` 的 token 获取 + 刷新模式实现，token 经 `TechnicalRedactor` redact。

- **备选（rejected）**：第一版就实现完整 CSRF + session 池--过度设计，read-only GET 多数场景不需要。

### 决策 3：4 过滤参数 -> OData `$filter`，"至少一个过滤条件"守卫

`MM.PurchaseOrder.GetList` 的 4 参数（PO 号 / 供应商 / 工厂或采购组 / 物料）映射为 OData `$filter`。第一版 4 参数全 optional，但**至少一个**过滤条件，否则 `MISSING_PARAMETER` 澄清（避免全表扫描与 SAP 负载）。

- **理由**：PO 列表无过滤会触发大结果集，违反 read-only pilot 低风险边界。
- **字段名对齐**：`$filter` 字段名（如 `PurchaseOrder`/`Supplier`/`Plant`/`Material`）以 live SAP OData 服务实际 entitySet schema 为准，design 阶段 spike 确认。

### 决策 4：`capability_selector` 改为 intent->capabilityId 映射 + 闭集校验

从硬编码 `if intent != "inventory_availability"` 改为映射表驱动：`inventory_availability` -> `MM.Inventory.GetAvailability`，`purchase_order_list` -> `MM.PurchaseOrder.GetList`。Agent 侧不感知 executor 类型（JCO_RFC/ODATA），executor 路由由 Gateway binding dispatcher 处理。保留闭集校验与 `UNSUPPORTED_INTENT`/`MISSING_PARAMETER`/`UNSUPPORTED_RFC_NAME` 语义。

- **理由**：验证"能力增长路径"--新能力只需在 intent 映射 + Registry 注册，不改 selector 核心逻辑。
- **LLM 路由**：本 change 保持规则路由；hybrid LLM adapter 仍作 advisory，经同样闭集校验。

### 决策 5：列表结果归一为数组 `ReasoningFact`

`ExecutionResult.outputs.purchaseOrders` 为数组。每条 PO 行归一为一条 `ReasoningFact`（`predicate=purchaseOrderItem`，`deterministic=true`，evidence 字段为 PO 号/供应商/物料/工厂/数量/单位）。Narrator 逐项 grounded；空列表输出"无匹配记录"（非错误）。

- **理由**：对标库存标量 `availableQuantity` 的归一路径，验证列表型 evidence 链路。

### 决策 6：分页仅 `$top` 上限 + `$count`

第一版用 `$top` 限上限（如 50/100），`$count` 返回总数，不实现 `$skip` 翻页。超限在 narrative 中说明"仅返回前 N 条"。

- **备选（rejected）**：完整 `$skip`/`$top` 翻页--复杂度高，read-only pilot 不需要。

### 决策 7：redaction 边界

OData destination base URL / token / cookie / authorization header 经 `TechnicalRedactor` redact，不进 `TechnicalExecutionResult`/trace/log/响应。Registry 只存 `serviceRef`（逻辑引用）/`entitySet`/`$filter` mapping 等非敏感 metadata；真实 base URL 与 credentials 经环境/credentialRef。

## Risks / Trade-offs

- **[Risk] live SAP OData 服务 schema 与假设不符**（字段名/filter 语义）-> Mitigation: design 阶段 spike 确认 serviceRef/entitySet 实际 schema；mock 回归隔离 live 依赖。
- **[Risk] `capability_selector` 改动影响 inventory 回归** -> Mitigation: 保留 `inventory_availability` 路径行为不变，增量加 PO 路由；inventory eval 全量回归。
- **[Risk] 多模块重构破坏既有 JCo 路径** -> Mitigation: 重构第一步只拆模块、不改行为；`cd services/gateway/app && gradle test`（或 `cd services/gateway && gradle test`）全绿（含既有 JCo + dispatcher + redactor + controller 测试）后才继续；`services/gateway/app` 组装 `services/gateway/core`+`services/gateway/jco` 即可独立运行。
- **[Risk] OData 大结果集体积** -> Mitigation: `$top` 上限；列表明文不进 trace（trace 只记 count + bindingId）。
- **[Risk] CSRF 实际需要但未实现** -> Mitigation: live 联调时验证；若需要，按决策 2 补 CSRF。
- **[Trade-off] 多模块重构增加本次 change 规模** -> 但这是"对等独立网关"期望的必要前置；重构后 `gateway-core`/`gateway-jco`/`gateway-odata`/`gateway-app` 结构为后续 `CDS_ADT`/`REST_JSON` 等 executor pilot 提供可复用骨架。
- **[Trade-off] §17.2 "不新增 executor family" 被超越** -> 经用户确认；本 change 显式新增 ODATA family，roadmap/runbook closeout 记录。

## Migration Plan

增量推进，每步可独立验证、可回滚：

1. **Gateway 多模块重构**：新建 `services/gateway/` 父目录（Gradle 根）；现有根目录 `gateway-jco/` 内容迁入 `services/gateway/jco/`；抽出 `services/gateway/core/`（契约/dispatcher/redactor/trace/registry/controller）；新建 `services/gateway/odata/` 空模块骨架与 `services/gateway/app/` 启动模块；既有 JCo 行为与 API 契约不变，inventory 回归全绿。
2. **Registry**：新增 ODATA executor binding + `MM.PurchaseOrder.GetList` capability entry（先 inactive 或 gated）。
3. **Gateway OData 连接器**：在 `gateway-odata/` 实现 `ODataTechnicalAdapter` + HTTP/CSRF/session/auth/JSON 归一；dispatcher 注册 `ODATA` 路由；unit test 用 mock OData 响应。
4. **Agent intent**：新增 PO 关键词 + `purchase_order_list` intent。
5. **Agent selector**：改映射表路由；inventory 回归。
6. **Agent 结果归一**：列表 `ExecutionResult` -> `ReasoningFact` 数组 -> narrative。
7. **Evals**：PO OData seed cases（mock 回归 + live 联调 gated）。
8. **live 联调验证**（gated by env flag，默认 skip）。

**回滚**：ODATA capability 在 Registry 置 `status=inactive` 即下线，不影响 inventory JCO 路径；多模块重构若出问题，`gateway-app` 仍组装 `gateway-core`+`gateway-jco`，OData 模块可移除。

## Open Questions

1. PO OData service 具体 `serviceRef`/`entitySet`（如 `MM_PUR_PO` / `API_PURCHASEORDER_PROCESS_SRV` / CDS-based service）--需 SAP 侧确认。
2. `$filter` 字段名与 live 服务 entitySet schema 对齐--design 阶段 spike。
3. `$top` 上限取值（50/100/200）。
4. live 联调 destination 配置来源（环境变量 / credentialRef / sap-sto-create 式配置）。
5. 是否真需 CSRF（GET read 多数不需要，需 live 验证）。
6. PO 行暴露字段集（PO号/供应商/物料/工厂/数量/单位/交货日期）最终范围。

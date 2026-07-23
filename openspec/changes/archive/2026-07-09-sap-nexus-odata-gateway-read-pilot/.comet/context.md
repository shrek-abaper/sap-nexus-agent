# Comet Design Handoff

- Change: sap-nexus-odata-gateway-read-pilot
- Phase: design
- Mode: compact
- Context hash: 49e39d46f87f905aff4545c6bd79a1210668cf0d732f6c3dfc8d342e651a87c7

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/sap-nexus-odata-gateway-read-pilot/proposal.md

- Source: openspec/changes/sap-nexus-odata-gateway-read-pilot/proposal.md
- Lines: 1-36
- SHA256: 8c70ad0ba13f1cb5acdc63f1661afe572f276cc32ec33bd66897f98ac97c2805

```md
## Why

当前 SAP read 路径只有 `MM.Inventory.GetAvailability` 一条能力，executor 仅 `JCO_RFC`，`capability_selector` 是单能力硬门（非 `inventory_availability` 一律 `UNSUPPORTED_INTENT`）。再做一条 JCO-PO 只会复用已证明的 JCo executor，验证增量有限。本 change 提前 Phase 4D OData Gateway Read Pilot，以采购订单列表查询作为首个 `ODATA` 能力，验证三个新维度：多 executor 类型能力注册（`JCO_RFC` + `ODATA` 共存）、`capability_selector` 从单能力硬门演进为多能力跨 executor 路由、列表型结果归一（PO 多行 -> 数组输出，对标库存的标量输出）。SAP 侧已有 live PO OData 服务可联调，可出真实执行证据。

## What Changes

- 新建 OData Gateway read-only 连接器模块 `gateway/odata/`：HTTP client + CSRF token + session + `sap-client` + JSON error 归一 + sensitive redaction + trace，借鉴 `sap-skill-create/skills-production/sap-sto-create` 的 OData 客户端经验。鉴权与通信全内聚于本模块，参数组装在 Agent 侧。
- Gradle 多模块重构：新建 `gateway/` 父目录（Gradle 根），从现有 `gateway-jco/` 抽出 `gateway/core/`（共享契约/dispatcher/redactor/trace/registry/controller），JCo 连接器迁入 `gateway/jco/`，新建 `gateway/odata/`，`gateway/app/` 组装单端点单进程；Agent 仍只认 `capabilityId`，不感知 executor 类型。
- 注册首个 `ODATA` 能力 `MM.PurchaseOrder.GetList`：采购订单列表查询，4 个过滤参数（PO 号 EBELN / 供应商 / 工厂或采购组 / 物料），列表输出。
- `agent/capability_selector.py` 从单能力硬门演进为多能力跨 executor 路由（`inventory_availability` -> `JCO_RFC`，`purchase_order_list` -> `ODATA`）。
- `agent/intent.py` 新增 PO 关键词（采购订单 / PO / 订单）与 `intent="purchase_order_list"`，保留 hybrid LLM adapter 兜底。
- 列表型 `ExecutionResult` 与 `ReasoningFact` 归一：PO 行数组映射为多条 grounded `ReasoningFact`，Narrator 逐项引用。
- `registry/executor-bindings.yaml` 新增首条 ODATA binding（`serviceRef` / `entitySet` / `$filter` mapping 等非敏感 metadata）。
- `gateway-execution-contract`：`ODATA` executor 类型不再 fail-closed，dispatcher 路由到 OData adapter。
- 新增 PO OData eval seed cases（live 联调 + mock 回归）。
- **非目标**：OData write / deep insert / STO create；`CDS_ADT` / `CDS_ODATA` / `REST_JSON` / `SQL_READ` executor；SAP WRITE 路径；PO `GetDetail`。

## Capabilities

### New Capabilities

- `odata-gateway-read`: OData Gateway 只读 executor 契约——CSRF/session/`$filter`/JSON 响应归一/redaction/trace 产出标准 `ExecutionResult`；read-only 边界；不接受 caller 提供的裸 OData URL/service/endpoint；Registry 只保存 `serviceRef`/`entitySet` 等非敏感 binding metadata。

### Modified Capabilities

- `gateway-execution-contract`: `ODATA` executor 类型由 fail-closed 改为有 runtime adapter，dispatcher 将 ODATA binding 路由到 OData adapter；其余 reserved executor（`CDS_ADT`/`CDS_ODATA`/`REST_JSON`/`SQL_READ`）仍 fail-closed。
- `agent-callplan-evidence`: 能力选择从单能力闭集扩展为多能力跨 executor 路由（`JCO_RFC` + `ODATA`）；新增 PO 意图解析；`ExecutionResult`/`ReasoningFact` 支持列表型结果归一。

## Impact

- 受影响代码：Gateway 多模块重构（`gateway/core`/`gateway/jco`/`gateway/odata`/`gateway/app`，新建 OData 连接器 + dispatcher 路由扩展）、`agent/intent.py`、`agent/capability_selector.py`、`agent/call_plan.py`、`agent/gateway_client.py`、`agent/execution_result.py`、`agent/narrator.py`、`agent/reasoning_fact.py`。
- 受影响 registry：`registry/capabilities.yaml`（新增 ODATA 能力）、`registry/executor-bindings.yaml`（首条 ODATA binding）。
- 受影响契约：`gateway-execution-contract`（ODATA 不再 fail-closed）、`agent-callplan-evidence`（多能力路由 + 列表结果）。
- 受影响验证：Gateway 测试、Registry contract 校验、Agent CallPlan/evidence 回归、新增 PO OData eval、OpenSpec strict validation。
- Roadmap 影响：激活 row 14 `sap-nexus-odata-gateway-read-pilot`（原 Reserved）；row 9 `sap-nexus-second-sap-read-capability` 由本 change 隐式满足；显式超越 §17.2 "不新增 executor family"（本 change 新增 ODATA family，经用户确认）；§17.4 顺序调整（OData pilot 前置于 sandbox write pilot）。
- 不预期破坏现有 inventory JCO 路径与 Workbench。

```

## openspec/changes/sap-nexus-odata-gateway-read-pilot/design.md

- Source: openspec/changes/sap-nexus-odata-gateway-read-pilot/design.md
- Lines: 1-113
- SHA256: 2c799fcef7f40f6480b67fe0aab1441bb2cf53a69c890aac3b1095cf75d6eccb

[TRUNCATED]

```md
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

将当前根目录单模块 `gateway-jco/` 重构为 `gateway/` 父目录下的 Gradle 多模块，使 OData 连接器与 JCo 连接器对等抽象：

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
- **重构边界**：现有根目录 `gateway-jco/` 内容迁入 `gateway/jco/`；从其抽出 `gateway/core/`（契约/dispatcher/redactor/trace/registry/controller）；既有 JCo 行为与 `/capabilities/{capabilityId}/validate|execute` API 契约不变，既有 inventory 回归全绿。

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


```

Full source: openspec/changes/sap-nexus-odata-gateway-read-pilot/design.md

## openspec/changes/sap-nexus-odata-gateway-read-pilot/tasks.md

- Source: openspec/changes/sap-nexus-odata-gateway-read-pilot/tasks.md
- Lines: 1-74
- SHA256: 19f252fe0d591586aa088790b3cb98d015ed22a281f0200ac404f023ba301095

```md
## 1. Gateway 多模块重构（前置）

- [ ] 1.1 新建 `gateway/` Gradle 多模块：`gateway/core`、`gateway/jco`、`gateway/odata`、`gateway/app`，`gateway/settings.gradle` 与各模块 `build.gradle`（`rootProject.name = 'sap-nexus-gateway'`）
- [ ] 1.2 从现有根目录 `gateway-jco/` 抽出 `gateway/core/`：`TechnicalExecutionRequest`/`Result`、`TechnicalAdapter`、`TechnicalExecutionDispatcher`、`TechnicalRedactor`、`Trace*`、`registry/*`、`api/CapabilityController`/`CapabilityValidationService`/`CapabilityResponse`
- [ ] 1.3 JCo 连接器代码迁入 `gateway/jco/` 模块：`JcoRfcTechnicalAdapter`、`JcoCapabilityExecutor`、`JcoDestination*`、`InventoryAvailabilityExecutor`、`InMemoryDestinationDataProvider`
- [ ] 1.4 新建 `gateway/app/` Spring Boot 启动模块，组装 `gateway/core`+`gateway/jco`（+预留 `gateway/odata`），单端点 `:8080`
- [ ] 1.5 `gateway/core` 的 `TechnicalExecutionDispatcher` 改为按 executor type 路由的 adapter 注册表（替换 `CapabilityController` 内联硬编码 `JCO_RFC` map）
- [ ] 1.6 `cd gateway && gradle test` 全绿（含既有 JCo + dispatcher + redactor + controller 测试），inventory 回归不变

## 2. Registry: ODATA 能力与 binding 注册

- [ ] 2.1 在 `registry/executor-bindings.yaml` 新增首条 ODATA executor binding（`serviceRef`/`entitySet`/`$filter` mapping/`$top` 上限，仅非敏感 metadata）
- [ ] 2.2 在 `registry/capabilities.yaml` 新增 `MM.PurchaseOrder.GetList` capability entry（executor type `ODATA`，4 过滤参数，列表输出 `purchaseOrders`，governance read-only/`not_required`）
- [ ] 2.3 运行 `.venv/bin/python scripts/validate-registry-contract.py registry/capabilities.yaml` 确认 ODATA binding 校验通过
- [ ] 2.4 运行 `.venv/bin/python -m pytest agent/tests/test_registry_contract.py -v` 确认 registry contract 回归通过

## 3. Gateway: OData 连接器与 dispatcher

- [ ] 3.1 在 `gateway/odata/` 新增 `ODataTechnicalAdapter`（implements `TechnicalAdapter`），实现 OData read 请求构建（`serviceRef`/`entitySet`/`$filter`/`$top`/`$count`）
- [ ] 3.2 在 `gateway/core` 的 `TechnicalExecutionDispatcher` 注册 `ODATA` executor type -> `ODataTechnicalAdapter` 路由
- [ ] 3.3 `gateway/odata/` 内 OData HTTP client 实现（GET read，`sap-client` header，session/destination 经环境注入，CSRF 按需）--鉴权与通信全内聚于本模块
- [ ] 3.4 OData JSON 响应归一为 `TechnicalExecutionResult`（列表输出 + count + redaction status）
- [ ] 3.5 经 `gateway/core` 的 `TechnicalRedactor` redact destination URL/token/cookie/authorization header
- [ ] 3.6 拒绝 caller 提供的裸 OData URL/endpoint/`$filter`/method/header/credential override（请求所有权守卫）
- [ ] 3.7 unit test：mock OData 响应覆盖正常列表/空列表/HTTP error/JSON 异常/redaction
- [ ] 3.8 `cd gateway && gradle test` 通过（含 dispatcher 新 ODATA 场景 + 既有 JCO 回归）

## 4. Agent: PO 意图解析

- [ ] 4.1 `agent/intent.py` 新增 PO 关键词（采购订单/PO/订单）与 `intent="purchase_order_list"`
- [ ] 4.2 解析 4 过滤参数（PO 号/供应商/工厂或采购组/物料）为 `parameters`
- [ ] 4.3 "至少一个过滤条件"守卫：无过滤 -> `missing_parameters` + clarification
- [ ] 4.4 拒绝裸 OData URL/service/`$filter`（扩展 `contains_rfc_name` 或等价机制）
- [ ] 4.5 unit test：PO 意图解析覆盖单参/多参/无参澄清/裸 endpoint 拒绝/与库存意图区分

## 5. Agent: 多能力跨 executor 路由

- [ ] 5.1 `capability_selector.py` 从硬编码单 intent 改为 intent->capabilityId 映射表 + 闭集校验
- [ ] 5.2 `inventory_availability` -> `MM.Inventory.GetAvailability`，`purchase_order_list` -> `MM.PurchaseOrder.GetList`
- [ ] 5.3 保留 `UNSUPPORTED_INTENT`/`MISSING_PARAMETER`/`UNSUPPORTED_RFC_NAME` 语义
- [ ] 5.4 Agent 不感知 executor 类型（`JCO_RFC`/`ODATA`），由 Gateway dispatcher 处理
- [ ] 5.5 unit test：selector 多能力路由 + 未知 intent 拒绝 + LLM 闭集校验

## 6. Agent: 列表结果归一与 narrative

- [ ] 6.1 `execution_result.py` 支持列表型输出（`purchaseOrders` 数组）
- [ ] 6.2 `call_plan.py` / `gateway_client.py` 适配 PO capability 的 CallPlan 与 Gateway execute
- [ ] 6.3 `reasoning_fact.py`：列表项归一为多条 `ReasoningFact`（`predicate=purchaseOrderItem`）
- [ ] 6.4 `narrator.py`：逐项 grounded narrative；空列表输出"无匹配记录"；超限说明"仅前 N 条"
- [ ] 6.5 narrator guard：拒绝输出 facts 中不存在的字段
- [ ] 6.6 unit test：列表归一 + 空 + 超限 + guard 失败

## 7. Evals: PO OData seed cases

- [ ] 7.1 `evals/` 新增 PO OData seed cases（核心成功/参数补全/多参 `$filter`/意图区分跨 executor/裸 endpoint 拒绝/列表归一/空结果/redaction）
- [ ] 7.2 mock 回归默认运行（不依赖 live SAP）
- [ ] 7.3 live 联调 case gated by env flag，默认 skip
- [ ] 7.4 `scripts/verify-agent-callplan-evidence.sh` 纳入 PO seed eval
- [ ] 7.5 `.venv/bin/python -m sap_nexus_agent.eval` 通过 PO seed

## 8. live 联调与验证

- [ ] 8.1 收敛 design open question：确认 PO OData service `serviceRef`/`entitySet` + `$filter` 字段名
- [ ] 8.2 live SAP OData 联调（gated env），确认真实 `ExecutionResult` + trace（非硬编码）
- [ ] 8.3 确认 redaction：destination/token/cookie 不进 trace/log/响应

## 9. Comet closeout

- [ ] 9.1 `git status --short` 确认改动范围
- [ ] 9.2 `openspec validate --all --strict` 通过
- [ ] 9.3 `scripts/verify-agent-callplan-evidence.sh` 全量通过
- [ ] 9.4 更新 `docs/runbooks/README.md` 与新建/更新对应 runbook
- [ ] 9.5 更新 `docs/wiki/sap-nexus-agent-implementation-roadmap.md`（激活 row 14，记录 §17.2 超越与 §17.4 顺序调整）
- [ ] 9.6 运行归档脚本 `node "$COMET_ARCHIVE" sap-nexus-odata-gateway-read-pilot`

```

## openspec/changes/sap-nexus-odata-gateway-read-pilot/specs/agent-callplan-evidence/spec.md

- Source: openspec/changes/sap-nexus-odata-gateway-read-pilot/specs/agent-callplan-evidence/spec.md
- Lines: 1-64
- SHA256: 0974edb7b57e70679244f27b64acaa81dda60c53d592c9ebfa3e36f605755109

```md
## MODIFIED Requirements

### Requirement: Closed-set capability selection
The system SHALL select capabilities only from the Registry closed set and MUST reject unsupported intent before Gateway execution. The selector SHALL route recognized intents to their registered capability IDs across executor types (for example `inventory_availability` -> `MM.Inventory.GetAvailability` via `JCO_RFC`, `purchase_order_list` -> `MM.PurchaseOrder.GetList` via `ODATA`) without the Agent needing to know the executor type or binding at selection time. LLM-assisted selection MUST be constrained to the same closed set and MUST NOT introduce new executable capability IDs.

#### Scenario: Route inventory intent to inventory capability
- **WHEN** the rule parser identifies `inventory_availability` intent with required `material` and `plant`
- **THEN** the Agent selects `capabilityId=MM.Inventory.GetAvailability` and proceeds to CallPlan and Gateway validation
- **AND** the Agent does not choose an executor type or binding at selection time

#### Scenario: Route purchase order intent to purchase order capability
- **WHEN** the rule parser identifies `purchase_order_list` intent with at least one filter parameter
- **THEN** the Agent selects `capabilityId=MM.PurchaseOrder.GetList` and proceeds to CallPlan and Gateway validation
- **AND** the Agent does not choose an executor type or binding at selection time

#### Scenario: LLM selects registered capability only
- **WHEN** the LLM returns `capabilityId=MM.Inventory.GetAvailability` or `capabilityId=MM.PurchaseOrder.GetList` with required parameters
- **THEN** the Agent accepts the candidate only after deterministic validation confirms the closed-set capability

#### Scenario: LLM returns unknown capability
- **WHEN** the LLM returns an unknown or unsupported `capabilityId`
- **THEN** the Agent rejects that LLM output for execution and does not call Gateway validate or execute from it

## ADDED Requirements

### Requirement: Purchase order list intent parsing
The system SHALL parse Chinese purchase order list queries for `MM.PurchaseOrder.GetList` into normalized intent parameters without using free-form RFC names or raw OData endpoints. The parser MAY use the real LLM intent adapter before deterministic validation, but the LLM output is advisory and MUST be normalized into the same closed-set intent contract before capability selection.

#### Scenario: Parse purchase order query with vendor filter
- **WHEN** the user asks `查供应商 DEMOV1 的采购订单`
- **THEN** the Agent identifies `purchase_order_list` intent and extracts `vendor=DEMOV1`
- **AND** the Agent proceeds through deterministic closed-set capability selection before Gateway validation

#### Scenario: Parse purchase order query with multiple filters
- **WHEN** the user asks `查工厂 1000 物料 MAT001 的采购订单`
- **THEN** the Agent identifies `purchase_order_list` intent and extracts plant and material parameters
- **AND** the Agent maps the parameters to the registered `$filter` fields through the capability contract, not by emitting a raw OData `$filter` string

#### Scenario: Clarify missing filter before Gateway call
- **WHEN** the user asks `帮我看看采购订单` without any of PO number, vendor, plant/purchasing group, or material
- **THEN** the Agent returns a Chinese clarification asking for at least one filter parameter
- **AND** the Agent does not call Gateway validate or execute

#### Scenario: Reject raw OData endpoint in user or LLM input
- **WHEN** the user or LLM output contains a raw OData URL, service path, or `$filter` string
- **THEN** the Agent treats the input as untrusted and does not execute from it
- **AND** Gateway validate and execute are not called unless a safe fallback parser independently produces a valid closed-set capability request

### Requirement: List execution result to reasoning facts
The system SHALL convert a successful list-shaped `ExecutionResult` into one or more deterministic `ReasoningFact` entries before narration, with one fact per returned item, and MUST narrate list results only from fields present in those facts.

#### Scenario: Successful list execution creates per-item facts
- **WHEN** Gateway execute returns success with a non-empty `purchaseOrders` array for `MM.PurchaseOrder.GetList`
- **THEN** the Agent creates one `ReasoningFact` per purchase order item with `predicate=purchaseOrderItem`, `deterministic=true`, `confidence=1.0`, source capability metadata, and per-item evidence fields
- **AND** the Chinese narrative cites only those item fields present in the facts and does not invent additional records

#### Scenario: Empty list execution creates no item facts
- **WHEN** Gateway execute returns success with an empty `purchaseOrders` array for a valid filter
- **THEN** the Agent does not create per-item facts that claim records exist
- **AND** the Chinese narrative states that no matching purchase orders were found

#### Scenario: Narrator rejects list item values not present in facts
- **WHEN** the narrator is asked to output a PO number, vendor, or quantity that is not present in any `ReasoningFact`
- **THEN** the Agent returns or raises a narrative guard failure instead of inventing the value

```

## openspec/changes/sap-nexus-odata-gateway-read-pilot/specs/gateway-execution-contract/spec.md

- Source: openspec/changes/sap-nexus-odata-gateway-read-pilot/specs/gateway-execution-contract/spec.md
- Lines: 1-24
- SHA256: 67adedbab31a19484a2efdcf3f37a3cdfe6d140167939c3e0d297a6eb5059d9d

```md
## MODIFIED Requirements

### Requirement: Dispatcher executes only allowlisted bindings

The Gateway MUST resolve technical execution through a closed dispatcher that maps registered `bindingId` and executor type to an allowed adapter. The dispatcher SHALL route `JCO_RFC` bindings to the JCo adapter and `ODATA` bindings to the OData adapter; contract-recognized executor types without an implemented runtime adapter MUST fail closed.

#### Scenario: Dispatch current JCO_RFC binding

- **WHEN** the registered inventory binding resolves to executor type `JCO_RFC`
- **THEN** the dispatcher invokes the controlled JCo adapter for the current inventory read path
- **AND** the adapter uses the registered binding metadata rather than arbitrary runtime RFC selection

#### Scenario: Dispatch ODATA binding to OData adapter

- **WHEN** the registered purchase order binding resolves to executor type `ODATA`
- **THEN** the dispatcher invokes the controlled OData adapter for the registered `serviceRef` and `entitySet`
- **AND** the adapter uses the registered binding metadata rather than arbitrary runtime OData URL or endpoint selection
- **AND** the OData adapter normalizes the response into the same technical execution result contract used by the JCo adapter

#### Scenario: Fail closed for unsupported future executor

- **WHEN** a registered binding uses `CDS_ADT`, `CDS_ODATA`, `REST_JSON`, `SQL_READ`, or another contract-recognized executor without an implemented runtime adapter in this change
- **THEN** the dispatcher returns a deterministic fail-closed technical result
- **AND** the Gateway does not attempt arbitrary HTTP, ADT, CDS, REST, SQL, or RFC execution

```

## openspec/changes/sap-nexus-odata-gateway-read-pilot/specs/odata-gateway-read/spec.md

- Source: openspec/changes/sap-nexus-odata-gateway-read-pilot/specs/odata-gateway-read/spec.md
- Lines: 1-83
- SHA256: 12bf78f49ee222b0b3d996bbe7b4098c8927c9b7b713ef9b954b2b362f17e753

[TRUNCATED]

```md
## ADDED Requirements

### Requirement: OData read-only execution via registered binding

The Gateway SHALL execute OData read capabilities through a registered `ODATA` executor binding, resolving `serviceRef`, `entitySet`, and `$filter` mapping from binding metadata without accepting caller-provided OData URLs, service paths, endpoints, HTTP methods, headers, or credentials.

#### Scenario: Execute OData purchase order list query

- **WHEN** a valid capability execution request is accepted for `MM.PurchaseOrder.GetList` with at least one filter parameter
- **THEN** the Gateway builds an OData read request using the capability's registered `executorBinding.bindingId`
- **AND** the request resolves `serviceRef`, `entitySet`, and `$filter` from registered binding metadata
- **AND** the request does not use caller-provided OData URL, service path, endpoint, HTTP method, header, or credential fields

#### Scenario: Reject raw OData endpoint override

- **WHEN** a caller includes a raw OData URL, service path, entity set, `$filter` string, HTTP method, header, or credential override
- **THEN** the Gateway rejects or ignores those fields before OData adapter execution
- **AND** no arbitrary OData HTTP call is attempted with caller-owned technical details

### Requirement: OData parameter to filter mapping

The Gateway SHALL map registered capability filter parameters to OData `$filter` expressions according to binding metadata, and MUST enforce the capability's parameter required/optional and "at-least-one-filter" semantics before execution.

#### Scenario: Map multiple filter parameters into one OData query

- **WHEN** `MM.PurchaseOrder.GetList` is executed with `vendor` and `material` parameters
- **THEN** the OData adapter builds a single `$filter` expression combining both parameters using the binding's field mapping
- **AND** the request is sent to the registered `entitySet` with the combined filter

#### Scenario: Reject purchase order list without any filter

- **WHEN** `MM.PurchaseOrder.GetList` is selected with no filter parameter supplied
- **THEN** the Agent returns a `MISSING_PARAMETER` clarification asking for at least one of PO number, vendor, plant/purchasing group, or material
- **AND** the Agent does not call Gateway validate or execute

### Requirement: OData list result normalization

The Gateway SHALL normalize OData response entity collections into a capability-level `ExecutionResult` with a list output field, preserving `traceId`, `bindingId`, count, and per-item structured fields without exposing raw OData JSON, credentials, or destination details.

#### Scenario: Normalize non-empty OData collection into list execution result

- **WHEN** the OData adapter receives a collection of purchase order items for `MM.PurchaseOrder.GetList`
- **THEN** the capability-level `ExecutionResult` exposes a `purchaseOrders` array with per-item structured fields (PO number, vendor, material, plant, quantity, unit)
- **AND** the result records `traceId`, `bindingId`, item count, duration, and redaction status
- **AND** raw OData JSON payload, destination URL, token, cookie, and authorization header are not exposed

#### Scenario: Normalize empty OData collection as empty list

- **WHEN** the OData adapter receives an empty collection for a valid `$filter`
- **THEN** the capability-level `ExecutionResult` exposes an empty `purchaseOrders` array with `success=true`
- **AND** the result is not treated as a technical failure

#### Scenario: Normalize OData error as deterministic failure

- **WHEN** the OData adapter receives an HTTP error, SAP authorization error, malformed JSON, or connectivity failure
- **THEN** the technical result records `traceId`, `bindingId`, executor type `ODATA`, `success=false`, error type, messages, duration, and redaction status
- **AND** the converted capability-level result uses deterministic error semantics compatible with the current Gateway API

### Requirement: OData read pagination boundary

The Gateway SHALL apply a `$top` upper limit and request `$count` for OData list read capabilities, and MUST NOT implement arbitrary pagination traversal in this change.

#### Scenario: Cap OData list result with top limit

- **WHEN** `MM.PurchaseOrder.GetList` matches more than the configured `$top` limit
- **THEN** the Gateway returns at most the configured maximum number of items
- **AND** the capability-level result or narrative indicates that only the first N items are returned

### Requirement: OData credentials and destination redaction

The Gateway MUST apply sensitive-data redaction at the OData execution boundary so destination config, base URL, token, cookie, authorization header, and credential reference material never appear in response, trace, or log output.

#### Scenario: Redact OData destination and credential material

- **WHEN** an OData technical request, result, trace, or error contains destination base URL, SAP password, token, cookie, authorization header, `.env` content, or credential reference material
- **THEN** the Gateway redacts the sensitive value before returning or writing trace output
- **AND** verification can prove no sensitive value is exposed through normal response, trace, or error paths

#### Scenario: Registry stores only non-sensitive OData binding metadata


```

Full source: openspec/changes/sap-nexus-odata-gateway-read-pilot/specs/odata-gateway-read/spec.md

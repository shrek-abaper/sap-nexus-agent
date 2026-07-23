## Why

当前 SAP read 路径只有 `MM.Inventory.GetAvailability` 一条能力，executor 仅 `JCO_RFC`，`capability_selector` 是单能力硬门（非 `inventory_availability` 一律 `UNSUPPORTED_INTENT`）。再做一条 JCO-PO 只会复用已证明的 JCo executor，验证增量有限。本 change 提前 Phase 4D OData Gateway Read Pilot，以采购订单列表查询作为首个 `ODATA` 能力，验证三个新维度：多 executor 类型能力注册（`JCO_RFC` + `ODATA` 共存）、`capability_selector` 从单能力硬门演进为多能力跨 executor 路由、列表型结果归一（PO 多行 -> 数组输出，对标库存的标量输出）。SAP 侧已有 live PO OData 服务可联调，可出真实执行证据。

## What Changes

- 新建 OData Gateway read-only 连接器模块 `services/gateway/odata/`：HTTP client + CSRF token + session + `sap-client` + JSON error 归一 + sensitive redaction + trace，借鉴 `sap-skill-create/skills-production/sap-sto-create` 的 OData 客户端经验。鉴权与通信全内聚于本模块，参数组装在 Agent 侧。
- Gradle 多模块重构：新建 `services/gateway/` 父目录（Gradle 根），从现有 `gateway-jco/` 抽出 `services/gateway/core/`（共享契约/dispatcher/redactor/trace/registry/controller），JCo 连接器迁入 `services/gateway/jco/`，新建 `services/gateway/odata/`，`services/gateway/app/` 组装单端点单进程；Agent 仍只认 `capabilityId`，不感知 executor 类型。
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

- 受影响代码：Gateway 多模块重构（`services/gateway/core`/`services/gateway/jco`/`services/gateway/odata`/`services/gateway/app`，新建 OData 连接器 + dispatcher 路由扩展）、`agent/intent.py`、`agent/capability_selector.py`、`agent/call_plan.py`、`agent/gateway_client.py`、`agent/execution_result.py`、`agent/narrator.py`、`agent/reasoning_fact.py`。
- 受影响 registry：`registry/capabilities.yaml`（新增 ODATA 能力）、`registry/executor-bindings.yaml`（首条 ODATA binding）。
- 受影响契约：`gateway-execution-contract`（ODATA 不再 fail-closed）、`agent-callplan-evidence`（多能力路由 + 列表结果）。
- 受影响验证：Gateway 测试、Registry contract 校验、Agent CallPlan/evidence 回归、新增 PO OData eval、OpenSpec strict validation。
- Roadmap 影响：激活 row 14 `sap-nexus-odata-gateway-read-pilot`（原 Reserved）；row 9 `sap-nexus-second-sap-read-capability` 由本 change 隐式满足；显式超越 §17.2 "不新增 executor family"（本 change 新增 ODATA family，经用户确认）；§17.4 顺序调整（OData pilot 前置于 sandbox write pilot）。
- 不预期破坏现有 inventory JCO 路径与 Workbench。

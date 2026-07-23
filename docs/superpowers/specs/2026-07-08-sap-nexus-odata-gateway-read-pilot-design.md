---
comet_change: sap-nexus-odata-gateway-read-pilot
role: technical-design
canonical_spec: openspec
archived-with: 2026-07-09-sap-nexus-odata-gateway-read-pilot
status: final
---

# Design Doc: SAP Nexus OData Gateway Read Pilot

- Change: `sap-nexus-odata-gateway-read-pilot`
- Date: 2026-07-08
- Phase: 4D（提前，原 Reserved）
- Canonical spec: `openspec/changes/sap-nexus-odata-gateway-read-pilot/specs/`

本文档是对 open 阶段 `design.md` 高层方案的深度技术细化。架构方向、目标、非目标、范围以 open 阶段产物为准，本文不重写。

## 1. 现状勘察

### 1.1 Agent 侧
- `agent/sap_nexus_agent/gateway_client.py`：单端点 `GatewayClient(base_url=:8080)`，只认 `capabilityId` + parameters，调用 `/capabilities/{capabilityId}/validate|execute`。Agent 不感知 executor 类型。
- `agent/sap_nexus_agent/execution_result.py`：`ExecutionResult.executor` 是 `dict[str, Any]`（泛型，不强制 `rfcName`）--Agent 侧与 executor 解耦。
- `agent/sap_nexus_agent/capability_selector.py`：硬编码 `if intent != "inventory_availability" -> UNSUPPORTED_INTENT`，单能力硬门。
- `agent/sap_nexus_agent/intent.py`：仅 `INVENTORY_KEYWORDS`（库存/可用量/...），无 PO 关键词。

### 1.2 Gateway 侧（`gateway-jco/`，Spring Boot 3.3.6）
- `TechnicalAdapter`（interface）+ `TechnicalExecutionDispatcher`（按 `executorType` 字符串路由到 adapter，未匹配 `UNSUPPORTED_EXECUTOR` fail-closed）。
- `JcoRfcTechnicalAdapter`：唯一 adapter，依赖 `JcoCapabilityExecutor` + `CapabilityDefinition`。
- `TechnicalExecutionRequest`：record(traceId, capabilityId, bindingId, executorType, operation, parameters, constraints, callerContext)。**不含** serviceRef/entitySet/filterMapping。
- `TechnicalExecutionResult`：record(..., data, adapterMetadata) + `toExecutionResult(String rfcName)`。
- `ExecutionResult.ExecutorMetadata(String type, String rfcName)`：`rfcName` 是 JCo 专用字段。
- `CapabilityController.execute`：每次请求内联 `new TechnicalExecutionDispatcher(Map.of("JCO_RFC", new JcoRfcTechnicalAdapter(...)))`，并调用 `technicalResult.toExecutionResult(capability.executor().rfcName())`。
- `TechnicalRedactor`：redact map/text 的敏感值。

### 1.3 Registry 侧
- `registry/capabilities.yaml`：仅 `MM.Inventory.GetAvailability`（executor type `JCO_RFC`，含 `rfcName`）。
- `registry/executor-bindings.yaml`：仅 `sap.mm.inventory.md04-stock-req-list`（JCO_RFC）。
- `scripts/validate_registry_contract.py`：`_require_binding_fields` 按 type 分支校验--JCO_RFC 要求 `rfcName/allowedImports/allowedOutputs`，ODATA 要求 `serviceRef/entitySet/method`。**Registry validator 已支持 ODATA binding，无需改。**

## 2. 深度技术决策

### 2.1 Gradle 多模块重构边界

```
gateway/
├── settings.gradle          # include core, jco, odata, app; rootProject.name = 'sap-nexus-gateway'
├── build.gradle             # 根：spring-boot plugin management / 公共依赖
├── core/
│   └── src/main/java/com/sapnexus/gateway/
│       ├── execution/       # TechnicalExecutionRequest, TechnicalExecutionResult, TechnicalAdapter,
│       │                    # TechnicalExecutionDispatcher, TechnicalRedactor
│       ├── result/          # ExecutionResult, ErrorType, SapReturnMessage, SapReturnNormalizer
│       ├── trace/           # TraceRecord, TraceWriter, TraceConfiguration, TraceProperties
│       ├── registry/        # CapabilityDefinition, CapabilityRegistry, CapabilityRegistryLoader,
│       │                    # CapabilityRegistryValidator, RegistryConfiguration, RegistryProperties,
│       │                    # CapabilityKind, CapabilityStatus, SideEffect, RegistryValidationException
│       ├── validation/      # CapabilityValidationService
│       └── api/             # CapabilityController, CapabilityResponse, CapabilityRequest, HealthController
├── jco/
│   └── src/main/java/com/sapnexus/gateway/jco/
│       ├── JcoRfcTechnicalAdapter.java
│       ├── JcoCapabilityExecutor.java
│       ├── JcoDestinationFactory.java
│       ├── JcoDestinationProperties.java
│       ├── InMemoryDestinationDataProvider.java
│       └── InventoryAvailabilityExecutor.java
├── odata/
│   └── src/main/java/com/sapnexus/gateway/odata/
│       ├── ODataHttpProxyAdapter.java   # 薄反代：HTTP 转发到 Python OData 服务 + JSON 归一
│       └── ODataProxyProperties.java    # Python OData 服务地址等非敏感配置
└── app/
    ├── build.gradle         # spring-boot 插件，bootRun 入口
    └── src/main/java/com/sapnexus/gateway/SapNexusGatewayApplication.java
```

**OData 执行层语言决策（架构修正 2026-07-09）**：OData executor 的真实 HTTP/CSRF/session/JSON 归一逻辑用 **Python** 实现（独立微服务 `services/odata-service/`，:8081），复用 `sap-sto-create` 经验。Java 侧 `services/gateway/odata/` 仅保留**薄反向代理 adapter** `ODataHttpProxyAdapter`（implements `TechnicalAdapter`）：接收 `TechnicalExecutionRequest`，HTTP 转发到 Python 服务，把返回 JSON 归一为 `TechnicalExecutionResult` + redaction。理由：JCo 用 Java 是 `sapjco3.jar` 技术强制，OData 是纯 HTTP 无 Java 绑定理由；编排层已 Python 且有成熟 Python OData 参考。详见 §2.3a。

**模块依赖**：`jco` -> `core`；`odata` -> `core`；`app` -> `core` + `jco` + `odata`。`lib/sapjco3.jar` 仅 `jco` 模块依赖。Python `services/odata-service/` 是独立进程，与 Java Gateway 经 HTTP 通信。

**迁移边界（第一步只搬不改）**：现有 `gateway-jco/` 全部源码按上述归属迁入对应模块；包名 `com.sapnexus.gateway.*` 不变（避免大量 import 改动）；既有测试随源码迁移到对应模块 `src/test`。迁移后 `cd services/gateway && gradle test` 必须全绿（既有 JCo + dispatcher + redactor + controller 测试），inventory 回归不变，才进入后续步骤。

### 2.2 Dispatcher 全局化与 adapter 注册

- `CapabilityController.execute` 不再内联创建 dispatcher。改为注入 `TechnicalExecutionDispatcher` 单例 bean。
- `services/gateway/app` 的 Spring 配置类（或 `services/gateway/core` 的 `ExecutionConfiguration`）注册 `TechnicalExecutionDispatcher` bean，注入 `Map<String, TechnicalAdapter>`（Spring 按 executor type 字符串键收集 adapter bean）。
- `JcoRfcTechnicalAdapter` 与 `ODataHttpProxyAdapter` 各自声明为 `@Component`，构造时按需注入 `CapabilityRegistry` / `JcoCapabilityExecutor` / `ODataProxyProperties`。
- Controller 只负责：拒绝 technical override -> validate -> 取 capability -> 构建 `TechnicalExecutionRequest`(bindingId + parameters，**不含 OData metadata**) -> `dispatcher.dispatch(technicalRequest)` -> `toExecutionResult(capability)`。

### 2.3 OData 执行层：Python 微服务 + Java 薄反代（架构修正 2026-07-09）

原方案 §2.3 "OData adapter 自取 binding（方案 A）" 把 OData 全部实现放在 Java `services/gateway/odata/`，已被修正：OData 是纯 HTTP/JSON，无 Java 绑定理由，真实 OData 逻辑改用 Python。

**职责划分**：

| 层 | 语言 | 职责 |
|---|---|---|
| Java `services/gateway/odata/ODataHttpProxyAdapter` | Java（薄） | implements `TechnicalAdapter`；接收 `TechnicalExecutionRequest`，HTTP POST 转发到 Python OData 服务（:8081），把返回 JSON 归一为 `TechnicalExecutionResult` + redaction；不做 `$filter` 组装、不直连 SAP |
| Python `services/odata-service/` | Python（真 OData） | 接收 Java 转发的 `{serviceRef, entitySet, filterMapping, parameters, topLimit}`，组装 `$filter`，发 GET 到 SAP OData（`sap-client` header，CSRF 按需，destination 经环境注入），返回归一 JSON（`purchaseOrders` 数组 + `totalCount`）；复用 `sap-sto-create` session/CSRF/JSON 归一 |

**单端点保持**：Agent 仍调 Java Gateway（:8080）只认 `capabilityId`；Java dispatcher 路由 ODATA binding 到 `ODataHttpProxyAdapter`，后者 HTTP 转发 Python 服务。Agent 不感知 executor 类型，`gateway-execution-contract` 契约语义不变。

**`TechnicalExecutionRequest` 契约**：仍**不变**（只携带 `bindingId` + `parameters` + capability 基本字段）。`ODataHttpProxyAdapter` 注入 `CapabilityRegistry` + `BindingRegistry`，按 `bindingId` 取 `serviceRef`/`entitySet`/`filterMapping`/`topLimit`，连同 `parameters` 一起 POST 给 Python 服务（参数->$filter 组装在 Python 服务内，Java 侧只转发语义参数 + binding metadata）。

**redaction 边界**：Java 侧 `ODataHttpProxyAdapter` 经 `TechnicalRedactor` redact destination/token/cookie；Python 服务经环境注入 destination，返回 JSON 不含敏感值。Java 侧不存 OData destination base URL/token（这些在 Python 服务的环境）。

**JCo 路径完全不受影响**（`JcoRfcTechnicalAdapter` 不依赖 Registry，行为不变）。

**代价**：多一跳 HTTP（Gateway->Python->SAP）+ 多一个 Python 进程。换取：OData 用 Python、JCo 零返工、既有契约/spec 不破。

### 2.4 `toExecutionResult` 去耦合（方案 A-1）

- `TechnicalExecutionResult.toExecutionResult(String rfcName)` 改为 `toExecutionResult(CapabilityDefinition capability)`。
- 内部从 `capability.executor()` 取 executor metadata：JCo capability 有 `rfcName` 则填入，OData capability 无 `rfcName` 则填 `null`。
- `ExecutionResult.ExecutorMetadata(String type, String rfcName)`：`rfcName` 改为 nullable（`String`，可为 null）。
- Controller 调用改为 `technicalResult.toExecutionResult(capability)`，无 if-else 分支。
- Agent 侧 `executor` 是泛型 dict，`rfcName` 缺失或 null 不影响 Agent 解析--**Agent 侧零改动**。
- `gateway-execution-contract` spec 的 "Preserve Agent-facing execution result" scenario 契约不变（仍是 `ExecutionResult` 字段兼容），**无需 Spec Patch**。

### 2.5 PO OData 能力与 binding

- `registry/executor-bindings.yaml` 新增：
  ```yaml
  - bindingId: sap.mm.purchaseorder.list-odata
    type: ODATA
    serviceRef: API_PURCHASEORDER_PROCESS_SRV
    entitySet: PurchaseOrder
    method: GET
    filterMapping:
      poNumber: PurchaseOrder
      vendor: Supplier
      plant: Plant
      material: Material
    topLimit: 50
    selectFields: [PurchaseOrder, Supplier, Plant, Material, OrderQuantity, PurchaseOrderUnit, <交货日期字段>]
    constraints:
      sideEffect: none
      timeoutMs: 30000
  ```
  字段名以 build 阶段 live spike 确认的实际 entitySet schema 为准（`API_PURCHASEORDER_PROCESS_SRV` 标准字段：`PurchaseOrder`/`Supplier`/`Plant`/`Material`/`OrderQuantity`/`PurchaseOrderUnit`；交货日期字段 spike 确认）。
- `registry/capabilities.yaml` 新增 `MM.PurchaseOrder.GetList`：executor type `ODATA`，4 过滤参数（poNumber/vendor/plant/material 全 optional），输出 `purchaseOrders` 数组，governance `sideEffect: none`/`requiresApproval: false`/`dataClassification: internal`/`auditRequired: true`。

### 2.6 Agent 多能力路由与列表归一

- `capability_selector.py`：改为 `INTENT_TO_CAPABILITY = {"inventory_availability": "MM.Inventory.GetAvailability", "purchase_order_list": "MM.PurchaseOrder.GetList"}` 映射表 + 闭集校验。保留 `UNSUPPORTED_INTENT`/`MISSING_PARAMETER`/`UNSUPPORTED_RFC_NAME` 语义。Agent 不感知 executor 类型。
- `intent.py`：新增 `PURCHASE_ORDER_KEYWORDS`（采购订单/PO/订单）+ `intent="purchase_order_list"`，解析 4 过滤参数；"至少一个过滤"守卫；拒绝裸 OData URL/service/`$filter`。
- `execution_result.py`：支持列表型输出（`purchaseOrders` 数组）--Agent 侧 `data` 是 `dict[str, Any]`，天然支持数组，无需改 dataclass。
- `reasoning_fact.py`：列表项归一为多条 `ReasoningFact`（`predicate=purchaseOrderItem`，`deterministic=true`，`confidence=1.0`，evidence = PO号/供应商/物料/工厂/数量/单位/交货日期）。
- `narrator.py`：逐项 grounded narrative；空列表输出"无匹配记录"；超 50 条说明"仅返回前 50 条"；narrator guard 拒绝输出 facts 中不存在的字段。

### 2.7 CSRF / session / destination

- OData read 第一版以 GET 为主，SAP OData read GET 通常不要求 CSRF token。
- destination（base URL / auth）经环境变量注入 `ODataDestinationProperties`，不进 Registry/git/trace。
- 若 live 服务要求 CSRF（build spike 验证），按 `sap-sto-create` 的 token 获取+刷新模式实现，token 经 `TechnicalRedactor` redact。
- `sap-client` header 从 destination 配置取，不暴露给 Agent。

## 3. 数据流（OData PO 查询）

```
用户: "查供应商 DEMOV1 的采购订单"
  │
  ▼ intent.py
IntentParseResult{intent=purchase_order_list, parameters={vendor:DEMOV1}}
  │
  ▼ capability_selector.py
SelectionResult{capabilityId=MM.PurchaseOrder.GetList}   # 映射表，不感知 ODATA
  │
  ▼ call_plan.py -> gateway_client.execute(capabilityId, {vendor:DEMOV1})
  │
  ▼ CapabilityController.execute (gateway/app)
   拒绝 technical override -> validate -> 取 capability (ODATA binding)
   TechnicalExecutionRequest{bindingId=sap.mm.purchaseorder.list-odata, parameters={vendor:DEMOV1}}
  │
  ▼ TechnicalExecutionDispatcher.dispatch (gateway/core)
   路由 executorType=ODATA -> ODataHttpProxyAdapter (gateway/odata, Java 薄反代)
  │
  ▼ ODataHttpProxyAdapter.execute (Java)
   registry.findEnabled + bindingRegistry -> 取 serviceRef/entitySet/filterMapping/topLimit
   HTTP POST {serviceRef,entitySet,filterMapping,parameters,topLimit} -> Python OData 服务 (:8081)
  │
  ▼ Python odata-service (:8081)
   $filter 组装: {vendor:DEMOV1} -> "Supplier eq 'DEMOV1'"
   GET SAP /sap/opu/odata/sap/API_PURCHASEORDER_PROCESS_SRV/PurchaseOrder?$filter=...&$top=50&$count
   归一 JSON -> {purchaseOrders:[...], totalCount:N} 返回 Java
  │
  ▼ ODataHttpProxyAdapter 归一 -> TechnicalExecutionResult{data:{purchaseOrders:[...], totalCount:N}} + redaction
  │
  ▼ toExecutionResult(capability)   # rfcName=null for ODATA
  │
  ▼ gateway_client -> execution_result.py
ExecutionResult{data:{purchaseOrders:[...]}}
  │
  ▼ reasoning_fact.py
[ReasoningFact(predicate=purchaseOrderItem, ...), ...]   # 每条 PO 一个 fact
  │
  ▼ narrator.py
中文 grounded narrative（逐项引用 PO号/供应商/物料/...）
```

## 4. 测试策略

### 4.1 Gateway
- `services/gateway/core`：既有 `TechnicalExecutionDispatcherTest`/`TechnicalRedactorTest`/`CapabilityControllerTest`/`CapabilityExecutionApiTest`/`CapabilityRegistryLoaderTest`/`TraceWriterTest` 迁移并保持全绿；新增 dispatcher ODATA 路由 + 未匹配 executor fail-closed 测试。
- `services/gateway/odata`：`ODataHttpProxyAdapterTest` 用 mock Python 服务响应覆盖--正常列表/空列表/HTTP 4xx/5xx/JSON 异常/redaction（destination/token/cookie 不泄露）；验证转发 payload 含 serviceRef/entitySet/filterMapping/parameters/topLimit。
- `services/odata-service/`（Python）：pytest 覆盖 `$filter` 组装（单参/多参/转义）、OData 响应归一（collection/空/错误）、CSRF/session（mock SAP HTTP）、redaction（destination 不进响应）。
- `services/gateway/app`：集成测试 JCo+OData 共存（同一端点，dispatcher 路由两条 capability）。
- 命令：`cd services/gateway && gradle test`。

### 4.2 Agent
- `test_intent.py`：PO 意图解析（单参/多参/无参澄清/裸 endpoint 拒绝/与库存意图区分）。
- 新增 selector 多能力路由测试（inventory -> JCO capability、PO -> ODATA capability、未知 intent 拒绝、LLM 闭集校验）。
- `test_reasoning_narrator.py`：列表归一（多条 fact）/空列表/超限说明/guard 失败。
- inventory 既有回归全绿。

### 4.3 Registry
- `validate-registry-contract.py` 确认 ODATA binding 校验通过。
- `test_registry_contract.py` 回归通过。

### 4.4 Eval
- `evals/` 新增 PO OData seed cases（核心成功/参数补全/多参 `$filter`/跨 executor 意图区分/裸 endpoint 拒绝/列表归一/空结果/redaction）。
- mock 回归默认运行；live 联调 case gated by env flag（默认 skip）。
- `scripts/verify-agent-callplan-evidence.sh` 纳入 PO seed eval。
- `.venv/bin/python -m sap_nexus_agent.eval` 通过 PO seed。

### 4.5 OpenSpec
- `openspec validate --all --strict` 通过。

## 5. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 多模块重构破坏 JCo 路径 | 第一步只搬不改；`cd services/gateway && gradle test` 全绿才继续；`services/gateway/app` 组装 core+jco 即可独立运行 |
| live OData service schema 与假设不符 | mock 回归隔离 live 依赖；build spike 验证 `API_PURCHASEORDER_PROCESS_SRV` 实际 entitySet 字段名 |
| `toExecutionResult` 重构引入回归 | 既有 JCo 测试覆盖 `ExecutorMetadata`；OData 传 null 不影响 Agent 泛型 dict 解析 |
| OData 大结果集体积 | `$top=50`；trace 只记 count + bindingId，不记列表明文 |
| CSRF 实际需要但未实现 | build live 验证；若需要按 `sap-sto-create` 模式补 |
| `capability_selector` 改动影响 inventory | 保留 inventory 路径行为不变；inventory eval 全量回归 |

## 6. 迁移与回滚

增量推进（对齐 tasks.md 9 组）：
1. 多模块重构（只搬不改，全绿）
2. Registry ODATA binding + capability
3. `services/gateway/odata` 薄反代 adapter（`ODataHttpProxyAdapter`）+ Python `services/odata-service/`（:8081）+ dispatcher 注册 ODATA 路由
4. Agent PO 意图解析
5. Agent 多能力路由
6. Agent 列表归一 + narrative
7. PO OData evals
8. live 联调（gated）
9. Comet closeout

**回滚**：ODATA capability 在 Registry 置 `status=inactive` 即下线，不影响 inventory JCO 路径；`services/gateway/app` 移除 `services/gateway/odata` 依赖 + 停 Python `odata-service` 即可回退到 core+jco。

## 7. Open Questions（build 阶段收敛）

### 收敛记录（Task 11 / live spike, 2026-07-09）

**Live spike 结果：BLOCKER（SAP ICF 403）**

SAP 系统可达（`http://<host>:8000`），但所有 ICF 服务返回 HTTP 403 "Service cannot be reached"
（含 `/sap/bc/ping`、`/sap/opu/odata/sap/API_PRODUCT_SRV/`、`/sap/opu/odata/sap/API_PURCHASEORDER_PROCESS_SRV/`）。
这表明 ICF 层面的 S_ICF_NODE 授权或 SICF 服务激活问题，不是 OData 服务本身的问题。
Live spike 测试 gated by `SAP_ODATA_LIVE=1`，默认 skip；mock 回归不受影响。

### 逐项收敛

1. **`API_PURCHASEORDER_PROCESS_SRV` live 可达性与实际 entitySet 字段名**
   - 状态：**部分收敛（基于 sap-sto-create 参考，live 未验证）**
   - Live 不可达（403 blocker）。但 sap-sto-create 的 `create_sto_odata.py` 提供了经实际验证的参考：
     - entitySet 实际为 `A_PurchaseOrder`（非 binding 原假设的 `PurchaseOrder`），已回写 `registry/executor-bindings.yaml`
     - 单位字段实际为 `PurchaseOrderQuantityUnit`（非 `PurchaseOrderUnit`），已回写 binding selectFields + normalizer FIELD_MAP
   - 待 live 可达后最终确认

2. **交货日期字段具体名**
   - 状态：**未收敛（live blocker）**
   - sap-sto-create 的 `to_ScheduleLine` 导航属性中使用 `ScheduleLineDeliveryDate`（行项目日程行级别，非 PO 抬头级别）
   - 候选字段：`DeliveryDate` / `ScheduleLineDeliveryDate` / `PurchasingDocumentDeliveryDate`
   - 待 live 可达后确认；normalizer 的 pass-through 设计允许任意字段自动透传

3. **live 联调 destination 配置来源**
   - 状态：**已收敛**
   - 环境变量注入（`SAP_URL` / `SAP_USER` / `SAP_PASSWORD` / `SAP_CLIENT` / `SAP_LANG`），与 JCo + sap-sto-create 共用
   - `SAP_ODATA_TIMEOUT_SECONDS` 为 OData 专属（默认 30s）

4. **CSRF 是否真需**
   - 状态：**部分收敛（基于 sap-sto-create 参考，live 未验证）**
   - sap-sto-create 的 `_get()` 方法不获取 CSRF token，仅 `_post()` 方法获取--read GET 通常不需要 CSRF
   - `ODataClient._fetch_csrf_token()` 保留为扩展点，待 live 可达后确认
   - 若需 CSRF，按 sap-sto-create 的 `_get_csrf_token` 模式实现（`x-csrf-token: fetch` header）

5. **live 联调 auth 方式**
   - 状态：**部分收敛（基于 sap-sto-create 参考，live 未验证）**
   - Basic auth（`SAP_USER` / `SAP_PASSWORD`）--与 sap-sto-create 一致
   - Live 403 是 ICF 层面（S_ICF_NODE 授权），不是 auth 方式问题；待 ICF 授权解决后确认

### Redaction 确认

- **Mock 层面**：已验证 destination/password/username 不进响应（`test_execute_redaction_no_destination_in_response` + `test_destination_password_not_in_repr`）
- **Live 层面**：因 403 blocker 无法验证；live spike 测试 `test_live_redaction_no_credentials_in_response` gated，待 ICF 授权解决后运行


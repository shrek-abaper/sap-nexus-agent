---
change: sap-nexus-odata-gateway-read-pilot
design-doc: docs/superpowers/specs/2026-07-08-sap-nexus-odata-gateway-read-pilot-design.md
base-ref: e5ab58f809fbaa7b120fe17672dfb8fb1236f44b
archived-with: 2026-07-09-sap-nexus-odata-gateway-read-pilot
---

# OData Gateway Read Pilot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 提前 Phase 4D OData Gateway Read Pilot：新建 OData 只读连接器（`services/gateway/odata`），以 `MM.PurchaseOrder.GetList` 作为首个 ODATA 能力，验证多 executor 类型注册、多能力跨 executor 路由、列表结果归一。

**Architecture:** 详见 Design Doc `docs/superpowers/specs/2026-07-08-sap-nexus-odata-gateway-read-pilot-design.md`。核心：`services/gateway/{core,jco,odata,app}` Gradle 多模块单端点；`TechnicalExecutionDispatcher` 按 executor type 路由；Java `ODataHttpProxyAdapter` 薄反代 + Python `odata-service` 真实 OData（方案 B）；`toExecutionResult(capability)` 去耦合（方案 A-1）；Agent `capability_selector` intent->capabilityId 映射表，不感知 executor 类型。

**Tech Stack:** Java 17, Spring Boot 3.3.6, JUnit 5, MockMvc, AssertJ, Gradle；Python 3, pytest；Registry YAML + JSON schema。

## Global Constraints

- Agent 仍单端点、只认 `capabilityId`，不感知 executor 类型/binding。
- LLM/user/Agent 不得提供 `rfcName`、裸 OData URL/service/`$filter`/endpoint/method/header/credential override。
- `JCO_RFC` + `ODATA` 是本 change 的运行时 adapter；`CDS_ADT`/`CDS_ODATA`/`REST_JSON`/`SQL_READ` 仍 fail-closed。
- OData read-only：不做 write/deep insert/STO create。
- 不破坏 inventory JCO 既有路径与 Workbench。
- 不提交 `.env`/destination config/token/credential/runtime trace。
- 每个任务：实现 -> 验证 -> tasks.md 勾选 -> git commit（不积攒）。
- 失败时加载 `systematic-debugging` skill，根因未定位前不修源码。

## File Structure

### Gateway 多模块（新建 `services/gateway/`）
- `services/gateway/settings.gradle`、`services/gateway/build.gradle`（根）
- `services/gateway/core/`：从 `gateway-jco/` 迁入 `execution/*`（TechnicalExecutionRequest/Result/Adapter/Dispatcher/Redactor）、`result/*`、`trace/*`、`registry/*`、`validation/CapabilityValidationService`、`api/*`（CapabilityController/Response/Request/HealthController）
- `services/gateway/jco/`：迁入 `jco/*`（JcoRfcTechnicalAdapter/JcoCapabilityExecutor/JcoDestination*/InventoryAvailabilityExecutor/InMemoryDestinationDataProvider）
- `services/gateway/odata/`（薄反代）：`ODataHttpProxyAdapter`、`ODataProxyProperties`（真实 OData 逻辑在 `services/odata-service/` Python 服务）
- `services/gateway/app/`：`SapNexusGatewayApplication`（Spring Boot 启动），`application.yml`
- 包名 `com.sapnexus.gateway.*` 不变

### Registry
- Modify `registry/executor-bindings.yaml`：新增 `sap.mm.purchaseorder.list-odata`（ODATA，serviceRef/entitySet/method/filterMapping/topLimit/selectFields）
- Modify `registry/capabilities.yaml`：新增 `MM.PurchaseOrder.GetList`
- Modify `schemas/executor-binding.schema.json`：binding properties 新增 `filterMapping`/`topLimit`/`selectFields`（因 `additionalProperties: false`）
- Modify `services/gateway/core` Java `CapabilityRegistryValidator`：按 executor type 分支校验（JCO_RFC 要 rfcName，ODATA 不要 rfcName）

### Agent（`agent/sap_nexus_agent/`）
- Modify `intent.py`：新增 `PURCHASE_ORDER_KEYWORDS` + `parse_intent(text)` 统一入口 + `contains_odata_override` 字段
- Modify `capability_selector.py`：intent->capabilityId 映射表 + 闭集校验
- Modify `call_plan.py`：去掉 `setdefault("unit","EA")` 通用化（inventory 默认 unit 移到 inventory 路径）
- Modify `orchestrator.py`：新增 `run_query(text, gateway)` 统一入口，按 capabilityId 路由 fact builder/narrator
- Modify `reasoning_fact.py`：新增 `build_purchase_order_facts`（列表项->多条 fact）
- Modify `narrator.py`：PO narrative + 列表/空/超限 + guard
- `execution_result.py`/`gateway_client.py`：无需改（data 是泛型 dict，execute 通用）

### Evals
- Modify `evals/eval_harness_seed_cases.json`：新增 PO OData seed cases
- Modify `agent/sap_nexus_agent/eval.py`：调用 `run_query` 统一入口
- Modify `scripts/verify-agent-callplan-evidence.sh`：纳入 PO seed

## Task 1: Gateway 多模块重构骨架（只搬不改）

**Files:**
- Create: `services/gateway/settings.gradle`、`services/gateway/build.gradle`、`services/gateway/{core,jco,odata,app}/build.gradle`
- Move: `gateway-jco/src/main/java/com/sapnexus/gateway/{execution,result,trace,registry,validation,api}/*` -> `services/gateway/core/src/main/java/...`
- Move: `gateway-jco/src/main/java/com/sapnexus/gateway/jco/*` -> `services/gateway/jco/src/main/java/...`
- Move: 既有测试随源码迁入对应模块 `src/test`
- Create: `services/gateway/app/src/main/java/com/sapnexus/gateway/SapNexusGatewayApplication.java`（从 `gateway-jco` 迁入 `SapNexusGatewayApplication`）
- Move: `gateway-jco/src/main/resources/application.yml` -> `services/gateway/app/src/main/resources/application.yml`
- Move: `gateway-jco/lib/sapjco3.jar` -> `services/gateway/jco/lib/sapjco3.jar`（仅 jco 模块依赖）
- Delete: `gateway-jco/`（迁移完成后删除旧目录）

**Interfaces:** 模块依赖 `jco`->`core`、`odata`->`core`、`app`->`core`+`jco`+`odata`。包名不变。

**Steps:**
1. 创建 `services/gateway/settings.gradle`（`include core, jco, odata, app`；`rootProject.name = 'sap-nexus-gateway'`）
2. 创建各模块 `build.gradle`：`core`（spring-boot-starter-web/validation + snakeyaml，无 boot 插件）、`jco`（`implementation files('lib/sapjco3.jar')` + `implementation project(':core')`）、`odata`（`implementation project(':core')`，预留 HTTP client）、`app`（`spring-boot` 插件 + `implementation project(':core')` + `project(':jco')` + `project(':odata')`）
3. 按上述归属 `git mv` 源码与测试到对应模块
4. 迁移 `SapNexusGatewayApplication` 到 `services/gateway/app`，确认 `@SpringBootApplication` 扫描 `com.sapnexus.gateway`
5. 迁移 `application.yml` 到 `services/gateway/app/src/main/resources/`
6. 删除旧 `gateway-jco/` 目录
7. **验证：** `cd services/gateway && gradle test` 全绿（既有 JCo + dispatcher + redactor + controller + registry 测试），inventory 回归不变

**Verify:** `cd services/gateway && gradle test` -> BUILD SUCCESSFUL，所有既有测试通过

## Task 2: Dispatcher 全局化与 toExecutionResult 去耦合

**Files:**
- Modify: `services/gateway/core/.../execution/TechnicalExecutionResult.java`（`toExecutionResult(String rfcName)` -> `toExecutionResult(CapabilityDefinition capability)`）
- Modify: `services/gateway/core/.../result/ExecutionResult.java`（`ExecutorMetadata.rfcName` 改 nullable）
- Modify: `services/gateway/core/.../execution/TechnicalExecutionDispatcher.java`（保持，已是 adapter 注册表）
- Modify: `services/gateway/jco/.../jco/JcoRfcTechnicalAdapter.java`（改 `@Component`，构造注入 `JcoCapabilityExecutor`，不再持有单个 capability）
- Modify: `services/gateway/core/.../api/CapabilityController.java`（注入 `TechnicalExecutionDispatcher` 单例 bean，移除内联 `new TechnicalExecutionDispatcher(...)`；调用 `technicalResult.toExecutionResult(capability)`）
- Create/Modify: `services/gateway/core/.../execution/ExecutionConfiguration.java`（Spring 配置，注册 dispatcher bean + adapter 收集）
- Modify: `JcoRfcTechnicalAdapter` 的 `execute`：从 `request.capabilityId()` 经 `CapabilityRegistry` 取 capability（注入 registry）

**Interfaces:** `JcoRfcTechnicalAdapter` 改为无状态 `@Component`（不再绑定单个 capability），`execute(request)` 内按 `request.capabilityId()` 从 registry 取 capability。

**Steps (TDD):**
1. 改 `ExecutorMetadata.rfcName` 为 nullable；更新 `ExecutionResult.success/failure` 静态工厂
2. 改 `TechnicalExecutionResult.toExecutionResult(CapabilityDefinition)`：JCo 取 `capability.executor().rfcName()`，OData 取 null
3. 改 `JcoRfcTechnicalAdapter` 为 `@Component`，构造注入 `JcoCapabilityExecutor` + `CapabilityRegistry`；`execute` 内 `registry.findEnabled(request.capabilityId())` 取 capability
4. 新增 `ExecutionConfiguration`：`@Bean TechnicalExecutionDispatcher(List<TechnicalAdapter> adapters)` 按 executor type 收集
5. 改 `CapabilityController`：注入 `TechnicalExecutionDispatcher`；移除内联创建；`toExecutionResult(capability)`
6. 更新既有测试：`CapabilityExecutionApiTest`/`TechnicalExecutionDispatcherTest`/`JcoRfcTechnicalAdapter` 相关构造
7. **验证：** `cd services/gateway && gradle test` 全绿

**Verify:** `cd services/gateway && gradle test` -> BUILD SUCCESSFUL

## Task 3: Registry ODATA binding + PO capability

**Files:**
- Modify: `registry/executor-bindings.yaml`（新增 ODATA binding）
- Modify: `registry/capabilities.yaml`（新增 `MM.PurchaseOrder.GetList`）
- Modify: `schemas/executor-binding.schema.json`（binding properties 加 `filterMapping`/`topLimit`/`selectFields`）
- Modify: `services/gateway/core/.../registry/CapabilityRegistryValidator.java`（按 executor type 分支：JCO_RFC 要 rfcName/mapping，ODATA 不要 rfcName）
- Modify: `services/gateway/core/.../registry/CapabilityDefinition.java` + `CapabilityRegistryLoader.java`（`Executor` record 支持 ODATA 无 rfcName；加载 ODATA capability）
- Modify: `ontology/` 相关（新增 PO capability 本体条目，若 OWL skeleton 要求）

**Interfaces:** `Executor` record 的 `rfcName` 改 nullable；ODATA capability 的 `executor` 仅 `type: ODATA`（无 rfcName/inputMapping/outputMapping）。

**Steps:**
1. 改 `schemas/executor-binding.schema.json`：binding properties 加 `filterMapping`(object)/`topLimit`(integer)/`selectFields`(array)；ODATA conditional required 加 `filterMapping`/`topLimit`
2. 改 Java `CapabilityRegistryValidator`：按 `executor.type` 分支--JCO_RFC 校验 rfcName/inputMapping/outputMapping；ODATA 校验无 rfcName（容许缺失）
3. 改 Java `CapabilityDefinition.Executor` record：`rfcName` nullable；`CapabilityRegistryLoader` 容许 ODATA executor 无 rfcName
4. 新增 `registry/executor-bindings.yaml` 条目：
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
     selectFields: [PurchaseOrder, Supplier, Plant, Material, OrderQuantity, PurchaseOrderUnit]
     constraints:
       sideEffect: none
       timeoutMs: 30000
   ```
5. 新增 `registry/capabilities.yaml` 条目 `MM.PurchaseOrder.GetList`（executor type ODATA，4 过滤参数 poNumber/vendor/plant/material 全 optional，输出 `purchaseOrders` 数组，governance read-only）
6. 更新 `CapabilityRegistryLoaderTest`：新增 ODATA capability 加载测试（可选 fixture）
7. **验证：** `.venv/bin/python scripts/validate-registry-contract.py registry/capabilities.yaml` + `.venv/bin/python -m pytest agent/tests/test_registry_contract.py -v` + `cd services/gateway && gradle test`

**Verify:** 三个命令均通过

## Task 4: Python OData 服务骨架 + $filter 组装

> 架构修正 2026-07-09：OData 真实逻辑用 Python，非 Java。本 task 建 Python `services/odata-service/` 微服务（:8081），复用 `sap-sto-create` 经验。

**Files:**
- Create: `services/odata-service/`（新 Python 包，独立于 `agent/`）：`pyproject.toml` 或 `requirements.txt`、`odata_service/__init__.py`、`odata_service/server.py`（HTTP 服务入口，:8081）、`odata_service/filter_builder.py`、`odata_service/odata_client.py`、`odata_service/destination.py`、`odata_service/normalizer.py`
- Create: `odata-service/tests/test_filter_builder.py`、`test_normalizer.py`、`test_server.py`
- Reference: `sap-skill-create/skills-production/sap-sto-create/scripts/lib/create_sto_odata.py`（session/CSRF/sap-client/JSON 归一借鉴）

**Interfaces:**
- `POST /execute`（:8081）：接收 `{serviceRef, entitySet, filterMapping, parameters, topLimit, selectFields, traceId}`，返回 `{success, purchaseOrders:[...], totalCount, errorType?, messages?}`
- `filter_builder.build(parameters, filterMapping) -> str`：如 `Supplier eq 'DEMOV1'`，多参 ` and ` 连接，忽略未提供参数，字符串转义
- `odata_client.get(serviceRef, entitySet, filter, top, count) -> dict`：HTTP GET SAP OData（`sap-client` header，CSRF 按需，destination 经环境注入）
- `normalizer.normalize(json_body) -> dict`：解析 `d.results`/`value` 数组为 `purchaseOrders` + `totalCount`；空集合 success；错误归一

**Steps (TDD):**
1. 写 `test_filter_builder.py`：单参/多参组合/无参（空字符串）/字符串转义
2. 实现 `filter_builder.py`
3. 写 `test_normalizer.py`：正常列表（多 PO item）/空集合/`$count`/JSON 异常
4. 实现 `normalizer.py`：映射字段 `PurchaseOrder`/`Supplier`/`Plant`/`Material`/`OrderQuantity`/`PurchaseOrderUnit` -> PO号/供应商/物料/工厂/数量/单位（+交货日期字段 spike 后补）
5. 写 `test_server.py`：`POST /execute` 端到端（mock `odata_client`）覆盖正常/空/错误
6. 实现 `server.py`（用 stdlib `http.server` 或 Flask/FastAPI，与 agent 一致用 stdlib 优先）+ `odata_client.py` + `destination.py`（env 注入，不进 git/trace）
7. **验证：** `cd services/odata-service && python -m pytest` 全绿

**Verify:** `cd services/odata-service && python -m pytest` 全绿

## Task 5: Java ODataHttpProxyAdapter（薄反代）+ BindingRegistry

> Java 侧只做 HTTP 转发到 Python 服务 + JSON 归一为 TechnicalExecutionResult + redaction。不做 $filter 组装、不直连 SAP。

**Files:**
- Create: `services/gateway/core/.../registry/BindingDefinition.java`（ODATA binding record：serviceRef/entitySet/method/filterMapping/topLimit/selectFields）
- Create: `services/gateway/core/.../registry/BindingRegistry.java` + `BindingRegistryLoader.java`（加载 `executor-bindings.yaml`）
- Modify: `services/gateway/core/.../registry/RegistryConfiguration.java`（注册 BindingRegistry bean）
- Create: `services/gateway/odata/.../ODataHttpProxyAdapter.java`（`@Component`，implements `TechnicalAdapter`）
- Create: `services/gateway/odata/.../ODataProxyProperties.java`（Python 服务地址 :8081，`@ConfigurationProperties`）
- Create: `services/gateway/odata/src/test/.../ODataHttpProxyAdapterTest.java`（mock Python 服务 HTTP 响应）

**Interfaces:** `ODataHttpProxyAdapter.execute(request)`：`registry.findEnabled(capabilityId)` -> `bindingRegistry.find(bindingId)` 取 serviceRef/entitySet/filterMapping/topLimit -> HTTP POST 到 Python `:8081/execute`（payload 含 serviceRef/entitySet/filterMapping/parameters/topLimit）-> 归一返回 JSON 为 `TechnicalExecutionResult`（`data.purchaseOrders` + `data.totalCount`）+ redaction。

**Steps (TDD):**
1. 写 `ODataHttpProxyAdapterTest`：mock Python 服务响应，覆盖正常列表/空/HTTP 4xx/5xx/JSON 异常/redaction（destination/token/cookie 不泄露）；验证转发 payload 含 serviceRef/entitySet/filterMapping/parameters/topLimit
2. 实现 `BindingDefinition`/`BindingRegistry`/`BindingRegistryLoader`
3. 实现 `ODataHttpProxyAdapter`（Spring `RestClient`/`RestTemplate` HTTP POST Python 服务）
4. 实现 `ODataProxyProperties`（env `sap.gateway.odata.proxy-url`）
5. **验证：** `cd services/gateway && gradle test`

**Verify:** gradle test 全绿

## Task 6: dispatcher ODATA 路由注册 + 请求所有权守卫扩展

**Files:**
- Modify: `services/gateway/core/.../execution/ExecutionConfiguration.java`（注册 `ODataHttpProxyAdapter` bean，bean name `ODATA`）
- Modify: `services/gateway/core/.../api/CapabilityRequest.java`（technical override 检测扩展：拒绝裸 OData URL/service/`$filter`/endpoint/method/header/credential，复用既有 `technicalOverrideKeys`）
- Modify: `services/gateway/app` 集成测试：JCo+OData 共存 dispatcher 路由（mock Python 服务）

**Interfaces:** dispatcher 按 executor type `ODATA` 路由到 `ODataHttpProxyAdapter`；`CapabilityRequest.technicalOverrideKeys` 扩展检测 OData 覆盖字段。

**Steps (TDD):**
1. 写集成测试：`/capabilities/MM.PurchaseOrder.GetList/execute` 路由到 `ODataHttpProxyAdapter`（mock Python 服务）；`MM.Inventory.GetAvailability` 仍走 JCo
2. 注册 `ODataHttpProxyAdapter` 为 `@Component("ODATA")`
3. 扩展 `CapabilityRequest.technicalOverrideKeys` 检测 OData 覆盖字段
4. **验证：** `cd services/gateway && gradle test`

**Verify:** gradle test 全绿（含 ODATA 路由 + JCo 回归 + 请求所有权守卫）

## Task 7:（已合并到 Task 5/6，原 ODataTechnicalAdapter 取消）

## Task 8: Agent PO 意图解析

**Files:**
- Modify: `agent/sap_nexus_agent/intent.py`
- Modify: `agent/tests/test_intent.py`

**Interfaces:** 新增 `PURCHASE_ORDER_KEYWORDS`（采购订单/PO/订单）；新增 `parse_intent(text)` 统一入口（先 inventory 后 PO，或按关键词优先级）；`IntentParseResult` 新增 `contains_odata_override: bool = False`；解析 4 过滤参数（poNumber/vendor/plant/material）；"至少一个过滤"守卫；检测裸 OData URL/service/`$filter`。

**Steps (TDD):**
1. 写测试：`查供应商 DEMOV1 的采购订单` -> intent=purchase_order_list, vendor=DEMOV1；`查工厂 1000 物料 MAT001 的采购订单` -> plant+material；`帮我看看采购订单` -> missing + clarification；裸 OData URL -> contains_odata_override=True；与库存意图区分
2. 实现 `parse_intent` + PO 关键词 + 参数解析 + 守卫 + OData override 检测
3. 保留 `parse_inventory_intent` 向后兼容（委托 `parse_intent` 或保留）
4. **验证：** `.venv/bin/python -m pytest agent/tests/test_intent.py -v`

**Verify:** pytest 全绿

## Task 9: Agent 多能力路由

**Files:**
- Modify: `agent/sap_nexus_agent/capability_selector.py`
- Modify `agent/tests/test_intent.py` 或新建 selector 测试

**Interfaces:** `INTENT_TO_CAPABILITY = {"inventory_availability": "MM.Inventory.GetAvailability", "purchase_order_list": "MM.PurchaseOrder.GetList"}`；`select_capability(parse_result)` 查映射表；保留 `UNSUPPORTED_INTENT`/`MISSING_PARAMETER`/`UNSUPPORTED_RFC_NAME`（含 `contains_odata_override` -> UNSUPPORTED_RFC_NAME 语义）；Agent 不感知 executor 类型。

**Steps (TDD):**
1. 写测试：inventory intent -> MM.Inventory.GetAvailability；PO intent -> MM.PurchaseOrder.GetList；未知 intent -> UNSUPPORTED_INTENT；PO 无过滤 -> MISSING_PARAMETER；裸 OData -> 拒绝
2. 实现映射表驱动 selector
3. **验证：** `.venv/bin/python -m pytest agent/tests/ -v`（含 inventory 回归）

**Verify:** pytest 全绿

## Task 10: Agent 列表归一与 narrative

**Files:**
- Modify: `agent/sap_nexus_agent/reasoning_fact.py`（新增 `build_purchase_order_facts(execution_result, context)`）
- Modify: `agent/sap_nexus_agent/narrator.py`（PO narrative：逐项 grounded/空列表/超限说明/guard）
- Modify: `agent/sap_nexus_agent/call_plan.py`（去掉通用 `setdefault("unit","EA")`，inventory 默认 unit 移到 inventory 路径）
- Modify: `agent/sap_nexus_agent/orchestrator.py`（新增 `run_query(text, gateway)` 统一入口，按 capabilityId 路由 fact builder/narrator；`run_inventory_query` 保留委托）
- Modify: `agent/sap_nexus_agent/execution_result.py`（无需改，data 泛型）
- Modify: `agent/tests/test_reasoning_narrator.py`、`test_orchestrator.py`

**Interfaces:** `build_purchase_order_facts`：每条 PO item -> 一条 `ReasoningFact(predicate=purchaseOrderItem, deterministic=true, confidence=1.0, evidence=PO号/供应商/物料/工厂/数量/单位/交货日期)`；空列表不创建 item fact；narrator guard 拒绝 facts 外字段。

**Steps (TDD):**
1. 写 `build_purchase_order_facts` 测试：N 条 PO -> N 条 fact；空列表 -> 无 fact
2. 写 narrator 测试：列表 grounded/空列表"无匹配记录"/超 50 "仅返回前 50 条"/guard 失败
3. 实现 fact builder + narrator
4. 改 `call_plan.py`：`create_call_plan` 不 setdefault unit；`run_inventory_query` 路径 `parameters.setdefault("unit","EA")` 保留 inventory 行为
5. 新增 `run_query(text, gateway)`：parse_intent -> select -> 按 capabilityId 路由 create_call_plan + fact builder + narrator
6. **验证：** `.venv/bin/python -m pytest agent/tests/ -v`（含 inventory 回归）

**Verify:** pytest 全绿

## Task 11: Evals PO OData seed cases

**Files:**
- Modify: `evals/eval_harness_seed_cases.json`（新增 PO seed cases）
- Modify: `agent/sap_nexus_agent/eval.py`（调用 `run_query` 统一入口）
- Modify: `scripts/verify-agent-callplan-evidence.sh`（纳入 PO seed，若需）
- Modify: `agent/tests/test_eval_runner.py`（PO eval 覆盖）

**Interfaces:** PO seed cases：核心成功（vendor 过滤）/参数补全（无过滤澄清）/多参 `$filter`/跨 executor 意图区分/裸 endpoint 拒绝/列表归一/空结果。mock 回归默认运行；live case gated by env flag 默认 skip。

**Steps:**
1. 新增 PO seed cases 到 `eval_harness_seed_cases.json`（mock 期望）
2. 改 `eval.py`：`run_query` 替换 `run_inventory_query`（inventory cases 仍走 inventory 路径）
3. 更新 `test_eval_runner.py`：PO eval 覆盖
4. **验证：** `.venv/bin/python -m sap_nexus_agent.eval evals/eval_harness_seed_cases.json` + `.venv/bin/python -m pytest agent/tests/test_eval_runner.py -v`

**Verify:** eval 通过（inventory 6/6 + PO 新 case 全绿）

## Task 12: live 联调 spike 与验证（gated）

**Files:** 无源码改动（仅 env + 验证记录）

**Steps:**
1. 收敛 Design Doc open question：确认 `API_PURCHASEORDER_PROCESS_SRV` live 可达性、实际 entitySet 字段名、交货日期字段名；若与假设不符，回写 binding/filterMapping
2. live 联调（gated by env flag）：真实 SAP OData 返回 -> `ExecutionResult` + trace（非硬编码）
3. 确认 redaction：destination/token/cookie 不进 trace/log/响应
4. 若 live 不可达，记录为 blocker，mock 回归仍完成

**Verify:** live 联调记录或 blocker 记录

## Task 13: Comet closeout

**Files:**
- Modify: `docs/runbooks/README.md` + 新建/更新对应 runbook（`09-odata-gateway-read-pilot.md`）
- Modify: `docs/wiki/sap-nexus-agent-implementation-roadmap.md`（激活 row 14，记录 §17.2 超越与 §17.4 顺序调整，version bump）
- Modify: `openspec/changes/sap-nexus-odata-gateway-read-pilot/tasks.md`（全勾选）

**Steps:**
1. `git status --short` 确认改动范围
2. `openspec validate --all --strict` 通过
3. `scripts/verify-agent-callplan-evidence.sh` 全量通过
4. `cd services/gateway && gradle test` 通过
5. 更新 runbook + roadmap
6. 运行归档脚本 `node "$COMET_ARCHIVE" sap-nexus-odata-gateway-read-pilot`

**Verify:** 全部命令通过 + 归档完成

## Self-Review Notes

- 本计划对齐 tasks.md 9 组 46 任务，按 Design Doc 迁移顺序拆为 13 个可执行 task。
- 深度代码决策（方案 A / A-1 / 模块边界 / 字段映射）以 Design Doc 为单一事实源，本计划不重复。
- 关键回归保护：每个 Gateway task 后 `gradle test` 全绿；每个 Agent task 后 pytest 全绿；inventory 路径全程不破坏。
- `call_plan.py` 的 `setdefault("unit","EA")` 移到 inventory 路径，PO 路径不设默认 unit（保护 inventory 回归）。
- `IntentParseResult` 新增 `contains_odata_override`（保留 `contains_rfc_name` 不变，避免破坏现有行为）。
- live 联调（Task 12）gated，不阻塞 mock 回归与 closeout。


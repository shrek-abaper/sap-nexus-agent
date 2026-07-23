## 1. Gateway 多模块重构（前置）

- [x] 1.1 新建 `services/gateway/` Gradle 多模块：`services/gateway/core`、`services/gateway/jco`、`services/gateway/odata`、`services/gateway/app`，`services/gateway/settings.gradle` 与各模块 `build.gradle`（`rootProject.name = 'sap-nexus-gateway'`）
- [x] 1.2 从现有根目录 `gateway-jco/` 抽出 `services/gateway/core/`：`TechnicalExecutionRequest`/`Result`、`TechnicalAdapter`、`TechnicalExecutionDispatcher`、`TechnicalRedactor`、`Trace*`、`registry/*`、`api/CapabilityController`/`CapabilityValidationService`/`CapabilityResponse` <!-- Task 1: core 抽出完成；CapabilityController/HealthController 因依赖 jco 类暂留 app 模块（循环依赖约束，Task 2 去耦合后移 core），CapabilityResponse/CapabilityValidationService 在 core -->
- [x] 1.3 JCo 连接器代码迁入 `services/gateway/jco/` 模块：`JcoRfcTechnicalAdapter`、`JcoCapabilityExecutor`、`JcoDestination*`、`InventoryAvailabilityExecutor`、`InMemoryDestinationDataProvider`
- [x] 1.4 新建 `services/gateway/app/` Spring Boot 启动模块，组装 `services/gateway/core`+`services/gateway/jco`（+预留 `services/gateway/odata`），单端点 `:8080`
- [x] 1.5 `services/gateway/core` 的 `TechnicalExecutionDispatcher` 改为按 executor type 路由的 adapter 注册表（替换 `CapabilityController` 内联硬编码 `JCO_RFC` map） <!-- Plan Task 2 完成：ExecutionConfiguration @Bean 收集 Map<String,TechnicalAdapter>，JcoRfcTechnicalAdapter @Component("JCO_RFC")，CapabilityController 注入单例 dispatcher，commit 3edfb85，review PASS -->
- [x] 1.6 `cd services/gateway && gradle test` 全绿（含既有 JCo + dispatcher + redactor + controller 测试），inventory 回归不变 <!-- BUILD SUCCESSFUL, 34 testcases (Task 2 后) -->

## 2. Registry: ODATA 能力与 binding 注册

- [x] 2.1 在 `registry/executor-bindings.yaml` 新增首条 ODATA executor binding（`serviceRef`/`entitySet`/`$filter` mapping/`$top` 上限，仅非敏感 metadata） <!-- Task 3 commit 894f7e3: sap.mm.purchaseorder.list-odata, filterMapping 4 字段, topLimit=50, selectFields 6 字段 -->
- [x] 2.2 在 `registry/capabilities.yaml` 新增 `MM.PurchaseOrder.GetList` capability entry（executor type `ODATA`，4 过滤参数，列表输出 `purchaseOrders`，governance read-only/`not_required`） <!-- Task 3: status=disabled（Task 11 翻 active + evalLinkage） -->
- [x] 2.3 运行 `.venv/bin/python scripts/validate-registry-contract.py registry/capabilities.yaml` 确认 ODATA binding 校验通过 <!-- Registry contract valid -->
- [x] 2.4 运行 `.venv/bin/python -m pytest agent/tests/test_registry_contract.py -v` 确认 registry contract 回归通过 <!-- 13 passed -->

## 3. Gateway: OData 连接器与 dispatcher

> 架构修正 2026-07-09：OData 真实逻辑在 Python `services/odata-service/`（Plan Task 4），Java 侧薄反代 `ODataHttpProxyAdapter`（Plan Task 5）+ dispatcher ODATA 路由（Plan Task 6）。

- [x] 3.1 ~~在 `services/gateway/odata/` 新增 `ODataTechnicalAdapter`~~ -> 改为 Python `services/odata-service/`（Plan Task 4，commit 8dbd994）：`POST /execute` + `filter_builder` + `normalizer` + `odata_client` + `destination`，22 测试绿
- [x] 3.2 在 `services/gateway/core` 的 `TechnicalExecutionDispatcher` 注册 `ODATA` executor type -> `ODataHttpProxyAdapter` 路由（Plan Task 6） <!-- Task 5 @Component("ODATA") 提前注册 + Task 6 集成测试验证, commit 64bf574 -->
- [x] 3.3 ~~`services/gateway/odata/` 内 OData HTTP client~~ -> Python `services/odata-service/odata_client.py`（Plan Task 4，commit 8dbd994）：GET read，`sap-client` header，destination 经 env 注入，CSRF 留扩展点
- [x] 3.4 ~~OData JSON 响应归一为 `TechnicalExecutionResult`~~ -> Python `normalizer.py` 归一为 JSON（Plan Task 4，commit 8dbd994）；Java 侧归一为 TechnicalExecutionResult 在 Plan Task 5
- [x] 3.5 经 `services/gateway/core` 的 `TechnicalRedactor` redact destination URL/token/cookie/authorization header（Plan Task 5 Java 反代侧，commit 73559ee；Python 侧 redaction 已在 Task 4） <!-- MINOR: redactor 不识别 cookie 键(pre-existing), Task 6 顺手补 -->
- [x] 3.6 拒绝 caller 提供的裸 OData URL/endpoint/`$filter`/method/header/credential override（请求所有权守卫）（Plan Task 6） <!-- Task 6 commit 64bf574 + fix 9d57381: 守卫覆盖 OData 系统查询选项($select/$top/$skip/$expand/$count) + 技术安全字段(baseUrl/sapClient/csrf/token/authorization/destination) -->
- [x] 3.7 ~~unit test：mock OData 响应~~ -> Python 22 测试（filter_builder/normalizer/server）覆盖正常/空/HTTP error/JSON 异常/redaction（Plan Task 4，commit 8dbd994）；Java 侧 mock 测试在 Plan Task 5
- [x] 3.8 `cd services/gateway && gradle test` 通过（含 dispatcher 新 ODATA 场景 + 既有 JCO 回归）（Plan Task 6） <!-- 79 tests green (66+13) -->

## 4. Agent: PO 意图解析

- [x] 4.1 `agent/intent.py` 新增 PO 关键词（采购订单/PO/订单）与 `intent="purchase_order_list"` <!-- Task 7 commit 6decacc + fix 74aeedb -->
- [x] 4.2 解析 4 过滤参数（PO 号/供应商/工厂或采购组/物料）为 `parameters` <!-- Task 7: poNumber(10位)/vendor/plant/material -->
- [x] 4.3 "至少一个过滤条件"守卫：无过滤 -> `missing_parameters` + clarification <!-- Task 7 -->
- [x] 4.4 拒绝裸 OData URL/service/`$filter`（扩展 `contains_rfc_name` 或等价机制） <!-- Task 7: contains_odata_override 覆盖 $filter/$select/$top/$skip/$expand/$count + baseUrl/sapClient/csrf/token/authorization + 复数/复合形式, 与 Java 守卫双层对齐 -->
- [x] 4.5 unit test：PO 意图解析覆盖单参/多参/无参澄清/裸 endpoint 拒绝/与库存意图区分 <!-- Task 7: 35 tests (24+11) -->

## 5. Agent: 多能力跨 executor 路由

- [x] 5.1 `capability_selector.py` 从硬编码单 intent 改为 intent->capabilityId 映射表 + 闭集校验 <!-- Task 8 commit a496867 -->
- [x] 5.2 `inventory_availability` -> `MM.Inventory.GetAvailability`，`purchase_order_list` -> `MM.PurchaseOrder.GetList` <!-- Task 8 INTENT_TO_CAPABILITY -->
- [x] 5.3 保留 `UNSUPPORTED_INTENT`/`MISSING_PARAMETER`/`UNSUPPORTED_RFC_NAME` 语义 <!-- Task 8: 含 contains_odata_override -> UNSUPPORTED_RFC_NAME -->
- [x] 5.4 Agent 不感知 executor 类型（`JCO_RFC`/`ODATA`），由 Gateway dispatcher 处理 <!-- Task 8: selector 全程语义层, reviewer 确认 -->
- [x] 5.5 unit test：selector 多能力路由 + 未知 intent 拒绝 + LLM 闭集校验 <!-- Task 8: 58 passed (8 new + 50 existing); llm_intent 补 contains_odata_override 防线 -->

## 6. Agent: 列表结果归一与 narrative

- [x] 6.1 `execution_result.py` 支持列表型输出（`purchaseOrders` 数组） <!-- Task 9: data 泛型 dict 天然支持, 无需改 -->
- [x] 6.2 `call_plan.py` / `gateway_client.py` 适配 PO capability 的 CallPlan 与 Gateway execute <!-- Task 9: call_plan 去 setdefault unit 通用化; gateway_client 通用无需改; orchestrator run_query 路由 -->
- [x] 6.3 `reasoning_fact.py`：列表项归一为多条 `ReasoningFact`（`predicate=purchaseOrderItem`） <!-- Task 9 commit 2e02d10: build_purchase_order_facts -->
- [x] 6.4 `narrator.py`：逐项 grounded narrative；空列表输出"无匹配记录"；超限说明"仅前 N 条" <!-- Task 9: narrate_purchase_order_facts -->
- [x] 6.5 narrator guard：拒绝输出 facts 中不存在的字段 <!-- Task 9: NarrativeGuardError 缺字段 -->
- [x] 6.6 unit test：列表归一 + 空 + 超限 + guard 失败 <!-- Task 9: 88 passed (12 new) -->

## 7. Evals: PO OData seed cases

- [x] 7.1 `evals/` 新增 PO OData seed cases（核心成功/参数补全/多参 `$filter`/意图区分跨 executor/裸 endpoint 拒绝/列表归一/空结果/redaction） <!-- Task 10 commit 7ea25b2: 7 bc_mm_purchaseorder_* cases -->
- [x] 7.2 mock 回归默认运行（不依赖 live SAP） <!-- Task 10: FakeGatewayClient mock, eval 13/13 -->
- [x] 7.3 live 联调 case gated by env flag，默认 skip <!-- Task 11 commit 464db91: SAP_ODATA_LIVE=1 gated, 5 live tests skip by default; ICF 403 blocker 记录 -->
- [x] 7.4 `scripts/verify-agent-callplan-evidence.sh` 纳入 PO seed eval <!-- Task 10: 脚本已含 eval_harness_seed_cases.json, 全量通过 -->
- [x] 7.5 `.venv/bin/python -m sap_nexus_agent.eval` 通过 PO seed <!-- Task 10: Eval passed 13/13 (inventory 6 + PO 7) -->

## 8. live 联调与验证

- [x] 8.1 收敛 design open question：确认 PO OData service `serviceRef`/`entitySet` + `$filter` 字段名 <!-- Task 11: entitySet=A_PurchaseOrder, 单位=PurchaseOrderQuantityUnit (基于 sto-create 参考, 待 live ICF 授权后最终确认) -->
- [x] 8.2 live SAP OData 联调（gated env），确认真实 `ExecutionResult` + trace（非硬编码） <!-- Task 11: BLOCKER - SAP ICF 403 "Service cannot be reached" (SICF 未激活/授权), 非代码问题; mock 回归全绿; live 待 Basis 团队激活 SICF -->
- [x] 8.3 确认 redaction：destination/token/cookie 不进 trace/log/响应 <!-- Task 11: mock 层面验证; live 因 ICF 403 无法验证 -->

## 9. Comet closeout

- [x] 9.1 `git status --short` 确认改动范围 <!-- 工作树干净, 所有改动已提交 -->
- [x] 9.2 `openspec validate --all --strict` 通过 <!-- 6 passed, 0 failed -->
- [x] 9.3 `scripts/verify-agent-callplan-evidence.sh` 全量通过 <!-- pytest 109 passed/1 skipped + eval 7/7 + eval 13/13 + openspec 6/6 -->
- [x] 9.4 更新 `docs/runbooks/README.md` 与新建/更新对应 runbook <!-- commit 9f50eb0: 新建 09-odata-gateway-read-pilot.md + README 更新 -->
- [x] 9.5 更新 `docs/wiki/sap-nexus-agent-implementation-roadmap.md`（激活 row 14，记录 §17.2 超越与 §17.4 顺序调整） <!-- commit 9f50eb0: v0.2.18, row 14 完成, §17 下一推荐 sandbox write -->

> 归档脚本 `node "$COMET_ARCHIVE" sap-nexus-odata-gateway-read-pilot` 由 comet-verify/archive 阶段执行，不在 build tasks.md（build 阶段不归档）。

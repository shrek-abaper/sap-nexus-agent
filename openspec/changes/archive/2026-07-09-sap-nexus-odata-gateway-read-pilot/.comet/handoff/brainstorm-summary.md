# Brainstorm Summary

- Change: sap-nexus-odata-gateway-read-pilot
- Date: 2026-07-08

## 确认的技术方案

### 已定（open 阶段）
- Gradle 多模块：`gateway/{core,jco,odata,app}`，单端点单进程，Agent 只认 capabilityId，Dispatcher 按 executor type 路由
- OData 对等连接器，鉴权通信内聚于 `gateway/odata`
- `capability_selector` intent->capabilityId 映射表 + 闭集校验，Agent 不感知 executor 类型
- 列表结果归一为多条 `ReasoningFact`（`predicate=purchaseOrderItem`）
- 分页仅 `$top`+`$count`，无 `$skip`
- 4 过滤参数全 optional + "至少一个"守卫
- CSRF 第一版按需（read GET 通常不需要）

### design 阶段新增确认
- **OData adapter 取 binding metadata：方案 A** -- `TechnicalExecutionRequest` 契约不变；`ODataTechnicalAdapter` 注入 `CapabilityRegistry` 依赖，按 `bindingId` 自取 `serviceRef`/`entitySet`/`$filter` mapping；参数->$filter 组装在 adapter 内（体现"参数组装在网关内侧"）；JCo 路径零影响。
- **`toExecutionResult` 抽象：方案 A-1** -- `TechnicalExecutionResult.toExecutionResult(capability)` 从 capability 取 executor metadata，移除 `rfcName` 参数；`ExecutorMetadata.rfcName` 改 nullable（OData 传 null）；JCo 路径仍从 `capability.executor().rfcName()` 取，行为不变；Agent 侧 `executor` 是泛型 dict，零感知。Controller 无 if-else 分支。
- **Registry validator 已支持 ODATA binding**：`_require_binding_fields` 按 type 分支，ODATA 要求 `serviceRef`/`entitySet`/`method`（不需 rfcName）。Registry 层无需改 validator。
- **Dispatcher 注册方式**：从 `CapabilityController.execute` 内联 `new TechnicalExecutionDispatcher(Map.of("JCO_RFC", ...))` 改为 Spring Bean 注入的全局 dispatcher（`gateway/core` 配置类注册 JCO_RFC + ODATA adapter bean），Controller 注入单例 dispatcher。
- **模块依赖方向**：`gateway/jco` + `gateway/odata` 依赖 `gateway/core`（TechnicalAdapter/Request/Result/Registry/Redactor/Trace）；`gateway/app` 依赖三者组装。
- **PO OData service**：`API_PURCHASEORDER_PROCESS_SRV`，entitySet=`PurchaseOrder`/`PurchaseOrderItem`，字段 `PurchaseOrder`/`Supplier`/`Plant`/`Material`/`OrderQuantity`/`PurchaseOrderUnit`/交货日期字段。design 按此写，build spike 验证 live 可达性与实际字段名。
- **`$top` 上限 = 50**；`$count` 返回总数；超限 narrative 说明"仅返回前 50 条"。
- **PO 行字段集**（ReasoningFact evidence）：PO号 / 供应商 / 物料 / 工厂 / 数量 / 单位 / 交货日期（全选）。

### 待确认（候选）
- live 联调 destination 配置来源（open question 4）：env/credentialRef -- build 阶段定
- CSRF 是否真需（open question 5）：GET read 多数不需要，build live 验证
- 以上两项不阻塞 Design Doc

## 关键取舍与风险

- [Risk] 多模块重构破坏 JCo 路径 -> 第一步只拆模块不改行为，`cd gateway && gradle test` 全绿才继续
- [Risk] `toExecutionResult(rfcName)` JCo 耦合 -> 需抽象为 executor-agnostic 转换（待确认方案）
- [Risk] live OData service schema 不符 -> mock 回归隔离，design spike 确认字段名
- [Trade-off] §17.2 超越（新增 ODATA family）-- 已确认

## 测试策略

- Gateway：`gateway/core` dispatcher/redactor/controller 既有测试迁移；`gateway/odata` 新增 mock OData 响应测试（正常/空/HTTP error/JSON 异常/redaction）；`gateway/app` 集成测试 JCo+OData 共存
- Agent：intent PO 解析、selector 多能力路由、列表归一、narrator guard 单测；inventory 回归全绿
- Eval：PO OData seed cases（mock 默认 + live gated）
- 验证命令：`cd gateway && gradle test`、`.venv/bin/python scripts/validate-registry-contract.py`、`scripts/verify-agent-callplan-evidence.sh`、`openspec validate --all --strict`

## Spec Patch

- **`gateway-execution-contract` delta spec 补充**：现有 "Technical results remain compatible with capability execution" requirement 的 "Preserve Agent-facing execution result" scenario 提到 `MM.Inventory.GetAvailability`。`toExecutionResult` 改为从 capability 取 metadata 后，该 requirement 行为不变（仍兼容），但建议补一个 OData 列表 result 兼容场景到 `odata-gateway-read` spec（已有 "Normalize non-empty OData collection"）。评估：`gateway-execution-contract` delta **无需 Spec Patch**（toExecutionResult 重构是内部实现，spec 描述的契约不变）；`odata-gateway-read` spec 已覆盖列表归一。如 build 阶段发现契约漂移再补。
- `agent-callplan-evidence` delta 已覆盖多能力路由 + PO 意图 + 列表归一，无需 Spec Patch。

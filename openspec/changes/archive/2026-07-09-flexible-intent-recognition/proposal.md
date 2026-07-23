## Why

当前 Agent 意图识别入口层（`llm_intent.py` / `cli.py`）是为「库存-only 时代」写的，OData 采购订单能力落地后未同步更新，导致已注册的 `MM.PurchaseOrder.GetList` 无法通过自然语言触发：

- 查询「查询采购订单DEMOPO1」返回 `当前仅支持已注册的只读能力（库存可用量查询、采购订单列表）。`
- 根因有三：(1) hybrid 模式 LLM 失败 fallback 调用库存-only 解析器 `parse_inventory_intent` 而非统一解析器 `parse_intent`；(2) LLM prompt 写死「只支持库存（capabilityId=MM.Inventory.GetAvailability），allowed intents 只有 inventory_availability/unsupported」；(3) CLI 入口用 `run_inventory_query` 且 `_payload_to_parse_result` 只认库存意图。
- 下游（`run_query` / `select_capability` / PO fact / PO narrator）已完整支持 PO，问题完全集中在意图识别入口层。

需要将意图识别重构为**柔性识别**：意图闭集从 `registry/capabilities.yaml` 的 active capability 动态派生，LLM prompt 动态注入能力元数据，新增能力只需注册即自动支持（LLM 可用时零代码），并修复规则 fallback 使 PO 等已注册能力在 LLM 不可用时也可查。

## What Changes

- 新增 `agent/sap_nexus_agent/registry_loader.py`：从 `registry/capabilities.yaml` 读取 active capability，派生 `IntentCatalog`（capability 闭集 + 描述符，含 capabilityId/name/description/domain/businessObject/inputs），供 LLM prompt 与闭集校验使用。
- 重构 `agent/sap_nexus_agent/llm_intent.py`：
  - LLM prompt 从「写死库存」改为**动态注入 registry 所有 active capability 的 capabilityId + description + inputs**，LLM 直接选 capabilityId 并提取参数（不再经 intent 名中转）。
  - `_payload_to_parse_result` 增加 **capabilityId 闭集校验**（必须在 registry active 集合内）+ 按 capability inputs 校验 required 参数；不再只认 `inventory_availability`。
  - hybrid/llm 模式 fallback 从 `parse_inventory_intent` 改为 **`parse_intent`**（统一规则解析器，已支持 PO）。
  - `build_intent_adapter(mode, catalog)` 注入 catalog。
- `agent/sap_nexus_agent/intent.py`：`IntentParseResult` 增加 `capability_id: str | None` 字段（LLM 路径填 capabilityId，规则路径填 intent 名）。规则解析器本身行为不变。
- `agent/sap_nexus_agent/capability_selector.py`：`select_capability` 优先用 `parse_result.capability_id`，回退 `INTENT_TO_CAPABILITY.get(intent)`。RFC/OData 拦截、missing_parameters 逻辑不变。
- `agent/sap_nexus_agent/cli.py`：入口从 `run_inventory_query` 改为 `run_query`（统一入口，能路由 PO）；加载 catalog 注入 adapter；help 文案去掉 inventory-only 措辞。
- 不改 `registry/capabilities.yaml` schema（复用现有 description/inputs/businessObject 字段）；不改下游 fact/narrator/gateway/前端事件流。

## Capabilities

### New Capabilities

（无独立新 spec 文件）

### Modified Capabilities

- `capability-registry-gateway`: 新增「柔性意图识别」行为--Agent 意图识别的 capability 闭集从 registry active capability 动态派生，LLM 直接从闭集选 capabilityId，规则 fallback 覆盖已注册的显式意图；新增已注册能力时 LLM 路径自动支持，无需改意图识别代码。

## Impact

- Agent 代码（Python）：
  - 新增 `agent/sap_nexus_agent/registry_loader.py`
  - 修改 `agent/sap_nexus_agent/llm_intent.py`、`intent.py`、`capability_selector.py`、`cli.py`
- 测试：
  - 更新 `agent/tests/test_llm_intent.py`（prompt 不再写死库存、PO LLM 用例、闭集校验、fallback 改 parse_intent）
  - 更新 `agent/tests/test_orchestrator.py`（run_query 经 LLM adapter 选 PO）
  - 新增 `agent/tests/test_registry_loader.py`
  - `agent/tests/test_intent.py` 基本不变（规则解析器不动）
- Registry：不改 schema，不改 `capabilities.yaml` 内容；`validate_registry_contract.py` 不受影响。
- 前端：不改（事件流、intentMode 默认 hybrid 保留）。
- 依赖：无新增（继续用现有 openai-compatible LLM client + PyYAML，后者已是依赖）。
- 验证：`pytest agent/tests`、PO eval、`validate_registry_contract.py`、`openspec validate --all --strict`、`scripts/verify-agent-callplan-evidence.sh` 仍需通过；端到端「查询采购订单DEMOPO1」应返回 PO 列表。

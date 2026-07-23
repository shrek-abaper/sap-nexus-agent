# Brainstorm Summary

- Change: flexible-intent-recognition
- Date: 2026-07-09

## 确认的技术方案

**A 方案为主**：LLM 从 registry active capability 闭集动态选 capabilityId，不改 registry schema。

### 核心架构
- 新增 `registry_loader.py`：`load_intent_catalog()` 读 `registry/capabilities.yaml`，过滤 `status==active`，构建 `IntentCatalog`（capabilities 列表 + capability_ids frozenset）。repo_root 多级回退：`SAP_NEXUS_AGENT_ROOT` env > 向上找 `registry/` > cwd；找不到返回空 catalog（不抛异常，LLM 路径降级 unsupported）。
- `IntentParseResult` 增加 `capability_id: str | None` 字段。LLM 路径填 capability_id（不填 intent），规则路径填 intent（不填 capability_id）。
- `select_capability` 优先用 `parse_result.capability_id`，回退 `INTENT_TO_CAPABILITY.get(intent)`。

### LLM 意图层（llm_intent.py 重构）
- `_messages(text, catalog)`：动态注入所有 active capability 的 `capabilityId + description + inputs`，prompt 改为「从闭集选 capabilityId 并提取参数，都不匹配则 capabilityId=null」。
- `_payload_to_parse_result(payload, catalog)`：capabilityId 闭集校验（不在 active 集合则 unsupported）+ 按选中 capability 的 required inputs 校验参数 + OData/RFC 注入检测保留。LLM 路径填 capability_id 不填 intent。
- 参数 key：保留 `_parameter_key` 别名映射，**扩展含 PO**（poNumber/purchaseOrderNumber、vendor/supplier；plant/material 已有）。别名表全局共享（参数语义跨能力共享）。
- `parse_with_hybrid` fallback：`parse_inventory_intent` -> **`parse_intent`**。
- `build_intent_adapter(mode, catalog)`：**rule 模式也改 `parse_intent`**（三路径一致）；`parse_inventory_intent` 仅保留给 `run_inventory_query` 向后兼容。

### CLI 入口
- `cli.py`：`run_inventory_query` -> `run_query`（统一入口，路由 PO）；加载 catalog 注入 adapter；help 去掉 inventory-only 措辞。

## 关键取舍与风险

- **[LLM 选错 capabilityId]** -> 闭集校验 + required 参数校验兜底；错则 unsupported，不执行。
- **[LLM 不可用时规则 fallback 仅覆盖显式意图]** -> 已修复为 `parse_intent`（PO 可查）；口语变体需 LLM。属 Non-Goal。
- **[IntentParseResult 加字段影响既有测试]** -> 字段默认 None，既有断言不破坏；测试同步更新。
- **[registry 读取路径解析]** -> 多级回退 env > 向上找 registry/ > cwd；测试注入固定路径。
- **[别名表全局 vs 每 capability]** -> 选全局共享（参数语义跨能力），扩展 PO 专属别名。比每 capability 独立别名表简单。
- **[规则路径仍需手动加映射]** -> 规则路径固有局限；LLM 可用时完全柔性。`aliases` 字段留未来扩展口。

## 测试策略

- `test_registry_loader.py`（新）：读真实 capabilities.yaml、active 过滤、闭集含 inventory+PO、inputs 解析。
- `test_llm_intent.py`（更新）：移除「prompt 写死库存」断言；PO LLM 用例（fake client 返回 PO capabilityId + poNumber -> 正确解析）；闭集校验用例（非法 capabilityId -> unsupported）；fallback 改 parse_intent 断言；PO 别名用例。
- `test_orchestrator.py`（更新）：run_query 经 LLM adapter（catalog + fake client）选 PO 集成用例；现有 inventory 用例不破坏。
- `test_intent.py`：不破坏（规则解析器未改行为，仅加字段）。
- 验证：pytest agent/tests + PO eval + validate_registry_contract.py + openspec validate + verify-agent-callplan-evidence.sh + 端到端 CLI 直测「查询采购订单DEMOPO1」返回 PO 列表。

## Spec Patch

无。delta spec 的 6 个验收场景已覆盖确认的方案（柔性闭集、PO 可选、闭集校验、required 参数校验、rule fallback 改 parse_intent、CLI 统一入口）。别名映射属实现细节，不需 spec 场景。

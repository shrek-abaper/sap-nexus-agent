## Context

Agent 意图识别入口层（`llm_intent.py` / `cli.py`）为库存-only 时代编写。OData PO 能力（`MM.PurchaseOrder.GetList`）已注册并已通过 `run_query` + PO fact/narrator 端到端验证（`test_run_query_po_list_success`），但意图识别入口层未同步：

- `llm_intent.py` LLM prompt 写死 `CAPABILITY_ID=MM.Inventory.GetAvailability`，allowed intents 仅 `inventory_availability/unsupported`。
- hybrid fallback 用 `parse_inventory_intent`（库存-only），而非 `parse_intent`（已支持 PO）。
- `cli.py` 入口 `run_inventory_query`，`_payload_to_parse_result` 只认库存意图。

`registry/capabilities.yaml` 每个 active capability 已有 `capabilityId/name/description/domain/businessObject/inputs[]`（含 name/semanticName/required/type），足以派生 LLM prompt 上下文与闭集校验，无需改 schema。LLM 配置已就绪（`.env` 配 DeepSeek-V4-Flash 网关，`available=True`）。

## Goals / Non-Goals

**Goals:**
- 意图闭集从 `registry/capabilities.yaml` active capability 动态派生，LLM prompt 动态注入能力元数据。
- LLM 直接选 capabilityId（不经 intent 名中转）+ 提取参数；闭集校验 + required 参数校验兜底。
- 规则 fallback 修复为 `parse_intent`（支持 PO），LLM 不可用时已注册显式意图可查。
- 新增 active capability 时 LLM 路径自动支持（零代码）。
- CLI 入口改 `run_query`，能路由 PO。
- 不改 registry schema、下游 fact/narrator/gateway、前端事件流。

**Non-Goals:**
- 不改 `registry/capabilities.yaml` schema（不加 intent/keywords 字段，`aliases` 留作未来可选扩展）。
- 不实现规则路径的完全柔性（规则路径仍需在 `intent.py` 显式映射；LLM 不可用时仅覆盖显式意图）。
- 不改前端（intentMode 默认 hybrid 保留，事件流不变）。
- 不改 LLM client（继续 openai-compatible + DeepSeek 网关）。
- 不做多轮上下文、不做 capability 之外的意图（如非 SAP 业务问题）。

## Decisions

### D1: A 方案为主--LLM 从 registry 闭集选 capabilityId，不改 schema

LLM prompt 动态注入所有 active capability 的 `capabilityId + description + inputs`，LLM 选 capabilityId + 提取参数。备选 B（registry 加 intent/keywords 字段）被否：关键词维护反柔性、schema 改动大、规则 fallback 价值有限（LLM 不可用时 A 的 businessObject 粗匹配 + 修复后的 `parse_intent` 已覆盖显式意图）。

### D2: LLM 路径直接输出 capabilityId，不经 intent 名中转

`IntentParseResult` 增加 `capability_id` 字段。LLM 路径填 capability_id（不填 intent），规则路径填 intent（不填 capability_id）。`select_capability` 优先用 `capability_id`，回退 `INTENT_TO_CAPABILITY[intent]`。两路径在 selector 汇合，下游无感。

**为何不统一为 intent 名**：LLM 选 capabilityId 更直接（registry 闭集即 capabilityId），intent 名是规则路径的内部概念。统一到 capabilityId 让 LLM 路径与 registry 闭集天然对齐。

### D3: registry_loader 派生 IntentCatalog

新增 `registry_loader.py`：`load_intent_catalog()` 读 `registry/capabilities.yaml`，过滤 `status==active`，构建 `IntentCatalog`（`capabilities: list[CapabilityDescriptor]` + `capability_ids: frozenset`）。repo_root 解析多级回退：`SAP_NEXUS_AGENT_ROOT` env > 向上查找 `registry/` > cwd。

### D4: 闭集校验 + required 参数校验

`_payload_to_parse_result(payload, catalog)`：
1. capabilityId 必须在 `catalog.capability_ids` 内，否则 intent=None（unsupported）。
2. 按 capabilityId 对应 inputs 校验 required 参数，生成 `missing_parameters` + `clarification`。
3. OData/RFC 注入检测保留（双层防御）。

### D5: fallback 修复为 parse_intent

hybrid/llm 模式 LLM 不可用时回退 `parse_intent`（非 `parse_inventory_intent`）。`parse_intent` 已支持 inventory + purchase_order_list，是规则路径的正确统一入口。

### D6: CLI 入口改 run_query

`cli.py` 从 `run_inventory_query` 改 `run_query`，加载 catalog 注入 adapter。`run_inventory_query` 保留（向后兼容，测试用）。

## Risks / Trade-offs

- **[LLM 选错 capabilityId]** -> 闭集校验 + required 参数校验兜底；错则 unsupported，不执行。
- **[LLM 不可用时规则 fallback 仅覆盖显式意图]** -> 已修复为 `parse_intent`（PO 可查）；口语变体需 LLM。属 Non-Goal。
- **[IntentParseResult 加字段影响既有测试]** -> 字段默认 None，既有断言不破坏；测试同步更新。
- **[registry 读取路径解析（agent cwd 不定）]** -> `load_intent_catalog` 多级回退 env > 向上找 registry/ > cwd；测试注入固定路径。
- **[LLM prompt 随能力增长变长]** -> 当前仅 2 能力，可控；后续可按 domain 分组或摘要。
- **[规则路径仍需手动加映射]** -> 规则路径固有局限；LLM 可用时完全柔性。`aliases` 字段留未来扩展口。

## Migration Plan

纯 agent 侧重构，无数据迁移、无后端部署：

1. 实现 registry_loader + llm_intent 重构 + intent/capability_selector/cli 小改。
2. 更新/新增测试。
3. `pytest agent/tests` + PO eval + `validate_registry_contract.py` + `openspec validate --all --strict` + `verify-agent-callplan-evidence.sh` 通过。
4. 端到端：启动后前端查「查询采购订单DEMOPO1」返回 PO 列表。
5. 归档 change。

**回滚**：`git revert` agent 改动即可，无副作用。

## Open Questions

无。方案 A 已在前序对话确认；LLM 配置已就绪。design 阶段 brainstorming 将细化 LLM prompt 结构与 `capability_id` 字段的细节。

## 1. Registry 派生意图闭集

- [x] 1.1 新增 `agent/sap_nexus_agent/registry_loader.py`：定义 `CapabilityDescriptor` / `InputDescriptor` / `IntentCatalog` dataclass；`load_intent_catalog(repo_root=None)` 读 `registry/capabilities.yaml`，过滤 `status==active`，构建 capabilities 列表 + `capability_ids` frozenset。
- [x] 1.2 repo_root 多级回退解析：`SAP_NEXUS_AGENT_ROOT` env > 向上查找 `registry/` 目录 > cwd；找不到时返回空 catalog 并记录（不抛异常，让 LLM 路径自然降级为 unsupported）。
- [x] 1.3 新增 `agent/tests/test_registry_loader.py`：读真实 capabilities.yaml 派生 catalog、active 过滤、闭集含 inventory + PO、inputs 解析正确。

## 2. IntentParseResult 扩展 capability_id

- [x] 2.1 `agent/sap_nexus_agent/intent.py`：`IntentParseResult` 增加 `capability_id: str | None = None` 字段；规则解析器（`parse_intent`/`parse_inventory_intent`）行为不变，不填 capability_id。
- [x] 2.2 `agent/sap_nexus_agent/capability_selector.py`：`select_capability` 优先用 `parse_result.capability_id`，回退 `INTENT_TO_CAPABILITY.get(parse_result.intent)`；RFC/OData 拦截与 missing_parameters 逻辑不变。

## 3. LLM 意图层柔性重构

- [x] 3.1 `agent/sap_nexus_agent/llm_intent.py`：`_messages(text, catalog)` 动态注入所有 active capability 的 `capabilityId + description + inputs`，prompt 改为「从闭集选 capabilityId 并提取参数，都不匹配则 capabilityId=null」。
- [x] 3.2 `_payload_to_parse_result(payload, catalog)`：capabilityId 闭集校验（不在 active 集合则 intent=None/unsupported）；按选中 capability 的 required inputs 校验参数，生成 missing_parameters + clarification；OData/RFC 注入检测保留；LLM 路径填 `capability_id` 不填 intent。
- [x] 3.3 `parse_with_llm` / `parse_with_hybrid` 接收 catalog 参数；`parse_with_hybrid` fallback 从 `parse_inventory_intent` 改为 **`parse_intent`**。
- [x] 3.4 `build_intent_adapter(mode, catalog)` 注入 catalog；rule 模式也改 `parse_intent`（三路径一致）。

## 4. CLI 入口统一

- [x] 4.1 `agent/sap_nexus_agent/cli.py`：入口从 `run_inventory_query` 改 `run_query`；加载 `load_intent_catalog()` 注入 `build_intent_adapter(mode, catalog)`；help 文案去掉 inventory-only 措辞。
- [x] 4.2 确认 `run_inventory_query` 保留（向后兼容 + 测试用），不删除。

## 5. 测试更新

- [x] 5.1 更新 `agent/tests/test_llm_intent.py`：移除「prompt 写死库存」断言；新增 PO LLM 用例（fake client 返回 PO capabilityId + poNumber -> 正确解析）；新增闭集校验用例（非法 capabilityId -> unsupported）；fallback 改 `parse_intent` 的断言。
- [x] 5.2 更新 `agent/tests/test_orchestrator.py`：补 `run_query` 经 LLM adapter（注入 catalog + fake client）选 PO 的集成用例；确认现有 inventory 用例不破坏。
- [x] 5.3 确认 `agent/tests/test_intent.py` 不破坏（规则解析器未改行为，仅加字段）。

## 6. 验证与端到端

- [x] 6.1 运行 `PYTHONPATH=agent .venv/bin/python -m pytest agent/tests -q` 通过。
- [x] 6.2 运行 `PYTHONPATH=agent .venv/bin/python -m sap_nexus_agent.eval evals/purchase_order_cases.json` 通过（PO eval）。
- [x] 6.3 运行 `.venv/bin/python scripts/validate_registry_contract.py registry/capabilities.yaml` 通过。
- [x] 6.4 运行 `openspec validate --all --strict` 通过。
- [x] 6.5 运行 `scripts/verify-agent-callplan-evidence.sh` 通过。
- [x] 6.6 端到端：CLI 直测 `查询采购订单DEMOPO1` 返回 PO 列表（非 unsupported）。

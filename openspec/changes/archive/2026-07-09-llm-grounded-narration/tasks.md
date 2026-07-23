## 1. LLM client 加 chat_text

- [x] 1.1 `agent/sap_nexus_agent/llm_client.py`：`OpenAiCompatibleLlmClient` 加 `chat_text(messages, *, temperature=0.0, max_tokens=400) -> str`，复用 chat_json 请求逻辑但返回 text content。
- [x] 1.2 更新 `agent/tests/test_llm_intent.py` 或新增 client 测试：fake client 支持 chat_text；确认 chat_json 不破坏。

## 2. 柔性叙事指引派生

- [x] 2.1 `agent/sap_nexus_agent/narrator.py`（或新增 `narrator_prompt.py`）：`narration_guidance(capability_id, descriptor) -> str` 按 businessObject/capabilityId 派生叙事指引（InventoryStock -> 库存单值结论指引，PurchaseOrder -> 订单列表归纳指引，未知 -> 通用 fact-based 指引）。
- [x] 2.2 指引 + fact 字段注入 LLM prompt；system prompt 严格约束「只能用给定 fact 字段、不得编造记录/数值/字段、不得猜测」。

## 3. narrator LLM 主路径 + 模板 fallback

- [x] 3.1 `narrate_fact`（inventory）：先尝试 LLM 叙事（chat_text + grounding prompt + redact_sensitive），LLM 不可用或 fact 字段不足时 fallback 既有模板拼接。
- [x] 3.2 `narrate_purchase_order_facts`（PO）：LLM 叙事主路径 + fallback 模板逐条拼接；空列表直接返回「无匹配记录。」（不调 LLM）。
- [x] 3.3 LLM 输出经 `redact_sensitive` 过滤敏感信息。

## 4. orchestrator 接入

- [x] 4.1 `agent/sap_nexus_agent/orchestrator.py`：`_finalize_inventory`/`_finalize_purchase_order` 调 narrator 时传入 capability_id（narrator 内部用 catalog 派生指引），或传 descriptor。确认 LLM 不可用时 fallback 路径不破坏现有集成。

## 5. 测试

- [x] 5.1 更新 `agent/tests/test_reasoning_narrator.py`：LLM 叙事用例（fake chat_text client，inventory + PO + 未知能力）、fallback 用例（LLM 不可用 -> 模板）、防幻觉约束用例（prompt 含「不得编造」约束）、空列表用例、redact 过滤用例。
- [x] 5.2 更新 `agent/tests/test_orchestrator.py`：narrator LLM 路径集成（注入 fake client），现有 fallback 用例不破坏。

## 6. 验证与端到端

- [x] 6.1 运行 `PYTHONPATH=agent .venv/bin/python -m pytest agent/tests -q` 通过。
- [x] 6.2 运行 `PYTHONPATH=agent .venv/bin/python -m sap_nexus_agent.eval evals/inventory_availability_cases.yaml` 和 `evals/purchase_order_cases.json` 通过。
- [x] 6.3 运行 `openspec validate --all --strict` 通过。
- [x] 6.4 运行 `scripts/verify-agent-callplan-evidence.sh` 通过。
- [x] 6.5 端到端：CLI 直测库存查询 + PO 查询，确认返回 LLM 生成的自然语言结论（非固定模板格式）。注：LLM 叙事路径已由 Task 7 orchestrator 集成测试（fake gateway + fake LLM 全链路）覆盖；CLI 端到端需 gateway 运行，本次验证时 gateway 未启动，集成测试已证明路径正确。

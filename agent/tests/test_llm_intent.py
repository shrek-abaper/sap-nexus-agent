import json

import pytest

from sap_nexus_agent.conversation_context import ConversationContext, LastContext, Turn
from sap_nexus_agent.intent import IntentParseResult
from sap_nexus_agent.llm_client import LlmSettings, LlmUnavailable, load_llm_settings
from sap_nexus_agent.llm_intent import (
    _format_last_context_block,
    _messages,
    _payload_to_parse_result,
    build_intent_adapter,
    parse_with_hybrid,
    parse_with_llm,
)
from sap_nexus_agent.registry_loader import load_intent_catalog


class FakeLlmClient:
    def __init__(self, payload=None, unavailable=False):
        self.payload = payload
        self.unavailable = unavailable
        self.calls = []

    def chat_json(self, messages, *, temperature=0.0, max_tokens=400):
        self.calls.append({"messages": messages, "temperature": temperature, "max_tokens": max_tokens})
        if self.unavailable:
            raise LlmUnavailable("model gateway unavailable")
        if isinstance(self.payload, str):
            return json.loads(self.payload)
        return self.payload


def test_load_llm_settings_reports_missing_config_without_secret(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    settings = load_llm_settings(load_dotenv_file=False)

    assert settings.available is False
    assert "LLM_API_KEY" in settings.missing
    assert "LLM_BASE_URL" in settings.missing
    assert "secret" not in repr(settings).lower()


def test_llm_settings_repr_does_not_expose_api_key():
    settings = LlmSettings(api_key="super-secret-key", base_url="https://model.example", model="DeepSeek-V3")

    assert "super-secret-key" not in repr(settings)
    assert "https://model.example" not in repr(settings)
    assert "***" in repr(settings)


def test_parse_with_llm_happy_path_returns_inventory_parse_result():
    catalog = load_intent_catalog()
    client = FakeLlmClient(
        {
            "capabilityId": "MM.Inventory.GetAvailability",
            "parameters": {"material": "DEMOA1", "plant": "1000", "unit": "EA"},
            "missingParameters": [],
            "clarification": None,
        }
    )

    result = parse_with_llm("帮我查一下 DEMOA1 在 1000 的库存", client, catalog)

    assert result.capability_id == "MM.Inventory.GetAvailability"
    assert result.intent is None
    assert result.parameters == {"material": "DEMOA1", "plant": "1000", "unit": "EA"}
    assert result.missing_parameters == []
    assert client.calls


def test_parse_with_llm_missing_plant_returns_clarification():
    catalog = load_intent_catalog()
    client = FakeLlmClient(
        {
            "capabilityId": "MM.Inventory.GetAvailability",
            "parameters": {"material": "DEMOA1"},
            "missingParameters": ["plant"],
            "clarification": "请提供要查询的工厂。",
        }
    )

    result = parse_with_llm("查一下 DEMOA1 的可用量", client, catalog)

    assert result.capability_id == "MM.Inventory.GetAvailability"
    assert result.intent is None
    assert result.parameters == {"material": "DEMOA1"}
    assert result.missing_parameters == ["plant"]
    assert result.clarification == "请提供要查询的工厂。"


def test_parse_with_llm_accepts_semantic_parameter_aliases_from_real_model():
    catalog = load_intent_catalog()
    client = FakeLlmClient(
        {
            "capabilityId": "MM.Inventory.GetAvailability",
            "parameters": {"materialNumber": "DEMOA1", "plantCode": "1000"},
            "missingParameters": [],
            "clarification": None,
        }
    )

    result = parse_with_llm("请帮我查一下 DEMOA1 在 1000 的可用库存", client, catalog)

    assert result.capability_id == "MM.Inventory.GetAvailability"
    assert result.parameters == {"material": "DEMOA1", "plant": "1000"}
    assert result.missing_parameters == []


def test_parse_with_llm_rejects_rfc_name_output():
    catalog = load_intent_catalog()
    client = FakeLlmClient(
        {
            "capabilityId": "MM.Inventory.GetAvailability",
            "rfcName": "BAPI_MATERIAL_AVAILABILITY",
            "parameters": {"material": "DEMOA1", "plant": "1000"},
        }
    )

    result = parse_with_llm("查库存", client, catalog)

    assert result.contains_rfc_name is True
    assert result.intent is None


def test_parse_with_llm_unknown_capability_is_unsupported():
    catalog = load_intent_catalog()
    client = FakeLlmClient(
        {
            "capabilityId": "MM.Purchase.CreateRequisition",
            "parameters": {"material": "DEMOA1", "plant": "1000"},
        }
    )

    result = parse_with_llm("查库存", client, catalog)

    assert result.intent is None
    assert result.capability_id is None
    assert result.parameters == {}


def test_hybrid_falls_back_to_rule_parser_when_llm_unavailable():
    client = FakeLlmClient(unavailable=True)

    result = parse_with_hybrid("DEMOA1 在 1000 还有多少可用库存？", client, catalog=load_intent_catalog())

    assert result.intent == "inventory_availability"
    assert result.parameters == {"material": "DEMOA1", "plant": "1000"}


def test_hybrid_falls_back_to_rule_parser_when_llm_json_is_malformed():
    client = FakeLlmClient("not-json")

    result = parse_with_hybrid("DEMOA1 在 1000 还有多少可用库存？", client, catalog=load_intent_catalog())

    assert result.intent == "inventory_availability"
    assert result.parameters == {"material": "DEMOA1", "plant": "1000"}


def test_hybrid_returns_llm_result_directly_when_llm_outputs_rfc_name():
    """D2: rfcName LLM result returned directly (flag preserved), rule NOT invoked."""
    catalog = load_intent_catalog()
    client = FakeLlmClient(
        {
            "capabilityId": "MM.Inventory.GetAvailability",
            "rfcName": "BAPI_MATERIAL_AVAILABILITY",
            "parameters": {"material": "WRONG", "plant": "9999"},
        }
    )

    result = parse_with_hybrid("DEMOA1 在 1000 还有多少可用库存？", client, catalog=catalog)

    # LLM result returned directly: intent None (rule not called), flag preserved
    # for the selector/orchestrator to REJECT. No rule re-parse.
    assert result.intent is None
    assert result.capability_id is None
    assert result.parameters == {}
    assert result.contains_rfc_name is True


def test_llm_mode_unavailable_returns_structured_unsupported_result(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "")
    monkeypatch.setenv("LLM_BASE_URL", "")
    adapter = build_intent_adapter("llm")

    result = adapter("DEMOA1 在 1000 还有多少可用库存？")

    assert result.intent is None
    assert result.parameters == {}
    assert result.contains_rfc_name is False


# --- Task 8: LLM path OData-override defense (reviewer fix) ---


def test_parse_with_llm_payload_with_odata_url_sets_override_flag():
    catalog = load_intent_catalog()
    client = FakeLlmClient(
        {
            "capabilityId": "MM.Inventory.GetAvailability",
            "parameters": {
                "material": "DEMOA1",
                "plant": "1000",
                "endpoint": "/sap/opu/odata/sap/API_MATERIAL_STOCK_SRV",
            },
        }
    )

    result = parse_with_llm("查库存", client, catalog)

    assert result.contains_odata_override is True


def test_parse_with_llm_payload_with_dollar_filter_sets_override_flag():
    catalog = load_intent_catalog()
    client = FakeLlmClient(
        {
            "capabilityId": "MM.Inventory.GetAvailability",
            "parameters": {"material": "DEMOA1", "plant": "1000"},
            "clarification": "$filter=Material eq 'DEMOA1'",
        }
    )

    result = parse_with_llm("查库存", client, catalog)

    assert result.contains_odata_override is True


def test_parse_with_llm_payload_with_safety_field_sets_override_flag():
    catalog = load_intent_catalog()
    client = FakeLlmClient(
        {
            "capabilityId": "MM.Inventory.GetAvailability",
            "parameters": {"material": "DEMOA1", "plant": "1000", "baseUrl": "https://evil"},
        }
    )

    result = parse_with_llm("查库存", client, catalog)

    assert result.contains_odata_override is True


def test_parse_with_llm_clean_payload_does_not_set_override_flag():
    catalog = load_intent_catalog()
    client = FakeLlmClient(
        {
            "capabilityId": "MM.Inventory.GetAvailability",
            "parameters": {"material": "DEMOA1", "plant": "1000", "unit": "EA"},
            "missingParameters": [],
            "clarification": None,
        }
    )

    result = parse_with_llm("查库存", client, catalog)

    assert result.contains_odata_override is False


def test_hybrid_returns_llm_result_directly_when_llm_outputs_odata_override():
    """D2: OData-override LLM result returned directly (flag preserved), rule NOT invoked."""
    catalog = load_intent_catalog()
    client = FakeLlmClient(
        {
            "capabilityId": "MM.Inventory.GetAvailability",
            "parameters": {
                "material": "WRONG",
                "plant": "9999",
                "endpoint": "https://evil.example",
            },
        }
    )

    result = parse_with_hybrid("DEMOA1 在 1000 还有多少可用库存？", client, catalog=catalog)

    # LLM result returned directly: intent None (rule not called), flag preserved
    # for the selector/orchestrator to REJECT. No rule re-parse.
    assert result.intent is None
    assert result.capability_id is None
    assert result.parameters == {}
    assert result.contains_odata_override is True


# --- capability_id priority in select_capability ---


def test_select_capability_prefers_capability_id_over_intent():
    from sap_nexus_agent.capability_selector import select_capability

    result = IntentParseResult(
        intent=None,
        capability_id="MM.PurchaseOrder.GetList",
        parameters={"poNumber": "DEMOPO1"},
        missing_parameters=[],
    )

    selected = select_capability(result)

    assert selected.capability_id == "MM.PurchaseOrder.GetList"
    assert selected.error_type is None


def test_select_capability_falls_back_to_intent_mapping():
    from sap_nexus_agent.capability_selector import select_capability

    result = IntentParseResult(
        intent="inventory_availability",
        parameters={"material": "DEMOA1", "plant": "1000"},
        missing_parameters=[],
    )

    selected = select_capability(result)

    assert selected.capability_id == "MM.Inventory.GetAvailability"
    assert selected.error_type is None


# --- Flexible intent: PO via LLM path ---


def test_parse_with_llm_selects_purchase_order():
    catalog = load_intent_catalog()
    client = FakeLlmClient({
        "capabilityId": "MM.PurchaseOrder.GetList",
        "parameters": {"poNumber": "DEMOPO1"},
        "missingParameters": [],
        "clarification": None,
    })

    result = parse_with_llm("查询采购订单DEMOPO1", client, catalog)

    assert result.capability_id == "MM.PurchaseOrder.GetList"
    assert result.intent is None
    assert result.parameters == {"poNumber": "DEMOPO1"}
    assert result.missing_parameters == []


def test_parse_with_llm_rejects_capability_not_in_closed_set():
    catalog = load_intent_catalog()
    client = FakeLlmClient({
        "capabilityId": "MM.Material.CreateBom",
        "parameters": {"material": "X"},
        "missingParameters": [],
        "clarification": None,
    })

    result = parse_with_llm("查物料", client, catalog)

    assert result.capability_id is None
    assert result.intent is None
    assert result.parameters == {}


def test_parse_with_llm_normalizes_po_aliases():
    catalog = load_intent_catalog()
    client = FakeLlmClient({
        "capabilityId": "MM.PurchaseOrder.GetList",
        "parameters": {"purchaseOrderNumber": "DEMOPO1", "supplier": "DEMOV1"},
        "missingParameters": [],
        "clarification": None,
    })

    result = parse_with_llm("查询采购订单", client, catalog)

    assert result.parameters == {"poNumber": "DEMOPO1", "vendor": "DEMOV1"}


def test_parse_with_llm_drops_unregistered_parameter_for_po():
    """LLM 返回 PO 不支持的参数应被丢弃。"""
    catalog = load_intent_catalog()
    client = FakeLlmClient({
        "capabilityId": "MM.PurchaseOrder.GetList",
        "parameters": {"poNumber": "DEMOPO1", "unit": "EA"},
        "missingParameters": [],
        "clarification": None,
    })

    result = parse_with_llm("查询采购订单", client, catalog)

    # unit 不在 PO inputs 中，应被丢弃
    assert result.parameters == {"poNumber": "DEMOPO1"}


def test_hybrid_falls_back_to_parse_intent_for_po():
    """hybrid fallback 应使用 parse_intent（支持 PO），非 parse_inventory_intent。"""
    client = FakeLlmClient(unavailable=True)
    catalog = load_intent_catalog()

    result = parse_with_hybrid("查询采购订单DEMOPO1", client, catalog=catalog)

    # parse_intent 识别 PO 关键词 -> intent="purchase_order_list"
    assert result.intent == "purchase_order_list"
    assert result.parameters.get("poNumber") == "DEMOPO1"
    assert result.capability_id is None  # 规则路径不填 capability_id


def test_hybrid_returns_llm_result_when_capability_id_set():
    """LLM 成功返回 capability_id 时不应 fallback（_requires_safe_fallback 修复验证）。"""
    catalog = load_intent_catalog()
    client = FakeLlmClient({
        "capabilityId": "MM.PurchaseOrder.GetList",
        "parameters": {"poNumber": "DEMOPO1"},
        "missingParameters": [],
        "clarification": None,
    })

    result = parse_with_hybrid("查询采购订单DEMOPO1", client, catalog=catalog)

    # 不应 fallback 到 parse_intent
    assert result.capability_id == "MM.PurchaseOrder.GetList"
    assert result.intent is None


def test_llm_prompt_injects_purchase_order_capability():
    catalog = load_intent_catalog()
    client = FakeLlmClient({
        "capabilityId": "MM.Inventory.GetAvailability",
        "parameters": {"material": "DEMOA1", "plant": "1000"},
        "missingParameters": [],
        "clarification": None,
    })

    parse_with_llm("查库存", client, catalog)

    system_prompt = client.calls[0]["messages"][0]["content"]
    assert "MM.PurchaseOrder.GetList" in system_prompt
    assert "MM.Inventory.GetAvailability" in system_prompt
    # 不再写死库存 only
    assert "inventory intent" not in system_prompt


def test_parse_with_llm_handles_unhashable_capability_id_without_crash():
    """Malformed LLM payload with list-valued capabilityId must not crash (safe-fail)."""
    catalog = load_intent_catalog()
    client = FakeLlmClient({
        "capabilityId": ["MM.Inventory.GetAvailability"],
        "parameters": {"material": "DEMOA1"},
        "missingParameters": [],
        "clarification": None,
    })

    result = parse_with_llm("查库存", client, catalog)

    assert result.capability_id is None
    assert result.intent is None
    assert result.parameters == {}


def test_parse_with_llm_rejects_all_capability_ids_when_catalog_empty():
    """Empty catalog makes every capabilityId fail closed-set validation (safe-fail)."""
    from sap_nexus_agent.registry_loader import IntentCatalog

    empty_catalog = IntentCatalog(capabilities=(), capability_ids=frozenset())
    client = FakeLlmClient({
        "capabilityId": "MM.Inventory.GetAvailability",
        "parameters": {"material": "DEMOA1", "plant": "1000"},
        "missingParameters": [],
        "clarification": None,
    })

    result = parse_with_llm("查库存", client, empty_catalog)

    assert result.capability_id is None
    assert result.parameters == {}


# --- Task 4: LLM path history injection with authority/data separation ---


def test_messages_no_context_returns_base_pair():
    catalog = load_intent_catalog(repo_root=".")
    messages = _messages("查库存", catalog, context=None)
    assert messages[0]["role"] == "system"
    assert messages[-1] == {"role": "user", "content": "查库存"}


def test_messages_with_history_injects_authority_and_data_block():
    catalog = load_intent_catalog(repo_root=".")
    ctx = ConversationContext(
        last_context=LastContext(
            capability_id="MM.Inventory.GetAvailability",
            parameters={"material": "DEMOA2"},
            missing_parameters=["plant"],
            decision_type="CLARIFY",
        ),
        history=(
            Turn(role="user", content="查库存 DEMOA2"),
            Turn(role="assistant", content="请提供工厂。"),
        ),
    )
    messages = _messages("1000", catalog, context=ctx)
    # 第一条：权威契约 system
    assert messages[0]["role"] == "system"
    assert "data" in messages[0]["content"].lower() or "数据" in messages[0]["content"]
    # 第二条：last_context 数据块 human，包裹在 durable_context_data 标签
    assert messages[1]["role"] == "user"
    assert "<durable_context_data>" in messages[1]["content"]
    assert "DEMOA2" in messages[1]["content"]
    # 第三条：历史数据 human，包裹在 durable_context_data 标签
    assert messages[2]["role"] == "user"
    assert "<durable_context_data>" in messages[2]["content"]
    assert "查库存 DEMOA2" in messages[2]["content"]
    # 末尾仍是当前轮 user
    assert messages[-1] == {"role": "user", "content": "1000"}


def test_messages_history_window_caps_at_three_turns():
    catalog = load_intent_catalog(repo_root=".")
    ctx = ConversationContext(
        last_context=None,
        history=tuple(
            Turn(role="user" if i % 2 == 0 else "assistant", content=f"turn{i}")
            for i in range(10)
        ),
    )
    messages = _messages("current", catalog, context=ctx)
    history_block = messages[1]["content"]
    # 近 3 轮 = 6 条 messages；turn0~turn3 被丢弃，turn4~turn9 保留 6 条
    assert "turn4" in history_block
    assert "turn9" in history_block
    assert "turn0" not in history_block


def test_payload_to_parse_result_rejects_injected_capability_id():
    """即使历史注入诱导 LLM 返回非注册 capabilityId，closed-set 仍 reject。"""
    catalog = load_intent_catalog(repo_root=".")
    malicious_payload = {
        "capabilityId": "EVIL.CAPABILITY",  # 非注册
        "parameters": {"material": "X"},
    }
    result = _payload_to_parse_result(malicious_payload, catalog)
    assert result.capability_id is None
    assert result.parameters == {}


# --- Task 1 (D1): last_context data block injection into _messages ---


def test_messages_injects_last_context_block():
    catalog = load_intent_catalog()
    ctx = ConversationContext(
        last_context=LastContext(
            capability_id="MM.Inventory.GetAvailability",
            parameters={"material": "DEMOA2", "plant": "5100"},
            missing_parameters=[],
            decision_type="SELECT",
        ),
        history=None,
    )
    msgs = _messages("这个物料在1000的库存", catalog, context=ctx)

    # authority + last_context block + base_system + base_user
    assert len(msgs) == 4
    assert msgs[0]["role"] == "system"
    assert "<durable_context_data>" in msgs[1]["content"]
    assert "DEMOA2" in msgs[1]["content"]
    assert "MM.Inventory.GetAvailability" in msgs[1]["content"]
    assert "SELECT" in msgs[1]["content"]
    assert msgs[2]["role"] == "system"
    assert msgs[3]["role"] == "user"


def test_messages_without_context_returns_baseline():
    catalog = load_intent_catalog()
    msgs = _messages("DEMOA2 在 5100 的库存", catalog, context=None)
    assert msgs == [msgs[0], msgs[-1]]
    assert msgs[0]["role"] == "system"
    assert msgs[-1]["role"] == "user"


def test_format_last_context_block_structure():
    lc = LastContext(
        capability_id="MM.Inventory.GetAvailability",
        parameters={"material": "DEMOA2"},
        missing_parameters=["plant"],
        decision_type="CLARIFY",
    )
    block = _format_last_context_block(lc)
    assert block["role"] == "user"
    assert "<durable_context_data>" in block["content"]
    assert "MM.Inventory.GetAvailability" in block["content"]
    assert "DEMOA2" in block["content"]
    assert "CLARIFY" in block["content"]


# --- Task 2 (D2): LLM as primary in parse_with_hybrid, rule only on LlmUnavailable ---


class _StubJsonClient:
    """Stub JsonLlmClient returning a preset payload."""
    def __init__(self, payload):
        self._payload = payload
        self.call_count = 0

    def chat_json(self, messages, **kwargs):
        self.call_count += 1
        return self._payload


class _RaisingJsonClient:
    """Stub JsonLlmClient that always raises LlmUnavailable."""
    def chat_json(self, messages, **kwargs):
        raise LlmUnavailable("connection refused")


def test_parse_with_hybrid_uses_llm_result_directly():
    payload = {
        "capabilityId": "MM.Inventory.GetAvailability",
        "parameters": {"material": "DEMOA2", "plant": "1000"},
    }
    client = _StubJsonClient(payload)
    result = parse_with_hybrid("DEMOA2 在 1000 的库存", client=client)
    assert result.capability_id == "MM.Inventory.GetAvailability"
    assert result.parameters == {"material": "DEMOA2", "plant": "1000"}
    assert client.call_count == 1


def test_parse_with_hybrid_falls_back_to_rule_on_llm_unavailable():
    ctx = ConversationContext(
        last_context=LastContext(
            capability_id="MM.Inventory.GetAvailability",
            parameters={"material": "DEMOA2"},
            missing_parameters=[],
            decision_type="SELECT",
        ),
        history=None,
    )
    # No primary keyword in text -> resolve_with_context inherits last_context
    # capability_id and merges plant extracted from "1000" (brief intent: 继承).
    result = parse_with_hybrid("1000", client=_RaisingJsonClient(), context=ctx)
    # rule 兜底应走 parse_intent(text, context=context) -> resolve_with_context（Task 4 实现继承）
    assert result.capability_id == "MM.Inventory.GetAvailability"
    assert result.parameters.get("plant") == "1000"


def test_parse_with_hybrid_empty_llm_return_does_not_invoke_rule(monkeypatch):
    """LLM 空返回时不再回退 rule（D2）；clarification 由 Task 3 填充。"""
    rule_calls = []
    original_parse_intent = __import__("sap_nexus_agent.intent", fromlist=["parse_intent"]).parse_intent

    def spy_parse_intent(text, context=None):
        rule_calls.append(text)
        return original_parse_intent(text, context=context)

    monkeypatch.setattr("sap_nexus_agent.llm_intent.parse_intent", spy_parse_intent)

    payload = {"capabilityId": None, "parameters": {}}
    client = _StubJsonClient(payload)
    result = parse_with_hybrid("完全不匹配的无关文本", client=client)
    assert client.call_count == 1
    assert rule_calls == []  # rule 未被调用
    assert result.capability_id is None


# --- Task 3 (Q3): LLM empty return fills generic clarification -> CLARIFY ---


def test_payload_empty_capabilityId_fills_clarification():
    catalog = load_intent_catalog()
    result = _payload_to_parse_result({"capabilityId": None, "parameters": {}}, catalog)
    assert result.capability_id is None
    assert result.clarification is not None
    assert "物料" in result.clarification or "工厂" in result.clarification or "明确" in result.clarification


def test_payload_unknown_capability_fills_clarification():
    catalog = load_intent_catalog()
    result = _payload_to_parse_result({"capabilityId": "MM.Bogus.Capability"}, catalog)
    assert result.capability_id is None
    assert result.clarification is not None


def test_payload_all_candidates_unknown_fills_clarification():
    catalog = load_intent_catalog()
    payload = {"candidates": [{"capabilityId": "MM.Bogus.A"}, {"capabilityId": "MM.Bogus.B"}]}
    result = _payload_to_parse_result(payload, catalog)
    assert result.capability_id is None
    assert result.clarification is not None


def test_payload_descriptor_none_fills_clarification():
    """Defensive path: capability_id in capability_ids but catalog.find returns None.

    Constructs a synthetic catalog where ``capability_ids`` advertises a
    capability that ``capabilities`` does not contain, so ``find()`` returns
    None. This is the third empty-return path in ``_payload_to_parse_result``.
    """
    from sap_nexus_agent.registry_loader import IntentCatalog

    synthetic = IntentCatalog(
        capabilities=(),
        capability_ids=frozenset({"MM.Bogus.Orphan"}),
    )
    result = _payload_to_parse_result({"capabilityId": "MM.Bogus.Orphan"}, synthetic)
    assert result.capability_id is None
    assert result.clarification is not None


def test_payload_rfc_name_path_has_no_clarification():
    """rfcName flag path is a REJECT case (selector step 1), must NOT get clarification."""
    catalog = load_intent_catalog()
    result = _payload_to_parse_result(
        {"capabilityId": "MM.Inventory.GetAvailability", "rfcName": "BAPI_X"}, catalog
    )
    assert result.capability_id is None
    assert result.clarification is None
    assert result.contains_rfc_name is True


def test_payload_odata_override_path_has_no_clarification():
    """OData flag path is a REJECT case (selector step 1), must NOT get clarification."""
    catalog = load_intent_catalog()
    result = _payload_to_parse_result(
        {"capabilityId": "MM.Inventory.GetAvailability", "endpoint": "/sap/opu/odata"}, catalog
    )
    assert result.capability_id is None
    assert result.clarification is None
    assert result.contains_odata_override is True


# --- Task 5: multi_parameters field + LLM multiParameters parsing ---


def test_payload_parses_multi_parameters():
    catalog = load_intent_catalog()
    payload = {
        "capabilityId": "MM.Inventory.GetAvailability",
        "parameters": {},
        "multiParameters": {"plant": ["5200", "1000"], "material": ["DEMOA2", "DEMOA4"]},
    }
    result = _payload_to_parse_result(payload, catalog)
    assert result.capability_id == "MM.Inventory.GetAvailability"
    assert result.multi_parameters == {
        "plant": ["5200", "1000"],
        "material": ["DEMOA2", "DEMOA4"],
    }


def test_payload_multi_parameters_defaults_empty():
    catalog = load_intent_catalog()
    payload = {
        "capabilityId": "MM.Inventory.GetAvailability",
        "parameters": {"material": "DEMOA2", "plant": "5100"},
    }
    result = _payload_to_parse_result(payload, catalog)
    assert result.multi_parameters == {}


def test_payload_multi_parameters_ignores_non_list_values():
    catalog = load_intent_catalog()
    payload = {
        "capabilityId": "MM.Inventory.GetAvailability",
        "parameters": {},
        "multiParameters": {"plant": "5200"},
    }
    result = _payload_to_parse_result(payload, catalog)
    assert result.multi_parameters == {}


def test_messages_base_system_contains_multi_value_guidance():
    catalog = load_intent_catalog()
    msgs = _messages("DEMOA2 和 DEMOA4 在 5200、1000 的库存", catalog, context=None)
    system_content = msgs[0]["content"]
    assert "multiParameters" in system_content
    assert "数组" in system_content or "array" in system_content.lower()


# Runbook 14: LLM payload -> IntentEnvelope conversion.
def test_payload_to_envelope_single_capability():
    """payload_to_envelope produces IntentEnvelope with created_by='llm'."""
    from sap_nexus_agent.llm_intent import payload_to_envelope
    from sap_nexus_agent.intent_envelope import IntentEnvelope

    payload = {
        "capabilityId": "MM.Inventory.GetAvailability",
        "parameters": {"material": "DEMOA2", "plant": "1000"},
    }
    catalog = _load_catalog()
    envelope = payload_to_envelope(
        payload,
        catalog,
        utterance="查库存 DEMOA2 1000",
        snapshot_id="snap-001",
        visible_capability_ids=frozenset(("MM.Inventory.GetAvailability",)),
    )
    assert isinstance(envelope, IntentEnvelope)
    assert envelope.created_by == "llm"
    assert envelope.snapshot_id == "snap-001"
    assert len(envelope.envelope_id) > 0
    assert len(envelope.goals) == 1
    assert envelope.goals[0].capability_hint == "MM.Inventory.GetAvailability"
    assert envelope.goals[0].parameters["material"] == "DEMOA2"


def test_payload_to_envelope_unknown_capability_discarded():
    """Unknown capability_id is discarded with structured reason."""
    from sap_nexus_agent.llm_intent import payload_to_envelope

    payload = {"capabilityId": "Foo.Bar", "parameters": {}}
    catalog = _load_catalog()
    envelope = payload_to_envelope(
        payload,
        catalog,
        utterance="x",
        snapshot_id="snap-001",
        visible_capability_ids=frozenset(("MM.Inventory.GetAvailability",)),
    )
    assert envelope.created_by == "llm"
    assert len(envelope.goals) == 0
    assert "unknown_capability:Foo.Bar" in envelope.discard_reasons


def test_payload_to_envelope_technical_field_discarded():
    """Technical field in parameters is discarded with reason."""
    from sap_nexus_agent.llm_intent import payload_to_envelope

    payload = {
        "capabilityId": "MM.Inventory.GetAvailability",
        "parameters": {"material": "DEMOA2", "baseUrl": "http://x"},
    }
    catalog = _load_catalog()
    envelope = payload_to_envelope(
        payload,
        catalog,
        utterance="x",
        snapshot_id="snap-001",
        visible_capability_ids=frozenset(("MM.Inventory.GetAvailability",)),
    )
    assert "technical_field:baseUrl" in envelope.discard_reasons
    # baseUrl must NOT leak into goal parameters.
    assert "baseUrl" not in envelope.goals[0].parameters


def test_payload_to_envelope_multi_candidate():
    """Multi-candidate payload produces multiple goals."""
    from sap_nexus_agent.llm_intent import payload_to_envelope

    payload = {
        "candidates": [
            {"capabilityId": "MM.Inventory.GetAvailability", "parameters": {"material": "DEMOA2"}},
            {"capabilityId": "MM.PurchaseOrder.GetList", "parameters": {}},
        ]
    }
    catalog = _load_catalog()
    visible = frozenset(("MM.Inventory.GetAvailability", "MM.PurchaseOrder.GetList"))
    envelope = payload_to_envelope(
        payload, catalog, utterance="x", snapshot_id="snap-001", visible_capability_ids=visible
    )
    assert len(envelope.goals) == 2
    hints = {g.capability_hint for g in envelope.goals}
    assert "MM.Inventory.GetAvailability" in hints
    assert "MM.PurchaseOrder.GetList" in hints


def test_payload_to_envelope_model_evidence_populated():
    """model_evidence contains a summary of the LLM payload."""
    from sap_nexus_agent.llm_intent import payload_to_envelope

    payload = {
        "capabilityId": "MM.Inventory.GetAvailability",
        "parameters": {"material": "DEMOA2", "plant": "1000"},
    }
    catalog = _load_catalog()
    envelope = payload_to_envelope(
        payload,
        catalog,
        utterance="x",
        snapshot_id="snap-001",
        visible_capability_ids=frozenset(("MM.Inventory.GetAvailability",)),
    )
    assert envelope.model_evidence  # non-empty
    assert "capabilityId" in envelope.model_evidence or "candidates" in envelope.model_evidence


def _load_catalog():
    from sap_nexus_agent.registry_loader import load_intent_catalog
    from pathlib import Path
    repo_root = Path(__file__).resolve().parents[2]
    return load_intent_catalog(str(repo_root))

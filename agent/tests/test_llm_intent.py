import json

import pytest

from sap_nexus_agent.intent import IntentParseResult
from sap_nexus_agent.llm_client import LlmSettings, LlmUnavailable, load_llm_settings
from sap_nexus_agent.llm_intent import build_intent_adapter, parse_with_hybrid, parse_with_llm
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


def test_hybrid_falls_back_to_rule_parser_when_llm_outputs_rfc_name():
    catalog = load_intent_catalog()
    client = FakeLlmClient(
        {
            "capabilityId": "MM.Inventory.GetAvailability",
            "rfcName": "BAPI_MATERIAL_AVAILABILITY",
            "parameters": {"material": "WRONG", "plant": "9999"},
        }
    )

    result = parse_with_hybrid("DEMOA1 在 1000 还有多少可用库存？", client, catalog=catalog)

    assert result.intent == "inventory_availability"
    assert result.parameters == {"material": "DEMOA1", "plant": "1000"}
    assert result.contains_rfc_name is False


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


def test_hybrid_falls_back_to_rule_parser_when_llm_outputs_odata_override():
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

    # Rule parser re-parses the clean user text -> no override, correct params.
    assert result.intent == "inventory_availability"
    assert result.parameters == {"material": "DEMOA1", "plant": "1000"}
    assert result.contains_odata_override is False


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

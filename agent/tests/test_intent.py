import json

import pytest

from sap_nexus_agent.capability_selector import select_capability
from sap_nexus_agent.conversation_context import ConversationContext, LastContext
from sap_nexus_agent.intent import IntentParseResult, parse_inventory_intent, parse_intent
from sap_nexus_agent.llm_client import LlmUnavailable
from sap_nexus_agent.llm_intent import parse_with_llm
from sap_nexus_agent.match_decision import MatchedIntent
from sap_nexus_agent.registry_loader import load_intent_catalog


def test_parse_complete_chinese_inventory_query():
    result = parse_inventory_intent("DEMOA1 在 1000 还有多少可用库存？")
    assert result.intent == "inventory_availability"
    assert result.parameters == {"material": "DEMOA1", "plant": "1000"}
    assert result.missing_parameters == []


def test_parse_optional_unit():
    result = parse_inventory_intent("查一下 DEMOA1 在 1000 的 EA 可用量")
    assert result.parameters["unit"] == "EA"


def test_missing_plant_clarifies_without_selection():
    result = parse_inventory_intent("查一下 DEMOA1 的可用量")
    assert result.missing_parameters == ["plant"]
    assert "工厂" in result.clarification


def test_missing_material_clarifies_without_selection():
    result = parse_inventory_intent("查一下 1000 工厂还有多少可用库存")
    assert result.missing_parameters == ["material"]
    assert "物料" in result.clarification


def test_complete_query_selects_inventory_capability():
    parsed = parse_inventory_intent("DEMOA1 在 1000 还有多少可用库存？")
    selected = select_capability(parsed)
    assert selected.capability_id == "MM.Inventory.GetAvailability"
    assert selected.error_type is None


def test_unknown_intent_is_not_selected():
    parsed = parse_inventory_intent("帮我创建一张采购申请")
    selected = select_capability(parsed)
    assert selected.capability_id is None
    assert selected.error_type == "UNSUPPORTED_INTENT"


def test_user_supplied_rfc_name_is_rejected():
    parsed = parse_inventory_intent("用 rfcName=BAPI_PO_CREATE1 查 DEMOA1 在 1000 的库存")
    selected = select_capability(parsed)
    assert selected.capability_id is None
    assert selected.error_type == "UNSUPPORTED_RFC_NAME"


# --- Purchase order intent parsing (Task 7) ---


def test_parse_intent_po_by_vendor():
    result = parse_intent("查供应商 DEMOV1 的采购订单")
    assert result.intent == "purchase_order_list"
    assert result.parameters == {"vendor": "DEMOV1"}
    assert result.missing_parameters == []
    assert result.clarification is None


def test_parse_intent_po_by_plant_and_material():
    result = parse_intent("查工厂 1000 物料 MAT001 的采购订单")
    assert result.intent == "purchase_order_list"
    assert result.parameters == {"plant": "1000", "material": "MAT001"}
    assert result.missing_parameters == []
    assert result.clarification is None


def test_parse_intent_po_by_po_number():
    result = parse_intent("查采购订单 4500000001")
    assert result.intent == "purchase_order_list"
    assert result.parameters == {"poNumber": "4500000001"}
    assert result.missing_parameters == []
    assert result.clarification is None


def test_parse_intent_po_no_filter_clarifies():
    result = parse_intent("帮我看看采购订单")
    assert result.intent == "purchase_order_list"
    assert result.parameters == {}
    assert result.missing_parameters == ["filter"]
    assert result.clarification is not None
    assert "过滤" in result.clarification


def test_parse_intent_distinguishes_inventory_vs_po():
    inventory = parse_intent("查库存")
    assert inventory.intent == "inventory_availability"

    po = parse_intent("查采购订单")
    assert po.intent == "purchase_order_list"


def test_parse_intent_po_query_has_no_odata_override():
    result = parse_intent("查供应商 DEMOV1 的采购订单")
    assert result.contains_odata_override is False


def test_parse_intent_detects_raw_odata_url():
    result = parse_intent("用 /sap/opu/odata/sap/API_PURCHASEORDER_PROCESS_SRV 查采购订单")
    assert result.contains_odata_override is True


def test_parse_intent_detects_dollar_select_injection():
    result = parse_intent("查采购订单 $select=PurchaseOrder")
    assert result.contains_odata_override is True


def test_parse_intent_detects_dollar_filter_injection():
    result = parse_intent("查采购订单 $filter=Supplier eq 'DEMOV1'")
    assert result.contains_odata_override is True


def test_parse_intent_detects_technical_endpoint_override():
    result = parse_intent("查采购订单 endpoint=https://sap.example")
    assert result.contains_odata_override is True


def test_parse_intent_detects_method_header_credential_override():
    result = parse_intent("查采购订单 method=GET header=Authorization credential=secret")
    assert result.contains_odata_override is True


def test_parse_intent_detects_dollar_top_skip_expand_count():
    result = parse_intent("查采购订单 $top=10 $skip=5 $expand=Items $count=true")
    assert result.contains_odata_override is True


def test_parse_intent_po_number_not_confused_with_vendor():
    # 10-digit vendor must be vendor, not poNumber
    result = parse_intent("查供应商 1000000001 的采购订单")
    assert result.parameters == {"vendor": "1000000001"}
    assert "poNumber" not in result.parameters


def test_parse_intent_routes_inventory_via_unified_entry():
    result = parse_intent("DEMOA1 在 1000 还有多少可用库存？")
    assert result.intent == "inventory_availability"
    assert result.parameters == {"material": "DEMOA1", "plant": "1000"}


def test_parse_intent_unknown_returns_none_intent():
    result = parse_intent("帮我查一下今天的天气")
    assert result.intent is None
    assert result.parameters == {}


def test_parse_inventory_intent_backward_compat_still_inventory_only():
    # parse_inventory_intent must NOT route to PO even for PO text
    result = parse_inventory_intent("查供应商 DEMOV1 的采购订单")
    assert result.intent is None


def test_intent_parse_result_has_odata_override_field():
    result = IntentParseResult(intent=None, parameters={}, missing_parameters=[])
    assert result.contains_odata_override is False


# --- Task 7 review fixes: safety-field coverage + CJK-adjacent PO number ---


# Java-side CapabilityRequest guard (Task 6 fix 9d57381) covers these five
# safety fields; the Agent layer must reject them too (double-layer defense).
@pytest.mark.parametrize(
    "override",
    [
        "baseUrl=https://evil",
        "sapClient=100",
        "csrf=token",
        "token=bearer",
        "authorization=Basic",
    ],
)
def test_parse_intent_detects_java_guard_safety_fields(override):
    result = parse_intent(f"查采购订单 {override}")
    assert result.contains_odata_override is True


# \b...\b word boundaries miss plural / compound forms; these must be detected
# to stay consistent with the Java guard's normalized contains/equals check.
@pytest.mark.parametrize(
    "override",
    [
        "headers=x",
        "credentialRef=x",
        "credentials=x",
        "serviceUrl=x",
        "servicePath=x",
    ],
)
def test_parse_intent_detects_plural_compound_technical_fields(override):
    result = parse_intent(f"查采购订单 {override}")
    assert result.contains_odata_override is True


def test_parse_intent_po_number_cjk_adjacent_no_space():
    # Python 3 \w includes CJK, so \b does not fire between a CJK char and a
    # digit. A 10-digit PO number directly adjacent to CJK must still parse.
    result = parse_intent("查采购订单4500000001")
    assert result.intent == "purchase_order_list"
    assert result.parameters.get("poNumber") == "4500000001"


# --- Task 8: multi-capability selector routing (intent -> capabilityId map) ---


def test_selector_routes_inventory_to_get_availability():
    parsed = parse_intent("DEMOA1 在 1000 还有多少可用库存？")
    selected = select_capability(parsed)
    assert selected.capability_id == "MM.Inventory.GetAvailability"
    assert selected.error_type is None


def test_selector_routes_purchase_order_to_get_list():
    parsed = parse_intent("查供应商 DEMOV1 的采购订单")
    selected = select_capability(parsed)
    assert selected.capability_id == "MM.PurchaseOrder.GetList"
    assert selected.error_type is None


def test_selector_rejects_purchase_order_without_filter_as_missing_parameter():
    parsed = parse_intent("帮我看看采购订单")
    selected = select_capability(parsed)
    # Task 10: CLARIFY carries capability_id for sticky continuation, so a PO
    # query without filter retains the PO capability id on the MatchDecision.
    assert selected.capability_id == "MM.PurchaseOrder.GetList"
    # select_capability now returns MatchDecision (S2-A): a PO query without
    # filter is a CLARIFY decision carrying missing_parameters, not a
    # SelectionResult with error_type="MISSING_PARAMETER".
    assert selected.decision_type == "CLARIFY"
    assert selected.missing_parameters == ["filter"]


def test_selector_rejects_unknown_intent_as_unsupported():
    parsed = parse_intent("帮我查一下今天的天气")
    selected = select_capability(parsed)
    assert selected.capability_id is None
    assert selected.error_type == "UNSUPPORTED_INTENT"


def test_selector_rejects_odata_override_as_unsupported_rfc_name():
    parsed = parse_intent("查采购订单 $filter=Supplier eq 'DEMOV1'")
    selected = select_capability(parsed)
    assert selected.capability_id is None
    assert selected.error_type == "UNSUPPORTED_RFC_NAME"


def test_selector_rejects_odata_url_override_as_unsupported_rfc_name():
    parsed = parse_intent("用 /sap/opu/odata/sap/API_PURCHASEORDER_PROCESS_SRV 查采购订单")
    selected = select_capability(parsed)
    assert selected.capability_id is None
    assert selected.error_type == "UNSUPPORTED_RFC_NAME"


def test_selector_rejects_rfc_name_override_as_unsupported_rfc_name():
    parsed = parse_intent("用 rfcName=BAPI_PO_GETLIST 查采购订单")
    selected = select_capability(parsed)
    assert selected.capability_id is None
    assert selected.error_type == "UNSUPPORTED_RFC_NAME"


# --- Task 2: multi-intent detection (D-1 fix) ---
#
# Bug D-1: parse_intent used first-match ordering (inventory -> purchase_order ->
# pr_create), so a multi-goal utterance like "DEMOA2 在 5100 的库存，再列出
# 近 30 天未清采购订单" was silently reduced to inventory only. Fix: scan ALL
# capability keyword sets, collect matched_intents; selector (Task 3) emits
# ESCALATE_TO_PLANNER when matched_intents length > 1.


def test_intent_parse_result_matched_intents_defaults_to_empty():
    """Backward compat: existing construction without matched_intents still works."""
    result = IntentParseResult(intent=None, parameters={}, missing_parameters=[])
    assert result.matched_intents == []


def test_parse_intent_multi_goal_inventory_and_po_collects_two_matched_intents():
    """D-1 fix core: multi-goal utterance must surface BOTH matched capabilities."""
    text = "DEMOA2 在 5100 的库存，再列出近 30 天未清采购订单"
    result = parse_intent(text)

    assert len(result.matched_intents) == 2
    capability_ids = {m.capability_id for m in result.matched_intents}
    assert capability_ids == {"MM.Inventory.GetAvailability", "MM.PurchaseOrder.GetList"}
    # Multi-intent: top-level intent/capability_id None (selector decides ESCALATE).
    assert result.intent is None
    assert result.capability_id is None
    # Each MatchedIntent carries its own parameters so the planner can compose.
    inv = next(m for m in result.matched_intents if m.capability_id == "MM.Inventory.GetAvailability")
    assert inv.parameters == {"material": "DEMOA2", "plant": "5100"}
    assert inv.missing == []


def test_parse_intent_single_inventory_not_misjudged_as_multi():
    """Single-intent utterance must not be misjudged as multi-intent."""
    text = "DEMOA2 在 5100 还有多少可用库存"
    result = parse_intent(text)

    assert len(result.matched_intents) == 1
    assert result.matched_intents[0].capability_id == "MM.Inventory.GetAvailability"
    # Single-intent path keeps existing extraction (backward compat).
    assert result.intent == "inventory_availability"
    assert result.parameters == {"material": "DEMOA2", "plant": "5100"}
    assert result.missing_parameters == []


def test_parse_intent_po_with_order_substring_not_misjudged_as_multi():
    """PO main keyword "采购订单" contains weak keyword "订单"; must not double-count.

    Per Design Doc §"错误处理与边界条件": single intent containing multiple
    keywords (e.g. "采购订单" containing "订单") must not be misjudged as ESCALATE.
    """
    text = "采购订单 4500000001"
    result = parse_intent(text)

    assert len(result.matched_intents) == 1
    assert result.matched_intents[0].capability_id == "MM.PurchaseOrder.GetList"
    assert result.intent == "purchase_order_list"
    assert result.parameters == {"poNumber": "4500000001"}


def test_parse_intent_single_pr_create_not_misjudged_as_multi():
    """PR create keywords must not cross-trigger inventory or PO."""
    text = "建PR 物料 MAT001 工厂 1000 数量 10 EA 交货日期 2026-08-01 采购组 G01"
    result = parse_intent(text)

    assert len(result.matched_intents) == 1
    assert result.matched_intents[0].capability_id == "MM.PR.CreateDraft"
    assert result.intent == "pr_create"
    assert result.capability_id == "MM.PR.CreateDraft"


def test_parse_intent_multi_goal_inventory_and_pr_collects_two_matched_intents():
    text = (
        "DEMOA2 在 5100 的库存，再帮我建PR 物料 DEMOA2 工厂 5100 "
        "数量 10 EA 交货日期 2026-08-01 采购组 G01"
    )
    result = parse_intent(text)

    assert len(result.matched_intents) == 2
    capability_ids = {m.capability_id for m in result.matched_intents}
    assert capability_ids == {"MM.Inventory.GetAvailability", "MM.PR.CreateDraft"}
    assert result.intent is None
    assert result.capability_id is None


def test_parse_intent_multi_goal_po_and_pr_collects_two_matched_intents():
    text = (
        "查采购订单 4500000001，再帮我建采购申请 物料 MAT001 工厂 1000 "
        "数量 10 EA 交货日期 2026-08-01 采购组 G01"
    )
    result = parse_intent(text)

    assert len(result.matched_intents) == 2
    capability_ids = {m.capability_id for m in result.matched_intents}
    assert capability_ids == {"MM.PurchaseOrder.GetList", "MM.PR.CreateDraft"}
    assert result.intent is None


def test_parse_intent_multi_goal_three_capabilities_collects_three_matched_intents():
    text = (
        "查 DEMOA2 在 5100 的库存，再列出采购订单 4500000001，"
        "最后帮我建PR 物料 DEMOA2 工厂 5100 数量 10 EA 交货日期 2026-08-01 采购组 G01"
    )
    result = parse_intent(text)

    assert len(result.matched_intents) == 3
    capability_ids = {m.capability_id for m in result.matched_intents}
    assert capability_ids == {
        "MM.Inventory.GetAvailability",
        "MM.PurchaseOrder.GetList",
        "MM.PR.CreateDraft",
    }
    assert result.intent is None
    assert result.capability_id is None


def test_parse_intent_unknown_returns_empty_matched_intents():
    text = "帮我查一下今天的天气"
    result = parse_intent(text)

    assert result.matched_intents == []
    assert result.intent is None


def test_parse_intent_multi_goal_preserves_rfc_name_detection():
    """Technical override (rfcName) takes priority over multi-intent collection."""
    text = "DEMOA2 在 5100 的库存，再列出采购订单 rfcName=BAPI_PO_GETLIST"
    result = parse_intent(text)

    assert result.contains_rfc_name is True
    # Rejection path: matched_intents not collected (selector emits REJECT).
    assert result.matched_intents == []
    assert result.intent is None


def test_parse_intent_multi_goal_preserves_odata_override_detection():
    """Technical override (OData) takes priority over multi-intent collection."""
    text = "DEMOA2 在 5100 的库存，再查采购订单 $filter=Supplier eq 'DEMOV1'"
    result = parse_intent(text)

    assert result.contains_odata_override is True
    assert result.matched_intents == []
    assert result.intent is None


def test_parse_inventory_intent_populates_matched_intents_when_inventory_match():
    """Backward-compat inventory-only parser also populates matched_intents."""
    result = parse_inventory_intent("DEMOA1 在 1000 还有多少可用库存？")

    assert len(result.matched_intents) == 1
    assert result.matched_intents[0].capability_id == "MM.Inventory.GetAvailability"
    assert result.matched_intents[0].parameters == {"material": "DEMOA1", "plant": "1000"}
    assert result.matched_intents[0].missing == []


def test_parse_inventory_intent_matched_intents_empty_when_no_inventory_match():
    result = parse_inventory_intent("查供应商 DEMOV1 的采购订单")

    assert result.matched_intents == []
    assert result.intent is None


# --- Task 2: LLM path multi-candidate detection (D-1 fix) ---


class _FakeLlmClient:
    """Minimal fake matching JsonLlmClient protocol; reused for LLM multi-intent tests."""

    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def chat_json(self, messages, *, temperature: float = 0.0, max_tokens: int = 400):
        self.calls.append({"messages": messages, "temperature": temperature, "max_tokens": max_tokens})
        if isinstance(self.payload, str):
            return json.loads(self.payload)
        return self.payload


def test_parse_with_llm_multi_candidates_returns_matched_intents():
    """LLM `candidates` payload with >1 entries -> matched_intents length >1."""
    catalog = load_intent_catalog()
    client = _FakeLlmClient({
        "candidates": [
            {
                "capabilityId": "MM.Inventory.GetAvailability",
                "parameters": {"material": "DEMOA2", "plant": "5100"},
            },
            {
                "capabilityId": "MM.PurchaseOrder.GetList",
                "parameters": {"poNumber": "4500000001"},
            },
        ],
    })

    result = parse_with_llm("DEMOA2 在 5100 的库存，再列出采购订单 4500000001", client, catalog)

    assert len(result.matched_intents) == 2
    capability_ids = {m.capability_id for m in result.matched_intents}
    assert capability_ids == {"MM.Inventory.GetAvailability", "MM.PurchaseOrder.GetList"}
    assert result.intent is None
    assert result.capability_id is None


def test_parse_with_llm_escalation_payload_returns_matched_intents():
    """LLM `escalation: {candidates: [...]}` payload -> matched_intents length >1."""
    catalog = load_intent_catalog()
    client = _FakeLlmClient({
        "escalation": {
            "reason": "multi_intent",
            "candidates": [
                {
                    "capabilityId": "MM.Inventory.GetAvailability",
                    "parameters": {"material": "DEMOA2", "plant": "5100"},
                },
                {
                    "capabilityId": "MM.PurchaseOrder.GetList",
                    "parameters": {"poNumber": "4500000001"},
                },
            ],
        },
    })

    result = parse_with_llm("multi-goal utterance", client, catalog)

    assert len(result.matched_intents) == 2
    capability_ids = {m.capability_id for m in result.matched_intents}
    assert capability_ids == {"MM.Inventory.GetAvailability", "MM.PurchaseOrder.GetList"}


def test_parse_with_llm_single_candidate_payload_keeps_single_intent_path():
    """LLM `candidates` with exactly 1 entry -> single-intent path (backward compat)."""
    catalog = load_intent_catalog()
    client = _FakeLlmClient({
        "candidates": [
            {
                "capabilityId": "MM.Inventory.GetAvailability",
                "parameters": {"material": "DEMOA2", "plant": "5100"},
            },
        ],
    })

    result = parse_with_llm("DEMOA2 在 5100 的库存", client, catalog)

    assert len(result.matched_intents) == 1
    assert result.matched_intents[0].capability_id == "MM.Inventory.GetAvailability"
    # Single-candidate path still populates top-level capability_id for compat.
    assert result.capability_id == "MM.Inventory.GetAvailability"
    assert result.intent is None


def test_parse_with_llm_single_capability_id_payload_populates_matched_intents():
    """Existing single `capabilityId` payload path also populates matched_intents."""
    catalog = load_intent_catalog()
    client = _FakeLlmClient({
        "capabilityId": "MM.Inventory.GetAvailability",
        "parameters": {"material": "DEMOA2", "plant": "5100"},
        "missingParameters": [],
        "clarification": None,
    })

    result = parse_with_llm("DEMOA2 在 5100 的库存", client, catalog)

    assert len(result.matched_intents) == 1
    assert result.matched_intents[0].capability_id == "MM.Inventory.GetAvailability"
    assert result.capability_id == "MM.Inventory.GetAvailability"


def test_parse_with_llm_unknown_candidate_capability_filtered_out():
    """Unknown capabilityId inside candidates is dropped; remaining valid candidate wins."""
    catalog = load_intent_catalog()
    client = _FakeLlmClient({
        "candidates": [
            {
                "capabilityId": "MM.Inventory.GetAvailability",
                "parameters": {"material": "DEMOA2", "plant": "5100"},
            },
            {
                "capabilityId": "MM.Material.CreateBom",  # not in closed set
                "parameters": {"material": "X"},
            },
        ],
    })

    result = parse_with_llm("utterance", client, catalog)

    # Only the valid candidate survives; single-intent path takes over.
    assert len(result.matched_intents) == 1
    assert result.matched_intents[0].capability_id == "MM.Inventory.GetAvailability"


def test_parse_with_llm_all_candidates_unknown_returns_empty_matched_intents():
    """All unknown candidates -> matched_intents empty (selector emits REJECT)."""
    catalog = load_intent_catalog()
    client = _FakeLlmClient({
        "candidates": [
            {"capabilityId": "MM.Material.CreateBom", "parameters": {"material": "X"}},
            {"capabilityId": "SD.Order.Create", "parameters": {"order": "1"}},
        ],
    })

    result = parse_with_llm("utterance", client, catalog)

    assert result.matched_intents == []
    assert result.capability_id is None
    assert result.intent is None


def test_parse_with_llm_empty_candidates_returns_empty_matched_intents():
    """Empty candidates list -> treated as no match (REJECT)."""
    catalog = load_intent_catalog()
    client = _FakeLlmClient({"candidates": []})

    result = parse_with_llm("utterance", client, catalog)

    assert result.matched_intents == []
    assert result.capability_id is None


def test_llm_system_prompt_detects_all_capabilities_not_select_exactly_one():
    """D-1 fix: LLM system prompt must instruct multi-capability detection."""
    catalog = load_intent_catalog()
    client = _FakeLlmClient({
        "capabilityId": "MM.Inventory.GetAvailability",
        "parameters": {"material": "DEMOA2", "plant": "5100"},
    })

    parse_with_llm("查库存", client, catalog)

    system_prompt = client.calls[0]["messages"][0]["content"]
    # Multi-intent detection instruction (D-1 fix).
    assert "detect all" in system_prompt.lower()
    # Single-intent bias removed.
    assert "select exactly one" not in system_prompt.lower()
    # Escalation guidance present.
    assert "escalation" in system_prompt.lower()


# --- Task 5.5: is_ambiguous keyword-ambiguity detection (SHOW_OPTIONS trigger) ---
#
# Design Doc § 多意图检测 Q2: keyword ambiguity = utterance weakly matches
# multiple capability keyword sets without a clear primary intent (not multi-
# intent, which is ESCALATE_TO_PLANNER). Primary/weak keyword tables are module
# constants in intent.py; threshold: >=2 capabilities weakly matched AND no
# primary keyword hit anywhere -> is_ambiguous=True.


def test_intent_parse_result_is_ambiguous_defaults_to_false():
    """Backward compat: existing construction without is_ambiguous still works."""
    result = IntentParseResult(intent=None, parameters={}, missing_parameters=[])
    assert result.is_ambiguous is False


def test_parse_intent_ambiguous_weak_only_po_and_pr_match():
    """'采购' alone weak-matches PO and PR (no primary) -> is_ambiguous=True.

    Per Design Doc § 多意图检测 Q2: '采购' fuzzy-matches PO query and PR creation.
    Neither '采购订单' (PO primary) nor '采购申请'/'创建采购' (PR primary) is
    present, so no clear primary intent exists.
    """
    result = parse_intent("采购")
    assert result.is_ambiguous is True


def test_parse_intent_not_ambiguous_when_po_primary_keyword_hit():
    """PO primary keyword '采购订单' -> clear single intent, not ambiguous."""
    result = parse_intent("采购订单 4500000001")
    assert result.is_ambiguous is False


def test_parse_intent_not_ambiguous_when_inventory_primary_keyword_hit():
    """Inventory primary keyword '库存' -> clear single intent, not ambiguous."""
    result = parse_intent("查库存")
    assert result.is_ambiguous is False


def test_parse_intent_not_ambiguous_when_pr_primary_keyword_hit():
    """PR primary keyword '采购申请' -> clear single intent, not ambiguous."""
    result = parse_intent(
        "采购申请 物料 MAT001 工厂 1000 数量 10 EA 交货日期 2026-08-01 采购组 G01"
    )
    assert result.is_ambiguous is False


def test_parse_intent_not_ambiguous_when_multi_intent_with_primary_hits():
    """Multi-intent with primary hits -> is_ambiguous=False.

    Multi-intent (matched_intents > 1) is a clear multi-goal utterance, not
    keyword ambiguity. ESCALATE_TO_PLANNER takes priority in the selector.
    """
    text = "DEMOA2 在 5100 的库存，再列出近 30 天未清采购订单"
    result = parse_intent(text)
    assert len(result.matched_intents) == 2
    assert result.is_ambiguous is False


def test_parse_intent_ambiguous_weak_inventory_and_pr():
    """Weak Inventory ('有没有') + weak PR/PO ('采购') -> is_ambiguous=True."""
    result = parse_intent("有没有采购")
    assert result.is_ambiguous is True


def test_parse_intent_ambiguous_with_single_existing_match_routes_show_options():
    """is_ambiguous=True with single existing match -> selector SHOW_OPTIONS.

    '有没有采购' weak-matches Inventory (existing scan finds '有没有') and
    weak-matches PR/PO ('采购'). The existing scan finds 1 match (Inventory),
    so matched_intents has 1 entry; is_ambiguous=True -> SHOW_OPTIONS fires
    (not ESCALATE, since matched_intents length is 1).
    """
    parsed = parse_intent("有没有采购")
    selected = select_capability(parsed)
    assert selected.decision_type == "SHOW_OPTIONS"
    assert selected.capability_id is None


def test_parse_intent_ambiguous_does_not_affect_single_clear_intent_extraction():
    """is_ambiguous=False for clear single intent; existing extraction preserved."""
    result = parse_intent("DEMOA2 在 5100 还有多少可用库存")
    assert result.is_ambiguous is False
    assert result.intent == "inventory_availability"
    assert result.parameters == {"material": "DEMOA2", "plant": "5100"}


# --- Rule fallback inherits last_context material on primary keyword (Task 4 / D3) ---


def test_rule_fallback_inherits_material_on_primary_keyword():
    """LLM 不可用 rule 兜底：主关键词 + 提取不到 material + last_context 有 -> 继承。"""
    ctx = ConversationContext(
        last_context=LastContext(
            capability_id="MM.Inventory.GetAvailability",
            parameters={"material": "DEMOA2", "plant": "5100"},
            missing_parameters=[],
            decision_type="SELECT",
        ),
        history=None,
    )
    result = parse_intent("查下这个物料在1000的库存", context=ctx)
    assert result.capability_id == "MM.Inventory.GetAvailability"
    assert result.parameters.get("material") == "DEMOA2"
    assert result.parameters.get("plant") == "1000"


def test_rule_fallback_does_not_inherit_when_new_material_present():
    """有新物料时不继承 last_context material。"""
    ctx = ConversationContext(
        last_context=LastContext(
            capability_id="MM.Inventory.GetAvailability",
            parameters={"material": "DEMOA2", "plant": "5100"},
            missing_parameters=[],
            decision_type="SELECT",
        ),
        history=None,
    )
    result = parse_intent("查 DEMOA4 在 1000 的库存", context=ctx)
    assert result.parameters.get("material") == "DEMOA4"
    assert result.parameters.get("plant") == "1000"


def test_rule_fallback_no_inherit_without_last_context():
    """无 last_context 时主关键词分支正常走单轮（不继承）。"""
    ctx = ConversationContext(last_context=None, history=None)
    result = parse_intent("查下这个物料在1000的库存", context=ctx)
    assert result.capability_id is None or result.missing_parameters == ["material"]


# --- Task 5: IntentParseResult.multi_parameters field ---


def test_intent_parse_result_has_multi_parameters_field():
    from sap_nexus_agent.intent import IntentParseResult
    result = IntentParseResult(intent=None, parameters={}, missing_parameters=[])
    assert result.multi_parameters == {}

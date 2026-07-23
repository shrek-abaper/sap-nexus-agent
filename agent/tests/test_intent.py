import pytest

from sap_nexus_agent.capability_selector import select_capability
from sap_nexus_agent.intent import IntentParseResult, parse_inventory_intent, parse_intent


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
    assert selected.capability_id is None
    assert selected.error_type == "MISSING_PARAMETER"


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

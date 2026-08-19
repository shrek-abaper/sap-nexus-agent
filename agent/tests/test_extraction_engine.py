from sap_nexus_agent.extraction.resolvers import resolve
from sap_nexus_agent.registry_loader import ValueFilters
from sap_nexus_agent.extraction import engine
from sap_nexus_agent.registry_loader import load_intent_catalog


def _catalog():
    return load_intent_catalog()


def _cap(catalog, cap_id):
    cap = catalog.find(cap_id)
    assert cap is not None and cap.intent_config is not None
    return cap


def test_text_resolver_verbatim():
    assert resolve("DEMOA2", "text", ValueFilters()) == "DEMOA2"
    assert resolve("demoa2", "text", ValueFilters()) == "demoa2"


def test_text_resolver_uppercases_output_when_declared():
    assert resolve("ea", "text", ValueFilters(to_upper_output=True)) == "EA"
    assert resolve("001", "text", ValueFilters(to_upper_output=True)) == "001"


def test_date_resolver_iso_verbatim():
    assert resolve("2026-08-18", "date", ValueFilters()) == "2026-08-18"


def test_quantity_resolver_numeric_verbatim():
    assert resolve("10", "quantity", ValueFilters()) == "10"
    assert resolve("1.5", "quantity", ValueFilters()) == "1.5"


def test_unknown_resolver_raises():
    import pytest

    with pytest.raises(ValueError):
        resolve("x", "decimal", ValueFilters())


def test_trigger_scan_inventory_weak_keyword_triggers():
    catalog = _catalog()
    inv = _cap(catalog, "MM.Inventory.GetAvailability")
    assert engine.triggered("有没有 DEMOA2", inv) is True
    assert engine.keyword_hits("有没有 DEMOA2", inv) == (False, True)


def test_trigger_scan_po_bounded_po():
    catalog = _catalog()
    po = _cap(catalog, "MM.PurchaseOrder.GetList")
    assert engine.triggered("IMPORT 4500000001", po) is False   # no false positive
    assert engine.triggered("PO 4500000001", po) is True
    assert engine.triggered("采购", po) is False                  # weak never triggers


def test_trigger_scan_pr_create_purchase_does_not_trigger():
    catalog = _catalog()
    pr = _cap(catalog, "MM.PR.CreateDraft")
    assert engine.triggered("采购", pr) is False
    assert engine.triggered("帮我创建PR 物料 DEMOA2", pr) is True


def test_ambiguity_condition():
    assert engine.is_ambiguous([(False, True), (False, True), (False, True)]) is True
    assert engine.is_ambiguous([(True, False), (False, True)]) is False
    assert engine.is_ambiguous([(False, True)]) is False


def test_extract_parameters_inventory_exclusion_and_priority():
    catalog = _catalog()
    inv = _cap(catalog, "MM.Inventory.GetAvailability")
    params = engine.extract_parameters("DEMOA2 1000 的库存 EA", inv, catalog)
    assert params == {"material": "DEMOA2", "plant": "1000", "unit": "EA"}


def test_extract_parameters_po_number_value_exclusion():
    catalog = _catalog()
    po = _cap(catalog, "MM.PurchaseOrder.GetList")
    params = engine.extract_parameters("采购订单 4500000001 供应商 4500000001", po, catalog)
    assert params == {"vendor": "4500000001"}  # poNumber excluded (value equality)


def test_extract_parameters_pr_conditional_cost_center():
    catalog = _catalog()
    pr = _cap(catalog, "MM.PR.CreateDraft")
    with_acct = engine.extract_parameters(
        "创建PR 间采 物料 DEMOA2 工厂 1000 数量 10 EA 交货日期 2026-10-01 采购组 002 成本中心 4700", pr, catalog)
    assert with_acct["acct_assgn_cat"] == "K"
    assert with_acct["cost_center"] == "4700"
    without = engine.extract_parameters(
        "创建PR 物料 DEMOA2 工厂 1000 数量 10 EA 交货日期 2026-10-01 采购组 002", pr, catalog)
    assert "acct_assgn_cat" not in without
    assert "cost_center" not in without  # when-gated


def test_missing_parameters_pr_required_when():
    catalog = _catalog()
    pr = _cap(catalog, "MM.PR.CreateDraft")
    assert engine.missing_parameters(pr, {"acct_assgn_cat": "K", "material": "DEMOA2"}) == [
        "plant", "quantity", "unit", "delivery_date", "purchasing_group", "cost_center"]


def test_missing_parameters_po_require_any():
    catalog = _catalog()
    po = _cap(catalog, "MM.PurchaseOrder.GetList")
    assert engine.missing_parameters(po, {}) == ["filter"]
    assert engine.missing_parameters(po, {"vendor": "1000"}) == []


def test_build_capability_result_inventory_clarify():
    catalog = _catalog()
    inv = _cap(catalog, "MM.Inventory.GetAvailability")
    result = engine.build_capability_result("查物料 DEMOA2 的库存", inv, catalog)
    assert result.intent == "inventory_availability"
    assert result.parameters == {"material": "DEMOA2"}
    assert result.missing_parameters == ["plant"]
    assert result.clarification == "请提供要查询的工厂。"


def test_parse_declared_single_and_multi():
    catalog = _catalog()
    single = engine.parse_declared("查物料 DEMOA2 在 1000 工厂的可用库存", catalog,
                                   contains_rfc_name=False, contains_odata_override=False)
    assert single.intent == "inventory_availability"
    assert single.capability_id == "MM.Inventory.GetAvailability"
    multi = engine.parse_declared(
        "DEMOA2 在 5100 的库存，再列出近 30 天未清采购订单", catalog,
        contains_rfc_name=False, contains_odata_override=False)
    assert len(multi.matched_intents) == 2
    assert multi.capability_id is None
    amb = engine.parse_declared("有没有采购", catalog,
                                contains_rfc_name=False, contains_odata_override=False)
    assert amb.is_ambiguous is True
    assert [m.capability_id for m in amb.matched_intents] == ["MM.Inventory.GetAvailability"]

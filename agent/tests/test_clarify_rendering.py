from sap_nexus_agent.extraction.clarify import render_clarify
from sap_nexus_agent.registry_loader import load_intent_catalog


def _cap(cap_id):
    catalog = load_intent_catalog()
    cap = catalog.find(cap_id)
    assert cap is not None and cap.intent_config is not None
    return cap


def test_inventory_cases_exact_missing_sets():
    inv = _cap("MM.Inventory.GetAvailability")
    assert render_clarify(inv, ["material"]) == "请提供要查询的物料编号。"
    assert render_clarify(inv, ["plant"]) == "请提供要查询的工厂。"
    assert render_clarify(inv, ["material", "plant"]) == "请提供要查询的物料编号和工厂。"
    assert render_clarify(inv, []) is None


def test_pr_fallback_join_template():
    pr = _cap("MM.PR.CreateDraft")
    assert render_clarify(pr, ["quantity", "unit"]) == "请提供: 数量, 单位"
    assert render_clarify(pr, ["material", "plant"]) == "请提供: 物料编号, 工厂"


def test_missing_locale_falls_back_to_names():
    pr = _cap("MM.PR.CreateDraft")
    # no en-US entry declared -> derive from input names, never raise
    assert render_clarify(pr, ["material"], locale="en-US") is not None


def test_po_filter_case():
    po = _cap("MM.PurchaseOrder.GetList")
    assert render_clarify(po, ["filter"]) == "请至少提供一个过滤条件（采购订单号、供应商、工厂或物料）。"


def test_sticky_clarify_rendered_from_declaration():
    from sap_nexus_agent.conversation_context import ConversationContext, LastContext
    from sap_nexus_agent.llm_intent import resolve_with_context

    context = ConversationContext(
        history=(),
        last_context=LastContext(
            capability_id="MM.PR.CreateDraft",
            decision_type="CLARIFY",
            parameters={"material": "DEMOA2", "quantity": "50"},
            missing_parameters=["plant", "unit", "delivery_date", "purchasing_group"],
        ),
    )
    result = resolve_with_context("工厂 1000 数量 50", context, load_intent_catalog())
    # Reconciliation #5: sticky PR clarification is now the declared text.
    assert result.clarification == "请提供: 单位, 交货日期, 采购组"
    assert result.missing_parameters == ["unit", "delivery_date", "purchasing_group"]


def test_sticky_inventory_clarify_matches_legacy_exactly():
    from sap_nexus_agent.conversation_context import ConversationContext, LastContext
    from sap_nexus_agent.llm_intent import resolve_with_context

    context = ConversationContext(
        history=(),
        last_context=LastContext(
            capability_id="MM.Inventory.GetAvailability",
            decision_type="CLARIFY",
            parameters={"plant": "1000"},
            missing_parameters=["material"],
        ),
    )
    result = resolve_with_context("继续查一下", context, load_intent_catalog())
    # Inventory single-turn and sticky texts coincide - stays strict.
    assert result.clarification == "请提供要查询的物料编号。"

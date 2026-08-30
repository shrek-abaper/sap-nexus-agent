"""SD/FI read capabilities: fact building, list narration, orchestrator routing.

Covers what registering SD.SalesOrder.GetList / FI.AR.GetOpenItems /
FI.AP.GetOpenItems changed beyond the registry: the ``list`` factShape used to
mean "purchase order" in both the orchestrator and the narrator, so this file
locks the generalized behavior AND the unchanged PO behavior next to it.
"""

import pytest

from sap_nexus_agent.execution_result import ExecutionResult
from sap_nexus_agent.narrator import NarrativeGuardError, narrate_list_by_capability
from sap_nexus_agent.reasoning_fact import (
    build_ap_open_items_facts,
    build_ar_open_items_facts,
    build_sales_order_facts,
)
from sap_nexus_agent.registry_loader import load_intent_catalog


def _sales_order_row(
    sd_doc="0000004711",
    doc_type="OR",
    doc_date="2026-08-01",
    sold_to="1000",
    material="DEMOA1",
    net_value="1500.00",
    currency="EUR",
    sales_org="1000",
    purch_no_c="CUSTPO-1",
):
    return {
        "sdDoc": sd_doc,
        "docType": doc_type,
        "docDate": doc_date,
        "soldTo": sold_to,
        "material": material,
        "netValue": net_value,
        "currency": currency,
        "salesOrg": sales_org,
        "purchNoC": purch_no_c,
    }


def _open_item_row(
    doc_no="1800000001",
    doc_date="2026-07-15",
    pstng_date="2026-07-15",
    amt_doccur="2500.00",
    currency="EUR",
    bline_date="2026-07-15",
    clear_date="",
):
    return {
        "docNo": doc_no,
        "docDate": doc_date,
        "pstngDate": pstng_date,
        "amtDoccur": amt_doccur,
        "currency": currency,
        "blineDate": bline_date,
        "clearDate": clear_date,
    }


def _execution(capability_id, rfc_name, data, *, success=True, trace_id="gw-1"):
    return ExecutionResult(
        trace_id=trace_id,
        capability_id=capability_id,
        success=success,
        executor={"type": "JCO_RFC", "rfcName": rfc_name},
        return_messages=[],
        data=data,
        duration_ms=10,
        error_type="NONE",
    )


def _sales_order_execution(rows, **kwargs):
    return _execution(
        "SD.SalesOrder.GetList", "BAPI_SALESORDER_GETLIST", {"salesOrders": rows}, **kwargs
    )


def _ar_execution(rows, **kwargs):
    return _execution(
        "FI.AR.GetOpenItems", "BAPI_AR_ACC_GETOPENITEMS", {"openItems": rows}, **kwargs
    )


def _ap_execution(rows, **kwargs):
    return _execution(
        "FI.AP.GetOpenItems", "BAPI_AP_ACC_GETOPENITEMS", {"openItems": rows}, **kwargs
    )


# ---------------------------------------------------------------------------
# Fact builders
# ---------------------------------------------------------------------------


def test_build_sales_order_facts_creates_one_fact_per_row():
    rows = [
        _sales_order_row(sd_doc="0000004711", net_value="1500.00"),
        _sales_order_row(sd_doc="0000004712", net_value="250.50"),
    ]
    facts = build_sales_order_facts("agent-so-1", _sales_order_execution(rows))

    assert len(facts) == 2
    assert [fact.evidence[0]["salesOrderNumber"] for fact in facts] == [
        "0000004711",
        "0000004712",
    ]
    for fact in facts:
        assert fact.domain == "SD"
        assert fact.business_object == "SalesOrder"
        assert fact.predicate == "salesOrderItem"
        assert fact.deterministic is True
        assert fact.confidence == 1.0
        assert fact.agent_trace_id == "agent-so-1"
        assert fact.gateway_trace_id == "gw-1"
        assert fact.unit == "EUR"
    # The monetary column arrives as text and lands in the numeric value slot.
    assert facts[0].value == 1500.0
    assert facts[1].value == 250.5


def test_build_sales_order_facts_maps_every_declared_fact_type_field():
    facts = build_sales_order_facts("agent-so-2", _sales_order_execution([_sales_order_row()]))

    assert facts[0].evidence[0] == {
        "salesOrderNumber": "0000004711",
        "documentType": "OR",
        "documentDate": "2026-08-01",
        "soldTo": "1000",
        "material": "DEMOA1",
        "netValue": "1500.00",
        "currency": "EUR",
        "salesOrg": "1000",
        "customerPoNumber": "CUSTPO-1",
    }


def test_build_ar_open_items_facts_maps_every_declared_fact_type_field():
    facts = build_ar_open_items_facts("agent-ar-1", _ar_execution([_open_item_row()]))

    assert len(facts) == 1
    fact = facts[0]
    assert fact.domain == "FI"
    assert fact.business_object == "CustomerOpenItem"
    assert fact.predicate == "customerOpenItem"
    assert fact.value == 2500.0
    assert fact.unit == "EUR"
    assert fact.evidence[0] == {
        "documentNumber": "1800000001",
        "documentDate": "2026-07-15",
        "postingDate": "2026-07-15",
        "amount": "2500.00",
        "currency": "EUR",
        "netDueDate": "2026-07-15",
        # An open item has no clearing date; blank is evidence, not absence.
        "clearingDate": "",
    }


def test_build_ap_open_items_facts_uses_the_vendor_business_object():
    facts = build_ap_open_items_facts("agent-ap-1", _ap_execution([_open_item_row()]))

    assert len(facts) == 1
    assert facts[0].domain == "FI"
    assert facts[0].business_object == "VendorOpenItem"
    assert facts[0].predicate == "vendorOpenItem"


@pytest.mark.parametrize(
    ("builder", "execution"),
    [
        (build_sales_order_facts, _sales_order_execution([])),
        (build_ar_open_items_facts, _ar_execution([])),
        (build_ap_open_items_facts, _ap_execution([])),
    ],
)
def test_empty_table_yields_no_facts(builder, execution):
    assert builder("agent-empty", execution) == []


@pytest.mark.parametrize(
    ("builder", "execution"),
    [
        (build_sales_order_facts, _sales_order_execution([_sales_order_row()], success=False)),
        (build_ar_open_items_facts, _ar_execution([_open_item_row()], success=False)),
        (build_ap_open_items_facts, _ap_execution([_open_item_row()], success=False)),
    ],
)
def test_failed_execution_yields_no_facts(builder, execution):
    assert builder("agent-failed", execution) == []


def test_non_numeric_amount_stays_in_evidence_only():
    facts = build_ar_open_items_facts(
        "agent-ar-2", _ar_execution([_open_item_row(amt_doccur="")])
    )

    assert facts[0].value is None
    assert facts[0].evidence[0]["amount"] == ""


# ---------------------------------------------------------------------------
# List narration driven by narrative.fieldMapping.row
# ---------------------------------------------------------------------------


class _UnavailableLlmClient:
    def chat_text(self, *_args, **_kwargs):
        from sap_nexus_agent.llm_client import LlmUnavailable

        raise LlmUnavailable("test")


class _EchoLlmClient:
    def __init__(self):
        self.messages = None

    def chat_text(self, messages, **_kwargs):
        self.messages = messages
        return "生成的中文归纳"


def test_sales_order_fallback_renders_the_declared_row_template():
    facts = build_sales_order_facts("agent-so-3", _sales_order_execution([_sales_order_row()]))

    text = narrate_list_by_capability(
        facts, "SD.SalesOrder.GetList", client=_UnavailableLlmClient()
    )

    assert text == "订单 0000004711：客户 1000，净值 1500.00 EUR，单据日期 2026-08-01"


def test_open_item_fallback_renders_the_declared_row_template():
    facts = build_ar_open_items_facts("agent-ar-3", _ar_execution([_open_item_row()]))

    text = narrate_list_by_capability(
        facts, "FI.AR.GetOpenItems", client=_UnavailableLlmClient()
    )

    assert text == "凭证 1800000001：金额 2500.00 EUR，到期基准日 2026-07-15"


def test_declared_rows_are_fed_to_the_llm_with_the_capability_guidance():
    facts = build_ap_open_items_facts("agent-ap-2", _ap_execution([_open_item_row()]))
    client = _EchoLlmClient()

    text = narrate_list_by_capability(
        facts, "FI.AP.GetOpenItems", total_count=1, client=client
    )

    assert text == "生成的中文归纳"
    system_messages = [m["content"] for m in client.messages if m["role"] == "system"]
    assert any("应付未清项" in content for content in system_messages)
    user_content = next(m["content"] for m in client.messages if m["role"] == "user")
    assert "凭证 1800000001：金额 2500.00 EUR" in user_content
    assert "总记录数: 1" in user_content


def test_empty_facts_say_no_match_without_calling_the_llm():
    assert narrate_list_by_capability([], "SD.SalesOrder.GetList", client=None) == "无匹配记录。"


def test_guard_rejects_a_row_field_the_fact_cannot_answer():
    from dataclasses import replace

    facts = build_sales_order_facts("agent-so-4", _sales_order_execution([_sales_order_row()]))
    # Drop the placeholder the declaration asks for: declaration and builder now
    # disagree, which must fail closed rather than render a blank order number.
    stripped = [
        replace(
            facts[0],
            evidence=[
                {
                    key: value
                    for key, value in facts[0].evidence[0].items()
                    if key != "salesOrderNumber"
                }
            ],
        )
    ]

    with pytest.raises(NarrativeGuardError) as excinfo:
        narrate_list_by_capability(
            stripped, "SD.SalesOrder.GetList", client=_UnavailableLlmClient()
        )
    assert "salesOrderNumber" in str(excinfo.value)


def test_purchase_order_list_keeps_its_undeclared_narration_path():
    """MM.PurchaseOrder.GetList declares no fieldMapping, so it must not be
    routed through the declared-row path (zero-regression boundary)."""
    catalog = load_intent_catalog()
    po = catalog.find("MM.PurchaseOrder.GetList")
    assert po is not None and po.narrative is not None
    assert po.narrative.fact_shape == "list"
    assert dict(po.narrative.field_mapping).get("row") is None

    for capability_id in (
        "SD.SalesOrder.GetList",
        "FI.AR.GetOpenItems",
        "FI.AP.GetOpenItems",
    ):
        descriptor = catalog.find(capability_id)
        assert descriptor is not None and descriptor.narrative is not None
        assert descriptor.narrative.fact_shape == "list"
        assert dict(descriptor.narrative.field_mapping)["row"]


# ---------------------------------------------------------------------------
# Orchestrator list routing
# ---------------------------------------------------------------------------


def test_every_list_capability_has_a_registered_fact_builder():
    """The orchestrator's list branch used to call the PO builder for any list
    capability. Every registered list capability must now name its own builder."""
    from sap_nexus_agent.orchestrator import _LIST_FACT_BUILDERS

    catalog = load_intent_catalog()
    list_capabilities = {
        descriptor.capability_id
        for descriptor in catalog.capabilities
        if descriptor.narrative is not None and descriptor.narrative.fact_shape == "list"
    }
    assert list_capabilities == set(_LIST_FACT_BUILDERS)


def test_list_routing_maps_each_capability_to_its_own_builder():
    from sap_nexus_agent.orchestrator import _LIST_FACT_BUILDERS
    from sap_nexus_agent.reasoning_fact import build_purchase_order_facts

    assert _LIST_FACT_BUILDERS["MM.PurchaseOrder.GetList"] is build_purchase_order_facts
    assert _LIST_FACT_BUILDERS["SD.SalesOrder.GetList"] is build_sales_order_facts
    assert _LIST_FACT_BUILDERS["FI.AR.GetOpenItems"] is build_ar_open_items_facts
    assert _LIST_FACT_BUILDERS["FI.AP.GetOpenItems"] is build_ap_open_items_facts


def test_unregistered_list_capability_fails_closed():
    from sap_nexus_agent.call_plan import CallPlan
    from sap_nexus_agent.orchestrator import _build_list_facts

    call_plan = CallPlan(
        agent_trace_id="agent-unreg",
        capability_id="SD.Unregistered.GetList",
        kind="Function",
        parameters={},
        validation_policy="strict",
        created_by="test",
        requires_approval=False,
    )

    with pytest.raises(NarrativeGuardError) as excinfo:
        _build_list_facts(
            "SD.Unregistered.GetList",
            call_plan,
            _sales_order_execution([_sales_order_row()]),
        )
    assert "SD.Unregistered.GetList" in str(excinfo.value)

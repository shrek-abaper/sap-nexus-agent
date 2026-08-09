import pytest

from sap_nexus_agent.execution_result import ExecutionResult
from sap_nexus_agent.narrator import (
    NarrativeGuardError,
    narrate_fact,
    narrate_failure,
    narrate_purchase_order_facts,
    redact_sensitive,
)
from sap_nexus_agent.reasoning_fact import (
    ReasoningFact,
    build_availability_fact,
    build_purchase_order_facts,
)


def successful_execution():
    return ExecutionResult(
        trace_id="gw-execute-1",
        capability_id="MM.Inventory.GetAvailability",
        success=True,
        executor={"type": "JCO_RFC", "rfcName": "BAPI_MATERIAL_AVAILABILITY"},
        return_messages=[],
        data={"material": "DEMOA1", "plant": "1000", "availableQuantity": 12, "unit": "EA"},
        duration_ms=10,
        error_type="NONE",
    )


def test_successful_execution_creates_availability_fact():
    fact = build_availability_fact("agent-1", successful_execution())

    assert fact is not None
    assert fact.agent_trace_id == "agent-1"
    assert fact.gateway_trace_id == "gw-execute-1"
    assert fact.predicate == "availableQuantity"
    assert fact.value == 12
    assert fact.unit == "EA"
    assert fact.source["capabilityId"] == "MM.Inventory.GetAvailability"
    assert fact.evidence[0]["field"] == "availableQuantity"


def test_md04_source_field_is_preserved_in_availability_fact_evidence():
    result = ExecutionResult(
        trace_id="gw-md04",
        capability_id="MM.Inventory.GetAvailability",
        success=True,
        executor={"type": "JCO_RFC", "rfcName": "BAPI_MATERIAL_STOCK_REQ_LIST"},
        return_messages=[],
        data={
            "material": "DEMOA1",
            "plant": "1000",
            "availableQuantity": 12.0,
            "unit": "EA",
            "sourceTable": "MRP_IND_LINES",
            "sourceField": "AVAIL_QTY1",
            "mrpElementInd": "WB",
        },
        duration_ms=10,
        error_type="NONE",
    )

    fact = build_availability_fact("agent-1", result)

    assert fact is not None
    assert fact.evidence[0]["sourceTable"] == "MRP_IND_LINES"
    assert fact.evidence[0]["sourceField"] == "AVAIL_QTY1"
    assert fact.evidence[0]["mrpElementInd"] == "WB"


def test_mrp_element_lines_are_preserved_in_availability_fact_evidence():
    result = ExecutionResult(
        trace_id="gw-md04-detail",
        capability_id="MM.Inventory.GetAvailability",
        success=True,
        executor={"type": "JCO_RFC", "rfcName": "BAPI_MATERIAL_STOCK_REQ_LIST"},
        return_messages=[],
        data={
            "material": "DEMOA1",
            "plant": "1000",
            "availableQuantity": 12.0,
            "unit": "EA",
            "sourceTable": "MRP_IND_LINES",
            "sourceField": "AVAIL_QTY1",
            "mrpElementInd": "WB",
            "mrpElementLines": [
                {
                    "mrpElementInd": "BE",
                    "mrpElement": "POitem",
                    "elementQty": 264.0,
                    "availQty1": 264.0,
                    "date": "2026-06-21",
                },
                {
                    "mrpElementInd": "WB",
                    "mrpElement": "Stock",
                    "elementQty": 12.0,
                    "availQty1": 12.0,
                    "date": "2026-06-21",
                },
            ],
        },
        duration_ms=10,
        error_type="NONE",
    )

    fact = build_availability_fact("agent-1", result)

    assert fact is not None
    detail = fact.evidence[0]["mrpElementLines"]
    assert isinstance(detail, list)
    assert len(detail) == 2
    assert detail[0]["mrpElementInd"] == "BE"
    assert detail[1]["mrpElementInd"] == "WB"


def test_narrate_fact_llm_path_includes_mrp_element_detail():
    result = ExecutionResult(
        trace_id="gw-md04-detail",
        capability_id="MM.Inventory.GetAvailability",
        success=True,
        executor={"type": "JCO_RFC", "rfcName": "BAPI_MATERIAL_STOCK_REQ_LIST"},
        return_messages=[],
        data={
            "material": "DEMOA1",
            "plant": "1000",
            "availableQuantity": 12.0,
            "unit": "EA",
            "mrpElementLines": [
                {
                    "mrpElementInd": "BE",
                    "mrpElement": "POitem",
                    "elementQty": 264.0,
                    "availQty1": 264.0,
                    "date": "2026-06-21",
                },
                {
                    "mrpElementInd": "WB",
                    "mrpElement": "Stock",
                    "elementQty": 12.0,
                    "availQty1": 12.0,
                    "date": "2026-06-21",
                },
            ],
        },
        duration_ms=10,
        error_type="NONE",
    )
    fact = build_availability_fact("agent-1", result)
    fake = FakeNarratorLlmClient(text="物料 DEMOA1 在 1000 可用 12 EA，含 2 个 MRP 元素行。")

    narrate_fact(fact, client=fake)

    user_content = fake.calls[0]["messages"][2]["content"]
    assert "MRP 元素明细" in user_content
    assert "BE/POitem" in user_content
    assert "WB/Stock" in user_content


def test_failed_execution_creates_no_success_fact():
    result = ExecutionResult(
        trace_id="gw-fail",
        capability_id="MM.Inventory.GetAvailability",
        success=False,
        executor={"type": "JCO_RFC", "rfcName": "BAPI_MATERIAL_AVAILABILITY"},
        return_messages=[{"type": "E", "message": "boom"}],
        data={},
        duration_ms=10,
        error_type="SAP_BUSINESS_ERROR",
    )

    assert build_availability_fact("agent-1", result) is None


def test_narrate_fact_uses_only_fact_fields():
    fact = build_availability_fact("agent-1", successful_execution())

    assert narrate_fact(fact) == (
        "物料 DEMOA1 在工厂 1000 的库存/需求清单（MD04）\n\n"
        "当前可用量：12 EA"
    )


def test_narrator_rejects_missing_quantity():
    fact = ReasoningFact(
        fact_id="fact-1",
        agent_trace_id="agent-1",
        trace_id="agent-1",
        gateway_trace_id="gw-1",
        domain="MM",
        business_object="InventoryStock",
        predicate="availableQuantity",
        value=None,
        unit="EA",
        deterministic=True,
        confidence=1.0,
        source={"capabilityId": "MM.Inventory.GetAvailability"},
        evidence=[],
        material="DEMOA1",
        plant="1000",
    )

    with pytest.raises(NarrativeGuardError):
        narrate_fact(fact)


def test_redact_sensitive_failure_text():
    text = narrate_failure(
        "SAP_AUTH_ERROR",
        ["password=abc token=secret .env SAP_PASSWORD=hidden destination=config"],
    )

    assert "abc" not in text
    assert "secret" not in text
    assert ".env" not in text
    assert "SAP_PASSWORD" not in text


def test_redact_sensitive_helper():
    assert redact_sensitive("passwd=abc token=xyz") == "passwd=*** token=***"


def test_redact_sensitive_colon_json_and_prose_formats():
    text = narrate_failure(
        "SAP_AUTH_ERROR",
        [
            'password: abc "token":"secret" SAP_PASSWORD: hidden destination config host=internal .env',
        ],
    )

    assert "abc" not in text
    assert "secret" not in text
    assert "hidden" not in text
    assert "internal" not in text
    assert "SAP_PASSWORD" not in text
    assert "destination config" not in text
    assert ".env" not in text


# ---------------------------------------------------------------------------
# Purchase Order fact builder + narrator
# ---------------------------------------------------------------------------


def _po_item(
    po="4500000001",
    supplier="DEMOV1",
    plant="1000",
    material="DEMOA1",
    qty=100,
    unit="EA",
):
    return {
        "purchaseOrder": po,
        "supplier": supplier,
        "plant": plant,
        "material": material,
        "orderQuantity": qty,
        "purchaseOrderUnit": unit,
    }


def _po_execution_result(items, *, success=True, trace_id="gw-po-1", total_count=None):
    data = {"purchaseOrders": items}
    if total_count is not None:
        data["totalCount"] = total_count
    return ExecutionResult(
        trace_id=trace_id,
        capability_id="MM.PurchaseOrder.GetList",
        success=success,
        executor={"type": "ODATA"},
        return_messages=[],
        data=data,
        duration_ms=10,
        error_type="NONE",
    )


def test_build_po_facts_creates_one_fact_per_item():
    items = [
        _po_item(po="4500000001", supplier="DEMOV1", qty=100),
        _po_item(po="4500000002", supplier="DEMOV2", qty=50),
        _po_item(po="4500000003", supplier="100002", qty=25),
    ]
    facts = build_purchase_order_facts("agent-po-1", _po_execution_result(items))

    assert len(facts) == 3
    for i, fact in enumerate(facts):
        assert fact.predicate == "purchaseOrderItem"
        assert fact.deterministic is True
        assert fact.confidence == 1.0
        assert fact.domain == "MM"
        assert fact.business_object == "PurchaseOrder"
        assert fact.agent_trace_id == "agent-po-1"
        assert fact.gateway_trace_id == "gw-po-1"
        ev = fact.evidence[0]
        assert ev["purchaseOrder"] == items[i]["purchaseOrder"]
        assert ev["supplier"] == items[i]["supplier"]
        assert ev["plant"] == items[i]["plant"]
        assert ev["material"] == items[i]["material"]
        assert ev["orderQuantity"] == items[i]["orderQuantity"]
        assert ev["purchaseOrderUnit"] == items[i]["purchaseOrderUnit"]


def test_build_po_facts_empty_list_returns_empty():
    facts = build_purchase_order_facts("agent-po-1", _po_execution_result([]))
    assert facts == []


def test_build_po_facts_failed_execution_returns_empty():
    result = ExecutionResult(
        trace_id="gw-po-fail",
        capability_id="MM.PurchaseOrder.GetList",
        success=False,
        executor={"type": "ODATA"},
        return_messages=[{"type": "E", "message": "boom"}],
        data={},
        duration_ms=10,
        error_type="SAP_BUSINESS_ERROR",
    )
    assert build_purchase_order_facts("agent-po-1", result) == []


def test_narrate_po_facts_grounded_list():
    items = [
        _po_item(po="4500000001", supplier="DEMOV1", plant="1000", material="MAT-001", qty=100, unit="EA"),
        _po_item(po="4500000002", supplier="DEMOV2", plant="2000", material="MAT-002", qty=50, unit="PC"),
    ]
    facts = build_purchase_order_facts("agent-po-1", _po_execution_result(items))
    narrative = narrate_purchase_order_facts(facts)

    assert "4500000001" in narrative
    assert "DEMOV1" in narrative
    assert "MAT-001" in narrative
    assert "1000" in narrative
    assert "100" in narrative
    assert "EA" in narrative
    assert "4500000002" in narrative
    assert "DEMOV2" in narrative
    assert "MAT-002" in narrative
    assert "2000" in narrative
    assert "50" in narrative
    assert "PC" in narrative


def test_narrate_po_facts_empty_list_says_no_match():
    narrative = narrate_purchase_order_facts([])
    assert "无匹配记录" in narrative


def test_narrate_po_facts_over_limit_notice():
    items = [_po_item(po=f"4500000{i:03d}") for i in range(51)]
    facts = build_purchase_order_facts("agent-po-1", _po_execution_result(items))
    narrative = narrate_purchase_order_facts(facts)

    assert "仅返回前 50 条" in narrative


def test_narrate_po_facts_total_count_triggers_notice():
    items = [_po_item(po=f"4500000{i:03d}") for i in range(50)]
    facts = build_purchase_order_facts(
        "agent-po-1", _po_execution_result(items, total_count=75)
    )
    narrative = narrate_purchase_order_facts(facts, total_count=75)

    assert "仅返回前 50 条" in narrative


def test_narrate_po_facts_guard_rejects_missing_evidence():
    fact = ReasoningFact(
        fact_id="fact-po-bad",
        agent_trace_id="agent-1",
        trace_id="agent-1",
        gateway_trace_id="gw-1",
        domain="MM",
        business_object="PurchaseOrder",
        predicate="purchaseOrderItem",
        value=None,
        unit=None,
        deterministic=True,
        confidence=1.0,
        source={"capabilityId": "MM.PurchaseOrder.GetList"},
        evidence=[{"purchaseOrder": "4500000001"}],  # missing supplier/plant/material/qty/unit
    )
    with pytest.raises(NarrativeGuardError):
        narrate_purchase_order_facts([fact])


# ---------------------------------------------------------------------------
# Nested OData items[] shape (real OData service output)
# ---------------------------------------------------------------------------


def _po_header_with_items(po="DEMOPO1", supplier="1100", item_plant="5400", item_material="DEMOA5", item_qty="1.000", item_unit="EA"):
    """Real OData shape: header has purchaseOrder/supplier; item fields nested in items[]."""
    return {
        "purchaseOrder": po,
        "supplier": supplier,
        "items": [
            {
                "purchaseOrder": po,
                "plant": item_plant,
                "material": item_material,
                "orderQuantity": item_qty,
                "purchaseOrderUnit": item_unit,
            }
        ],
    }


def test_build_po_facts_handles_nested_items_shape():
    """Real OData nested items[] -> one fact per item, header supplies po/supplier."""
    items = [_po_header_with_items(po="DEMOPO1", supplier="1100", item_plant="5400", item_material="DEMOA5", item_qty="1.000", item_unit="EA")]
    facts = build_purchase_order_facts("agent-po-nested", _po_execution_result(items))

    assert len(facts) == 1
    fact = facts[0]
    assert fact.predicate == "purchaseOrderItem"
    ev = fact.evidence[0]
    # header supplies purchaseOrder/supplier
    assert ev["purchaseOrder"] == "DEMOPO1"
    assert ev["supplier"] == "1100"
    # item supplies plant/material/orderQuantity/purchaseOrderUnit
    assert ev["plant"] == "5400"
    assert ev["material"] == "DEMOA5"
    assert ev["orderQuantity"] == "1.000"
    assert ev["purchaseOrderUnit"] == "EA"
    # fact-level material/plant from item
    assert fact.material == "DEMOA5"
    assert fact.plant == "5400"


def test_build_po_facts_nested_multiple_items_per_header():
    """One header with multiple items -> one fact per item."""
    header = {
        "purchaseOrder": "DEMOPO1",
        "supplier": "1100",
        "items": [
            {"purchaseOrder": "DEMOPO1", "plant": "5400", "material": "DEMOA5", "orderQuantity": "1.000", "purchaseOrderUnit": "EA"},
            {"purchaseOrder": "DEMOPO1", "plant": "5400", "material": "ADA-000259", "orderQuantity": "2.000", "purchaseOrderUnit": "EA"},
        ],
    }
    facts = build_purchase_order_facts("agent-po-nested", _po_execution_result([header]))

    assert len(facts) == 2
    assert facts[0].evidence[0]["material"] == "DEMOA5"
    assert facts[1].evidence[0]["material"] == "ADA-000259"
    # both facts share header purchaseOrder/supplier
    assert all(f.evidence[0]["purchaseOrder"] == "DEMOPO1" for f in facts)
    assert all(f.evidence[0]["supplier"] == "1100" for f in facts)


def test_build_po_facts_nested_empty_items_yields_no_fact():
    """Header with empty items[] -> no fact for that header."""
    header = {"purchaseOrder": "DEMOPO1", "supplier": "1100", "items": []}
    facts = build_purchase_order_facts("agent-po-nested", _po_execution_result([header]))

    assert facts == []


def test_narrate_po_facts_nested_shape_succeeds():
    """End-to-end: nested items facts narrate without NarrativeGuardError."""
    header = _po_header_with_items()
    facts = build_purchase_order_facts("agent-po-nested", _po_execution_result([header]))

    narrative = narrate_purchase_order_facts(facts, total_count=1)

    assert "DEMOPO1" in narrative
    assert "1100" in narrative
    assert "5400" in narrative
    assert "DEMOA5" in narrative


# ---------------------------------------------------------------------------
# Flexible narration guidance derivation (LLM-grounded narration)
# ---------------------------------------------------------------------------

from sap_nexus_agent.narrator import narration_guidance


def test_narration_guidance_inventory():
    guidance = narration_guidance("MM.Inventory.GetAvailability")
    assert "库存" in guidance
    assert "MRP" in guidance or "需求" in guidance


def test_narration_guidance_purchase_order():
    guidance = narration_guidance("MM.PurchaseOrder.GetList")
    assert "采购订单" in guidance


def test_narration_guidance_unknown_capability_returns_generic():
    guidance = narration_guidance("MM.NonExistent.Capability")
    assert "事实" in guidance or "字段" in guidance


# ---------------------------------------------------------------------------
# Prompt message construction
# ---------------------------------------------------------------------------

from sap_nexus_agent.narrator import _build_single_value_messages, _build_list_messages
from sap_nexus_agent.registry_loader import load_intent_catalog


def test_build_messages_inventory_contains_system_constraint_and_fact_fields():
    fact = build_availability_fact("agent-1", successful_execution())
    config = load_intent_catalog().find("MM.Inventory.GetAvailability").narrative
    messages = _build_single_value_messages(fact, config)

    assert messages[0]["role"] == "system"
    assert "不得编造" in messages[0]["content"]
    assert messages[1]["role"] == "system"
    assert "库存" in messages[1]["content"]
    assert messages[2]["role"] == "user"
    assert "DEMOA1" in messages[2]["content"]
    assert "1000" in messages[2]["content"]
    assert "12" in messages[2]["content"]
    assert "EA" in messages[2]["content"]


def test_build_po_messages_contains_constraint_and_evidence():
    items = [_po_item(po="4500000001", supplier="DEMOV1")]
    facts = build_purchase_order_facts("agent-po-1", _po_execution_result(items))
    config = load_intent_catalog().find("MM.PurchaseOrder.GetList").narrative
    messages = _build_list_messages(facts, total_count=1, config=config)

    assert messages[0]["role"] == "system"
    assert "不得编造" in messages[0]["content"]
    assert messages[1]["role"] == "system"
    assert "采购订单" in messages[1]["content"]
    assert messages[2]["role"] == "user"
    assert "4500000001" in messages[2]["content"]
    assert "DEMOV1" in messages[2]["content"]


# ---------------------------------------------------------------------------
# narrate_fact LLM path + fallback (Task 4)
# ---------------------------------------------------------------------------


class FakeNarratorLlmClient:
    """Fake LLM client implementing chat_text for narrator tests."""

    def __init__(self, text="LLM 生成的库存叙事。", unavailable=False):
        self.text = text
        self.unavailable = unavailable
        self.calls = []

    def chat_text(self, messages, *, temperature=0.0, max_tokens=400):
        self.calls.append({"messages": messages, "temperature": temperature, "max_tokens": max_tokens})
        if self.unavailable:
            raise LlmUnavailable("model gateway unavailable")
        return self.text


from sap_nexus_agent.llm_client import LlmUnavailable


def test_narrate_fact_llm_path_returns_generated_text():
    fact = build_availability_fact("agent-1", successful_execution())
    fake = FakeNarratorLlmClient(text="物料 DEMOA1 在 1000 当前可用 12 EA。")

    result = narrate_fact(fact, client=fake)

    assert result == "物料 DEMOA1 在 1000 当前可用 12 EA。"
    assert len(fake.calls) == 1
    assert fake.calls[0]["temperature"] == 0.0


def test_narrate_fact_llm_path_passes_capability_id_to_guidance():
    fact = build_availability_fact("agent-1", successful_execution())
    fake = FakeNarratorLlmClient()

    narrate_fact(fact, capability_id="MM.Inventory.GetAvailability", client=fake)

    messages = fake.calls[0]["messages"]
    assert "库存" in messages[1]["content"]


def test_narrate_fact_llm_unavailable_falls_back_to_template():
    fact = build_availability_fact("agent-1", successful_execution())
    fake = FakeNarratorLlmClient(unavailable=True)

    result = narrate_fact(fact, client=fake)

    assert result == (
        "物料 DEMOA1 在工厂 1000 的库存/需求清单（MD04）\n\n"
        "当前可用量：12 EA"
    )


def test_narrate_fact_no_client_falls_back_to_template():
    """Without injected client, OpenAiCompatibleLlmClient() raises LlmUnavailable (conftest)."""
    fact = build_availability_fact("agent-1", successful_execution())

    result = narrate_fact(fact)

    assert result == (
        "物料 DEMOA1 在工厂 1000 的库存/需求清单（MD04）\n\n"
        "当前可用量：12 EA"
    )


def test_narrate_fact_template_includes_mrp_detail_table():
    """Template fallback renders the raw MRP element rows as an aligned table."""
    result = ExecutionResult(
        trace_id="gw-md04-detail",
        capability_id="MM.Inventory.GetAvailability",
        success=True,
        executor={"type": "JCO_RFC", "rfcName": "BAPI_MATERIAL_STOCK_REQ_LIST"},
        return_messages=[],
        data={
            "material": "DEMOA1",
            "plant": "1000",
            "availableQuantity": 12.0,
            "unit": "EA",
            "mrpElementLines": [
                {
                    "mrpElementInd": "BE",
                    "mrpElement": "POitem",
                    "elementQty": 264.0,
                    "availQty1": 264.0,
                    "date": "2026-06-21",
                },
                {
                    "mrpElementInd": "WB",
                    "mrpElement": "Stock",
                    "elementQty": 12.0,
                    "availQty1": 12.0,
                    "date": "2026-06-21",
                },
            ],
        },
        duration_ms=10,
        error_type="NONE",
    )
    fact = build_availability_fact("agent-1", result)
    fake = FakeNarratorLlmClient(unavailable=True)

    narrative = narrate_fact(fact, client=fake)

    assert "库存/需求清单（MD04）" in narrative
    assert "当前可用量：12" in narrative
    assert "EA" in narrative
    assert "MRP 元素明细：" in narrative
    assert "元素指示符" in narrative
    assert "WB" in narrative
    assert "BE" in narrative
    assert "Stock" in narrative
    assert "POitem" in narrative
    assert "2026-06-21" in narrative


def test_narrate_po_facts_llm_path_returns_generated_text():
    items = [_po_item(po="4500000001", supplier="DEMOV1")]
    facts = build_purchase_order_facts("agent-po-1", _po_execution_result(items))
    fake = FakeNarratorLlmClient(text="共 1 条采购订单，订单 4500000001 由供应商 DEMOV1 供应。")

    result = narrate_purchase_order_facts(facts, total_count=1, client=fake)

    assert "4500000001" in result
    assert "DEMOV1" in result
    assert len(fake.calls) == 1


def test_narrate_po_facts_llm_unavailable_falls_back_to_template():
    items = [_po_item(po="4500000001", supplier="DEMOV1")]
    facts = build_purchase_order_facts("agent-po-1", _po_execution_result(items))
    fake = FakeNarratorLlmClient(unavailable=True)

    result = narrate_purchase_order_facts(facts, total_count=1, client=fake)

    assert "4500000001" in result
    assert "DEMOV1" in result
    assert "采购订单 4500000001" in result


def test_narrate_po_facts_empty_list_does_not_call_llm():
    fake = FakeNarratorLlmClient()

    result = narrate_purchase_order_facts([], client=fake)

    assert result == "无匹配记录。"
    assert len(fake.calls) == 0


def test_narrate_po_facts_no_client_falls_back_to_template():
    """Without injected client, falls back to template (conftest isolates LLM)."""
    items = [_po_item(po="4500000001", supplier="DEMOV1")]
    facts = build_purchase_order_facts("agent-po-1", _po_execution_result(items))

    result = narrate_purchase_order_facts(facts)

    assert "采购订单 4500000001" in result


# ---------------------------------------------------------------------------
# Anti-hallucination + redact on LLM output (Task 7)
# ---------------------------------------------------------------------------


def test_narrate_fact_llm_output_redacts_sensitive_info():
    fact = build_availability_fact("agent-1", successful_execution())
    fake = FakeNarratorLlmClient(text="库存为 12 EA。password=secret token=abc")

    result = narrate_fact(fact, client=fake)

    assert "secret" not in result
    assert "abc" not in result
    assert "12" in result


def test_narrate_po_facts_llm_output_redacts_sensitive_info():
    items = [_po_item(po="4500000001")]
    facts = build_purchase_order_facts("agent-po-1", _po_execution_result(items))
    fake = FakeNarratorLlmClient(text="订单 4500000001。host=internal .env")

    result = narrate_purchase_order_facts(facts, client=fake)

    assert "internal" not in result
    assert ".env" not in result
    assert "4500000001" in result


def test_narrate_fact_prompt_system_constraint_forbids_fabrication():
    """System prompt must contain anti-fabrication constraint."""
    fact = build_availability_fact("agent-1", successful_execution())
    fake = FakeNarratorLlmClient()

    narrate_fact(fact, client=fake)

    system_content = fake.calls[0]["messages"][0]["content"]
    assert "不得编造" in system_content
    assert "不得猜测" in system_content
    assert "BAPI" in system_content or "RFC" in system_content


def test_narrate_po_facts_prompt_system_constraint_forbids_fabrication():
    items = [_po_item(po="4500000001")]
    facts = build_purchase_order_facts("agent-po-1", _po_execution_result(items))
    fake = FakeNarratorLlmClient()

    narrate_purchase_order_facts(facts, client=fake)

    system_content = fake.calls[0]["messages"][0]["content"]
    assert "不得编造" in system_content


# ---------------------------------------------------------------------------
# PO evidence guard determinism (review fix: LLM-up path also guards)
# ---------------------------------------------------------------------------


def test_narrate_po_facts_incomplete_evidence_raises_guard_with_llm_available():
    """Incomplete evidence raises NarrativeGuardError even when LLM is available
    (guard before LLM, deterministic regardless of LLM availability)."""
    fact = ReasoningFact(
        fact_id="fact-x",
        agent_trace_id="agent-po-1",
        trace_id="agent-po-1",
        gateway_trace_id="gw-po-1",
        domain="MM",
        business_object="PurchaseOrder",
        predicate="purchaseOrderItem",
        value=None,
        unit=None,
        deterministic=True,
        confidence=1.0,
        source={"capabilityId": "MM.PurchaseOrder.GetList"},
        evidence=[{"purchaseOrder": "4500000001"}],  # missing supplier/plant/material/qty/unit
    )
    fake = FakeNarratorLlmClient()

    with pytest.raises(NarrativeGuardError):
        narrate_purchase_order_facts([fact], client=fake)

    # LLM must not be called when evidence is incomplete
    assert len(fake.calls) == 0


def test_narrate_po_facts_incomplete_evidence_raises_guard_with_llm_unavailable():
    """Same incomplete evidence raises guard when LLM unavailable (deterministic)."""
    fact = ReasoningFact(
        fact_id="fact-x",
        agent_trace_id="agent-po-1",
        trace_id="agent-po-1",
        gateway_trace_id="gw-po-1",
        domain="MM",
        business_object="PurchaseOrder",
        predicate="purchaseOrderItem",
        value=None,
        unit=None,
        deterministic=True,
        confidence=1.0,
        source={"capabilityId": "MM.PurchaseOrder.GetList"},
        evidence=[{"purchaseOrder": "4500000001"}],
    )
    fake = FakeNarratorLlmClient(unavailable=True)

    with pytest.raises(NarrativeGuardError):
        narrate_purchase_order_facts([fact], client=fake)


# ---------------------------------------------------------------------------
# narrate_inventory_facts: multi-value batch aggregation (Task 9)
# ---------------------------------------------------------------------------

from sap_nexus_agent.narrator import narrate_inventory_facts


def _inv_fact(material, plant, value, unit="EA"):
    return ReasoningFact(
        fact_id=f"fact-{material}-{plant}",
        agent_trace_id="trace-1",
        trace_id="trace-1",
        gateway_trace_id="gw-1",
        domain="MM",
        business_object="InventoryStock",
        predicate="availableQuantity",
        value=value,
        unit=unit,
        deterministic=True,
        confidence=1.0,
        source={"capabilityId": "MM.Inventory.GetAvailability"},
        evidence=[{"field": "availableQuantity", "value": value}],
        material=material,
        plant=plant,
    )


class _StubTextClient:
    def __init__(self, text):
        self._text = text

    def chat_text(self, messages, **kwargs):
        return self._text


class _RaisingTextClient:
    def chat_text(self, messages, **kwargs):
        from sap_nexus_agent.llm_client import LlmUnavailable
        raise LlmUnavailable("down")


def test_narrate_inventory_facts_empty():
    assert narrate_inventory_facts([]) == "无匹配记录。"


def test_narrate_inventory_facts_llm_main():
    facts = [_inv_fact("DEMOA2", "5200", 176), _inv_fact("DEMOA2", "1000", 0)]
    text = narrate_inventory_facts(facts, client=_StubTextClient("5200: 176 EA; 1000: 0 EA"))
    assert "5200" in text and "176" in text
    assert "1000" in text and "0" in text


def test_narrate_inventory_facts_template_fallback_single_material():
    facts = [_inv_fact("DEMOA2", "5200", 176), _inv_fact("DEMOA2", "1000", 0)]
    text = narrate_inventory_facts(facts, client=_RaisingTextClient())
    # 单物料模板："在工厂 5200 为 176 EA；在工厂 1000 为 0 EA"
    assert "5200" in text and "176" in text
    assert "1000" in text and "0" in text
    assert "DEMOA2" in text


def test_narrate_inventory_facts_template_fallback_multi_material():
    facts = [_inv_fact("DEMOA2", "5200", 176), _inv_fact("DEMOA4", "1000", 5)]
    text = narrate_inventory_facts(facts, client=_RaisingTextClient())
    assert "DEMOA2" in text
    assert "DEMOA4" in text
    assert "5200" in text and "176" in text
    assert "1000" in text and "5" in text


def test_narrate_inventory_facts_partial_failure():
    facts = [_inv_fact("DEMOA2", "5200", 176)]
    failures = [{"parameters": {"material": "DEMOA2", "plant": "1000"}, "error": "SAP_ERROR"}]
    text = narrate_inventory_facts(facts, failures=failures, client=_RaisingTextClient())
    assert "5200" in text
    assert "1000" in text  # 失败工厂被标注
    assert "失败" in text


def test_narrate_inventory_facts_guard_on_missing_fields():
    bad = ReasoningFact(
        fact_id="bad", agent_trace_id="t", trace_id="t", gateway_trace_id="g",
        domain="MM", business_object="InventoryStock", predicate="availableQuantity",
        value=None, unit=None, deterministic=True, confidence=1.0,
        source={}, evidence=[], material=None, plant=None,
    )
    try:
        narrate_inventory_facts([bad], client=_RaisingTextClient())
        assert False, "expected NarrativeGuardError"
    except NarrativeGuardError:
        pass


# ---------------------------------------------------------------------------
# Generalized framework: synthetic capability narrates via declaration only (A6)
# ---------------------------------------------------------------------------


def test_synthetic_capability_narrates_via_declaration_only():
    """A6: a capability with only a narrative declaration (no new narrator code)
    narrates through the generic factShape framework."""
    from sap_nexus_agent.narrator import narrate_single_value
    from sap_nexus_agent.registry_loader import NarrativeConfig

    config = NarrativeConfig(
        fact_shape="single-value",
        prompt_template="inventory-md04",
        fallback_template="inventory-md04",
        field_mapping=(("title", "{material} 在工厂 {plant}"), ("primary", "{value} {unit}")),
        detail_formatter="none",
    )
    fact = build_availability_fact("agent-1", successful_execution())
    fake = FakeNarratorLlmClient(unavailable=True)

    result = narrate_single_value(fact, config, client=fake)

    assert "DEMOA1" in result
    assert "1000" in result
    assert "12" in result
    assert "EA" in result


def test_unknown_detail_formatter_falls_back_to_none():
    """A8: unknown detailFormatter id falls back to none (no detail, no error)."""
    from sap_nexus_agent.narrator import narrate_single_value
    from sap_nexus_agent.registry_loader import NarrativeConfig

    config = NarrativeConfig(
        fact_shape="single-value",
        prompt_template="inventory-md04",
        fallback_template="inventory-md04",
        field_mapping=(("title", "{material} 在工厂 {plant}"),),
        detail_formatter="unknown-xyz",
    )
    fact = build_availability_fact("agent-1", successful_execution())
    fake = FakeNarratorLlmClient(unavailable=True)

    result = narrate_single_value(fact, config, client=fake)

    assert "MRP 元素明细" not in result
    assert "当前可用量" in result


# ---------------------------------------------------------------------------
# Action-receipt narration (PR create) via the framework
# ---------------------------------------------------------------------------


def test_action_receipt_narration_with_pr_number():
    """A5: PR create narration flows through narrate_action_receipt."""
    from sap_nexus_agent.narrator import narrate_action_receipt
    from sap_nexus_agent.registry_loader import NarrativeConfig
    from sap_nexus_agent.reasoning_fact import build_pr_create_fact

    result = ExecutionResult(
        trace_id="gw-pr",
        capability_id="MM.PR.CreateDraft",
        success=True,
        executor={"type": "JCO_RFC", "rfcName": "BAPI_PR_CREATE"},
        return_messages=[],
        data={"prNumber": "0010001234"},
        duration_ms=10,
        error_type="NONE",
    )
    fact = build_pr_create_fact("agent-1", result)
    config = NarrativeConfig(
        fact_shape="action-receipt",
        prompt_template="pr-create-receipt",
        fallback_template="pr-create-receipt",
        field_mapping=(("receiptId", "prNumber"),),
        detail_formatter="none",
    )

    text = narrate_action_receipt(fact, config)

    assert "0010001234" in text
    assert "采购申请创建成功" in text


def test_action_receipt_narration_without_pr_number():
    """A5: PR create without a PR number yields the missing-number message."""
    from sap_nexus_agent.narrator import narrate_action_receipt
    from sap_nexus_agent.registry_loader import NarrativeConfig
    from sap_nexus_agent.reasoning_fact import build_pr_create_fact

    result = ExecutionResult(
        trace_id="gw-pr-empty",
        capability_id="MM.PR.CreateDraft",
        success=True,
        executor={"type": "JCO_RFC", "rfcName": "BAPI_PR_CREATE"},
        return_messages=[],
        data={"prNumber": ""},
        duration_ms=10,
        error_type="NONE",
    )
    fact = build_pr_create_fact("agent-1", result)
    config = NarrativeConfig(
        fact_shape="action-receipt",
        prompt_template="pr-create-receipt",
        fallback_template="pr-create-receipt",
        field_mapping=(("receiptId", "prNumber"),),
        detail_formatter="none",
    )

    text = narrate_action_receipt(fact, config)

    assert "未返回 PR 号" in text


def test_build_pr_create_fact_is_deterministic():
    """PR create fact stays deterministic; no LLM text in evidence."""
    from sap_nexus_agent.reasoning_fact import build_pr_create_fact

    result = ExecutionResult(
        trace_id="gw-pr",
        capability_id="MM.PR.CreateDraft",
        success=True,
        executor={"type": "JCO_RFC", "rfcName": "BAPI_PR_CREATE"},
        return_messages=[],
        data={"prNumber": "0010001234"},
        duration_ms=10,
        error_type="NONE",
    )
    fact = build_pr_create_fact("agent-1", result)

    assert fact is not None
    assert fact.deterministic is True
    assert fact.confidence == 1.0
    assert fact.predicate == "purchaseRequisitionCreated"
    assert fact.business_object == "PurchaseRequisition"
    assert fact.evidence[0]["value"] == "0010001234"

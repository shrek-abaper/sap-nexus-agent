from sap_nexus_agent.execution_result import ExecutionResult, ValidationResult
from sap_nexus_agent.intent import IntentParseResult
from sap_nexus_agent.llm_intent import parse_with_hybrid
from sap_nexus_agent.orchestrator import run_inventory_query, run_query
from sap_nexus_agent.registry_loader import load_intent_catalog


class FakeGatewayClient:
    def __init__(self, validation=None, execution=None):
        self.validation = validation or ValidationResult(
            trace_id="gw-validate-1",
            capability_id="MM.Inventory.GetAvailability",
            success=True,
            error_type="NONE",
            messages=[],
        )
        self.execution = execution or ExecutionResult(
            trace_id="gw-execute-1",
            capability_id="MM.Inventory.GetAvailability",
            success=True,
            executor={"type": "JCO_RFC", "rfcName": "BAPI_MATERIAL_AVAILABILITY"},
            return_messages=[],
            data={"material": "DEMOA1", "plant": "1000", "availableQuantity": 12, "unit": "EA"},
            duration_ms=10,
            error_type="NONE",
        )
        self.validate_calls = []
        self.execute_calls = []

    def validate(self, capability_id, parameters):
        self.validate_calls.append((capability_id, parameters))
        assert "rfcName" not in parameters
        return self.validation

    def execute(self, capability_id, parameters, approval_id=None):
        self.execute_calls.append((capability_id, parameters))
        assert "rfcName" not in parameters
        return self.execution


def test_complete_request_creates_call_plan_and_calls_validate_then_execute():
    gateway = FakeGatewayClient()
    outcome = run_inventory_query("DEMOA1 在 1000 还有多少可用库存？", gateway)

    assert outcome.status == "success"
    assert outcome.call_plan is not None
    assert outcome.call_plan.capability_id == "MM.Inventory.GetAvailability"
    assert outcome.call_plan.parameters == {"material": "DEMOA1", "plant": "1000", "unit": "EA"}
    assert gateway.validate_calls == [("MM.Inventory.GetAvailability", {"material": "DEMOA1", "plant": "1000", "unit": "EA"})]
    assert gateway.execute_calls == [("MM.Inventory.GetAvailability", {"material": "DEMOA1", "plant": "1000", "unit": "EA"})]
    assert outcome.gateway_trace_id == "gw-execute-1"


def test_missing_plant_does_not_call_gateway():
    gateway = FakeGatewayClient()
    outcome = run_inventory_query("查一下 DEMOA1 的可用量", gateway)

    assert outcome.status == "clarification"
    assert outcome.missing_parameters == ["plant"]
    assert gateway.validate_calls == []
    assert gateway.execute_calls == []


def test_validation_failure_stops_execute():
    gateway = FakeGatewayClient(
        validation=ValidationResult(
            trace_id="gw-invalid",
            capability_id="MM.Inventory.GetAvailability",
            success=False,
            error_type="INVALID_PARAMETER",
            messages=["Invalid parameter: plant"],
        )
    )
    outcome = run_inventory_query("DEMOA1 在 1000 还有多少可用库存？", gateway)

    assert outcome.status == "failure"
    assert outcome.error_type == "INVALID_PARAMETER"
    assert len(gateway.validate_calls) == 1
    assert gateway.execute_calls == []


def test_user_supplied_rfc_name_does_not_call_gateway():
    gateway = FakeGatewayClient()
    outcome = run_inventory_query("用 rfcName=BAPI_PO_CREATE1 查 DEMOA1 在 1000 的库存", gateway)

    assert outcome.status == "failure"
    assert outcome.error_type == "UNSUPPORTED_RFC_NAME"
    assert gateway.validate_calls == []
    assert gateway.execute_calls == []


def test_gateway_shaped_success_uses_call_plan_parameters_for_fact_context():
    gateway = FakeGatewayClient(
        execution=ExecutionResult(
            trace_id="gw-real-shape",
            capability_id="MM.Inventory.GetAvailability",
            success=True,
            executor={"type": "JCO_RFC", "rfcName": "BAPI_MATERIAL_AVAILABILITY"},
            return_messages=[],
            data={"availableQuantity": 12},
            duration_ms=10,
            error_type="NONE",
        )
    )
    outcome = run_inventory_query("DEMOA1 在 1000 还有多少可用库存？", gateway)

    assert outcome.status == "success"
    assert outcome.fact is not None
    assert outcome.fact.material == "DEMOA1"
    assert outcome.fact.plant == "1000"
    assert outcome.fact.unit == "EA"
    assert outcome.response_text == "物料 DEMOA1 在工厂 1000 的可用库存为 12 EA。"


def test_success_without_available_quantity_returns_structured_failure():
    gateway = FakeGatewayClient(
        execution=ExecutionResult(
            trace_id="gw-no-quantity",
            capability_id="MM.Inventory.GetAvailability",
            success=True,
            executor={"type": "JCO_RFC", "rfcName": "BAPI_MATERIAL_AVAILABILITY"},
            return_messages=[],
            data={},
            duration_ms=10,
            error_type="NONE",
        )
    )
    outcome = run_inventory_query("DEMOA1 在 1000 还有多少可用库存？", gateway)

    assert outcome.status == "failure"
    assert outcome.error_type == "NARRATIVE_GUARD_ERROR"
    assert "缺少可叙事的库存事实" in outcome.response_text


def test_user_supplied_rfc_name_takes_precedence_over_missing_parameter_clarification():
    gateway = FakeGatewayClient()
    outcome = run_inventory_query("用 rfcName=BAPI_PO_CREATE1 查 DEMOA1 的库存", gateway)

    assert outcome.status == "failure"
    assert outcome.error_type == "UNSUPPORTED_RFC_NAME"
    assert gateway.validate_calls == []
    assert gateway.execute_calls == []


def test_injected_intent_adapter_can_drive_inventory_query():
    gateway = FakeGatewayClient()

    def adapter(_text):
        return IntentParseResult(
            intent="inventory_availability",
            parameters={"material": "MAT-9000", "plant": "1000"},
            missing_parameters=[],
        )

    outcome = run_inventory_query("帮我查这个料在这个工厂的库存", gateway, intent_adapter=adapter)

    assert outcome.status == "success"
    assert outcome.call_plan is not None
    assert outcome.call_plan.parameters == {"material": "MAT-9000", "plant": "1000", "unit": "EA"}
    assert gateway.validate_calls == [
        ("MM.Inventory.GetAvailability", {"material": "MAT-9000", "plant": "1000", "unit": "EA"})
    ]


def test_injected_intent_adapter_missing_plant_does_not_call_gateway():
    gateway = FakeGatewayClient()

    def adapter(_text):
        return IntentParseResult(
            intent="inventory_availability",
            parameters={"material": "MAT-9000"},
            missing_parameters=["plant"],
            clarification="请提供要查询的工厂。",
        )

    outcome = run_inventory_query("帮我查这个料的库存", gateway, intent_adapter=adapter)

    assert outcome.status == "clarification"
    assert outcome.missing_parameters == ["plant"]
    assert gateway.validate_calls == []
    assert gateway.execute_calls == []


def test_injected_intent_adapter_rfc_name_does_not_call_gateway():
    gateway = FakeGatewayClient()

    def adapter(_text):
        return IntentParseResult(
            intent="inventory_availability",
            parameters={"material": "MAT-9000", "plant": "1000"},
            missing_parameters=[],
            contains_rfc_name=True,
        )

    outcome = run_inventory_query("查库存", gateway, intent_adapter=adapter)

    assert outcome.status == "failure"
    assert outcome.error_type == "UNSUPPORTED_RFC_NAME"
    assert gateway.validate_calls == []
    assert gateway.execute_calls == []


# ---------------------------------------------------------------------------
# run_query unified entry (Plan Task 10)
# ---------------------------------------------------------------------------


class FakePoGatewayClient:
    """Gateway double returning PO list data."""

    def __init__(self, execution=None):
        self.validation = ValidationResult(
            trace_id="gw-validate-po",
            capability_id="MM.PurchaseOrder.GetList",
            success=True,
            error_type="NONE",
            messages=[],
        )
        self.execution = execution or ExecutionResult(
            trace_id="gw-execute-po",
            capability_id="MM.PurchaseOrder.GetList",
            success=True,
            executor={"type": "ODATA"},
            return_messages=[],
            data={
                "purchaseOrders": [
                    {
                        "purchaseOrder": "4500000001",
                        "supplier": "DEMOV1",
                        "plant": "1000",
                        "material": "DEMOA1",
                        "orderQuantity": 100,
                        "purchaseOrderUnit": "EA",
                    },
                    {
                        "purchaseOrder": "4500000002",
                        "supplier": "DEMOV2",
                        "plant": "2000",
                        "material": "MAT-002",
                        "orderQuantity": 50,
                        "purchaseOrderUnit": "PC",
                    },
                ]
            },
            duration_ms=10,
            error_type="NONE",
        )
        self.validate_calls = []
        self.execute_calls = []

    def validate(self, capability_id, parameters):
        self.validate_calls.append((capability_id, parameters))
        assert "rfcName" not in parameters
        return self.validation

    def execute(self, capability_id, parameters, approval_id=None):
        self.execute_calls.append((capability_id, parameters))
        assert "rfcName" not in parameters
        return self.execution


def test_run_query_inventory_regression():
    """Inventory query via run_query follows the same path as run_inventory_query."""
    gateway = FakeGatewayClient()
    outcome = run_query("DEMOA1 在 1000 还有多少可用库存？", gateway)

    assert outcome.status == "success"
    assert outcome.call_plan is not None
    assert outcome.call_plan.capability_id == "MM.Inventory.GetAvailability"
    assert outcome.call_plan.parameters == {"material": "DEMOA1", "plant": "1000", "unit": "EA"}
    assert outcome.fact is not None
    assert outcome.fact.predicate == "availableQuantity"
    assert outcome.response_text == "物料 DEMOA1 在工厂 1000 的可用库存为 12 EA。"


def test_run_query_po_list_success():
    gateway = FakePoGatewayClient()
    outcome = run_query("查供应商 DEMOV1 的采购订单", gateway)

    assert outcome.status == "success"
    assert outcome.call_plan is not None
    assert outcome.call_plan.capability_id == "MM.PurchaseOrder.GetList"
    assert outcome.call_plan.parameters == {"vendor": "DEMOV1"}
    assert gateway.validate_calls == [("MM.PurchaseOrder.GetList", {"vendor": "DEMOV1"})]
    assert gateway.execute_calls == [("MM.PurchaseOrder.GetList", {"vendor": "DEMOV1"})]
    assert outcome.facts is not None
    assert len(outcome.facts) == 2
    assert outcome.facts[0].predicate == "purchaseOrderItem"
    assert "4500000001" in outcome.response_text
    assert "DEMOV1" in outcome.response_text
    assert "无匹配记录" not in outcome.response_text


def test_run_query_po_empty_list_success():
    gateway = FakePoGatewayClient(
        execution=ExecutionResult(
            trace_id="gw-po-empty",
            capability_id="MM.PurchaseOrder.GetList",
            success=True,
            executor={"type": "ODATA"},
            return_messages=[],
            data={"purchaseOrders": []},
            duration_ms=10,
            error_type="NONE",
        )
    )
    outcome = run_query("查供应商 DEMOV1 的采购订单", gateway)

    assert outcome.status == "success"
    assert outcome.facts is not None
    assert len(outcome.facts) == 0
    assert "无匹配记录" in outcome.response_text


def test_run_query_inventory_via_run_inventory_query_backward_compat():
    """run_inventory_query still works and delegates to run_query."""
    gateway = FakeGatewayClient()
    outcome = run_inventory_query("DEMOA1 在 1000 还有多少可用库存？", gateway)

    assert outcome.status == "success"
    assert outcome.call_plan.parameters == {"material": "DEMOA1", "plant": "1000", "unit": "EA"}
    assert outcome.fact is not None


# ---------------------------------------------------------------------------
# run_query via LLM intent adapter (flexible intent recognition)
# ---------------------------------------------------------------------------


class _FakePoLlmClient:
    """Fake LLM client returning a PO capability selection."""

    def __init__(self, payload):
        self._payload = payload
        self.calls = []

    def chat_json(self, messages, *, temperature=0.0, max_tokens=400):
        self.calls.append({"messages": messages})
        return self._payload


def test_run_query_via_llm_adapter_selects_purchase_order():
    """run_query 经 LLM adapter（catalog + fake client）选 PO 全链路。"""
    catalog = load_intent_catalog()
    fake_client = _FakePoLlmClient({
        "capabilityId": "MM.PurchaseOrder.GetList",
        "parameters": {"poNumber": "DEMOPO1"},
        "missingParameters": [],
        "clarification": None,
    })
    adapter = lambda text: parse_with_hybrid(text, client=fake_client, catalog=catalog)

    gateway = FakePoGatewayClient()
    outcome = run_query("查询采购订单DEMOPO1", gateway, intent_adapter=adapter)

    assert outcome.status == "success"
    assert outcome.call_plan is not None
    assert outcome.call_plan.capability_id == "MM.PurchaseOrder.GetList"
    assert outcome.call_plan.parameters == {"poNumber": "DEMOPO1"}
    assert gateway.validate_calls == [("MM.PurchaseOrder.GetList", {"poNumber": "DEMOPO1"})]
    assert gateway.execute_calls == [("MM.PurchaseOrder.GetList", {"poNumber": "DEMOPO1"})]
    assert outcome.facts is not None
    assert len(outcome.facts) == 2
    assert "4500000001" in outcome.response_text


# ---------------------------------------------------------------------------
# orchestrator LLM narration path (Task 7)
# ---------------------------------------------------------------------------

from unittest.mock import patch


class _FakeNarratorClient:
    """Fake LLM client for orchestrator-level narration tests."""

    def __init__(self, text="LLM 叙事结论。", unavailable=False):
        self.text = text
        self.unavailable = unavailable
        self.calls = []

    def chat_text(self, messages, *, temperature=0.0, max_tokens=400):
        self.calls.append({"messages": messages})
        if self.unavailable:
            from sap_nexus_agent.llm_client import LlmUnavailable
            raise LlmUnavailable("model gateway unavailable")
        return self.text


def test_run_query_inventory_llm_narration_full_path():
    """orchestrator -> narrate_fact LLM path with injected fake client."""
    gateway = FakeGatewayClient()
    fake_llm = _FakeNarratorClient(text="物料 DEMOA1 在工厂 1000 可用库存为 12 EA。")

    with patch("sap_nexus_agent.narrator.OpenAiCompatibleLlmClient", return_value=fake_llm):
        outcome = run_inventory_query("DEMOA1 在 1000 还有多少可用库存？", gateway)

    assert outcome.status == "success"
    assert outcome.response_text == "物料 DEMOA1 在工厂 1000 可用库存为 12 EA。"
    assert len(fake_llm.calls) == 1


def test_run_query_po_llm_narration_full_path():
    """orchestrator -> narrate_purchase_order_facts LLM path with injected fake client."""
    gateway = FakePoGatewayClient()
    fake_llm = _FakeNarratorClient(text="共 2 条采购订单记录。")

    with patch("sap_nexus_agent.narrator.OpenAiCompatibleLlmClient", return_value=fake_llm):
        outcome = run_query("查供应商 DEMOV1 的采购订单", gateway)

    assert outcome.status == "success"
    assert outcome.response_text == "共 2 条采购订单记录。"
    assert len(fake_llm.calls) == 1


def test_run_query_inventory_llm_unavailable_falls_back_to_template():
    """When LLM is unavailable, orchestrator falls back to template narration."""
    gateway = FakeGatewayClient()
    fake_llm = _FakeNarratorClient(unavailable=True)

    with patch("sap_nexus_agent.narrator.OpenAiCompatibleLlmClient", return_value=fake_llm):
        outcome = run_inventory_query("DEMOA1 在 1000 还有多少可用库存？", gateway)

    assert outcome.status == "success"
    assert outcome.response_text == "物料 DEMOA1 在工厂 1000 的可用库存为 12 EA。"

from sap_nexus_agent.execution_result import ExecutionResult, ValidationResult
from sap_nexus_agent.intent import IntentParseResult
from sap_nexus_agent.llm_intent import parse_with_hybrid
from sap_nexus_agent.orchestrator import (
    AgentOutcome,
    BATCH_COMBINATION_CAP,
    expand_combinations,
    run_inventory_query,
    run_query,
)
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


# ---------------------------------------------------------------------------
# run_query five-state MatchDecision routing (Plan Task 3)
#
# SELECT -> CallPlan + Gateway validate/execute (regression covered above).
# CLARIFY / REJECT / SHOW_OPTIONS / ESCALATE_TO_PLANNER must return without
# touching the Gateway. SHOW_OPTIONS/ESCALATE surface as status="match_decision"
# carrying the MatchDecision for the frontend (SSE event is a later task).
# ---------------------------------------------------------------------------

import types

from sap_nexus_agent.match_decision import MatchDecision, MatchedIntent
from sap_nexus_agent.workbench_output import outcome_to_workbench_dict


def _inventory_matched(material="DEMOA1", plant="1000", missing=None):
    return MatchedIntent(
        capability_id="MM.Inventory.GetAvailability",
        parameters={"material": material, "plant": plant},
        missing=missing or [],
    )


def test_run_query_escalate_does_not_call_gateway():
    """Multi-intent -> ESCALATE_TO_PLANNER: no Gateway validate/execute."""
    gateway = FakeGatewayClient()

    def adapter(_text):
        return IntentParseResult(
            intent=None,
            parameters={},
            missing_parameters=[],
            matched_intents=[
                _inventory_matched(),
                MatchedIntent(
                    capability_id="MM.PurchaseOrder.GetList",
                    parameters={"vendor": "DEMOV1"},
                    missing=[],
                ),
            ],
        )

    outcome = run_query("查库存和采购订单", gateway, intent_adapter=adapter)

    assert outcome.status == "match_decision"
    assert outcome.match_decision is not None
    assert outcome.match_decision.decision_type == "ESCALATE_TO_PLANNER"
    assert outcome.match_decision.handoff is not None
    assert len(outcome.match_decision.handoff.matched_intents) == 2
    assert gateway.validate_calls == []
    assert gateway.execute_calls == []


def test_run_query_show_options_does_not_call_gateway():
    """Keyword ambiguity -> SHOW_OPTIONS: no Gateway validate/execute.

    Uses a SimpleNamespace adapter because Task 2 did not add ``is_ambiguous``
    to IntentParseResult; the selector reads it defensively. A future intent.py
    enhancement will populate the flag from the keyword-ambiguity threshold.
    """
    gateway = FakeGatewayClient()

    def adapter(_text):
        return types.SimpleNamespace(
            intent="inventory_availability",
            parameters={"material": "DEMOA1"},
            missing_parameters=["plant"],
            contains_rfc_name=False,
            contains_odata_override=False,
            capability_id="MM.Inventory.GetAvailability",
            clarification="请提供工厂。",
            matched_intents=[_inventory_matched(missing=["plant"])],
            is_ambiguous=True,
        )

    outcome = run_query("查一下采购的库存", gateway, intent_adapter=adapter)

    assert outcome.status == "match_decision"
    assert outcome.match_decision is not None
    assert outcome.match_decision.decision_type == "SHOW_OPTIONS"
    assert outcome.match_decision.candidates is not None
    assert gateway.validate_calls == []
    assert gateway.execute_calls == []


def test_run_query_unsupported_intent_returns_failure_without_gateway():
    """No match -> REJECT(UNSUPPORTED_INTENT): failure, no Gateway."""
    gateway = FakeGatewayClient()

    def adapter(_text):
        return IntentParseResult(
            intent=None,
            parameters={},
            missing_parameters=[],
            matched_intents=[],
        )

    outcome = run_query("今天天气不错", gateway, intent_adapter=adapter)

    assert outcome.status == "failure"
    assert outcome.error_type == "UNSUPPORTED_INTENT"
    assert outcome.match_decision is not None
    assert outcome.match_decision.decision_type == "REJECT"
    assert gateway.validate_calls == []
    assert gateway.execute_calls == []


def test_run_query_clarify_carries_match_decision():
    """CLARIFY path surfaces the MatchDecision alongside missing_parameters."""
    gateway = FakeGatewayClient()

    def adapter(_text):
        return IntentParseResult(
            intent="inventory_availability",
            parameters={"material": "DEMOA1"},
            missing_parameters=["plant"],
            clarification="请提供要查询的工厂。",
            capability_id="MM.Inventory.GetAvailability",
            matched_intents=[
                MatchedIntent(
                    capability_id="MM.Inventory.GetAvailability",
                    parameters={"material": "DEMOA1"},
                    missing=["plant"],
                )
            ],
        )

    outcome = run_query("查 DEMOA1 的库存", gateway, intent_adapter=adapter)

    assert outcome.status == "clarification"
    assert outcome.missing_parameters == ["plant"]
    assert outcome.match_decision is not None
    assert outcome.match_decision.decision_type == "CLARIFY"
    assert gateway.validate_calls == []
    assert gateway.execute_calls == []


def test_run_query_reject_rfc_name_carries_match_decision():
    """REJECT(UNSUPPORTED_RFC_NAME) path surfaces the MatchDecision."""
    gateway = FakeGatewayClient()

    def adapter(_text):
        return IntentParseResult(
            intent="inventory_availability",
            parameters={"material": "DEMOA1", "plant": "1000"},
            missing_parameters=[],
            contains_rfc_name=True,
        )

    outcome = run_query("用 rfcName=BAPI_X 查库存", gateway, intent_adapter=adapter)

    assert outcome.status == "failure"
    assert outcome.error_type == "UNSUPPORTED_RFC_NAME"
    assert outcome.match_decision is not None
    assert outcome.match_decision.decision_type == "REJECT"
    assert gateway.validate_calls == []
    assert gateway.execute_calls == []


def test_workbench_dict_serializes_match_decision_for_escalate():
    """outcome_to_workbench_dict emits a matchDecision field for ESCALATE."""
    gateway = FakeGatewayClient()

    def adapter(_text):
        return IntentParseResult(
            intent=None,
            parameters={},
            missing_parameters=[],
            matched_intents=[
                _inventory_matched(),
                MatchedIntent(
                    capability_id="MM.PurchaseOrder.GetList",
                    parameters={"vendor": "DEMOV1"},
                    missing=[],
                ),
            ],
        )

    outcome = run_query("查库存和采购订单", gateway, intent_adapter=adapter)
    payload = outcome_to_workbench_dict(outcome)

    assert payload["status"] == "match_decision"
    assert payload["matchDecision"] is not None
    assert payload["matchDecision"]["decisionType"] == "ESCALATE_TO_PLANNER"
    assert payload["matchDecision"]["handoff"] is not None
    assert len(payload["matchDecision"]["handoff"]["matchedIntents"]) == 2
    assert gateway.validate_calls == []
    assert gateway.execute_calls == []


def test_workbench_dict_match_decision_none_when_absent():
    """matchDecision is None for outcomes that bypass the selector (continue_action)."""
    # An AgentOutcome constructed without match_decision (e.g. approval continue
    # path) serializes matchDecision as None. SELECT/CLARIFY/REJECT/SHOW_OPTIONS
    # /ESCALATE outcomes all carry a MatchDecision via run_query.
    outcome = AgentOutcome(status="rejected", response_text="已拒绝")

    payload = outcome_to_workbench_dict(outcome)

    assert payload["status"] == "rejected"
    assert payload["matchDecision"] is None


def test_workbench_dict_select_path_carries_match_decision():
    """SELECT outcomes carry a SELECT MatchDecision for uniform rendering."""
    gateway = FakeGatewayClient()

    def adapter(_text):
        return IntentParseResult(
            intent="inventory_availability",
            parameters={"material": "MAT-9000", "plant": "1000"},
            missing_parameters=[],
        )

    outcome = run_inventory_query("查库存", gateway, intent_adapter=adapter)
    payload = outcome_to_workbench_dict(outcome)

    assert payload["status"] == "success"
    assert payload["matchDecision"] is not None
    assert payload["matchDecision"]["decisionType"] == "SELECT"
    assert payload["matchDecision"]["capabilityId"] == "MM.Inventory.GetAvailability"


# ---------------------------------------------------------------------------
# S2-B handoff wiring (Plan Task 9)
#
# Design Doc §"总体数据流": ESCALATE_TO_PLANNER handoff -> planner
# (CapabilityCard discovery + GoalSpec + PlanCompiler.compile_dry_run) ->
# DryRunResult attached to AgentOutcome. No Gateway/SAP execution.
# ---------------------------------------------------------------------------

from pathlib import Path

from sap_nexus_agent.match_decision import EscalationHandoff
from sap_nexus_agent.planner.plan_compiler import DryRunResult
from sap_nexus_agent.semantic_planning import (
    build_registry_snapshot,
    load_semantic_sources,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _real_planner_sources():
    """Load real registry sources + snapshot for dry-run tests."""
    sources = load_semantic_sources(REPO_ROOT)
    snapshot = build_registry_snapshot(sources)
    return snapshot, sources


def _multi_intent_parse_result():
    """Parse result that triggers ESCALATE_TO_PLANNER (inventory + PO)."""
    return IntentParseResult(
        intent=None,
        parameters={},
        missing_parameters=[],
        matched_intents=[
            _inventory_matched(),
            MatchedIntent(
                capability_id="MM.PurchaseOrder.GetList",
                parameters={},
                missing=[],
            ),
        ],
    )


def test_run_query_escalate_compiles_dry_run_from_handoff():
    """ESCALATE_TO_PLANNER -> orchestrator calls PlanCompiler.compile_dry_run;
    AgentOutcome carries a DryRunResult with a 2-node PlanGraph (inventory +
    purchase_order). No Gateway validate/execute."""
    gateway = FakeGatewayClient()
    snapshot, sources = _real_planner_sources()

    outcome = run_query(
        "查库存和采购订单",
        gateway,
        intent_adapter=lambda _text: _multi_intent_parse_result(),
        snapshot=snapshot,
        sources=sources,
    )

    assert outcome.status == "match_decision"
    assert outcome.match_decision is not None
    assert outcome.match_decision.decision_type == "ESCALATE_TO_PLANNER"
    assert outcome.dry_run is not None
    assert isinstance(outcome.dry_run, DryRunResult)
    nodes = outcome.dry_run.plan_graph["nodes"]
    assert len(nodes) == 2
    capability_ids = {n["capabilityId"] for n in nodes}
    assert capability_ids == {
        "MM.Inventory.GetAvailability",
        "MM.PurchaseOrder.GetList",
    }
    assert gateway.validate_calls == []
    assert gateway.execute_calls == []


def test_run_query_escalate_dry_run_binds_goal_constraints_from_matched_intents():
    """Dry-run plan_graph binds identifier inputs via goalConstraint sources
    derived from handoff.matched_intents parameters (material + plant)."""
    gateway = FakeGatewayClient()
    snapshot, sources = _real_planner_sources()

    def adapter(_text):
        return IntentParseResult(
            intent=None,
            parameters={},
            missing_parameters=[],
            matched_intents=[
                MatchedIntent(
                    capability_id="MM.Inventory.GetAvailability",
                    parameters={"material": "DEMOA2", "plant": "5100"},
                    missing=[],
                ),
                MatchedIntent(
                    capability_id="MM.PurchaseOrder.GetList",
                    parameters={},
                    missing=[],
                ),
            ],
        )

    outcome = run_query(
        "DEMOA2 在 5100 的库存，再列出近 30 天未清采购订单",
        gateway,
        intent_adapter=adapter,
        snapshot=snapshot,
        sources=sources,
    )

    assert outcome.dry_run is not None
    inv_nodes = [
        n
        for n in outcome.dry_run.plan_graph["nodes"]
        if n["capabilityId"] == "MM.Inventory.GetAvailability"
    ]
    assert inv_nodes, "expected an inventory producer node"
    bindings = inv_nodes[0]["parameterBindings"]
    bound_names = {b["parameterName"] for b in bindings}
    assert {"material", "plant"}.issubset(bound_names)
    source_kinds = {b["source"]["kind"] for b in bindings}
    assert source_kinds == {"goalConstraint"}


def test_run_query_escalate_dry_run_does_not_call_gateway():
    """Dry-run path must not call Gateway validate or execute (Design Doc §dry-run 输出)."""
    gateway = FakeGatewayClient()
    snapshot, sources = _real_planner_sources()

    outcome = run_query(
        "查库存和采购订单",
        gateway,
        intent_adapter=lambda _text: _multi_intent_parse_result(),
        snapshot=snapshot,
        sources=sources,
    )

    assert outcome.dry_run is not None
    assert gateway.validate_calls == []
    assert gateway.execute_calls == []


def test_run_query_escalate_dry_run_absent_when_decision_not_escalate():
    """dry_run is None for non-ESCALATE outcomes (SELECT/CLARIFY/REJECT/SHOW_OPTIONS)."""
    gateway = FakeGatewayClient()

    def adapter(_text):
        return IntentParseResult(
            intent="inventory_availability",
            parameters={"material": "MAT-9000", "plant": "1000"},
            missing_parameters=[],
        )

    outcome = run_query("查库存", gateway, intent_adapter=adapter)

    assert outcome.dry_run is None


def test_run_query_escalate_dry_run_loads_default_sources_when_not_injected():
    """When snapshot/sources are not injected, the orchestrator loads them
    from the registry (path discovery) so the dry-run still runs."""
    gateway = FakeGatewayClient()

    outcome = run_query(
        "查库存和采购订单",
        gateway,
        intent_adapter=lambda _text: _multi_intent_parse_result(),
    )

    assert outcome.status == "match_decision"
    assert outcome.dry_run is not None
    assert len(outcome.dry_run.plan_graph["nodes"]) == 2


def test_workbench_dict_serializes_dry_run_for_escalate():
    """outcome_to_workbench_dict emits a dryRun field (camelCase) for ESCALATE
    outcomes with planGraph / gaps / governanceFlags / rationale."""
    gateway = FakeGatewayClient()
    snapshot, sources = _real_planner_sources()

    outcome = run_query(
        "查库存和采购订单",
        gateway,
        intent_adapter=lambda _text: _multi_intent_parse_result(),
        snapshot=snapshot,
        sources=sources,
    )
    payload = outcome_to_workbench_dict(outcome)

    assert payload["status"] == "match_decision"
    assert payload["dryRun"] is not None
    dry_run = payload["dryRun"]
    assert isinstance(dry_run["planGraph"], dict)
    assert isinstance(dry_run["gaps"], list)
    assert isinstance(dry_run["governanceFlags"], list)
    assert isinstance(dry_run["rationale"], str) and dry_run["rationale"]
    nodes = dry_run["planGraph"]["nodes"]
    assert len(nodes) == 2


def test_workbench_dict_dry_run_none_when_absent():
    """dryRun is None for outcomes that do not carry a dry-run (SELECT path)."""
    outcome = AgentOutcome(status="rejected", response_text="已拒绝")

    payload = outcome_to_workbench_dict(outcome)

    assert payload["dryRun"] is None


def test_expand_combinations_single_key():
    base = {"material": "DEMOA2", "unit": "EA"}
    multi = {"plant": ["5200", "1000"]}
    combos = expand_combinations(base, multi)
    assert combos == [
        {"material": "DEMOA2", "unit": "EA", "plant": "5200"},
        {"material": "DEMOA2", "unit": "EA", "plant": "1000"},
    ]


def test_expand_combinations_multi_key_cartesian():
    base = {"unit": "EA"}
    multi = {"plant": ["5200", "1000"], "material": ["DEMOA2", "DEMOA4"]}
    combos = expand_combinations(base, multi)
    assert len(combos) == 4
    assert {"plant": "5200", "material": "DEMOA2", "unit": "EA"} in combos
    assert {"plant": "1000", "material": "DEMOA4", "unit": "EA"} in combos


def test_expand_combinations_empty_multi():
    assert expand_combinations({"material": "DEMOA2"}, {}) == [{"material": "DEMOA2"}]


def test_batch_combination_cap_constant():
    assert BATCH_COMBINATION_CAP == 20


def test_agent_outcome_has_combinations_field():
    outcome = AgentOutcome(status="awaiting_batch_confirm", combinations=[{"plant": "5200"}])
    assert outcome.combinations == [{"plant": "5200"}]
    outcome2 = AgentOutcome(status="success")
    assert outcome2.combinations is None


# ---------------------------------------------------------------------------
# run_query SELECT multi-value detection (Plan Task 8)
#
# Design Doc §4.4: when parsed.multi_parameters is non-empty, expand
# combinations BEFORE create_call_plan/validate/execute. Cap > BATCH_COMBINATION_CAP
# -> CLARIFY; otherwise -> awaiting_batch_confirm (no Gateway call).
# ---------------------------------------------------------------------------


def _multi_value_adapter(multi_parameters):
    """Stub adapter returning a preset multi_parameters IntentParseResult."""
    def _adapter(text, context=None):
        return IntentParseResult(
            intent=None,
            parameters={"unit": "EA"},
            missing_parameters=[],
            capability_id="MM.Inventory.GetAvailability",
            matched_intents=[MatchedIntent(
                capability_id="MM.Inventory.GetAvailability",
                parameters={"unit": "EA"},
                missing=[],
            )],
            multi_parameters=multi_parameters,
        )
    return _adapter


def test_run_query_multi_value_emits_awaiting_batch_confirm():
    gateway = FakeGatewayClient()
    adapter = _multi_value_adapter({"plant": ["5200", "1000"], "material": ["DEMOA2", "DEMOA4"]})
    outcome = run_query("DEMOA2 和 DEMOA4 在 5200、1000 的库存", gateway, intent_adapter=adapter)
    assert outcome.status == "awaiting_batch_confirm"
    assert outcome.combinations is not None
    assert len(outcome.combinations) == 4
    assert gateway.validate_calls == []
    assert gateway.execute_calls == []
    assert outcome.call_plan is not None
    assert outcome.call_plan.capability_id == "MM.Inventory.GetAvailability"


def test_run_query_multi_value_over_cap_emits_clarify():
    gateway = FakeGatewayClient()
    # 21 个 plant 组合 > cap 20
    plants = [f"P{i:03d}" for i in range(21)]
    adapter = _multi_value_adapter({"plant": plants, "material": ["DEMOA2"]})
    outcome = run_query("查 DEMOA2 在多个工厂的库存", gateway, intent_adapter=adapter)
    assert outcome.status == "clarification"
    assert "组合数" in (outcome.response_text or "")
    assert outcome.combinations is None
    assert gateway.validate_calls == []
    assert gateway.execute_calls == []


def test_run_query_single_value_still_executes():
    """单值回归：multi_parameters 空 -> 走原 execute 路径。"""
    gateway = FakeGatewayClient()
    # 单值 adapter 把 material/plant 放 parameters
    def _single_adapter(text, context=None):
        return IntentParseResult(
            intent=None,
            parameters={"material": "DEMOA2", "plant": "5100", "unit": "EA"},
            missing_parameters=[],
            capability_id="MM.Inventory.GetAvailability",
            matched_intents=[MatchedIntent(
                capability_id="MM.Inventory.GetAvailability",
                parameters={"material": "DEMOA2", "plant": "5100", "unit": "EA"},
                missing=[],
            )],
            multi_parameters={},
        )
    outcome = run_query("DEMOA2 在 5100 的库存", gateway, intent_adapter=_single_adapter)
    assert outcome.status == "success"
    assert outcome.fact is not None
    assert len(gateway.execute_calls) == 1


# ---------------------------------------------------------------------------
# Design Doc §4.4: continue_batch - per-combination validate+execute+build_fact
# with partial-failure aggregation. Invoked by workbench after user confirms an
# awaiting_batch_confirm outcome (NOT via run_query). READ-only inventory path.
# ---------------------------------------------------------------------------

from sap_nexus_agent.call_plan import create_call_plan
from sap_nexus_agent.execution_result import ExecutionResult, ValidationResult
from sap_nexus_agent.orchestrator import continue_batch


class _BatchFakeGateway:
    """Gateway stub: validate always ok; execute returns preset result per (material, plant)."""
    def __init__(self, exec_map):
        self._exec_map = exec_map
        self.validate_calls = []
        self.execute_calls = []

    def validate(self, capability_id, parameters):
        self.validate_calls.append((capability_id, parameters))
        return ValidationResult(
            trace_id="gw-v", capability_id=capability_id, success=True,
            error_type="NONE", messages=[],
        )

    def execute(self, capability_id, parameters, approval_id=None):
        self.execute_calls.append((capability_id, parameters))
        key = (parameters.get("material"), parameters.get("plant"))
        return self._exec_map.get(key, ExecutionResult(
            trace_id="gw-x", capability_id=capability_id, success=False,
            executor={"type": "JCO_RFC"}, return_messages=[],
            data={}, duration_ms=0, error_type="SAP_ERROR",
        ))


def _exec_ok(material, plant, qty):
    return ExecutionResult(
        trace_id=f"gw-{material}-{plant}", capability_id="MM.Inventory.GetAvailability",
        success=True, executor={"type": "JCO_RFC", "rfcName": "BAPI_MATERIAL_AVAILABILITY"},
        return_messages=[], data={"availableQuantity": qty, "unit": "EA"},
        duration_ms=5, error_type="NONE",
    )


def test_continue_batch_all_success():
    call_plan = create_call_plan("MM.Inventory.GetAvailability", {"unit": "EA"})
    combos = [
        {"material": "DEMOA2", "plant": "5200", "unit": "EA"},
        {"material": "DEMOA2", "plant": "1000", "unit": "EA"},
    ]
    gw = _BatchFakeGateway({
        ("DEMOA2", "5200"): _exec_ok("DEMOA2", "5200", 176),
        ("DEMOA2", "1000"): _exec_ok("DEMOA2", "1000", 0),
    })
    outcome = continue_batch(call_plan, combos, gw)
    assert outcome.status == "success"
    assert outcome.facts is not None
    assert len(outcome.facts) == 2
    assert len(gw.execute_calls) == 2
    assert "5200" in outcome.response_text and "176" in outcome.response_text


def test_continue_batch_partial_failure():
    call_plan = create_call_plan("MM.Inventory.GetAvailability", {"unit": "EA"})
    combos = [
        {"material": "DEMOA2", "plant": "5200", "unit": "EA"},
        {"material": "DEMOA2", "plant": "1000", "unit": "EA"},
    ]
    gw = _BatchFakeGateway({
        ("DEMOA2", "5200"): _exec_ok("DEMOA2", "5200", 176),
        # 1000 缺失 -> default failure
    })
    outcome = continue_batch(call_plan, combos, gw)
    assert outcome.status == "success"  # 部分失败不全局失败
    assert outcome.facts is not None
    assert len(outcome.facts) == 1
    assert "1000" in outcome.response_text  # 失败工厂被标注


def test_continue_batch_all_failure():
    call_plan = create_call_plan("MM.Inventory.GetAvailability", {"unit": "EA"})
    combos = [
        {"material": "DEMOA2", "plant": "5200", "unit": "EA"},
    ]
    gw = _BatchFakeGateway({})  # 全部 default failure
    outcome = continue_batch(call_plan, combos, gw)
    assert outcome.status == "failure"
    assert outcome.facts == []

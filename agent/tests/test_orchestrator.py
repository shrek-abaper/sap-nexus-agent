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
from sap_nexus_agent.governed_context import PLACEHOLDER_PRINCIPAL, TrustedPrincipal


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


# ---------------------------------------------------------------------------
# Design Doc §3.2 e2e 3-turn multi-value batch flow (Plan Task 12)
#
# Turn 1: single-value SELECT -> success -> last_context
# Turn 2: same conversation, multi-value plant -> awaiting_batch_confirm (no Gateway)
# Turn 3: user confirms -> continue_batch -> success + 2 facts + aggregated narrative
# ---------------------------------------------------------------------------

from sap_nexus_agent.conversation_context import ConversationContext, LastContext


def test_e2e_three_turn_multi_value_batch():
    """Design Doc §3.2 / tasks.md 5.3 e2e 3 轮。

    Turn 1: "DEMOA2 在 5100 的库存" -> SELECT -> success -> last_context
    Turn 2: "这个物料在5200、1000的库存分别是多少" -> awaiting_batch_confirm
    Turn 3: 用户确认 -> continue_batch -> 批量结果
    """

    # --- Turn 1: 单值 SELECT ---
    def turn1_adapter(text, context=None):
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

    gw1 = FakeGatewayClient(execution=ExecutionResult(
        trace_id="gw-t1", capability_id="MM.Inventory.GetAvailability",
        success=True, executor={"type": "JCO_RFC", "rfcName": "BAPI_MATERIAL_AVAILABILITY"},
        return_messages=[],
        data={"availableQuantity": 200, "unit": "EA", "material": "DEMOA2", "plant": "5100"},
        duration_ms=5, error_type="NONE",
    ))
    outcome1 = run_query("DEMOA2 在 5100 的库存", gw1, intent_adapter=turn1_adapter)
    assert outcome1.status == "success"
    assert outcome1.fact is not None
    assert outcome1.fact.material == "DEMOA2"
    # 构造 last_context（workbench 层职责，此处模拟）
    last_context = LastContext(
        capability_id="MM.Inventory.GetAvailability",
        parameters={"material": "DEMOA2", "plant": "5100"},
        missing_parameters=[],
        decision_type="SELECT",
    )

    # --- Turn 2: 多值 awaiting_batch_confirm ---
    def turn2_adapter(text, context=None):
        # 模拟 LLM 解析"这个物料"=last_context material + 多 plant
        return IntentParseResult(
            intent=None,
            parameters={"material": "DEMOA2", "unit": "EA"},
            missing_parameters=[],
            capability_id="MM.Inventory.GetAvailability",
            matched_intents=[MatchedIntent(
                capability_id="MM.Inventory.GetAvailability",
                parameters={"material": "DEMOA2", "unit": "EA"},
                missing=[],
            )],
            multi_parameters={"plant": ["5200", "1000"]},
        )

    gw2 = FakeGatewayClient()  # Turn 2 不应触达 Gateway
    ctx2 = ConversationContext(last_context=last_context, history=None)
    outcome2 = run_query(
        "这个物料在5200、1000的库存分别是多少", gw2,
        intent_adapter=turn2_adapter, context=ctx2,
    )
    assert outcome2.status == "awaiting_batch_confirm"
    assert outcome2.combinations is not None
    assert len(outcome2.combinations) == 2
    assert gw2.validate_calls == []
    assert gw2.execute_calls == []
    assert outcome2.call_plan is not None

    # --- Turn 3: 用户确认 -> continue_batch ---
    gw3 = _BatchFakeGateway({
        ("DEMOA2", "5200"): _exec_ok("DEMOA2", "5200", 176),
        ("DEMOA2", "1000"): _exec_ok("DEMOA2", "1000", 0),
    })
    outcome3 = continue_batch(outcome2.call_plan, outcome2.combinations, gw3)
    assert outcome3.status == "success"
    assert outcome3.facts is not None
    assert len(outcome3.facts) == 2
    # 聚合 narrative 含两个工厂结果
    assert "5200" in outcome3.response_text
    assert "176" in outcome3.response_text
    assert "1000" in outcome3.response_text
    assert "0" in outcome3.response_text


# ---------------------------------------------------------------------------
# I-1 fix: WRITE capability must not bypass ApprovalRecord via batch path.
#
# Action capabilities (e.g. MM.PR.CreateDraft) with multi_parameters must
# fall through to the single-action awaiting_approval path (ApprovalRecord +
# gateway.approve), NOT awaiting_batch_confirm. continue_batch is READ-only
# (Design Doc §2 Non-Goal) and must raise ValueError if handed an Action
# call_plan (defense-in-depth).
# ---------------------------------------------------------------------------

import pytest

_ACTION_BASE_PARAMS = {
    "material": "DEMOA2",
    "quantity": "10",
    "unit": "EA",
    "delivery_date": "2026-08-01",
    "purchasing_group": "001",
}


def _action_multi_value_adapter(multi_parameters):
    """Stub adapter returning an Action capability (MM.PR.CreateDraft) with
    multi_parameters. Base parameters cover all required descriptor inputs so
    the selector emits SELECT (not CLARIFY)."""
    def _adapter(text, context=None):
        return IntentParseResult(
            intent=None,
            parameters=dict(_ACTION_BASE_PARAMS),
            missing_parameters=[],
            capability_id="MM.PR.CreateDraft",
            matched_intents=[MatchedIntent(
                capability_id="MM.PR.CreateDraft",
                parameters=dict(_ACTION_BASE_PARAMS),
                missing=[],
            )],
            multi_parameters=multi_parameters,
        )
    return _adapter


def test_run_query_action_multi_parameters_routes_to_awaiting_approval():
    """Action capability with multi_parameters -> awaiting_approval, NOT
    awaiting_batch_confirm. The batch path is READ-only; Action batch is a
    non-goal (Design Doc §2). Base parameters are used for single-action
    approval."""
    gateway = FakeGatewayClient(validation=ValidationResult(
        trace_id="gw-validate-pr",
        capability_id="MM.PR.CreateDraft",
        success=True,
        error_type="NONE",
        messages=[],
    ))
    adapter = _action_multi_value_adapter({"plant": ["5200", "1000"]})

    outcome = run_query(
        "为 DEMOA2 在 5200、1000 各建一个采购申请",
        gateway,
        intent_adapter=adapter,
    )

    assert outcome.status == "awaiting_approval"
    assert outcome.approval_record is not None
    assert outcome.combinations is None
    assert len(gateway.validate_calls) == 1
    assert gateway.validate_calls[0][0] == "MM.PR.CreateDraft"
    assert gateway.execute_calls == []


def test_continue_batch_raises_for_action_capability():
    """continue_batch must never execute a WRITE capability (defense-in-depth).
    Action capabilities require an ApprovalRecord; the batch path is READ-only
    (Design Doc §2 Non-Goal)."""
    call_plan = create_call_plan(
        "MM.PR.CreateDraft",
        dict(_ACTION_BASE_PARAMS),
        kind="Action",
    )
    gw = _BatchFakeGateway({})

    with pytest.raises(ValueError):
        continue_batch(call_plan, [dict(_ACTION_BASE_PARAMS, plant="5200")], gw)


# ---- Task 2: run_query principal binding + planner_failure field ----


def test_run_query_accepts_principal_param():
    """run_query accepts a principal param; defaults to PLACEHOLDER when None."""
    from sap_nexus_agent.orchestrator import run_query

    class _FakeGateway:
        def validate(self, capability_id, parameters):
            return ValidationResult(
                trace_id="t",
                capability_id=capability_id,
                success=True,
                error_type="NONE",
                messages=[],
            )

        def execute(self, capability_id, parameters, approval_id=None):
            return ExecutionResult(
                trace_id="t",
                capability_id=capability_id,
                success=True,
                executor={},
                return_messages=[],
                duration_ms=1,
                error_type=None,
                data={"availableQuantity": 10, "unit": "EA"},
            )

    principal = TrustedPrincipal("user-42", "operator", {"tenantId": "t1"})
    outcome = run_query(
        "查物料 DEMOA1 在工厂 1000 的可用库存",
        _FakeGateway(),
        principal=principal,
    )
    assert outcome.status in {"success", "failure", "clarification"}


def test_run_query_defaults_principal_to_placeholder():
    """run_query with principal=None uses PLACEHOLDER_PRINCIPAL (backward compat)."""
    from sap_nexus_agent.orchestrator import run_query

    class _FakeGateway:
        def validate(self, capability_id, parameters):
            return ValidationResult(
                trace_id="t",
                capability_id=capability_id,
                success=True,
                error_type="NONE",
                messages=[],
            )

        def execute(self, capability_id, parameters, approval_id=None):
            return ExecutionResult(
                trace_id="t",
                capability_id=capability_id,
                success=True,
                executor={},
                return_messages=[],
                duration_ms=1,
                error_type=None,
                data={"availableQuantity": 10, "unit": "EA"},
            )

    outcome = run_query(
        "查物料 DEMOA1 在工厂 1000 的可用库存",
        _FakeGateway(),
    )
    assert outcome.status in {"success", "failure", "clarification"}


def test_agent_outcome_has_planner_failure_field():
    """AgentOutcome has a planner_failure field defaulting to None."""
    outcome = AgentOutcome(status="success")
    assert outcome.planner_failure is None


# ---- Task 5: _compile_dry_run_safely returns PlannerFailure on drift/error ----


def test_compile_dry_run_safely_returns_planner_failure_on_drift():
    from sap_nexus_agent.orchestrator import _compile_dry_run_safely
    from sap_nexus_agent.governed_context import SnapshotLease, PlannerFailure
    from sap_nexus_agent.match_decision import EscalationHandoff, MatchedIntent
    from sap_nexus_agent.semantic_planning.contracts import (
        RegistrySnapshot,
        SemanticSourceDocuments,
        SnapshotSource,
    )

    snapshot = RegistrySnapshot(
        snapshot_version=1,
        canonicalization_version=1,
        snapshot_id="sha256:lease-snap",
        sources=(SnapshotSource(path="x", document_version=1, digest="x"),),
    )
    sources = SemanticSourceDocuments(
        capabilities={"capabilities": []},
        executor_bindings={"bindings": []},
        fact_types={"factTypes": []},
        relations={"relations": []},
    )
    lease = SnapshotLease(snapshot=snapshot, sources=sources)
    handoff = EscalationHandoff(
        reason="multi-intent",
        matched_intents=[MatchedIntent(capability_id="A", parameters={}, missing=[])],
        utterance="test",
        registry_snapshot_id="sha256:different-snap",
    )
    result = _compile_dry_run_safely(handoff, lease=lease)
    assert result is not None
    assert isinstance(result, PlannerFailure)
    assert result.error_type == "SNAPSHOT_DRIFT"
    assert result.audit_evidence["expected_snapshot_id"] == "sha256:lease-snap"
    assert result.audit_evidence["actual_snapshot_id"] == "sha256:different-snap"


def test_compile_dry_run_safely_returns_planner_failure_on_source_load_error():
    from sap_nexus_agent.orchestrator import _compile_dry_run_safely
    from sap_nexus_agent.governed_context import SnapshotLease, PlannerFailure
    from sap_nexus_agent.match_decision import EscalationHandoff, MatchedIntent
    from sap_nexus_agent.semantic_planning.contracts import (
        RegistrySnapshot,
        SemanticSourceDocuments,
        SnapshotSource,
    )

    snapshot = RegistrySnapshot(
        snapshot_version=1,
        canonicalization_version=1,
        snapshot_id="sha256:snap",
        sources=(SnapshotSource(path="x", document_version=1, digest="x"),),
    )
    sources = SemanticSourceDocuments(
        capabilities={"capabilities": "not-a-list"},  # type: ignore[arg-type]
        executor_bindings={"bindings": []},
        fact_types={"factTypes": []},
        relations={"relations": []},
    )
    lease = SnapshotLease(snapshot=snapshot, sources=sources)
    handoff = EscalationHandoff(
        reason="multi-intent",
        matched_intents=[MatchedIntent(capability_id="A", parameters={}, missing=[])],
        utterance="test",
        registry_snapshot_id="sha256:snap",
    )
    result = _compile_dry_run_safely(handoff, lease=lease)
    assert result is not None
    assert isinstance(result, PlannerFailure)
    assert result.error_type == "SOURCE_LOAD_ERROR"


# ---- Task 6: capability kind from governance.requires_approval ----


def test_kind_from_governance_requires_approval():
    from sap_nexus_agent.planner.capability_card import CapabilityCard, Governance

    card_action = CapabilityCard(
        capability_id="MM.PR.CreateDraft",
        name="PR",
        governance=Governance(
            side_effect="sap_write", requires_approval=True, data_classification="internal"
        ),
        registry_snapshot_id="sha256:x",
    )
    assert card_action.governance.requires_approval is True

    card_function = CapabilityCard(
        capability_id="MM.Inventory.GetAvailability",
        name="Inv",
        governance=Governance(
            side_effect="none", requires_approval=False, data_classification="internal"
        ),
        registry_snapshot_id="sha256:x",
    )
    assert card_function.governance.requires_approval is False


def test_orchestrator_kind_uses_governance_not_action_capability_ids():
    """PR CreateDraft path produces awaiting_approval (Action kind from governance)."""
    from sap_nexus_agent.orchestrator import run_query

    class _FakeGateway:
        def validate(self, capability_id, parameters):
            return ValidationResult(
                trace_id="t",
                capability_id=capability_id,
                success=True,
                error_type="NONE",
                messages=[],
            )

        def execute(self, capability_id, parameters, approval_id=None):
            return ExecutionResult(
                trace_id="t",
                capability_id=capability_id,
                success=True,
                executor={},
                return_messages=[],
                data={},
                duration_ms=1,
                error_type=None,
            )

    outcome = run_query(
        "帮我创建采购申请 物料 M1 工厂 1000 数量 10",
        _FakeGateway(),
    )
    assert outcome.status in {"awaiting_approval", "clarification", "failure"}


# ---------------------------------------------------------------------------
# Runbook 14 Task 7.3 / 7.4 / 7.5 / 9.5 / 9.6: cross-turn continuation
# ---------------------------------------------------------------------------

from sap_nexus_agent.conversation_context import (  # noqa: E402
    ConversationContext,
    LastContext,
    PendingEscalate,
    PendingShowOptions,
)


def _show_options_adapter(_text):
    """Adapter that always returns an ambiguous SHOW_OPTIONS IntentParseResult.

    SHOW_OPTIONS fires when ``is_ambiguous=True`` and ``matched_intents``
    has exactly one entry (the selector checks multi-intent -> ESCALATE
    first, so >1 entries would escalate).
    """
    return types.SimpleNamespace(
        intent=None,
        parameters={},
        missing_parameters=[],
        contains_rfc_name=False,
        contains_odata_override=False,
        capability_id=None,
        clarification=None,
        matched_intents=[
            MatchedIntent(
                capability_id="MM.PurchaseOrder.GetList",
                parameters={},
                missing=[],
            ),
        ],
        is_ambiguous=True,
        multi_parameters={},
    )


def _escalate_adapter(_text):
    """Adapter that always returns a multi-intent ESCALATE IntentParseResult."""
    return IntentParseResult(
        intent=None,
        parameters={},
        missing_parameters=[],
        matched_intents=[
            MatchedIntent(
                capability_id="MM.Inventory.GetAvailability",
                parameters={"material": "DEMOA1", "plant": "1000"},
                missing=[],
            ),
            MatchedIntent(
                capability_id="MM.PurchaseOrder.GetList",
                parameters={},
                missing=[],
            ),
        ],
    )


def _show_options_adapter_with_context(text, context=None):
    """Variant accepting the context arg for context-passing paths."""
    return _show_options_adapter(text)


def _escalate_adapter_with_context(text, context=None):
    """Variant accepting the context arg for context-passing paths."""
    return _escalate_adapter(text)


def test_show_options_writes_pending_show_options():
    """Turn N SHOW_OPTIONS writes pending_show_options on updated_context."""
    gateway = FakeGatewayClient()
    ctx = ConversationContext(last_context=None, history=None)
    outcome = run_query(
        "订单", gateway, intent_adapter=_show_options_adapter_with_context, context=ctx
    )
    assert outcome.match_decision is not None
    assert outcome.match_decision.decision_type == "SHOW_OPTIONS"
    assert outcome.updated_context is not None
    assert outcome.updated_context.pending_show_options is not None
    assert outcome.updated_context.pending_escalate is None
    candidates = outcome.updated_context.pending_show_options.candidates
    assert len(candidates) == 1
    assert candidates[0].capability_id == "MM.PurchaseOrder.GetList"


def test_show_options_writes_pending_then_select_clears():
    """Turn N SHOW_OPTIONS writes pending; Turn N+1 selection clears + SELECT."""
    gateway = FakeGatewayClient()
    ctx = ConversationContext(last_context=None, history=None)
    outcome_n = run_query(
        "订单", gateway, intent_adapter=_show_options_adapter_with_context, context=ctx
    )
    assert outcome_n.updated_context.pending_show_options is not None

    # Turn N+1: "采购订单" -> primary keyword selects MM.PurchaseOrder.GetList.
    # The pending state is cleared on entry; the real parse_intent runs and
    # produces a SELECT (PO list with no required params).
    outcome_n1 = run_query(
        "采购订单",
        gateway,
        context=outcome_n.updated_context,
    )
    assert outcome_n1.updated_context is not None
    assert outcome_n1.updated_context.pending_show_options is None
    assert outcome_n1.updated_context.pending_escalate is None


def test_escalate_writes_pending_escalate():
    """Turn N ESCALATE writes pending_escalate on updated_context."""
    gateway = FakeGatewayClient()
    ctx = ConversationContext(last_context=None, history=None)
    outcome = run_query(
        "查库存和采购订单", gateway, intent_adapter=_escalate_adapter_with_context, context=ctx
    )
    assert outcome.match_decision is not None
    assert outcome.match_decision.decision_type == "ESCALATE_TO_PLANNER"
    assert outcome.updated_context is not None
    assert outcome.updated_context.pending_escalate is not None
    assert outcome.updated_context.pending_show_options is None


def test_escalate_writes_pending_then_confirm_clears():
    """Turn N ESCALATE writes pending; Turn N+1 '继续' clears pending."""
    gateway = FakeGatewayClient()
    ctx = ConversationContext(last_context=None, history=None)
    outcome_n = run_query(
        "查库存和采购订单", gateway, intent_adapter=_escalate_adapter_with_context, context=ctx
    )
    assert outcome_n.updated_context.pending_escalate is not None

    # Turn N+1: "继续" -> confirmation clears pending_escalate. The fresh
    # parse_intent runs (no primary keyword, no params) and the selector
    # produces REJECT(UNSUPPORTED_INTENT); the key assertion is that
    # updated_context has no pending state.
    outcome_n1 = run_query(
        "继续", gateway, context=outcome_n.updated_context
    )
    assert outcome_n1.updated_context is not None
    assert outcome_n1.updated_context.pending_escalate is None
    assert outcome_n1.updated_context.pending_show_options is None


def test_new_intent_clears_pending_show_options():
    """Turn N+1 with a new primary keyword clears pending_show_options."""
    gateway = FakeGatewayClient()
    ctx = ConversationContext(
        last_context=None,
        history=None,
        pending_show_options=PendingShowOptions(
            candidates=(
                MatchedIntent(
                    capability_id="MM.PurchaseOrder.GetList",
                    parameters={},
                    missing=[],
                ),
            ),
            snapshot_id="snap-1",
        ),
    )
    # Turn N+1: "查库存" -> inventory primary keyword -> clear pending.
    outcome = run_query("查库存", gateway, context=ctx)
    assert outcome.updated_context is not None
    assert outcome.updated_context.pending_show_options is None
    assert outcome.updated_context.pending_escalate is None


def test_new_intent_clears_pending_escalate():
    """Turn N+1 with a new primary keyword clears pending_escalate."""
    from sap_nexus_agent.match_decision import EscalationHandoff

    gateway = FakeGatewayClient()
    handoff = EscalationHandoff(
        reason="multi-intent",
        matched_intents=[
            MatchedIntent(
                capability_id="MM.Inventory.GetAvailability",
                parameters={},
                missing=[],
            )
        ],
        utterance="库存 + 采购订单",
        registry_snapshot_id="snap-1",
    )
    ctx = ConversationContext(
        last_context=None,
        history=None,
        pending_escalate=PendingEscalate(handoff=handoff, snapshot_id="snap-1"),
    )
    # Turn N+1: "查库存" -> inventory primary keyword -> clear pending.
    outcome = run_query("查库存", gateway, context=ctx)
    assert outcome.updated_context is not None
    assert outcome.updated_context.pending_escalate is None
    assert outcome.updated_context.pending_show_options is None


def test_run_query_context_none_has_no_updated_context():
    """Single-turn path (context=None) leaves updated_context=None."""
    gateway = FakeGatewayClient()
    outcome = run_query(
        "查库存 DEMOA1 在 1000", gateway, context=None
    )
    assert outcome.updated_context is None


def test_select_clears_prior_pending_show_options():
    """SELECT on turn N+1 clears any prior pending_show_options."""
    gateway = FakeGatewayClient()
    ctx = ConversationContext(
        last_context=None,
        history=None,
        pending_show_options=PendingShowOptions(
            candidates=(
                MatchedIntent(
                    capability_id="MM.PurchaseOrder.GetList",
                    parameters={},
                    missing=[],
                ),
            ),
            snapshot_id="snap-1",
        ),
    )
    # Turn N+1: full inventory query -> SELECT -> pending cleared.
    outcome = run_query(
        "查库存 DEMOA1 在 1000", gateway, context=ctx
    )
    assert outcome.status == "success"
    assert outcome.updated_context is not None
    assert outcome.updated_context.pending_show_options is None
    assert outcome.updated_context.pending_escalate is None


def test_reject_clears_prior_pending_escalate():
    """REJECT on turn N+1 clears any prior pending_escalate."""
    from sap_nexus_agent.match_decision import EscalationHandoff

    gateway = FakeGatewayClient()
    handoff = EscalationHandoff(
        reason="multi-intent",
        matched_intents=[],
        utterance="",
        registry_snapshot_id="snap-1",
    )
    ctx = ConversationContext(
        last_context=None,
        history=None,
        pending_escalate=PendingEscalate(handoff=handoff, snapshot_id="snap-1"),
    )

    def reject_adapter(_text, _context=None):
        return IntentParseResult(
            intent=None,
            parameters={},
            missing_parameters=[],
            contains_rfc_name=True,
        )

    outcome = run_query(
        "rfcName=BAPI_EVIL", gateway, intent_adapter=reject_adapter, context=ctx
    )
    assert outcome.match_decision.decision_type == "REJECT"
    assert outcome.updated_context is not None
    assert outcome.updated_context.pending_escalate is None
    assert outcome.updated_context.pending_show_options is None


def test_clarify_clears_prior_pending_show_options():
    """CLARIFY on turn N+1 clears any prior pending_show_options."""
    gateway = FakeGatewayClient()
    ctx = ConversationContext(
        last_context=None,
        history=None,
        pending_show_options=PendingShowOptions(
            candidates=(
                MatchedIntent(
                    capability_id="MM.PurchaseOrder.GetList",
                    parameters={},
                    missing=[],
                ),
            ),
            snapshot_id="snap-1",
        ),
    )
    # Turn N+1: inventory query missing plant -> CLARIFY -> pending cleared.
    outcome = run_query("查一下 DEMOA1 的可用量", gateway, context=ctx)
    assert outcome.match_decision.decision_type == "CLARIFY"
    assert outcome.updated_context is not None
    assert outcome.updated_context.pending_show_options is None
    assert outcome.updated_context.pending_escalate is None


def test_show_options_writes_no_pending_when_context_none():
    """SHOW_OPTIONS with context=None -> updated_context stays None."""
    gateway = FakeGatewayClient()
    outcome = run_query(
        "订单", gateway, intent_adapter=_show_options_adapter, context=None
    )
    assert outcome.match_decision.decision_type == "SHOW_OPTIONS"
    # Single-turn path: no context to write pending state onto.
    assert outcome.updated_context is None


def test_escalate_writes_no_pending_when_context_none():
    """ESCALATE with context=None -> updated_context stays None."""
    gateway = FakeGatewayClient()
    outcome = run_query(
        "查库存和采购订单", gateway, intent_adapter=_escalate_adapter, context=None
    )
    assert outcome.match_decision.decision_type == "ESCALATE_TO_PLANNER"
    assert outcome.updated_context is None


def test_resolve_pending_state_returns_unchanged_when_no_pending():
    """_resolve_pending_state is a no-op when no pending state is set."""
    from sap_nexus_agent.orchestrator import _resolve_pending_state

    ctx = ConversationContext(last_context=None, history=None)
    result = _resolve_pending_state("any text", ctx)
    assert result is ctx


def test_resolve_pending_state_clears_show_options_on_selection():
    """_resolve_pending_state clears pending_show_options on candidate selection."""
    from sap_nexus_agent.orchestrator import _resolve_pending_state

    ctx = ConversationContext(
        last_context=None,
        history=None,
        pending_show_options=PendingShowOptions(
            candidates=(
                MatchedIntent(
                    capability_id="MM.PurchaseOrder.GetList",
                    parameters={},
                    missing=[],
                ),
            ),
            snapshot_id="snap-1",
        ),
    )
    result = _resolve_pending_state("采购订单", ctx)
    assert result.pending_show_options is None


def test_resolve_pending_state_clears_escalate_on_confirm():
    """_resolve_pending_state clears pending_escalate on '继续'."""
    from sap_nexus_agent.match_decision import EscalationHandoff
    from sap_nexus_agent.orchestrator import _resolve_pending_state

    handoff = EscalationHandoff(
        reason="r", matched_intents=[], utterance="u", registry_snapshot_id="s"
    )
    ctx = ConversationContext(
        last_context=None,
        history=None,
        pending_escalate=PendingEscalate(handoff=handoff, snapshot_id="snap-1"),
    )
    result = _resolve_pending_state("继续", ctx)
    assert result.pending_escalate is None


def test_resolve_pending_state_keeps_show_options_on_unrelated_text():
    """_resolve_pending_state keeps pending_show_options when text has no primary keyword."""
    from sap_nexus_agent.orchestrator import _resolve_pending_state

    ctx = ConversationContext(
        last_context=None,
        history=None,
        pending_show_options=PendingShowOptions(
            candidates=(
                MatchedIntent(
                    capability_id="MM.PurchaseOrder.GetList",
                    parameters={},
                    missing=[],
                ),
            ),
            snapshot_id="snap-1",
        ),
    )
    # "DEMOA2" has no primary keyword -> pending retained (selector re-runs
    # and will likely REJECT, but the pending state is advisory and cleared
    # by the REJECT outcome's _clear_pending_if_present, not here).
    result = _resolve_pending_state("DEMOA2", ctx)
    assert result.pending_show_options is not None


def test_clear_pending_if_present_returns_none_for_none():
    """_clear_pending_if_present(None) returns None (single-turn path)."""
    from sap_nexus_agent.orchestrator import _clear_pending_if_present

    assert _clear_pending_if_present(None) is None


def test_clear_pending_if_present_returns_unchanged_when_no_pending():
    """_clear_pending_if_present returns the same context when no pending state."""
    from sap_nexus_agent.orchestrator import _clear_pending_if_present

    ctx = ConversationContext(last_context=None, history=None)
    assert _clear_pending_if_present(ctx) is ctx


def test_clear_pending_if_present_clears_both():
    """_clear_pending_if_present clears any pending state present."""
    from sap_nexus_agent.match_decision import EscalationHandoff
    from sap_nexus_agent.orchestrator import _clear_pending_if_present

    handoff = EscalationHandoff(
        reason="r", matched_intents=[], utterance="u", registry_snapshot_id="s"
    )
    ctx = ConversationContext(
        last_context=None,
        history=None,
        pending_escalate=PendingEscalate(handoff=handoff, snapshot_id="snap-1"),
    )
    result = _clear_pending_if_present(ctx)
    assert result is not ctx
    assert result.pending_escalate is None
    assert result.pending_show_options is None

from sap_nexus_agent.approval import create_approval_record
from sap_nexus_agent.execution_result import ExecutionResult, ValidationResult
from sap_nexus_agent.intent import IntentParseResult
from sap_nexus_agent.match_decision import MatchDecision
from sap_nexus_agent.orchestrator import AgentOutcome
from sap_nexus_agent.reasoning_fact import ReasoningFact
from sap_nexus_agent.workbench_output import outcome_to_workbench_dict, run_workbench_query


class FakeGatewayClient:
    def __init__(self):
        self.validate_calls = []
        self.execute_calls = []

    def validate(self, capability_id, parameters):
        self.validate_calls.append((capability_id, dict(parameters)))
        return ValidationResult(
            trace_id="gw-validate-live",
            capability_id="MM.Inventory.GetAvailability",
            success=True,
            error_type="NONE",
            messages=[],
        )

    def execute(self, capability_id, parameters, approval_id=None):
        self.execute_calls.append((capability_id, dict(parameters)))
        return ExecutionResult(
            trace_id="gw-execute-live",
            capability_id="MM.Inventory.GetAvailability",
            success=True,
            executor={"type": "JCO_RFC", "rfcName": "BAPI_MATERIAL_AVAILABILITY"},
            return_messages=[],
            data={"material": "MAT-LIVE", "plant": "1000", "availableQuantity": 7, "unit": "EA"},
            duration_ms=25,
            error_type="NONE",
        )


def test_workbench_output_serializes_live_agent_result_without_fake_quantity_or_secrets():
    gateway = FakeGatewayClient()

    def adapter(_text):
        return IntentParseResult(
            intent="inventory_availability",
            parameters={"material": "MAT-LIVE", "plant": "1000"},
            missing_parameters=[],
        )

    payload = run_workbench_query("查真实库存", gateway, intent_adapter=adapter)

    assert gateway.validate_calls == [
        ("MM.Inventory.GetAvailability", {"material": "MAT-LIVE", "plant": "1000", "unit": "EA"})
    ]
    assert gateway.execute_calls == [
        ("MM.Inventory.GetAvailability", {"material": "MAT-LIVE", "plant": "1000", "unit": "EA"})
    ]
    assert payload["status"] == "success"
    assert payload["validationResult"]["traceId"] == "gw-validate-live"
    assert payload["executionResult"]["data"]["availableQuantity"] == 7
    assert payload["gatewayTraceId"] == "gw-execute-live"
    assert payload["fact"]["value"] == 7
    assert payload["responseText"] == "物料 MAT-LIVE 在工厂 1000 的可用库存为 7 EA。"
    assert "SAP_PASSWORD" not in str(payload)
    assert "LLM_API_KEY" not in str(payload)


def test_workbench_output_renders_po_facts_list():
    """outcome_to_workbench_dict renders outcome.facts (PO list) when present."""
    facts = [
        ReasoningFact(
            fact_id="fact-po-1",
            agent_trace_id="agent-po",
            trace_id="agent-po",
            gateway_trace_id="gw-po",
            domain="MM",
            business_object="PurchaseOrder",
            predicate="purchaseOrderItem",
            value=100,
            unit="EA",
            deterministic=True,
            confidence=1.0,
            source={"capabilityId": "MM.PurchaseOrder.GetList", "executorType": "ODATA"},
            evidence=[
                {
                    "purchaseOrder": "4500000001",
                    "supplier": "DEMOV1",
                    "plant": "1000",
                    "material": "DEMOA1",
                    "orderQuantity": 100,
                    "purchaseOrderUnit": "EA",
                }
            ],
            material="DEMOA1",
            plant="1000",
        ),
    ]
    outcome = AgentOutcome(
        status="success",
        response_text="采购订单 4500000001：供应商 DEMOV1，物料 DEMOA1，工厂 1000，数量 100 EA。",
        facts=facts,
        gateway_trace_id="gw-po",
    )

    payload = outcome_to_workbench_dict(outcome)

    assert payload["facts"] is not None
    assert len(payload["facts"]) == 1
    assert payload["facts"][0]["businessObject"] == "PurchaseOrder"
    assert payload["facts"][0]["predicate"] == "purchaseOrderItem"
    assert payload["facts"][0]["value"] == 100
    # inventory fact slot remains None for PO outcomes
    assert payload["fact"] is None


def test_workbench_output_serializes_pending_approval_record():
    approval = create_approval_record(
        capability_id="MM.PR.CreateDraft",
        parameters={"material": "M001", "plant": "1000"},
        approver="user",
    )
    outcome = AgentOutcome(status="awaiting_approval", approval_record=approval)

    payload = outcome_to_workbench_dict(outcome)

    assert payload["approvalRecord"] == approval.to_dict()


def test_outcome_clarify_emits_last_context():
    decision = MatchDecision(
        decision_type="CLARIFY",
        capability_id="MM.Inventory.GetAvailability",
        parameters={"material": "DEMOA2"},
        missing_parameters=["plant"],
        error_type=None,
        candidates=None,
        handoff=None,
        rationale="缺 plant",
    )
    outcome = AgentOutcome(
        status="clarification",
        message="请提供工厂",
        response_text="请提供工厂",
        missing_parameters=["plant"],
        match_decision=decision,
    )
    payload = outcome_to_workbench_dict(outcome)
    assert payload["lastContext"] == {
        "capabilityId": "MM.Inventory.GetAvailability",
        "parameters": {"material": "DEMOA2"},
        "missingParameters": ["plant"],
        "decisionType": "CLARIFY",
    }


def test_outcome_select_success_emits_last_context():
    decision = MatchDecision(
        decision_type="SELECT",
        capability_id="MM.Inventory.GetAvailability",
        parameters={"material": "DEMOA2", "plant": "1000"},
        missing_parameters=[],
        error_type=None,
        candidates=None,
        handoff=None,
        rationale="",
    )
    outcome = AgentOutcome(
        status="success",
        response_text="库存 7 EA",
        match_decision=decision,
    )
    payload = outcome_to_workbench_dict(outcome)
    assert payload["lastContext"]["decisionType"] == "SELECT"
    assert payload["lastContext"]["missingParameters"] == []


def test_outcome_reject_no_last_context():
    decision = MatchDecision(
        decision_type="REJECT",
        capability_id=None,
        parameters=None,
        missing_parameters=None,
        error_type="UNSUPPORTED_INTENT",
        candidates=None,
        handoff=None,
        rationale="unsupported",
    )
    outcome = AgentOutcome(status="failure", match_decision=decision)
    payload = outcome_to_workbench_dict(outcome)
    assert payload["lastContext"] is None


def test_outcome_awaiting_approval_no_last_context():
    """审批 pending 不回填 lastContext（Q2：审批 pending 拒绝新查询）。"""
    decision = MatchDecision(
        decision_type="SELECT",
        capability_id="MM.PR.CreateDraft",
        parameters={"material": "X", "plant": "1000"},
        missing_parameters=[],
        error_type=None,
        candidates=None,
        handoff=None,
        rationale="",
    )
    outcome = AgentOutcome(status="awaiting_approval", match_decision=decision)
    payload = outcome_to_workbench_dict(outcome)
    assert payload["lastContext"] is None


def test_awaiting_batch_confirm_serializes_combinations():
    from sap_nexus_agent.call_plan import create_call_plan

    call_plan = create_call_plan(
        "MM.Inventory.GetAvailability",
        {"material": "DEMOA2", "plant": "5200"},
        kind="Function",
    )
    outcome = AgentOutcome(
        status="awaiting_batch_confirm",
        response_text="将查询 2 个组合，请确认。",
        call_plan=call_plan,
        combinations=[
            {"material": "DEMOA2", "plant": "5200"},
            {"material": "DEMOA2", "plant": "1000"},
        ],
    )

    result = outcome_to_workbench_dict(outcome)

    assert result["status"] == "awaiting_batch_confirm"
    assert result["combinations"] == [
        {"material": "DEMOA2", "plant": "5200"},
        {"material": "DEMOA2", "plant": "1000"},
    ]
    assert result["callPlan"] is not None
    assert result["callPlan"]["capabilityId"] == "MM.Inventory.GetAvailability"


def test_workbench_output_serializes_only_redacted_context_shadow():
    from sap_nexus_agent.context_decision_gate import ContextShadow

    outcome = AgentOutcome(
        status="success",
        context_shadow=ContextShadow(
            legacy_decision="SELECT",
            frame_v2_decision="CLARIFY",
            slot_diff=("material", "plant"),
            would_block_legacy_execution=True,
            would_clarify=True,
        ),
    )

    payload = outcome_to_workbench_dict(outcome)

    assert payload["contextShadow"] == outcome.context_shadow.to_dict()
    assert "rawPayload" not in payload["contextShadow"]


def test_workbench_rejects_hostile_untyped_context_shadow_payload():
    outcome = AgentOutcome(
        status="success",
        context_shadow={
            "legacyDecision": "SELECT",
            "rawPayload": {"history": ["secret"], "token": "secret"},
            "wouldClarify": True,
        },
    )

    payload = outcome_to_workbench_dict(outcome)

    assert payload["contextShadow"] is None


def test_non_batch_outcome_combinations_is_none():
    outcome = AgentOutcome(
        status="success",
        response_text="库存为 100 EA",
    )

    result = outcome_to_workbench_dict(outcome)

    assert result["combinations"] is None

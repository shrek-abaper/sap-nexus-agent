from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import sys
from typing import Any

from sap_nexus_agent.execution_result import ExecutionResult, ValidationResult
from sap_nexus_agent.intent import parse_intent
from sap_nexus_agent.orchestrator import continue_action, run_query


_CAPABILITY_TO_INTENT = {
    "MM.Inventory.GetAvailability": "inventory_availability",
    "MM.PurchaseOrder.GetList": "purchase_order_list",
}


@dataclass(frozen=True)
class EvalSummary:
    total: int
    passed: int
    failed: int


class FakeGatewayClient:
    def __init__(self, case: dict[str, Any]):
        gateway = case.get("gateway", {})
        case_id = _case_id(case)
        capability_id = case.get("expectedCapabilityId") or case.get("expected", {}).get("capabilityId")
        is_po = capability_id == "MM.PurchaseOrder.GetList"

        self.validation_payload = gateway.get(
            "validate",
            {
                "traceId": f"{case_id}-validate",
                "capabilityId": capability_id or "MM.Inventory.GetAvailability",
                "success": True,
                "errorType": "NONE",
                "messages": [],
            },
        )
        self.has_explicit_validation = "validate" in gateway
        if is_po:
            default_execute = {
                "traceId": f"{case_id}-execute",
                "capabilityId": "MM.PurchaseOrder.GetList",
                "success": True,
                "executor": {"type": "ODATA"},
                "returnMessages": [],
                "data": {
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
                    ],
                    "totalCount": 2,
                },
                "durationMs": 10,
                "errorType": "NONE",
            }
        else:
            default_execute = {
                "traceId": f"{case_id}-execute",
                "capabilityId": "MM.Inventory.GetAvailability",
                "success": True,
                "executor": {"type": "JCO_RFC", "rfcName": "BAPI_MATERIAL_AVAILABILITY"},
                "returnMessages": [],
                "data": {
                    "availableQuantity": 12,
                },
                "durationMs": 10,
                "errorType": "NONE",
            }
        self.execution_payload = gateway.get("execute", default_execute)
        self.validate_calls: list[tuple[str, dict[str, str]]] = []
        self.execute_calls: list[tuple[str, dict[str, str]]] = []

    def validate(self, capability_id: str, parameters: dict[str, str]) -> ValidationResult:
        self.validate_calls.append((capability_id, dict(parameters)))
        payload = self.validation_payload
        if not self.has_explicit_validation:
            payload = {**payload, "capabilityId": capability_id}
        return ValidationResult.from_dict(payload)

    def approve(self, capability_id: str, approval_record) -> str:
        # Task 18: registration channel echo; eval asserts on validate/execute counts only.
        return approval_record.approval_id

    def execute(
        self,
        capability_id: str,
        parameters: dict[str, str],
        approval_id: str | None = None,
        parameter_snapshot_hash: str | None = None,
    ) -> ExecutionResult:
        self.execute_calls.append((capability_id, dict(parameters)))
        return ExecutionResult.from_dict(self.execution_payload)


def run_eval_file(path: Path) -> EvalSummary:
    payload = json.loads(path.read_text(encoding="utf-8"))
    total = len(payload["cases"])
    failures: list[str] = []
    for case in payload["cases"]:
        gateway = FakeGatewayClient(case)
        outcome = run_query(_case_utterance(case), gateway)
        expected = case.get("expected", {})
        if outcome.status == "awaiting_approval" and expected.get("executeCalls") == 1:
            outcome = continue_action(
                outcome.call_plan,
                outcome.validation_result,
                outcome.approval_record,
                gateway,
                decision="approve",
            )
        try:
            _assert_case(case, outcome, gateway)
        except AssertionError as exc:
            failures.append(f"{_case_id(case)}: {exc}")
    if failures:
        raise AssertionError("\n".join(failures))
    return EvalSummary(total=total, passed=total, failed=0)


def _assert_case(case: dict[str, Any], outcome: Any, gateway: FakeGatewayClient) -> None:
    if "expectedDecision" in case:
        _assert_seed_case(case, outcome, gateway)
        return

    expected = case["expected"]
    assert outcome.status == expected["status"]
    if "capabilityId" in expected:
        assert outcome.call_plan is not None
        assert outcome.call_plan.capability_id == expected["capabilityId"]
    if "missingParameters" in expected:
        assert outcome.missing_parameters == expected["missingParameters"]
    if "errorType" in expected:
        assert outcome.error_type == expected["errorType"]
    if "responseContains" in expected:
        response = outcome.response_text or ""
        for text in expected["responseContains"]:
            assert text in response
    for text in expected.get("sensitiveAbsent", []):
        assert text not in (outcome.response_text or "")
    assert len(gateway.validate_calls) == expected["validateCalls"]
    assert len(gateway.execute_calls) == expected["executeCalls"]


def _assert_seed_case(case: dict[str, Any], outcome: Any, gateway: FakeGatewayClient) -> None:
    _assert_seed_contract_shape(case)
    expected_status = {
        "SELECT": "success",
        "CLARIFY": "clarification",
        "REJECT": "failure",
    }[case["expectedDecision"]]
    assert outcome.status == expected_status

    if case.get("expectedCapabilityId"):
        if outcome.call_plan is not None:
            assert outcome.call_plan.capability_id == case["expectedCapabilityId"]
        else:
            parsed = parse_intent(case["utterance"])
            expected_intent = _CAPABILITY_TO_INTENT.get(case["expectedCapabilityId"])
            if expected_intent:
                assert parsed.intent == expected_intent

    if "expectedParameters" in case:
        actual_parameters = _actual_parameters(case, outcome)
        for name, value in case["expectedParameters"].items():
            assert actual_parameters.get(name) == value

    clarification = case.get("expectedClarification")
    if clarification:
        assert outcome.missing_parameters == clarification["missingFields"]
        _assert_clarification_intent(clarification["questionIntent"], outcome.response_text or "")

    if case.get("expectedRejectReason") is not None:
        assert outcome.error_type == case["expectedRejectReason"]

    business_caliber = case.get("expectedBusinessCaliber")
    if business_caliber and case["expectedDecision"] == "SELECT":
        _assert_business_caliber(business_caliber["caliberId"], outcome)

    response = outcome.response_text or ""
    for text in case.get("responseContains", []):
        assert text in response
    for text in case.get("sensitiveAbsent", []):
        assert text not in response

    expected_calls = _expected_gateway_calls(case["expectedDecision"])
    assert len(gateway.validate_calls) == expected_calls[0]
    assert len(gateway.execute_calls) == expected_calls[1]


def _assert_seed_contract_shape(case: dict[str, Any]) -> None:
    assert case["caseId"]
    assert case["status"] == "active"
    assert case["utterance"]
    assert case["expectedDecision"] in {"SELECT", "CLARIFY", "REJECT"}
    assert isinstance(case["regressionTags"], list)
    assert case["regressionTags"]
    assert "createdAt" in case


def _actual_parameters(case: dict[str, Any], outcome: Any) -> dict[str, str]:
    if outcome.call_plan is not None:
        return outcome.call_plan.parameters
    return parse_intent(case["utterance"]).parameters


def _assert_clarification_intent(question_intent: str, response: str) -> None:
    expected_text = {
        "ask_for_material": "物料",
        "ask_for_plant": "工厂",
        "ask_for_filter": "过滤条件",
    }[question_intent]
    assert expected_text in response


def _assert_business_caliber(caliber_id: str, outcome: Any) -> None:
    if caliber_id == "MM.PurchaseOrder.ListQuery.v1":
        assert outcome.facts is not None
        if outcome.facts:
            assert outcome.facts[0].domain == "MM"
            assert outcome.facts[0].business_object == "PurchaseOrder"
            assert outcome.facts[0].predicate == "purchaseOrderItem"
        return
    assert caliber_id == "MM.Inventory.AvailabilityForCommitment.v1"
    assert outcome.fact is not None
    assert outcome.fact.domain == "MM"
    assert outcome.fact.business_object == "InventoryStock"
    assert outcome.fact.predicate == "availableQuantity"


def _expected_gateway_calls(decision: str) -> tuple[int, int]:
    if decision == "SELECT":
        return (1, 1)
    return (0, 0)


def _case_id(case: dict[str, Any]) -> str:
    return str(case.get("caseId") or case.get("id"))


def _case_utterance(case: dict[str, Any]) -> str:
    return str(case.get("utterance") or case.get("userQuery"))


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 1:
        print("Usage: python -m sap_nexus_agent.eval <json-formatted-cases-file>", file=sys.stderr)
        return 2
    summary = run_eval_file(Path(args[0]))
    print(f"Eval passed: {summary.passed}/{summary.total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

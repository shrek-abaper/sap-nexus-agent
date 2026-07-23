from __future__ import annotations

from typing import Callable

from sap_nexus_agent.execution_result import ExecutionResult, ValidationResult
from sap_nexus_agent.gateway_client import GatewayClientProtocol
from sap_nexus_agent.intent import IntentParseResult
from sap_nexus_agent.llm_intent import build_intent_adapter
from sap_nexus_agent.orchestrator import AgentOutcome, run_inventory_query


IntentAdapter = Callable[[str], IntentParseResult]


def run_workbench_query(
    text: str,
    gateway: GatewayClientProtocol,
    *,
    intent_mode: str = "hybrid",
    intent_adapter: IntentAdapter | None = None,
) -> dict[str, object]:
    adapter = intent_adapter or build_intent_adapter(intent_mode)
    return outcome_to_workbench_dict(run_inventory_query(text, gateway, intent_adapter=adapter))


def outcome_to_workbench_dict(outcome: AgentOutcome) -> dict[str, object]:
    return {
        "status": outcome.status,
        "message": outcome.message,
        "responseText": outcome.response_text,
        "callPlan": outcome.call_plan.to_dict() if outcome.call_plan else None,
        "validationResult": _validation_to_dict(outcome.validation_result),
        "executionResult": _execution_to_dict(outcome.execution_result),
        "fact": outcome.fact.to_dict() if outcome.fact else None,
        "facts": [f.to_dict() for f in outcome.facts] if outcome.facts else None,
        "gatewayTraceId": outcome.gateway_trace_id,
        "errorType": outcome.error_type,
        "missingParameters": list(outcome.missing_parameters or []),
        "approvalRecord": outcome.approval_record.to_dict() if outcome.approval_record else None,
    }


def _validation_to_dict(result: ValidationResult | None) -> dict[str, object] | None:
    if result is None:
        return None
    return {
        "traceId": result.trace_id,
        "capabilityId": result.capability_id,
        "success": result.success,
        "errorType": result.error_type,
        "messages": list(result.messages),
    }


def _execution_to_dict(result: ExecutionResult | None) -> dict[str, object] | None:
    if result is None:
        return None
    return {
        "traceId": result.trace_id,
        "capabilityId": result.capability_id,
        "success": result.success,
        "executor": dict(result.executor),
        "returnMessages": list(result.return_messages),
        "data": dict(result.data),
        "durationMs": result.duration_ms,
        "errorType": result.error_type,
    }

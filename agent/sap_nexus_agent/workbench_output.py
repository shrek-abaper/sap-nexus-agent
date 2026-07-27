from __future__ import annotations

from typing import Callable

from sap_nexus_agent.conversation_context import ConversationContext, LastContext
from sap_nexus_agent.execution_result import ExecutionResult, ValidationResult
from sap_nexus_agent.gateway_client import GatewayClientProtocol
from sap_nexus_agent.intent import IntentParseResult
from sap_nexus_agent.llm_intent import build_intent_adapter
from sap_nexus_agent.match_decision import EscalationHandoff, MatchDecision, MatchedIntent
from sap_nexus_agent.orchestrator import AgentOutcome, run_inventory_query


IntentAdapter = Callable[[str, "ConversationContext | None"], IntentParseResult]


def run_workbench_query(
    text: str,
    gateway: GatewayClientProtocol,
    *,
    intent_mode: str = "hybrid",
    intent_adapter: IntentAdapter | None = None,
    context: ConversationContext | None = None,
) -> dict[str, object]:
    adapter = intent_adapter or build_intent_adapter(intent_mode)
    return outcome_to_workbench_dict(
        run_inventory_query(text, gateway, intent_adapter=adapter, context=context)
    )


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
        # Advisory field for the frontend SSE layer (Task 6.1 emits
        # match_decision_created for SHOW_OPTIONS / ESCALATE_TO_PLANNER).
        # SELECT/CLARIFY/REJECT reuse existing event paths but still carry the
        # decision here for uniform rendering.
        "matchDecision": _match_decision_to_dict(outcome.match_decision),
        # S2-B dry-run result (Task 9). Populated only for ESCALATE_TO_PLANNER
        # outcomes; the orchestrator wires the handoff into the PlanCompiler
        # (deterministic, no Gateway/SAP). The frontend folds this into the
        # match-decision artifact payload so the Workbench can render the
        # dry-run preview (PlanGraph nodes/edges/gaps/governanceFlags) in the
        # same ESCALATE turn.
        "dryRun": _dry_run_to_dict(outcome.dry_run),
        # Conversational context (Task 5): LastContext for the next turn,
        # derived from the outcome's match_decision. The backend records this
        # on the session so the next utterance can continue slot-fill (CLARIFY)
        # or follow up (SELECT). None clears the session (REJECT / SHOW_OPTIONS
        # / ESCALATE / awaiting_approval).
        "lastContext": _last_context_from_outcome(outcome),
    }


def _last_context_from_outcome(outcome: AgentOutcome) -> dict[str, object] | None:
    """Derive LastContext for the next turn from the outcome's match_decision.

    CLARIFY -> LastContext(CLARIFY, params, missing) for slot-fill.
    SELECT success -> LastContext(SELECT, params, []) for Q1 follow-up.
    REJECT / SHOW_OPTIONS / ESCALATE / awaiting_approval / awaiting_batch_confirm
    -> None (clear session).
    """
    if outcome.status == "awaiting_approval":
        return None  # Q2: approval pending rejects new queries, no last_context.
    if outcome.status == "awaiting_batch_confirm":
        # Batch pending: clear session so the LLM does not re-emit
        # multi_parameters from the prior SELECT's material on the user's
        # "确认" reply (caused a dead loop: awaiting_batch_confirm -> "确认"
        # -> re-emit multi_parameters -> awaiting_batch_confirm).
        return None
    decision = outcome.match_decision
    if decision is None:
        return None
    if decision.decision_type == "CLARIFY":
        ctx = LastContext(
            capability_id=decision.capability_id,
            parameters=dict(decision.parameters or {}),
            missing_parameters=list(decision.missing_parameters or []),
            decision_type="CLARIFY",
        )
        return ctx.to_dict()
    # Q1 follow-up: retain lastContext even when execute fails (e.g. SAP
    # RETURN type E) so the user can sticky-retry or swap params. The
    # decision (capability_id + parameters) is settled before execute.
    if decision.decision_type == "SELECT":
        ctx = LastContext(
            capability_id=decision.capability_id,
            parameters=dict(decision.parameters or {}),
            missing_parameters=[],
            decision_type="SELECT",
        )
        return ctx.to_dict()
    return None


def _dry_run_to_dict(dry_run) -> dict[str, object] | None:
    if dry_run is None:
        return None
    return {
        "planGraph": dry_run.plan_graph,
        "gaps": [
            {"kind": gap.kind, "detail": gap.detail} for gap in dry_run.gaps
        ],
        "governanceFlags": [
            {"kind": flag.kind, "detail": flag.detail}
            for flag in dry_run.governance_flags
        ],
        "rationale": dry_run.rationale,
    }


def _match_decision_to_dict(decision: MatchDecision | None) -> dict[str, object] | None:
    if decision is None:
        return None
    return {
        "decisionType": decision.decision_type,
        "capabilityId": decision.capability_id,
        "parameters": dict(decision.parameters) if decision.parameters else None,
        "missingParameters": list(decision.missing_parameters) if decision.missing_parameters else None,
        "errorType": decision.error_type,
        "candidates": (
            [_matched_intent_to_dict(c) for c in decision.candidates]
            if decision.candidates
            else None
        ),
        "handoff": _handoff_to_dict(decision.handoff) if decision.handoff else None,
        "rationale": decision.rationale,
    }


def _matched_intent_to_dict(intent: MatchedIntent) -> dict[str, object]:
    return {
        "capabilityId": intent.capability_id,
        "parameters": dict(intent.parameters),
        "missing": list(intent.missing),
    }


def _handoff_to_dict(handoff: EscalationHandoff) -> dict[str, object]:
    return {
        "reason": handoff.reason,
        "matchedIntents": [_matched_intent_to_dict(mi) for mi in handoff.matched_intents],
        "utterance": handoff.utterance,
        "registrySnapshotId": handoff.registry_snapshot_id,
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

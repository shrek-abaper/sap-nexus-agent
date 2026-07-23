from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from sap_nexus_agent.action_result import ActionResult
from sap_nexus_agent.approval import (
    ApprovalRecord,
    ApprovalState,
    approve,
    compute_parameter_hash,
    create_approval_record,
    mark_executed,
    reject,
)
from sap_nexus_agent.call_plan import CallPlan, create_call_plan
from sap_nexus_agent.capability_selector import select_capability
from sap_nexus_agent.execution_result import ExecutionResult
from sap_nexus_agent.execution_result import ValidationResult
from sap_nexus_agent.gateway_client import GatewayClientProtocol
from sap_nexus_agent.intent import IntentParseResult, parse_intent, parse_inventory_intent
from sap_nexus_agent.narrator import (
    NarrativeGuardError,
    narrate_fact,
    narrate_failure,
    narrate_purchase_order_facts,
)
from sap_nexus_agent.reasoning_fact import (
    ReasoningFact,
    build_availability_fact,
    build_purchase_order_facts,
)


INVENTORY_CAPABILITY_ID = "MM.Inventory.GetAvailability"
PR_CREATE_CAPABILITY_ID = "MM.PR.CreateDraft"
# Action capabilities require human approval before Gateway execute.
ACTION_CAPABILITY_IDS = frozenset({PR_CREATE_CAPABILITY_ID})


@dataclass(frozen=True)
class AgentOutcome:
    status: str
    message: str | None = None
    response_text: str | None = None
    call_plan: CallPlan | None = None
    validation_result: ValidationResult | None = None
    execution_result: ExecutionResult | None = None
    fact: ReasoningFact | None = None
    facts: list[ReasoningFact] | None = None
    gateway_trace_id: str | None = None
    error_type: str | None = None
    missing_parameters: list[str] | None = None
    approval_record: ApprovalRecord | None = None


IntentAdapter = Callable[[str], IntentParseResult]


def run_query(
    text: str,
    gateway: GatewayClientProtocol,
    *,
    intent_adapter: IntentAdapter = parse_intent,
) -> AgentOutcome:
    """Unified entry: parse_intent -> select_capability -> route by capabilityId.

    The Agent never senses the executor type (JCO_RFC / ODATA); routing is
    purely on the registered capabilityId closed set.
    """
    parsed = intent_adapter(text)
    selected = select_capability(parsed)

    if selected.error_type == "UNSUPPORTED_RFC_NAME":
        return AgentOutcome(
            status="failure",
            message=selected.message,
            response_text=selected.message,
            error_type=selected.error_type,
        )
    if parsed.missing_parameters:
        return AgentOutcome(
            status="clarification",
            message=parsed.clarification,
            response_text=parsed.clarification,
            missing_parameters=parsed.missing_parameters,
        )
    if selected.capability_id is None:
        return AgentOutcome(
            status="failure",
            message=selected.message,
            response_text=selected.message,
            error_type=selected.error_type,
        )

    parameters = dict(parsed.parameters)
    if selected.capability_id == INVENTORY_CAPABILITY_ID:
        parameters.setdefault("unit", "EA")

    kind = "Action" if selected.capability_id in ACTION_CAPABILITY_IDS else "Function"
    call_plan = create_call_plan(selected.capability_id, parameters, kind=kind)
    validation = gateway.validate(call_plan.capability_id, call_plan.parameters)
    if not validation.success:
        return AgentOutcome(
            status="failure",
            message="；".join(validation.messages),
            response_text=narrate_failure(validation.error_type, validation.messages),
            call_plan=call_plan,
            validation_result=validation,
            gateway_trace_id=validation.trace_id,
            error_type=validation.error_type,
        )

    is_action = call_plan.kind == "Action"
    if is_action:
        pending = create_approval_record(
            capability_id=call_plan.capability_id,
            parameters=call_plan.parameters,
            approver="user",
        )
        return AgentOutcome(
            status="awaiting_approval",
            message="采购申请参数已就绪，等待人工审批。",
            response_text="请确认采购申请参数后批准或拒绝。",
            call_plan=call_plan,
            validation_result=validation,
            gateway_trace_id=validation.trace_id,
            approval_record=pending,
        )
    execution = gateway.execute(call_plan.capability_id, call_plan.parameters)
    if not execution.success:
        messages = [_message_text(message) for message in execution.return_messages]
        return AgentOutcome(
            status="failure",
            message="Gateway execute failed",
            response_text=narrate_failure(execution.error_type, messages),
            call_plan=call_plan,
            validation_result=validation,
            execution_result=execution,
            gateway_trace_id=execution.trace_id,
            error_type=execution.error_type,
        )

    if selected.capability_id == INVENTORY_CAPABILITY_ID:
        return _finalize_inventory(call_plan, validation, execution)
    return _finalize_purchase_order(call_plan, validation, execution)


def run_inventory_query(
    text: str,
    gateway: GatewayClientProtocol,
    *,
    intent_adapter: IntentAdapter = parse_inventory_intent,
) -> AgentOutcome:
    """Backward-compatible inventory-only entry (delegates to run_query)."""
    return run_query(text, gateway, intent_adapter=intent_adapter)


def continue_action(
    call_plan: CallPlan,
    validation: ValidationResult,
    approval_record: ApprovalRecord,
    gateway: GatewayClientProtocol,
    *,
    decision: str,
) -> AgentOutcome:
    """Continue an Action only after an external approve/reject decision."""
    if call_plan.kind != "Action" or approval_record.status is not ApprovalState.pending:
        return _approval_failure(
            call_plan,
            validation,
            approval_record,
            "APPROVAL_REQUIRED",
            "审批记录不是可执行的 pending Action。",
        )
    if not validation.success:
        return _approval_failure(
            call_plan,
            validation,
            approval_record,
            "APPROVAL_REQUIRED",
            "原参数校验未成功，禁止继续执行审批。",
        )
    if validation.capability_id != call_plan.capability_id:
        return _approval_failure(
            call_plan,
            validation,
            approval_record,
            "APPROVAL_VERSION_MISMATCH",
            "参数校验 capability 与 CallPlan 不一致。",
        )
    if call_plan.capability_id != approval_record.capability_id:
        return _approval_failure(
            call_plan,
            validation,
            approval_record,
            "APPROVAL_VERSION_MISMATCH",
            "审批 capability 与 CallPlan 不一致。",
        )
    if (
        call_plan.parameters != approval_record.parameters
        or compute_parameter_hash(call_plan.parameters) != approval_record.parameter_snapshot_hash
        or compute_parameter_hash(approval_record.parameters) != approval_record.parameter_snapshot_hash
    ):
        return _approval_failure(
            call_plan,
            validation,
            approval_record,
            "APPROVAL_VERSION_MISMATCH",
            "审批参数快照与 CallPlan 不一致。",
        )
    if decision == "reject":
        rejected = reject(approval_record)
        return AgentOutcome(
            status="rejected",
            message="用户已拒绝采购申请。",
            response_text="采购申请已拒绝，未执行 SAP 写入。",
            call_plan=call_plan,
            validation_result=validation,
            gateway_trace_id=validation.trace_id,
            approval_record=rejected,
        )
    if decision != "approve":
        return _approval_failure(
            call_plan,
            validation,
            approval_record,
            "INVALID_APPROVAL_DECISION",
            "审批决策只能是 approve 或 reject。",
        )

    approved = approve(approval_record)
    gateway.approve(call_plan.capability_id, approved)
    execution = gateway.execute(
        call_plan.capability_id,
        call_plan.parameters,
        approval_id=approved.approval_id,
        parameter_snapshot_hash=approved.parameter_snapshot_hash,
    )
    if not execution.success:
        messages = [_message_text(message) for message in execution.return_messages]
        return AgentOutcome(
            status="failure",
            message="Gateway execute failed",
            response_text=narrate_failure(execution.error_type, messages),
            call_plan=call_plan,
            validation_result=validation,
            execution_result=execution,
            gateway_trace_id=execution.trace_id,
            error_type=execution.error_type,
            approval_record=approved,
        )

    executed = mark_executed(approved)
    return _finalize_pr_create(
        call_plan,
        validation,
        execution,
        approval_record=executed,
    )


def _approval_failure(
    call_plan: CallPlan,
    validation: ValidationResult,
    approval_record: ApprovalRecord,
    error_type: str,
    message: str,
) -> AgentOutcome:
    return AgentOutcome(
        status="failure",
        message=message,
        response_text=message,
        call_plan=call_plan,
        validation_result=validation,
        gateway_trace_id=validation.trace_id,
        error_type=error_type,
        approval_record=approval_record,
    )


def _finalize_pr_create(
    call_plan: CallPlan,
    validation: ValidationResult,
    execution: ExecutionResult,
    *,
    approval_record: ApprovalRecord | None = None,
) -> AgentOutcome:
    pr_number = execution.data.get("prNumber", "")
    response_text = (
        f"采购申请创建成功，PR 号：{pr_number}"
        if pr_number
        else "采购请求创建成功但未返回 PR 号。"
    )
    return AgentOutcome(
        status="success",
        response_text=response_text,
        call_plan=call_plan,
        validation_result=validation,
        execution_result=execution,
        gateway_trace_id=execution.trace_id,
        approval_record=approval_record,
    )


def _finalize_inventory(
    call_plan: CallPlan,
    validation: ValidationResult,
    execution: ExecutionResult,
) -> AgentOutcome:
    fact = build_availability_fact(call_plan.agent_trace_id, execution, call_plan.parameters)
    if fact is None:
        return AgentOutcome(
            status="failure",
            message="缺少可叙事的库存事实。",
            response_text="缺少可叙事的库存事实，无法生成库存结论。",
            call_plan=call_plan,
            validation_result=validation,
            execution_result=execution,
            gateway_trace_id=execution.trace_id,
            error_type="NARRATIVE_GUARD_ERROR",
        )
    try:
        response_text = narrate_fact(fact, capability_id="MM.Inventory.GetAvailability")
    except NarrativeGuardError as exc:
        return AgentOutcome(
            status="failure",
            message=str(exc),
            response_text="缺少可叙事的库存事实，无法生成库存结论。",
            call_plan=call_plan,
            validation_result=validation,
            execution_result=execution,
            fact=fact,
            gateway_trace_id=execution.trace_id,
            error_type="NARRATIVE_GUARD_ERROR",
        )
    return AgentOutcome(
        status="success",
        response_text=response_text,
        call_plan=call_plan,
        validation_result=validation,
        execution_result=execution,
        fact=fact,
        gateway_trace_id=execution.trace_id,
    )


def _finalize_purchase_order(
    call_plan: CallPlan,
    validation: ValidationResult,
    execution: ExecutionResult,
) -> AgentOutcome:
    facts = build_purchase_order_facts(call_plan.agent_trace_id, execution, call_plan.parameters)
    total_count = execution.data.get("totalCount")
    try:
        response_text = narrate_purchase_order_facts(facts, total_count=total_count)
    except NarrativeGuardError as exc:
        return AgentOutcome(
            status="failure",
            message=str(exc),
            response_text="采购订单事实缺少必要字段，无法生成结论。",
            call_plan=call_plan,
            validation_result=validation,
            execution_result=execution,
            facts=facts,
            gateway_trace_id=execution.trace_id,
            error_type="NARRATIVE_GUARD_ERROR",
        )
    return AgentOutcome(
        status="success",
        response_text=response_text,
        call_plan=call_plan,
        validation_result=validation,
        execution_result=execution,
        facts=facts,
        gateway_trace_id=execution.trace_id,
    )


def _message_text(message: object) -> str:
    if isinstance(message, dict):
        return str(message.get("message") or message.get("MESSAGE") or message)
    return str(message)

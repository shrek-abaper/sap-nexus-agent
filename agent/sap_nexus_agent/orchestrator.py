from __future__ import annotations

import itertools
from dataclasses import dataclass
from pathlib import Path
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
from sap_nexus_agent.conversation_context import ConversationContext
from sap_nexus_agent.execution_result import ExecutionResult
from sap_nexus_agent.execution_result import ValidationResult
from sap_nexus_agent.gateway_client import GatewayClientProtocol
from sap_nexus_agent.intent import IntentParseResult, parse_intent, parse_inventory_intent
from sap_nexus_agent.match_decision import MatchDecision
from sap_nexus_agent.narrator import (
    NarrativeGuardError,
    narrate_fact,
    narrate_failure,
    narrate_purchase_order_facts,
)
from sap_nexus_agent.planner.handoff import compile_dry_run_from_handoff
from sap_nexus_agent.planner.plan_compiler import DryRunResult
from sap_nexus_agent.reasoning_fact import (
    ReasoningFact,
    build_availability_fact,
    build_purchase_order_facts,
)
from sap_nexus_agent.semantic_planning import (
    RegistrySnapshot,
    SemanticSourceDocuments,
    build_registry_snapshot,
    load_semantic_sources,
)


INVENTORY_CAPABILITY_ID = "MM.Inventory.GetAvailability"
PR_CREATE_CAPABILITY_ID = "MM.PR.CreateDraft"
# Action capabilities require human approval before Gateway execute.
ACTION_CAPABILITY_IDS = frozenset({PR_CREATE_CAPABILITY_ID})
# Soft cap for multi-value combination expansion (Design Doc §4.4). Exceeding
# this emits CLARIFY instead of awaiting_batch_confirm.
BATCH_COMBINATION_CAP = 20


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
    # Five-state MatchDecision (S2-A). Populated for every run_query path so
    # the workbench / SSE layer can surface SELECT/CLARIFY/REJECT/SHOW_OPTIONS
    # /ESCALATE_TO_PLANNER uniformly. None only for continue_action outcomes
    # (approval continue flow) which do not re-run the selector.
    match_decision: MatchDecision | None = None
    # S2-B dry-run result (Task 9). Populated only for ESCALATE_TO_PLANNER
    # outcomes - the orchestrator wires the handoff into the PlanCompiler
    # (deterministic, no Gateway/SAP). None for every other path.
    dry_run: DryRunResult | None = None
    # Multi-value batch (Design Doc §4.4): combinations awaiting user confirm.
    # Populated only for status="awaiting_batch_confirm".
    combinations: list[dict[str, str]] | None = None


IntentAdapter = Callable[[str, "ConversationContext | None"], IntentParseResult]
PlannerSourcesLoader = Callable[[], tuple[RegistrySnapshot, SemanticSourceDocuments]]


def expand_combinations(
    base: dict[str, str],
    multi: dict[str, list[str]],
) -> list[dict[str, str]]:
    """Cartesian product of multi-valued parameters over a base dict.

    Generic over parameter names (Design Doc §4.4). Single key -> N combos;
    multi key -> Cartesian product. Empty ``multi`` -> single ``base`` combo.
    """
    if not multi:
        return [dict(base)]
    keys = list(multi.keys())
    value_lists = [multi[k] for k in keys]
    combos: list[dict[str, str]] = []
    for values in itertools.product(*value_lists):
        combo = dict(base)
        combo.update(dict(zip(keys, values)))
        combos.append(combo)
    return combos


def run_query(
    text: str,
    gateway: GatewayClientProtocol,
    *,
    intent_adapter: IntentAdapter = parse_intent,
    context: ConversationContext | None = None,
    snapshot: RegistrySnapshot | None = None,
    sources: SemanticSourceDocuments | None = None,
    planner_sources_loader: PlannerSourcesLoader | None = None,
) -> AgentOutcome:
    """Unified entry: parse_intent -> select_capability -> route by decision_type.

    The Agent never senses the executor type (JCO_RFC / ODATA); routing is
    purely on the registered capabilityId closed set. Non-SELECT decisions
    (CLARIFY / REJECT / SHOW_OPTIONS / ESCALATE_TO_PLANNER) return without
    touching the Gateway; only SELECT proceeds to CallPlan -> validate/execute.

    For ESCALATE_TO_PLANNER, the orchestrator wires the handoff into the
    S2-B PlanCompiler (``planner.handoff.compile_dry_run_from_handoff``)
    to produce a deterministic ``DryRunResult`` attached to the outcome.
    The PlanCompiler does not call the Gateway or SAP. ``snapshot`` /
    ``sources`` may be injected by tests; if absent, the orchestrator
    loads them from the registry via path discovery (or the injected
    ``planner_sources_loader``).

    Task 2: ``context`` is forwarded to ``intent_adapter``. When ``None``
    (default) the call is identical to the single-turn path (backward
    compatible): the adapter is invoked with just ``text`` so existing
    single-arg adapters (e.g. test stubs) keep working unchanged. When
    non-``None``, ``context`` is passed through. Sticky-CLARIFY continuation
    (Task 3) and history injection (Task 4) consume the same parameter
    downstream.
    """
    # Backward-compat dispatch: when context is None, call the adapter with
    # the original single-arg signature so existing 1-arg adapters (and the
    # default ``parse_intent``) are byte-for-byte unchanged. Only forward
    # ``context`` when it is actually provided.
    if context is None:
        parsed = intent_adapter(text)
    else:
        parsed = intent_adapter(text, context)
    decision = select_capability(parsed)

    # REJECT (technical override / unsupported intent): no Gateway.
    if decision.decision_type == "REJECT":
        return AgentOutcome(
            status="failure",
            message=decision.rationale,
            response_text=decision.rationale,
            error_type=decision.error_type,
            match_decision=decision,
        )

    # CLARIFY (single intent missing required params): no Gateway.
    if decision.decision_type == "CLARIFY":
        return AgentOutcome(
            status="clarification",
            message=decision.rationale,
            response_text=decision.rationale,
            missing_parameters=decision.missing_parameters,
            match_decision=decision,
        )

    # SHOW_OPTIONS / ESCALATE_TO_PLANNER: handoff to workbench/planner, no Gateway.
    if decision.decision_type in ("SHOW_OPTIONS", "ESCALATE_TO_PLANNER"):
        dry_run = None
        if decision.decision_type == "ESCALATE_TO_PLANNER" and decision.handoff is not None:
            dry_run = _compile_dry_run_safely(
                decision.handoff,
                snapshot=snapshot,
                sources=sources,
                planner_sources_loader=planner_sources_loader,
            )
        return AgentOutcome(
            status="match_decision",
            message=decision.rationale,
            response_text=decision.rationale,
            match_decision=decision,
            dry_run=dry_run,
        )

    # SELECT -> CallPlan -> Gateway validate/execute (existing path).
    capability_id = decision.capability_id
    parameters = dict(decision.parameters or parsed.parameters)
    if capability_id == INVENTORY_CAPABILITY_ID:
        parameters.setdefault("unit", "EA")

    # Multi-value detection (Design Doc §4.4): expand combinations and await
    # user confirmation before any Gateway call.
    if parsed.multi_parameters:
        combinations = expand_combinations(parameters, parsed.multi_parameters)
        if len(combinations) > BATCH_COMBINATION_CAP:
            return AgentOutcome(
                status="clarification",
                response_text=f"组合数 {len(combinations)} 过多，请缩小范围（如减少物料或工厂）。",
                match_decision=decision,
            )
        kind = "Action" if capability_id in ACTION_CAPABILITY_IDS else "Function"
        call_plan = create_call_plan(capability_id, parameters, kind=kind)
        combos_desc = "; ".join(
            f"material={c.get('material')}, plant={c.get('plant')}" for c in combinations
        )
        return AgentOutcome(
            status="awaiting_batch_confirm",
            response_text=f"将查询 {len(combinations)} 个组合：{combos_desc}，请确认。",
            call_plan=call_plan,
            combinations=combinations,
            match_decision=decision,
        )

    kind = "Action" if capability_id in ACTION_CAPABILITY_IDS else "Function"
    call_plan = create_call_plan(capability_id, parameters, kind=kind)
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
            match_decision=decision,
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
            match_decision=decision,
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
            match_decision=decision,
        )

    if capability_id == INVENTORY_CAPABILITY_ID:
        return _finalize_inventory(call_plan, validation, execution, decision=decision)
    return _finalize_purchase_order(call_plan, validation, execution, decision=decision)


def run_inventory_query(
    text: str,
    gateway: GatewayClientProtocol,
    *,
    intent_adapter: IntentAdapter = parse_inventory_intent,
    context: ConversationContext | None = None,
) -> AgentOutcome:
    """Backward-compatible inventory-only entry (delegates to run_query).

    Task 2: ``context`` is forwarded to ``run_query`` -> ``intent_adapter``.
    """
    return run_query(text, gateway, intent_adapter=intent_adapter, context=context)


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
    *,
    decision: MatchDecision | None = None,
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
            match_decision=decision,
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
            match_decision=decision,
        )
    return AgentOutcome(
        status="success",
        response_text=response_text,
        call_plan=call_plan,
        validation_result=validation,
        execution_result=execution,
        fact=fact,
        gateway_trace_id=execution.trace_id,
        match_decision=decision,
    )


def _finalize_purchase_order(
    call_plan: CallPlan,
    validation: ValidationResult,
    execution: ExecutionResult,
    *,
    decision: MatchDecision | None = None,
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
            match_decision=decision,
        )
    return AgentOutcome(
        status="success",
        response_text=response_text,
        call_plan=call_plan,
        validation_result=validation,
        execution_result=execution,
        facts=facts,
        gateway_trace_id=execution.trace_id,
        match_decision=decision,
    )


def _message_text(message: object) -> str:
    if isinstance(message, dict):
        return str(message.get("message") or message.get("MESSAGE") or message)
    return str(message)


# ---------------------------------------------------------------------------
# S2-B handoff wiring helpers (Task 9)
# ---------------------------------------------------------------------------


def _compile_dry_run_safely(
    handoff,
    *,
    snapshot: RegistrySnapshot | None,
    sources: SemanticSourceDocuments | None,
    planner_sources_loader: PlannerSourcesLoader | None,
) -> DryRunResult | None:
    """Compile a dry-run from the handoff, loading sources if not injected.

    Swallows source-loading errors so an ESCALATE decision never crashes
    the orchestrator: if the registry cannot be loaded, ``dry_run`` is
    ``None`` and the match_decision still surfaces to the workbench. The
    PlanCompiler itself is deterministic and does not call the Gateway.
    """
    try:
        if snapshot is None or sources is None:
            loader = planner_sources_loader or _default_planner_sources
            snapshot, sources = loader()
        return compile_dry_run_from_handoff(handoff, snapshot, sources)
    except Exception:
        # Source-loading failure (registry missing, YAML malformed, etc.).
        # The match_decision still surfaces; the dry-run is omitted.
        return None


def _default_planner_sources() -> tuple[RegistrySnapshot, SemanticSourceDocuments]:
    """Load registry snapshot + sources via path discovery.

    Mirrors ``registry_loader._resolve_registry_path``: walks up from the
    ``sap_nexus_agent`` package location looking for ``registry/``.
    """
    here = Path(__file__).resolve().parent
    repo_root: Path | None = None
    for parent in [here, *here.parents]:
        if (parent / "registry" / "capabilities.yaml").exists():
            repo_root = parent
            break
    if repo_root is None:
        # Last-resort cwd fallback; ``load_semantic_sources`` will raise
        # ``SourceLoadError`` if the files are missing, which the caller
        # swallows in ``_compile_dry_run_safely``.
        repo_root = Path.cwd()
    sources = load_semantic_sources(repo_root)
    snapshot = build_registry_snapshot(sources)
    return snapshot, sources

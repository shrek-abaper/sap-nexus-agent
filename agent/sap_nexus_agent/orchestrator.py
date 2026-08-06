from __future__ import annotations

import itertools
import hashlib
import json
import os
import re
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Callable, Mapping

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
from sap_nexus_agent.conversation_context import (
    ConversationContext,
    ReadExecutionBinding,
    SelectionExecutionBinding,
)
from sap_nexus_agent.execution_result import ExecutionResult
from sap_nexus_agent.execution_result import ValidationResult
from sap_nexus_agent.gateway_client import GatewayClientProtocol
from sap_nexus_agent.intent import IntentParseResult, parse_intent, parse_inventory_intent
from sap_nexus_agent.match_decision import MatchDecision
from sap_nexus_agent.narrator import (
    NarrativeGuardError,
    narrate_fact,
    narrate_failure,
    narrate_inventory_facts,
    narrate_purchase_order_facts,
)
from sap_nexus_agent.planner.handoff import compile_plan_v2_from_handoff
from sap_nexus_agent.planner.plan_compiler_v2 import PlanCompileResult
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
from sap_nexus_agent.governed_context import (
    PLACEHOLDER_PRINCIPAL,
    GovernedContext,
    PlannerFailure,
    SnapshotDriftError,
    SnapshotLease,
    TrustedPrincipal,
    VisibleCapabilitySet,
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
    # outcomes - the orchestrator wires the handoff into the PlanCompiler v2
    # (deterministic, no Gateway/SAP). None for every other path.
    dry_run: PlanCompileResult | None = None
    # Multi-value batch (Design Doc §4.4): combinations awaiting user confirm.
    # Populated only for status="awaiting_batch_confirm".
    combinations: list[dict[str, str]] | None = None
    # Structured planner failure (Design Doc §3.5). Populated when the
    # planner encounters snapshot drift, source load error, or visibility
    # denial. None for all non-ESCALATE paths and successful dry-runs.
    planner_failure: "PlannerFailure | None" = None
    # Runbook 14 cross-turn continuation: the updated ConversationContext
    # for the next turn. Populated when SHOW_OPTIONS / ESCALATE_TO_PLANNER
    # writes advisory pending state (pending_show_options / pending_escalate),
    # and when a non-pending decision clears prior pending state. None when
    # run_query was called without a context (single-turn; no continuation).
    updated_context: "ConversationContext | None" = None
    # Task 4 shadow rollout evidence. This is a redacted comparison only;
    # it never contains a shadow CallPlan, session state, or model payload.
    context_shadow: "ContextShadow | None" = None
    # Authoritative READ two-phase payload. These fields are populated by
    # resolve_read_turn before any Gateway client exists.
    read_state: "ConversationReadState | None" = None
    resolution_report: Mapping[str, object] | None = None
    read_execution_binding: ReadExecutionBinding | None = None
    selection_execution_binding: SelectionExecutionBinding | None = None
    turn_id: str | None = None
    frame_id: str | None = None
    state_version: int | None = None
    registry_snapshot_id: str | None = None


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


def resolve_read_turn(
    text: str,
    *,
    context: ConversationContext,
    intent_adapter: IntentAdapter,
    principal: TrustedPrincipal,
    snapshot: RegistrySnapshot,
    sources: SemanticSourceDocuments,
    turn_id: str,
) -> AgentOutcome:
    """Resolve one READ turn into persisted state and a plan without Gateway IO."""
    lease, governed_context, visible = _governed_read_authority(
        principal, snapshot, sources
    )
    parsed = intent_adapter(text, context)
    from sap_nexus_agent.intent_envelope import IntentEnvelope

    if isinstance(parsed, IntentEnvelope):
        legacy_decision, envelope = _dispatch_envelope(parsed, visible, lease)
    else:
        legacy_decision = select_capability(parsed, visible=visible)
        envelope = None
    outcome = _resolve_authoritative_read(
        text=text,
        context=context,
        parsed=parsed,
        envelope=envelope,
        legacy_decision=legacy_decision,
        principal=principal,
        governed_context=governed_context,
        lease=lease,
        visible=visible,
        turn_id=turn_id,
    )
    if outcome is not None:
        return outcome
    raise RuntimeError("authoritative turn resolver returned no immutable outcome")


def continue_resolved_read(
    call_plan: CallPlan,
    binding: ReadExecutionBinding,
    gateway: GatewayClientProtocol,
    *,
    persisted_state: "ConversationReadState | None" = None,
    principal: TrustedPrincipal | None = None,
    snapshot: RegistrySnapshot | None = None,
    sources: SemanticSourceDocuments | None = None,
) -> AgentOutcome:
    """Execute one immutable, server-owned, CAS-bound READY READ plan."""
    if not preflight_resolved_read(
        call_plan,
        binding,
        persisted_state=persisted_state,
        principal=principal,
        snapshot=snapshot,
        sources=sources,
    ):
        return AgentOutcome(
            status="failure",
            message="Resolved READ execution binding does not match persisted state.",
            response_text="READ 上下文绑定已失效，请重新发起查询。",
            error_type="READ_EXECUTION_BINDING_MISMATCH",
            call_plan=call_plan,
        )

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
    if call_plan.capability_id == INVENTORY_CAPABILITY_ID:
        return _finalize_inventory(call_plan, validation, execution)
    return _finalize_purchase_order(call_plan, validation, execution)


def preflight_resolved_read(
    call_plan: CallPlan,
    binding: ReadExecutionBinding,
    *,
    persisted_state: "ConversationReadState | None",
    principal: TrustedPrincipal | None,
    snapshot: RegistrySnapshot | None,
    sources: SemanticSourceDocuments | None,
) -> bool:
    """Validate all current READ authority before a Gateway can be constructed."""
    return _valid_current_read_authority(
        call_plan,
        binding,
        persisted_state=persisted_state,
        principal=principal,
        snapshot=snapshot,
        sources=sources,
    )


def preflight_resolved_batch(
    call_plan: CallPlan,
    combinations: list[dict[str, str]],
    binding: ReadExecutionBinding,
    *,
    persisted_state: "ConversationReadState | None",
    principal: TrustedPrincipal | None,
    snapshot: RegistrySnapshot | None,
    sources: SemanticSourceDocuments | None,
) -> bool:
    if not preflight_resolved_read(
        call_plan,
        binding,
        persisted_state=persisted_state,
        principal=principal,
        snapshot=snapshot,
        sources=sources,
    ) or not combinations or len(combinations) > BATCH_COMBINATION_CAP or sources is None:
        return False
    capability = _current_capability(sources, call_plan.capability_id)
    inputs = capability.get("inputs") if capability else None
    if not isinstance(inputs, (tuple, list)):
        return False
    descriptors = {
        raw.get("name"): raw for raw in inputs
        if isinstance(raw, Mapping) and isinstance(raw.get("name"), str)
    }
    required = {name for name, raw in descriptors.items() if raw.get("required") is True}
    return len(descriptors) == len(inputs) and all(
        required.issubset(combo)
        and set(combo).issubset(descriptors)
        and all(_valid_semantic_input_value(descriptors[name], value) for name, value in combo.items())
        for combo in combinations
    )


def continue_resolved_selection(
    call_plan: CallPlan,
    binding: SelectionExecutionBinding,
    gateway: GatewayClientProtocol,
    *,
    principal: TrustedPrincipal,
    snapshot: RegistrySnapshot,
    sources: SemanticSourceDocuments,
) -> AgentOutcome:
    """Validate one parsed WRITE selection without rerunning semantic parsing."""
    capability = _current_capability(sources, call_plan.capability_id)
    governance = capability.get("governance") if capability else None
    executor_binding = capability.get("executorBinding") if capability else None
    bound_executor = (
        _current_executor_binding(sources, binding.executor_binding_id)
        if isinstance(binding, SelectionExecutionBinding)
        else None
    )
    if (
        not isinstance(binding, SelectionExecutionBinding)
        or not binding.validates(call_plan)
        or binding.principal_id != principal.principal_id
        or binding.registry_snapshot_id != snapshot.snapshot_id
        or capability is None
        or capability.get("status") != "active"
        or str(capability.get("version", "1")) != binding.capability_version
        or _executor_binding_id(capability) != binding.executor_binding_id
        or not isinstance(executor_binding, Mapping)
        or bound_executor is None
        or bound_executor.get("type") != executor_binding.get("type")
        or not isinstance(governance, Mapping)
        or governance.get("sideEffect") == "none"
        or governance.get("requiresApproval") is not True
    ):
        return AgentOutcome(
            status="failure",
            message="Resolved selection authority is invalid or stale.",
            error_type="SELECTION_EXECUTION_BINDING_MISMATCH",
        )
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
    approval = create_approval_record(
        capability_id=call_plan.capability_id,
        parameters=call_plan.parameters,
        approver="user",
        registry_snapshot_id=snapshot.snapshot_id,
    )
    return AgentOutcome(
        status="awaiting_approval",
        message="采购申请参数已就绪，等待人工审批。",
        response_text="请确认采购申请参数后批准或拒绝。",
        call_plan=call_plan,
        validation_result=validation,
        gateway_trace_id=validation.trace_id,
        approval_record=approval,
    )


def _valid_current_read_authority(
    call_plan: CallPlan,
    binding: ReadExecutionBinding,
    *,
    persisted_state: "ConversationReadState | None",
    principal: TrustedPrincipal | None,
    snapshot: RegistrySnapshot | None,
    sources: SemanticSourceDocuments | None,
) -> bool:
    if (
        not isinstance(binding, ReadExecutionBinding)
        or persisted_state is None
        or principal is None
        or snapshot is None
        or sources is None
        or not binding.validates(call_plan, persisted_state)
        or binding.principal_id != principal.principal_id
        or binding.registry_snapshot_id != snapshot.snapshot_id
    ):
        return False
    from sap_nexus_agent.semantic_planning.validation import build_semantic_contracts

    try:
        contracts = build_semantic_contracts(sources)
    except Exception:
        return False
    if not contracts.report.valid or contracts.snapshot != snapshot:
        return False
    capability = _current_capability(sources, call_plan.capability_id)
    governance = capability.get("governance") if capability else None
    executor_binding = capability.get("executorBinding") if capability else None
    if (
        capability is None
        or capability.get("status") != "active"
        or capability.get("kind") != "Function"
        or str(capability.get("version", "1")) != binding.capability_version
        or not isinstance(governance, Mapping)
        or governance.get("sideEffect") != "none"
        or governance.get("requiresApproval") is not False
        or not isinstance(executor_binding, Mapping)
        or executor_binding.get("bindingId") != binding.executor_binding_id
    ):
        return False
    from sap_nexus_agent.planner.capability_card import discover_cards
    from sap_nexus_agent.visibility import filter_visible

    execution_ids = {
        card.capability_id
        for card in filter_visible(discover_cards(snapshot, sources), for_execution=True)
    }
    if call_plan.capability_id not in execution_ids:
        return False
    raw_bindings = sources.executor_bindings.get("bindings", ())
    matches = [
        raw for raw in raw_bindings
        if isinstance(raw, Mapping) and raw.get("bindingId") == binding.executor_binding_id
    ] if isinstance(raw_bindings, (tuple, list)) else []
    if len(matches) != 1 or matches[0].get("type") != executor_binding.get("type"):
        return False
    constraints = matches[0].get("constraints")
    if not isinstance(constraints, Mapping) or constraints.get("sideEffect") != "none":
        return False
    frame = persisted_state.active_frame
    if frame is None:
        return False
    inputs = capability.get("inputs", ())
    if not isinstance(inputs, (tuple, list)):
        return False
    input_descriptors = {
        raw.get("name"): raw for raw in inputs
        if isinstance(raw, Mapping) and isinstance(raw.get("name"), str)
    }
    if len(input_descriptors) != len(inputs):
        return False
    input_names = set(input_descriptors)
    required_names = {
        name for name, raw in input_descriptors.items() if raw.get("required") is True
    }
    if not required_names.issubset(frame.slots):
        return False
    if any(
        name not in input_names
        or slot.state != "RESOLVED"
        or slot.value is None
        or not _valid_semantic_input_value(input_descriptors[name], slot.value)
        for name, slot in frame.slots.items()
    ):
        return False
    expected_parameters = {
        name: slot.value
        for name, slot in frame.slots.items()
        if name in input_names and slot.state == "RESOLVED" and slot.value is not None
    }
    if call_plan.capability_id == INVENTORY_CAPABILITY_ID:
        expected_parameters.setdefault("unit", "EA")
    return (
        required_names.issubset(expected_parameters)
        and set(call_plan.parameters).issubset(input_names)
        and all(
            _valid_semantic_input_value(input_descriptors[name], value)
            for name, value in call_plan.parameters.items()
        )
        and call_plan.parameters == expected_parameters
    )


def _valid_semantic_input_value(descriptor: Mapping[str, object], value: str) -> bool:
    if not isinstance(value, str):
        return False
    value_type = descriptor.get("type")
    if value_type == "string":
        minimum = descriptor.get("minLength")
        maximum = descriptor.get("maxLength")
        if isinstance(minimum, int) and len(value) < minimum:
            return False
        if isinstance(maximum, int) and len(value) > maximum:
            return False
        pattern = descriptor.get("pattern")
        if isinstance(pattern, str):
            try:
                if re.fullmatch(pattern, value) is None:
                    return False
            except re.error:
                return False
        return True
    if value_type == "number":
        try:
            number = float(value)
        except ValueError:
            return False
        return number not in {float("inf"), float("-inf")} and number == number
    if value_type == "integer":
        try:
            int(value)
        except ValueError:
            return False
        return str(int(value)) == value or value.startswith("+") and str(int(value)) == value[1:]
    if value_type == "boolean":
        return value.lower() in {"true", "false"}
    if value_type in {"object", "array"}:
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            return False
        return isinstance(parsed, dict if value_type == "object" else list)
    return False


def _current_capability(
    sources: SemanticSourceDocuments, capability_id: str
) -> Mapping[str, object] | None:
    values = sources.capabilities.get("capabilities", ())
    matches = [
        value for value in values
        if isinstance(value, Mapping) and value.get("capabilityId") == capability_id
    ] if isinstance(values, (tuple, list)) else []
    return matches[0] if len(matches) == 1 else None


def _executor_binding_id(capability: Mapping[str, object]) -> str | None:
    executor_binding = capability.get("executorBinding")
    if not isinstance(executor_binding, Mapping):
        return None
    binding_id = executor_binding.get("bindingId")
    return binding_id if isinstance(binding_id, str) and binding_id else None


def _current_executor_binding(
    sources: SemanticSourceDocuments, binding_id: str
) -> Mapping[str, object] | None:
    values = sources.executor_bindings.get("bindings", ())
    matches = [
        value for value in values
        if isinstance(value, Mapping) and value.get("bindingId") == binding_id
    ] if isinstance(values, (tuple, list)) else []
    return matches[0] if len(matches) == 1 else None


def _governed_read_authority(
    principal: TrustedPrincipal,
    snapshot: RegistrySnapshot,
    sources: SemanticSourceDocuments,
) -> tuple[SnapshotLease, GovernedContext, VisibleCapabilitySet]:
    from sap_nexus_agent.planner.capability_card import discover_cards
    from sap_nexus_agent.visibility import filter_visible

    lease = SnapshotLease(snapshot=snapshot, sources=sources)
    governed_context = GovernedContext(
        principal=principal,
        scopes=tuple(f"{key}:{value}" for key, value in principal.data_scope.items()),
        snapshot_id=lease.snapshot_id,
        registry_version=snapshot.snapshot_version,
    )
    cards = filter_visible(discover_cards(snapshot, sources), for_execution=False)
    visible = VisibleCapabilitySet(
        cards=tuple(cards),
        snapshot_id=lease.snapshot_id,
        principal_id=principal.principal_id,
    )
    return lease, governed_context, visible


def _resolve_authoritative_read(
    *,
    text: str,
    context: ConversationContext,
    parsed: object,
    envelope: "IntentEnvelope | None",
    legacy_decision: MatchDecision,
    principal: TrustedPrincipal,
    governed_context: GovernedContext,
    lease: SnapshotLease,
    visible: VisibleCapabilitySet,
    turn_id: str,
) -> AgentOutcome | None:
    from sap_nexus_agent.capability_selector import build_read_context_candidates
    from sap_nexus_agent.context_decision_gate import (
        ReadCapabilityCandidates,
        decide_read_context,
    )
    from sap_nexus_agent.context_reducer import ContextReductionRequest, reduce_context
    from sap_nexus_agent.read_context import ConversationReadState
    from sap_nexus_agent.registry_loader import load_intent_catalog

    prior_state = context.read_state or ConversationReadState(None, None, 0)
    pending_resolution = _resolve_non_slot_pending(
        text=text,
        context=context,
        prior_state=prior_state,
        decision=legacy_decision,
        lease=lease,
        visible=visible,
        turn_id=turn_id,
    )
    if isinstance(pending_resolution, AgentOutcome):
        return pending_resolution
    prior_state = pending_resolution

    capability_id = legacy_decision.capability_id
    if legacy_decision.decision_type in {"SHOW_OPTIONS", "ESCALATE_TO_PLANNER"}:
        if legacy_decision.decision_type == "SHOW_OPTIONS":
            candidate_ids = tuple(
                candidate.capability_id for candidate in legacy_decision.candidates or ()
            )
            pending_kind = "CAPABILITY_CHOICE"
        else:
            candidate_ids = tuple(
                matched.capability_id
                for matched in (
                    legacy_decision.handoff.matched_intents
                    if legacy_decision.handoff is not None
                    else ()
                )
            )
            pending_kind = "PLANNER_CONFIRMATION"
        visible_ids = frozenset(card.capability_id for card in visible.cards)
        if candidate_ids and len(set(candidate_ids)) == len(candidate_ids) and all(
            candidate_id in visible_ids for candidate_id in candidate_ids
        ):
            return _bound_pending_outcome(
                context=context,
                prior_state=prior_state,
                decision=legacy_decision,
                kind=pending_kind,
                capability_ids=candidate_ids,
                resolution_kind=(
                    "read"
                    if all(
                        _is_current_read_capability(lease.sources, candidate_id)
                        for candidate_id in candidate_ids
                    )
                    else "non_read"
                ),
                snapshot_id=lease.snapshot_id,
                turn_id=turn_id,
                lease=lease,
            )
    if legacy_decision.decision_type == "REJECT":
        return _resolved_non_read_outcome(
            context=context,
            prior_state=prior_state,
            decision=legacy_decision,
            lease=lease,
            principal=principal,
            turn_id=turn_id,
        )
    if capability_id is None and envelope is not None and len(envelope.goals) == 1:
        capability_id = envelope.goals[0].capability_hint
    descriptor = load_intent_catalog().find(capability_id) if capability_id else None
    if descriptor is None or descriptor.side_effect != "none":
        return _resolved_non_read_outcome(
            context=context,
            prior_state=prior_state,
            decision=legacy_decision,
            lease=lease,
            principal=principal,
            turn_id=turn_id,
            parsed=parsed,
        )
    visible_ids = frozenset(card.capability_id for card in visible.cards)
    if capability_id not in visible_ids:
        return AgentOutcome(
            status="failure",
            message="READ capability is not visible to this principal.",
            error_type="VISIBILITY_DENIED",
            match_decision=MatchDecision(
                decision_type="REJECT",
                error_type="VISIBILITY_DENIED",
                rationale="READ capability is not visible to this principal.",
            ),
        )

    resolution = reduce_context(
        ContextReductionRequest(
            prior_state=prior_state,
            candidates=build_read_context_candidates(text, descriptor, envelope),
            descriptor=descriptor,
            registry_snapshot_id=lease.snapshot_id,
            capability_version=_read_capability_version(lease.sources, capability_id),
            turn_id=turn_id,
            server_time=datetime.now(UTC),
        )
    )
    decision_result = decide_read_context(
        resolution,
        governed_context=governed_context,
        lease=lease,
        capability_candidates=ReadCapabilityCandidates(
            capability_ids=(capability_id,),
            snapshot_id=lease.snapshot_id,
            purpose="AMBIGUITY",
        ),
    )
    decision = decision_result.decision
    next_state = resolution.next_state
    next_context = replace(
        context,
        last_context=None,
        pending_show_options=None,
        pending_escalate=None,
        read_state=next_state,
        schema_version=2,
    )
    call_plan = None
    binding = None
    combinations = None
    multi_parameters = getattr(parsed, "multi_parameters", {}) or {}
    if decision.decision_type == "SELECT" and decision_result.call_plan_parameters is not None:
        parameters = dict(decision_result.call_plan_parameters)
        if capability_id == INVENTORY_CAPABILITY_ID:
            parameters.setdefault("unit", "EA")
        call_plan = create_call_plan(capability_id, parameters, kind="Function")
        if multi_parameters:
            combinations = expand_combinations(parameters, multi_parameters)
            from sap_nexus_agent.read_context import PendingInteraction

            pending = PendingInteraction.batch_confirmation(
                frame_id=resolution.next_state.active_frame.frame_id,
                batch_ref=_pending_payload_ref({
                    "callPlan": call_plan.to_dict(),
                    "combinations": combinations,
                }),
                state_version=resolution.next_state.state_version,
                registry_snapshot_id=lease.snapshot_id,
                expires_at=(datetime.now(UTC) + timedelta(minutes=15))
                .isoformat()
                .replace("+00:00", "Z"),
            )
            next_state = ConversationReadState(
                active_frame=resolution.next_state.active_frame,
                pending_interaction=pending,
                state_version=resolution.next_state.state_version,
                recent_frames=resolution.next_state.recent_frames,
            )
            next_context = replace(next_context, read_state=next_state)
            decision = MatchDecision(
                decision_type="CLARIFY",
                capability_id=capability_id,
                parameters=dict(decision_result.call_plan_parameters),
                missing_parameters=[],
                rationale="READ 批量参数已绑定，等待用户确认。",
            )
            binding = ReadExecutionBinding.create(
                turn_id=turn_id,
                principal_id=principal.principal_id,
                call_plan=call_plan,
                read_state=next_state,
                executor_binding_id=_executor_binding_id(
                    _current_capability(lease.sources, capability_id) or {}
                ) or "",
            )
        else:
            binding = ReadExecutionBinding.create(
                turn_id=turn_id,
                principal_id=principal.principal_id,
                call_plan=call_plan,
                read_state=next_state,
                executor_binding_id=_executor_binding_id(
                    _current_capability(lease.sources, capability_id) or {}
                ) or "",
            )

    status = "awaiting_batch_confirm" if combinations is not None else {
        "SELECT": "resolved_read",
        "CLARIFY": "clarification",
        "SHOW_OPTIONS": "match_decision",
        "ESCALATE_TO_PLANNER": "match_decision",
        "REJECT": "failure",
    }[decision.decision_type]
    frame = next_state.active_frame
    return AgentOutcome(
        status=status,
        message=decision.rationale,
        response_text=decision.rationale,
        call_plan=call_plan,
        combinations=combinations,
        error_type=decision.error_type,
        missing_parameters=decision.missing_parameters,
        match_decision=decision,
        updated_context=next_context,
        read_state=next_state,
        resolution_report=decision_result.resolution_report,
        read_execution_binding=binding,
        turn_id=turn_id,
        frame_id=frame.frame_id if frame else None,
        state_version=next_state.state_version,
        registry_snapshot_id=lease.snapshot_id,
    )


def _read_capability_version(
    sources: SemanticSourceDocuments, capability_id: str
) -> str:
    values = sources.capabilities.get("capabilities", ())
    if isinstance(values, (tuple, list)):
        for value in values:
            if isinstance(value, Mapping) and value.get("capabilityId") == capability_id:
                return str(value.get("version", "1"))
    return "1"


def _is_current_read_capability(
    sources: SemanticSourceDocuments, capability_id: str
) -> bool:
    capability = _current_capability(sources, capability_id)
    governance = capability.get("governance") if capability else None
    return bool(
        capability is not None
        and capability.get("kind") == "Function"
        and isinstance(governance, Mapping)
        and governance.get("sideEffect") == "none"
        and governance.get("requiresApproval") is False
    )


def _bound_pending_outcome(
    *,
    context: ConversationContext,
    prior_state: "ConversationReadState",
    decision: MatchDecision,
    kind: str,
    capability_ids: tuple[str, ...],
    resolution_kind: str,
    snapshot_id: str,
    turn_id: str,
    lease: SnapshotLease,
) -> AgentOutcome:
    from sap_nexus_agent.read_context import ConversationReadState, PendingInteraction

    state_version = prior_state.state_version + 1
    frame_id = (
        prior_state.active_frame.frame_id
        if prior_state.active_frame is not None
        else f"pending:{kind.lower()}:{_pending_payload_ref({'turnId': turn_id, 'snapshotId': snapshot_id, 'capabilityIds': capability_ids})[-24:]}"
    )
    expires_at = (datetime.now(UTC) + timedelta(minutes=15)).isoformat().replace(
        "+00:00", "Z"
    )
    if kind == "CAPABILITY_CHOICE":
        pending = PendingInteraction.capability_choice(
            frame_id=frame_id,
            capability_ids=capability_ids,
            state_version=state_version,
            registry_snapshot_id=snapshot_id,
            expires_at=expires_at,
        )
    else:
        handoff = decision.handoff
        goals = tuple(
            {
                "capabilityId": matched.capability_id,
                "parameters": dict(matched.parameters),
                "missing": list(matched.missing),
            }
            for matched in (handoff.matched_intents if handoff is not None else ())
        )
        pending = PendingInteraction.planner_confirmation(
            frame_id=frame_id,
            planner_ref=_pending_payload_ref({"goals": goals}),
            goals=goals,
            state_version=state_version,
            registry_snapshot_id=snapshot_id,
            expires_at=expires_at,
        )
    next_state = ConversationReadState(
        active_frame=prior_state.active_frame,
        pending_interaction=pending,
        state_version=state_version,
        recent_frames=prior_state.recent_frames,
    )
    next_context = replace(
        context,
        last_context=None,
        pending_show_options=None,
        pending_escalate=None,
        read_state=next_state,
        schema_version=2,
    )
    compiled = (
        _compile_dry_run_safely(decision.handoff, lease=lease)
        if kind == "PLANNER_CONFIRMATION" and decision.handoff is not None
        else None
    )
    return AgentOutcome(
        status="match_decision",
        message=decision.rationale,
        response_text=decision.rationale,
        match_decision=decision,
        dry_run=compiled if isinstance(compiled, PlanCompileResult) else None,
        planner_failure=compiled if isinstance(compiled, PlannerFailure) else None,
        updated_context=next_context,
        read_state=next_state,
        resolution_report={
            "resolutionKind": resolution_kind,
            "frameStatus": (
                prior_state.active_frame.status
                if prior_state.active_frame is not None
                else "COLLECTING"
            ),
            "pendingKind": kind,
        },
        turn_id=turn_id,
        frame_id=frame_id,
        state_version=state_version,
        registry_snapshot_id=snapshot_id,
    )


def _resolved_non_read_outcome(
    *,
    context: ConversationContext,
    prior_state: "ConversationReadState",
    decision: MatchDecision,
    lease: SnapshotLease,
    principal: TrustedPrincipal,
    turn_id: str,
    parsed: object | None = None,
) -> AgentOutcome:
    from sap_nexus_agent.read_context import ConversationReadState

    next_state = ConversationReadState(
        active_frame=prior_state.active_frame,
        pending_interaction=None,
        state_version=prior_state.state_version + 1,
        recent_frames=prior_state.recent_frames,
    )
    next_context = replace(context, read_state=next_state, schema_version=2)
    status = {
        "CLARIFY": "clarification",
        "SHOW_OPTIONS": "match_decision",
        "ESCALATE_TO_PLANNER": "match_decision",
        "REJECT": "failure",
        "SELECT": "failure",
    }[decision.decision_type]
    call_plan = None
    binding = None
    if decision.decision_type == "SELECT" and decision.capability_id:
        capability = _current_capability(lease.sources, decision.capability_id)
        governance = capability.get("governance") if capability else None
        binding_id = _executor_binding_id(capability or {})
        if (
            capability is not None
            and capability.get("status") == "active"
            and capability.get("kind") == "Action"
            and isinstance(governance, Mapping)
            and governance.get("sideEffect") != "none"
            and governance.get("requiresApproval") is True
            and binding_id
        ):
            parameters = dict(
                decision.parameters or getattr(parsed, "parameters", {}) or {}
            )
            call_plan = create_call_plan(decision.capability_id, parameters, kind="Action")
            binding = SelectionExecutionBinding.create(
                turn_id=turn_id,
                state_version=next_state.state_version,
                registry_snapshot_id=lease.snapshot_id,
                principal_id=principal.principal_id,
                capability_version=str(capability.get("version", "1")),
                executor_binding_id=binding_id,
                call_plan=call_plan,
            )
            status = "resolved_selection"
    return AgentOutcome(
        status=status,
        message=decision.rationale,
        response_text=decision.rationale,
        call_plan=call_plan,
        error_type=decision.error_type,
        missing_parameters=decision.missing_parameters,
        match_decision=decision,
        updated_context=next_context,
        read_state=next_state,
        selection_execution_binding=binding,
        resolution_report={"resolutionKind": "non_read"},
        turn_id=turn_id,
        frame_id=(next_state.active_frame.frame_id if next_state.active_frame else None),
        state_version=next_state.state_version,
        registry_snapshot_id=lease.snapshot_id,
    )


def _pending_payload_ref(payload: object) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _resolve_non_slot_pending(
    *,
    text: str,
    context: ConversationContext,
    prior_state: "ConversationReadState",
    decision: MatchDecision,
    lease: SnapshotLease,
    visible: VisibleCapabilitySet,
    turn_id: str,
) -> "ConversationReadState | AgentOutcome":
    from sap_nexus_agent.read_context import ConversationReadState

    pending = prior_state.pending_interaction
    if pending is None or pending.kind == "SLOT_CLARIFICATION":
        return prior_state
    active_frame_id = prior_state.active_frame.frame_id if prior_state.active_frame else None
    synthetic = pending.frame_id.startswith("pending:") and active_frame_id is None
    binding_valid = (
        pending.state_version == prior_state.state_version
        and pending.registry_snapshot_id == lease.snapshot_id
        and (pending.frame_id == active_frame_id or synthetic)
        and _parse_expiry(pending.expires_at) > datetime.now(UTC)
    )
    visible_ids = frozenset(card.capability_id for card in visible.cards)
    if pending.kind == "BATCH_CONFIRMATION":
        if not binding_valid or not pending.batch_ref.startswith("sha256:"):
            return replace(prior_state, pending_interaction=None)
        return replace(prior_state, pending_interaction=None)
    if pending.kind == "CAPABILITY_CHOICE":
        binding_valid = binding_valid and bool(pending.capability_ids) and all(
            capability_id in visible_ids for capability_id in pending.capability_ids
        )
        selected = decision.capability_id
        if binding_valid and selected in pending.capability_ids:
            return replace(prior_state, pending_interaction=None)
        return replace(prior_state, pending_interaction=None)

    goals_payload = tuple(goal.to_dict() for goal in pending.planner_goals)
    binding_valid = (
        binding_valid
        and pending.planner_ref == _pending_payload_ref({"goals": goals_payload})
        and all(goal.capability_id in visible_ids for goal in pending.planner_goals)
    )
    confirmed = text.strip().lower() in {"继续", "continue", "ok", "好的", "确认", "confirm"}
    if not binding_valid or not confirmed:
        return replace(prior_state, pending_interaction=None)

    from sap_nexus_agent.match_decision import EscalationHandoff, MatchedIntent

    handoff = EscalationHandoff(
        reason="pending-confirmed",
        matched_intents=[
            MatchedIntent(
                capability_id=goal.capability_id,
                parameters=dict(goal.parameters),
                missing=list(goal.missing),
            )
            for goal in pending.planner_goals
        ],
        utterance=text,
        registry_snapshot_id=lease.snapshot_id,
    )
    confirmed_decision = MatchDecision(
        decision_type="ESCALATE_TO_PLANNER",
        handoff=handoff,
        rationale="用户已确认进入规划。",
    )
    next_state = replace(
        prior_state,
        pending_interaction=None,
        state_version=prior_state.state_version + 1,
    )
    next_context = replace(context, read_state=next_state, schema_version=2)
    compiled = _compile_dry_run_safely(handoff, lease=lease)
    return AgentOutcome(
        status="match_decision",
        message=confirmed_decision.rationale,
        response_text=confirmed_decision.rationale,
        match_decision=confirmed_decision,
        dry_run=compiled if isinstance(compiled, PlanCompileResult) else None,
        planner_failure=compiled if isinstance(compiled, PlannerFailure) else None,
        updated_context=next_context,
        read_state=next_state,
        resolution_report={"pendingKind": "PLANNER_CONFIRMATION", "consumed": True},
        turn_id=turn_id,
        frame_id=pending.frame_id,
        state_version=next_state.state_version,
        registry_snapshot_id=lease.snapshot_id,
    )


def _refresh_pending_outcome(
    context: ConversationContext,
    prior_state: "ConversationReadState",
    pending: "PendingInteraction",
    turn_id: str,
    response: str,
) -> AgentOutcome:
    from sap_nexus_agent.read_context import ConversationReadState

    rebound = replace(pending, state_version=prior_state.state_version + 1)
    next_state = ConversationReadState(
        active_frame=prior_state.active_frame,
        pending_interaction=rebound,
        state_version=prior_state.state_version + 1,
        recent_frames=prior_state.recent_frames,
    )
    return AgentOutcome(
        status="match_decision",
        message=response,
        response_text=response,
        updated_context=replace(context, read_state=next_state, schema_version=2),
        read_state=next_state,
        resolution_report={"pendingKind": pending.kind, "consumed": False},
        turn_id=turn_id,
        frame_id=pending.frame_id,
        state_version=next_state.state_version,
        registry_snapshot_id=pending.registry_snapshot_id,
    )


def _parse_expiry(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
    except ValueError:
        return datetime.min.replace(tzinfo=UTC)


def run_query(
    text: str,
    gateway: GatewayClientProtocol,
    *,
    intent_adapter: IntentAdapter = parse_intent,
    context: ConversationContext | None = None,
    principal: TrustedPrincipal | None = None,
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
    S2-B PlanCompiler v2 (``planner.handoff.compile_plan_v2_from_handoff``)
    to produce a deterministic ``PlanCompileResult`` attached to the outcome.
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
    # GovernedContext binding (Design Doc §4 data flow).
    # principal defaults to PLACEHOLDER for local dev backward compat.
    effective_principal = principal or PLACEHOLDER_PRINCIPAL

    # Construct SnapshotLease at entry: reuse injected snapshot/sources or
    # load via _default_planner_sources. Failure -> PlannerFailure.
    planner_failure: PlannerFailure | None = None
    lease: SnapshotLease | None = None
    try:
        if snapshot is None or sources is None:
            loader = planner_sources_loader or _default_planner_sources
            loaded_snapshot, loaded_sources = loader()
            if snapshot is None:
                snapshot = loaded_snapshot
            if sources is None:
                sources = loaded_sources
        if not snapshot.snapshot_id:
            planner_failure = PlannerFailure(
                error_type="SNAPSHOT_MISSING",
                message="build_registry_snapshot returned empty snapshot_id",
                snapshot_id=None,
                audit_evidence={
                    "expected_snapshot_id": None,
                    "actual_snapshot_id": None,
                    "principal_id": effective_principal.principal_id,
                    "source_paths": [],
                    "stage": "entry",
                },
            )
        else:
            lease = SnapshotLease(snapshot=snapshot, sources=sources)
    except Exception as exc:
        planner_failure = PlannerFailure(
            error_type="SOURCE_LOAD_ERROR",
            message=f"failed to load registry sources: {exc}",
            snapshot_id=None,
            audit_evidence={
                "expected_snapshot_id": None,
                "actual_snapshot_id": None,
                "principal_id": effective_principal.principal_id,
                "source_paths": [],
                "stage": "entry",
            },
        )

    if planner_failure is not None:
        return AgentOutcome(
            status="failure",
            message=planner_failure.message,
            response_text=planner_failure.message,
            error_type=planner_failure.error_type,
            planner_failure=planner_failure,
        )

    assert lease is not None  # for type checker
    scopes = tuple(f"{k}:{v}" for k, v in effective_principal.data_scope.items())
    governed_context = GovernedContext(
        principal=effective_principal,
        scopes=scopes,
        snapshot_id=lease.snapshot_id,
        registry_version=snapshot.snapshot_version,
    )

    # Backward-compat dispatch: when context is None, call the adapter with
    # the original single-arg signature so existing 1-arg adapters (and the
    # default ``parse_intent``) are byte-for-byte unchanged. Only forward
    # ``context`` when it is actually provided.
    if context is None:
        parsed = intent_adapter(text)
    else:
        # Runbook 14 cross-turn continuation: inspect pending_show_options /
        # pending_escalate from turn N and clear them if turn N+1 is a new
        # intent (primary keyword) or a candidate selection / confirm.
        context = _resolve_pending_state(text, context)
        parsed = intent_adapter(text, context)

    # Discover cards from snapshot and filter visible (Design Doc §4).
    from sap_nexus_agent.planner.capability_card import discover_cards
    from sap_nexus_agent.visibility import filter_visible

    all_cards = discover_cards(snapshot, sources)
    visible_cards = filter_visible(all_cards, for_execution=False)
    if not visible_cards:
        return AgentOutcome(
            status="failure",
            message="principal has no visible capabilities",
            response_text="principal has no visible capabilities",
            error_type="VISIBILITY_DENIED",
            planner_failure=PlannerFailure(
                error_type="VISIBILITY_DENIED",
                message="principal has no visible capabilities",
                snapshot_id=lease.snapshot_id,
                audit_evidence={
                    "expected_snapshot_id": lease.snapshot_id,
                    "actual_snapshot_id": lease.snapshot_id,
                    "principal_id": effective_principal.principal_id,
                    "source_paths": [],
                    "stage": "visibility",
                },
            ),
        )
    visible_capability_set = VisibleCapabilitySet(
        cards=tuple(visible_cards),
        snapshot_id=lease.snapshot_id,
        principal_id=effective_principal.principal_id,
    )

    # Runbook 14 bridge: if the adapter returned an IntentEnvelope, dispatch
    # through recall -> rerank -> select_capability_from_envelope. Otherwise
    # fall back to the legacy IntentParseResult -> select_capability path.
    # This allows new envelope-based adapters to coexist with legacy ones
    # during the migration; the BREAKING removal of IntentParseResult is
    # deferred to a follow-up.
    from sap_nexus_agent.intent_envelope import IntentEnvelope

    if isinstance(parsed, IntentEnvelope):
        decision, envelope = _dispatch_envelope(
            parsed, visible_capability_set, lease
        )
    else:
        decision = select_capability(parsed, visible=visible_capability_set)
        envelope = None

    if (
        _read_context_mode() == "v2"
        and context is not None
        and context.read_state is not None
    ):
        resolved = _resolve_authoritative_read(
            text=text,
            context=context,
            parsed=parsed,
            envelope=envelope,
            legacy_decision=decision,
            principal=effective_principal,
            governed_context=governed_context,
            lease=lease,
            visible=visible_capability_set,
            turn_id=f"turn-{context.read_state.state_version + 1}",
        )
        if resolved is not None:
            if resolved.match_decision is None or resolved.match_decision.decision_type != "SELECT":
                return resolved
            assert resolved.call_plan is not None
            if resolved.status == "resolved_selection":
                assert resolved.selection_execution_binding is not None
                executed = continue_resolved_selection(
                    resolved.call_plan,
                    resolved.selection_execution_binding,
                    gateway,
                    principal=effective_principal,
                    snapshot=snapshot,
                    sources=sources,
                )
                return replace(
                    executed,
                    match_decision=resolved.match_decision,
                    updated_context=resolved.updated_context,
                    read_state=resolved.read_state,
                    resolution_report=resolved.resolution_report,
                    selection_execution_binding=resolved.selection_execution_binding,
                    turn_id=resolved.turn_id,
                    frame_id=resolved.frame_id,
                    state_version=resolved.state_version,
                    registry_snapshot_id=resolved.registry_snapshot_id,
                )
            assert resolved.read_execution_binding is not None
            executed = continue_resolved_read(
                resolved.call_plan,
                resolved.read_execution_binding,
                gateway,
                persisted_state=resolved.read_state,
                principal=effective_principal,
                snapshot=snapshot,
                sources=sources,
            )
            return replace(
                executed,
                match_decision=resolved.match_decision,
                updated_context=resolved.updated_context,
                read_state=resolved.read_state,
                resolution_report=resolved.resolution_report,
                read_execution_binding=resolved.read_execution_binding,
                turn_id=resolved.turn_id,
                frame_id=resolved.frame_id,
                state_version=resolved.state_version,
                registry_snapshot_id=resolved.registry_snapshot_id,
            )

    context_shadow = _context_shadow(
        mode=_read_context_mode(),
        decision=decision,
        envelope=envelope,
        context=context,
        governed_context=governed_context,
        lease=lease,
    )

    # REJECT (technical override / unsupported intent): no Gateway.
    if decision.decision_type == "REJECT":
        return AgentOutcome(
            status="failure",
            message=decision.rationale,
            response_text=decision.rationale,
            error_type=decision.error_type,
            match_decision=decision,
            updated_context=_clear_pending_if_present(context),
            context_shadow=context_shadow,
        )

    # CLARIFY (single intent missing required params): no Gateway.
    if decision.decision_type == "CLARIFY":
        return AgentOutcome(
            status="clarification",
            message=decision.rationale,
            response_text=decision.rationale,
            missing_parameters=decision.missing_parameters,
            match_decision=decision,
            updated_context=_clear_pending_if_present(context),
            context_shadow=context_shadow,
        )

    # SHOW_OPTIONS / ESCALATE_TO_PLANNER: handoff to workbench/planner, no Gateway.
    if decision.decision_type in ("SHOW_OPTIONS", "ESCALATE_TO_PLANNER"):
        dry_run = None
        planner_failure = None
        if decision.decision_type == "ESCALATE_TO_PLANNER" and decision.handoff is not None:
            result = _compile_dry_run_safely(decision.handoff, lease=lease)
            if isinstance(result, PlannerFailure):
                planner_failure = result
            else:
                dry_run = result
        # Runbook 14: write advisory pending state for cross-turn continuation.
        # Mutual exclusivity is enforced by ConversationContext.with_pending_*.
        updated_context = None
        if context is not None:
            from sap_nexus_agent.conversation_context import (
                PendingEscalate,
                PendingShowOptions,
            )

            if (
                decision.decision_type == "SHOW_OPTIONS"
                and decision.candidates
            ):
                pending = PendingShowOptions(
                    candidates=tuple(decision.candidates),
                    snapshot_id=lease.snapshot_id,
                )
                updated_context = context.with_pending_show_options(pending)
            elif (
                decision.decision_type == "ESCALATE_TO_PLANNER"
                and decision.handoff is not None
            ):
                pending = PendingEscalate(
                    handoff=decision.handoff,
                    snapshot_id=lease.snapshot_id,
                )
                updated_context = context.with_pending_escalate(pending)
        return AgentOutcome(
            status="match_decision",
            message=decision.rationale,
            response_text=decision.rationale,
            match_decision=decision,
            dry_run=dry_run,
            planner_failure=planner_failure,
            updated_context=updated_context,
            context_shadow=context_shadow,
        )

    # SELECT -> CallPlan -> Gateway validate/execute (existing path).
    capability_id = decision.capability_id
    # For the envelope path, decision.parameters already carries the goal's
    # merged parameters; for the legacy path, fall back to parsed.parameters.
    if envelope is not None:
        parameters = dict(decision.parameters or {})
    else:
        parameters = dict(decision.parameters or parsed.parameters)
    if capability_id == INVENTORY_CAPABILITY_ID:
        parameters.setdefault("unit", "EA")

    # Kind from snapshot projection (Design Doc D6): use
    # governance.requires_approval from the visible CapabilityCard,
    # not the hardcoded ACTION_CAPABILITY_IDS set.
    matched_card = next(
        (c for c in visible_capability_set.cards if c.capability_id == capability_id),
        None,
    )
    is_action = matched_card is not None and matched_card.governance.requires_approval

    # Multi-value detection (Design Doc §4.4): expand combinations and await
    # user confirmation before any Gateway call. READ-only: Action capabilities
    # must NOT take this path - they require an ApprovalRecord (single-action
    # approval). Action batch is a non-goal (Design Doc §2); an Action with
    # multi_parameters falls through to the awaiting_approval path below using
    # base parameters.
    #
    # Envelope path: multi_parameters is not yet carried on IntentEnvelope
    # (deferred to a follow-up per Task 8.1 note); the legacy path reads it
    # from parsed.multi_parameters.
    multi_parameters = (
        {} if envelope is not None else getattr(parsed, "multi_parameters", {}) or {}
    )
    if multi_parameters and capability_id not in ACTION_CAPABILITY_IDS:
        combinations = expand_combinations(parameters, multi_parameters)
        if len(combinations) > BATCH_COMBINATION_CAP:
            return AgentOutcome(
                status="clarification",
                response_text=f"组合数 {len(combinations)} 过多，请缩小范围（如减少物料或工厂）。",
                match_decision=decision,
                updated_context=_clear_pending_if_present(context),
                context_shadow=context_shadow,
            )
        kind = "Action" if is_action else "Function"
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
            updated_context=_clear_pending_if_present(context),
            context_shadow=context_shadow,
        )

    kind = "Action" if is_action else "Function"
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
            updated_context=_clear_pending_if_present(context),
            context_shadow=context_shadow,
        )

    is_action = call_plan.kind == "Action"
    if is_action:
        pending = create_approval_record(
            capability_id=call_plan.capability_id,
            parameters=call_plan.parameters,
            approver="user",
            registry_snapshot_id=lease.snapshot_id,
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
            updated_context=_clear_pending_if_present(context),
            context_shadow=context_shadow,
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
            updated_context=_clear_pending_if_present(context),
            context_shadow=context_shadow,
        )

    if capability_id == INVENTORY_CAPABILITY_ID:
        return _finalize_inventory(
            call_plan, validation, execution, decision=decision,
            updated_context=_clear_pending_if_present(context),
            context_shadow=context_shadow,
        )
    return _finalize_purchase_order(
        call_plan, validation, execution, decision=decision,
        updated_context=_clear_pending_if_present(context),
        context_shadow=context_shadow,
    )


def continue_batch(
    call_plan: CallPlan,
    combinations: list[dict[str, str]],
    gateway: GatewayClientProtocol,
    *,
    decision: MatchDecision | None = None,
) -> AgentOutcome:
    """Execute a confirmed multi-value batch (Design Doc §4.4).

    Per combination: validate -> execute -> build_availability_fact.
    Partial failures are annotated, not global. All-failed -> failure outcome.
    READ-only: no approval flow (analogous to continue_action but without
    ApprovalRecord).
    """
    # Defense-in-depth: continue_batch must never execute a WRITE capability.
    # Action capabilities require an ApprovalRecord + gateway.approve; the
    # batch path bypasses both (Design Doc §2 Non-Goal). The run_query guard
    # already prevents Action from reaching awaiting_batch_confirm; this assert
    # protects against direct misuse of continue_batch with an Action call_plan.
    if call_plan.capability_id in ACTION_CAPABILITY_IDS:
        raise ValueError(
            f"continue_batch is READ-only; capability {call_plan.capability_id} "
            "is an Action requiring human approval"
        )
    facts: list[ReasoningFact] = []
    failures: list[dict] = []
    for combo in combinations:
        validation = gateway.validate(call_plan.capability_id, combo)
        if not validation.success:
            failures.append({"parameters": combo, "error": validation.error_type})
            continue
        execution = gateway.execute(call_plan.capability_id, combo)
        if not execution.success:
            failures.append({"parameters": combo, "error": execution.error_type})
            continue
        fact = build_availability_fact(call_plan.agent_trace_id, execution, combo)
        if fact is not None:
            facts.append(fact)

    if not facts and failures:
        return AgentOutcome(
            status="failure",
            message="全部组合查询失败",
            response_text=narrate_failure(failures[0]["error"], []),
            call_plan=call_plan,
            error_type=failures[0]["error"],
            facts=[],
            match_decision=decision,
        )

    try:
        response_text = narrate_inventory_facts(facts, failures=failures)
    except NarrativeGuardError:
        response_text = "批量查询完成，但部分结果缺少可叙事字段。"

    return AgentOutcome(
        status="success",
        response_text=response_text,
        call_plan=call_plan,
        facts=facts,
        match_decision=decision,
    )


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
    updated_context: "ConversationContext | None" = None,
    context_shadow: "ContextShadow | None" = None,
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
            updated_context=updated_context,
            context_shadow=context_shadow,
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
            updated_context=updated_context,
            context_shadow=context_shadow,
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
        updated_context=updated_context,
        context_shadow=context_shadow,
    )


def _finalize_purchase_order(
    call_plan: CallPlan,
    validation: ValidationResult,
    execution: ExecutionResult,
    *,
    decision: MatchDecision | None = None,
    updated_context: "ConversationContext | None" = None,
    context_shadow: "ContextShadow | None" = None,
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
            updated_context=updated_context,
            context_shadow=context_shadow,
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
        updated_context=updated_context,
        context_shadow=context_shadow,
    )


def _read_context_mode() -> str:
    """Read the rollout mode from server process configuration only."""
    mode = os.environ.get("READ_CONTEXT_MODE", "v2")
    return mode if mode in {"legacy", "shadow", "v2"} else "v2"


def _context_shadow(
    *,
    mode: str,
    decision: MatchDecision,
    envelope: "IntentEnvelope | None",
    context: "ConversationContext | None",
    governed_context: GovernedContext,
    lease: SnapshotLease,
) -> "ContextShadow | None":
    """Enter the combined server-owned shadow decision service."""
    if mode != "shadow" or envelope is None:
        return None

    from sap_nexus_agent.context_decision_gate import evaluate_context_shadow

    return evaluate_context_shadow(
        decision=decision,
        envelope=envelope,
        prior_state=context.read_state if context is not None else None,
        governed_context=governed_context,
        lease=lease,
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
    lease: SnapshotLease,
) -> "PlanCompileResult | PlannerFailure":
    """Compile a dry-run from the handoff, consuming the same lease.

    Checks snapshot drift via ``lease.assert_same`` before compiling.
    On drift or source-load failure, returns a structured ``PlannerFailure``
    (Design Doc §3.5) instead of silently returning None.
    """
    try:
        lease.assert_same(handoff.registry_snapshot_id, stage="planner")
    except SnapshotDriftError as exc:
        return PlannerFailure(
            error_type="SNAPSHOT_DRIFT",
            message=str(exc),
            snapshot_id=lease.snapshot_id,
            audit_evidence={
                "expected_snapshot_id": exc.expected,
                "actual_snapshot_id": exc.actual,
                "principal_id": None,
                "source_paths": [],
                "stage": exc.stage,
            },
        )
    try:
        return compile_plan_v2_from_handoff(handoff, lease.snapshot, lease.sources)
    except Exception as exc:
        return PlannerFailure(
            error_type="SOURCE_LOAD_ERROR",
            message=f"planner source compilation failed: {exc}",
            snapshot_id=lease.snapshot_id,
            audit_evidence={
                "expected_snapshot_id": lease.snapshot_id,
                "actual_snapshot_id": lease.snapshot_id,
                "principal_id": None,
                "source_paths": [],
                "stage": "planner",
            },
        )


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


# ---------------------------------------------------------------------------
# Runbook 14: cross-turn continuation helpers
# ---------------------------------------------------------------------------


def _dispatch_envelope(
    envelope: "IntentEnvelope",
    visible_capability_set: "VisibleCapabilitySet",
    lease: SnapshotLease,
) -> "tuple[MatchDecision, IntentEnvelope]":
    """Run the Runbook 14 envelope pipeline: recall -> rerank -> selector.

    Returns the ``MatchDecision`` and the source ``IntentEnvelope`` (for
    callers that need to read goal-level fields not carried on the decision).
    Advisory recall / rerank evidence is attached to the decision's replay
    fields by ``select_capability_from_envelope``.
    """
    from sap_nexus_agent.capability_selector import select_capability_from_envelope
    from sap_nexus_agent.recall import recall
    from sap_nexus_agent.rerank import rerank
    from sap_nexus_agent.registry_loader import load_intent_catalog

    catalog = load_intent_catalog()
    visible_ids = frozenset(c.capability_id for c in visible_capability_set.cards)
    recall_candidates = recall(envelope.utterance, visible_ids, catalog)
    ranked_candidates, rerank_evidence = rerank(recall_candidates, envelope, catalog)
    decision = select_capability_from_envelope(
        envelope,
        recall_candidates=ranked_candidates,
        rerank_evidence=rerank_evidence,
        visible_capability_ids=visible_ids,
    )
    return decision, envelope


def _clear_pending_if_present(
    context: "ConversationContext | None",
) -> "ConversationContext | None":
    """Clear advisory pending state when the new decision supersedes it.

    SELECT / CLARIFY / REJECT all represent a fresh capability decision for
    turn N+1; any pending_show_options / pending_escalate left over from
    turn N must be discarded so the next turn starts clean. Returns the
    cleared context, or None if no context was provided (single-turn path).
    """
    if context is None:
        return None
    if context.pending_show_options is None and context.pending_escalate is None:
        return context
    return context.clear_pending()


def _resolve_pending_state(
    text: str,
    context: "ConversationContext",
) -> "ConversationContext":
    """Inspect pending_show_options / pending_escalate at turn N+1 entry.

    Advisory only: this function MUST NOT route execution or short-circuit
    the selector. It only clears pending state when the user's turn N+1
    utterance signals a new intent (primary keyword) or a candidate
    selection / planner confirmation - the selector re-runs in either case
    so the decision is re-derived from the fresh utterance.

    Clearing rules:
    - ``pending_show_options``: cleared when the utterance contains a
      primary keyword for one of the candidates (selection) or any primary
      keyword at all (new intent). The selector re-runs on the fresh text.
    - ``pending_escalate``: cleared when the utterance is a confirmation
      ("继续" / "continue" / "ok") or contains any primary keyword (new
      intent). Confirmation hands off to the planner dry-run; new intent
      starts a fresh capability match.

    If neither pending state is present, the context is returned unchanged.
    """
    from sap_nexus_agent.llm_intent import _contains_any_primary_keyword

    if context.pending_show_options is None and context.pending_escalate is None:
        return context

    has_primary = _contains_any_primary_keyword(text)

    if context.pending_show_options is not None:
        if _match_selected_capability(text, context.pending_show_options.candidates):
            return context.clear_pending()
        if has_primary:
            return context.clear_pending()

    if context.pending_escalate is not None:
        normalized = text.strip().lower()
        if normalized in ("继续", "continue", "ok", "好的", "确认", "confirm"):
            return context.clear_pending()
        if has_primary:
            return context.clear_pending()

    return context


def _match_selected_capability(text: str, candidates) -> str | None:
    """Match utterance against a candidate's primary keyword.

    Returns the matched capability_id, or None if no candidate's primary
    keyword set matches the utterance. Used by ``_resolve_pending_state``
    to detect a SHOW_OPTIONS selection on turn N+1.
    """
    from sap_nexus_agent.intent import (
        INVENTORY_PRIMARY_KEYWORDS,
        PR_CREATE_PRIMARY_KEYWORDS,
        PURCHASE_ORDER_PRIMARY_KEYWORDS,
    )

    keyword_map = {
        "MM.Inventory.GetAvailability": INVENTORY_PRIMARY_KEYWORDS,
        "MM.PurchaseOrder.GetList": PURCHASE_ORDER_PRIMARY_KEYWORDS,
        "MM.PR.CreateDraft": PR_CREATE_PRIMARY_KEYWORDS,
    }
    for cand in candidates:
        cid = cand.capability_id
        keywords = keyword_map.get(cid)
        if keywords and any(k in text for k in keywords):
            return cid
    return None

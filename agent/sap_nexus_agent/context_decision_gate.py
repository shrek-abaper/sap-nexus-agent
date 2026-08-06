"""Fail-closed adapter from a reduced READ frame to a match decision."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Iterable, Literal, Mapping

from sap_nexus_agent.context_reducer import ContextResolution
from sap_nexus_agent.governed_context import (
    GovernedContext,
    SnapshotLease,
    TrustedPrincipal,
    VisibleCapabilitySet,
)
from sap_nexus_agent.match_decision import MatchDecision, MatchedIntent
from sap_nexus_agent.planner.capability_card import CapabilityCard
from sap_nexus_agent.semantic_planning import SemanticSourceDocuments
from sap_nexus_agent.semantic_planning import validation as semantic_validation

CandidatePurpose = Literal["AMBIGUITY", "MULTI_GOAL"]
__all__ = [
    "ContextDecisionResult",
    "ContextShadow",
    "ReadCapabilityCandidates",
    "decide_read_context",
    "evaluate_context_shadow",
]
_DECISION_TYPES = frozenset(
    {"SELECT", "CLARIFY", "REJECT", "SHOW_OPTIONS", "ESCALATE_TO_PLANNER"}
)


@dataclass(frozen=True, repr=False)
class _ServerReadAuthority:
    """Ephemeral eligibility derived and consumed inside this service boundary."""

    visible: VisibleCapabilitySet
    capability_ids: frozenset[str]
    sources: SemanticSourceDocuments
    snapshot_id: str

    def __reduce__(self) -> object:
        raise TypeError("server READ authority is not serializable")

    def __reduce_ex__(self, _protocol: int) -> object:
        raise TypeError("server READ authority is not serializable")


@dataclass(frozen=True)
class ReadCapabilityCandidates:
    """Bounded candidate IDs that must be revalidated against current visibility."""

    capability_ids: tuple[str, ...]
    snapshot_id: str
    purpose: CandidatePurpose
    goal_count: int | None = None

    def __post_init__(self) -> None:
        ids = tuple(self.capability_ids)
        if not all(isinstance(capability_id, str) and capability_id for capability_id in ids):
            raise ValueError("ReadCapabilityCandidates capability IDs are invalid")
        if not isinstance(self.snapshot_id, str) or not self.snapshot_id:
            raise ValueError("ReadCapabilityCandidates requires a snapshot ID")
        if self.purpose not in {"AMBIGUITY", "MULTI_GOAL"}:
            raise ValueError("ReadCapabilityCandidates purpose is invalid")
        goal_count = self.goal_count if self.goal_count is not None else len(ids)
        if not isinstance(goal_count, int) or goal_count < 1:
            raise ValueError("ReadCapabilityCandidates goal_count is invalid")
        if self.purpose == "AMBIGUITY" and not ids:
            raise ValueError("AMBIGUITY candidates require capability IDs")
        if self.purpose == "MULTI_GOAL" and goal_count < 2:
            raise ValueError("MULTI_GOAL candidates require multiple goals")
        object.__setattr__(self, "capability_ids", ids)
        object.__setattr__(self, "goal_count", goal_count)


@dataclass(frozen=True)
class ContextShadow:
    """The five-field, serializable boundary for shadow rollout evidence."""

    legacy_decision: str
    frame_v2_decision: str
    slot_diff: tuple[str, ...]
    would_block_legacy_execution: bool
    would_clarify: bool

    def __post_init__(self) -> None:
        if self.legacy_decision not in _DECISION_TYPES:
            raise ValueError("ContextShadow legacy_decision is invalid")
        if self.frame_v2_decision not in _DECISION_TYPES:
            raise ValueError("ContextShadow frame_v2_decision is invalid")
        if not isinstance(self.slot_diff, tuple) or not all(
            isinstance(slot, str) and slot for slot in self.slot_diff
        ):
            raise ValueError("ContextShadow slot_diff must be a tuple of slot names")
        if not isinstance(self.would_block_legacy_execution, bool):
            raise ValueError("ContextShadow would_block_legacy_execution must be bool")
        if not isinstance(self.would_clarify, bool):
            raise ValueError("ContextShadow would_clarify must be bool")

    def to_dict(self) -> dict[str, object]:
        return {
            "legacyDecision": self.legacy_decision,
            "frameV2Decision": self.frame_v2_decision,
            "slotDiff": list(self.slot_diff),
            "wouldBlockLegacyExecution": self.would_block_legacy_execution,
            "wouldClarify": self.would_clarify,
        }


@dataclass(frozen=True)
class ContextDecisionResult:
    """Decision and redacted reduction evidence; never an executable CallPlan."""

    decision: MatchDecision
    resolution_report: Mapping[str, object]
    call_plan_parameters: Mapping[str, str] | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "resolution_report", MappingProxyType(dict(self.resolution_report)))
        if self.call_plan_parameters is not None:
            object.__setattr__(
                self,
                "call_plan_parameters",
                MappingProxyType(dict(self.call_plan_parameters)),
            )


def decide_read_context(
    resolution: ContextResolution | None,
    *,
    governed_context: GovernedContext | None = None,
    lease: SnapshotLease | None = None,
    capability_candidates: ReadCapabilityCandidates | None = None,
) -> ContextDecisionResult:
    """Derive current server authority and decide without exposing it.

    ``governed_context`` and ``lease`` are server-owned orchestration inputs.
    Request/model/Session fields may influence ``resolution`` or candidates,
    but cannot provide visibility, Registry sources, or execution eligibility.
    The derived authority exists only for this call and is never returned.
    """
    report = _resolution_report(resolution)
    authority = _derive_server_read_authority(governed_context, lease)
    if authority is None:
        return _reject(
            report,
            "EXECUTION_VISIBILITY_INVALID",
            "READ 执行权威缺失、无效或不属于当前服务端上下文。",
        )
    return _decide_read_context(
        resolution,
        authority=authority,
        capability_candidates=capability_candidates,
    )


def _decide_read_context(
    resolution: ContextResolution | None,
    *,
    authority: _ServerReadAuthority,
    capability_candidates: ReadCapabilityCandidates | None,
) -> ContextDecisionResult:
    """Pure decision core; callers cannot inject execution eligibility."""
    report = _resolution_report(resolution)
    visible = authority.visible
    current_snapshot_id = authority.snapshot_id

    candidate_decision = _candidate_decision(
        capability_candidates,
        visible,
        current_snapshot_id,
        report,
        authority.capability_ids,
    )
    if candidate_decision is not None:
        return candidate_decision

    frame = resolution.next_state.active_frame if resolution is not None else None
    if frame is None:
        return _clarify(report, "没有可用的 READ 上下文帧。")
    if frame.registry_snapshot_id != current_snapshot_id:
        return _reject(report, "CONTEXT_SNAPSHOT_DRIFT", "上下文帧不属于当前 Registry 快照。")

    cards = tuple(card for card in visible.cards if card.capability_id == frame.capability_id)
    if len(cards) != 1:
        return _reject(report, "VISIBILITY_DENIED", "上下文能力不在当前可见闭集内。")
    card = cards[0]
    if not _is_current_executable_read(
        card, current_snapshot_id, authority.capability_ids
    ):
        return _reject(
            report,
            "READ_CONTEXT_VISIBILITY_DENIED",
            "上下文能力不属于当前可执行 READ 可见集。",
        )

    inputs = {input_.name: input_ for input_ in card.inputs}
    if any(name not in inputs for name in frame.slots):
        return _reject(report, "CONTEXT_TECHNICAL_FIELD", "上下文包含未注册参数。")
    if resolution.operation == "NEW_MULTI_GOAL":
        return _escalate(report)
    if frame.status != "READY" or resolution.next_state.pending_interaction is not None:
        return ContextDecisionResult(
            MatchDecision(
                decision_type="CLARIFY",
                capability_id=frame.capability_id,
                missing_parameters=_clarification_fields(card.inputs, frame.slots),
                rationale="READ 上下文尚未可安全执行。",
            ),
            report,
            None,
        )

    parameters: dict[str, str] = {}
    for input_ in card.inputs:
        slot = frame.slots.get(input_.name)
        if input_.required and (slot is None or slot.state != "RESOLVED" or slot.value is None):
            return _clarify(report, "缺少已确认的必需 READ 参数。")
        if slot is None:
            continue
        if slot.state != "RESOLVED" or slot.value is None:
            return _reject(report, "CONTEXT_SLOT_INVALID", "READ 上下文包含未解析参数。")
        if slot.provenance == "MODEL_CANDIDATE":
            return _reject(report, "CONTEXT_MODEL_CANDIDATE", "模型候选不能成为 READ 执行参数。")
        parameters[input_.name] = slot.value

    decision = MatchDecision(
        decision_type="SELECT",
        capability_id=frame.capability_id,
        parameters=dict(parameters),
        rationale="当前快照中的唯一可见 READ capability 已由已解析槽位满足。",
    )
    return ContextDecisionResult(decision, report, parameters)


def _candidate_decision(
    candidates: ReadCapabilityCandidates | None,
    visible: VisibleCapabilitySet,
    current_snapshot_id: str,
    report: Mapping[str, object],
    executable_ids: frozenset[str],
) -> ContextDecisionResult | None:
    if candidates is None:
        return None
    if candidates.snapshot_id != current_snapshot_id:
        return _reject(report, "CONTEXT_SNAPSHOT_DRIFT", "候选能力不属于当前 Registry 快照。")
    if (
        candidates.purpose == "AMBIGUITY"
        and len(set(candidates.capability_ids)) != len(candidates.capability_ids)
    ):
        return _reject(report, "CONTEXT_CANDIDATE_DUPLICATE", "候选能力不能重复。")

    cards = []
    for capability_id in dict.fromkeys(candidates.capability_ids):
        matching = [card for card in visible.cards if card.capability_id == capability_id]
        if len(matching) != 1 or not _is_current_executable_read(
            matching[0], current_snapshot_id, executable_ids
        ):
            return _reject(
                report,
                "READ_CONTEXT_VISIBILITY_DENIED",
                "候选能力不在当前可执行 READ 可见集内。",
            )
        cards.append(matching[0])

    if candidates.purpose == "MULTI_GOAL":
        return _escalate(report)
    if len(cards) > 1:
        return ContextDecisionResult(
            MatchDecision(
                decision_type="SHOW_OPTIONS",
                candidates=[
                    MatchedIntent(card.capability_id, parameters={}, missing=[])
                    for card in cards
                ],
                rationale="多个当前可见 READ capability 需要用户选择。",
            ),
            report,
            None,
        )
    return None


def _is_current_executable_read(
    card, snapshot_id: str, executable_ids: frozenset[str]
) -> bool:
    return (
        card.registry_snapshot_id == snapshot_id
        and card.capability_id in executable_ids
        and card.governance.side_effect == "none"
        and not card.governance.requires_approval
        and card.governance.data_classification == "internal"
    )


def _derive_server_read_authority(
    governed_context: GovernedContext | None,
    lease: SnapshotLease | None,
) -> _ServerReadAuthority | None:
    """Bind current immutable sources, snapshot, principal and READ bindings."""
    if (
        not isinstance(governed_context, GovernedContext)
        or not isinstance(governed_context.principal, TrustedPrincipal)
        or not isinstance(lease, SnapshotLease)
        or not isinstance(lease.sources, SemanticSourceDocuments)
    ):
        return None
    try:
        contracts = semantic_validation.build_semantic_contracts(lease.sources)
        if (
            not contracts.report.valid
            or contracts.snapshot != lease.snapshot
            or not governed_context.principal.principal_id
            or governed_context.snapshot_id != lease.snapshot_id
            or governed_context.registry_version != lease.registry_version
        ):
            return None
        return _project_server_read_authority(governed_context, lease)
    except Exception:
        # Malformed Registry data or projection failures never grant authority.
        return None


def _project_server_read_authority(
    governed_context: GovernedContext,
    lease: SnapshotLease,
) -> _ServerReadAuthority:
    from sap_nexus_agent.planner.capability_card import discover_cards
    from sap_nexus_agent.visibility import filter_visible

    all_cards = discover_cards(lease.snapshot, lease.sources)
    visible_cards = filter_visible(all_cards, for_execution=False)
    visible = VisibleCapabilitySet(
        cards=tuple(visible_cards),
        snapshot_id=lease.snapshot_id,
        principal_id=governed_context.principal.principal_id,
    )
    raw_capabilities = _unique_registry_index(
        lease.sources.capabilities.get("capabilities", ()), "capabilityId"
    )
    bindings = _unique_registry_index(
        lease.sources.executor_bindings.get("bindings", ()), "bindingId"
    )
    execution_cards = _unique_card_index(
        filter_visible(all_cards, for_execution=True)
    )
    unique_visible_cards = _unique_card_index(visible_cards)
    eligible_ids: set[str] = set()
    for capability_id, card in execution_cards.items():
        if (
            unique_visible_cards.get(capability_id) != card
            or card.registry_snapshot_id != lease.snapshot_id
            or card.governance.requires_approval
        ):
            continue
        capability = raw_capabilities.get(capability_id)
        if not isinstance(capability, Mapping) or capability.get("status") != "active":
            continue
        executor_binding = capability.get("executorBinding")
        if not isinstance(executor_binding, Mapping):
            continue
        binding_id = executor_binding.get("bindingId")
        binding = bindings.get(binding_id)
        if (
            not isinstance(binding_id, str)
            or not binding_id
            or not isinstance(binding, Mapping)
            or executor_binding.get("type") != binding.get("type")
        ):
            continue
        constraints = binding.get("constraints")
        if isinstance(constraints, Mapping) and constraints.get("sideEffect") == "none":
            eligible_ids.add(capability_id)

    return _ServerReadAuthority(
        visible=visible,
        capability_ids=frozenset(eligible_ids),
        sources=lease.sources,
        snapshot_id=lease.snapshot_id,
    )


def evaluate_context_shadow(
    *,
    decision: MatchDecision,
    envelope: object,
    prior_state: object | None,
    governed_context: GovernedContext | None,
    lease: SnapshotLease | None,
) -> ContextShadow | None:
    """Resolve and decide one shadow turn inside the trusted service boundary."""
    authority = _derive_server_read_authority(governed_context, lease)
    if authority is None:
        return None
    capability_candidates = _shadow_capability_candidates(
        envelope, decision, authority.snapshot_id
    )
    if capability_candidates is None:
        return None
    if capability_candidates.purpose == "MULTI_GOAL" or len(
        capability_candidates.capability_ids
    ) > 1:
        frame_decision = _decide_read_context(
            None,
            authority=authority,
            capability_candidates=capability_candidates,
        )
        return _to_context_shadow(decision, frame_decision, ())

    capability_id = capability_candidates.capability_ids[0]
    descriptor = _current_read_descriptor(authority, capability_id)
    if descriptor is None:
        return None

    from sap_nexus_agent.context_candidates import extract_context_candidates
    from sap_nexus_agent.context_reducer import ContextReductionRequest, reduce_context
    from sap_nexus_agent.read_context import ConversationReadState

    if prior_state is None:
        current_state = ConversationReadState(None, None, 0)
    elif isinstance(prior_state, ConversationReadState):
        current_state = prior_state
    else:
        return None
    resolution = reduce_context(
        ContextReductionRequest(
            prior_state=current_state,
            candidates=extract_context_candidates(
                envelope.utterance, descriptor, envelope
            ),
            descriptor=descriptor,
            registry_snapshot_id=authority.snapshot_id,
            capability_version=_capability_version(
                authority.sources, descriptor.capability_id
            ),
            turn_id="shadow-read-context",
            server_time=datetime.now(UTC),
        )
    )
    frame_decision = _decide_read_context(
        resolution,
        authority=authority,
        capability_candidates=capability_candidates,
    )
    legacy_parameters = decision.parameters or {}
    frame_parameters = frame_decision.call_plan_parameters or {}
    slot_diff = tuple(
        input_.name
        for input_ in descriptor.inputs
        if legacy_parameters.get(input_.name) != frame_parameters.get(input_.name)
    )
    return _to_context_shadow(decision, frame_decision, slot_diff)


def _shadow_capability_candidates(
    envelope: object,
    decision: MatchDecision,
    snapshot_id: str,
) -> ReadCapabilityCandidates | None:
    goals = getattr(envelope, "goals", None)
    if not isinstance(goals, tuple):
        return None
    if len(goals) > 1:
        capability_ids = tuple(
            goal.capability_hint
            for goal in goals
            if isinstance(getattr(goal, "capability_hint", None), str)
            and goal.capability_hint
        )
        return ReadCapabilityCandidates(
            capability_ids=capability_ids,
            snapshot_id=snapshot_id,
            purpose="MULTI_GOAL",
            goal_count=len(goals),
        )
    if len(goals) != 1:
        return None

    recall_candidates = tuple(decision.recall_candidates)
    if len(recall_candidates) > 1:
        return ReadCapabilityCandidates(
            capability_ids=recall_candidates,
            snapshot_id=snapshot_id,
            purpose="AMBIGUITY",
        )
    capability_id = getattr(goals[0], "capability_hint", None)
    if not isinstance(capability_id, str) or not capability_id:
        return None
    return ReadCapabilityCandidates(
        capability_ids=(capability_id,),
        snapshot_id=snapshot_id,
        purpose="AMBIGUITY",
    )


def _current_read_descriptor(
    authority: _ServerReadAuthority,
    capability_id: str,
):
    cards = [
        card
        for card in authority.visible.cards
        if card.capability_id == capability_id
    ]
    if len(cards) != 1:
        return None
    card = cards[0]
    if not _is_current_executable_read(
        card, authority.snapshot_id, authority.capability_ids
    ):
        return None

    raw_capabilities = authority.sources.capabilities.get("capabilities")
    if not isinstance(raw_capabilities, (tuple, list)):
        return None
    matches = [
        raw
        for raw in raw_capabilities
        if isinstance(raw, Mapping)
        and raw.get("capabilityId") == capability_id
        and raw.get("status") == "active"
    ]
    if len(matches) != 1:
        return None

    from sap_nexus_agent.registry_loader import CapabilityDescriptor, InputDescriptor

    raw = matches[0]
    raw_inputs = raw.get("inputs")
    if not isinstance(raw_inputs, (tuple, list)):
        return None
    inputs = []
    for input_ in raw_inputs:
        if not isinstance(input_, Mapping) or not isinstance(input_.get("name"), str):
            return None
        inputs.append(
            InputDescriptor(
                name=input_["name"],
                semantic_name=str(input_.get("semanticName", input_["name"])),
                semantic_type=str(input_.get("semanticType", "")),
                binding_kind=(
                    str(input_["bindingKind"])
                    if input_.get("bindingKind") is not None
                    else None
                ),
                required=bool(input_.get("required", False)),
                type=str(input_.get("type", "string")),
                min_length=input_.get("minLength"),
                max_length=input_.get("maxLength"),
                pattern=input_.get("pattern"),
            )
        )
    return CapabilityDescriptor(
        capability_id=capability_id,
        name=str(raw.get("name", "")),
        description=str(raw.get("description", "")),
        domain=str(raw.get("domain", "")),
        business_object=str(raw.get("businessObject", "")),
        inputs=tuple(inputs),
        aliases=(),
        examples=(),
        side_effect=card.governance.side_effect,
    )


def _capability_version(
    sources: SemanticSourceDocuments, capability_id: str
) -> str:
    capabilities = _unique_registry_index(
        sources.capabilities.get("capabilities", ()), "capabilityId"
    )
    capability = capabilities.get(capability_id)
    return str(capability.get("version", "1")) if capability is not None else "1"


def _to_context_shadow(
    legacy_decision: MatchDecision,
    frame_decision: ContextDecisionResult,
    slot_diff: tuple[str, ...],
) -> ContextShadow:
    frame_decision_type = frame_decision.decision.decision_type
    return ContextShadow(
        legacy_decision=legacy_decision.decision_type,
        frame_v2_decision=frame_decision_type,
        slot_diff=slot_diff,
        would_block_legacy_execution=(
            legacy_decision.decision_type == "SELECT"
            and frame_decision_type != "SELECT"
        ),
        would_clarify=frame_decision_type == "CLARIFY",
    )


def _unique_registry_index(
    values: object, identity_field: str
) -> dict[str, Mapping[str, object]]:
    if not isinstance(values, (tuple, list)):
        return {}
    index: dict[str, Mapping[str, object]] = {}
    duplicates: set[str] = set()
    for value in values:
        if not isinstance(value, Mapping):
            continue
        identity = value.get(identity_field)
        if not isinstance(identity, str) or not identity:
            continue
        if identity in index or identity in duplicates:
            index.pop(identity, None)
            duplicates.add(identity)
            continue
        index[identity] = value
    return index


def _unique_card_index(cards: Iterable[CapabilityCard]) -> dict[str, CapabilityCard]:
    index: dict[str, CapabilityCard] = {}
    duplicates: set[str] = set()
    for card in cards:
        capability_id = card.capability_id
        if capability_id in index or capability_id in duplicates:
            index.pop(capability_id, None)
            duplicates.add(capability_id)
            continue
        index[capability_id] = card
    return index


def _clarification_fields(inputs, slots) -> list[str]:
    fields: list[str] = []
    for input_ in inputs:
        slot = slots.get(input_.name)
        if input_.required and (slot is None or slot.state != "RESOLVED"):
            fields.append(input_.name)
        if slot is not None and slot.state == "CONFLICTED" and input_.name not in fields:
            fields.append(input_.name)
    return fields


def _escalate(report: Mapping[str, object]) -> ContextDecisionResult:
    return ContextDecisionResult(
        MatchDecision(
            decision_type="ESCALATE_TO_PLANNER",
            rationale="多个 READ 目标需要 planner 处理。",
        ),
        report,
        None,
    )


def _resolution_report(resolution: ContextResolution | None) -> dict[str, object]:
    frame = resolution.next_state.active_frame if resolution is not None else None
    return {
        "frameStatus": frame.status if frame is not None else None,
        "capabilityId": frame.capability_id if frame is not None else None,
        "slotStates": {
            name: slot.state for name, slot in frame.slots.items()
        }
        if frame is not None
        else {},
        "issues": list(resolution.issues) if resolution is not None else [],
    }


def _clarify(report: Mapping[str, object], rationale: str) -> ContextDecisionResult:
    return ContextDecisionResult(
        MatchDecision(decision_type="CLARIFY", missing_parameters=[], rationale=rationale),
        report,
        None,
    )


def _reject(
    report: Mapping[str, object], error_type: str, rationale: str
) -> ContextDecisionResult:
    return ContextDecisionResult(
        MatchDecision(decision_type="REJECT", error_type=error_type, rationale=rationale),
        report,
        None,
    )

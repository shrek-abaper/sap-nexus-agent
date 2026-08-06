"""Fail-closed adapter from a reduced READ frame to a match decision."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from dataclasses import asdict, dataclass, field
from types import MappingProxyType
from typing import Iterable, Literal, Mapping

from sap_nexus_agent.context_reducer import ContextResolution
from sap_nexus_agent.governed_context import VisibleCapabilitySet
from sap_nexus_agent.match_decision import MatchDecision, MatchedIntent
from sap_nexus_agent.planner.capability_card import CapabilityCard
from sap_nexus_agent.semantic_planning import SemanticSourceDocuments

CandidatePurpose = Literal["AMBIGUITY", "MULTI_GOAL"]
_DECISION_TYPES = frozenset(
    {"SELECT", "CLARIFY", "REJECT", "SHOW_OPTIONS", "ESCALATE_TO_PLANNER"}
)
_EXECUTION_PROJECTION_KEY = secrets.token_bytes(32)


@dataclass(frozen=True)
class ExecutionVisibilityProjection:
    """Server-issued proof of execution eligibility for one governed view."""

    capability_ids: frozenset[str]
    snapshot_id: str
    principal_id: str
    visible_context_binding: str
    _proof: bytes = field(repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "capability_ids", frozenset(self.capability_ids))


def _build_execution_visibility_projection(
    *,
    cards: Iterable[CapabilityCard],
    visible: VisibleCapabilitySet,
    current_snapshot_id: str,
    sources: SemanticSourceDocuments,
) -> ExecutionVisibilityProjection:
    """Issue a projection only from current Registry and governed card facts."""
    raw_capabilities = _unique_registry_index(
        sources.capabilities.get("capabilities", ()), "capabilityId"
    )
    bindings = _unique_registry_index(
        sources.executor_bindings.get("bindings", ()), "bindingId"
    )

    from sap_nexus_agent.visibility import filter_visible

    execution_cards = _unique_card_index(filter_visible(list(cards), for_execution=True))
    visible_cards = _unique_card_index(visible.cards)
    eligible_ids: set[str] = set()
    if visible.snapshot_id == current_snapshot_id:
        for capability_id, card in execution_cards.items():
            if (
                visible_cards.get(capability_id) != card
                or card.registry_snapshot_id != current_snapshot_id
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

    capability_ids = frozenset(eligible_ids)
    visible_context_binding = _visible_context_binding(visible)
    proof = _execution_projection_proof(
        capability_ids,
        current_snapshot_id,
        visible.principal_id,
        visible_context_binding,
    )
    return ExecutionVisibilityProjection(
        capability_ids=capability_ids,
        snapshot_id=current_snapshot_id,
        principal_id=visible.principal_id,
        visible_context_binding=visible_context_binding,
        _proof=proof,
    )


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
    visible: VisibleCapabilitySet,
    current_snapshot_id: str,
    capability_candidates: ReadCapabilityCandidates | None = None,
    execution_visibility: ExecutionVisibilityProjection | None = None,
) -> ContextDecisionResult:
    """Map one reduced frame to a closed-set READ decision without side effects."""
    report = _resolution_report(resolution)
    if not current_snapshot_id or visible.snapshot_id != current_snapshot_id:
        return _reject(report, "CONTEXT_SNAPSHOT_DRIFT", "当前 Registry 快照不匹配。")
    executable_ids = _validated_execution_ids(
        execution_visibility, visible, current_snapshot_id
    )
    if executable_ids is None:
        return _reject(
            report,
            "EXECUTION_VISIBILITY_INVALID",
            "READ 执行可见性投影无效或不属于当前受信上下文。",
        )

    candidate_decision = _candidate_decision(
        capability_candidates, visible, current_snapshot_id, report, executable_ids
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
    if not _is_current_executable_read(card, current_snapshot_id, executable_ids):
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


def _projection_allows_execution(
    projection: ExecutionVisibilityProjection,
    *,
    visible: VisibleCapabilitySet,
    current_snapshot_id: str,
    capability_id: str,
) -> bool:
    executable_ids = _validated_execution_ids(
        projection, visible, current_snapshot_id
    )
    return executable_ids is not None and capability_id in executable_ids


def _validated_execution_ids(
    projection: ExecutionVisibilityProjection | None,
    visible: VisibleCapabilitySet,
    current_snapshot_id: str,
) -> frozenset[str] | None:
    if projection is None:
        return frozenset(
            card.capability_id
            for card in visible.cards
            if card.visibility == "VISIBLE_EXECUTION"
        )
    if not isinstance(projection, ExecutionVisibilityProjection):
        return None
    try:
        visible_context_binding = _visible_context_binding(visible)
        expected_proof = _execution_projection_proof(
            projection.capability_ids,
            projection.snapshot_id,
            projection.principal_id,
            projection.visible_context_binding,
        )
    except (AttributeError, TypeError, ValueError):
        return None
    if (
        projection.snapshot_id != current_snapshot_id
        or projection.principal_id != visible.principal_id
        or projection.visible_context_binding != visible_context_binding
        or not isinstance(projection._proof, bytes)
        or not hmac.compare_digest(projection._proof, expected_proof)
    ):
        return None
    for capability_id in projection.capability_ids:
        matches = [card for card in visible.cards if card.capability_id == capability_id]
        if len(matches) != 1 or not _is_current_executable_read(
            matches[0], current_snapshot_id, projection.capability_ids
        ):
            return None
    return projection.capability_ids


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


def _visible_context_binding(visible: VisibleCapabilitySet) -> str:
    payload = {
        "cards": [asdict(card) for card in visible.cards],
        "principalId": visible.principal_id,
        "snapshotId": visible.snapshot_id,
    }
    canonical = json.dumps(
        payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def _execution_projection_proof(
    capability_ids: frozenset[str],
    snapshot_id: str,
    principal_id: str,
    visible_context_binding: str,
) -> bytes:
    payload = json.dumps(
        {
            "capabilityIds": sorted(capability_ids),
            "principalId": principal_id,
            "snapshotId": snapshot_id,
            "visibleContextBinding": visible_context_binding,
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hmac.digest(_EXECUTION_PROJECTION_KEY, payload, "sha256")


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

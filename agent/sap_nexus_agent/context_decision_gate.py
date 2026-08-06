"""Fail-closed adapter from a reduced READ frame to a match decision."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal, Mapping

from sap_nexus_agent.context_reducer import ContextResolution
from sap_nexus_agent.governed_context import VisibleCapabilitySet
from sap_nexus_agent.match_decision import MatchDecision, MatchedIntent

CandidatePurpose = Literal["AMBIGUITY", "MULTI_GOAL"]
_DECISION_TYPES = frozenset(
    {"SELECT", "CLARIFY", "REJECT", "SHOW_OPTIONS", "ESCALATE_TO_PLANNER"}
)


@dataclass(frozen=True)
class ReadCapabilityCandidates:
    """Bounded candidate IDs that must be revalidated against current visibility."""

    capability_ids: tuple[str, ...]
    snapshot_id: str
    purpose: CandidatePurpose

    def __post_init__(self) -> None:
        ids = tuple(self.capability_ids)
        if not ids or not all(isinstance(capability_id, str) and capability_id for capability_id in ids):
            raise ValueError("ReadCapabilityCandidates requires non-empty capability IDs")
        if not isinstance(self.snapshot_id, str) or not self.snapshot_id:
            raise ValueError("ReadCapabilityCandidates requires a snapshot ID")
        if self.purpose not in {"AMBIGUITY", "MULTI_GOAL"}:
            raise ValueError("ReadCapabilityCandidates purpose is invalid")
        object.__setattr__(self, "capability_ids", ids)


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
) -> ContextDecisionResult:
    """Map one reduced frame to a closed-set READ decision without side effects."""
    report = _resolution_report(resolution)
    if not current_snapshot_id or visible.snapshot_id != current_snapshot_id:
        return _reject(report, "CONTEXT_SNAPSHOT_DRIFT", "当前 Registry 快照不匹配。")

    candidate_decision = _candidate_decision(
        capability_candidates, visible, current_snapshot_id, report
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
    if not _is_current_executable_read(card, current_snapshot_id):
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
) -> ContextDecisionResult | None:
    if candidates is None:
        return None
    if candidates.snapshot_id != current_snapshot_id:
        return _reject(report, "CONTEXT_SNAPSHOT_DRIFT", "候选能力不属于当前 Registry 快照。")
    if len(set(candidates.capability_ids)) != len(candidates.capability_ids):
        return _reject(report, "CONTEXT_CANDIDATE_DUPLICATE", "候选能力不能重复。")

    cards = []
    for capability_id in candidates.capability_ids:
        matching = [card for card in visible.cards if card.capability_id == capability_id]
        if len(matching) != 1 or not _is_current_executable_read(
            matching[0], current_snapshot_id
        ):
            return _reject(
                report,
                "READ_CONTEXT_VISIBILITY_DENIED",
                "候选能力不在当前可执行 READ 可见集内。",
            )
        cards.append(matching[0])

    if candidates.purpose == "MULTI_GOAL":
        if len(cards) < 2:
            return _reject(report, "CONTEXT_MULTI_GOAL_INVALID", "多目标至少需要两个 READ capability。")
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


def _is_current_executable_read(card, snapshot_id: str) -> bool:
    return (
        card.registry_snapshot_id == snapshot_id
        and card.visibility == "VISIBLE_EXECUTION"
        and card.governance.side_effect == "none"
        and not card.governance.requires_approval
        and card.governance.data_classification == "internal"
    )


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

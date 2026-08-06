"""Fail-closed adapter from a reduced READ frame to a match decision."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from sap_nexus_agent.context_reducer import ContextResolution
from sap_nexus_agent.governed_context import VisibleCapabilitySet
from sap_nexus_agent.match_decision import MatchDecision


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
    resolution: ContextResolution,
    *,
    visible: VisibleCapabilitySet,
    current_snapshot_id: str,
) -> ContextDecisionResult:
    """Map one reduced frame to a closed-set READ decision without side effects."""
    frame = resolution.next_state.active_frame
    report = _resolution_report(resolution)
    if frame is None:
        return _clarify(report, "没有可用的 READ 上下文帧。")

    if not current_snapshot_id or visible.snapshot_id != current_snapshot_id:
        return _reject(report, "CONTEXT_SNAPSHOT_DRIFT", "当前 Registry 快照不匹配。")
    if frame.registry_snapshot_id != current_snapshot_id:
        return _reject(report, "CONTEXT_SNAPSHOT_DRIFT", "上下文帧不属于当前 Registry 快照。")

    cards = tuple(card for card in visible.cards if card.capability_id == frame.capability_id)
    if len(cards) != 1:
        return _reject(report, "VISIBILITY_DENIED", "上下文能力不在当前可见闭集内。")
    card = cards[0]
    if card.registry_snapshot_id and card.registry_snapshot_id != current_snapshot_id:
        return _reject(report, "CONTEXT_SNAPSHOT_DRIFT", "可见能力不属于当前 Registry 快照。")
    if (
        card.governance.side_effect != "none"
        or card.governance.requires_approval
        or card.governance.data_classification != "internal"
    ):
        return _reject(report, "READ_CONTEXT_WRITE_DENIED", "READ 上下文不能选择 WRITE capability。")

    inputs = {input_.name: input_ for input_ in card.inputs}
    if any(name not in inputs for name in frame.slots):
        return _reject(report, "CONTEXT_TECHNICAL_FIELD", "上下文包含未注册参数。")
    if resolution.operation == "NEW_MULTI_GOAL":
        return ContextDecisionResult(
            MatchDecision(
                decision_type="ESCALATE_TO_PLANNER",
                rationale="多个 READ 目标需要 planner 处理。",
            ),
            report,
            None,
        )
    if frame.status != "READY" or resolution.next_state.pending_interaction is not None:
        missing = [
            input_.name
            for input_ in card.inputs
            if input_.required
            and (
                input_.name not in frame.slots
                or frame.slots[input_.name].state != "RESOLVED"
            )
        ]
        return ContextDecisionResult(
            MatchDecision(
                decision_type="CLARIFY",
                capability_id=frame.capability_id,
                missing_parameters=missing,
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


def _resolution_report(resolution: ContextResolution) -> dict[str, object]:
    frame = resolution.next_state.active_frame
    return {
        "frameStatus": frame.status if frame is not None else None,
        "capabilityId": frame.capability_id if frame is not None else None,
        "slotStates": {
            name: slot.state for name, slot in frame.slots.items()
        }
        if frame is not None
        else {},
        "issues": list(resolution.issues),
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

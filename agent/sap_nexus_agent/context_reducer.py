"""Pure, deterministic state reduction for governed READ context."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from collections.abc import Iterable
from typing import Literal, Mapping

from sap_nexus_agent.context_candidates import ContextCandidate, ContextCandidateSet
from sap_nexus_agent.read_context import (
    ConversationReadState,
    PendingInteraction,
    ReadContextFrame,
    SlotBinding,
)
from sap_nexus_agent.registry_loader import CapabilityDescriptor

ContextOperation = Literal[
    "CONTINUE_FRAME",
    "REPLACE_SLOT",
    "CLEAR_SLOT",
    "SWITCH_CAPABILITY",
    "CONFIRM_PENDING",
    "REJECT_PENDING",
    "NEW_MULTI_GOAL",
]


@dataclass(frozen=True)
class ResolutionEvidence:
    slot: str | None
    value: str | None
    source: str
    reason: str


@dataclass(frozen=True)
class ContextReductionRequest:
    prior_state: ConversationReadState
    candidates: ContextCandidateSet
    descriptor: CapabilityDescriptor
    registry_snapshot_id: str
    capability_version: str
    turn_id: str
    server_time: str | datetime


@dataclass(frozen=True)
class ContextResolution:
    next_state: ConversationReadState
    operation: ContextOperation
    changed_slots: tuple[str, ...]
    issues: tuple[str, ...]
    evidence: tuple[ResolutionEvidence, ...]

    def slot(self, name: str) -> SlotBinding:
        """Return a slot from the next active frame for concise regression assertions."""
        frame = self.next_state.active_frame
        if frame is None:
            raise KeyError(name)
        return frame.slots[name]


def reduce_context(request: ContextReductionRequest) -> ContextResolution:
    """Reduce one trusted READ turn without IO or execution side effects."""
    prior = request.prior_state
    descriptor = request.descriptor
    active = prior.active_frame
    issues = list(request.candidates.discard_reasons)
    evidence: list[ResolutionEvidence] = []
    operation: ContextOperation = "CONTINUE_FRAME"
    recent_frames = prior.recent_frames
    pending = prior.pending_interaction

    switching = active is not None and active.capability_id != descriptor.capability_id
    if switching:
        operation = "SWITCH_CAPABILITY"
        recent_frames = (active, *recent_frames)[:2]
        active = None
        pending = None
        evidence.append(ResolutionEvidence(None, None, "DETERMINISTIC_LABEL", "capability_switch"))

    stale = False
    if active is not None:
        if active.capability_version != request.capability_version:
            stale = True
            pending = None
            _append_unique(issues, "capability_version_mismatch")
        elif active.registry_snapshot_id != request.registry_snapshot_id:
            evidence.append(ResolutionEvidence(None, None, "SYSTEM", "snapshot_rebound"))

    rejected_pending = pending is not None and not _pending_is_current(pending, active, prior, request)
    rejected_pending_fields = pending.expected_fields if rejected_pending and pending is not None else ()
    if rejected_pending:
        pending = None
        _append_unique(issues, "pending_binding_invalid")
        if not switching:
            operation = "REJECT_PENDING"

    slots = dict(active.slots) if active is not None else {}
    changed_slots: list[str] = []
    confirmed_pending = False
    deterministic_changed = False

    for input_ in descriptor.inputs:
        name = input_.name
        prior_slot = slots.get(name)
        slot_candidates = request.candidates.for_slot(name)
        deterministic = _unique_deterministic_values(slot_candidates.candidates)
        model_values = _unique_model_values(slot_candidates.candidates)

        if name in rejected_pending_fields:
            evidence.append(ResolutionEvidence(name, None, "SYSTEM", "stale_pending_answer_discarded"))
            continue

        for value in model_values:
            evidence.append(ResolutionEvidence(name, value, "MODEL_CANDIDATE", "advisory_only"))

        if name in request.candidates.clear_slots:
            replacement = SlotBinding(
                name=name,
                value=None,
                candidates=(),
                state="CLEARED",
                provenance="EXPLICIT",
                source_turn_id=request.turn_id,
                source_span=None,
                issues=(),
            )
            if replacement != prior_slot:
                slots[name] = replacement
                changed_slots.append(name)
            evidence.append(ResolutionEvidence(name, None, "EXPLICIT", "slot_cleared"))
            continue

        if len(deterministic) > 1:
            replacement = SlotBinding(
                name=name,
                value=None,
                candidates=deterministic,
                state="CONFLICTED",
                provenance="EXPLICIT",
                source_turn_id=request.turn_id,
                source_span=None,
                issues=("conflicting_deterministic_values",),
            )
            slots[name] = replacement
            changed_slots.append(name)
            _append_unique(issues, f"conflicting_deterministic_values:{name}")
            evidence.append(ResolutionEvidence(name, None, "DETERMINISTIC_LABEL", "conflict"))
            continue

        if deterministic:
            value = deterministic[0]
            was_cleared = prior_slot is not None and prior_slot.state == "CLEARED"
            pending_answer = pending is not None and name in pending.expected_fields
            provenance = "CONFIRMED" if was_cleared or pending_answer else "EXPLICIT"
            replacement = SlotBinding(
                name=name,
                value=value,
                candidates=(value,),
                state="RESOLVED",
                provenance=provenance,
                source_turn_id=request.turn_id,
                source_span=_source_span(slot_candidates.candidates, value),
                issues=(),
            )
            if replacement != prior_slot:
                slots[name] = replacement
                changed_slots.append(name)
                deterministic_changed = True
            evidence.append(ResolutionEvidence(name, value, "DETERMINISTIC_LABEL", provenance.lower()))
            if pending_answer:
                confirmed_pending = True
            continue

        if prior_slot is not None and prior_slot.provenance == "INHERITED_LEGACY":
            slots[name] = prior_slot
            evidence.append(
                ResolutionEvidence(name, prior_slot.value, "INHERITED_LEGACY", "requires_revalidation")
            )
            continue

        if prior_slot is not None and prior_slot.state == "RESOLVED":
            inherited = SlotBinding(
                name=name,
                value=prior_slot.value,
                candidates=prior_slot.candidates,
                state="RESOLVED",
                provenance="INHERITED",
                source_turn_id=prior_slot.source_turn_id,
                source_span=prior_slot.source_span,
                issues=prior_slot.issues,
            )
            if inherited != prior_slot:
                slots[name] = inherited
                changed_slots.append(name)
            evidence.append(ResolutionEvidence(name, prior_slot.value, "INHERITED", "active_confirmed_value"))

    if request.candidates.clear_slots and not switching:
        operation = "CLEAR_SLOT"
    elif confirmed_pending and not switching:
        operation = "CONFIRM_PENDING"
        pending = None
    elif deterministic_changed and active is not None and not switching and operation == "CONTINUE_FRAME":
        operation = "REPLACE_SLOT"

    if active is None:
        frame_id = _frame_id(descriptor.capability_id, request.turn_id)
        created_turn_id = request.turn_id
    else:
        frame_id = active.frame_id
        created_turn_id = active.created_turn_id

    status = _derive_status(descriptor, slots, stale, pending)
    frame = ReadContextFrame(
        frame_id=frame_id,
        capability_id=descriptor.capability_id,
        slots=slots,
        status=status,
        created_turn_id=created_turn_id,
        updated_turn_id=request.turn_id,
        registry_snapshot_id=request.registry_snapshot_id,
        capability_version=request.capability_version,
    )

    if status != "READY" and not stale:
        expected_fields = tuple(
            input_.name
            for input_ in descriptor.inputs
            if input_.required and (input_.name not in slots or slots[input_.name].state != "RESOLVED")
        )
        if expected_fields and pending is None:
            pending = PendingInteraction.slot_clarification(
                frame_id=frame.frame_id,
                expected_fields=expected_fields,
                state_version=prior.state_version + 1,
                registry_snapshot_id=request.registry_snapshot_id,
                expires_at=_expires_at(request.server_time),
            )
        for name in expected_fields:
            _append_unique(issues, f"missing_required:{name}")

    if pending is not None:
        pending = PendingInteraction(
            kind=pending.kind,
            frame_id=frame.frame_id,
            expected_fields=pending.expected_fields,
            state_version=prior.state_version + 1,
            registry_snapshot_id=request.registry_snapshot_id,
            expires_at=pending.expires_at,
        )

    next_state = ConversationReadState(
        active_frame=frame,
        pending_interaction=pending,
        state_version=prior.state_version + 1,
        recent_frames=recent_frames,
    )
    return ContextResolution(
        next_state=next_state,
        operation=operation,
        changed_slots=tuple(changed_slots),
        issues=tuple(issues),
        evidence=tuple(evidence),
    )


def _derive_status(
    descriptor: CapabilityDescriptor,
    slots: Mapping[str, SlotBinding],
    stale: bool,
    pending: PendingInteraction | None,
) -> Literal["COLLECTING", "READY", "CONFLICTED", "STALE"]:
    if stale or descriptor.side_effect != "none":
        return "STALE"
    if any(slot.state == "CONFLICTED" for slot in slots.values()):
        return "CONFLICTED"
    for input_ in descriptor.inputs:
        if input_.required and (input_.name not in slots or slots[input_.name].state != "RESOLVED"):
            return "COLLECTING"
    if pending is not None:
        return "COLLECTING"
    if any(slot.provenance == "INHERITED_LEGACY" for slot in slots.values()):
        return "STALE"
    return "READY"


def _pending_is_current(
    pending: PendingInteraction,
    active: ReadContextFrame | None,
    state: ConversationReadState,
    request: ContextReductionRequest,
) -> bool:
    if active is None or pending.binding_key != (
        active.frame_id,
        state.state_version,
        request.registry_snapshot_id,
    ):
        return False
    return _parse_time(request.server_time) < _parse_time(pending.expires_at)


def _expires_at(server_time: str | datetime) -> str:
    return (_parse_time(server_time) + timedelta(minutes=15)).isoformat().replace("+00:00", "Z")


def _parse_time(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _frame_id(capability_id: str, turn_id: str) -> str:
    return f"{capability_id}:{turn_id}"


def _unique_deterministic_values(candidates: tuple[ContextCandidate, ...]) -> tuple[str, ...]:
    return _unique_values(candidate for candidate in candidates if candidate.source == "DETERMINISTIC_LABEL")


def _unique_model_values(candidates: tuple[ContextCandidate, ...]) -> tuple[str, ...]:
    return _unique_values(candidate for candidate in candidates if candidate.source == "MODEL_CANDIDATE")


def _unique_values(candidates: Iterable[ContextCandidate]) -> tuple[str, ...]:
    values: list[str] = []
    for candidate in candidates:
        if candidate.value not in values:
            values.append(candidate.value)
    return tuple(values)


def _source_span(candidates: tuple[ContextCandidate, ...], value: str) -> tuple[int, int] | None:
    for candidate in candidates:
        if candidate.source == "DETERMINISTIC_LABEL" and candidate.value == value:
            return candidate.source_span
    return None


def _append_unique(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)

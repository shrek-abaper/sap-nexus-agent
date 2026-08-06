"""Fail-closed decoder for legacy ``LastContext`` READ state."""

from __future__ import annotations

from collections.abc import Mapping

from sap_nexus_agent.conversation_context import ConversationContext, LastContext
from sap_nexus_agent.read_context import ConversationReadState, ReadContextFrame, SlotBinding


def migrate_legacy_context(
    legacy: ConversationContext | Mapping[str, object], *, snapshot_id: str, turn_id: str
) -> ConversationReadState:
    """Convert a schema-v1 context into a stale Frame without mutating its source."""
    _require_non_empty(snapshot_id, "snapshot_id")
    _require_non_empty(turn_id, "turn_id")

    last_context = _legacy_last_context(legacy)
    if last_context is None:
        return ConversationReadState(active_frame=None, pending_interaction=None, state_version=0)

    if (
        last_context.decision_type not in {"SELECT", "CLARIFY"}
        or not isinstance(last_context.capability_id, str)
        or not last_context.capability_id
        or not isinstance(last_context.parameters, Mapping)
        or not isinstance(last_context.missing_parameters, list)
    ):
        return ConversationReadState(active_frame=None, pending_interaction=None, state_version=0)

    slots: dict[str, SlotBinding] = {}
    try:
        for name, value in last_context.parameters.items():
            _require_non_empty(name, "legacy parameter name")
            _require_non_empty(value, "legacy parameter value")
            slots[name] = SlotBinding(
                name=name,
                value=value,
                candidates=(value,),
                state="RESOLVED",
                provenance="INHERITED_LEGACY",
                source_turn_id=turn_id,
                source_span=None,
                issues=(),
            )
        for name in last_context.missing_parameters:
            _require_non_empty(name, "legacy missing parameter name")
            slots.setdefault(
                name,
                SlotBinding(
                    name=name,
                    value=None,
                    candidates=(),
                    state="CLEARED",
                    provenance="INHERITED_LEGACY",
                    source_turn_id=turn_id,
                    source_span=None,
                    issues=(),
                ),
            )
    except ValueError:
        return ConversationReadState(active_frame=None, pending_interaction=None, state_version=0)

    frame = ReadContextFrame(
        frame_id=f"legacy:{last_context.capability_id}:{turn_id}",
        capability_id=last_context.capability_id,
        slots=slots,
        status="STALE",
        created_turn_id=turn_id,
        updated_turn_id=turn_id,
        registry_snapshot_id=snapshot_id,
        capability_version="legacy",
    )
    return ConversationReadState(active_frame=frame, pending_interaction=None, state_version=0)


def _legacy_last_context(
    legacy: ConversationContext | Mapping[str, object],
) -> LastContext | None:
    if isinstance(legacy, ConversationContext):
        return legacy.last_context
    if not isinstance(legacy, Mapping):
        return None
    try:
        raw_last_context = legacy.get("lastContext")
        if not _is_strict_legacy_last_context(raw_last_context):
            return None
        return LastContext.from_dict(dict(raw_last_context))
    except (KeyError, TypeError, ValueError):
        return None


def _is_strict_legacy_last_context(payload: object) -> bool:
    if not isinstance(payload, Mapping):
        return False
    capability_id = payload.get("capabilityId")
    parameters = payload.get("parameters")
    missing_parameters = payload.get("missingParameters")
    decision_type = payload.get("decisionType")
    return (
        isinstance(capability_id, str)
        and bool(capability_id)
        and isinstance(parameters, Mapping)
        and all(
            isinstance(name, str) and isinstance(value, str)
            for name, value in parameters.items()
        )
        and isinstance(missing_parameters, list)
        and all(isinstance(name, str) for name in missing_parameters)
        and decision_type in {"SELECT", "CLARIFY"}
    )


def _require_non_empty(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a non-empty string")
    return value

"""Immutable, version-bound contracts for governed READ conversation state."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

FrameStatus = Literal["COLLECTING", "READY", "CONFLICTED", "STALE"]
SlotState = Literal["RESOLVED", "CONFLICTED", "CLEARED"]
SlotProvenance = Literal[
    "EXPLICIT", "CONFIRMED", "INHERITED", "MODEL_CANDIDATE", "INHERITED_LEGACY"
]
PendingKind = Literal[
    "SLOT_CLARIFICATION", "CAPABILITY_CHOICE", "BATCH_CONFIRMATION", "PLANNER_CONFIRMATION"
]

_FRAME_STATUSES = frozenset({"COLLECTING", "READY", "CONFLICTED", "STALE"})
_SLOT_STATES = frozenset({"RESOLVED", "CONFLICTED", "CLEARED"})
_SLOT_PROVENANCES = frozenset(
    {"EXPLICIT", "CONFIRMED", "INHERITED", "MODEL_CANDIDATE", "INHERITED_LEGACY"}
)
_PENDING_KINDS = frozenset(
    {"SLOT_CLARIFICATION", "CAPABILITY_CHOICE", "BATCH_CONFIRMATION", "PLANNER_CONFIRMATION"}
)


def _non_empty_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a non-empty string")
    return value


def _payload_mapping(payload: object, name: str) -> Mapping[str, object]:
    if not isinstance(payload, Mapping):
        raise ValueError(f"{name} must be a mapping")
    return payload


@dataclass(frozen=True)
class SlotBinding:
    name: str
    value: str | None
    candidates: tuple[str, ...]
    state: SlotState
    provenance: SlotProvenance
    source_turn_id: str
    source_span: tuple[int, int] | None
    issues: tuple[str, ...]

    def __post_init__(self) -> None:
        _non_empty_string(self.name, "SlotBinding.name")
        _non_empty_string(self.source_turn_id, "SlotBinding.source_turn_id")
        if self.state not in _SLOT_STATES:
            raise ValueError(f"SlotBinding.state is invalid: {self.state!r}")
        if self.provenance not in _SLOT_PROVENANCES:
            raise ValueError(f"SlotBinding.provenance is invalid: {self.provenance!r}")
        if self.value is not None and not isinstance(self.value, str):
            raise ValueError("SlotBinding.value must be a string or None")
        if self.state == "RESOLVED" and not self.value:
            raise ValueError("RESOLVED slot requires a value")
        if self.state == "CLEARED" and self.value is not None:
            raise ValueError("CLEARED slot cannot carry a value")

        candidates = _string_tuple(self.candidates, "SlotBinding.candidates")
        issues = _string_tuple(self.issues, "SlotBinding.issues")
        object.__setattr__(self, "candidates", candidates)
        object.__setattr__(self, "issues", issues)

        if self.source_span is not None:
            if (
                not isinstance(self.source_span, tuple)
                or len(self.source_span) != 2
                or not all(isinstance(part, int) for part in self.source_span)
                or self.source_span[0] < 0
                or self.source_span[0] > self.source_span[1]
            ):
                raise ValueError("SlotBinding.source_span must be an ordered pair of offsets")

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "value": self.value,
            "candidates": list(self.candidates),
            "state": self.state,
            "provenance": self.provenance,
            "sourceTurnId": self.source_turn_id,
            "sourceSpan": list(self.source_span) if self.source_span is not None else None,
            "issues": list(self.issues),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "SlotBinding":
        raw = _payload_mapping(payload, "SlotBinding payload")
        source_span = raw.get("sourceSpan")
        if source_span is not None:
            if not isinstance(source_span, list) or len(source_span) != 2:
                raise ValueError("SlotBinding.sourceSpan must be a two-item list or null")
            source_span = (source_span[0], source_span[1])
        return cls(
            name=_non_empty_string(raw.get("name"), "SlotBinding.name"),
            value=raw.get("value"),
            candidates=_string_tuple(raw.get("candidates", ()), "SlotBinding.candidates"),
            state=raw.get("state"),  # type: ignore[arg-type]
            provenance=raw.get("provenance"),  # type: ignore[arg-type]
            source_turn_id=_non_empty_string(raw.get("sourceTurnId"), "SlotBinding.sourceTurnId"),
            source_span=source_span,  # type: ignore[arg-type]
            issues=_string_tuple(raw.get("issues", ()), "SlotBinding.issues"),
        )


@dataclass(frozen=True)
class ReadContextFrame:
    frame_id: str
    capability_id: str
    slots: Mapping[str, SlotBinding]
    status: FrameStatus
    created_turn_id: str
    updated_turn_id: str
    registry_snapshot_id: str
    capability_version: str

    def __post_init__(self) -> None:
        for field in (
            "frame_id",
            "capability_id",
            "created_turn_id",
            "updated_turn_id",
            "registry_snapshot_id",
            "capability_version",
        ):
            _non_empty_string(getattr(self, field), f"ReadContextFrame.{field}")
        if self.status not in _FRAME_STATUSES:
            raise ValueError(f"ReadContextFrame.status is invalid: {self.status!r}")
        if not isinstance(self.slots, Mapping):
            raise ValueError("ReadContextFrame.slots must be a mapping")

        copied_slots: dict[str, SlotBinding] = {}
        for slot_name, slot in self.slots.items():
            _non_empty_string(slot_name, "ReadContextFrame slot key")
            if not isinstance(slot, SlotBinding):
                raise ValueError("ReadContextFrame slots must contain SlotBinding values")
            if slot_name != slot.name:
                raise ValueError("ReadContextFrame slot key must match SlotBinding.name")
            copied_slots[slot_name] = slot
        if self.status == "READY" and any(slot.state != "RESOLVED" for slot in copied_slots.values()):
            raise ValueError("READY frame requires all slots to be RESOLVED")
        object.__setattr__(self, "slots", MappingProxyType(copied_slots))

    def to_dict(self) -> dict[str, object]:
        return {
            "frameId": self.frame_id,
            "capabilityId": self.capability_id,
            "slots": {name: slot.to_dict() for name, slot in self.slots.items()},
            "status": self.status,
            "createdTurnId": self.created_turn_id,
            "updatedTurnId": self.updated_turn_id,
            "registrySnapshotId": self.registry_snapshot_id,
            "capabilityVersion": self.capability_version,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "ReadContextFrame":
        raw = _payload_mapping(payload, "ReadContextFrame payload")
        raw_slots = _payload_mapping(raw.get("slots"), "ReadContextFrame.slots")
        return cls(
            frame_id=_non_empty_string(raw.get("frameId"), "ReadContextFrame.frameId"),
            capability_id=_non_empty_string(
                raw.get("capabilityId"), "ReadContextFrame.capabilityId"
            ),
            slots={
                _non_empty_string(name, "ReadContextFrame slot key"): SlotBinding.from_dict(slot)
                for name, slot in raw_slots.items()
            },
            status=raw.get("status"),  # type: ignore[arg-type]
            created_turn_id=_non_empty_string(
                raw.get("createdTurnId"), "ReadContextFrame.createdTurnId"
            ),
            updated_turn_id=_non_empty_string(
                raw.get("updatedTurnId"), "ReadContextFrame.updatedTurnId"
            ),
            registry_snapshot_id=_non_empty_string(
                raw.get("registrySnapshotId"), "ReadContextFrame.registrySnapshotId"
            ),
            capability_version=_non_empty_string(
                raw.get("capabilityVersion"), "ReadContextFrame.capabilityVersion"
            ),
        )


@dataclass(frozen=True)
class PendingInteraction:
    kind: PendingKind
    frame_id: str
    expected_fields: tuple[str, ...]
    state_version: int
    registry_snapshot_id: str
    expires_at: str

    def __post_init__(self) -> None:
        if self.kind not in _PENDING_KINDS:
            raise ValueError(f"PendingInteraction.kind is invalid: {self.kind!r}")
        _non_empty_string(self.frame_id, "PendingInteraction.frame_id")
        _non_empty_string(self.registry_snapshot_id, "PendingInteraction.registry_snapshot_id")
        _non_empty_string(self.expires_at, "PendingInteraction.expires_at")
        if not isinstance(self.state_version, int) or isinstance(self.state_version, bool) or self.state_version < 0:
            raise ValueError("PendingInteraction.state_version must be a non-negative integer")
        fields = _string_tuple(self.expected_fields, "PendingInteraction.expected_fields")
        if len(set(fields)) != len(fields):
            raise ValueError("PendingInteraction.expected_fields must not contain duplicates")
        object.__setattr__(self, "expected_fields", fields)

    @property
    def binding_key(self) -> tuple[str, int, str]:
        return (self.frame_id, self.state_version, self.registry_snapshot_id)

    @classmethod
    def slot_clarification(
        cls,
        *,
        frame_id: str,
        expected_fields: tuple[str, ...],
        state_version: int,
        registry_snapshot_id: str,
        expires_at: str,
    ) -> "PendingInteraction":
        fields = _string_tuple(expected_fields, "PendingInteraction.expected_fields")
        if not fields:
            raise ValueError("SLOT_CLARIFICATION requires at least one expected field")
        return cls(
            kind="SLOT_CLARIFICATION",
            frame_id=frame_id,
            expected_fields=fields,
            state_version=state_version,
            registry_snapshot_id=registry_snapshot_id,
            expires_at=expires_at,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "frameId": self.frame_id,
            "expectedFields": list(self.expected_fields),
            "stateVersion": self.state_version,
            "registrySnapshotId": self.registry_snapshot_id,
            "expiresAt": self.expires_at,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "PendingInteraction":
        raw = _payload_mapping(payload, "PendingInteraction payload")
        return cls(
            kind=raw.get("kind"),  # type: ignore[arg-type]
            frame_id=_non_empty_string(raw.get("frameId"), "PendingInteraction.frameId"),
            expected_fields=_string_tuple(
                raw.get("expectedFields", ()), "PendingInteraction.expectedFields"
            ),
            state_version=raw.get("stateVersion"),  # type: ignore[arg-type]
            registry_snapshot_id=_non_empty_string(
                raw.get("registrySnapshotId"), "PendingInteraction.registrySnapshotId"
            ),
            expires_at=_non_empty_string(raw.get("expiresAt"), "PendingInteraction.expiresAt"),
        )


@dataclass(frozen=True)
class ConversationReadState:
    active_frame: ReadContextFrame | None
    pending_interaction: PendingInteraction | None
    state_version: int
    recent_frames: tuple[ReadContextFrame, ...] = ()

    def __post_init__(self) -> None:
        if self.active_frame is not None and not isinstance(self.active_frame, ReadContextFrame):
            raise ValueError("ConversationReadState.active_frame must be a ReadContextFrame or None")
        if self.pending_interaction is not None and not isinstance(
            self.pending_interaction, PendingInteraction
        ):
            raise ValueError(
                "ConversationReadState.pending_interaction must be a PendingInteraction or None"
            )
        if not isinstance(self.state_version, int) or isinstance(self.state_version, bool) or self.state_version < 0:
            raise ValueError("ConversationReadState.state_version must be a non-negative integer")
        if isinstance(self.recent_frames, (str, bytes)) or not isinstance(
            self.recent_frames, (tuple, list)
        ):
            raise ValueError("ConversationReadState.recent_frames must be a list or tuple")
        recent_frames = tuple(self.recent_frames)
        if len(recent_frames) > 2:
            raise ValueError("ConversationReadState.recent_frames must contain at most two frames")
        if not all(isinstance(frame, ReadContextFrame) for frame in recent_frames):
            raise ValueError("ConversationReadState.recent_frames must contain ReadContextFrame values")
        object.__setattr__(self, "recent_frames", recent_frames)

    def to_dict(self) -> dict[str, object]:
        return {
            "activeFrame": self.active_frame.to_dict() if self.active_frame else None,
            "pendingInteraction": self.pending_interaction.to_dict() if self.pending_interaction else None,
            "stateVersion": self.state_version,
            "recentFrames": [frame.to_dict() for frame in self.recent_frames],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "ConversationReadState":
        raw = _payload_mapping(payload, "ConversationReadState payload")
        active_frame = raw.get("activeFrame")
        pending = raw.get("pendingInteraction")
        recent_frames = raw.get("recentFrames", ())
        if not isinstance(recent_frames, (list, tuple)):
            raise ValueError("ConversationReadState.recentFrames must be a list")
        return cls(
            active_frame=ReadContextFrame.from_dict(active_frame)
            if isinstance(active_frame, Mapping)
            else None,
            pending_interaction=PendingInteraction.from_dict(pending)
            if isinstance(pending, Mapping)
            else None,
            state_version=raw.get("stateVersion", 0),  # type: ignore[arg-type]
            recent_frames=tuple(ReadContextFrame.from_dict(frame) for frame in recent_frames),
        )


def _string_tuple(value: object, field: str) -> tuple[str, ...]:
    if isinstance(value, str) or not isinstance(value, (tuple, list)):
        raise ValueError(f"{field} must be a list or tuple of strings")
    values = tuple(value)
    if not all(isinstance(item, str) for item in values):
        raise ValueError(f"{field} must contain only strings")
    return values

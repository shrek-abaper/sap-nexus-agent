"""ConversationContext data model for multi-turn conversational agent.

Frozen dataclasses representing the agent's conversational state:
- LastContext: the last capability decision (CLARIFY missing params / SELECT among candidates)
- Turn: a single user or assistant utterance
- ConversationContext: last_context + recent history (last ~3 turns)
- PendingShowOptions / PendingEscalate: Runbook 14 cross-turn continuation
  state for SHOW_OPTIONS / ESCALATE_TO_PLANNER (advisory only, no execution
  authority).

All three are JSON round-trippable via to_dict() / from_dict() for transparent
pass-through across LLM calls. The context field defaults to None so existing
callers can adopt it with zero changes.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Type-only import: avoids a circular import at runtime
    # (conversation_context -> match_decision -> capability_selector).
    from sap_nexus_agent.match_decision import EscalationHandoff, MatchedIntent
    from sap_nexus_agent.call_plan import CallPlan
    from sap_nexus_agent.read_context import ConversationReadState


@dataclass(frozen=True)
class LastContext:
    """The last capability decision context.

    decision_type is "CLARIFY" (missing required parameters) or "SELECT"
    (choose among candidate capabilities).
    """

    capability_id: str
    parameters: dict[str, str]
    missing_parameters: list[str]
    decision_type: str  # "CLARIFY" | "SELECT"

    def to_dict(self) -> dict[str, object]:
        return {
            "capabilityId": self.capability_id,
            "parameters": dict(self.parameters),
            "missingParameters": list(self.missing_parameters),
            "decisionType": self.decision_type,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "LastContext":
        return cls(
            capability_id=str(payload["capabilityId"]),
            parameters={str(k): str(v) for k, v in dict(payload.get("parameters") or {}).items()},
            missing_parameters=[str(x) for x in (payload.get("missingParameters") or [])],
            decision_type=str(payload["decisionType"]),
        )


@dataclass(frozen=True)
class Turn:
    """A single conversation turn. role is "user" or "assistant"."""

    role: str  # "user" | "assistant"
    content: str

    def to_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "Turn":
        return cls(role=str(payload["role"]), content=str(payload["content"]))


@dataclass(frozen=True)
class ConversationContext:
    """Conversational state passed to the LLM.

    last_context defaults to None for backward compatibility (existing
    callers pass no context). history is a tuple of the most recent turns
    (target: last 3 turns); None means no history.

    Runbook 14 adds two advisory pending fields:

    - ``pending_show_options``: written by SHOW_OPTIONS on turn N so turn
      N+1 can resolve a selection without re-running recall/rerank.
    - ``pending_escalate``: written by ESCALATE_TO_PLANNER on turn N so
      turn N+1 can confirm continuation to the planner dry-run.

    Both are advisory only: MUST NOT influence CallPlan / ApprovalRecord
    lifecycle. Mutual exclusivity is enforced by ``with_pending_show_options``
    / ``with_pending_escalate`` / ``clear_pending``.
    """

    last_context: LastContext | None
    history: tuple[Turn, ...] | None
    pending_show_options: "PendingShowOptions | None" = None
    pending_escalate: "PendingEscalate | None" = None
    read_state: "ConversationReadState | None" = None
    schema_version: int | None = None

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "lastContext": self.last_context.to_dict() if self.last_context else None,
            "history": [t.to_dict() for t in self.history] if self.history else None,
            "pendingShowOptions": (
                self.pending_show_options.to_dict() if self.pending_show_options else None
            ),
            "pendingEscalate": (
                self.pending_escalate.to_dict() if self.pending_escalate else None
            ),
        }
        if self.read_state is not None:
            payload["readState"] = self.read_state.to_dict()
        if self.schema_version is not None:
            payload["schemaVersion"] = self.schema_version
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "ConversationContext":
        last_raw = payload.get("lastContext")
        last_context = LastContext.from_dict(last_raw) if isinstance(last_raw, dict) else None
        history_raw = payload.get("history")
        history = (
            tuple(Turn.from_dict(item) for item in history_raw)
            if isinstance(history_raw, list)
            else None
        )
        pso_raw = payload.get("pendingShowOptions")
        pending_show_options = (
            PendingShowOptions.from_dict(pso_raw) if isinstance(pso_raw, dict) else None
        )
        pe_raw = payload.get("pendingEscalate")
        pending_escalate = (
            PendingEscalate.from_dict(pe_raw) if isinstance(pe_raw, dict) else None
        )
        read_state_raw = payload.get("readState")
        read_state = None
        if isinstance(read_state_raw, dict):
            from sap_nexus_agent.read_context import ConversationReadState

            read_state = ConversationReadState.from_dict(read_state_raw)
        schema_version_raw = payload.get("schemaVersion")
        schema_version = schema_version_raw if isinstance(schema_version_raw, int) else None
        return cls(
            last_context=last_context,
            history=history,
            pending_show_options=pending_show_options,
            pending_escalate=pending_escalate,
            read_state=read_state,
            schema_version=schema_version,
        )

    def with_pending_show_options(
        self, pending: "PendingShowOptions | None"
    ) -> "ConversationContext":
        """Write SHOW_OPTIONS pending; clear pending_escalate (mutual exclusivity)."""
        return dataclasses.replace(
            self, pending_show_options=pending, pending_escalate=None
        )

    def with_pending_escalate(
        self, pending: "PendingEscalate | None"
    ) -> "ConversationContext":
        """Write ESCALATE pending; clear pending_show_options (mutual exclusivity)."""
        return dataclasses.replace(
            self, pending_show_options=None, pending_escalate=pending
        )

    def clear_pending(self) -> "ConversationContext":
        """Clear all pending states."""
        return dataclasses.replace(
            self, pending_show_options=None, pending_escalate=None
        )


@dataclass(frozen=True)
class ReadExecutionBinding:
    """Server-owned identity binding for one persisted READY READ plan."""

    turn_id: str
    frame_id: str
    state_version: int
    registry_snapshot_id: str
    principal_id: str
    capability_version: str
    executor_binding_id: str
    call_plan_hash: str
    read_state: "ConversationReadState"

    def __post_init__(self) -> None:
        for field in (
            "turn_id", "frame_id", "registry_snapshot_id", "principal_id",
            "capability_version", "executor_binding_id", "call_plan_hash",
        ):
            value = getattr(self, field)
            if not isinstance(value, str) or not value:
                raise ValueError(f"ReadExecutionBinding.{field} must be non-empty")
        if not isinstance(self.state_version, int) or isinstance(self.state_version, bool) or self.state_version < 0:
            raise ValueError("ReadExecutionBinding.state_version must be non-negative")

    @classmethod
    def create(
        cls,
        *,
        turn_id: str,
        principal_id: str,
        call_plan: "CallPlan",
        read_state: "ConversationReadState",
        executor_binding_id: str,
    ) -> "ReadExecutionBinding":
        frame = read_state.active_frame
        if frame is None:
            raise ValueError("READ execution binding requires an active frame")
        return cls(
            turn_id=turn_id,
            frame_id=frame.frame_id,
            state_version=read_state.state_version,
            registry_snapshot_id=frame.registry_snapshot_id,
            principal_id=principal_id,
            capability_version=frame.capability_version,
            executor_binding_id=executor_binding_id,
            call_plan_hash=cls.hash_call_plan(call_plan),
            read_state=read_state,
        )

    @staticmethod
    def hash_call_plan(call_plan: "CallPlan") -> str:
        encoded = json.dumps(
            call_plan.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def validates(
        self,
        call_plan: "CallPlan",
        persisted_state: "ConversationReadState | None" = None,
    ) -> bool:
        frame = self.read_state.active_frame
        return bool(
            self.turn_id
            and self.principal_id
            and frame is not None
            and frame.status == "READY"
            and frame.updated_turn_id == self.turn_id
            and frame.frame_id == self.frame_id
            and frame.registry_snapshot_id == self.registry_snapshot_id
            and frame.capability_version == self.capability_version
            and self.executor_binding_id
            and self.read_state.state_version == self.state_version
            and self.read_state.pending_interaction is None
            and (persisted_state is None or persisted_state == self.read_state)
            and call_plan.kind == "Function"
            and not call_plan.requires_approval
            and call_plan.capability_id == frame.capability_id
            and self.hash_call_plan(call_plan) == self.call_plan_hash
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "turnId": self.turn_id,
            "frameId": self.frame_id,
            "stateVersion": self.state_version,
            "registrySnapshotId": self.registry_snapshot_id,
            "principalId": self.principal_id,
            "capabilityVersion": self.capability_version,
            "executorBindingId": self.executor_binding_id,
            "callPlanHash": self.call_plan_hash,
            "readState": self.read_state.to_dict(),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "ReadExecutionBinding":
        from sap_nexus_agent.read_context import ConversationReadState

        expected = {
            "turnId", "frameId", "stateVersion", "registrySnapshotId", "principalId",
            "capabilityVersion", "executorBindingId", "callPlanHash", "readState",
        }
        if set(payload) != expected:
            raise ValueError("ReadExecutionBinding contains unsupported fields")
        read_state = payload.get("readState")
        if not isinstance(read_state, dict):
            raise ValueError("ReadExecutionBinding.readState must be an object")
        return cls(
            turn_id=str(payload["turnId"]),
            frame_id=str(payload["frameId"]),
            state_version=int(payload["stateVersion"]),
            registry_snapshot_id=str(payload["registrySnapshotId"]),
            principal_id=str(payload["principalId"]),
            capability_version=str(payload["capabilityVersion"]),
            executor_binding_id=str(payload["executorBindingId"]),
            call_plan_hash=str(payload["callPlanHash"]),
            read_state=ConversationReadState.from_dict(read_state),
        )


@dataclass(frozen=True)
class SelectionExecutionBinding:
    """Server-owned binding for a parsed non-READ selection continuation."""

    turn_id: str
    state_version: int
    registry_snapshot_id: str
    principal_id: str
    capability_id: str
    capability_version: str
    executor_binding_id: str
    call_plan_hash: str

    def __post_init__(self) -> None:
        for field in (
            "turn_id", "registry_snapshot_id", "principal_id", "capability_id",
            "capability_version", "executor_binding_id", "call_plan_hash",
        ):
            value = getattr(self, field)
            if not isinstance(value, str) or not value:
                raise ValueError(f"SelectionExecutionBinding.{field} must be non-empty")
        if not isinstance(self.state_version, int) or isinstance(self.state_version, bool) or self.state_version < 0:
            raise ValueError("SelectionExecutionBinding.state_version must be non-negative")

    @classmethod
    def create(
        cls,
        *,
        turn_id: str,
        state_version: int,
        registry_snapshot_id: str,
        principal_id: str,
        capability_version: str,
        executor_binding_id: str,
        call_plan: "CallPlan",
    ) -> "SelectionExecutionBinding":
        return cls(
            turn_id=turn_id,
            state_version=state_version,
            registry_snapshot_id=registry_snapshot_id,
            principal_id=principal_id,
            capability_id=call_plan.capability_id,
            capability_version=capability_version,
            executor_binding_id=executor_binding_id,
            call_plan_hash=ReadExecutionBinding.hash_call_plan(call_plan),
        )

    def validates(self, call_plan: "CallPlan") -> bool:
        return bool(
            self.turn_id
            and self.principal_id
            and self.capability_id == call_plan.capability_id
            and self.executor_binding_id
            and call_plan.kind == "Action"
            and call_plan.requires_approval
            and ReadExecutionBinding.hash_call_plan(call_plan) == self.call_plan_hash
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "turnId": self.turn_id,
            "stateVersion": self.state_version,
            "registrySnapshotId": self.registry_snapshot_id,
            "principalId": self.principal_id,
            "capabilityId": self.capability_id,
            "capabilityVersion": self.capability_version,
            "executorBindingId": self.executor_binding_id,
            "callPlanHash": self.call_plan_hash,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "SelectionExecutionBinding":
        expected = {
            "turnId", "stateVersion", "registrySnapshotId", "principalId",
            "capabilityId", "capabilityVersion", "executorBindingId", "callPlanHash",
        }
        if set(payload) != expected:
            raise ValueError("SelectionExecutionBinding contains unsupported fields")
        return cls(
            turn_id=str(payload["turnId"]),
            state_version=int(payload["stateVersion"]),
            registry_snapshot_id=str(payload["registrySnapshotId"]),
            principal_id=str(payload["principalId"]),
            capability_id=str(payload["capabilityId"]),
            capability_version=str(payload["capabilityVersion"]),
            executor_binding_id=str(payload["executorBindingId"]),
            call_plan_hash=str(payload["callPlanHash"]),
        )


@dataclass(frozen=True)
class PendingShowOptions:
    """Advisory cross-turn state for SHOW_OPTIONS (Runbook 14).

    Carries the candidate ``MatchedIntent`` objects shown to the user on turn
    N so turn N+1 can resolve a selection without re-running recall/rerank.
    Advisory only: MUST NOT influence CallPlan / ApprovalRecord lifecycle.
    """

    candidates: "tuple[MatchedIntent, ...]"
    snapshot_id: str

    def to_dict(self) -> dict[str, object]:
        return {
            "candidates": [
                {
                    "capabilityId": c.capability_id,
                    "parameters": dict(c.parameters),
                    "missing": list(c.missing),
                }
                for c in self.candidates
            ],
            "snapshotId": self.snapshot_id,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "PendingShowOptions":
        from sap_nexus_agent.match_decision import MatchedIntent

        raw = payload.get("candidates") or []
        candidates = tuple(
            MatchedIntent(
                capability_id=str(item["capabilityId"]),
                parameters={str(k): str(v) for k, v in dict(item.get("parameters") or {}).items()},
                missing=[str(x) for x in (item.get("missing") or [])],
            )
            for item in raw
            if isinstance(item, dict)
        )
        return cls(
            candidates=candidates,
            snapshot_id=str(payload["snapshotId"]),
        )


@dataclass(frozen=True)
class PendingEscalate:
    """Advisory cross-turn state for ESCALATE_TO_PLANNER (Runbook 14).

    Carries the EscalationHandoff from turn N so turn N+1 can confirm
    continuation to the planner (dry-run only). Advisory only: MUST NOT
    influence CallPlan / ApprovalRecord lifecycle.
    """

    handoff: "EscalationHandoff"
    snapshot_id: str

    def to_dict(self) -> dict[str, object]:
        return {
            "handoff": {
                "reason": self.handoff.reason,
                "matchedIntents": [
                    {
                        "capabilityId": mi.capability_id,
                        "parameters": dict(mi.parameters),
                        "missing": list(mi.missing),
                    }
                    for mi in self.handoff.matched_intents
                ],
                "utterance": self.handoff.utterance,
                "registrySnapshotId": self.handoff.registry_snapshot_id,
            },
            "snapshotId": self.snapshot_id,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "PendingEscalate":
        from sap_nexus_agent.match_decision import EscalationHandoff, MatchedIntent

        handoff_raw = payload.get("handoff")
        if not isinstance(handoff_raw, dict):
            raise ValueError("PendingEscalate.from_dict: handoff must be a dict")
        matched_raw = handoff_raw.get("matchedIntents") or []
        matched_intents = [
            MatchedIntent(
                capability_id=str(mi["capabilityId"]),
                parameters={str(k): str(v) for k, v in dict(mi.get("parameters") or {}).items()},
                missing=[str(x) for x in (mi.get("missing") or [])],
            )
            for mi in matched_raw
            if isinstance(mi, dict)
        ]
        handoff = EscalationHandoff(
            reason=str(handoff_raw["reason"]),
            matched_intents=matched_intents,
            utterance=str(handoff_raw["utterance"]),
            registry_snapshot_id=str(handoff_raw["registrySnapshotId"]),
        )
        return cls(handoff=handoff, snapshot_id=str(payload["snapshotId"]))

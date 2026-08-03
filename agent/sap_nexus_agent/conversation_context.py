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

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Type-only import: avoids a circular import at runtime
    # (conversation_context -> match_decision -> capability_selector).
    from sap_nexus_agent.match_decision import EscalationHandoff


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
    """

    last_context: LastContext | None
    history: tuple[Turn, ...] | None

    def to_dict(self) -> dict[str, object]:
        return {
            "lastContext": self.last_context.to_dict() if self.last_context else None,
            "history": [t.to_dict() for t in self.history] if self.history else None,
        }

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
        return cls(last_context=last_context, history=history)


@dataclass(frozen=True)
class PendingShowOptions:
    """Advisory cross-turn state for SHOW_OPTIONS (Runbook 14).

    Carries the candidate capability_ids shown to the user on turn N so turn
    N+1 can resolve a selection without re-running recall/rerank. Advisory
    only: MUST NOT influence CallPlan / ApprovalRecord lifecycle.
    """

    candidates: list[str]
    snapshot_id: str

    def to_dict(self) -> dict[str, object]:
        return {
            "candidates": list(self.candidates),
            "snapshotId": self.snapshot_id,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "PendingShowOptions":
        return cls(
            candidates=[str(x) for x in (payload.get("candidates") or [])],
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

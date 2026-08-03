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
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Type-only import: avoids a circular import at runtime
    # (conversation_context -> match_decision -> capability_selector).
    from sap_nexus_agent.match_decision import EscalationHandoff, MatchedIntent


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

    def to_dict(self) -> dict[str, object]:
        return {
            "lastContext": self.last_context.to_dict() if self.last_context else None,
            "history": [t.to_dict() for t in self.history] if self.history else None,
            "pendingShowOptions": (
                self.pending_show_options.to_dict() if self.pending_show_options else None
            ),
            "pendingEscalate": (
                self.pending_escalate.to_dict() if self.pending_escalate else None
            ),
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
        pso_raw = payload.get("pendingShowOptions")
        pending_show_options = (
            PendingShowOptions.from_dict(pso_raw) if isinstance(pso_raw, dict) else None
        )
        pe_raw = payload.get("pendingEscalate")
        pending_escalate = (
            PendingEscalate.from_dict(pe_raw) if isinstance(pe_raw, dict) else None
        )
        return cls(
            last_context=last_context,
            history=history,
            pending_show_options=pending_show_options,
            pending_escalate=pending_escalate,
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

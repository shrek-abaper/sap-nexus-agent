"""ConversationContext data model for multi-turn conversational agent.

Frozen dataclasses representing the agent's conversational state:
- LastContext: the last capability decision (CLARIFY missing params / SELECT among candidates)
- Turn: a single user or assistant utterance
- ConversationContext: last_context + recent history (last ~3 turns)

All three are JSON round-trippable via to_dict() / from_dict() for transparent
pass-through across LLM calls. The context field defaults to None so existing
callers can adopt it with zero changes.
"""

from __future__ import annotations

from dataclasses import dataclass


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

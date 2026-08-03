"""Versioned IntentEnvelope data structure (Runbook 14).

Replaces the flat ``IntentParseResult`` as the LLM-first intent carrier.
``IntentEnvelope`` is an immutable (frozen) dataclass carrying goals,
constraints, ambiguities, evidence, snapshot_id, and discard_reasons so every
``MatchDecision`` can be replayed to its source LLM output and registry
snapshot.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class IntentGoal:
    """One user goal extracted by the LLM or rule path.

    ``capability_hint`` / ``parameters`` / ``missing`` are advisory: the
    selector validates them against the closed set and required inputs.
    """

    goal_text: str
    capability_hint: str | None
    parameters: dict[str, str]
    missing: list[str]


@dataclass(frozen=True)
class IntentEnvelope:
    """Versioned LLM-first intent carrier.

    Replaces ``IntentParseResult``. Carries enough context for decision
    replay: original utterance, goals, model evidence, snapshot_id, and
    discard_reasons (audit trail for filtered LLM output).

    ``goals`` / ``user_constraints`` / ``ambiguities`` / ``discard_reasons``
    are tuples/lists so the envelope stays hashable and immutable.
    ``model_evidence`` is a dict summary of the LLM payload (empty for the
    rule fallback path).
    """

    envelope_id: str
    utterance: str
    goals: tuple[IntentGoal, ...]
    user_constraints: dict[str, str]
    ambiguities: list[str]
    reference_turn_id: str | None
    model_evidence: dict[str, object]
    snapshot_id: str
    discard_reasons: list[str]
    created_by: Literal["llm", "rule"]

"""Versioned IntentEnvelope data structure (Runbook 14).

Replaces the flat ``IntentParseResult`` as the LLM-first intent carrier.
``IntentEnvelope`` is an immutable (frozen) dataclass carrying goals,
constraints, ambiguities, evidence, snapshot_id, and discard_reasons so every
``MatchDecision`` can be replayed to its source LLM output and registry
snapshot.
"""

from __future__ import annotations

from dataclasses import dataclass


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

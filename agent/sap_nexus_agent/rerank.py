"""Bounded rerank stage (Runbook 14).

Heuristic scoring of recall candidates (no embedding / RAG). Outputs
``ranked_candidates`` (sorted desc by score) and ``rerank_evidence``
(per-candidate score breakdown). Advisory only: does NOT produce a
MatchDecision.

Scoring:
- LLM ``capability_hint`` match: +3
- lexical match (name/description): +2
- alias match: +2
- example match: +1
- parameter fit (all required inputs covered): +1

Tie-break: ``capability_id`` alphabetical order (stable, deterministic).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sap_nexus_agent.intent_envelope import IntentEnvelope
    from sap_nexus_agent.registry_loader import IntentCatalog


@dataclass(frozen=True)
class RerankCandidate:
    """One candidate's rerank result (capability_id + score + components)."""

    capability_id: str
    score: int
    components: dict[str, int]


def rerank(
    candidates: list[str],
    envelope: "IntentEnvelope",
    catalog: "IntentCatalog",
) -> tuple[list[str], list[dict[str, object]]]:
    """Score and sort recall candidates by heuristic.

    Args:
        candidates: capability_ids from the recall stage.
        envelope: Source IntentEnvelope (provides utterance + goals with
            capability_hint and parameters).
        catalog: IntentCatalog for descriptor lookups (name/description,
            aliases, examples, required inputs).

    Returns:
        Tuple of (ranked_candidates, rerank_evidence). ``ranked_candidates``
        is a list[str] sorted desc by score (ties broken by capability_id
        alphabetical). ``rerank_evidence`` is a list[dict] with per-candidate
        ``capabilityId``, ``score``, and ``components``.
    """
    if not candidates:
        return [], []

    text = envelope.utterance.lower()
    # Collect all LLM hint capability_ids from goals (advisory).
    hint_ids = {
        goal.capability_hint.lower()
        for goal in envelope.goals
        if goal.capability_hint
    }
    # Build a map of capability_id -> parameters from goals (first match wins).
    goal_params: dict[str, dict[str, str]] = {}
    for goal in envelope.goals:
        if goal.capability_hint and goal.capability_hint not in goal_params:
            goal_params[goal.capability_hint] = dict(goal.parameters)

    scored: list[RerankCandidate] = []
    for cap_id in candidates:
        descriptor = catalog.find(cap_id)
        if descriptor is None:
            # Unknown capability — skip (shouldn't happen post-recall filter).
            continue

        components: dict[str, int] = {}
        # LLM hint match (+3).
        if cap_id.lower() in hint_ids:
            components["llm_hint"] = 3
        # Lexical match (+2): utterance overlaps name/description.
        name_desc = f"{descriptor.name} {descriptor.description}".lower()
        if _text_overlaps(text, name_desc):
            components["lexical"] = 2
        # Alias match (+2).
        elif any(alias.lower() in text for alias in descriptor.aliases):
            components["alias"] = 2
        # Example match (+1).
        elif any(ex.lower() in text or text in ex.lower() for ex in descriptor.examples):
            components["example"] = 1

        # Parameter fit (+1): all required inputs covered by goal params.
        params = goal_params.get(cap_id, {})
        required_inputs = {inp.name for inp in descriptor.inputs if inp.required}
        if required_inputs and required_inputs.issubset(params.keys()):
            components["param_fit"] = 1

        score = sum(components.values())
        scored.append(RerankCandidate(capability_id=cap_id, score=score, components=components))

    # Sort: desc by score, then asc by capability_id (stable tie-break).
    scored.sort(key=lambda c: (-c.score, c.capability_id))

    ranked = [c.capability_id for c in scored]
    evidence = [
        {
            "capabilityId": c.capability_id,
            "score": c.score,
            "components": dict(c.components),
        }
        for c in scored
    ]
    return ranked, evidence


def _text_overlaps(text: str, haystack: str) -> bool:
    """Return True if ``text`` and ``haystack`` share any keyword overlap.

    Mirrors ``recall._text_overlaps`` so rerank's lexical check is consistent
    with recall's lexical source.
    """
    if not text:
        return False
    for token in text.split():
        if token and token in haystack:
            return True
    if text in haystack:
        return True
    for token in haystack.split():
        if len(token) >= 2 and token in text:
            return True
    return False

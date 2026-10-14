"""Goal-first resolver: desired facts -> visible READ producers.

Unlike compile_plan_v2 (which starts from already-matched intents), the
resolver starts from the facts the question needs and only then chooses
capabilities. Outcomes are deterministic: clarify, capability gap,
semantic gap, or resolved.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from sap_nexus_agent.planner.capability_card import CapabilityCard, discover_cards


@dataclass(frozen=True)
class DesiredFact:
    fact_type_id: str
    fields: tuple[str, ...]
    producer_capability_id: str
    selectors: tuple[Mapping[str, str], ...]


@dataclass(frozen=True)
class Resolution:
    status: str
    desired: tuple[DesiredFact, ...]
    producers: Mapping[str, str]
    clarification: tuple[str, ...]
    gaps: tuple[str, ...]
    candidates: Mapping[str, tuple[str, ...]]
    closure: tuple[Any, ...] = ()


def _visible_read_cards(
    cards: list[CapabilityCard], sources: Any
) -> list[CapabilityCard]:
    raw = {
        item["capabilityId"]: item
        for item in sources.capabilities.get("capabilities", [])
    }
    visible: list[CapabilityCard] = []
    for card in cards:
        definition = raw.get(card.capability_id, {})
        if definition.get("kind") != "Function":
            continue
        governance = card.governance
        if governance.requires_approval or governance.side_effect != "none":
            continue
        visible.append(card)
    return visible


def _producers_by_fact(
    cards: list[CapabilityCard],
) -> Mapping[str, tuple[CapabilityCard, ...]]:
    index: dict[str, list[CapabilityCard]] = defaultdict(list)
    for card in cards:
        for fact_type in card.produces_fact_types:
            index[fact_type].append(card)
    for producers in index.values():
        producers.sort(key=lambda card: card.capability_id)
    return {fact_type: tuple(producers) for fact_type, producers in index.items()}


def resolve(
    draft: Any,
    pinned: Any,
    sources: Any,
    snapshot: Any,
    graph: Any,
    principal: Mapping[str, Any],
) -> Resolution:
    cards = discover_cards(snapshot, sources)
    visible = _visible_read_cards(cards, sources)
    producers_by_fact = _producers_by_fact(visible)

    gaps: list[str] = []
    clarification: list[str] = []
    candidates: dict[str, tuple[str, ...]] = {}
    desired: list[DesiredFact] = []
    producers: dict[str, str] = {}

    ambiguous = set()

    for requested in draft.requested_facts:
        fact_type = requested.fact_type_id
        producers_for_fact = producers_by_fact.get(fact_type, ())

        if len(producers_for_fact) == 0:
            gaps.append(f"NO_PRODUCER:{fact_type}")
            continue
        if len(producers_for_fact) > 1:
            candidate_ids = tuple(c.capability_id for c in producers_for_fact)
            candidates[fact_type] = candidate_ids
            ambiguous.add(fact_type)
            clarification.append(
                f"AMBIGUOUS_PRODUCER:{fact_type} candidates={list(candidate_ids)}"
            )
            continue

        card = producers_for_fact[0]
        allowed_fields = pinned.allowlist_fields.get(fact_type, frozenset())
        illegal = tuple(field for field in requested.fields if field not in allowed_fields)
        if illegal:
            for field_name in illegal:
                gaps.append(
                    f"FIELD_NOT_ALLOWLISTED:{fact_type}.{field_name}"
                )
            continue

        missing = _missing_required_values(requested, draft, card)
        if missing:
            for name in missing:
                clarification.append(f"MISSING_SELECTOR_VALUE:{name}")
            continue

        selectors = tuple(
            {"objectTypeId": s.object_type_id, "key": s.key, "value": s.value}
            for s in requested.selectors
        )
        desired.append(
            DesiredFact(
                fact_type_id=fact_type,
                fields=tuple(requested.fields),
                producer_capability_id=card.capability_id,
                selectors=selectors,
            )
        )
        producers[fact_type] = card.capability_id

    status = _overall_status(gaps, clarification)
    return Resolution(
        status=status,
        desired=tuple(desired),
        producers=dict(sorted(producers.items())),
        clarification=tuple(clarification),
        gaps=tuple(gaps),
        candidates=dict(sorted(candidates.items())),
    )


def _missing_required_values(requested: Any, draft: Any, card: CapabilityCard) -> tuple[str, ...]:
    supplied: dict[str, str] = {s.key: s.value for s in requested.selectors}
    for constraint in draft.constraints:
        supplied.setdefault(constraint.name, constraint.value)
    missing: list[str] = []
    for descriptor in card.inputs:
        if not descriptor.required or descriptor.binding_kind != "identifier":
            continue
        if descriptor.satisfiable_by_fact_type:
            # Derived inputs are handled by the closure step (Task 6).
            continue
        if descriptor.name not in supplied:
            missing.append(descriptor.name)
    return tuple(missing)


def _overall_status(gaps: list[str], clarification: list[str]) -> str:
    if any(g.startswith("NO_PRODUCER") for g in gaps):
        return "capability_gap"
    if any(g.startswith("FIELD_NOT_ALLOWLISTED") for g in gaps):
        return "semantic_gap"
    if clarification:
        return "clarification"
    return "complete"

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
from sap_nexus_agent.semantic_planning.derivation import derive_data_dependencies


@dataclass(frozen=True)
class DesiredFact:
    fact_type_id: str
    fields: tuple[str, ...]
    producer_capability_id: str
    selectors: tuple[Mapping[str, str], ...]


@dataclass(frozen=True, order=True)
class ClosureBinding:
    consumer_capability_id: str
    consumer_input_name: str
    producer_capability_id: str
    fact_type_id: str
    fact_field_name: str


@dataclass(frozen=True)
class Resolution:
    status: str
    desired: tuple[DesiredFact, ...]
    producers: Mapping[str, str]
    clarification: tuple[str, ...]
    gaps: tuple[str, ...]
    candidates: Mapping[str, tuple[str, ...]]
    closure: tuple[ClosureBinding, ...] = ()
    closure_capabilities: tuple[str, ...] = ()


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

    closure_bindings, auto_pulled, closure_clarification = _close_inputs(
        sources, visible, desired, producers_by_fact, producers, supplied_map(draft)
    )
    clarification.extend(closure_clarification)

    status = _overall_status(gaps, clarification)
    return Resolution(
        status=status,
        desired=tuple(desired),
        producers=dict(sorted(producers.items())),
        clarification=tuple(clarification),
        gaps=tuple(gaps),
        candidates=dict(sorted(candidates.items())),
        closure=tuple(sorted(closure_bindings)),
        closure_capabilities=tuple(sorted(auto_pulled)),
    )


def supplied_map(draft: Any) -> dict[str, str]:
    supplied: dict[str, str] = {}
    for fact in draft.requested_facts:
        for selector in fact.selectors:
            supplied.setdefault(selector.key, selector.value)
    for constraint in draft.constraints:
        supplied.setdefault(constraint.name, constraint.value)
    return supplied


def _fact_field_cardinality(sources: Any, fact_type: str, field_name: str) -> str:
    for fact in sources.fact_types.get("factTypes", []):
        if fact.get("factTypeId") != fact_type:
            continue
        for field in fact.get("fields", []):
            if field.get("name") == field_name:
                return str(field.get("cardinality", "one"))
    return "one"


def _close_inputs(
    sources: Any,
    visible: list[CapabilityCard],
    desired: list[DesiredFact],
    producers_by_fact: Mapping[str, tuple[CapabilityCard, ...]],
    producers: dict[str, str],
    supplied: dict[str, str],
) -> tuple[set[ClosureBinding], set[str], list[str]]:
    view = derive_data_dependencies(sources)
    cards_by_id = {card.capability_id: card for card in visible}
    bindings: set[ClosureBinding] = set()
    auto_pulled: set[str] = set()
    clarification: list[str] = []

    planned = {fact.producer_capability_id for fact in desired}
    # Deriver diagnostics on planned consumers (e.g. many-cardinality fields
    # requiring a reduction the planner must not choose) stay unbound.
    for diagnostic in view.diagnostics:
        if diagnostic.consumer_capability_id not in planned:
            continue
        if diagnostic.kind == "needsReduction":
            clarification.append(
                f"NEEDS_REDUCTION:{diagnostic.fact_type_id}."
                f"{diagnostic.consumer_input_name} "
                f"for {diagnostic.consumer_capability_id}"
            )

    worklist = list(planned)
    while worklist:
        consumer_id = worklist.pop()
        consumer = cards_by_id.get(consumer_id)
        if consumer is None:
            continue
        for edge in view.edges:
            if edge.consumer_capability_id != consumer_id:
                continue
            descriptor = next(
                (i for i in consumer.inputs if i.name == edge.consumer_input_name),
                None,
            )
            if descriptor is None or not descriptor.required:
                continue
            if edge.consumer_input_name in supplied:
                continue  # user/context value wins; no derived binding
            cardinality = _fact_field_cardinality(
                sources, edge.fact_type_id, edge.fact_field_name
            )
            if cardinality == "many":
                clarification.append(
                    f"NEEDS_REDUCTION:{edge.fact_type_id}.{edge.fact_field_name} "
                    f"for {consumer_id}.{edge.consumer_input_name}"
                )
                continue
            producer_cards = producers_by_fact.get(edge.fact_type_id, ())
            if len(producer_cards) != 1:
                clarification.append(
                    f"MISSING_SELECTOR_VALUE:{edge.consumer_input_name}"
                )
                continue
            producer_id = producer_cards[0].capability_id
            bindings.add(
                ClosureBinding(
                    consumer_capability_id=consumer_id,
                    consumer_input_name=edge.consumer_input_name,
                    producer_capability_id=producer_id,
                    fact_type_id=edge.fact_type_id,
                    fact_field_name=edge.fact_field_name,
                )
            )
            if producer_id not in planned:
                auto_pulled.add(producer_id)
                planned.add(producer_id)
                worklist.append(producer_id)
    return bindings, auto_pulled, clarification


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

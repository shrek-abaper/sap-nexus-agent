"""S2-B handoff wiring: MatchDecision.ESCALATE_TO_PLANNER -> DryRunResult.

Connects the S2-A ``MatchDecision`` (Task 1) to the S2-B ``PlanCompiler``
(Task 8) by:

1. Discovering ``CapabilityCard``s from the registry snapshot + sources.
2. Building a ``GoalSpec`` from the handoff - ``desiredFactTypes`` from
   ``CapabilityCard.produces_fact_types`` (reuses Task 7's
   ``build_goal_spec``) and ``constraints`` derived from
   ``handoff.matched_intents`` parameters cross-referenced with
   ``CapabilityCard.inputs`` (identifier inputs only).
3. Calling ``PlanCompiler.compile_dry_run`` to produce a ``DryRunResult``.

Deterministic: no LLM, no Gateway/SAP. The orchestrator calls this
helper in the ``ESCALATE_TO_PLANNER`` branch (Design Doc §"总体数据流").

Design Doc: docs/superpowers/specs/2026-07-25-sap-nexus-planner-dry-run-design.md
section "总体数据流".
"""

from __future__ import annotations

from sap_nexus_agent.match_decision import EscalationHandoff
from sap_nexus_agent.planner.capability_card import CapabilityCard, discover_cards
from sap_nexus_agent.planner.goal_spec import GoalConstraint, GoalSpec, build_goal_spec
from sap_nexus_agent.planner.plan_compiler import DryRunResult, compile_dry_run
from sap_nexus_agent.semantic_planning import (
    RegistrySnapshot,
    SemanticSourceDocuments,
)

# Only identifier inputs become goal constraints. ``literal`` sources
# (utterance extraction) and ``factField`` sources (fact wiring) are
# not authored here - the PlanCompiler records them as missing_parameter
# gaps if required (Task 8 behaviour).
_IDENTIFIER_BINDING_KIND = "identifier"


def compile_dry_run_from_handoff(
    handoff: EscalationHandoff,
    snapshot: RegistrySnapshot,
    sources: SemanticSourceDocuments,
) -> DryRunResult:
    """Compile a deterministic dry-run plan from an escalation handoff.

    Reuses ``build_goal_spec`` (Task 7) for ``desiredFactTypes`` derivation
    and ``PlanCompiler.compile_dry_run`` (Task 8) for the validated
    ``PlanGraph``. The handoff's matched-intent parameters are projected
    into ``GoalConstraint``s so the PlanCompiler can bind identifier
    inputs via ``goalConstraint`` sources (rather than recording them as
    ``missing_parameter`` gaps).
    """
    cards = discover_cards(snapshot, sources)
    goal = _build_goal_with_constraints(handoff, cards)
    return compile_dry_run(goal, snapshot, sources)


def _build_goal_with_constraints(
    handoff: EscalationHandoff,
    cards: list[CapabilityCard],
) -> GoalSpec:
    """Build a ``GoalSpec`` with constraints derived from matched intents.

    ``desiredFactTypes`` / ``goal_id`` / ``goal_type`` / ``execution_mode``
    come from ``build_goal_spec`` (Task 7). ``constraints`` are derived
    from ``handoff.matched_intents``: each parameter is matched to a
    ``CapabilityCard.InputDescriptor`` by name; identifier inputs become
    ``GoalConstraint``s with the ``semantic_type`` from the input
    descriptor so the PlanCompiler can bind them via ``goalConstraint``
    source kind. Parameters on non-identifier inputs are skipped (the
    dry-run does not author ``literal`` / ``factField`` sources).
    """
    goal = build_goal_spec(handoff, cards)
    cards_by_id = {c.capability_id: c for c in cards}
    constraints: list[GoalConstraint] = []
    seen: set[tuple[str, str]] = set()
    for matched in handoff.matched_intents:
        card = cards_by_id.get(matched.capability_id)
        if card is None:
            continue
        inputs_by_name = {inp.name: inp for inp in card.inputs}
        for param_name, param_value in matched.parameters.items():
            inp = inputs_by_name.get(param_name)
            if inp is None or inp.binding_kind != _IDENTIFIER_BINDING_KIND:
                continue
            key = (param_name, inp.semantic_type)
            if key in seen:
                continue
            seen.add(key)
            constraints.append(
                GoalConstraint(
                    name=param_name,
                    semantic_type=inp.semantic_type,
                    value=param_value,
                )
            )
    return GoalSpec(
        goal_id=goal.goal_id,
        goal_type=goal.goal_type,
        desired_fact_types=goal.desired_fact_types,
        execution_mode=goal.execution_mode,
        goal_spec_version=goal.goal_spec_version,
        constraints=tuple(constraints),
    )

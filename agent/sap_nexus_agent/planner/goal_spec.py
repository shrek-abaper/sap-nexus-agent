"""GoalSpec v1 for the planner (S2-B, Plan Task 7).

S1 ``semantic-planning-foundation`` defines ``GoalSpec v1`` only as a
dict/JSON-schema shape (validated in
``semantic_planning.validation.validate_goal_spec``). This module lands
a Python dataclass mirror so the planner can construct goals
programmatically from ``EscalationHandoff``.

Schema (per ``schemas/goal-spec.schema.json``):
- ``goalSpecVersion``: int (const 1)
- ``goalId``: str (non-empty)
- ``goalType``: str (non-empty)
- ``executionMode``: ``"PLAN_ONLY"`` | ``"READ_ONLY"``
- ``desiredFactTypes``: list[str] (unique, non-empty)
- ``constraints``: list[``GoalConstraint``]

For the dry-run planner, ``executionMode`` defaults to ``PLAN_ONLY``:
the planner is not authorised to execute or approve; it only drafts an
advisory plan.

Design Doc: docs/superpowers/specs/2026-07-25-sap-nexus-planner-dry-run-design.md
section "GoalSpec / PlanDraft".
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from sap_nexus_agent.match_decision import EscalationHandoff

from .capability_card import CapabilityCard

ExecutionMode = str  # "PLAN_ONLY" | "READ_ONLY"


@dataclass(frozen=True)
class GoalConstraint:
    """Typed scalar constraint on a goal (mirrors S1 JSON schema)."""

    name: str
    semantic_type: str
    value: str | int | float | bool


@dataclass(frozen=True)
class GoalSpec:
    """GoalSpec v1 dataclass mirror of the S1 JSON schema.

    ``execution_mode`` defaults to ``"PLAN_ONLY"`` because the dry-run
    planner does not authorise execution or approval. Callers that need
    ``READ_ONLY`` semantics pass it explicitly.
    """

    goal_id: str
    goal_type: str
    desired_fact_types: tuple[str, ...]
    execution_mode: ExecutionMode = "PLAN_ONLY"
    goal_spec_version: int = 1
    constraints: tuple[GoalConstraint, ...] = ()

    def to_dict(self) -> dict[str, object]:
        """Emit a dict in the S1 JSON-schema (camelCase) shape.

        The result is suitable for feeding into S1's
        ``validate_goal_spec`` in Task 8 (``PlanCompiler``).
        """
        return {
            "goalSpecVersion": self.goal_spec_version,
            "goalId": self.goal_id,
            "goalType": self.goal_type,
            "executionMode": self.execution_mode,
            "desiredFactTypes": list(self.desired_fact_types),
            "constraints": [
                {
                    "name": c.name,
                    "semanticType": c.semantic_type,
                    "value": c.value,
                }
                for c in self.constraints
            ],
        }


def build_goal_spec(
    handoff: EscalationHandoff,
    cards: list[CapabilityCard],
) -> GoalSpec:
    """Construct a ``GoalSpec`` from an escalation handoff.

    ``desired_fact_types`` is the de-duplicated union of
    ``CapabilityCard.produces_fact_types`` for each matched intent's
    capability, preserving first-seen order. Matched intents whose
    capability has no corresponding card contribute no fact types
    (no crash).

    T3 task 5.4: that union is then **closed** under the unbound required
    inputs that declare ``satisfiableByFactType``, so a producer the user
    never asked for is pulled in on the consumer's behalf. The closure lives
    here rather than in ``plan_compiler_v2._build_plan_graph_v2`` so the
    ``GoalSpec`` records *why* the extra node exists: the extra SAP read is
    auditable instead of being a silent planner side effect.

    ``execution_mode`` is always ``"PLAN_ONLY"``: the dry-run planner
    is advisory only and does not authorise execution.
    """
    cards_by_id = {c.capability_id: c for c in cards}
    seen: set[str] = set()
    desired: list[str] = []
    for matched in handoff.matched_intents:
        card = cards_by_id.get(matched.capability_id)
        if card is None:
            continue
        for fact_type in card.produces_fact_types:
            if fact_type in seen:
                continue
            seen.add(fact_type)
            desired.append(fact_type)

    bound_parameters: dict[str, object] = {}
    for matched in handoff.matched_intents:
        bound_parameters.update(matched.parameters)
    matched_cards = [
        cards_by_id[m.capability_id]
        for m in handoff.matched_intents
        if m.capability_id in cards_by_id
    ]
    desired.extend(
        _auto_pulled_fact_types(cards, matched_cards, bound_parameters, tuple(desired))
    )

    return GoalSpec(
        goal_id=_derive_goal_id(handoff),
        goal_type=_derive_goal_type(handoff, desired),
        desired_fact_types=tuple(desired),
        execution_mode="PLAN_ONLY",
    )


def _is_auto_pullable(card: CapabilityCard) -> bool:
    """Whether ``card`` may be pulled into the plan without the user asking.

    Invariant 5: auto-pull must not drag in a WRITE, and must not become a
    reason to skip or shorten Human Approval. The registry schema binds
    ``kind: Function`` to ``sideEffect: none`` + ``requiresApproval: false``,
    and ``CapabilityCard`` projects those two governance fields rather than
    the ``kind`` label, so the restriction is enforced on the fields that
    actually gate execution. Both are checked: a capability with a side
    effect is not a READ even if it forgot to demand approval.
    """
    return (
        card.governance.side_effect == "none"
        and not card.governance.requires_approval
    )


def _auto_pulled_fact_types(
    cards: Sequence[CapabilityCard],
    matched_cards: Sequence[CapabilityCard],
    bound_parameters: Mapping[str, object],
    desired: tuple[str, ...],
) -> tuple[str, ...]:
    """Close ``desired`` under unbound required inputs' ``satisfiableByFactType``.

    Restricted to producers that pass ``_is_auto_pullable``, so the closure
    structurally cannot put a WRITE or an approval-bearing capability into the
    plan (invariant 5).

    A parameter the user stated is *not* closed over (ruling ④, 用户明说优先):
    the value is already known, so the extra SAP read must not happen at all.
    Optional inputs are likewise skipped — an omission the plan may honour is
    not a gap worth a round trip.

    Returns only the **added** Fact Types, in discovery order. This is a real
    closure, not a single hop: a pulled producer's own unbound required inputs
    are closed too. Termination is by construction, because each Fact Type is
    added at most once and the worklist only grows through additions, so a
    producer cycle in the registry cannot loop.

    When several capabilities produce the same Fact Type the first pullable one
    in ``cards`` order wins. That is registry order, hence deterministic, but it
    is the same silently-picks-one shape as ``producers[0]`` elsewhere and is
    reported as such rather than presented as a choice.
    """
    added_set = set(desired)
    added: list[str] = []
    worklist = list(matched_cards)
    while worklist:
        card = worklist.pop(0)
        for inp in card.inputs:
            if not inp.required or not inp.satisfiable_by_fact_type:
                continue
            if inp.name in bound_parameters:
                continue
            fact_type = inp.satisfiable_by_fact_type
            if fact_type in added_set:
                continue
            producer = next(
                (
                    candidate
                    for candidate in cards
                    if fact_type in candidate.produces_fact_types
                    and _is_auto_pullable(candidate)
                ),
                None,
            )
            if producer is None:
                continue
            added_set.add(fact_type)
            added.append(fact_type)
            worklist.append(producer)
    return tuple(added)


def _derive_goal_id(handoff: EscalationHandoff) -> str:
    """Deterministic-ish goal id from the handoff.

    Anchored on ``registry_snapshot_id`` + matched capability ids so the
    same handoff yields the same goal id within a session (the snapshot
    id already commits to the registry contents).
    """
    cap_ids = ",".join(m.capability_id for m in handoff.matched_intents)
    return f"goal.dry-run.{handoff.registry_snapshot_id}:{cap_ids}"


def _derive_goal_type(handoff: EscalationHandoff, desired: list[str]) -> str:
    """Best-effort goal type label.

    With no ontology lookup available at this skeleton stage, the goal
    type is derived from the first desired fact type (the most specific
    signal available). Falls back to a generic planner label when no
    fact types are produced.
    """
    if desired:
        return f"sapnexus:GoalFor:{desired[0].rsplit(':', 1)[-1]}"
    return "sapnexus:PlannerDryRunGoal"

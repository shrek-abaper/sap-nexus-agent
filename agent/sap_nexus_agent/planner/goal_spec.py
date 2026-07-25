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

    return GoalSpec(
        goal_id=_derive_goal_id(handoff),
        goal_type=_derive_goal_type(handoff, desired),
        desired_fact_types=tuple(desired),
        execution_mode="PLAN_ONLY",
    )


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

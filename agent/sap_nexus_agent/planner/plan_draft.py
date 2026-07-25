"""Advisory PlanDraft for the planner (S2-B, Plan Task 7).

``PlanDraft`` is an advisory candidate capability composition. It is
NOT a ``PlanGraph`` and grants NO execution authority. ``PlanCompiler``
(Task 8) deterministically compiles a ``PlanDraft`` into a ``PlanGraph``
after running the S1 validators.

Design Doc: docs/superpowers/specs/2026-07-25-sap-nexus-planner-dry-run-design.md
section "GoalSpec / PlanDraft".
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PlanDraft:
    """Advisory capability composition candidate.

    Fields:
    - ``capability_ids``: ordered tuple of capability ids that the
      planner proposes to compose. Order is the proposed execution
      order; ``PlanCompiler`` will re-derive a topological order.
    - ``advisory``: always ``True`` for the dry-run planner. Surfaced
      as an explicit field so downstream code cannot mistake a draft
      for an authorised plan.
    - ``rationale``: short human-readable note (why this composition).
    """

    capability_ids: tuple[str, ...]
    advisory: bool = True
    rationale: str = ""

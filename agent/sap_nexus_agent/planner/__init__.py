"""S2-B planner module (dry-run capability composition).

Task 7 ships the module skeleton:
- ``CapabilityCard`` / ``Governance`` / ``InputDescriptor`` (migrated
  from ``visibility.py`` and extended with ``inputs``)
- ``discover_cards``: projection from ``SemanticSourceDocuments`` +
  ``RegistrySnapshot``
- ``GoalSpec`` v1 + ``build_goal_spec`` (from ``EscalationHandoff``)
- ``PlanDraft``: advisory capability composition candidate

Task 8 will add ``PlanCompiler`` / ``DryRunResult`` (deterministic
compilation of a ``PlanDraft`` into a validated ``PlanGraph``); they
are intentionally absent from this skeleton.

Design Doc: docs/superpowers/specs/2026-07-25-sap-nexus-planner-dry-run-design.md
section "S2-B 规划层".
"""

from __future__ import annotations

from .capability_card import (
    CapabilityCard,
    Governance,
    InputDescriptor,
    discover_cards,
)
from .goal_spec import GoalConstraint, GoalSpec, build_goal_spec
from .plan_draft import PlanDraft

__all__ = [
    "CapabilityCard",
    "GoalConstraint",
    "GoalSpec",
    "Governance",
    "InputDescriptor",
    "PlanDraft",
    "build_goal_spec",
    "discover_cards",
]

"""Visibility pre-filter for capability cards (S2-A, Plan Task 4).

Filters ``CapabilityCard`` sets by governance (``sideEffect`` /
``dataClassification``) so the execution layer never sees write capabilities
(S3 gate), while the dry-run / planner layer sees them with their
``requiresApproval`` marker surfaced.

Design Doc: docs/superpowers/specs/2026-07-25-sap-nexus-planner-dry-run-design.md
section "visibility pre-filter".

``CapabilityCard`` / ``Governance`` were migrated to
``planner.capability_card`` in Task 7 and are re-exported here for
backward compatibility. ``filter_visible`` stays in this module because
its responsibility (execution-layer gating) is orthogonal to the
planner's responsibility (capability composition).
"""

from __future__ import annotations

from sap_nexus_agent.planner.capability_card import (
    CapabilityCard,
    Governance,
    InputDescriptor,
    SideEffect,
    DataClassification,
    Visibility,
)

__all__ = [
    "CapabilityCard",
    "DataClassification",
    "Governance",
    "InputDescriptor",
    "SideEffect",
    "Visibility",
    "filter_visible",
]


def filter_visible(
    cards: list[CapabilityCard],
    *,
    for_execution: bool,
) -> list[CapabilityCard]:
    """Filter capability cards by visibility and governance.

    - ``for_execution=False`` (dry-run / planner): all non-HIDDEN cards are
      visible. Write capabilities (``sideEffect=sap_write``) remain in the
      set with their ``governance.requires_approval`` marker so the planner
      can surface the approval requirement.
    - ``for_execution=True`` (execution layer, S3 gate): only cards with
      ``sideEffect=none`` AND ``dataClassification=internal`` pass; write
      and restricted capabilities are filtered out.
    """
    if not for_execution:
        return [c for c in cards if c.visibility != "HIDDEN"]
    return [
        c
        for c in cards
        if c.visibility != "HIDDEN"
        and c.governance.side_effect == "none"
        and c.governance.data_classification == "internal"
    ]

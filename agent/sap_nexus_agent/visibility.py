"""Visibility pre-filter for capability cards (S2-A, Plan Task 4).

Filters ``CapabilityCard`` sets by governance (``sideEffect`` /
``dataClassification``) so the execution layer never sees write capabilities
(S3 gate), while the dry-run / planner layer sees them with their
``requiresApproval`` marker surfaced.

Design Doc: docs/superpowers/specs/2026-07-25-sap-nexus-planner-dry-run-design.md
section "visibility pre-filter".

``CapabilityCard`` is co-located here intentionally. Task 7 migrates it to
``planner/capability_card.py`` and extends it with ``inputs`` /
``InputDescriptor``. Keep this module self-contained so the migration is a
move + re-export.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

SideEffect = Literal["none", "sap_write"]
DataClassification = Literal["internal", "restricted"]
Visibility = Literal["VISIBLE_DRY_RUN", "VISIBLE_EXECUTION", "HIDDEN"]


@dataclass(frozen=True)
class Governance:
    """Capability governance projection consumed by the visibility filter.

    Mirrors the ``governance`` block of ``registry/capabilities.yaml``: only
    the three fields that drive S3 execution gating are projected here.
    """

    side_effect: SideEffect
    requires_approval: bool
    data_classification: DataClassification


@dataclass(frozen=True)
class CapabilityCard:
    """Read-only projection of a registry capability for the planner.

    Only the fields the visibility filter needs are defined here. Task 7
    migrates this dataclass to ``planner/capability_card.py`` and extends it
    with ``inputs: tuple[InputDescriptor, ...]``.
    """

    capability_id: str
    name: str
    governance: Governance
    visibility: Visibility = "VISIBLE_DRY_RUN"
    produces_fact_types: tuple[str, ...] = ()


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

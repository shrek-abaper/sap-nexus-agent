"""CapabilityCard projection for the planner (S2-B, Plan Task 7).

Migrates ``CapabilityCard`` / ``Governance`` out of ``visibility.py`` and
extends the dataclass with ``inputs: tuple[InputDescriptor, ...]`` plus
``produces_fact_types`` (sourced from ``outputs.factTypeRef`` per Design
Doc §Spec Patch 2).

``visibility.py`` re-exports ``CapabilityCard`` / ``Governance`` for
backward compatibility; ``filter_visible`` stays there.

``discover_cards`` projects ``SemanticSourceDocuments`` (the S1 source
bundle) + ``RegistrySnapshot`` into a closed set of ``CapabilityCard``
instances. It reads only - it does not mutate the registry or grant
execution authority.

Design Doc: docs/superpowers/specs/2026-07-25-sap-nexus-planner-dry-run-design.md
sections "S2-B 规划层", "CapabilityCard".
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

from sap_nexus_agent.semantic_planning import (
    RegistrySnapshot,
    SemanticSourceDocuments,
)

SideEffect = str  # "none" | "sap_write" (loose to pass through registry values)
DataClassification = str  # "internal" | "restricted"
Visibility = str  # "VISIBLE_DRY_RUN" | "VISIBLE_EXECUTION" | "HIDDEN"


@dataclass(frozen=True)
class InputDescriptor:
    """Planner-side projection of a capability input.

    Richer than ``registry_loader.InputDescriptor``: carries
    ``binding_kind`` (literal / fact / identifier pass-through) and
    ``satisfiable_by_fact_type`` so the planner can later match inputs
    against produced fact types (Task 8 ``PlanCompiler``).
    """

    name: str
    semantic_type: str
    required: bool
    binding_kind: str
    satisfiable_by_fact_type: str | None = None


@dataclass(frozen=True)
class Governance:
    """Capability governance projection consumed by the visibility filter.

    Mirrors the ``governance`` block of ``registry/capabilities.yaml``:
    only the three fields that drive S3 execution gating are projected.
    """

    side_effect: SideEffect
    requires_approval: bool
    data_classification: DataClassification


@dataclass(frozen=True)
class CapabilityCard:
    """Read-only projection of a registry capability for the planner.

    Fields:
    - ``capability_id`` / ``name``: identity.
    - ``inputs``: tuple of ``InputDescriptor`` (defaults to ``()`` so
      existing ``visibility.py`` callers that do not pass ``inputs``
      keep working during the migration).
    - ``governance``: drives S3 execution gating.
    - ``visibility``: default ``VISIBLE_DRY_RUN``; write capabilities
      remain ``VISIBLE_DRY_RUN`` (execution layer filtering happens in
      ``visibility.filter_visible``).
    - ``produces_fact_types``: sourced from ``outputs.factTypeRef``.
    """

    capability_id: str
    name: str
    governance: Governance
    visibility: Visibility = "VISIBLE_DRY_RUN"
    produces_fact_types: tuple[str, ...] = ()
    inputs: tuple[InputDescriptor, ...] = ()
    registry_snapshot_id: str = ""


# ---- projection ----


def _coerce_mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    return MappingProxyType({})


def _project_input(raw: Mapping[str, Any]) -> InputDescriptor | None:
    name = raw.get("name")
    if not isinstance(name, str) or not name:
        return None
    return InputDescriptor(
        name=name,
        semantic_type=str(raw.get("semanticType", raw.get("type", "string"))),
        required=bool(raw.get("required", False)),
        binding_kind=str(raw.get("bindingKind", "literal")),
        satisfiable_by_fact_type=(
            str(raw["satisfiableByFactType"])
            if raw.get("satisfiableByFactType")
            else None
        ),
    )


def _project_governance(raw: Mapping[str, Any]) -> Governance:
    return Governance(
        side_effect=str(raw.get("sideEffect", "none")),
        requires_approval=bool(raw.get("requiresApproval", False)),
        data_classification=str(raw.get("dataClassification", "internal")),
    )


def _project_produces_fact_types(raw_outputs: Any) -> tuple[str, ...]:
    if not isinstance(raw_outputs, (list, tuple)):
        return ()
    fact_types: list[str] = []
    for output in raw_outputs:
        if not isinstance(output, Mapping):
            continue
        ref = output.get("factTypeRef")
        if isinstance(ref, str) and ref:
            fact_types.append(ref)
    return tuple(fact_types)


def discover_cards(
    snapshot: RegistrySnapshot,
    sources: SemanticSourceDocuments,
) -> list[CapabilityCard]:
    """Project the closed set of active capabilities into ``CapabilityCard``.

    Iterates ``sources.capabilities["capabilities"]``; for each active
    capability projects:
    - ``inputs`` -> ``InputDescriptor`` (bindingKind, satisfiableByFactType)
    - ``governance`` -> ``Governance``
    - ``outputs[].factTypeRef`` -> ``produces_fact_types``
    - ``visibility`` defaults to ``VISIBLE_DRY_RUN`` (write capabilities
      stay visible to the dry-run / planner layer; the execution layer
      filter happens in ``visibility.filter_visible``).

    The ``snapshot`` argument is accepted for API symmetry with the S1
    contract and the upcoming ``PlanCompiler`` (Task 8); this function
    does not currently need to consult snapshot fields because
    ``SemanticSourceDocuments`` already carries the raw registry content.
    """
    capabilities_yaml = _coerce_mapping(sources.capabilities)
    raw_capabilities = capabilities_yaml.get("capabilities") or []
    if not isinstance(raw_capabilities, (list, tuple)):
        return []

    cards: list[CapabilityCard] = []
    for raw in raw_capabilities:
        if not isinstance(raw, Mapping):
            continue
        if raw.get("status") != "active":
            continue
        capability_id = raw.get("capabilityId")
        if not isinstance(capability_id, str) or not capability_id:
            continue
        raw_inputs = raw.get("inputs") or []
        inputs = tuple(
            projected
            for projected in (
                _project_input(inp)
                for inp in raw_inputs
                if isinstance(inp, Mapping)
            )
            if projected is not None
        )
        governance_raw = _coerce_mapping(raw.get("governance"))
        cards.append(
            CapabilityCard(
                capability_id=capability_id,
                name=str(raw.get("name", "")),
                inputs=inputs,
                governance=_project_governance(governance_raw),
                visibility="VISIBLE_DRY_RUN",
                produces_fact_types=_project_produces_fact_types(
                    raw.get("outputs")
                ),
                registry_snapshot_id=snapshot.snapshot_id,
            )
        )
    return cards

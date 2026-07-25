"""Unit tests for visibility pre-filter (S2-A, Plan Task 4).

Covers:
- CapabilityCard / Governance dataclass construction & defaults
- Visibility Literal accepts VISIBLE_DRY_RUN / VISIBLE_EXECUTION / HIDDEN
- filter_visible for_execution=False (dry-run / planner): keeps all
  non-HIDDEN cards; write capabilities remain visible with their
  governance.requires_approval marker
- filter_visible for_execution=True (execution layer, S3 gate): filters
  out sideEffect=sap_write and dataClassification=restricted
- visibility=HIDDEN filtered in both modes
- frozen dataclass immutability, order preservation, no input mutation

Design Doc: docs/superpowers/specs/2026-07-25-sap-nexus-planner-dry-run-design.md
section "visibility pre-filter".
"""

from __future__ import annotations

import dataclasses

import pytest

from sap_nexus_agent.visibility import (
    CapabilityCard,
    Governance,
    filter_visible,
)


def _read_card(capability_id: str = "MM.Inventory.GetAvailability") -> CapabilityCard:
    """sideEffect=none + dataClassification=internal, safe for execution."""
    return CapabilityCard(
        capability_id=capability_id,
        name="Inventory Availability",
        governance=Governance(
            side_effect="none",
            requires_approval=False,
            data_classification="internal",
        ),
        visibility="VISIBLE_EXECUTION",
        produces_fact_types=("InventoryAvailability",),
    )


def _write_card(capability_id: str = "MM.PR.CreateDraft") -> CapabilityCard:
    """sideEffect=sap_write, marked VISIBLE_DRY_RUN + requiresApproval."""
    return CapabilityCard(
        capability_id=capability_id,
        name="PR Create Draft",
        governance=Governance(
            side_effect="sap_write",
            requires_approval=True,
            data_classification="internal",
        ),
        visibility="VISIBLE_DRY_RUN",
        produces_fact_types=("PurchaseRequestDraft",),
    )


def _restricted_card(capability_id: str = "MM.CostCenter.GetList") -> CapabilityCard:
    """dataClassification=restricted, read but not execution-safe."""
    return CapabilityCard(
        capability_id=capability_id,
        name="Cost Center List",
        governance=Governance(
            side_effect="none",
            requires_approval=False,
            data_classification="restricted",
        ),
        visibility="VISIBLE_EXECUTION",
        produces_fact_types=("CostCenterList",),
    )


def _hidden_card(capability_id: str = "MM.Internal.Debug") -> CapabilityCard:
    return CapabilityCard(
        capability_id=capability_id,
        name="Debug",
        governance=Governance(
            side_effect="none",
            requires_approval=False,
            data_classification="internal",
        ),
        visibility="HIDDEN",
    )


# ---- dataclass construction & defaults ----


def test_governance_construction():
    g = Governance(
        side_effect="none",
        requires_approval=False,
        data_classification="internal",
    )
    assert g.side_effect == "none"
    assert g.requires_approval is False
    assert g.data_classification == "internal"


def test_capability_card_defaults():
    card = CapabilityCard(
        capability_id="X",
        name="X",
        governance=Governance(
            side_effect="none",
            requires_approval=False,
            data_classification="internal",
        ),
    )
    assert card.visibility == "VISIBLE_DRY_RUN"
    assert card.produces_fact_types == ()


def test_capability_card_construction_with_all_fields():
    card = _read_card()
    assert card.capability_id == "MM.Inventory.GetAvailability"
    assert card.name == "Inventory Availability"
    assert card.governance.side_effect == "none"
    assert card.governance.requires_approval is False
    assert card.governance.data_classification == "internal"
    assert card.visibility == "VISIBLE_EXECUTION"
    assert card.produces_fact_types == ("InventoryAvailability",)


def test_governance_is_frozen():
    g = Governance(
        side_effect="none",
        requires_approval=False,
        data_classification="internal",
    )
    assert dataclasses.is_dataclass(g)
    with pytest.raises(dataclasses.FrozenInstanceError):
        g.side_effect = "sap_write"  # type: ignore[misc]


def test_capability_card_is_frozen():
    card = _read_card()
    assert dataclasses.is_dataclass(card)
    with pytest.raises(dataclasses.FrozenInstanceError):
        card.capability_id = "mutated"  # type: ignore[misc]


def test_visibility_literal_accepts_three_states():
    for v in ("VISIBLE_DRY_RUN", "VISIBLE_EXECUTION", "HIDDEN"):
        card = CapabilityCard(
            capability_id="X",
            name="X",
            governance=Governance(
                side_effect="none",
                requires_approval=False,
                data_classification="internal",
            ),
            visibility=v,  # type: ignore[arg-type]
        )
        assert card.visibility == v


# ---- filter_visible: for_execution=False (dry-run / planner) ----


def test_filter_visible_dry_run_keeps_read_card():
    cards = [_read_card()]
    result = filter_visible(cards, for_execution=False)
    assert len(result) == 1
    assert result[0].capability_id == "MM.Inventory.GetAvailability"


def test_filter_visible_dry_run_keeps_write_card_with_governance_mark():
    """Write capabilities remain visible in dry-run; their
    governance.requires_approval flag is the marker the planner / UI must
    surface (not the filter's job to remove)."""
    cards = [_write_card()]
    result = filter_visible(cards, for_execution=False)
    assert len(result) == 1
    assert result[0].governance.side_effect == "sap_write"
    assert result[0].governance.requires_approval is True


def test_filter_visible_dry_run_keeps_restricted_card():
    cards = [_restricted_card()]
    result = filter_visible(cards, for_execution=False)
    assert len(result) == 1
    assert result[0].governance.data_classification == "restricted"


def test_filter_visible_dry_run_filters_hidden():
    cards = [_hidden_card()]
    result = filter_visible(cards, for_execution=False)
    assert result == []


def test_filter_visible_dry_run_mixed_set():
    cards = [_read_card(), _write_card(), _restricted_card(), _hidden_card()]
    result = filter_visible(cards, for_execution=False)
    assert [c.capability_id for c in result] == [
        "MM.Inventory.GetAvailability",
        "MM.PR.CreateDraft",
        "MM.CostCenter.GetList",
    ]


# ---- filter_visible: for_execution=True (execution layer, S3 gate) ----


def test_filter_visible_execution_keeps_read_card():
    cards = [_read_card()]
    result = filter_visible(cards, for_execution=True)
    assert len(result) == 1
    assert result[0].capability_id == "MM.Inventory.GetAvailability"


def test_filter_visible_execution_filters_write_card():
    """S3 execution gate: sideEffect=sap_write must NOT reach the executor."""
    cards = [_write_card()]
    result = filter_visible(cards, for_execution=True)
    assert result == []


def test_filter_visible_execution_filters_restricted_card():
    cards = [_restricted_card()]
    result = filter_visible(cards, for_execution=True)
    assert result == []


def test_filter_visible_execution_filters_hidden():
    cards = [_hidden_card()]
    result = filter_visible(cards, for_execution=True)
    assert result == []


def test_filter_visible_execution_mixed_set():
    cards = [_read_card(), _write_card(), _restricted_card(), _hidden_card()]
    result = filter_visible(cards, for_execution=True)
    assert [c.capability_id for c in result] == ["MM.Inventory.GetAvailability"]


# ---- edge cases ----


def test_filter_visible_empty_list_returns_empty():
    assert filter_visible([], for_execution=False) == []
    assert filter_visible([], for_execution=True) == []


def test_filter_visible_preserves_input_order():
    cards = [
        _read_card("A"),
        _read_card("B"),
        _read_card("C"),
    ]
    result = filter_visible(cards, for_execution=True)
    assert [c.capability_id for c in result] == ["A", "B", "C"]


def test_filter_visible_does_not_mutate_input():
    cards = [_read_card(), _write_card()]
    original = list(cards)
    _ = filter_visible(cards, for_execution=True)
    assert cards == original

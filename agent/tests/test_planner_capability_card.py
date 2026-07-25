"""Unit tests for planner module skeleton (S2-B, Plan Task 7).

Covers:
- ``planner.capability_card``: ``InputDescriptor`` / ``Governance`` /
  ``CapabilityCard`` dataclasses (migrated from ``visibility.py`` and
  extended with ``inputs``).
- ``discover_cards``: projection from ``SemanticSourceDocuments`` +
  ``RegistrySnapshot`` to ``list[CapabilityCard]`` with ``inputs`` from
  ``bindingKind`` + ``produces_fact_types`` from ``outputs.factTypeRef``.
- ``planner.goal_spec``: ``GoalSpec`` v1 dataclass per S1 schema
  (``goalSpecVersion`` / ``goalId`` / ``goalType`` / ``executionMode`` /
  ``desiredFactTypes`` / ``constraints``); ``build_goal_spec`` derives
  ``desiredFactTypes`` from ``EscalationHandoff.matched_intents`` +
  ``CapabilityCard.produces_fact_types``.
- ``planner.plan_draft``: advisory ``PlanDraft`` (``advisory=True``,
  no execution authority).
- ``planner`` package exports ``CapabilityCard`` / ``GoalSpec`` /
  ``PlanDraft`` (``PlanCompiler`` / ``DryRunResult`` land in Task 8).
- Backward compat: ``sap_nexus_agent.visibility`` re-exports the migrated
  ``CapabilityCard`` / ``Governance`` so existing callers (and
  ``test_visibility.py``) keep working.

Design Doc: docs/superpowers/specs/2026-07-25-sap-nexus-planner-dry-run-design.md
sections "S2-B 规划层", "CapabilityCard", "GoalSpec / PlanDraft".
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from sap_nexus_agent.match_decision import EscalationHandoff, MatchedIntent
from sap_nexus_agent.planner import CapabilityCard, GoalSpec, PlanDraft
from sap_nexus_agent.planner.capability_card import (
    Governance,
    InputDescriptor,
    discover_cards,
)
from sap_nexus_agent.planner.goal_spec import GoalConstraint, build_goal_spec
from sap_nexus_agent.semantic_planning import (
    RegistrySnapshot,
    SemanticSourceDocuments,
    build_registry_snapshot,
    load_semantic_sources,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


# ---- helpers ----


def _make_input(
    name: str = "material",
    semantic_type: str = "sapnexus:MaterialNumber",
    required: bool = True,
    binding_kind: str = "identifier",
    satisfiable_by_fact_type: str | None = None,
) -> InputDescriptor:
    return InputDescriptor(
        name=name,
        semantic_type=semantic_type,
        required=required,
        binding_kind=binding_kind,
        satisfiable_by_fact_type=satisfiable_by_fact_type,
    )


def _make_governance(
    side_effect: str = "none",
    requires_approval: bool = False,
    data_classification: str = "internal",
) -> Governance:
    return Governance(
        side_effect=side_effect,  # type: ignore[arg-type]
        requires_approval=requires_approval,
        data_classification=data_classification,  # type: ignore[arg-type]
    )


def _make_card(
    capability_id: str = "MM.Inventory.GetAvailability",
    name: str = "Inventory Availability",
    inputs: tuple[InputDescriptor, ...] = (),
    governance: Governance | None = None,
    visibility: str = "VISIBLE_DRY_RUN",
    produces_fact_types: tuple[str, ...] = ("sapnexus:InventoryAvailabilityFact",),
) -> CapabilityCard:
    return CapabilityCard(
        capability_id=capability_id,
        name=name,
        inputs=inputs,
        governance=governance or _make_governance(),
        visibility=visibility,  # type: ignore[arg-type]
        produces_fact_types=produces_fact_types,
    )


def _load_real_sources() -> SemanticSourceDocuments:
    return load_semantic_sources(REPO_ROOT)


def _load_real_snapshot() -> RegistrySnapshot:
    return build_registry_snapshot(_load_real_sources())


# ---- InputDescriptor ----


def test_input_descriptor_construction():
    inp = _make_input()
    assert inp.name == "material"
    assert inp.semantic_type == "sapnexus:MaterialNumber"
    assert inp.required is True
    assert inp.binding_kind == "identifier"
    assert inp.satisfiable_by_fact_type is None


def test_input_descriptor_defaults_satisfiable_none():
    inp = InputDescriptor(
        name="plant",
        semantic_type="sapnexus:Plant",
        required=True,
        binding_kind="identifier",
    )
    assert inp.satisfiable_by_fact_type is None


def test_input_descriptor_is_frozen():
    inp = _make_input()
    assert dataclasses.is_dataclass(inp)
    with pytest.raises(dataclasses.FrozenInstanceError):
        inp.name = "mutated"  # type: ignore[misc]


# ---- Governance (migrated to planner.capability_card) ----


def test_governance_construction_in_planner():
    g = _make_governance(side_effect="sap_write", requires_approval=True)
    assert g.side_effect == "sap_write"
    assert g.requires_approval is True
    assert g.data_classification == "internal"


def test_governance_is_frozen():
    g = _make_governance()
    with pytest.raises(dataclasses.FrozenInstanceError):
        g.side_effect = "sap_write"  # type: ignore[misc]


# ---- CapabilityCard (migrated + extended with inputs) ----


def test_capability_card_construction_with_inputs():
    inp = _make_input()
    card = _make_card(inputs=(inp,), produces_fact_types=("sapnexus:F1",))
    assert card.capability_id == "MM.Inventory.GetAvailability"
    assert card.name == "Inventory Availability"
    assert len(card.inputs) == 1
    assert card.inputs[0] is inp
    assert card.governance.side_effect == "none"
    assert card.visibility == "VISIBLE_DRY_RUN"
    assert card.produces_fact_types == ("sapnexus:F1",)


def test_capability_card_defaults_inputs_empty_tuple():
    """Backward compat: ``inputs`` defaults to ``()`` so existing
    ``visibility.py`` callers (which do not pass ``inputs``) keep working."""
    card = CapabilityCard(
        capability_id="X",
        name="X",
        governance=_make_governance(),
    )
    assert card.inputs == ()
    assert card.visibility == "VISIBLE_DRY_RUN"
    assert card.produces_fact_types == ()


def test_capability_card_is_frozen():
    card = _make_card()
    assert dataclasses.is_dataclass(card)
    with pytest.raises(dataclasses.FrozenInstanceError):
        card.capability_id = "mutated"  # type: ignore[misc]


def test_capability_card_inputs_is_tuple():
    inp = _make_input()
    card = _make_card(inputs=(inp,))
    assert isinstance(card.inputs, tuple)


# ---- discover_cards projection ----


def test_discover_cards_projects_all_active_capabilities():
    sources = _load_real_sources()
    snapshot = _load_real_snapshot()
    cards = discover_cards(snapshot, sources)
    ids = {c.capability_id for c in cards}
    assert ids == {
        "MM.Inventory.GetAvailability",
        "MM.PurchaseOrder.GetList",
        "MM.PR.CreateDraft",
    }


def test_discover_cards_projects_inputs_from_binding_kind():
    sources = _load_real_sources()
    snapshot = _load_real_snapshot()
    cards = discover_cards(snapshot, sources)
    inv = next(c for c in cards if c.capability_id == "MM.Inventory.GetAvailability")
    # yaml: material / plant / unit, all bindingKind: identifier
    assert len(inv.inputs) == 3
    assert {i.name for i in inv.inputs} == {"material", "plant", "unit"}
    for inp in inv.inputs:
        assert inp.binding_kind == "identifier"
        assert inp.required is True or inp.name == "unit"  # unit is optional
    # unit is required=False
    unit = next(i for i in inv.inputs if i.name == "unit")
    assert unit.required is False
    # material/plant required=True
    material = next(i for i in inv.inputs if i.name == "material")
    assert material.required is True
    assert material.semantic_type == "sapnexus:MaterialNumber"


def test_discover_cards_projects_produces_fact_types_from_outputs_fact_type_ref():
    """Design Doc §Spec Patch 2: ``producesFactTypes`` comes from
    ``outputs.factTypeRef``."""
    sources = _load_real_sources()
    snapshot = _load_real_snapshot()
    cards = discover_cards(snapshot, sources)
    by_id = {c.capability_id: c for c in cards}
    assert by_id["MM.Inventory.GetAvailability"].produces_fact_types == (
        "sapnexus:InventoryAvailabilityFact",
    )
    assert by_id["MM.PurchaseOrder.GetList"].produces_fact_types == (
        "sapnexus:PurchaseOrderSupplyFact",
    )
    assert by_id["MM.PR.CreateDraft"].produces_fact_types == (
        "sapnexus:PurchaseRequisitionCreatedFact",
    )


def test_discover_cards_projects_governance():
    sources = _load_real_sources()
    snapshot = _load_real_snapshot()
    cards = discover_cards(snapshot, sources)
    by_id = {c.capability_id: c for c in cards}
    # read capabilities: sideEffect=none, requiresApproval=false
    inv = by_id["MM.Inventory.GetAvailability"]
    assert inv.governance.side_effect == "none"
    assert inv.governance.requires_approval is False
    assert inv.governance.data_classification == "internal"
    # write capability: sideEffect=sap_write, requiresApproval=true
    pr = by_id["MM.PR.CreateDraft"]
    assert pr.governance.side_effect == "sap_write"
    assert pr.governance.requires_approval is True


def test_discover_cards_default_visibility_is_visible_dry_run():
    sources = _load_real_sources()
    snapshot = _load_real_snapshot()
    cards = discover_cards(snapshot, sources)
    for card in cards:
        assert card.visibility == "VISIBLE_DRY_RUN"


def test_discover_cards_does_not_mutate_sources():
    sources = _load_real_sources()
    snapshot = _load_real_snapshot()
    _ = discover_cards(snapshot, sources)
    # sources remain frozen mappings; just ensure call is repeatable
    cards_again = discover_cards(snapshot, sources)
    assert len(cards_again) == 3


def test_discover_cards_empty_sources_returns_empty():
    empty_sources = SemanticSourceDocuments(
        capabilities={"version": 1, "capabilities": []},
        executor_bindings={"version": 1, "bindings": []},
        fact_types={"version": 1, "factTypes": []},
        relations={"version": 1, "relations": []},
    )
    snapshot = build_registry_snapshot(empty_sources)
    cards = discover_cards(snapshot, empty_sources)
    assert cards == []


def test_discover_cards_skips_non_active_capabilities():
    """``status != active`` entries must not be projected."""
    sources = SemanticSourceDocuments(
        capabilities={
            "version": 2,
            "capabilities": [
                {
                    "capabilityId": "X.Active",
                    "name": "Active",
                    "status": "active",
                    "governance": {
                        "sideEffect": "none",
                        "requiresApproval": False,
                        "dataClassification": "internal",
                    },
                    "outputs": [],
                },
                {
                    "capabilityId": "Y.Inactive",
                    "name": "Inactive",
                    "status": "deprecated",
                    "governance": {
                        "sideEffect": "none",
                        "requiresApproval": False,
                        "dataClassification": "internal",
                    },
                    "outputs": [],
                },
            ],
        },
        executor_bindings={"version": 1, "bindings": []},
        fact_types={"version": 1, "factTypes": []},
        relations={"version": 1, "relations": []},
    )
    snapshot = build_registry_snapshot(sources)
    cards = discover_cards(snapshot, sources)
    assert {c.capability_id for c in cards} == {"X.Active"}


def test_discover_cards_capability_without_outputs_has_empty_produces_fact_types():
    sources = SemanticSourceDocuments(
        capabilities={
            "version": 2,
            "capabilities": [
                {
                    "capabilityId": "X.NoOutputs",
                    "name": "NoOutputs",
                    "status": "active",
                    "inputs": [],
                    "outputs": None,
                    "governance": {
                        "sideEffect": "none",
                        "requiresApproval": False,
                        "dataClassification": "internal",
                    },
                },
            ],
        },
        executor_bindings={"version": 1, "bindings": []},
        fact_types={"version": 1, "factTypes": []},
        relations={"version": 1, "relations": []},
    )
    snapshot = build_registry_snapshot(sources)
    cards = discover_cards(snapshot, sources)
    assert len(cards) == 1
    assert cards[0].produces_fact_types == ()
    assert cards[0].inputs == ()


# ---- GoalSpec ----


def test_goal_spec_construction_with_defaults():
    goal = GoalSpec(
        goal_id="goal.test-001",
        goal_type="sapnexus:MaterialSupplySnapshot",
        desired_fact_types=("sapnexus:InventoryAvailabilityFact",),
    )
    assert goal.goal_spec_version == 1
    assert goal.goal_id == "goal.test-001"
    assert goal.goal_type == "sapnexus:MaterialSupplySnapshot"
    assert goal.execution_mode == "PLAN_ONLY"  # dry-run default
    assert goal.desired_fact_types == ("sapnexus:InventoryAvailabilityFact",)
    assert goal.constraints == ()


def test_goal_spec_construction_with_constraints():
    goal = GoalSpec(
        goal_id="goal.test-002",
        goal_type="sapnexus:MaterialSupplySnapshot",
        desired_fact_types=(
            "sapnexus:InventoryAvailabilityFact",
            "sapnexus:PurchaseOrderSupplyFact",
        ),
        constraints=(
            GoalConstraint(
                name="material",
                semantic_type="sapnexus:MaterialNumber",
                value="DEMOA4B",
            ),
        ),
    )
    assert goal.goal_spec_version == 1
    assert len(goal.desired_fact_types) == 2
    assert goal.constraints[0].name == "material"
    assert goal.constraints[0].value == "DEMOA4B"


def test_goal_spec_is_frozen():
    goal = GoalSpec(
        goal_id="g",
        goal_type="t",
        desired_fact_types=("f",),
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        goal.goal_id = "mutated"  # type: ignore[misc]


def test_goal_spec_to_dict_matches_s1_schema_shape():
    """``to_dict`` should produce keys matching the S1 JSON schema
    (camelCase) so the result can be fed to S1 validators in Task 8."""
    goal = GoalSpec(
        goal_id="goal.material-supply.fixture-001",
        goal_type="sapnexus:MaterialSupplySnapshot",
        desired_fact_types=(
            "sapnexus:InventoryAvailabilityFact",
            "sapnexus:PurchaseOrderSupplyFact",
        ),
        constraints=(
            GoalConstraint(
                name="material",
                semantic_type="sapnexus:MaterialNumber",
                value="DEMOA4B",
            ),
        ),
    )
    d = goal.to_dict()
    assert d["goalSpecVersion"] == 1
    assert d["goalId"] == "goal.material-supply.fixture-001"
    assert d["goalType"] == "sapnexus:MaterialSupplySnapshot"
    assert d["executionMode"] == "PLAN_ONLY"
    assert d["desiredFactTypes"] == [
        "sapnexus:InventoryAvailabilityFact",
        "sapnexus:PurchaseOrderSupplyFact",
    ]
    assert d["constraints"] == [
        {
            "name": "material",
            "semanticType": "sapnexus:MaterialNumber",
            "value": "DEMOA4B",
        }
    ]


# ---- build_goal_spec ----


def test_build_goal_spec_derives_desired_fact_types_from_matched_intents():
    """``desiredFactTypes`` is the de-duplicated union of
    ``CapabilityCard.produces_fact_types`` for each matched intent's
    capability, preserving first-seen order."""
    handoff = EscalationHandoff(
        reason="multi-intent",
        matched_intents=[
            MatchedIntent(
                capability_id="MM.Inventory.GetAvailability",
                parameters={},
                missing=[],
            ),
            MatchedIntent(
                capability_id="MM.PurchaseOrder.GetList",
                parameters={},
                missing=[],
            ),
        ],
        utterance="show inventory and POs for material X at plant Y",
        registry_snapshot_id="sha256:abc",
    )
    cards = [
        _make_card(
            capability_id="MM.Inventory.GetAvailability",
            produces_fact_types=("sapnexus:InventoryAvailabilityFact",),
        ),
        _make_card(
            capability_id="MM.PurchaseOrder.GetList",
            produces_fact_types=("sapnexus:PurchaseOrderSupplyFact",),
        ),
    ]
    goal = build_goal_spec(handoff, cards)
    assert goal.execution_mode == "PLAN_ONLY"
    assert goal.desired_fact_types == (
        "sapnexus:InventoryAvailabilityFact",
        "sapnexus:PurchaseOrderSupplyFact",
    )


def test_build_goal_spec_dedupes_fact_types_preserving_order():
    """If two matched capabilities produce the same fact type, it appears
    only once, in first-seen order."""
    handoff = EscalationHandoff(
        reason="multi-intent",
        matched_intents=[
            MatchedIntent(
                capability_id="A", parameters={}, missing=[]
            ),
            MatchedIntent(
                capability_id="B", parameters={}, missing=[]
            ),
        ],
        utterance="u",
        registry_snapshot_id="sha256:x",
    )
    cards = [
        _make_card(
            capability_id="A",
            produces_fact_types=("sapnexus:SharedFact", "sapnexus:OnlyA"),
        ),
        _make_card(
            capability_id="B",
            produces_fact_types=("sapnexus:SharedFact", "sapnexus:OnlyB"),
        ),
    ]
    goal = build_goal_spec(handoff, cards)
    assert goal.desired_fact_types == (
        "sapnexus:SharedFact",
        "sapnexus:OnlyA",
        "sapnexus:OnlyB",
    )


def test_build_goal_spec_skips_matched_intents_without_card():
    """A matched intent whose capability_id has no corresponding card
    contributes no fact types (no crash)."""
    handoff = EscalationHandoff(
        reason="multi-intent",
        matched_intents=[
            MatchedIntent(
                capability_id="MM.Inventory.GetAvailability",
                parameters={},
                missing=[],
            ),
            MatchedIntent(
                capability_id="MM.Missing.Capability",
                parameters={},
                missing=[],
            ),
        ],
        utterance="u",
        registry_snapshot_id="sha256:x",
    )
    cards = [
        _make_card(
            capability_id="MM.Inventory.GetAvailability",
            produces_fact_types=("sapnexus:InventoryAvailabilityFact",),
        ),
    ]
    goal = build_goal_spec(handoff, cards)
    assert goal.desired_fact_types == ("sapnexus:InventoryAvailabilityFact",)


def test_build_goal_spec_empty_handoff_returns_empty_fact_types():
    handoff = EscalationHandoff(
        reason="empty",
        matched_intents=[],
        utterance="",
        registry_snapshot_id="sha256:x",
    )
    goal = build_goal_spec(handoff, [])
    assert goal.desired_fact_types == ()
    assert goal.execution_mode == "PLAN_ONLY"


def test_build_goal_spec_records_goal_id_and_type():
    handoff = EscalationHandoff(
        reason="r",
        matched_intents=[
            MatchedIntent(capability_id="A", parameters={}, missing=[])
        ],
        utterance="u",
        registry_snapshot_id="sha256:abc123",
    )
    cards = [_make_card(capability_id="A")]
    goal = build_goal_spec(handoff, cards)
    # goal_id is non-empty and stable-ish (deterministic from handoff)
    assert isinstance(goal.goal_id, str) and goal.goal_id
    # goal_type is non-empty
    assert isinstance(goal.goal_type, str) and goal.goal_type


# ---- PlanDraft ----


def test_plan_draft_construction_default_advisory_true():
    draft = PlanDraft(capability_ids=("A", "B"))
    assert draft.advisory is True
    assert draft.capability_ids == ("A", "B")


def test_plan_draft_is_frozen():
    draft = PlanDraft(capability_ids=("A",))
    assert dataclasses.is_dataclass(draft)
    with pytest.raises(dataclasses.FrozenInstanceError):
        draft.advisory = False  # type: ignore[misc]


def test_plan_draft_does_not_authorize_execution():
    """Advisory draft must not be confused with an execution plan."""
    draft = PlanDraft(capability_ids=("MM.PR.CreateDraft",))
    assert draft.advisory is True
    # No execution fields present
    field_names = {f.name for f in dataclasses.fields(draft)}
    assert "executor_binding" not in field_names
    assert "approved_by" not in field_names


# ---- planner package exports ----


def test_planner_package_exports_expected_symbols():
    """Task 7 ships CapabilityCard / GoalSpec / PlanDraft.
    PlanCompiler / DryRunResult land in Task 8."""
    import sap_nexus_agent.planner as planner

    assert hasattr(planner, "CapabilityCard")
    assert hasattr(planner, "GoalSpec")
    assert hasattr(planner, "PlanDraft")


# ---- backward compat: visibility.py re-exports migrated CapabilityCard ----


def test_visibility_module_re_exports_capability_card_and_governance():
    """``visibility.py`` must keep exporting ``CapabilityCard`` / ``Governance``
    after the migration so existing callers (test_visibility.py) work."""
    from sap_nexus_agent.visibility import (
        CapabilityCard as VisibilityCapabilityCard,
    )
    from sap_nexus_agent.visibility import (
        Governance as VisibilityGovernance,
    )
    from sap_nexus_agent.visibility import filter_visible

    assert VisibilityCapabilityCard is CapabilityCard
    assert VisibilityGovernance is Governance
    # filter_visible still works with the migrated dataclass
    card = _make_card(visibility="HIDDEN")
    assert filter_visible([card], for_execution=False) == []
    assert filter_visible([card], for_execution=True) == []

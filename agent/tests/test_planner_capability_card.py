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


# ---- Task 5: CapabilityCard.registry_snapshot_id + discover_cards binds snapshot ----


def test_capability_card_has_registry_snapshot_id_field():
    from sap_nexus_agent.planner.capability_card import CapabilityCard, Governance

    card = CapabilityCard(
        capability_id="X",
        name="X",
        governance=Governance(
            side_effect="none", requires_approval=False, data_classification="internal"
        ),
        registry_snapshot_id="sha256:snap-1",
    )
    assert card.registry_snapshot_id == "sha256:snap-1"


def test_capability_card_registry_snapshot_id_defaults_empty():
    from sap_nexus_agent.planner.capability_card import CapabilityCard, Governance

    card = CapabilityCard(
        capability_id="X",
        name="X",
        governance=Governance(
            side_effect="none", requires_approval=False, data_classification="internal"
        ),
    )
    assert card.registry_snapshot_id == ""


def test_discover_cards_binds_registry_snapshot_id():
    from sap_nexus_agent.planner.capability_card import discover_cards

    snapshot = _load_real_snapshot()
    sources = _load_real_sources()
    cards = discover_cards(snapshot, sources)
    assert len(cards) > 0
    for card in cards:
        assert card.registry_snapshot_id == snapshot.snapshot_id


# ---- Task 9: CapabilityCard safe projection negative test ----


def test_capability_card_does_not_leak_technical_bindings():
    """CapabilityCard must NOT contain rfcName, serviceUrl, credentialRef, rawSql, executorBinding."""
    import dataclasses
    from sap_nexus_agent.planner.capability_card import discover_cards

    snapshot = _load_real_snapshot()
    sources = _load_real_sources()
    cards = discover_cards(snapshot, sources)
    assert len(cards) > 0

    forbidden_fields = {
        "rfcName",
        "serviceUrl",
        "entitySet",
        "httpMethod",
        "headers",
        "credentialRef",
        "rawSql",
        "executorBinding",
        "executor",
    }
    for card in cards:
        field_names = {f.name for f in dataclasses.fields(card)}
        assert not (field_names & forbidden_fields), (
            f"CapabilityCard leaks technical field(s): {field_names & forbidden_fields}"
        )
        gov_fields = {f.name for f in dataclasses.fields(card.governance)}
        assert not (gov_fields & forbidden_fields), (
            f"Governance leaks technical field(s): {gov_fields & forbidden_fields}"
        )


def test_capability_card_only_exposes_semantic_fields():
    """CapabilityCard fields are limited to semantic projection."""
    import dataclasses
    from sap_nexus_agent.planner.capability_card import CapabilityCard

    expected_fields = {
        "capability_id",
        "name",
        "governance",
        "visibility",
        "produces_fact_types",
        "inputs",
        "registry_snapshot_id",
    }
    actual_fields = {f.name for f in dataclasses.fields(CapabilityCard)}
    assert actual_fields == expected_fields, (
        f"Unexpected CapabilityCard fields: {actual_fields - expected_fields}"
    )


# ---- Task 5.4: producer auto-pull as a closure over desired_fact_types ----
#
# Design Decision 16, ruling 3 (规划器自动拉入). The planner adds the producer of
# an unbound required input's ``satisfiableByFactType`` to ``desired_fact_types``,
# so ``plan_compiler_v2``'s node-creation loop materialises the upstream node
# without any change of its own.
#
# Invariant 5 is the load-bearing constraint here: auto-pull must never drag in a
# WRITE or shorten Human Approval, so the pull is restricted to READ producers.
# ``CapabilityCard`` does not project ``kind``, and the registry schema binds
# ``kind: Function`` => ``sideEffect: none`` + ``requiresApproval: false``, so the
# restriction is enforced on the governance fields that actually gate execution
# rather than on a label that only implies them.


def _consumer_needing_an_upstream_unit() -> tuple[EscalationHandoff, list[CapabilityCard]]:
    """A matched consumer whose required ``unit`` is unbound and declares
    ``satisfiableByFactType``, plus an unmatched READ producer of that Fact."""
    handoff = EscalationHandoff(
        reason="derived-parameter",
        matched_intents=[
            MatchedIntent(
                capability_id="MM.PR.CreateDraft",
                parameters={"material": "M-1001", "plant": "1010"},
                missing=[],
            ),
        ],
        utterance="给物料 M-1001 在工厂 1010 建一张采购申请",
        registry_snapshot_id="sha256:abc",
    )
    consumer = _make_card(
        capability_id="MM.PR.CreateDraft",
        inputs=(
            _make_input(name="material"),
            _make_input(name="plant", semantic_type="sapnexus:Plant"),
            _make_input(
                name="unit",
                semantic_type="sapnexus:BaseUnitOfMeasure",
                satisfiable_by_fact_type="sapnexus:MaterialInfoFact",
            ),
        ),
        governance=_make_governance(side_effect="create", requires_approval=True),
        produces_fact_types=("sapnexus:PrCreateFact",),
    )
    producer = _make_card(
        capability_id="MM.Material.GetInfo",
        produces_fact_types=("sapnexus:MaterialInfoFact",),
    )
    return handoff, [consumer, producer]


def test_the_closure_pulls_the_producer_of_an_unbound_derivable_input():
    """Task 5.4.1(a) — the feature's core.

    ``MM.Material.GetInfo`` is not in ``matched_intents``: the user never asked
    for it. It enters ``desired_fact_types`` only because ``unit`` is required,
    unbound, and declares ``satisfiableByFactType``.
    """
    handoff, cards = _consumer_needing_an_upstream_unit()
    goal = build_goal_spec(handoff, cards)
    assert goal.desired_fact_types == (
        "sapnexus:PrCreateFact",
        "sapnexus:MaterialInfoFact",
    )


def test_the_closure_refuses_to_pull_a_producer_that_is_not_read_only():
    """Task 5.4.1(b) — invariant 5. Auto-pull must not execute a WRITE.

    The only producer of the Fact requires approval, so pulling it would put an
    unapproved WRITE into the plan on the user's behalf. The Fact is therefore
    left out and ``unit`` stays unresolved (the user is asked), which is the
    correct failure direction: elicit rather than execute.
    """
    handoff, cards = _consumer_needing_an_upstream_unit()
    cards[1] = _make_card(
        capability_id="MM.Material.Rewrite",
        governance=_make_governance(side_effect="update", requires_approval=True),
        produces_fact_types=("sapnexus:MaterialInfoFact",),
    )
    goal = build_goal_spec(handoff, cards)
    assert goal.desired_fact_types == ("sapnexus:PrCreateFact",)


def test_the_closure_refuses_a_side_effecting_producer_even_without_approval():
    """Task 5.4.1(b) — both governance fields are checked, not just one.

    A capability with ``sideEffect`` other than ``none`` is not a READ even if
    it happens to declare ``requiresApproval: false``; ``kind: Function`` binds
    *both*, so the closure must too. Without this, a mis-declared capability
    would become auto-pullable.
    """
    handoff, cards = _consumer_needing_an_upstream_unit()
    cards[1] = _make_card(
        capability_id="MM.Material.Touch",
        governance=_make_governance(side_effect="create", requires_approval=False),
        produces_fact_types=("sapnexus:MaterialInfoFact",),
    )
    goal = build_goal_spec(handoff, cards)
    assert goal.desired_fact_types == ("sapnexus:PrCreateFact",)


def test_the_closure_does_not_pull_when_the_user_supplied_the_value():
    """Task 5.4.1(c) — ruling 4: 用户明说优先.

    The user stated the unit, so no upstream read is needed and the producer is
    never pulled at all. This is not merely a precedence rule about which source
    wins: the extra SAP call must not happen.
    """
    handoff, cards = _consumer_needing_an_upstream_unit()
    handoff = dataclasses.replace(
        handoff,
        matched_intents=[
            MatchedIntent(
                capability_id="MM.PR.CreateDraft",
                parameters={"material": "M-1001", "plant": "1010", "unit": "ST"},
                missing=[],
            ),
        ],
    )
    goal = build_goal_spec(handoff, cards)
    assert goal.desired_fact_types == ("sapnexus:PrCreateFact",)


def test_the_closure_ignores_an_optional_derivable_input():
    """Task 5.4 — only *required* inputs justify an extra SAP read.

    An optional input the user omitted is an omission the plan may honour, not a
    gap the planner should spend a round trip closing.
    """
    handoff, cards = _consumer_needing_an_upstream_unit()
    cards[0] = dataclasses.replace(
        cards[0],
        inputs=(
            _make_input(name="material"),
            _make_input(name="plant", semantic_type="sapnexus:Plant"),
            _make_input(
                name="unit",
                semantic_type="sapnexus:BaseUnitOfMeasure",
                required=False,
                satisfiable_by_fact_type="sapnexus:MaterialInfoFact",
            ),
        ),
    )
    goal = build_goal_spec(handoff, cards)
    assert goal.desired_fact_types == ("sapnexus:PrCreateFact",)


def test_the_closure_does_not_duplicate_a_fact_type_already_desired():
    """Task 5.4 — a producer already matched is not pulled a second time.

    ``desiredFactTypes`` has ``uniqueItems: true`` in the S1 schema, so a
    duplicate would make the GoalSpec invalid rather than merely redundant.
    """
    handoff, cards = _consumer_needing_an_upstream_unit()
    handoff = dataclasses.replace(
        handoff,
        matched_intents=list(handoff.matched_intents)
        + [
            MatchedIntent(
                capability_id="MM.Material.GetInfo",
                parameters={"material": "M-1001"},
                missing=[],
            ),
        ],
    )
    goal = build_goal_spec(handoff, cards)
    assert goal.desired_fact_types == (
        "sapnexus:PrCreateFact",
        "sapnexus:MaterialInfoFact",
    )


def test_the_closure_is_transitive_and_terminates():
    """Task 5.4 — it is a *closure*, not a single hop.

    A pulled producer may itself have an unbound required derivable input. The
    worklist adds each Fact Type at most once, so a producer cycle terminates
    instead of looping — asserted here by a producer pair that references each
    other's Fact Type.
    """
    handoff, cards = _consumer_needing_an_upstream_unit()
    cards[1] = _make_card(
        capability_id="MM.Material.GetInfo",
        inputs=(
            _make_input(
                name="group",
                semantic_type="sapnexus:PurchasingGroup",
                satisfiable_by_fact_type="sapnexus:MaterialGroupFact",
            ),
        ),
        produces_fact_types=("sapnexus:MaterialInfoFact",),
    )
    cards.append(
        _make_card(
            capability_id="MM.Material.GetGroup",
            inputs=(
                _make_input(
                    name="unit",
                    semantic_type="sapnexus:BaseUnitOfMeasure",
                    satisfiable_by_fact_type="sapnexus:MaterialInfoFact",
                ),
            ),
            produces_fact_types=("sapnexus:MaterialGroupFact",),
        )
    )
    goal = build_goal_spec(handoff, cards)
    assert goal.desired_fact_types == (
        "sapnexus:PrCreateFact",
        "sapnexus:MaterialInfoFact",
        "sapnexus:MaterialGroupFact",
    )

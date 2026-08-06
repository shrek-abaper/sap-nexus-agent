import dataclasses

import pytest

from sap_nexus_agent.context_reducer import ContextResolution
from sap_nexus_agent.governed_context import VisibleCapabilitySet
from sap_nexus_agent.planner.capability_card import (
    CapabilityCard,
    Governance,
    InputDescriptor,
)
from sap_nexus_agent.read_context import ConversationReadState, ReadContextFrame, SlotBinding

from sap_nexus_agent.context_decision_gate import (
    ExecutionVisibilityProjection,
    ReadCapabilityCandidates,
    _build_execution_visibility_projection,
    decide_read_context,
)
from sap_nexus_agent.semantic_planning import SemanticSourceDocuments


INVENTORY_ID = "MM.Inventory.GetAvailability"
SNAPSHOT_ID = "sha256:current"


def _slot(name: str, value: str) -> SlotBinding:
    return SlotBinding(
        name=name,
        value=value,
        candidates=(value,),
        state="RESOLVED",
        provenance="EXPLICIT",
        source_turn_id="turn-1",
        source_span=None,
        issues=(),
    )


def _resolution(status: str = "READY") -> ContextResolution:
    frame = ReadContextFrame(
        frame_id="inventory:turn-1",
        capability_id=INVENTORY_ID,
        slots={
            "material": _slot("material", "DEMOA2"),
            "plant": _slot("plant", "1000"),
        },
        status=status,
        created_turn_id="turn-1",
        updated_turn_id="turn-1",
        registry_snapshot_id=SNAPSHOT_ID,
        capability_version="1",
    )
    return ContextResolution(
        next_state=ConversationReadState(frame, None, 1),
        operation="CONTINUE_FRAME",
        changed_slots=(),
        issues=(),
        evidence=(),
    )


def _visible() -> VisibleCapabilitySet:
    return VisibleCapabilitySet(
        cards=(
            CapabilityCard(
                capability_id=INVENTORY_ID,
                name="Inventory availability",
                governance=Governance(
                    side_effect="none",
                    requires_approval=False,
                    data_classification="internal",
                ),
                visibility="VISIBLE_EXECUTION",
                inputs=(
                    InputDescriptor("material", "sapnexus:MaterialNumber", True, "literal"),
                    InputDescriptor("plant", "sapnexus:Plant", True, "literal"),
                ),
                registry_snapshot_id=SNAPSHOT_ID,
            ),
        ),
        snapshot_id=SNAPSHOT_ID,
        principal_id="user-1",
    )


def _candidates(*capability_ids: str, purpose: str = "AMBIGUITY") -> ReadCapabilityCandidates:
    return ReadCapabilityCandidates(
        capability_ids=capability_ids,
        snapshot_id=SNAPSHOT_ID,
        purpose=purpose,
    )


def _sources(
    *,
    capabilities: tuple[dict[str, object], ...] | None = None,
    bindings: tuple[dict[str, object], ...] | None = None,
) -> SemanticSourceDocuments:
    capability = {
        "capabilityId": INVENTORY_ID,
        "status": "active",
        "executorBinding": {
            "type": "JCO_RFC",
            "bindingId": "inventory-binding",
        },
    }
    binding = {
        "bindingId": "inventory-binding",
        "type": "JCO_RFC",
        "constraints": {"sideEffect": "none"},
    }
    return SemanticSourceDocuments(
        capabilities={"capabilities": capabilities or (capability,)},
        executor_bindings={"bindings": bindings or (binding,)},
        fact_types={},
        relations={},
    )


def _production_projection(
    visible: VisibleCapabilitySet,
    *,
    sources: SemanticSourceDocuments | None = None,
) -> ExecutionVisibilityProjection:
    return _build_execution_visibility_projection(
        cards=visible.cards,
        visible=visible,
        current_snapshot_id=SNAPSHOT_ID,
        sources=sources or _sources(),
    )


@pytest.mark.parametrize("status", ["COLLECTING", "CONFLICTED", "STALE"])
def test_non_ready_frame_cannot_select(status: str) -> None:
    result = decide_read_context(
        _resolution(status), visible=_visible(), current_snapshot_id=SNAPSHOT_ID
    )

    assert result.decision.decision_type != "SELECT"
    assert result.call_plan_parameters is None


def test_ready_frame_uses_only_resolved_slots() -> None:
    result = decide_read_context(
        _resolution(), visible=_visible(), current_snapshot_id=SNAPSHOT_ID
    )

    assert result.decision.decision_type == "SELECT"
    assert result.decision.parameters == {"material": "DEMOA2", "plant": "1000"}
    assert result.call_plan_parameters == {"material": "DEMOA2", "plant": "1000"}


def test_current_snapshot_and_read_visibility_are_required() -> None:
    result = decide_read_context(
        _resolution(), visible=_visible(), current_snapshot_id="sha256:drifted"
    )

    assert result.decision.decision_type == "REJECT"
    assert result.decision.error_type == "CONTEXT_SNAPSHOT_DRIFT"
    assert result.call_plan_parameters is None


def test_non_execution_card_cannot_enter_read_selection() -> None:
    visible = _visible()
    restricted = dataclasses.replace(
        visible.cards[0],
        governance=dataclasses.replace(
            visible.cards[0].governance, data_classification="restricted"
        ),
    )
    result = decide_read_context(
        _resolution(),
        visible=dataclasses.replace(visible, cards=(restricted,)),
        current_snapshot_id=SNAPSHOT_ID,
    )

    assert result.decision.decision_type == "REJECT"
    assert result.call_plan_parameters is None


def test_one_current_visible_read_candidate_preserves_single_frame_selection() -> None:
    result = decide_read_context(
        _resolution(),
        visible=_visible(),
        current_snapshot_id=SNAPSHOT_ID,
        capability_candidates=_candidates(INVENTORY_ID),
    )

    assert result.decision.decision_type == "SELECT"


def test_valid_production_projection_can_prove_a_bound_dry_run_card() -> None:
    visible = _visible()
    visible = dataclasses.replace(
        visible,
        cards=(dataclasses.replace(visible.cards[0], visibility="VISIBLE_DRY_RUN"),),
    )

    result = decide_read_context(
        _resolution(),
        visible=visible,
        current_snapshot_id=SNAPSHOT_ID,
        capability_candidates=_candidates(INVENTORY_ID),
        execution_visibility=_production_projection(visible),
    )

    assert result.decision.decision_type == "SELECT"


def test_execution_projection_with_changed_snapshot_fails_closed() -> None:
    visible = dataclasses.replace(
        _visible(),
        cards=(dataclasses.replace(_visible().cards[0], visibility="VISIBLE_DRY_RUN"),),
    )
    projection = dataclasses.replace(
        _production_projection(visible), snapshot_id="sha256:forged"
    )

    result = decide_read_context(
        _resolution(),
        visible=visible,
        current_snapshot_id=SNAPSHOT_ID,
        capability_candidates=_candidates(INVENTORY_ID),
        execution_visibility=projection,
    )

    assert result.decision.decision_type == "REJECT"
    assert result.call_plan_parameters is None


def test_execution_projection_cannot_cross_visible_contexts() -> None:
    visible = dataclasses.replace(
        _visible(),
        cards=(dataclasses.replace(_visible().cards[0], visibility="VISIBLE_DRY_RUN"),),
    )
    projection = _production_projection(visible)
    other_visible = dataclasses.replace(visible, principal_id="user-2")

    result = decide_read_context(
        _resolution(),
        visible=other_visible,
        current_snapshot_id=SNAPSHOT_ID,
        capability_candidates=_candidates(INVENTORY_ID),
        execution_visibility=projection,
    )

    assert result.decision.decision_type == "REJECT"
    assert result.call_plan_parameters is None


def test_execution_projection_cannot_be_expanded_with_unproven_ids() -> None:
    visible = _visible()
    purchase_orders = dataclasses.replace(
        visible.cards[0],
        capability_id="MM.PurchaseOrder.GetList",
        visibility="VISIBLE_DRY_RUN",
    )
    visible = dataclasses.replace(
        visible,
        cards=(
            dataclasses.replace(visible.cards[0], visibility="VISIBLE_DRY_RUN"),
            purchase_orders,
        ),
    )
    projection = dataclasses.replace(
        _production_projection(visible),
        capability_ids=frozenset({INVENTORY_ID, "MM.PurchaseOrder.GetList"}),
    )

    result = decide_read_context(
        _resolution(),
        visible=visible,
        current_snapshot_id=SNAPSHOT_ID,
        capability_candidates=_candidates(INVENTORY_ID, "MM.PurchaseOrder.GetList"),
        execution_visibility=projection,
    )

    assert result.decision.decision_type == "REJECT"
    assert result.call_plan_parameters is None


def test_raw_execution_id_set_is_not_an_authority_override() -> None:
    visible = _visible()
    visible = dataclasses.replace(
        visible,
        cards=(dataclasses.replace(visible.cards[0], visibility="VISIBLE_DRY_RUN"),),
    )

    result = decide_read_context(
        _resolution(),
        visible=visible,
        current_snapshot_id=SNAPSHOT_ID,
        capability_candidates=_candidates(INVENTORY_ID),
        execution_visibility=frozenset({INVENTORY_ID}),
    )

    assert result.decision.decision_type == "REJECT"
    assert result.call_plan_parameters is None


def test_malformed_typed_projection_fails_closed() -> None:
    visible = _visible()
    visible = dataclasses.replace(
        visible,
        cards=(dataclasses.replace(visible.cards[0], visibility="VISIBLE_DRY_RUN"),),
    )
    forged = dataclasses.replace(
        _production_projection(visible),
        _proof="request-controlled",  # type: ignore[arg-type]
    )

    result = decide_read_context(
        _resolution(),
        visible=visible,
        current_snapshot_id=SNAPSHOT_ID,
        capability_candidates=_candidates(INVENTORY_ID),
        execution_visibility=forged,
    )

    assert result.decision.decision_type == "REJECT"
    assert result.call_plan_parameters is None


@pytest.mark.parametrize(
    "duplicate",
    [
        {
            "bindingId": "inventory-binding",
            "type": "JCO_RFC",
            "constraints": {"sideEffect": "sap_write"},
        },
        {
            "bindingId": "inventory-binding",
            "type": "ODATA",
            "constraints": {"sideEffect": "none"},
        },
    ],
)
@pytest.mark.parametrize("reverse", [False, True])
def test_duplicate_binding_ids_never_grant_shadow_selection(
    duplicate: dict[str, object], reverse: bool
) -> None:
    visible = _visible()
    visible = dataclasses.replace(
        visible,
        cards=(dataclasses.replace(visible.cards[0], visibility="VISIBLE_DRY_RUN"),),
    )
    read_binding = {
        "bindingId": "inventory-binding",
        "type": "JCO_RFC",
        "constraints": {"sideEffect": "none"},
    }
    bindings = (duplicate, read_binding) if reverse else (read_binding, duplicate)

    result = decide_read_context(
        _resolution(),
        visible=visible,
        current_snapshot_id=SNAPSHOT_ID,
        capability_candidates=_candidates(INVENTORY_ID),
        execution_visibility=_production_projection(
            visible, sources=_sources(bindings=bindings)
        ),
    )

    assert result.decision.decision_type == "REJECT"
    assert result.call_plan_parameters is None


@pytest.mark.parametrize("reverse", [False, True])
def test_duplicate_capability_ids_never_grant_shadow_options(reverse: bool) -> None:
    visible = _visible()
    purchase_orders = dataclasses.replace(
        visible.cards[0],
        capability_id="MM.PurchaseOrder.GetList",
        visibility="VISIBLE_DRY_RUN",
    )
    visible = dataclasses.replace(
        visible,
        cards=(
            dataclasses.replace(visible.cards[0], visibility="VISIBLE_DRY_RUN"),
            purchase_orders,
        ),
    )
    inventory = {
        "capabilityId": INVENTORY_ID,
        "status": "active",
        "executorBinding": {"type": "JCO_RFC", "bindingId": "inventory-binding"},
    }
    duplicate = {
        "capabilityId": INVENTORY_ID,
        "status": "active",
        "executorBinding": {"type": "ODATA", "bindingId": "other-binding"},
    }
    purchase_order = {
        "capabilityId": "MM.PurchaseOrder.GetList",
        "status": "active",
        "executorBinding": {"type": "JCO_RFC", "bindingId": "po-binding"},
    }
    capabilities = (
        (duplicate, inventory, purchase_order)
        if reverse
        else (inventory, duplicate, purchase_order)
    )
    bindings = (
        {
            "bindingId": "inventory-binding",
            "type": "JCO_RFC",
            "constraints": {"sideEffect": "none"},
        },
        {
            "bindingId": "other-binding",
            "type": "ODATA",
            "constraints": {"sideEffect": "none"},
        },
        {
            "bindingId": "po-binding",
            "type": "JCO_RFC",
            "constraints": {"sideEffect": "none"},
        },
    )

    result = decide_read_context(
        _resolution(),
        visible=visible,
        current_snapshot_id=SNAPSHOT_ID,
        capability_candidates=_candidates(INVENTORY_ID, "MM.PurchaseOrder.GetList"),
        execution_visibility=_production_projection(
            visible,
            sources=_sources(capabilities=capabilities, bindings=bindings),
        ),
    )

    assert result.decision.decision_type == "REJECT"
    assert result.call_plan_parameters is None


@pytest.mark.parametrize(
    ("candidates", "cards"),
    [
        ((INVENTORY_ID, INVENTORY_ID), None),
        (("MM.Inventory.Hidden",), None),
        ((INVENTORY_ID,), "duplicate"),
    ],
)
def test_duplicate_or_invisible_candidates_fail_closed(candidates, cards) -> None:
    visible = _visible()
    if cards == "duplicate":
        visible = dataclasses.replace(visible, cards=(visible.cards[0], visible.cards[0]))
    result = decide_read_context(
        _resolution(),
        visible=visible,
        current_snapshot_id=SNAPSHOT_ID,
        capability_candidates=_candidates(*candidates),
    )

    assert result.decision.decision_type == "REJECT"
    assert result.call_plan_parameters is None


def test_multiple_current_visible_read_candidates_show_options() -> None:
    visible = _visible()
    purchase_orders = dataclasses.replace(
        visible.cards[0],
        capability_id="MM.PurchaseOrder.GetList",
        name="Purchase orders",
    )
    result = decide_read_context(
        _resolution(),
        visible=dataclasses.replace(visible, cards=(visible.cards[0], purchase_orders)),
        current_snapshot_id=SNAPSHOT_ID,
        capability_candidates=_candidates(INVENTORY_ID, "MM.PurchaseOrder.GetList"),
    )

    assert result.decision.decision_type == "SHOW_OPTIONS"
    assert [candidate.capability_id for candidate in result.decision.candidates] == [
        INVENTORY_ID,
        "MM.PurchaseOrder.GetList",
    ]
    assert result.call_plan_parameters is None


@pytest.mark.parametrize(
    "card",
    [
        dataclasses.replace(_visible().cards[0], registry_snapshot_id=""),
        dataclasses.replace(_visible().cards[0], registry_snapshot_id="sha256:stale"),
        dataclasses.replace(_visible().cards[0], visibility="HIDDEN"),
        dataclasses.replace(_visible().cards[0], visibility="VISIBLE_DRY_RUN"),
        dataclasses.replace(
            _visible().cards[0],
            governance=dataclasses.replace(_visible().cards[0].governance, side_effect="sap_write"),
        ),
        dataclasses.replace(
            _visible().cards[0],
            governance=dataclasses.replace(_visible().cards[0].governance, requires_approval=True),
        ),
    ],
)
def test_non_current_or_non_execution_cards_fail_closed(card) -> None:
    visible = dataclasses.replace(_visible(), cards=(card,))
    result = decide_read_context(
        _resolution(),
        visible=visible,
        current_snapshot_id=SNAPSHOT_ID,
        capability_candidates=_candidates(INVENTORY_ID),
    )

    assert result.decision.decision_type == "REJECT"


def test_multi_read_goal_candidates_escalate_without_a_call_plan() -> None:
    visible = _visible()
    purchase_orders = dataclasses.replace(
        visible.cards[0], capability_id="MM.PurchaseOrder.GetList"
    )
    result = decide_read_context(
        _resolution(),
        visible=dataclasses.replace(visible, cards=(visible.cards[0], purchase_orders)),
        current_snapshot_id=SNAPSHOT_ID,
        capability_candidates=_candidates(
            INVENTORY_ID,
            "MM.PurchaseOrder.GetList",
            purpose="MULTI_GOAL",
        ),
    )

    assert result.decision.decision_type == "ESCALATE_TO_PLANNER"
    assert result.call_plan_parameters is None


def test_unknown_and_model_candidate_slots_are_rejected() -> None:
    frame = _resolution().next_state.active_frame
    assert frame is not None
    technical = SlotBinding(
        name="rfcName",
        value="BAPI_EVIL",
        candidates=("BAPI_EVIL",),
        state="RESOLVED",
        provenance="EXPLICIT",
        source_turn_id="turn-1",
        source_span=None,
        issues=(),
    )
    model_material = dataclasses.replace(
        frame.slots["material"], provenance="MODEL_CANDIDATE"
    )
    for slots in (
        {**frame.slots, "rfcName": technical},
        {**frame.slots, "material": model_material},
    ):
        adjusted = dataclasses.replace(frame, slots=slots)
        result = decide_read_context(
            dataclasses.replace(
                _resolution(),
                next_state=ConversationReadState(adjusted, None, 1),
            ),
            visible=_visible(),
            current_snapshot_id=SNAPSHOT_ID,
            capability_candidates=_candidates(INVENTORY_ID),
        )
        assert result.decision.decision_type == "REJECT"


def test_conflicted_optional_slot_is_an_actionable_clarification_field() -> None:
    visible = _visible()
    optional = InputDescriptor("storageLocation", "sapnexus:StorageLocation", False, "literal")
    card = dataclasses.replace(visible.cards[0], inputs=(*visible.cards[0].inputs, optional))
    frame = _resolution().next_state.active_frame
    assert frame is not None
    conflicted = SlotBinding(
        name="storageLocation",
        value=None,
        candidates=("A001", "B001"),
        state="CONFLICTED",
        provenance="EXPLICIT",
        source_turn_id="turn-1",
        source_span=None,
        issues=("conflict",),
    )
    adjusted = dataclasses.replace(
        frame,
        slots={**frame.slots, "storageLocation": conflicted},
        status="CONFLICTED",
    )
    result = decide_read_context(
        dataclasses.replace(_resolution(), next_state=ConversationReadState(adjusted, None, 1)),
        visible=dataclasses.replace(visible, cards=(card,)),
        current_snapshot_id=SNAPSHOT_ID,
        capability_candidates=_candidates(INVENTORY_ID),
    )

    assert result.decision.decision_type == "CLARIFY"
    assert result.decision.missing_parameters == ["storageLocation"]

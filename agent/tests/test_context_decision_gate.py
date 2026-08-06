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
    ReadCapabilityCandidates,
    decide_read_context,
)


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

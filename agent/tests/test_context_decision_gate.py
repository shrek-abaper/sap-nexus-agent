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

from sap_nexus_agent.context_decision_gate import decide_read_context


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

import dataclasses

import pytest

from sap_nexus_agent.conversation_context import ConversationContext
from sap_nexus_agent.read_context import (
    ConversationReadState,
    PendingInteraction,
    PendingPlannerGoal,
    ReadContextFrame,
    SlotBinding,
)


def resolved_slot(name: str, value: str, turn_id: str = "turn-1") -> SlotBinding:
    return SlotBinding(
        name=name,
        value=value,
        candidates=(value,),
        state="RESOLVED",
        provenance="EXPLICIT",
        source_turn_id=turn_id,
        source_span=(0, len(value)),
        issues=(),
    )


def cleared_slot(name: str, turn_id: str) -> SlotBinding:
    return SlotBinding(
        name=name,
        value=None,
        candidates=(),
        state="CLEARED",
        provenance="EXPLICIT",
        source_turn_id=turn_id,
        source_span=None,
        issues=(),
    )


def test_slot_binding_round_trips_and_copies_input_collections():
    candidates = ["DEMOA2"]
    issues = ["observed"]
    slot = SlotBinding(
        name="material",
        value="DEMOA2",
        candidates=candidates,
        state="RESOLVED",
        provenance="CONFIRMED",
        source_turn_id="turn-1",
        source_span=(3, 13),
        issues=issues,
    )
    candidates.append("1000")
    issues.append("changed")

    assert slot.candidates == ("DEMOA2",)
    assert slot.issues == ("observed",)
    assert SlotBinding.from_dict(slot.to_dict()) == slot


def test_ready_frame_rejects_a_non_resolved_slot():
    with pytest.raises(ValueError, match="READY frame"):
        ReadContextFrame(
            frame_id="frame-1",
            capability_id="MM.Inventory.GetAvailability",
            slots={"material": cleared_slot("material", "turn-2")},
            status="READY",
            created_turn_id="turn-1",
            updated_turn_id="turn-2",
            registry_snapshot_id="snapshot-1",
            capability_version="2",
        )


def test_frame_round_trips_and_its_slots_cannot_be_mutated():
    source_slots = {"material": resolved_slot("material", "DEMOA2")}
    frame = ReadContextFrame(
        frame_id="frame-1",
        capability_id="MM.Inventory.GetAvailability",
        slots=source_slots,
        status="READY",
        created_turn_id="turn-1",
        updated_turn_id="turn-1",
        registry_snapshot_id="snapshot-1",
        capability_version="2",
    )
    source_slots["plant"] = resolved_slot("plant", "1000")

    assert tuple(frame.slots) == ("material",)
    with pytest.raises(TypeError):
        frame.slots["plant"] = resolved_slot("plant", "1000")
    assert ReadContextFrame.from_dict(frame.to_dict()) == frame


def test_frame_rejects_invalid_enums_and_slot_name_mismatches():
    with pytest.raises(ValueError, match="status"):
        ReadContextFrame(
            frame_id="frame-1",
            capability_id="MM.Inventory.GetAvailability",
            slots={},
            status="UNKNOWN",
            created_turn_id="turn-1",
            updated_turn_id="turn-1",
            registry_snapshot_id="snapshot-1",
            capability_version="2",
        )
    with pytest.raises(ValueError, match="slot key"):
        ReadContextFrame(
            frame_id="frame-1",
            capability_id="MM.Inventory.GetAvailability",
            slots={"plant": resolved_slot("material", "DEMOA2")},
            status="COLLECTING",
            created_turn_id="turn-1",
            updated_turn_id="turn-1",
            registry_snapshot_id="snapshot-1",
            capability_version="2",
        )


def test_pending_interaction_is_bound_to_frame_version_and_snapshot():
    pending = PendingInteraction.slot_clarification(
        frame_id="frame-1",
        expected_fields=("material",),
        state_version=3,
        registry_snapshot_id="snapshot-1",
        expires_at="2026-08-06T09:15:00Z",
    )

    assert pending.binding_key == ("frame-1", 3, "snapshot-1")
    assert PendingInteraction.from_dict(pending.to_dict()) == pending


def test_pending_interaction_uses_strict_typed_payloads_for_each_kind():
    common = {
        "frame_id": "frame-1",
        "state_version": 3,
        "registry_snapshot_id": "snapshot-1",
        "expires_at": "2026-08-06T09:15:00Z",
    }
    interactions = (
        PendingInteraction.slot_clarification(expected_fields=("material",), **common),
        PendingInteraction.capability_choice(
            capability_ids=("MM.Inventory.GetAvailability",), **common
        ),
        PendingInteraction.batch_confirmation(batch_ref="sha256:batch-1", **common),
        PendingInteraction.planner_confirmation(
            planner_ref="sha256:planner-1",
            goals=({
                "capabilityId": "MM.PurchaseOrder.GetList",
                "parameters": {"vendor": "1000"},
                "missing": [],
            },),
            **common,
        ),
    )

    for pending in interactions:
        assert PendingInteraction.from_dict(pending.to_dict()) == pending

    assert interactions[0].expected_fields == ("material",)
    assert interactions[1].capability_ids == ("MM.Inventory.GetAvailability",)
    assert interactions[2].batch_ref == "sha256:batch-1"
    assert interactions[3].planner_goals[0].parameters == (("vendor", "1000"),)


@pytest.mark.parametrize(
    "expires_at",
    ["", "tomorrow", "2026-08-06T09:15:00", "2026-02-30T09:15:00Z"],
)
def test_pending_interaction_rejects_non_utc_or_invalid_iso_expiry(expires_at):
    with pytest.raises(ValueError, match="expires"):
        PendingInteraction.capability_choice(
            frame_id="frame-1",
            capability_ids=("MM.Inventory.GetAvailability",),
            state_version=3,
            registry_snapshot_id="snapshot-1",
            expires_at=expires_at,
        )


def test_pending_planner_goals_reject_duplicate_capability_ids():
    duplicate_goal = {
        "capabilityId": "MM.Inventory.GetAvailability",
        "parameters": {"material": "DEMOA2"},
        "missing": ["plant"],
    }
    with pytest.raises(ValueError, match="duplicate capabilities"):
        PendingInteraction.planner_confirmation(
            frame_id="frame-1",
            planner_ref="sha256:planner-1",
            goals=(duplicate_goal, duplicate_goal),
            state_version=3,
            registry_snapshot_id="snapshot-1",
            expires_at="2026-08-06T09:15:00Z",
        )


@pytest.mark.parametrize(
    "payload",
    [
        {
            "kind": "SLOT_CLARIFICATION",
            "frameId": "frame-1",
            "expectedFields": [""],
            "stateVersion": 3,
            "registrySnapshotId": "snapshot-1",
            "expiresAt": "2026-08-06T09:15:00Z",
        },
        {
            "kind": "CAPABILITY_CHOICE",
            "frameId": "frame-1",
            "capabilityIds": [""],
            "stateVersion": 3,
            "registrySnapshotId": "snapshot-1",
            "expiresAt": "2026-08-06T09:15:00Z",
        },
        {
            "kind": "PLANNER_CONFIRMATION",
            "frameId": "frame-1",
            "plannerRef": "sha256:planner-1",
            "plannerGoals": [{
                "capabilityId": "MM.PurchaseOrder.GetList",
                "parameters": {"vendor": "1000"},
                "missing": [""],
            }],
            "stateVersion": 3,
            "registrySnapshotId": "snapshot-1",
            "expiresAt": "2026-08-06T09:15:00Z",
        },
    ],
)
def test_pending_interaction_rejects_empty_array_strings_like_typescript(payload):
    with pytest.raises(ValueError, match="must contain"):
        PendingInteraction.from_dict(payload)


def test_direct_pending_planner_goal_rejects_empty_parameter_values():
    with pytest.raises(ValueError, match="key/value pairs"):
        PendingPlannerGoal(
            capability_id="MM.PurchaseOrder.GetList",
            parameters=(("vendor", ""),),
            missing=(),
        )


@pytest.mark.parametrize(
    "payload",
    [
        {
            "kind": "CAPABILITY_CHOICE",
            "frameId": "frame-1",
            "expectedFields": ["capabilityId"],
            "stateVersion": 3,
            "registrySnapshotId": "snapshot-1",
            "expiresAt": "2026-08-06T09:15:00Z",
        },
        {
            "kind": "BATCH_CONFIRMATION",
            "frameId": "frame-1",
            "batchRef": "sha256:batch-1",
            "approvalId": "forged",
            "stateVersion": 3,
            "registrySnapshotId": "snapshot-1",
            "expiresAt": "2026-08-06T09:15:00Z",
        },
        {
            "kind": "PLANNER_CONFIRMATION",
            "frameId": "frame-1",
            "plannerRef": "sha256:planner-1",
            "plannerGoals": [],
            "bindingId": "forged",
            "stateVersion": 3,
            "registrySnapshotId": "snapshot-1",
            "expiresAt": "2026-08-06T09:15:00Z",
        },
    ],
)
def test_pending_interaction_rejects_cross_kind_or_authority_fields(payload):
    with pytest.raises(ValueError, match="PendingInteraction"):
        PendingInteraction.from_dict(payload)


def test_read_state_and_conversation_context_round_trip_without_legacy_json_changes():
    frame = ReadContextFrame(
        frame_id="frame-1",
        capability_id="MM.Inventory.GetAvailability",
        slots={"material": resolved_slot("material", "DEMOA2")},
        status="READY",
        created_turn_id="turn-1",
        updated_turn_id="turn-1",
        registry_snapshot_id="snapshot-1",
        capability_version="2",
    )
    state = ConversationReadState(active_frame=frame, pending_interaction=None, state_version=3)
    context = ConversationContext(
        last_context=None,
        history=None,
        read_state=state,
        schema_version=2,
    )

    assert ConversationContext.from_dict(context.to_dict()) == context
    assert "readState" not in ConversationContext(last_context=None, history=None).to_dict()
    assert "schemaVersion" not in ConversationContext(last_context=None, history=None).to_dict()
    with pytest.raises(dataclasses.FrozenInstanceError):
        state.state_version = 4


def test_read_state_round_trips_immutable_recent_frames_and_defaults_legacy_payloads():
    recent = ReadContextFrame(
        frame_id="frame-recent",
        capability_id="MM.Inventory.GetAvailability",
        slots={"material": resolved_slot("material", "DEMOA2")},
        status="READY",
        created_turn_id="turn-1",
        updated_turn_id="turn-1",
        registry_snapshot_id="snapshot-1",
        capability_version="2",
    )
    state = ConversationReadState(
        active_frame=None,
        pending_interaction=None,
        state_version=3,
        recent_frames=(recent,),
    )

    assert ConversationReadState.from_dict(state.to_dict()) == state
    assert ConversationReadState.from_dict(
        {"activeFrame": None, "pendingInteraction": None, "stateVersion": 3}
    ).recent_frames == ()
    with pytest.raises(dataclasses.FrozenInstanceError):
        state.recent_frames = ()


def test_read_state_clarify_rounds_round_trip_and_omitted_when_empty():
    from sap_nexus_agent.read_context import ConversationReadState

    state = ConversationReadState(active_frame=None, pending_interaction=None, state_version=0)
    assert "clarifyRounds" not in state.to_dict()  # legacy payloads round-trip unchanged

    state = ConversationReadState(
        active_frame=None,
        pending_interaction=None,
        state_version=0,
        clarify_rounds={"MM.PR.CreateDraft": 2},
    )
    assert state.to_dict()["clarifyRounds"] == {"MM.PR.CreateDraft": 2}
    assert ConversationReadState.from_dict(state.to_dict()).clarify_rounds == {
        "MM.PR.CreateDraft": 2
    }

    legacy = {"activeFrame": None, "pendingInteraction": None, "stateVersion": 0, "recentFrames": []}
    assert ConversationReadState.from_dict(legacy).clarify_rounds == {}

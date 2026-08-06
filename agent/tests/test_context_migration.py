from sap_nexus_agent.context_migration import migrate_legacy_context
from sap_nexus_agent.conversation_context import ConversationContext, LastContext


def test_migrate_select_context_preserves_source_and_never_returns_ready():
    legacy = ConversationContext(
        last_context=LastContext(
            capability_id="MM.Inventory.GetAvailability",
            parameters={"material": "DEMOA2", "plant": "1000"},
            missing_parameters=[],
            decision_type="SELECT",
        ),
        history=None,
    )
    original = legacy.to_dict()

    state = migrate_legacy_context(legacy, snapshot_id="snapshot-2", turn_id="turn-9")

    assert legacy.to_dict() == original
    assert state.active_frame is not None
    assert state.active_frame.status == "STALE"
    assert state.active_frame.slots["plant"].provenance == "INHERITED_LEGACY"
    assert state.active_frame.slots["material"].value == "DEMOA2"


def test_migrate_clarify_context_preserves_missing_slots_as_cleared_legacy_slots():
    legacy = ConversationContext(
        last_context=LastContext(
            capability_id="MM.Inventory.GetAvailability",
            parameters={"material": "DEMOA2"},
            missing_parameters=["plant"],
            decision_type="CLARIFY",
        ),
        history=None,
    )

    state = migrate_legacy_context(legacy, snapshot_id="snapshot-2", turn_id="turn-9")

    assert state.active_frame is not None
    assert state.active_frame.status == "STALE"
    assert state.active_frame.slots["material"].provenance == "INHERITED_LEGACY"
    assert state.active_frame.slots["plant"].state == "CLEARED"
    assert state.active_frame.slots["plant"].provenance == "INHERITED_LEGACY"


def test_migrate_empty_parameters_creates_a_stale_frame_without_slots():
    legacy = ConversationContext(
        last_context=LastContext(
            capability_id="MM.Inventory.GetAvailability",
            parameters={},
            missing_parameters=[],
            decision_type="SELECT",
        ),
        history=None,
    )

    state = migrate_legacy_context(legacy, snapshot_id="snapshot-2", turn_id="turn-9")

    assert state.active_frame is not None
    assert state.active_frame.status == "STALE"
    assert dict(state.active_frame.slots) == {}


def test_migrate_malformed_payload_fails_closed_without_a_frame():
    source = {"lastContext": {"capabilityId": 3, "parameters": "not-a-mapping"}}

    state = migrate_legacy_context(source, snapshot_id="snapshot-2", turn_id="turn-9")

    assert state.active_frame is None
    assert state.pending_interaction is None

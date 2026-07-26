"""Unit tests for ConversationContext data model (Task 1)."""

from sap_nexus_agent.conversation_context import (
    ConversationContext,
    LastContext,
    Turn,
)


def test_last_context_clarify_round_trip():
    ctx = LastContext(
        capability_id="MM.Inventory.GetAvailability",
        parameters={"material": "DEMOA2"},
        missing_parameters=["plant"],
        decision_type="CLARIFY",
    )
    payload = ctx.to_dict()
    assert payload == {
        "capabilityId": "MM.Inventory.GetAvailability",
        "parameters": {"material": "DEMOA2"},
        "missingParameters": ["plant"],
        "decisionType": "CLARIFY",
    }
    assert LastContext.from_dict(payload) == ctx


def test_last_context_select_empty_missing():
    ctx = LastContext(
        capability_id="MM.Inventory.GetAvailability",
        parameters={"material": "DEMOA2", "plant": "1000"},
        missing_parameters=[],
        decision_type="SELECT",
    )
    assert ctx.missing_parameters == []
    assert ctx.decision_type == "SELECT"


def test_turn_to_dict():
    turn = Turn(role="user", content="DEMOA2 1000")
    assert turn.to_dict() == {"role": "user", "content": "DEMOA2 1000"}


def test_conversation_context_round_trip():
    ctx = ConversationContext(
        last_context=LastContext(
            capability_id="MM.Inventory.GetAvailability",
            parameters={"material": "DEMOA2"},
            missing_parameters=["plant"],
            decision_type="CLARIFY",
        ),
        history=(Turn(role="user", content="查库存"), Turn(role="assistant", content="请提供物料和工厂")),
    )
    payload = ctx.to_dict()
    restored = ConversationContext.from_dict(payload)
    assert restored == ctx


def test_conversation_context_empty_round_trip():
    ctx = ConversationContext(last_context=None, history=None)
    payload = ctx.to_dict()
    assert payload == {"lastContext": None, "history": None}
    assert ConversationContext.from_dict(payload) == ctx

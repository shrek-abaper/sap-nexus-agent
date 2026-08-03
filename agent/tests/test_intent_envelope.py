import dataclasses
import uuid

import pytest

from sap_nexus_agent.intent_envelope import IntentEnvelope, IntentGoal


def test_intent_goal_construction():
    goal = IntentGoal(
        goal_text="查物料 DEMOA2 在 1000 的库存",
        capability_hint="MM.Inventory.GetAvailability",
        parameters={"material": "DEMOA2", "plant": "1000"},
        missing=[],
    )
    assert goal.goal_text == "查物料 DEMOA2 在 1000 的库存"
    assert goal.capability_hint == "MM.Inventory.GetAvailability"
    assert goal.parameters == {"material": "DEMOA2", "plant": "1000"}
    assert goal.missing == []


def test_intent_goal_is_frozen():
    goal = IntentGoal(goal_text="x", capability_hint=None, parameters={}, missing=[])
    assert dataclasses.is_dataclass(goal)
    with pytest.raises(dataclasses.FrozenInstanceError):
        goal.goal_text = "mutated"  # type: ignore[misc]


def test_intent_envelope_construction_llm():
    goal = IntentGoal(
        goal_text="查库存",
        capability_hint="MM.Inventory.GetAvailability",
        parameters={"material": "DEMOA2", "plant": "1000"},
        missing=[],
    )
    envelope = IntentEnvelope(
        envelope_id=uuid.uuid4().hex,
        utterance="查库存 DEMOA2 1000",
        goals=(goal,),
        user_constraints={},
        ambiguities=[],
        reference_turn_id=None,
        model_evidence={"goals": 1, "candidates": ["MM.Inventory.GetAvailability"]},
        snapshot_id="snap-001",
        discard_reasons=[],
        created_by="llm",
    )
    assert envelope.created_by == "llm"
    assert envelope.snapshot_id == "snap-001"
    assert len(envelope.envelope_id) > 0
    assert len(envelope.goals) == 1
    assert envelope.goals[0].capability_hint == "MM.Inventory.GetAvailability"


def test_intent_envelope_is_frozen():
    envelope = IntentEnvelope(
        envelope_id="id",
        utterance="u",
        goals=(),
        user_constraints={},
        ambiguities=[],
        reference_turn_id=None,
        model_evidence={},
        snapshot_id="snap-001",
        discard_reasons=[],
        created_by="rule",
    )
    assert dataclasses.is_dataclass(envelope)
    with pytest.raises(dataclasses.FrozenInstanceError):
        envelope.utterance = "mutated"  # type: ignore[misc]


def test_intent_envelope_rule_path_created_by():
    envelope = IntentEnvelope(
        envelope_id="id",
        utterance="查库存",
        goals=(),
        user_constraints={},
        ambiguities=[],
        reference_turn_id=None,
        model_evidence={},
        snapshot_id="snap-001",
        discard_reasons=[],
        created_by="rule",
    )
    assert envelope.created_by == "rule"
    assert envelope.model_evidence == {}

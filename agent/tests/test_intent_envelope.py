import dataclasses

import pytest

from sap_nexus_agent.intent_envelope import IntentGoal


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

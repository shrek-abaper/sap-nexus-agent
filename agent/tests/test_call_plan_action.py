from __future__ import annotations

from sap_nexus_agent.call_plan import CallPlan, create_call_plan
from sap_nexus_agent.capability_selector import INTENT_TO_CAPABILITY


def test_action_call_plan_sets_kind_and_approval():
    plan = create_call_plan(
        "MM.PR.CreateDraft",
        {"material": "M001", "plant": "1000"},
        kind="Action",
    )
    assert plan.kind == "Action"
    assert plan.requires_approval is True
    assert plan.capability_id == "MM.PR.CreateDraft"


def test_function_call_plan_remains_default():
    plan = create_call_plan(
        "MM.Inventory.GetAvailability",
        {"material": "M001", "plant": "1000"},
    )
    assert plan.kind == "Function"
    assert plan.requires_approval is False


def test_action_call_plan_round_trips_workbench_payload():
    plan = create_call_plan(
        "MM.PR.CreateDraft",
        {"material": "M001", "plant": "1000"},
        kind="Action",
    )

    restored = CallPlan.from_dict(plan.to_dict())

    assert restored == plan


def test_pr_create_intent_maps_to_create_draft_capability():
    assert INTENT_TO_CAPABILITY["pr_create"] == "MM.PR.CreateDraft"

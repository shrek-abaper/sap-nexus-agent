"""Unit tests for MatchDecision dataclass (S2-A, Plan Task 1).

Covers:
- Five-state construction (SELECT / CLARIFY / REJECT / SHOW_OPTIONS / ESCALATE_TO_PLANNER)
- MatchedIntent and EscalationHandoff field shapes
- to_selection_result() narrow-view compat: returns SelectionResult for
  SELECT/CLARIFY/REJECT, returns None for SHOW_OPTIONS/ESCALATE_TO_PLANNER
- frozen dataclass immutability
"""

from __future__ import annotations

import dataclasses

import pytest

from sap_nexus_agent.capability_selector import SelectionResult
from sap_nexus_agent.match_decision import (
    DecisionType,
    EscalationHandoff,
    MatchDecision,
    MatchedIntent,
)


def test_matched_intent_construction():
    mi = MatchedIntent(
        capability_id="MM.Inventory.GetAvailability",
        parameters={"material": "DEMOA1", "plant": "1000"},
        missing=[],
    )
    assert mi.capability_id == "MM.Inventory.GetAvailability"
    assert mi.parameters == {"material": "DEMOA1", "plant": "1000"}
    assert mi.missing == []


def test_select_state_construction():
    decision = MatchDecision(
        decision_type="SELECT",
        capability_id="MM.Inventory.GetAvailability",
        parameters={"material": "DEMOA1", "plant": "1000"},
        rationale="single inventory hit",
    )
    assert decision.decision_type == "SELECT"
    assert decision.capability_id == "MM.Inventory.GetAvailability"
    assert decision.parameters == {"material": "DEMOA1", "plant": "1000"}
    assert decision.missing_parameters is None
    assert decision.error_type is None
    assert decision.candidates is None
    assert decision.handoff is None
    assert decision.rationale == "single inventory hit"


def test_clarify_state_construction():
    decision = MatchDecision(
        decision_type="CLARIFY",
        missing_parameters=["plant"],
        rationale="请提供工厂代码",
    )
    assert decision.decision_type == "CLARIFY"
    assert decision.missing_parameters == ["plant"]
    assert decision.capability_id is None
    assert decision.parameters is None
    assert decision.rationale == "请提供工厂代码"


def test_reject_state_construction():
    decision = MatchDecision(
        decision_type="REJECT",
        error_type="UNSUPPORTED_RFC_NAME",
        rationale="Agent 不接受 rfcName 技术覆盖",
    )
    assert decision.decision_type == "REJECT"
    assert decision.error_type == "UNSUPPORTED_RFC_NAME"
    assert decision.capability_id is None
    assert decision.rationale == "Agent 不接受 rfcName 技术覆盖"


def test_show_options_state_construction():
    candidates = [
        MatchedIntent(capability_id="MM.PurchaseOrder.GetList", parameters={}, missing=[]),
        MatchedIntent(capability_id="MM.PR.CreateDraft", parameters={}, missing=[]),
    ]
    decision = MatchDecision(
        decision_type="SHOW_OPTIONS",
        candidates=candidates,
        rationale="ambiguous purchase keyword",
    )
    assert decision.decision_type == "SHOW_OPTIONS"
    assert decision.candidates is not None
    assert len(decision.candidates) == 2
    assert decision.candidates[0].capability_id == "MM.PurchaseOrder.GetList"
    assert decision.candidates[1].capability_id == "MM.PR.CreateDraft"
    assert decision.handoff is None


def test_escalate_state_with_full_handoff():
    matched = [
        MatchedIntent(
            capability_id="MM.Inventory.GetAvailability",
            parameters={"material": "DEMOA1"},
            missing=["plant"],
        ),
        MatchedIntent(
            capability_id="MM.PurchaseOrder.GetList",
            parameters={"plant": "1000"},
            missing=[],
        ),
    ]
    handoff = EscalationHandoff(
        reason="multi-intent utterance requires planner composition",
        matched_intents=matched,
        utterance="查一下 DEMOA1 的库存和 1000 的采购订单",
        registry_snapshot_id="reg-20260725-abcd",
    )
    decision = MatchDecision(
        decision_type="ESCALATE_TO_PLANNER",
        handoff=handoff,
        rationale="2 capabilities matched",
    )
    assert decision.decision_type == "ESCALATE_TO_PLANNER"
    assert decision.handoff is not None
    assert decision.handoff.reason == "multi-intent utterance requires planner composition"
    assert len(decision.handoff.matched_intents) == 2
    assert decision.handoff.matched_intents[0].capability_id == "MM.Inventory.GetAvailability"
    assert decision.handoff.matched_intents[0].missing == ["plant"]
    assert decision.handoff.utterance == "查一下 DEMOA1 的库存和 1000 的采购订单"
    assert decision.handoff.registry_snapshot_id == "reg-20260725-abcd"
    assert decision.capability_id is None


def test_escalation_handoff_is_frozen_dataclass():
    handoff = EscalationHandoff(
        reason="x",
        matched_intents=[],
        utterance="u",
        registry_snapshot_id="s",
    )
    assert dataclasses.is_dataclass(handoff)
    with pytest.raises(dataclasses.FrozenInstanceError):
        handoff.reason = "mutated"  # type: ignore[misc]


def test_to_selection_result_select_returns_narrow_view():
    decision = MatchDecision(
        decision_type="SELECT",
        capability_id="MM.Inventory.GetAvailability",
        parameters={"material": "DEMOA1", "plant": "1000"},
        rationale="ok",
    )
    sr = decision.to_selection_result()
    assert sr is not None
    assert isinstance(sr, SelectionResult)
    assert sr.capability_id == "MM.Inventory.GetAvailability"
    assert sr.error_type is None
    assert sr.message is None


def test_to_selection_result_clarify_returns_narrow_view():
    decision = MatchDecision(
        decision_type="CLARIFY",
        missing_parameters=["plant"],
        rationale="请提供工厂代码",
    )
    sr = decision.to_selection_result()
    assert sr is not None
    assert isinstance(sr, SelectionResult)
    assert sr.capability_id is None
    assert sr.error_type == "MISSING_PARAMETER"
    assert sr.message == "请提供工厂代码"


def test_to_selection_result_reject_returns_narrow_view():
    decision = MatchDecision(
        decision_type="REJECT",
        error_type="UNSUPPORTED_RFC_NAME",
        rationale="Agent 不接受 rfcName 技术覆盖",
    )
    sr = decision.to_selection_result()
    assert sr is not None
    assert isinstance(sr, SelectionResult)
    assert sr.capability_id is None
    assert sr.error_type == "UNSUPPORTED_RFC_NAME"
    assert sr.message == "Agent 不接受 rfcName 技术覆盖"


def test_to_selection_result_show_options_returns_none():
    decision = MatchDecision(
        decision_type="SHOW_OPTIONS",
        candidates=[
            MatchedIntent(capability_id="MM.PurchaseOrder.GetList", parameters={}, missing=[]),
        ],
        rationale="ambiguous",
    )
    assert decision.to_selection_result() is None


def test_to_selection_result_escalate_returns_none():
    handoff = EscalationHandoff(
        reason="multi-intent",
        matched_intents=[],
        utterance="u",
        registry_snapshot_id="s",
    )
    decision = MatchDecision(
        decision_type="ESCALATE_TO_PLANNER",
        handoff=handoff,
        rationale="escalate",
    )
    assert decision.to_selection_result() is None


def test_match_decision_is_frozen():
    decision = MatchDecision(decision_type="SELECT", capability_id="X", parameters={})
    assert dataclasses.is_dataclass(decision)
    with pytest.raises(dataclasses.FrozenInstanceError):
        decision.capability_id = "Y"  # type: ignore[misc]


def test_matched_intent_is_frozen():
    mi = MatchedIntent(capability_id="X", parameters={}, missing=[])
    with pytest.raises(dataclasses.FrozenInstanceError):
        mi.capability_id = "Y"  # type: ignore[misc]


def test_decision_type_literal_accepts_five_states():
    # DecisionType is a Literal; verify the five allowed string values are
    # the documented set. Construction with each must succeed.
    for dt in ("SELECT", "CLARIFY", "REJECT", "SHOW_OPTIONS", "ESCALATE_TO_PLANNER"):
        d = MatchDecision(decision_type=dt)  # type: ignore[arg-type]
        assert d.decision_type == dt

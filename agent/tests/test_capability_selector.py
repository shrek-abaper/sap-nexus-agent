"""Unit tests for select_capability five-state MatchDecision (S2-A, Plan Task 3).

Covers the decision tree from Design Doc § selector (order-sensitive):
1. Technical override (rfcName/OData) -> REJECT(UNSUPPORTED_RFC_NAME)
2. matched_intents > 1              -> ESCALATE_TO_PLANNER(handoff)
3. is_ambiguous (keyword ambiguity) -> SHOW_OPTIONS(candidates)
4. Single intent missing params     -> CLARIFY(missing_parameters)
5. Single intent complete           -> SELECT(capability_id, parameters)
6. No match                         -> REJECT(UNSUPPORTED_INTENT)

Note on SHOW_OPTIONS: Task 2 (intent.py) did not add ``is_ambiguous`` to
IntentParseResult, so SHOW_OPTIONS is not yet reachable from real rule/LLM
input. The selector reads ``is_ambiguous`` defensively (``getattr`` default
False); these tests exercise the code path via a lightweight test double
(SimpleNamespace) so the branch is covered and ready for a future intent.py
enhancement that populates the flag.
"""

from __future__ import annotations

import types

from sap_nexus_agent.capability_selector import select_capability
from sap_nexus_agent.intent import IntentParseResult
from sap_nexus_agent.match_decision import (
    EscalationHandoff,
    MatchDecision,
    MatchedIntent,
)


def _inventory_matched(material="DEMOA1", plant="1000", missing=None) -> MatchedIntent:
    return MatchedIntent(
        capability_id="MM.Inventory.GetAvailability",
        parameters={"material": material, "plant": plant},
        missing=missing or [],
    )


# ---------------------------------------------------------------------------
# 1. Technical override -> REJECT(UNSUPPORTED_RFC_NAME)
# ---------------------------------------------------------------------------


def test_select_capability_rejects_rfc_name_technical_override():
    parsed = IntentParseResult(
        intent=None,
        parameters={},
        missing_parameters=[],
        contains_rfc_name=True,
    )
    decision = select_capability(parsed)

    assert isinstance(decision, MatchDecision)
    assert decision.decision_type == "REJECT"
    assert decision.error_type == "UNSUPPORTED_RFC_NAME"
    assert decision.capability_id is None
    assert "rfcName" in decision.rationale or "OData" in decision.rationale


def test_select_capability_rejects_odata_override():
    parsed = IntentParseResult(
        intent=None,
        parameters={},
        missing_parameters=[],
        contains_odata_override=True,
    )
    decision = select_capability(parsed)

    assert decision.decision_type == "REJECT"
    assert decision.error_type == "UNSUPPORTED_RFC_NAME"


def test_rfc_name_takes_precedence_over_multi_intent():
    """Decision tree order: technical override is checked before ESCALATE."""
    parsed = IntentParseResult(
        intent=None,
        parameters={},
        missing_parameters=[],
        contains_rfc_name=True,
        matched_intents=[_inventory_matched(), _inventory_matched(material="OTHER")],
    )
    decision = select_capability(parsed)

    assert decision.decision_type == "REJECT"
    assert decision.error_type == "UNSUPPORTED_RFC_NAME"


# ---------------------------------------------------------------------------
# 2. matched_intents > 1 -> ESCALATE_TO_PLANNER(handoff)
# ---------------------------------------------------------------------------


def test_select_capability_escalates_when_multiple_matched_intents():
    matched = [
        _inventory_matched(plant="1000"),
        MatchedIntent(
            capability_id="MM.PurchaseOrder.GetList",
            parameters={"vendor": "DEMOV1"},
            missing=[],
        ),
    ]
    parsed = IntentParseResult(
        intent=None,
        parameters={},
        missing_parameters=[],
        matched_intents=matched,
    )
    decision = select_capability(parsed)

    assert decision.decision_type == "ESCALATE_TO_PLANNER"
    assert decision.handoff is not None
    assert isinstance(decision.handoff, EscalationHandoff)
    assert decision.handoff.reason  # non-empty reason
    assert decision.handoff.matched_intents == matched
    assert len(decision.handoff.matched_intents) == 2


def test_escalate_takes_precedence_over_ambiguous():
    """Decision tree order: multi-intent (len > 1) is checked before SHOW_OPTIONS."""
    matched = [
        _inventory_matched(),
        MatchedIntent(capability_id="MM.PurchaseOrder.GetList", parameters={}, missing=[]),
    ]
    # is_ambiguous=True but len > 1 -> ESCALATE wins per tree order.
    parsed = types.SimpleNamespace(
        intent=None,
        parameters={},
        missing_parameters=[],
        contains_rfc_name=False,
        contains_odata_override=False,
        capability_id=None,
        clarification=None,
        matched_intents=matched,
        is_ambiguous=True,
    )
    decision = select_capability(parsed)

    assert decision.decision_type == "ESCALATE_TO_PLANNER"


# ---------------------------------------------------------------------------
# 3. is_ambiguous (single goal, ambiguous) -> SHOW_OPTIONS(candidates)
# ---------------------------------------------------------------------------


def test_select_capability_show_options_when_ambiguous_single_match():
    """SHOW_OPTIONS fires when is_ambiguous=True with a non-empty matched_intents.

    Uses a SimpleNamespace because Task 2 did not add ``is_ambiguous`` to
    IntentParseResult; the selector reads it defensively. A future intent.py
    enhancement will populate the flag from the keyword-ambiguity threshold.
    """
    matched = [_inventory_matched(missing=["plant"])]
    parsed = types.SimpleNamespace(
        intent="inventory_availability",
        parameters={"material": "DEMOA1"},
        missing_parameters=["plant"],
        contains_rfc_name=False,
        contains_odata_override=False,
        capability_id="MM.Inventory.GetAvailability",
        clarification="请提供工厂。",
        matched_intents=matched,
        is_ambiguous=True,
    )
    decision = select_capability(parsed)

    assert decision.decision_type == "SHOW_OPTIONS"
    assert decision.candidates is not None
    assert decision.candidates == matched
    assert decision.capability_id is None


# ---------------------------------------------------------------------------
# 4. Single intent missing params -> CLARIFY(missing_parameters)
# ---------------------------------------------------------------------------


def test_select_capability_clarify_when_missing_parameters():
    parsed = IntentParseResult(
        intent="inventory_availability",
        parameters={"material": "DEMOA1"},
        missing_parameters=["plant"],
        clarification="请提供要查询的工厂。",
        capability_id="MM.Inventory.GetAvailability",
        matched_intents=[_inventory_matched(plant="1000", missing=["plant"]) if False else MatchedIntent(
            capability_id="MM.Inventory.GetAvailability",
            parameters={"material": "DEMOA1"},
            missing=["plant"],
        )],
    )
    decision = select_capability(parsed)

    assert decision.decision_type == "CLARIFY"
    assert decision.missing_parameters == ["plant"]
    # Task 10: CLARIFY carries capability_id + parameters so the workbench
    # LastContext preserves them for sticky continuation in the next turn.
    assert decision.capability_id == "MM.Inventory.GetAvailability"
    assert decision.parameters == {"material": "DEMOA1"}
    assert "工厂" in decision.rationale


def test_clarify_takes_precedence_over_select():
    """Decision tree order: missing params (CLARIFY) before complete (SELECT)."""
    parsed = IntentParseResult(
        intent="inventory_availability",
        parameters={"material": "DEMOA1"},
        missing_parameters=["plant"],
        clarification="请提供工厂。",
        capability_id="MM.Inventory.GetAvailability",
        matched_intents=[
            MatchedIntent(
                capability_id="MM.Inventory.GetAvailability",
                parameters={"material": "DEMOA1"},
                missing=["plant"],
            )
        ],
    )
    decision = select_capability(parsed)

    assert decision.decision_type == "CLARIFY"
    # Task 10: CLARIFY carries capability_id for sticky continuation.
    assert decision.capability_id == "MM.Inventory.GetAvailability"


# ---------------------------------------------------------------------------
# 5. Single intent complete -> SELECT(capability_id, parameters)
# ---------------------------------------------------------------------------


def test_select_capability_select_when_single_intent_complete_via_capability_id():
    parsed = IntentParseResult(
        intent="inventory_availability",
        parameters={"material": "DEMOA1", "plant": "1000"},
        missing_parameters=[],
        capability_id="MM.Inventory.GetAvailability",
        matched_intents=[_inventory_matched()],
    )
    decision = select_capability(parsed)

    assert decision.decision_type == "SELECT"
    assert decision.capability_id == "MM.Inventory.GetAvailability"
    assert decision.parameters == {"material": "DEMOA1", "plant": "1000"}


def test_select_capability_select_falls_back_to_intent_mapping():
    """When capability_id is None, INTENT_TO_CAPABILITY maps the intent name."""
    parsed = IntentParseResult(
        intent="purchase_order_list",
        parameters={"vendor": "DEMOV1"},
        missing_parameters=[],
        capability_id=None,
        matched_intents=[
            MatchedIntent(
                capability_id="MM.PurchaseOrder.GetList",
                parameters={"vendor": "DEMOV1"},
                missing=[],
            )
        ],
    )
    decision = select_capability(parsed)

    assert decision.decision_type == "SELECT"
    assert decision.capability_id == "MM.PurchaseOrder.GetList"
    assert decision.parameters == {"vendor": "DEMOV1"}


# ---------------------------------------------------------------------------
# 6. No match -> REJECT(UNSUPPORTED_INTENT)
# ---------------------------------------------------------------------------


def test_select_capability_rejects_unsupported_intent_when_no_match():
    parsed = IntentParseResult(
        intent=None,
        parameters={},
        missing_parameters=[],
        matched_intents=[],
    )
    decision = select_capability(parsed)

    assert decision.decision_type == "REJECT"
    assert decision.error_type == "UNSUPPORTED_INTENT"
    assert decision.capability_id is None


# ---------------------------------------------------------------------------
# Return type contract
# ---------------------------------------------------------------------------


def test_select_capability_always_returns_match_decision():
    cases = [
        IntentParseResult(intent=None, parameters={}, missing_parameters=[], contains_rfc_name=True),
        IntentParseResult(
            intent=None,
            parameters={},
            missing_parameters=[],
            matched_intents=[_inventory_matched(), MatchedIntent(capability_id="MM.PurchaseOrder.GetList", parameters={}, missing=[])],
        ),
        IntentParseResult(
            intent="inventory_availability",
            parameters={"material": "X", "plant": "1000"},
            missing_parameters=[],
            capability_id="MM.Inventory.GetAvailability",
            matched_intents=[_inventory_matched()],
        ),
        IntentParseResult(intent=None, parameters={}, missing_parameters=[], matched_intents=[]),
    ]
    for parsed in cases:
        decision = select_capability(parsed)
        assert isinstance(decision, MatchDecision), f"expected MatchDecision, got {type(decision)}"

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


# ---------------------------------------------------------------------------
# Task 3 (Q3): LLM empty return with clarification -> CLARIFY (not REJECT)
# ---------------------------------------------------------------------------


def test_select_emits_clarify_when_llm_clarification_present():
    """LLM path empty return carries clarification -> CLARIFY (not REJECT)."""
    parse_result = IntentParseResult(
        intent=None,
        parameters={},
        missing_parameters=[],
        clarification="无法识别查询意图，请明确物料、工厂等信息",
        capability_id=None,
    )
    decision = select_capability(parse_result)
    assert decision.decision_type == "CLARIFY"
    assert decision.rationale == "无法识别查询意图，请明确物料、工厂等信息"


def test_select_emits_reject_when_no_clarification():
    """Rule path empty return has no clarification -> still REJECT (not CLARIFY)."""
    parse_result = IntentParseResult(
        intent=None,
        parameters={},
        missing_parameters=[],
        clarification=None,
        capability_id=None,
    )
    decision = select_capability(parse_result)
    assert decision.decision_type == "REJECT"
    assert decision.error_type == "UNSUPPORTED_INTENT"


def test_select_emits_reject_when_rfc_name_flag_present_even_with_clarification():
    """rfcName/OData flag path is REJECT at step 1 (technical override),
    even if clarification were set (it isn't, but defensive test)."""
    parse_result = IntentParseResult(
        intent=None,
        parameters={},
        missing_parameters=[],
        clarification="some clarification",
        capability_id=None,
        contains_rfc_name=True,
    )
    decision = select_capability(parse_result)
    assert decision.decision_type == "REJECT"
    assert decision.error_type == "UNSUPPORTED_RFC_NAME"


def test_select_emits_reject_when_odata_flag_present():
    """OData override flag -> REJECT at step 1 (technical override), not CLARIFY."""
    parse_result = IntentParseResult(
        intent=None,
        parameters={},
        missing_parameters=[],
        clarification="some clarification",
        capability_id=None,
        contains_odata_override=True,
    )
    decision = select_capability(parse_result)
    assert decision.decision_type == "REJECT"
    assert decision.error_type == "UNSUPPORTED_RFC_NAME"


# ---------------------------------------------------------------------------
# Task 6: multi_parameters satisfies required inputs (Design Doc §4.3)
# ---------------------------------------------------------------------------


def test_select_satisfied_by_multi_parameters():
    """Required params in multi_parameters count as provided -> SELECT (not CLARIFY).

    Design Doc §4.3: a required parameter is satisfied if present in
    ``parameters`` OR ``multi_parameters``. ``MatchDecision.parameters`` still
    carries only single-value ``parameters`` (multi_parameters is read from
    ``parsed`` directly by the orchestrator in Task 8).
    """
    parse_result = IntentParseResult(
        intent=None,
        parameters={},
        missing_parameters=[],
        capability_id="MM.Inventory.GetAvailability",
        multi_parameters={"plant": ["5200", "1000"], "material": ["DEMOA2"]},
    )
    decision = select_capability(parse_result)
    assert decision.decision_type == "SELECT"
    assert decision.capability_id == "MM.Inventory.GetAvailability"
    assert decision.parameters == {}  # multi_parameters 不进 MatchDecision.parameters
    assert decision.missing_parameters is None or decision.missing_parameters == []


def test_select_clarify_when_multi_parameters_partial():
    """multi_parameters 只覆盖部分 required -> 仍 CLARIFY。"""
    parse_result = IntentParseResult(
        intent=None,
        parameters={},
        missing_parameters=[],
        capability_id="MM.Inventory.GetAvailability",
        multi_parameters={"plant": ["5200"]},  # material 缺失
    )
    decision = select_capability(parse_result)
    assert decision.decision_type == "CLARIFY"
    assert "material" in (decision.missing_parameters or [])


def test_select_parameters_excludes_multi_parameters():
    """MatchDecision.parameters carries only single-value parameters;
    multi_parameters never leaks into MatchDecision.parameters even when
    both are present and together satisfy all required inputs."""
    parse_result = IntentParseResult(
        intent=None,
        parameters={"material": "DEMOA2"},
        missing_parameters=[],
        capability_id="MM.Inventory.GetAvailability",
        multi_parameters={"plant": ["5200", "1000"]},
    )
    decision = select_capability(parse_result)
    assert decision.decision_type == "SELECT"
    assert decision.parameters == {"material": "DEMOA2"}
    assert "plant" not in decision.parameters


# ---- Task 3: select_capability accepts VisibleCapabilitySet ----

from sap_nexus_agent.governed_context import VisibleCapabilitySet
from sap_nexus_agent.planner.capability_card import CapabilityCard, Governance


def _visible_card(capability_id: str, snapshot_id: str = "sha256:test") -> VisibleCapabilitySet:
    card = CapabilityCard(
        capability_id=capability_id,
        name=capability_id,
        governance=Governance(
            side_effect="none", requires_approval=False, data_classification="internal"
        ),
    )
    return VisibleCapabilitySet(cards=(card,), snapshot_id=snapshot_id, principal_id="user-1")


def test_select_capability_accepts_visible_capability_set():
    """select_capability with visible set filters matched_intents to visible only."""
    from sap_nexus_agent.intent import IntentParseResult
    from sap_nexus_agent.match_decision import MatchedIntent
    from sap_nexus_agent.capability_selector import select_capability

    parse_result = IntentParseResult(
        intent=None,
        parameters={},
        missing_parameters=[],
        matched_intents=[
            MatchedIntent(capability_id="MM.Inventory.GetAvailability", parameters={}, missing=[]),
            MatchedIntent(capability_id="MM.PurchaseOrder.GetList", parameters={}, missing=[]),
            MatchedIntent(capability_id="MM.Hidden.Capability", parameters={}, missing=[]),
        ],
    )
    # visible contains the two real capabilities; hidden is filtered out.
    visible = VisibleCapabilitySet(
        cards=(
            CapabilityCard(
                capability_id="MM.Inventory.GetAvailability",
                name="inv",
                governance=Governance(
                    side_effect="none", requires_approval=False, data_classification="internal"
                ),
            ),
            CapabilityCard(
                capability_id="MM.PurchaseOrder.GetList",
                name="po",
                governance=Governance(
                    side_effect="none", requires_approval=False, data_classification="internal"
                ),
            ),
        ),
        snapshot_id="sha256:snap-1",
        principal_id="user-1",
    )
    decision = select_capability(parse_result, visible=visible)
    assert decision.decision_type == "ESCALATE_TO_PLANNER"
    assert decision.handoff is not None
    assert decision.handoff.registry_snapshot_id == "sha256:snap-1"
    visible_in_handoff = [mi.capability_id for mi in decision.handoff.matched_intents]
    assert "MM.Hidden.Capability" not in visible_in_handoff
    assert len(visible_in_handoff) == 2


def test_select_capability_without_visible_backward_compat():
    """select_capability without visible param behaves as before (backward compat)."""
    from sap_nexus_agent.intent import IntentParseResult
    from sap_nexus_agent.capability_selector import select_capability

    parse_result = IntentParseResult(
        intent="inventory_availability",
        parameters={"material": "M1", "plant": "P1"},
        missing_parameters=[],
    )
    decision = select_capability(parse_result)
    assert decision.decision_type == "SELECT"


# ---- Task 4: handoff.registry_snapshot_id non-empty when visible provided ----


def test_handoff_snapshot_id_is_non_empty_when_visible_provided():
    """EscalationHandoff.registry_snapshot_id non-empty when visible provided."""
    from sap_nexus_agent.intent import IntentParseResult
    from sap_nexus_agent.match_decision import MatchedIntent
    from sap_nexus_agent.capability_selector import select_capability
    from sap_nexus_agent.governed_context import VisibleCapabilitySet

    parse_result = IntentParseResult(
        intent=None,
        parameters={},
        missing_parameters=[],
        matched_intents=[
            MatchedIntent(capability_id="MM.Inventory.GetAvailability", parameters={}, missing=[]),
            MatchedIntent(capability_id="MM.PurchaseOrder.GetList", parameters={}, missing=[]),
        ],
    )
    visible = VisibleCapabilitySet(
        cards=(
            CapabilityCard(
                capability_id="MM.Inventory.GetAvailability",
                name="Inv",
                governance=Governance(
                    side_effect="none", requires_approval=False, data_classification="internal"
                ),
            ),
            CapabilityCard(
                capability_id="MM.PurchaseOrder.GetList",
                name="PO",
                governance=Governance(
                    side_effect="none", requires_approval=False, data_classification="internal"
                ),
            ),
        ),
        snapshot_id="sha256:snap-42",
        principal_id="user-1",
    )
    decision = select_capability(parse_result, visible=visible)
    assert decision.decision_type == "ESCALATE_TO_PLANNER"
    assert decision.handoff is not None
    assert decision.handoff.registry_snapshot_id == "sha256:snap-42"
    assert decision.handoff.registry_snapshot_id != ""


def test_handoff_snapshot_id_empty_when_no_visible():
    """Without visible, handoff.registry_snapshot_id falls back to default (backward compat)."""
    from sap_nexus_agent.intent import IntentParseResult
    from sap_nexus_agent.match_decision import MatchedIntent
    from sap_nexus_agent.capability_selector import select_capability

    parse_result = IntentParseResult(
        intent=None,
        parameters={},
        missing_parameters=[],
        matched_intents=[
            MatchedIntent(capability_id="A", parameters={}, missing=[]),
            MatchedIntent(capability_id="B", parameters={}, missing=[]),
        ],
    )
    decision = select_capability(parse_result)
    assert decision.decision_type == "ESCALATE_TO_PLANNER"
    assert decision.handoff is not None
    assert decision.handoff.registry_snapshot_id == ""


def test_select_capability_rejects_non_visible_capability_id():
    """SELECT path REJECTs capability_id not in visible set (defense-in-depth)."""
    from sap_nexus_agent.intent import IntentParseResult
    from sap_nexus_agent.capability_selector import select_capability

    parse_result = IntentParseResult(
        intent="inventory_availability",
        parameters={"material": "M1", "plant": "P1"},
        missing_parameters=[],
    )
    # visible set contains only PO, not inventory -> SELECT inventory should REJECT
    visible = VisibleCapabilitySet(
        cards=(
            CapabilityCard(
                capability_id="MM.PurchaseOrder.GetList",
                name="PO",
                governance=Governance(
                    side_effect="none", requires_approval=False, data_classification="internal"
                ),
            ),
        ),
        snapshot_id="sha256:snap",
        principal_id="user-1",
    )
    decision = select_capability(parse_result, visible=visible)
    assert decision.decision_type == "REJECT"
    assert decision.error_type == "VISIBILITY_DENIED"


# Runbook 14: select_capability_from_envelope with replay fields.
def test_select_from_envelope_select_carries_replay_fields():
    """SELECT decision carries envelope_id + recall + rerank + discard."""
    from sap_nexus_agent.capability_selector import select_capability_from_envelope
    from sap_nexus_agent.intent_envelope import IntentEnvelope, IntentGoal

    goal = IntentGoal(
        goal_text="查库存",
        capability_hint="MM.Inventory.GetAvailability",
        parameters={"material": "DEMOA2", "plant": "1000"},
        missing=[],
    )
    envelope = IntentEnvelope(
        envelope_id="env-001",
        utterance="查库存 DEMOA2 1000",
        goals=(goal,),
        user_constraints={},
        ambiguities=[],
        reference_turn_id=None,
        model_evidence={},
        snapshot_id="snap-001",
        discard_reasons=[],
        created_by="llm",
    )
    recall_candidates = ["MM.Inventory.GetAvailability"]
    rerank_evidence = (
        {"capabilityId": "MM.Inventory.GetAvailability", "score": 6, "components": {"llm_hint": 3, "lexical": 2, "param_fit": 1}},
    )
    decision = select_capability_from_envelope(
        envelope,
        recall_candidates=recall_candidates,
        rerank_evidence=rerank_evidence,
    )
    assert decision.decision_type == "SELECT"
    assert decision.capability_id == "MM.Inventory.GetAvailability"
    assert decision.envelope_id == "env-001"
    assert decision.recall_candidates == ("MM.Inventory.GetAvailability",)
    assert len(decision.rerank_evidence) == 1
    assert decision.discard_reasons == ()


def test_select_from_envelope_clarify_missing_params():
    """Single goal with missing required params -> CLARIFY."""
    from sap_nexus_agent.capability_selector import select_capability_from_envelope
    from sap_nexus_agent.intent_envelope import IntentEnvelope, IntentGoal

    goal = IntentGoal(
        goal_text="查库存",
        capability_hint="MM.Inventory.GetAvailability",
        parameters={"material": "DEMOA2"},  # plant missing
        missing=["plant"],
    )
    envelope = IntentEnvelope(
        envelope_id="env-002",
        utterance="查库存 DEMOA2",
        goals=(goal,),
        user_constraints={},
        ambiguities=[],
        reference_turn_id=None,
        model_evidence={},
        snapshot_id="snap-001",
        discard_reasons=[],
        created_by="llm",
    )
    decision = select_capability_from_envelope(
        envelope,
        recall_candidates=["MM.Inventory.GetAvailability"],
        rerank_evidence=(),
    )
    assert decision.decision_type == "CLARIFY"
    assert "plant" in (decision.missing_parameters or [])


def test_select_from_envelope_reject_unknown_capability():
    """Goal with unknown capability_hint (not in visible) -> REJECT."""
    from sap_nexus_agent.capability_selector import select_capability_from_envelope
    from sap_nexus_agent.intent_envelope import IntentEnvelope, IntentGoal

    goal = IntentGoal(
        goal_text="x",
        capability_hint="Foo.Bar",
        parameters={},
        missing=[],
    )
    envelope = IntentEnvelope(
        envelope_id="env-003",
        utterance="x",
        goals=(goal,),
        user_constraints={},
        ambiguities=[],
        reference_turn_id=None,
        model_evidence={},
        snapshot_id="snap-001",
        discard_reasons=["unknown_capability:Foo.Bar"],
        created_by="llm",
    )
    decision = select_capability_from_envelope(
        envelope,
        recall_candidates=[],
        rerank_evidence=(),
        visible_capability_ids=frozenset(("MM.Inventory.GetAvailability",)),
    )
    assert decision.decision_type == "REJECT"
    assert "unknown_capability:Foo.Bar" in decision.discard_reasons


def test_select_from_envelope_escalate_multi_goal():
    """Multiple goals -> ESCALATE_TO_PLANNER."""
    from sap_nexus_agent.capability_selector import select_capability_from_envelope
    from sap_nexus_agent.intent_envelope import IntentEnvelope, IntentGoal

    g1 = IntentGoal(goal_text="库存", capability_hint="MM.Inventory.GetAvailability", parameters={"material": "DEMOA2", "plant": "1000"}, missing=[])
    g2 = IntentGoal(goal_text="采购订单", capability_hint="MM.PurchaseOrder.GetList", parameters={"poNumber": "4500000001"}, missing=[])
    envelope = IntentEnvelope(
        envelope_id="env-004",
        utterance="库存 + 采购订单",
        goals=(g1, g2),
        user_constraints={},
        ambiguities=[],
        reference_turn_id=None,
        model_evidence={},
        snapshot_id="snap-001",
        discard_reasons=[],
        created_by="llm",
    )
    decision = select_capability_from_envelope(
        envelope,
        recall_candidates=["MM.Inventory.GetAvailability", "MM.PurchaseOrder.GetList"],
        rerank_evidence=(),
    )
    assert decision.decision_type == "ESCALATE_TO_PLANNER"
    assert decision.handoff is not None
    assert len(decision.handoff.matched_intents) == 2


def test_select_from_envelope_reject_technical_field():
    """Envelope with discard_reasons containing technical_field -> REJECT."""
    from sap_nexus_agent.capability_selector import select_capability_from_envelope
    from sap_nexus_agent.intent_envelope import IntentEnvelope

    envelope = IntentEnvelope(
        envelope_id="env-005",
        utterance="rfcName=BAPI_X",
        goals=(),
        user_constraints={},
        ambiguities=[],
        reference_turn_id=None,
        model_evidence={},
        snapshot_id="snap-001",
        discard_reasons=["technical_field:rfcName"],
        created_by="rule",
    )
    decision = select_capability_from_envelope(
        envelope,
        recall_candidates=[],
        rerank_evidence=(),
    )
    assert decision.decision_type == "REJECT"
    assert "technical_field:rfcName" in decision.discard_reasons


# ---- T5 task 7.1: a derivable parameter is not asked; the decision escalates ----
#
# Before this, the planner could derive `unit` and `purchasing_group` (6.1's table
# fell from 4 to 2) but no conversational entry point reached that plan: the
# selector still listed both in `missing_parameters` and returned CLARIFY, so the
# user was asked for values the system could have read. The feature was half
# delivered.
#
# A derivable parameter is dropped from `missing_parameters`, and because deriving
# requires an upstream node plus a data edge (invariant 2), the decision escalates
# to ESCALATE_TO_PLANNER rather than becoming a SELECT the single-capability
# CallPlan path could not honour.
#
# Derivability is decided by reading the registry only - `satisfiableByFactType`
# plus an active auto-pullable producer - never by calling anything. Task 5.8's
# audit covers that: `derivation` performs no data fetch.


def _pr_parse_result(**overrides):
    from types import SimpleNamespace

    base = dict(
        intent="pr_create",
        capability_id="MM.PR.CreateDraft",
        parameters={
            "material": "DEMOA2",
            "plant": "5100",
            "quantity": "10",
            "delivery_date": "2026-09-30",
        },
        missing_parameters=["unit", "purchasing_group"],
        matched_intents=[],
        multi_parameters={},
        clarification=None,
        contains_rfc_name=False,
        contains_odata_override=False,
        is_ambiguous=False,
        utterance="给 DEMOA2 在 5100 建一张采购申请，数量 10，交货日期 2026-09-30",
        registry_snapshot_id="",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_a_derivable_parameter_is_not_asked_and_escalates_to_the_planner():
    """Task 7.1 — the conversational half of the feature.

    Both remaining "missing" parameters are derivable from
    `sapnexus:MaterialInfoFact`, so neither is asked and the decision escalates so
    a two-node plan can be authored.
    """
    decision = select_capability(_pr_parse_result())

    assert decision.decision_type == "ESCALATE_TO_PLANNER"
    assert decision.missing_parameters == []
    assert decision.handoff is not None
    assert [m.capability_id for m in decision.handoff.matched_intents] == [
        "MM.PR.CreateDraft"
    ]
    assert decision.handoff.matched_intents[0].parameters == {
        "material": "DEMOA2",
        "plant": "5100",
        "quantity": "10",
        "delivery_date": "2026-09-30",
    }


def test_a_non_derivable_missing_parameter_still_clarifies():
    """The escalation must not swallow a genuinely unanswerable gap.

    `quantity` has no upstream producer — no SAP read can say how many the user
    wants — so omitting it must still produce CLARIFY, and the CLARIFY must name
    `quantity` alone rather than the derivable pair alongside it.
    """
    decision = select_capability(
        _pr_parse_result(
            parameters={
                "material": "DEMOA2",
                "plant": "5100",
                "delivery_date": "2026-09-30",
            },
            missing_parameters=["quantity", "unit", "purchasing_group"],
        )
    )

    assert decision.decision_type == "CLARIFY"
    assert decision.missing_parameters == ["quantity"]


def test_nothing_escalates_when_no_parameter_was_derivable():
    """Non-vacuity guard: the escalation is caused by derivability, not by mood.

    An inventory query with a genuinely missing `plant` has no derivable input at
    all, so it must still CLARIFY. If this went to the planner, the previous test
    would prove nothing about *why* the PR case escalated.
    """
    decision = select_capability(
        _pr_parse_result(
            intent="inventory_availability",
            capability_id="MM.Inventory.GetAvailability",
            parameters={"material": "DEMOA1"},
            missing_parameters=["plant"],
        )
    )

    assert decision.decision_type == "CLARIFY"
    assert decision.missing_parameters == ["plant"]

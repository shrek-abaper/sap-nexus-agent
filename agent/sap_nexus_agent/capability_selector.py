from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sap_nexus_agent.intent import IntentParseResult

if TYPE_CHECKING:
    # Type-only import: avoids a circular import at runtime
    # (capability_selector -> match_decision -> capability_selector). The
    # runtime import is done lazily inside select_capability, mirroring the
    # pattern used in intent.py for the same cycle.
    from sap_nexus_agent.match_decision import EscalationHandoff, MatchDecision, MatchedIntent


# Intent -> capabilityId closed set. The Agent never senses the executor type
# (JCO_RFC / ODATA); executor routing is the Gateway dispatcher's job.
INTENT_TO_CAPABILITY = {
    "inventory_availability": "MM.Inventory.GetAvailability",
    "purchase_order_list": "MM.PurchaseOrder.GetList",
    "pr_create": "MM.PR.CreateDraft",
}

# Inventory capability id, retained for the LLM path (still inventory-only until
# the orchestrator unified-entry refactor in Plan Task 10).
CAPABILITY_ID = "MM.Inventory.GetAvailability"


@dataclass(frozen=True)
class SelectionResult:
    """Legacy narrow-view result (SELECT/CLARIFY/REJECT).

    Retained for the ``to_selection_result()`` compat bridge on MatchDecision.
    One release cycle of compat, then evaluate removal.
    """

    capability_id: str | None
    error_type: str | None = None
    message: str | None = None


def select_capability(parse_result: IntentParseResult) -> MatchDecision:
    """Five-state capability match decision (Design Doc § selector).

    Decision tree (order-sensitive):

    1. Technical override (rfcName / OData) -> REJECT(UNSUPPORTED_RFC_NAME)
    2. matched_intents > 1                 -> ESCALATE_TO_PLANNER(handoff)
    3. Keyword ambiguity (is_ambiguous)    -> SHOW_OPTIONS(candidates)
    4. Single intent missing params        -> CLARIFY(missing_parameters)
    5. Single intent complete              -> SELECT(capability_id, parameters)
    6. No match                            -> REJECT(UNSUPPORTED_INTENT)

    ``is_ambiguous`` is read defensively (``getattr`` default False): Task 2
    did not add the flag to IntentParseResult, so SHOW_OPTIONS is currently
    unreachable from real rule/LLM input. A future intent.py enhancement
    populating the flag (keyword-ambiguity threshold) will activate the branch.
    """
    # Lazy import breaks the capability_selector <-> match_decision cycle.
    from sap_nexus_agent.match_decision import EscalationHandoff, MatchDecision

    # 1. Technical-override rejection (rfcName / OData injection) takes priority -
    #    same semantics as the Java-side CapabilityRequest guard (Task 6).
    if parse_result.contains_rfc_name or parse_result.contains_odata_override:
        return MatchDecision(
            decision_type="REJECT",
            error_type="UNSUPPORTED_RFC_NAME",
            rationale="Agent 不接受 rfcName 或 OData 技术覆盖，只能从已注册能力闭集选择。",
        )

    # 2. Multi-intent -> escalate to planner (composition required, D-1 fix).
    if len(parse_result.matched_intents) > 1:
        return MatchDecision(
            decision_type="ESCALATE_TO_PLANNER",
            handoff=EscalationHandoff(
                reason="multi-intent",
                matched_intents=list(parse_result.matched_intents),
                # utterance / registry_snapshot_id are not yet carried by
                # IntentParseResult (Task 2 did not add them). Read defensively
                # so a future enhancement populates them without a selector
                # signature change.
                utterance=getattr(parse_result, "utterance", ""),
                registry_snapshot_id=getattr(parse_result, "registry_snapshot_id", ""),
            ),
            rationale=f"matched {len(parse_result.matched_intents)} capabilities; planner composition required",
        )

    # 3. Keyword ambiguity (weak match, single goal, multi candidates) ->
    #    SHOW_OPTIONS. Defensive getattr: Task 2 did not populate is_ambiguous.
    if getattr(parse_result, "is_ambiguous", False) and parse_result.matched_intents:
        return MatchDecision(
            decision_type="SHOW_OPTIONS",
            candidates=list(parse_result.matched_intents),
            rationale="utterance 弱匹配多能力关键词，需用户明确主意图",
        )

    # 4. Single intent missing required parameters -> CLARIFY.
    #
    # Task 10: CLARIFY now carries ``capability_id`` + ``parameters`` so the
    # workbench LastContext (used by sticky continuation in turn N+1) preserves
    # the matched capability and any partial params the user already supplied.
    # Without this, ``resolve_with_context`` in the next turn sees
    # ``capability_id=None`` -> catalog miss -> single-turn fallback -> REJECT,
    # breaking the core multi-turn flow. The capability id is derived with the
    # same fallback chain as the SELECT branch below.
    if parse_result.missing_parameters:
        clarify_cap_id = parse_result.capability_id
        if not clarify_cap_id and parse_result.matched_intents:
            clarify_cap_id = parse_result.matched_intents[0].capability_id
        if not clarify_cap_id:
            clarify_cap_id = INTENT_TO_CAPABILITY.get(parse_result.intent)
        return MatchDecision(
            decision_type="CLARIFY",
            capability_id=clarify_cap_id,
            parameters=dict(parse_result.parameters),
            missing_parameters=list(parse_result.missing_parameters),
            rationale=parse_result.clarification or "请补充缺失的参数",
        )

    # 5. Single intent complete -> SELECT.
    capability_id = parse_result.capability_id or INTENT_TO_CAPABILITY.get(parse_result.intent)
    if capability_id:
        return MatchDecision(
            decision_type="SELECT",
            capability_id=capability_id,
            parameters=dict(parse_result.parameters),
            rationale="single capability matched with complete parameters",
        )

    # 6. No match -> REJECT(UNSUPPORTED_INTENT).
    return MatchDecision(
        decision_type="REJECT",
        error_type="UNSUPPORTED_INTENT",
        rationale="当前仅支持已注册的能力（库存可用量查询、采购订单列表、采购申请草稿创建）。",
    )

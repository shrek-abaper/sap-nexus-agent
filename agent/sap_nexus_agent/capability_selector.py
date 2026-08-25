from __future__ import annotations

import dataclasses
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sap_nexus_agent.intent import IntentParseResult

if TYPE_CHECKING:
    # Type-only import: avoids a circular import at runtime
    # (capability_selector -> match_decision -> capability_selector). The
    # runtime import is done lazily inside select_capability, mirroring the
    # pattern used in intent.py for the same cycle.
    from sap_nexus_agent.governed_context import VisibleCapabilitySet
    from sap_nexus_agent.intent_envelope import IntentEnvelope
    from sap_nexus_agent.match_decision import EscalationHandoff, MatchDecision, MatchedIntent


def _is_derivable_input(capability_id: str, input_name: str) -> bool:
    """Whether the planner can bind ``input_name`` from an upstream capability.

    T5 task 7.1. Decided by **reading the registry**: the derived data-dependency
    view already answers exactly this question — it pairs a consumer input that
    declares ``satisfiableByFactType`` with a producer output whose
    ``semanticType`` matches — so the selector reuses that authority instead of
    reimplementing the rule and letting the two drift.

    Invariant 2 holds: `derivation` reads the governed source documents and
    performs no Gateway, RFC or OData call, which task 5.8's audit asserts as a
    file-level lock. This is a declaration lookup, not a data fetch.

    Fails closed on any load or derivation error: an input that cannot be proven
    derivable is treated as not derivable, so the user is asked rather than
    silently left with an unbindable parameter.
    """
    try:
        from pathlib import Path

        from sap_nexus_agent.semantic_planning import load_semantic_sources
        from sap_nexus_agent.semantic_planning.derivation import (
            derive_data_dependencies,
        )

        repo_root = Path(__file__).resolve().parents[2]
        view = derive_data_dependencies(load_semantic_sources(repo_root))
    except Exception:  # noqa: BLE001 - fail closed, ask the user
        return False
    return any(
        edge.consumer_capability_id == capability_id
        and edge.consumer_input_name == input_name
        for edge in view.edges
    )


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


def build_read_context_candidates(utterance, descriptor, envelope):
    """Combine Frame v2 extraction with independent deterministic rule evidence."""
    from sap_nexus_agent.context_candidates import (
        ContextCandidate,
        ContextCandidateSet,
        SlotCandidates,
        extract_context_candidates,
        is_semantically_valid,
    )
    from sap_nexus_agent.intent import parse_intent

    extracted = extract_context_candidates(utterance, descriptor, envelope)
    deterministic = parse_intent(utterance)
    slots = dict(extracted.slots)
    inputs = {input_.name: input_ for input_ in descriptor.inputs}
    for name, value in deterministic.parameters.items():
        input_ = inputs.get(name)
        if input_ is None or not is_semantically_valid(input_, value):
            continue
        current = slots.get(name, SlotCandidates(name, ()))
        candidate = ContextCandidate(name, value, "DETERMINISTIC_LABEL", None)
        candidates = current.candidates
        if candidate not in candidates:
            candidates = (*candidates, candidate)
        slots[name] = SlotCandidates(name, candidates)
    _prefer_explicit_plant_suffix(utterance, descriptor, slots)
    return ContextCandidateSet(
        slots=slots,
        clear_slots=extracted.clear_slots,
        discard_reasons=extracted.discard_reasons,
    )


def _prefer_explicit_plant_suffix(utterance, descriptor, slots):
    """Do not reuse a token labeled as a plant as an unlabeled material."""
    from sap_nexus_agent.context_candidates import SlotCandidates

    plant_names = {
        input_.name
        for input_ in descriptor.inputs
        if input_.semantic_type.lower().endswith("plant")
    }
    for plant_name in plant_names:
        plant_candidates = slots.get(plant_name)
        if plant_candidates is None:
            continue
        labeled = {
            (candidate.value, candidate.source_span)
            for candidate in plant_candidates.candidates
            if candidate.source_span is not None
            and re.match(
                r"\s*(?:工厂|plant)",
                utterance[candidate.source_span[1] :],
                flags=re.IGNORECASE,
            )
        }
        if not labeled:
            continue
        for name, slot in tuple(slots.items()):
            if name == plant_name:
                continue
            slots[name] = SlotCandidates(
                name,
                tuple(
                    candidate
                    for candidate in slot.candidates
                    if candidate.source == "MODEL_CANDIDATE"
                    or (candidate.value, candidate.source_span) not in labeled
                ),
            )


@dataclass(frozen=True)
class SelectionResult:
    """Legacy narrow-view result (SELECT/CLARIFY/REJECT).

    Retained for the ``to_selection_result()`` compat bridge on MatchDecision.
    One release cycle of compat, then evaluate removal.
    """

    capability_id: str | None
    error_type: str | None = None
    message: str | None = None


def select_capability(
    parse_result: IntentParseResult,
    visible: "VisibleCapabilitySet | None" = None,
) -> MatchDecision:
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
    from sap_nexus_agent.match_decision import (
        EscalationHandoff,
        MatchDecision,
        MatchedIntent,
    )

    # When a VisibleCapabilitySet is provided, filter matched_intents to
    # only visible capabilities (double-check; the catalog was already
    # pre-filtered). Also derive snapshot_id for the handoff from visible.
    visible_snapshot_id = ""
    visible_ids = frozenset()  # empty if no visible set provided
    if visible is not None:
        visible_ids = frozenset(c.capability_id for c in visible.cards)
        visible_snapshot_id = visible.snapshot_id
        if parse_result.matched_intents:
            filtered = [
                mi
                for mi in parse_result.matched_intents
                if mi.capability_id in visible_ids
            ]
            # Rebuild parse_result with filtered matched_intents. Support both
            # IntentParseResult (frozen dataclass) and test SimpleNamespace.
            if dataclasses.is_dataclass(parse_result):
                parse_result = dataclasses.replace(parse_result, matched_intents=filtered)
            else:
                from types import SimpleNamespace

                parse_result = SimpleNamespace(
                    **{**vars(parse_result), "matched_intents": filtered}
                )

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
                registry_snapshot_id=visible_snapshot_id or getattr(parse_result, "registry_snapshot_id", ""),
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
    #
    # Task 6: ``multi_parameters`` (Design Doc §4.3) also counts as provided.
    # The parser pre-computes ``missing_parameters`` from ``parameters`` only;
    # the selector adjusts here so a required param in ``multi_parameters`` no
    # longer triggers CLARIFY. Two paths:
    #   - parser's missing non-empty (rule path): drop entries now satisfied by
    #     ``multi_parameters``. Preserves parser business logic the descriptor
    #     cannot express (e.g., PO's synthetic "filter" required-at-least-one).
    #   - parser's missing empty (LLM path that set capability_id +
    #     multi_parameters only): recompute from the descriptor to catch
    #     required inputs the parser never checked.
    # ``getattr`` defensive read mirrors the ``is_ambiguous`` pattern: Task 5
    # added ``multi_parameters`` to IntentParseResult, but older test doubles
    # (SimpleNamespace) may not set it.
    multi_parameters = getattr(parse_result, "multi_parameters", {}) or {}
    provided_keys = set(parse_result.parameters.keys()) | set(multi_parameters.keys())
    if parse_result.missing_parameters:
        missing = [m for m in parse_result.missing_parameters if m not in provided_keys]
    else:
        missing = []
        capability_id_for_missing = parse_result.capability_id
        if not capability_id_for_missing and parse_result.matched_intents:
            capability_id_for_missing = parse_result.matched_intents[0].capability_id
        if capability_id_for_missing:
            # Lazy import to get descriptor inputs (avoids module-level registry IO).
            from sap_nexus_agent.registry_loader import load_intent_catalog
            descriptor = load_intent_catalog().find(capability_id_for_missing)
            if descriptor is not None:
                missing = [
                    inp.name
                    for inp in descriptor.inputs
                    if inp.required and inp.name not in provided_keys
                ]
    # T5 task 7.1: a parameter the planner can derive must not be asked.
    #
    # Until this, `missing_parameters` listed every unbound required input, so the
    # user was asked for `unit` and `purchasing_group` even though an upstream
    # capability publishes both. 6.1's reduction existed in the plan layer with no
    # conversational entry point reaching it.
    #
    # Derivable entries are removed here, and if any was removed the decision
    # escalates: deriving requires an upstream node plus a data edge in a
    # PlanGraph (invariant 2), which the single-capability SELECT/CallPlan path
    # cannot express. A genuinely unanswerable gap still clarifies.
    derivable_cap_id = parse_result.capability_id
    if not derivable_cap_id and parse_result.matched_intents:
        derivable_cap_id = parse_result.matched_intents[0].capability_id
    derivable: list[str] = []
    if missing and derivable_cap_id:
        derivable = [
            name
            for name in missing
            if _is_derivable_input(derivable_cap_id, name)
        ]
        if derivable:
            missing = [name for name in missing if name not in derivable]

    if not missing and derivable:
        return MatchDecision(
            decision_type="ESCALATE_TO_PLANNER",
            handoff=EscalationHandoff(
                reason="derived-parameter",
                matched_intents=[
                    MatchedIntent(
                        capability_id=derivable_cap_id,
                        parameters=dict(parse_result.parameters),
                        missing=[],
                    )
                ],
                utterance=getattr(parse_result, "utterance", ""),
                registry_snapshot_id=visible_snapshot_id
                or getattr(parse_result, "registry_snapshot_id", ""),
            ),
            missing_parameters=[],
            rationale=(
                "所有未提供的必需参数均可由上游能力推导，需规划器编排上游读取: "
                + ", ".join(derivable)
            ),
        )

    if missing:
        clarify_cap_id = parse_result.capability_id
        if not clarify_cap_id and parse_result.matched_intents:
            clarify_cap_id = parse_result.matched_intents[0].capability_id
        if not clarify_cap_id:
            clarify_cap_id = INTENT_TO_CAPABILITY.get(parse_result.intent)
        return MatchDecision(
            decision_type="CLARIFY",
            capability_id=clarify_cap_id,
            parameters=dict(parse_result.parameters),
            missing_parameters=missing,
            rationale=parse_result.clarification or "请补充缺失的参数",
        )

    # 5. Single intent complete -> SELECT.
    capability_id = parse_result.capability_id or INTENT_TO_CAPABILITY.get(parse_result.intent)
    if capability_id:
        if visible is not None and capability_id not in visible_ids:
            return MatchDecision(
                decision_type="REJECT",
                error_type="VISIBILITY_DENIED",
                rationale="matched capability is not visible to this principal",
            )
        return MatchDecision(
            decision_type="SELECT",
            capability_id=capability_id,
            parameters=dict(parse_result.parameters),
            rationale="single capability matched with complete parameters",
        )

    # 6. No match -> REJECT(UNSUPPORTED_INTENT). LLM 路径空返回带 clarification 时发 CLARIFY
    #    (rule 路径空返回无 clarification，仍走 REJECT)。
    if parse_result.clarification and not parse_result.capability_id:
        return MatchDecision(
            decision_type="CLARIFY",
            capability_id=None,
            parameters={},
            missing_parameters=[],
            rationale=parse_result.clarification,
        )

    return MatchDecision(
        decision_type="REJECT",
        error_type="UNSUPPORTED_INTENT",
        rationale="当前仅支持已注册的能力（库存可用量查询、采购订单列表、采购申请草稿创建）。",
    )


def select_capability_from_envelope(
    envelope: "IntentEnvelope",
    *,
    recall_candidates: list[str] | tuple[str, ...] = (),
    rerank_evidence: list[dict[str, object]] | tuple[dict[str, object], ...] = (),
    visible_capability_ids: "frozenset[str] | None" = None,
) -> "MatchDecision":
    """Runbook 14 envelope-driven selector.

    Consumes ``IntentEnvelope`` + recall candidates + rerank evidence and
    produces a five-state ``MatchDecision`` with replay fields populated.

    Decision tree (order-sensitive):

    1. Technical override (discard_reasons contains technical_field)
       -> REJECT(UNSUPPORTED_RFC_NAME) with discard_reasons
    2. All goals have unknown capability_hint (or no goals)
       -> REJECT(UNKNOWN_CAPABILITY) with discard_reasons
    3. Multiple goals with valid capability_hints
       -> ESCALATE_TO_PLANNER(handoff)
    4. Single goal with missing required params -> CLARIFY(missing_parameters)
    5. Single goal complete -> SELECT(capability_id, parameters)
    6. No goals / no valid hints -> REJECT(UNSUPPORTED_INTENT)

    Replay fields (``envelope_id`` / ``recall_candidates`` / ``rerank_evidence``
    / ``discard_reasons``) are always populated from the envelope.
    """
    from sap_nexus_agent.match_decision import (
        EscalationHandoff,
        MatchDecision,
        MatchedIntent,
    )

    envelope_id = envelope.envelope_id
    recall_tuple = tuple(recall_candidates)
    rerank_tuple = tuple(rerank_evidence)
    discard_tuple = tuple(envelope.discard_reasons)

    # 1. Technical override (rfcName / OData in discard_reasons).
    if any(r.startswith("technical_field:") for r in envelope.discard_reasons):
        return MatchDecision(
            decision_type="REJECT",
            error_type="UNSUPPORTED_RFC_NAME",
            rationale="技术字段覆盖被丢弃",
            envelope_id=envelope_id,
            recall_candidates=recall_tuple,
            rerank_evidence=rerank_tuple,
            discard_reasons=discard_tuple,
        )

    # Filter goals to those whose capability_hint is visible (if visibility
    # set was provided).
    if visible_capability_ids is not None:
        valid_goals = [
            g for g in envelope.goals
            if g.capability_hint and g.capability_hint in visible_capability_ids
        ]
    else:
        valid_goals = [
            g for g in envelope.goals if g.capability_hint
        ]

    # 2. No valid goals but discard_reasons has unknown_capability -> REJECT.
    if not valid_goals and any(r.startswith("unknown_capability:") for r in envelope.discard_reasons):
        return MatchDecision(
            decision_type="REJECT",
            error_type="UNKNOWN_CAPABILITY",
            rationale="LLM 候选能力不在可见闭集内",
            envelope_id=envelope_id,
            recall_candidates=recall_tuple,
            rerank_evidence=rerank_tuple,
            discard_reasons=discard_tuple,
        )

    # 3. Multiple valid goals -> ESCALATE_TO_PLANNER.
    if len(valid_goals) > 1:
        matched_intents = [
            MatchedIntent(
                capability_id=g.capability_hint,  # type: ignore[arg-type]
                parameters=dict(g.parameters),
                missing=list(g.missing),
            )
            for g in valid_goals
        ]
        handoff = EscalationHandoff(
            reason="multi-intent",
            matched_intents=matched_intents,
            utterance=envelope.utterance,
            registry_snapshot_id=envelope.snapshot_id,
        )
        return MatchDecision(
            decision_type="ESCALATE_TO_PLANNER",
            handoff=handoff,
            rationale="多个目标需要 planner 组合",
            envelope_id=envelope_id,
            recall_candidates=recall_tuple,
            rerank_evidence=rerank_tuple,
            discard_reasons=discard_tuple,
        )

    # 4. Single valid goal with missing params -> CLARIFY.
    if len(valid_goals) == 1:
        goal = valid_goals[0]
        if goal.missing:
            return MatchDecision(
                decision_type="CLARIFY",
                capability_id=goal.capability_hint,
                parameters=dict(goal.parameters),
                missing_parameters=list(goal.missing),
                rationale="缺少必需参数",
                envelope_id=envelope_id,
                recall_candidates=recall_tuple,
                rerank_evidence=rerank_tuple,
                discard_reasons=discard_tuple,
            )
        # 5. Single goal complete -> SELECT.
        return MatchDecision(
            decision_type="SELECT",
            capability_id=goal.capability_hint,
            parameters=dict(goal.parameters),
            missing_parameters=[],
            rationale="single capability matched with complete parameters",
            envelope_id=envelope_id,
            recall_candidates=recall_tuple,
            rerank_evidence=rerank_tuple,
            discard_reasons=discard_tuple,
        )

    # 6. No goals / no valid hints -> REJECT(UNSUPPORTED_INTENT).
    return MatchDecision(
        decision_type="REJECT",
        error_type="UNSUPPORTED_INTENT",
        rationale="当前仅支持已注册的能力（库存可用量查询、采购订单列表、采购申请草稿创建）。",
        envelope_id=envelope_id,
        recall_candidates=recall_tuple,
        rerank_evidence=rerank_tuple,
        discard_reasons=discard_tuple,
    )

from __future__ import annotations

from dataclasses import dataclass, field, replace
import re
import uuid
from typing import TYPE_CHECKING

from sap_nexus_agent.intent_envelope import IntentEnvelope, IntentGoal

if TYPE_CHECKING:
    # Type-only import: avoids a circular import at runtime
    # (intent -> match_decision -> capability_selector -> intent).
    # MatchedIntent is imported lazily inside parse_intent / parse_inventory_intent.
    from sap_nexus_agent.match_decision import MatchedIntent
    # Type-only import for the conversational context parameter (Task 2).
    # Avoids a circular import at runtime; ConversationContext is a pure
    # data model with no runtime dependency on intent.py.
    from sap_nexus_agent.conversation_context import ConversationContext


# OData / technical-override detection. Forms a double-layer defense with the
# Java-side CapabilityRequest guard (Task 6): Agent rejects first, Java rejects
# again. Covers raw OData URLs, OData query options, and technical safety fields
# that must never be supplied by the LLM / user.
#
# Field list mirrors the Java guard (Task 6 fix 9d57381): baseUrl/sapClient/
# csrf/token/authorization are included here too. The trailing \b is dropped so
# plural / compound forms (headers, credentialRef, credentials, serviceUrl,
# servicePath) are also caught, matching the Java guard's normalized
# contains/equals check. The leading \b is kept so a field name is not matched
# mid-token (e.g. inside a longer identifier).
_ODATA_OVERRIDE_PATTERN = re.compile(
    r"/sap/opu/odata"
    r"|\$(?:filter|select|top|skip|expand|count|orderby|search)"
    r"|\b(?:endpoint|method|header|credential|service|baseUrl|sapClient|csrf|token|authorization|destination|serviceRef|bindingId|entitySet|executorType)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class IntentParseResult:
    intent: str | None
    parameters: dict[str, str]
    missing_parameters: list[str]
    clarification: str | None = None
    contains_rfc_name: bool = False
    contains_odata_override: bool = False
    capability_id: str | None = None
    # D-1 fix: all capabilities whose keyword sets matched the utterance.
    # Empty for the rejection / unknown paths; length 1 for single-intent
    # (keeps existing extraction intact); length >1 for multi-intent (selector
    # in Task 3 emits ESCALATE_TO_PLANNER). Defaults to empty for backward
    # compatibility with existing callers that do not pass it.
    matched_intents: list[MatchedIntent] = field(default_factory=list)
    # Task 5.5: keyword ambiguity flag (Design Doc § 多意图检测 Q2). True when
    # the utterance weakly matches >=2 capabilities' keyword sets without a
    # clear primary intent (no primary keyword hit). The selector fires
    # SHOW_OPTIONS when is_ambiguous=True and matched_intents is non-empty
    # (length 1; length >1 triggers ESCALATE first per decision-tree order).
    is_ambiguous: bool = False
    # Multi-value parameters (Design Doc §4.2): any parameter can carry multiple
    # values. Orthogonal to ``parameters`` (single-valued). Default empty for
    # backward compatibility.
    multi_parameters: dict[str, list[str]] = field(default_factory=dict)


def parse_intent(
    text: str,
    context: "ConversationContext | None" = None,
) -> IntentParseResult:
    """Unified intent entry: scan ALL capability keyword sets, collect matched_intents.

    D-1 fix: previously this returned the first-matched intent in fixed order
    (inventory -> purchase_order -> pr_create), silently dropping other
    capabilities mentioned in the same utterance. Now it scans every keyword
    set independently and surfaces every match via ``matched_intents``; the
    selector (Task 3) decides ESCALATE_TO_PLANNER when length > 1.

    Task 2: ``context`` parameter is accepted for signature compatibility with
    the conversational adapter contract. When ``None`` (default) behavior is
    identical to the single-turn path (backward compatible).

    Task 3: when ``context`` is non-``None`` and carries a ``last_context``,
    the call is routed to ``llm_intent.resolve_with_context`` for sticky
    continuation (inherit ``last_context.capability_id`` and merge params).
    History injection is implemented in Task 4.
    """
    normalized = text.strip()
    contains_rfc_name = _detect_rfc_name(normalized)
    contains_odata_override = _detect_odata_override(normalized)

    # Technical override (rfcName / OData) takes priority over sticky
    # continuation and multi-intent collection (defense-in-depth, Design Doc
    # 边界4): rejection path, matched_intents stays empty. Task 3 concern 1:
    # catch this BEFORE sticky routing so a turn containing rfcName/OData
    # override does not slot-fill via last_context. The selector REJECTs on
    # contains_rfc_name/contains_odata_override without relying on the
    # gateway double-layer.
    if contains_rfc_name or contains_odata_override:
        return IntentParseResult(
            intent=None,
            parameters={},
            missing_parameters=[],
            contains_rfc_name=contains_rfc_name,
            contains_odata_override=contains_odata_override,
        )

    # Task 3: sticky continuation. When context carries a last_context, delegate
    # to resolve_with_context (lazy import avoids a circular dependency: llm_intent
    # imports parse_intent from this module at module level).
    if context is not None and context.last_context is not None:
        from sap_nexus_agent.llm_intent import resolve_with_context
        from sap_nexus_agent.registry_loader import load_intent_catalog

        return resolve_with_context(text, context, load_intent_catalog())

    return _parse_single_turn(normalized, contains_rfc_name, contains_odata_override)


def _parse_single_turn(
    normalized: str,
    contains_rfc_name: bool,
    contains_odata_override: bool,
) -> IntentParseResult:
    from sap_nexus_agent.extraction import engine
    from sap_nexus_agent.registry_loader import load_intent_catalog

    parsed = engine.parse_declared(
        normalized,
        load_intent_catalog(),
        contains_rfc_name=contains_rfc_name,
        contains_odata_override=contains_odata_override,
    )
    # Legacy compatibility: Inventory/PO single-turn results expose their
    # capability only through matched_intents[0].capability_id. Selector routing
    # still maps these intents to capability ids, and tests document this contract.
    if parsed.capability_id in {"MM.Inventory.GetAvailability", "MM.PurchaseOrder.GetList"}:
        return replace(parsed, capability_id=None)
    return parsed


def parse_inventory_intent(
    text: str,
    context: "ConversationContext | None" = None,
) -> IntentParseResult:
    """Backward-compatible inventory-only parser (does not route to PO)."""
    from sap_nexus_agent.extraction import engine
    from sap_nexus_agent.match_decision import MatchedIntent
    from sap_nexus_agent.registry_loader import load_intent_catalog

    normalized = text.strip()
    contains_rfc_name = _detect_rfc_name(normalized)
    contains_odata_override = _detect_odata_override(normalized)
    catalog = load_intent_catalog()
    cap = catalog.find("MM.Inventory.GetAvailability")

    if cap is None or cap.intent_config is None or not engine.triggered(normalized, cap):
        return IntentParseResult(
            intent=None,
            parameters={},
            missing_parameters=[],
            contains_rfc_name=contains_rfc_name,
            contains_odata_override=contains_odata_override,
            matched_intents=[],
        )

    single = engine.build_capability_result(
        normalized,
        cap,
        catalog,
        contains_rfc_name=contains_rfc_name,
        contains_odata_override=contains_odata_override,
    )
    return replace(
        single,
        matched_intents=[
            MatchedIntent(
                capability_id=cap.capability_id,
                parameters=single.parameters,
                missing=list(single.missing_parameters),
            )
        ],
    )


def _detect_rfc_name(text: str) -> bool:
    return bool(re.search(r"\brfcName\s*=", text, re.IGNORECASE))


def _detect_odata_override(text: str) -> bool:
    return bool(_ODATA_OVERRIDE_PATTERN.search(text))


def parse_intent_envelope(
    text: str,
    context: "ConversationContext | None" = None,
    *,
    snapshot_id: str = "",
) -> IntentEnvelope:
    """Rule-path intent parsing returning IntentEnvelope (created_by='rule').

    Runbook 14: reuses existing keyword extraction via ``parse_intent`` and
    converts the ``IntentParseResult`` to an ``IntentEnvelope``. Technical
    override (rfcName / OData) produces an envelope with empty goals and
    ``discard_reasons`` recording the violation. ``model_evidence`` is empty
    on the rule path (no LLM payload to summarize).
    """
    rule_payload = parse_intent(text, context=context)
    return _rule_payload_to_envelope(rule_payload, text, snapshot_id)


def _rule_payload_to_envelope(
    rule_payload: "IntentParseResult",
    utterance: str,
    snapshot_id: str,
) -> IntentEnvelope:
    """Convert an IntentParseResult (rule path) to IntentEnvelope."""
    discard_reasons: list[str] = []
    if rule_payload.contains_rfc_name:
        discard_reasons.append("technical_field:rfcName")
    if rule_payload.contains_odata_override:
        discard_reasons.append("technical_field:odata_override")

    goals: list[IntentGoal] = []
    for mi in rule_payload.matched_intents:
        goals.append(
            IntentGoal(
                goal_text=utterance,
                capability_hint=mi.capability_id,
                parameters=dict(mi.parameters),
                missing=list(mi.missing),
            )
        )

    return IntentEnvelope(
        envelope_id=uuid.uuid4().hex,
        utterance=utterance,
        goals=tuple(goals),
        user_constraints={},
        ambiguities=[],
        reference_turn_id=None,
        model_evidence={},  # rule path: empty model_evidence
        snapshot_id=snapshot_id,
        discard_reasons=discard_reasons,
        created_by="rule",
    )

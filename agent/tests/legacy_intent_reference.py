# FROZEN legacy oracle for differential parity. Deleted with the legacy path (tasks.md 4.3).
from __future__ import annotations

from dataclasses import replace

from sap_nexus_agent.conversation_context import ConversationContext
from sap_nexus_agent.intent import (
    INVENTORY_KEYWORDS,
    INVENTORY_PRIMARY_KEYWORDS,
    PURCHASE_ORDER_PRIMARY_KEYWORDS,
    PR_CREATE_PRIMARY_KEYWORDS,
    IntentParseResult,
    _PURCHASE_ORDER_KEYWORD_PATTERN,
    _build_inventory_result,
    _build_purchase_order_result,
    _detect_keyword_ambiguity,
    _detect_odata_override,
    _detect_rfc_name,
)
from sap_nexus_agent.llm_intent import _extract_params_for
from sap_nexus_agent.match_decision import MatchedIntent
from sap_nexus_agent.pr_intent import PR_CREATE_KEYWORDS, parse_pr_create_intent
from sap_nexus_agent.registry_loader import load_intent_catalog


_INVENTORY_CAPABILITY_ID = "MM.Inventory.GetAvailability"
_PURCHASE_ORDER_CAPABILITY_ID = "MM.PurchaseOrder.GetList"
_PR_CREATE_CAPABILITY_ID = "MM.PR.CreateDraft"


def parse(text: str, context=None) -> IntentParseResult:
    normalized = text.strip()
    contains_rfc_name = _detect_rfc_name(normalized)
    contains_odata_override = _detect_odata_override(normalized)

    if contains_rfc_name or contains_odata_override:
        return IntentParseResult(
            intent=None,
            parameters={},
            missing_parameters=[],
            contains_rfc_name=contains_rfc_name,
            contains_odata_override=contains_odata_override,
        )

    if context is not None and context.last_context is not None:
        return sticky(text, context)

    is_ambiguous = _detect_keyword_ambiguity(normalized)

    matches_inventory = any(keyword in normalized for keyword in INVENTORY_KEYWORDS)
    matches_po = _PURCHASE_ORDER_KEYWORD_PATTERN.search(normalized) is not None
    matches_pr = any(keyword in normalized for keyword in PR_CREATE_KEYWORDS)

    per_capability: list[tuple[str, IntentParseResult]] = []
    if matches_inventory:
        per_capability.append((
            _INVENTORY_CAPABILITY_ID,
            _build_inventory_result(normalized, contains_rfc_name, contains_odata_override),
        ))
    if matches_po:
        per_capability.append((
            _PURCHASE_ORDER_CAPABILITY_ID,
            _build_purchase_order_result(normalized, contains_rfc_name, contains_odata_override),
        ))
    if matches_pr:
        per_capability.append((
            _PR_CREATE_CAPABILITY_ID,
            parse_pr_create_intent(normalized),
        ))

    matched_intents = [
        MatchedIntent(
            capability_id=cap_id,
            parameters=res.parameters,
            missing=list(res.missing_parameters),
        )
        for cap_id, res in per_capability
    ]

    if len(per_capability) == 0:
        return IntentParseResult(
            intent=None,
            parameters={},
            missing_parameters=[],
            contains_rfc_name=contains_rfc_name,
            contains_odata_override=contains_odata_override,
            matched_intents=[],
            is_ambiguous=is_ambiguous,
        )

    if len(per_capability) == 1:
        _cap_id, single = per_capability[0]
        return IntentParseResult(
            intent=single.intent,
            parameters=single.parameters,
            missing_parameters=single.missing_parameters,
            clarification=single.clarification,
            contains_rfc_name=contains_rfc_name,
            contains_odata_override=contains_odata_override,
            capability_id=single.capability_id,
            matched_intents=matched_intents,
            is_ambiguous=is_ambiguous,
        )

    return IntentParseResult(
        intent=None,
        parameters={},
        missing_parameters=[],
        contains_rfc_name=contains_rfc_name,
        contains_odata_override=contains_odata_override,
        capability_id=None,
        matched_intents=matched_intents,
        is_ambiguous=is_ambiguous,
    )


def sticky(text: str, context: ConversationContext) -> IntentParseResult:
    catalog = load_intent_catalog()
    if context is None or context.last_context is None:
        return parse(text)

    if _contains_any_primary_keyword(text):
        parsed = parse(text)
        if (
            "material" not in parsed.parameters
            and context.last_context.parameters.get("material")
            and len(parsed.matched_intents) == 1
            and parsed.matched_intents[0].capability_id
            == context.last_context.capability_id
        ):
            new_params = dict(parsed.parameters)
            new_params["material"] = context.last_context.parameters["material"]
            new_missing = [m for m in parsed.missing_parameters if m != "material"]
            parsed = replace(
                parsed,
                parameters=new_params,
                missing_parameters=new_missing,
                clarification=None if not new_missing else parsed.clarification,
                capability_id=context.last_context.capability_id,
            )
        return parsed

    cap_id = context.last_context.capability_id
    descriptor = catalog.find(cap_id)
    if descriptor is None:
        return parse(text)

    extracted = _extract_params_for(cap_id, text)
    merged = {**context.last_context.parameters, **extracted}
    missing = [
        inp.name for inp in descriptor.inputs if inp.required and inp.name not in merged
    ]

    if (
        cap_id == _INVENTORY_CAPABILITY_ID
        and "material" not in extracted
        and "material" in (context.last_context.parameters or {})
        and __import__("re").search(r"[A-Za-z0-9][A-Za-z0-9-]{4,}", text)
    ):
        merged = {k: v for k, v in merged.items() if k != "material"}
        missing = ["material"] + [m for m in missing if m != "material"]

    clarification = _legacy_sticky_clarify(cap_id, missing)
    return IntentParseResult(
        intent=None,
        capability_id=cap_id,
        parameters=merged,
        missing_parameters=missing,
        clarification=clarification,
        contains_rfc_name=False,
        contains_odata_override=False,
        matched_intents=[
            MatchedIntent(capability_id=cap_id, parameters=merged, missing=list(missing))
        ],
    )


def _contains_any_primary_keyword(text: str) -> bool:
    return any(
        any(kw in text for kw in keyword_set)
        for keyword_set in (
            INVENTORY_PRIMARY_KEYWORDS,
            PURCHASE_ORDER_PRIMARY_KEYWORDS,
            PR_CREATE_PRIMARY_KEYWORDS,
        )
    )


def _legacy_sticky_clarify(capability_id: str, missing: list[str]) -> str | None:
    if capability_id == "MM.Inventory.GetAvailability":
        if missing == ["material"]:
            return "请提供要查询的物料编号。"
        if missing == ["plant"]:
            return "请提供要查询的工厂。"
        if missing:
            return "请提供要查询的物料编号和工厂。"
        return None
    if missing:
        return f"请提供以下参数：{', '.join(missing)}。"
    return None

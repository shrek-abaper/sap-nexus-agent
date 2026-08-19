from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import replace
import re
from typing import TYPE_CHECKING, Final

from sap_nexus_agent.extraction._matching import input_filters, keyword_matches, match_value
from sap_nexus_agent.extraction.clarify import render_clarify
from sap_nexus_agent.extraction.resolvers import resolve
from sap_nexus_agent.registry_loader import (
    CapabilityDescriptor,
    IntentCatalog,
)

if TYPE_CHECKING:
    from sap_nexus_agent.conversation_context import ConversationContext
    from sap_nexus_agent.intent import IntentParseResult
    from sap_nexus_agent.match_decision import MatchedIntent

_SUSPECT_TOKEN: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{4,}")


def keyword_hits(text: str, cap: CapabilityDescriptor) -> tuple[bool, bool]:
    intent_config = cap.intent_config
    if intent_config is None:
        return False, False
    primary_hit = any(keyword_matches(keyword, text) for keyword in intent_config.primary_keywords)
    weak_hit = any(keyword_matches(keyword, text) for keyword in intent_config.weak_keywords)
    return primary_hit, weak_hit


def triggered(text: str, cap: CapabilityDescriptor) -> bool:
    intent_config = cap.intent_config
    if intent_config is None:
        return False
    keywords = intent_config.trigger_keywords or intent_config.primary_keywords
    return any(keyword_matches(keyword, text) for keyword in keywords)


def is_ambiguous(hits: Iterable[tuple[bool, bool]]) -> bool:
    hit_list = list(hits)
    matched = sum(1 for primary, weak in hit_list if primary or weak)
    primary = sum(1 for primary, _weak in hit_list if primary)
    return matched >= 2 and primary == 0


def any_primary_keyword(
    text: str,
    catalog: IntentCatalog,
    restrict_to: set[str] | None = None,
) -> bool:
    return any(
        keyword_matches(keyword, text)
        for cap in catalog.capabilities
        if cap.intent_config is not None
        and (restrict_to is None or cap.capability_id in restrict_to)
        for keyword in cap.intent_config.primary_keywords
    )


def extract_parameters(
    text: str,
    cap: CapabilityDescriptor,
    catalog: IntentCatalog,
    base: Mapping[str, str] | None = None,
) -> dict[str, str]:
    parameters = dict(base or {})
    ordered = [(idx, inp) for idx, inp in enumerate(cap.inputs) if inp.extraction is not None]
    ordered.sort(key=lambda pair: (-pair[1].extraction.priority, pair[0]))

    for _idx, inp in ordered:
        ext = inp.extraction
        if ext is None or (ext.when is not None and parameters.get(ext.when.field) != ext.when.equals):
            continue
        excluded_values = {
            parameters[other_name]
            for other_name in ext.excludes
            if other_name in parameters
        }
        for matcher in ext.matchers:
            filters = input_filters(matcher, catalog)
            value = match_value(matcher, text, catalog, filters, excluded_values)
            if value is not None:
                parameters[inp.name] = resolve(value, ext.resolver, filters)
                break
    return parameters


def missing_parameters(cap: CapabilityDescriptor, parameters: Mapping[str, str]) -> list[str]:
    missing = []
    for inp in cap.inputs:
        required_when = (
            inp.extraction is not None
            and inp.extraction.required_when is not None
            and parameters.get(inp.extraction.required_when.field) == inp.extraction.required_when.equals
        )
        if (inp.required or required_when) and inp.name not in parameters:
            missing.append(inp.name)

    intent_config = cap.intent_config
    if missing or intent_config is None or intent_config.require_any is None:
        return missing
    if not any(name in parameters for name in intent_config.require_any.inputs):
        return [intent_config.require_any.missing_name]
    return []


def build_capability_result(
    text: str,
    cap: CapabilityDescriptor,
    catalog: IntentCatalog,
    *,
    contains_rfc_name: bool = False,
    contains_odata_override: bool = False,
) -> "IntentParseResult":
    from sap_nexus_agent.intent import IntentParseResult

    intent_config = cap.intent_config
    if intent_config is None:
        return _empty_result(contains_rfc_name, contains_odata_override)
    parameters = extract_parameters(text, cap, catalog)
    missing = missing_parameters(cap, parameters)
    return IntentParseResult(
        intent=intent_config.intent_name,
        parameters=parameters,
        missing_parameters=missing,
        clarification=render_clarify(cap, missing),
        contains_rfc_name=contains_rfc_name,
        contains_odata_override=contains_odata_override,
        capability_id=cap.capability_id,
    )


def parse_declared(
    text: str,
    catalog: IntentCatalog,
    *,
    contains_rfc_name: bool,
    contains_odata_override: bool,
) -> "IntentParseResult":
    if contains_rfc_name or contains_odata_override:
        return _empty_result(contains_rfc_name, contains_odata_override)

    caps = [cap for cap in catalog.capabilities if cap.intent_config is not None]
    ambiguous = is_ambiguous(keyword_hits(text, cap) for cap in caps)
    per_capability = [
        (cap, build_capability_result(text, cap, catalog))
        for cap in caps
        if triggered(text, cap)
    ]
    matched_intents = _matched_intents(per_capability)

    if not per_capability:
        result = _empty_result(contains_rfc_name, contains_odata_override)
        return replace(result, is_ambiguous=ambiguous)
    if len(per_capability) == 1:
        _cap, single = per_capability[0]
        return replace(single, matched_intents=matched_intents, is_ambiguous=ambiguous)
    return _multi_result(contains_rfc_name, contains_odata_override, matched_intents, ambiguous)


def sticky_parse(text: str, context: "ConversationContext", catalog: IntentCatalog) -> "IntentParseResult":
    if context is None or context.last_context is None:
        return parse_declared(text, catalog, contains_rfc_name=False, contains_odata_override=False)

    if any_primary_keyword(text, catalog):
        parsed = parse_declared(text, catalog, contains_rfc_name=False, contains_odata_override=False)
        return _inherit_material_for_same_capability(parsed, context, catalog)

    cap_id = context.last_context.capability_id
    descriptor = catalog.find(cap_id)
    if descriptor is None:
        return parse_declared(text, catalog, contains_rfc_name=False, contains_odata_override=False)

    extracted = extract_parameters(text, descriptor, catalog)
    merged = extract_parameters(text, descriptor, catalog, base=context.last_context.parameters)
    missing = missing_parameters(descriptor, merged)
    merged, missing = _drop_reask_suspects(text, descriptor, context.last_context.parameters, extracted, merged, missing)
    return _sticky_result(cap_id, merged, missing, render_clarify(descriptor, missing))


def _matched_intents(
    per_capability: list[tuple[CapabilityDescriptor, "IntentParseResult"]],
) -> list["MatchedIntent"]:
    from sap_nexus_agent.match_decision import MatchedIntent

    return [
        MatchedIntent(
            capability_id=cap.capability_id,
            parameters=result.parameters,
            missing=list(result.missing_parameters),
        )
        for cap, result in per_capability
    ]


def _empty_result(contains_rfc_name: bool, contains_odata_override: bool) -> "IntentParseResult":
    from sap_nexus_agent.intent import IntentParseResult

    return IntentParseResult(
        intent=None,
        parameters={},
        missing_parameters=[],
        contains_rfc_name=contains_rfc_name,
        contains_odata_override=contains_odata_override,
    )


def _multi_result(
    contains_rfc_name: bool,
    contains_odata_override: bool,
    matched_intents: list["MatchedIntent"],
    ambiguous: bool,
) -> "IntentParseResult":
    from sap_nexus_agent.intent import IntentParseResult

    return IntentParseResult(
        intent=None,
        parameters={},
        missing_parameters=[],
        contains_rfc_name=contains_rfc_name,
        contains_odata_override=contains_odata_override,
        capability_id=None,
        matched_intents=matched_intents,
        is_ambiguous=ambiguous,
    )


def _inherit_material_for_same_capability(
    parsed: "IntentParseResult",
    context: "ConversationContext",
    catalog: IntentCatalog,
) -> "IntentParseResult":
    # TODO(follow-up): generalize field-name special cases.
    if (
        "material" in parsed.parameters
        or context.last_context is None
        or not context.last_context.parameters.get("material")
        or len(parsed.matched_intents) != 1
        or parsed.matched_intents[0].capability_id != context.last_context.capability_id
    ):
        return parsed

    parameters = dict(parsed.parameters)
    parameters["material"] = context.last_context.parameters["material"]
    missing = [name for name in parsed.missing_parameters if name != "material"]
    return replace(
        parsed,
        parameters=parameters,
        missing_parameters=missing,
        capability_id=context.last_context.capability_id,
    )


def _drop_reask_suspects(
    text: str,
    cap: CapabilityDescriptor,
    previous: Mapping[str, str],
    extracted: Mapping[str, str],
    merged: Mapping[str, str],
    missing: list[str],
) -> tuple[dict[str, str], list[str]]:
    if _SUSPECT_TOKEN.search(text) is None:
        return dict(merged), missing
    reask_fields = [
        inp.name
        for inp in cap.inputs
        if inp.extraction is not None
        and inp.extraction.reask_suspect
        and inp.name in previous
        and inp.name not in extracted
    ]
    if not reask_fields:
        return dict(merged), missing
    next_params = {name: value for name, value in merged.items() if name not in reask_fields}
    next_missing = [*reask_fields, *(name for name in missing if name not in reask_fields)]
    return next_params, next_missing


def _sticky_result(
    cap_id: str,
    parameters: dict[str, str],
    missing: list[str],
    clarification: str | None,
) -> "IntentParseResult":
    from sap_nexus_agent.intent import IntentParseResult
    from sap_nexus_agent.match_decision import MatchedIntent

    return IntentParseResult(
        intent=None,
        capability_id=cap_id,
        parameters=parameters,
        missing_parameters=missing,
        clarification=clarification,
        contains_rfc_name=False,
        contains_odata_override=False,
        matched_intents=[MatchedIntent(capability_id=cap_id, parameters=parameters, missing=list(missing))],
    )

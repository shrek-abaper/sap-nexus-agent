from __future__ import annotations

import json
from typing import Protocol

from sap_nexus_agent.intent import (
    IntentParseResult,
    _detect_odata_override,
    parse_intent,
)
from sap_nexus_agent.llm_client import LlmUnavailable, OpenAiCompatibleLlmClient
from sap_nexus_agent.registry_loader import (
    CapabilityDescriptor,
    InputDescriptor,
    IntentCatalog,
    load_intent_catalog,
)


class JsonLlmClient(Protocol):
    def chat_json(self, messages: list[dict[str, str]], *, temperature: float = 0.0, max_tokens: int = 400) -> dict[str, object]:
        ...


def parse_with_llm(text: str, client: JsonLlmClient, catalog: IntentCatalog) -> IntentParseResult:
    try:
        payload = client.chat_json(_messages(text, catalog), temperature=0.0, max_tokens=400)
    except (LlmUnavailable, json.JSONDecodeError, ValueError, TypeError):
        raise LlmUnavailable("LLM intent parsing unavailable")
    return _payload_to_parse_result(payload, catalog)


def parse_with_hybrid(text: str, client: JsonLlmClient | None = None, *, catalog: IntentCatalog | None = None) -> IntentParseResult:
    if catalog is None:
        catalog = load_intent_catalog()
    try:
        llm_client = client or OpenAiCompatibleLlmClient()
        result = parse_with_llm(text, llm_client, catalog)
        if _requires_safe_fallback(result):
            return parse_intent(text)
        return result
    except LlmUnavailable:
        return parse_intent(text)


def build_intent_adapter(mode: str, catalog: IntentCatalog | None = None):
    if catalog is None:
        catalog = load_intent_catalog()
    normalized = mode.lower()
    if normalized == "rule":
        return parse_intent
    if normalized == "llm":
        return lambda text: _parse_llm_only(text, catalog)
    if normalized == "hybrid":
        return lambda text: parse_with_hybrid(text, catalog=catalog)
    raise ValueError(f"Unsupported intent mode: {mode}")


def _parse_llm_only(text: str, catalog: IntentCatalog) -> IntentParseResult:
    try:
        return parse_with_llm(text, OpenAiCompatibleLlmClient(), catalog)
    except LlmUnavailable:
        return IntentParseResult(intent=None, parameters={}, missing_parameters=[])


def _requires_safe_fallback(result: IntentParseResult) -> bool:
    if result.contains_rfc_name or result.contains_odata_override:
        return True
    # LLM path fills capability_id; rule path fills intent.
    # Fall back only when neither is set (unsupported / ambiguous).
    return result.capability_id is None and result.intent is None


def _messages(text: str, catalog: IntentCatalog) -> list[dict[str, str]]:
    capabilities_desc = "\n".join(
        f"- capabilityId: {c.capability_id}\n"
        f"  description: {c.description}\n"
        f"  inputs:\n{_format_inputs(c.inputs)}"
        for c in catalog.capabilities
    )
    return [
        {
            "role": "system",
            "content": (
                "You extract SAP Nexus read-only query intent as strict JSON. "
                "Select exactly one capabilityId from the registered closed set below, "
                "and extract parameters from the user query. "
                "If none matches, set capabilityId=null. "
                "Never output rfcName or raw SAP BAPI/RFC names. "
                "Return keys: capabilityId, parameters, missingParameters, clarification.\n\n"
                f"Registered capabilities:\n{capabilities_desc}"
            ),
        },
        {"role": "user", "content": text},
    ]


def _format_inputs(inputs: tuple[InputDescriptor, ...]) -> str:
    if not inputs:
        return "    (none)"
    lines = []
    for inp in inputs:
        req = "required" if inp.required else "optional"
        lines.append(f"    - {inp.name} ({inp.type}, {req})")
    return "\n".join(lines)


def _payload_to_parse_result(payload: dict[str, object], catalog: IntentCatalog) -> IntentParseResult:
    if not isinstance(payload, dict):
        raise LlmUnavailable("LLM payload is not an object")

    contains_rfc_name = any(str(key).lower() == "rfcname" for key in payload)
    # Reuse the rule-path OData override detector over the serialized payload so
    # the LLM path forms the same double-layer defense (Agent rejects first,
    # Java guard rejects again). Catches override fields in keys or values.
    contains_odata_override = _detect_odata_override(json.dumps(payload, ensure_ascii=False))
    if contains_rfc_name or contains_odata_override:
        return IntentParseResult(
            intent=None,
            parameters={},
            missing_parameters=[],
            contains_rfc_name=contains_rfc_name,
            contains_odata_override=contains_odata_override,
        )

    capability_id = payload.get("capabilityId")
    if not isinstance(capability_id, str) or capability_id not in catalog.capability_ids:
        return IntentParseResult(intent=None, parameters={}, missing_parameters=[])

    descriptor = catalog.find(str(capability_id))
    if descriptor is None:
        return IntentParseResult(intent=None, parameters={}, missing_parameters=[])

    raw_parameters = payload.get("parameters") or {}
    parameters = _extract_parameters(raw_parameters, descriptor)

    missing = [inp.name for inp in descriptor.inputs if inp.required and inp.name not in parameters]
    clarification = _clarification_for(str(capability_id), missing)

    return IntentParseResult(
        intent=None,
        capability_id=str(capability_id),
        parameters=parameters,
        missing_parameters=missing,
        clarification=clarification,
        contains_rfc_name=False,
        contains_odata_override=False,
    )


def _extract_parameters(raw_parameters: object, descriptor: CapabilityDescriptor) -> dict[str, str]:
    if not isinstance(raw_parameters, dict):
        return {}
    allowed = {inp.name for inp in descriptor.inputs}
    parameters: dict[str, str] = {}
    for key, value in raw_parameters.items():
        normalized = _parameter_key(str(key))
        if normalized and normalized in allowed and value is not None and str(value).strip():
            parameters[normalized] = str(value).strip()
    return parameters


def _clarification_for(capability_id: str, missing: list[str]) -> str | None:
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


_ALIASES = {
    # inventory
    "material": "material",
    "materialNumber": "material",
    "materialCode": "material",
    "matnr": "material",
    "plant": "plant",
    "plantCode": "plant",
    "werks": "plant",
    "unit": "unit",
    "uom": "unit",
    "unitOfMeasure": "unit",
    # purchase order
    "poNumber": "poNumber",
    "purchaseOrderNumber": "poNumber",
    "ebeln": "poNumber",
    "vendor": "vendor",
    "supplier": "vendor",
    "lifnr": "vendor",
}


def _parameter_key(key: str) -> str | None:
    return _ALIASES.get(key.strip())

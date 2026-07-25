from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Type-only import: avoids a circular import at runtime
    # (intent -> match_decision -> capability_selector -> intent).
    # MatchedIntent is imported lazily inside parse_intent / parse_inventory_intent.
    from sap_nexus_agent.match_decision import MatchedIntent


INVENTORY_KEYWORDS = ("库存", "可用量", "可用库存", "还有多少", "有没有")
PURCHASE_ORDER_KEYWORDS = ("采购订单", "订单", "PO")
UNIT_VALUES = ("EA", "PC", "KG", "G", "L", "M")
PLANT_PATTERN = re.compile(r"(?:在\s*([A-Z]\d{3}|\d{4}))|(?:([A-Z]\d{3}|\d{4})\s*工厂)")
TOKEN_PATTERN = re.compile(r"\b[A-Z0-9][A-Z0-9-]{1,39}\b")

# PO keyword detection: Chinese substrings are safe; bare "PO" must be isolated
# from ASCII letters so words like "IMPORT" / "POSITION" do not false-positive.
_PURCHASE_ORDER_KEYWORD_PATTERN = re.compile(r"采购订单|订单|(?<![A-Za-z])PO(?![A-Za-z])")

# PO filter parameter patterns.
PO_VENDOR_PATTERN = re.compile(r"供应商\s*(\d+)")
PO_PLANT_PATTERN = re.compile(r"(?:工厂\s*(\d{4}|[A-Z]\d{3}))|(?:(\d{4}|[A-Z]\d{3})\s*工厂)")
PO_MATERIAL_PATTERN = re.compile(r"物料\s*([A-Za-z0-9][A-Za-z0-9\-/]+)")
PO_NUMBER_PATTERN = re.compile(r"(?<!\d)(\d{10})(?!\d)")

# Capability-id closed set mapped from intent names; used to populate
# MatchedIntent.capability_id for the multi-intent collection (D-1 fix).
_INVENTORY_CAPABILITY_ID = "MM.Inventory.GetAvailability"
_PURCHASE_ORDER_CAPABILITY_ID = "MM.PurchaseOrder.GetList"
_PR_CREATE_CAPABILITY_ID = "MM.PR.CreateDraft"

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


def parse_intent(text: str) -> IntentParseResult:
    """Unified intent entry: scan ALL capability keyword sets, collect matched_intents.

    D-1 fix: previously this returned the first-matched intent in fixed order
    (inventory -> purchase_order -> pr_create), silently dropping other
    capabilities mentioned in the same utterance. Now it scans every keyword
    set independently and surfaces every match via ``matched_intents``; the
    selector (Task 3) decides ESCALATE_TO_PLANNER when length > 1.
    """
    normalized = text.strip()
    contains_rfc_name = _detect_rfc_name(normalized)
    contains_odata_override = _detect_odata_override(normalized)

    # Technical override (rfcName / OData) takes priority over multi-intent
    # collection: rejection path, matched_intents stays empty.
    if contains_rfc_name or contains_odata_override:
        return IntentParseResult(
            intent=None,
            parameters={},
            missing_parameters=[],
            contains_rfc_name=contains_rfc_name,
            contains_odata_override=contains_odata_override,
        )

    # Lazy import: pr_intent imports IntentParseResult from this module, so a
    # top-level import would create a circular dependency. MatchedIntent is
    # co-located with the selector layer (match_decision -> capability_selector
    # -> intent), so it is also lazy to break the same cycle.
    from sap_nexus_agent.match_decision import MatchedIntent
    from sap_nexus_agent.pr_intent import PR_CREATE_KEYWORDS, parse_pr_create_intent

    # Detect each capability's keyword set independently (D-1 fix).
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
        )

    if len(per_capability) == 1:
        # Single-intent path: keep existing extraction (backward compat) and
        # mirror the result into matched_intents (length 1).
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
        )

    # Multi-intent: top-level intent/capability_id None (selector decides
    # ESCALATE_TO_PLANNER). Parameters live on each MatchedIntent so the
    # planner can compose without re-parsing the utterance.
    return IntentParseResult(
        intent=None,
        parameters={},
        missing_parameters=[],
        contains_rfc_name=contains_rfc_name,
        contains_odata_override=contains_odata_override,
        capability_id=None,
        matched_intents=matched_intents,
    )


def parse_inventory_intent(text: str) -> IntentParseResult:
    """Backward-compatible inventory-only parser (does not route to PO)."""
    from sap_nexus_agent.match_decision import MatchedIntent

    normalized = text.strip()
    contains_rfc_name = _detect_rfc_name(normalized)
    contains_odata_override = _detect_odata_override(normalized)

    if not any(keyword in normalized for keyword in INVENTORY_KEYWORDS):
        return IntentParseResult(
            intent=None,
            parameters={},
            missing_parameters=[],
            contains_rfc_name=contains_rfc_name,
            contains_odata_override=contains_odata_override,
            matched_intents=[],
        )

    single = _build_inventory_result(normalized, contains_rfc_name, contains_odata_override)
    return IntentParseResult(
        intent=single.intent,
        parameters=single.parameters,
        missing_parameters=single.missing_parameters,
        clarification=single.clarification,
        contains_rfc_name=contains_rfc_name,
        contains_odata_override=contains_odata_override,
        capability_id=single.capability_id,
        matched_intents=[
            MatchedIntent(
                capability_id=_INVENTORY_CAPABILITY_ID,
                parameters=single.parameters,
                missing=list(single.missing_parameters),
            )
        ],
    )


def _build_inventory_result(
    normalized: str, contains_rfc_name: bool, contains_odata_override: bool
) -> IntentParseResult:
    plant = _extract_plant(normalized)
    unit = _extract_unit(normalized)
    material = _extract_material(normalized, plant=plant, unit=unit)

    parameters: dict[str, str] = {}
    if material:
        parameters["material"] = material
    if plant:
        parameters["plant"] = plant
    if unit:
        parameters["unit"] = unit

    missing = [name for name in ("material", "plant") if name not in parameters]
    return IntentParseResult(
        intent="inventory_availability",
        parameters=parameters,
        missing_parameters=missing,
        clarification=_clarification(missing),
        contains_rfc_name=contains_rfc_name,
        contains_odata_override=contains_odata_override,
    )


def _build_purchase_order_result(
    normalized: str, contains_rfc_name: bool, contains_odata_override: bool
) -> IntentParseResult:
    parameters: dict[str, str] = {}

    vendor = _extract_po_vendor(normalized)
    if vendor:
        parameters["vendor"] = vendor

    plant = _extract_po_plant(normalized)
    if plant:
        parameters["plant"] = plant

    material = _extract_po_material(normalized)
    if material:
        parameters["material"] = material

    po_number = _extract_po_number(normalized, excluded={vendor, plant})
    if po_number:
        parameters["poNumber"] = po_number

    # All four PO filters are individually optional, but at least one is required.
    if not parameters:
        return IntentParseResult(
            intent="purchase_order_list",
            parameters={},
            missing_parameters=["filter"],
            clarification="请至少提供一个过滤条件（采购订单号、供应商、工厂或物料）。",
            contains_rfc_name=contains_rfc_name,
            contains_odata_override=contains_odata_override,
        )

    return IntentParseResult(
        intent="purchase_order_list",
        parameters=parameters,
        missing_parameters=[],
        clarification=None,
        contains_rfc_name=contains_rfc_name,
        contains_odata_override=contains_odata_override,
    )


def _detect_rfc_name(text: str) -> bool:
    return bool(re.search(r"\brfcName\s*=", text, re.IGNORECASE))


def _detect_odata_override(text: str) -> bool:
    return bool(_ODATA_OVERRIDE_PATTERN.search(text))


def _extract_plant(text: str) -> str | None:
    for match in PLANT_PATTERN.finditer(text):
        token = match.group(1) or match.group(2)
        if len(token) <= 4:
            return token
    return None


def _extract_unit(text: str) -> str | None:
    for unit in UNIT_VALUES:
        if re.search(rf"\b{re.escape(unit)}\b", text):
            return unit
    return None


def _extract_material(text: str, plant: str | None, unit: str | None) -> str | None:
    excluded = {value for value in (plant, unit) if value}
    excluded.update({"RFCNAME"})
    for match in TOKEN_PATTERN.finditer(text):
        token = match.group(0)
        if token.upper() in excluded:
            continue
        if token.startswith("BAPI_"):
            continue
        if len(token) > 4:
            return token
    return None


def _extract_po_vendor(text: str) -> str | None:
    match = PO_VENDOR_PATTERN.search(text)
    return match.group(1) if match else None


def _extract_po_plant(text: str) -> str | None:
    match = PO_PLANT_PATTERN.search(text)
    if match:
        return match.group(1) or match.group(2)
    return None


def _extract_po_material(text: str) -> str | None:
    match = PO_MATERIAL_PATTERN.search(text)
    return match.group(1) if match else None


def _extract_po_number(text: str, excluded: set[str | None]) -> str | None:
    for match in PO_NUMBER_PATTERN.finditer(text):
        number = match.group(1)
        if number in excluded:
            continue
        return number
    return None


def _clarification(missing: list[str]) -> str | None:
    if missing == ["material"]:
        return "请提供要查询的物料编号。"
    if missing == ["plant"]:
        return "请提供要查询的工厂。"
    if missing:
        return "请提供要查询的物料编号和工厂。"
    return None

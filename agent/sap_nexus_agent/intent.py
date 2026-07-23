from __future__ import annotations

from dataclasses import dataclass
import re


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


def parse_intent(text: str) -> IntentParseResult:
    """Unified intent entry: inventory -> purchase_order_list -> pr_create -> None."""
    normalized = text.strip()
    contains_rfc_name = _detect_rfc_name(normalized)
    contains_odata_override = _detect_odata_override(normalized)

    if any(keyword in normalized for keyword in INVENTORY_KEYWORDS):
        return _build_inventory_result(normalized, contains_rfc_name, contains_odata_override)

    if _PURCHASE_ORDER_KEYWORD_PATTERN.search(normalized):
        return _build_purchase_order_result(normalized, contains_rfc_name, contains_odata_override)

    # Lazy import: pr_intent imports IntentParseResult from this module, so a
    # top-level import would create a circular dependency.
    from sap_nexus_agent.pr_intent import PR_CREATE_KEYWORDS, parse_pr_create_intent

    if any(keyword in normalized for keyword in PR_CREATE_KEYWORDS):
        # parse_pr_create_intent does not re-detect technical overrides; guard
        # here so rfcName/OData injections are still rejected upstream by
        # select_capability (UNSUPPORTED_RFC_NAME), matching the read paths.
        if contains_rfc_name or contains_odata_override:
            return IntentParseResult(
                intent=None,
                parameters={},
                missing_parameters=[],
                contains_rfc_name=contains_rfc_name,
                contains_odata_override=contains_odata_override,
            )
        return parse_pr_create_intent(normalized)

    return IntentParseResult(
        intent=None,
        parameters={},
        missing_parameters=[],
        contains_rfc_name=contains_rfc_name,
        contains_odata_override=contains_odata_override,
    )


def parse_inventory_intent(text: str) -> IntentParseResult:
    """Backward-compatible inventory-only parser (does not route to PO)."""
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
        )

    return _build_inventory_result(normalized, contains_rfc_name, contains_odata_override)


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

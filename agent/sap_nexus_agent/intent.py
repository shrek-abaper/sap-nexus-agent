from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Type-only import: avoids a circular import at runtime
    # (intent -> match_decision -> capability_selector -> intent).
    # MatchedIntent is imported lazily inside parse_intent / parse_inventory_intent.
    from sap_nexus_agent.match_decision import MatchedIntent
    # Type-only import for the conversational context parameter (Task 2).
    # Avoids a circular import at runtime; ConversationContext is a pure
    # data model with no runtime dependency on intent.py.
    from sap_nexus_agent.conversation_context import ConversationContext


INVENTORY_KEYWORDS = ("库存", "可用量", "可用库存", "还有多少", "有没有")
PURCHASE_ORDER_KEYWORDS = ("采购订单", "订单", "PO")
UNIT_VALUES = ("EA", "PC", "KG", "G", "L", "M")

# Primary/weak keyword tables for is_ambiguous detection (Design Doc § 多意图检测 Q2).
# Primary = unambiguous capability signal; weak = ambiguous cross-capability signal.
# These tables are SEPARATE from INVENTORY_KEYWORDS / _PURCHASE_ORDER_KEYWORD_PATTERN /
# PR_CREATE_KEYWORDS (which drive matched_intents collection). A weak-only match
# across >=2 capabilities with no primary hit -> is_ambiguous=True (SHOW_OPTIONS).
#
# "采购" appears in both PO_WEAK and PR_WEAK per Design Doc: '采购' 模糊匹配 PO 查询
# 与 PR 创建 ("采购" fuzzy-matches PO query and PR creation).
INVENTORY_PRIMARY_KEYWORDS = ("库存", "可用量", "可用库存", "还有多少")
INVENTORY_WEAK_KEYWORDS = ("有没有",)
PURCHASE_ORDER_PRIMARY_KEYWORDS = ("采购订单",)
PURCHASE_ORDER_WEAK_KEYWORDS = ("订单", "PO", "采购")
# PR_CREATE_PRIMARY_KEYWORDS mirrors PR_CREATE_KEYWORDS from pr_intent.py (all are
# unambiguous PR signals). Hardcoded here because pr_intent.py imports from
# intent.py at module level, so a reverse module-level import would be circular.
PR_CREATE_PRIMARY_KEYWORDS = (
    "采购申请", "创建采购", "建PR", "建 PR", "创建PR", "创建 PR", "PR草稿", "PR 草稿",
)
PR_CREATE_WEAK_KEYWORDS = ("采购",)
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
    # Task 5.5: keyword ambiguity flag (Design Doc § 多意图检测 Q2). True when
    # the utterance weakly matches >=2 capabilities' keyword sets without a
    # clear primary intent (no primary keyword hit). The selector fires
    # SHOW_OPTIONS when is_ambiguous=True and matched_intents is non-empty
    # (length 1; length >1 triggers ESCALATE first per decision-tree order).
    is_ambiguous: bool = False


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
    # Task 3: sticky continuation. When context carries a last_context, delegate
    # to resolve_with_context (lazy import avoids a circular dependency: llm_intent
    # imports parse_intent from this module at module level).
    if context is not None and context.last_context is not None:
        from sap_nexus_agent.llm_intent import resolve_with_context
        from sap_nexus_agent.registry_loader import load_intent_catalog

        return resolve_with_context(text, context, load_intent_catalog())

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

    # Keyword ambiguity detection (Design Doc § 多意图检测 Q2). Computed before
    # the existing keyword scan so it is available on every return path below.
    is_ambiguous = _detect_keyword_ambiguity(normalized)

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
            is_ambiguous=is_ambiguous,
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
            is_ambiguous=is_ambiguous,
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
        is_ambiguous=is_ambiguous,
    )


def parse_inventory_intent(
    text: str,
    context: "ConversationContext | None" = None,
) -> IntentParseResult:
    """Backward-compatible inventory-only parser (does not route to PO).

    Task 2: ``context`` parameter is accepted for signature compatibility
    (this parser is the default adapter for ``run_inventory_query``). The
    context is currently ignored; sticky continuation arrives in Task 3.
    """
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


def _detect_keyword_ambiguity(normalized: str) -> bool:
    """Keyword ambiguity threshold (Design Doc § 多意图检测 Q2).

    Returns True when the utterance weakly matches >=2 capabilities' keyword
    sets but NO capability has a primary keyword hit (all weak matches across
    capabilities, no clear primary intent). This distinguishes keyword
    ambiguity (SHOW_OPTIONS) from clear multi-intent (ESCALATE_TO_PLANNER).

    Primary vs weak per capability:
      - Inventory primary: 库存/可用量/可用库存/还有多少; weak: 有没有
      - PO primary: 采购订单; weak: 订单/PO/采购
      - PR primary: 采购申请/创建采购/建PR/...; weak: 采购
    """
    inv_primary = any(k in normalized for k in INVENTORY_PRIMARY_KEYWORDS)
    po_primary = any(k in normalized for k in PURCHASE_ORDER_PRIMARY_KEYWORDS)
    pr_primary = any(k in normalized for k in PR_CREATE_PRIMARY_KEYWORDS)

    inv_weak = any(k in normalized for k in INVENTORY_WEAK_KEYWORDS)
    po_weak = any(k in normalized for k in PURCHASE_ORDER_WEAK_KEYWORDS)
    pr_weak = any(k in normalized for k in PR_CREATE_WEAK_KEYWORDS)

    matched_count = sum([inv_primary or inv_weak, po_primary or po_weak, pr_primary or pr_weak])
    primary_count = sum([inv_primary, po_primary, pr_primary])

    return matched_count >= 2 and primary_count == 0


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

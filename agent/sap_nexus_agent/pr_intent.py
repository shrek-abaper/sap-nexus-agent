from __future__ import annotations

import re

from sap_nexus_agent.intent import IntentParseResult


PR_CREATE_KEYWORDS = ("采购申请", "建PR", "建 PR", "创建PR", "创建 PR", "PR草稿", "PR 草稿")
MATERIAL_PATTERN = re.compile(r"物料\s*([A-Za-z0-9][A-Za-z0-9\-/]+)")
PLANT_PATTERN = re.compile(r"工厂\s*(\d{4}|[A-Z]\d{3})")
QUANTITY_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*(?:EA|PC|KG|G|L|M)", re.IGNORECASE)
UNIT_PATTERN = re.compile(r"\b(EA|PC|KG|G|L|M)\b", re.IGNORECASE)
DATE_PATTERN = re.compile(r"(\d{4}-\d{2}-\d{2})")
ACCT_ASSGN_CAT_PATTERN = re.compile(r"(?:间采|账号分配)\s*[Kk]")
COST_CENTER_PATTERN = re.compile(r"成本中心\s*(\d+)")
PURCHASING_GROUP_PATTERN = re.compile(r"采购组\s*([A-Za-z0-9]{1,3})")

REQUIRED_FIELDS = ("material", "plant", "quantity", "unit", "delivery_date", "purchasing_group")


def parse_pr_create_intent(text: str) -> IntentParseResult:
    normalized = text.strip()

    parameters: dict[str, str] = {}

    material_match = MATERIAL_PATTERN.search(normalized)
    if material_match:
        parameters["material"] = material_match.group(1)

    plant_match = PLANT_PATTERN.search(normalized)
    if plant_match:
        parameters["plant"] = plant_match.group(1)

    quantity_match = QUANTITY_PATTERN.search(normalized)
    if quantity_match:
        parameters["quantity"] = quantity_match.group(1)

    unit_match = UNIT_PATTERN.search(normalized)
    if unit_match:
        parameters["unit"] = unit_match.group(1).upper()

    date_match = DATE_PATTERN.search(normalized)
    if date_match:
        parameters["delivery_date"] = date_match.group(1)

    purchasing_group_match = PURCHASING_GROUP_PATTERN.search(normalized)
    if purchasing_group_match:
        parameters["purchasing_group"] = purchasing_group_match.group(1).upper()

    acct_match = ACCT_ASSGN_CAT_PATTERN.search(normalized)
    if acct_match:
        parameters["acct_assgn_cat"] = "K"

    if parameters.get("acct_assgn_cat") == "K":
        cost_center_match = COST_CENTER_PATTERN.search(normalized)
        if cost_center_match:
            parameters["cost_center"] = cost_center_match.group(1)

    missing = [field for field in REQUIRED_FIELDS if field not in parameters]
    if parameters.get("acct_assgn_cat") == "K" and "cost_center" not in parameters:
        missing.append("cost_center")

    clarification = _build_clarification(missing)

    return IntentParseResult(
        intent="pr_create",
        parameters=parameters,
        missing_parameters=missing,
        clarification=clarification,
        contains_rfc_name=False,
        contains_odata_override=False,
        capability_id="MM.PR.CreateDraft",
    )


def _build_clarification(missing: list[str]) -> str | None:
    if not missing:
        return None
    parts = []
    field_names = {
        "material": "物料编号",
        "plant": "工厂",
        "quantity": "数量",
        "unit": "单位",
        "delivery_date": "交货日期",
        "purchasing_group": "采购组",
        "cost_center": "成本中心(间采 PR 需提供)",
    }
    for field in missing:
        if field in field_names:
            parts.append(field_names[field])
    if parts:
        return f"请提供: {', '.join(parts)}"
    return None

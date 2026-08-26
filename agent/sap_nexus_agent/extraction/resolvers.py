"""Generic value resolvers. Behavior lifted verbatim from the legacy extractors
(pr_intent.py / intent.py) to guarantee migration parity."""
from __future__ import annotations

import re
from datetime import date, timedelta

from sap_nexus_agent.registry_loader import ValueFilters

RESOLVERS = ("text", "date", "quantity", "relative_date")

_COMPACT_DATE = re.compile(r"^\d{8}$")
_RELATIVE_DATE = re.compile(r"^(\d+|半)\s*(年|个月|月|天|日)$")
_RELATIVE_UNIT_DAYS = {"年": 365, "个月": 30, "月": 30, "天": 1, "日": 1}


def normalize_date(value: str) -> str:
    """Normalize a captured delivery-date value to canonical ISO (YYYY-MM-DD).

    Accepts the compact SAP DATS-style YYYYMMDD form (SAP's own wire format)
    in addition to the already-canonical ISO form and reformats it to ISO,
    since downstream consumers (Java Gateway `LocalDate.parse`, TS
    `isCalendarDate`) require the dashed form. Anything else passes through
    unchanged so that validation happens explicitly downstream instead of
    this normalizer guessing.
    """
    if _COMPACT_DATE.match(value):
        return f"{value[0:4]}-{value[4:6]}-{value[6:8]}"
    return value


def resolve_relative_date(value: str) -> str:
    """Turn a captured relative-time phrase ("1年"/"半年"/"12个月") into an
    absolute ISO date (today minus that span), for "近1年"-style filters.

    Computed against today's date at resolution time, since the phrase is
    relative to "now", not a fixed calendar date. Anything unparseable passes
    through unchanged (same fail-soft contract as ``normalize_date``).
    """
    match = _RELATIVE_DATE.match(value.strip())
    if match is None:
        return value
    quantity_token, unit = match.group(1), match.group(2)
    quantity = 0.5 if quantity_token == "半" else int(quantity_token)
    days = round(quantity * _RELATIVE_UNIT_DAYS[unit])
    return (date.today() - timedelta(days=days)).isoformat()


def resolve(value: str, resolver: str, filters: ValueFilters) -> str:
    if resolver not in RESOLVERS:
        raise ValueError(f"unknown resolver: {resolver}")
    if resolver == "date":
        return normalize_date(value)
    if resolver == "relative_date":
        return resolve_relative_date(value)
    if resolver == "quantity":
        return value  # numeric capture stored verbatim (legacy behavior)
    if filters.to_upper_output:
        return value.upper()
    return value

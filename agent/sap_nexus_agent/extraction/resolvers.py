"""Generic value resolvers. Behavior lifted verbatim from the legacy extractors
(pr_intent.py / intent.py) to guarantee migration parity."""
from __future__ import annotations

from sap_nexus_agent.registry_loader import ValueFilters

RESOLVERS = ("text", "date", "quantity")


def resolve(value: str, resolver: str, filters: ValueFilters) -> str:
    if resolver not in RESOLVERS:
        raise ValueError(f"unknown resolver: {resolver}")
    if resolver in ("date", "quantity"):
        return value  # ISO date / numeric capture stored verbatim (legacy behavior)
    if filters.to_upper_output:
        return value.upper()
    return value

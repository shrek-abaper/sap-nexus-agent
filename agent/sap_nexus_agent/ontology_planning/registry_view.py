"""Dynamic capability/fact views derived from the registry YAML.

The ontology planner must not hardcode registered capability or fact-type
ids in production source (a standing lock enforces this for the declared
capabilities): every mapping below is read from SemanticSourceDocuments.
"""

from __future__ import annotations

from typing import Any


def read_capability_ids(sources: Any) -> frozenset[str]:
    """Active Function capabilities with no side effect and no approval."""
    ids = set()
    for capability in sources.capabilities.get("capabilities", []):
        governance = capability.get("governance", {})
        if capability.get("status") != "active":
            continue
        if capability.get("kind") != "Function":
            continue
        if governance.get("sideEffect", "none") != "none":
            continue
        if governance.get("requiresApproval", False):
            continue
        ids.add(capability["capabilityId"])
    return frozenset(ids)


def capability_fact_types(sources: Any) -> dict[str, str]:
    """capabilityId -> produced fact type (capabilities producing exactly one read fact)."""
    mapping: dict[str, str] = {}
    for capability in sources.capabilities.get("capabilities", []):
        fact_refs = {
            output.get("factTypeRef")
            for output in capability.get("outputs", [])
            if output.get("factTypeRef")
        }
        if len(fact_refs) == 1:
            mapping[capability["capabilityId"]] = next(iter(fact_refs))
    return mapping

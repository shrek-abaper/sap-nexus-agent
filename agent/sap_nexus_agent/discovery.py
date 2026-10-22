"""Discovery surfaces: master-data directory listing and capability catalog.

Both are read-only projections over governed sources, consumed by the dsh
chat runtime as the ``list_master_data`` / ``list_capabilities`` tools:

- ``list_master_data`` reuses the registered MD.*.Search READ capabilities
  declared in ontology/entity-resolution.yaml; an empty query selects the
  provider's browse mode (all in-scope active entities). The agent never
  touches the master-data store directly — every call goes through the
  governed gateway channel with capabilityId only.
- ``list_capabilities`` projects the governed registry snapshot into a
  user-facing catalog (id, description, domain, read/write, required
  inputs). It is pure metadata: no SAP or master-data store access, so it
  stays answerable even when data services are down.
"""

from __future__ import annotations

from pathlib import Path
from typing import Mapping, Protocol

from sap_nexus_agent.entity_resolution.rules import (
    REPO_ROOT,
    EntityResolutionRule,
    load_resolution_rules,
)


class SearchGateway(Protocol):
    """Minimal governed channel (matches GatewayClientProtocol)."""

    def execute(self, capability_id: str, parameters: Mapping[str, object]): ...


def _unavailable(object_type: str) -> dict[str, object]:
    return {
        "status": "unavailable",
        "objectType": object_type,
        "candidates": [],
        "message": "主数据检索服务暂时不可用，请确认主数据服务已启动后重试。",
    }


def list_master_data(
    *,
    object_type: str,
    gateway: SearchGateway,
    query: str | None = None,
    org_filter: str | None = None,
    limit: int | None = None,
    repo_root: Path | None = None,
) -> dict[str, object]:
    """List or semantically search master-data entities of one object type.

    ``object_type`` must be a registered objectTypeId (e.g.
    ``sapnexus:Material``); the search capability is looked up from the
    entity-resolution rules, never from the request. No query means browse
    mode: the provider enumerates every in-scope active entity.
    """
    rules = load_resolution_rules(repo_root or REPO_ROOT)
    rule: EntityResolutionRule | None = next(
        (candidate for candidate in rules if candidate.object_type_id == object_type),
        None,
    )
    if rule is None:
        known = ", ".join(candidate.object_type_id for candidate in rules)
        return {
            "status": "invalid",
            "objectType": object_type,
            "candidates": [],
            "message": f"未知的主数据对象类型 {object_type or '（空）'}（已注册：{known}）。",
        }

    parameters: dict[str, object] = {}
    if query and query.strip():
        parameters["query"] = query.strip()
    if org_filter and org_filter.strip() and rule.organizational_filters:
        parameters[rule.organizational_filters[0][0]] = org_filter.strip()
    if limit is not None:
        parameters["limit"] = str(limit)

    try:
        execution = gateway.execute(rule.search_capability_id, parameters)
    except Exception:
        return _unavailable(object_type)
    if not getattr(execution, "success", False):
        error_type = str(getattr(execution, "error_type", "") or "")
        if "PERMISSION" in error_type:
            return {
                "status": "permission-denied",
                "objectType": object_type,
                "candidates": [],
                "message": "当前身份无权检索该主数据范围。",
            }
        return _unavailable(object_type)

    data = getattr(execution, "data", {}) or {}
    candidates = [
        {
            "canonicalCode": str(item.get("canonicalCode") or ""),
            "displayName": str(item.get("displayName") or ""),
            "matchKind": str(item.get("matchKind") or ""),
            "status": str(item.get("status") or "active"),
            "distinguishing": {
                str(key): str(value)
                for key, value in (item.get("distinguishing") or {}).items()
            },
            "orgScopes": [
                {"field": str(scope.get("field")), "value": str(scope.get("value"))}
                for scope in (item.get("orgScopes") or [])
            ],
        }
        for item in (data.get("candidates") or [])
        if item.get("canonicalCode")
    ]
    return {
        "status": "complete",
        "objectType": rule.object_type_id,
        "capabilityId": rule.search_capability_id,
        "candidates": candidates,
        "snapshotId": str(data.get("snapshotId") or "unknown"),
        "resultCompleteness": str(data.get("resultCompleteness") or ""),
        "sourceExtractedAt": str(data.get("sourceExtractedAt") or "") or None,
    }


def list_capabilities(*, repo_root: Path | None = None) -> dict[str, object]:
    """Project the governed registry snapshot into a user-facing catalog."""
    from sap_nexus_agent.planner.capability_card import discover_cards
    from sap_nexus_agent.semantic_planning import (
        build_registry_snapshot,
        load_semantic_sources,
    )
    from sap_nexus_agent.visibility import filter_visible

    root = repo_root or REPO_ROOT
    sources = load_semantic_sources(root)
    snapshot = build_registry_snapshot(sources)
    cards = filter_visible(discover_cards(snapshot, sources), for_execution=False)
    raw_by_id = {
        entry["capabilityId"]: entry
        for entry in sources.capabilities.get("capabilities", [])
        if isinstance(entry, Mapping) and entry.get("capabilityId")
    }

    entries: list[dict[str, object]] = []
    for card in cards:
        raw = raw_by_id.get(card.capability_id, {})
        governance = raw.get("governance", {})
        entries.append({
            "capabilityId": card.capability_id,
            "name": card.name,
            "description": str(raw.get("description") or ""),
            "domain": str(raw.get("domain") or ""),
            "sideEffect": card.governance.side_effect,
            "requiresApproval": governance.get("approvalPolicy", "not_required") != "not_required",
            "requiredInputs": [field.name for field in card.inputs if field.required],
        })
    return {
        "status": "complete",
        "snapshotId": snapshot.snapshot_id,
        "capabilities": entries,
    }

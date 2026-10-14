"""Normalize raw gateway node results into allowlisted TypedFact rows.

The C1 Fact-field allowlist is the single field authority. Row rules mirror
the proven TS projection (header/items expansion, header fallback,
identity) but arithmetic stays downstream in the Python operators.
"""

from __future__ import annotations

import re
from typing import Any

from .contracts import (
    ExcludedRow,
    FactEvidence,
    Normalization,
    NodeResult,
    TypedFact,
    TypedFieldValue,
)

_DECIMAL = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$")

# Closed v1 mapping of read capability -> produced fact/object metadata.
_CAPABILITY_FACT = {
    "MM.PurchaseOrder.GetList": (
        "sapnexus:PurchaseOrderSupplyFact",
        "PurchaseOrderItem",
        "purchaseOrderUnit",
    ),
    "MM.Inventory.GetAvailability": (
        "sapnexus:InventoryAvailabilityFact",
        "InventoryStock",
        None,
    ),
    "MM.Material.GetInfo": (
        "sapnexus:MaterialInfoFact",
        "Material",
        None,
    ),
}

_IDENTITY_FIELDS = ("purchaseOrder", "purchaseOrderItem")


def _field_semantic_types(pinned: Any) -> dict[str, dict[str, str]]:
    allowlist = pinned.assets["ontology/analysis-fact-fields.yaml"]["allowlist"]
    return {
        entry["factTypeId"]: {
            field["name"]: field["semanticType"] for field in entry["fields"]
        }
        for entry in allowlist
    }


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value if value else None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return None


def _decimal_text(value: Any) -> str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return None
    text = _text(value)
    if text is not None and _DECIMAL.match(text):
        return text
    return None


def normalize(
    node_results: tuple[NodeResult, ...],
    pinned: Any,
    run_id: str,
) -> Normalization:
    semantic_types = _field_semantic_types(pinned)
    facts: list[TypedFact] = []
    exclusions: list[ExcludedRow] = []
    identities: dict[tuple[str, tuple[tuple[str, str], ...]], int] = {}
    conflicts: list[str] = []
    row_counter = 0

    for node in node_results:
        mapping = _CAPABILITY_FACT.get(node.capability_id)
        if mapping is None:
            continue
        fact_type, object_type, unit_field = mapping
        allowed = semantic_types.get(fact_type, {})

        if node.capability_id == "MM.PurchaseOrder.GetList":
            rows = _po_rows(node, exclusions)
        else:
            rows = [_scalar_row(node)]

        for row in rows:
            identity = tuple(sorted(
                (key, str(value))
                for key, value in row.items()
                if key in _IDENTITY_FIELDS and value is not None
            )) or tuple(sorted(
                (key, str(value))
                for key, value in (node.parameters or {}).items()
            ))
            identity_key = (fact_type, identity)
            if identity_key in identities:
                prior = facts[identities[identity_key]]
                conflicts.append(
                    f"ROW_IDENTITY_CONFLICT:{fact_type}:"
                    f"{dict(prior.row_identity)}"
                )
            else:
                identities[identity_key] = len(facts)

            fields: dict[str, TypedFieldValue] = {}
            for name, value in row.items():
                if name not in allowed or value is None:
                    continue
                fields[name] = TypedFieldValue(
                    value=str(value), semantic_type=allowed[name]
                )

            row_identity = {key: str(value) for key, value in identity}
            scope = (
                {"plant": node.parameters["plant"]}
                if node.parameters.get("plant") else {}
            )
            object_key = {
                key: value
                for key, value in row_identity.items()
                if key in ("purchaseOrder", "purchaseOrderItem")
            } or dict(node.parameters)
            unit = None
            if unit_field and row.get(unit_field):
                unit = {"field": unit_field, "value": str(row[unit_field])}

            fact_id = f"{node.node_id}:row:{row_counter}"
            row_counter += 1
            facts.append(
                TypedFact(
                    fact_id=fact_id,
                    fact_type_ref=fact_type,
                    object_type=object_type,
                    object_key=object_key,
                    scope=scope,
                    row_identity=row_identity,
                    fields=fields,
                    unit=unit,
                    business_time=None,
                    collected_at=node.executed_at,
                    definition_ref=None,
                    evidence=FactEvidence(
                        run_id=run_id,
                        node_id=node.node_id,
                        gateway_trace_id=node.gateway_trace_id,
                        raw_fields=tuple(
                            sorted(name for name in row if name in allowed)
                        ),
                        completeness="complete",
                    ),
                )
            )

    facts.sort(key=lambda fact: (fact.fact_type_ref, fact.fact_id))
    return Normalization(
        facts=tuple(facts),
        exclusions=tuple(exclusions),
        conflicts=tuple(conflicts),
    )


def _scalar_row(node: NodeResult) -> dict[str, Any]:
    return {key: value for key, value in node.data.items()}


def _po_rows(node: NodeResult, exclusions: list[ExcludedRow]) -> list[dict[str, Any]]:
    payload = node.data.get("purchaseOrders")
    if not isinstance(payload, list):
        return []
    rows: list[dict[str, Any]] = []
    for index, raw_header in enumerate(payload):
        if not isinstance(raw_header, dict):
            continue
        items = raw_header.get("items")
        item_list = items if isinstance(items, list) else [raw_header]
        for item_index, raw_item in enumerate(item_list):
            item = raw_item if isinstance(raw_item, dict) else {}
            quantity = _decimal_text(
                item["orderQuantity"]
                if "orderQuantity" in item
                else raw_header.get("orderQuantity")
            )
            if quantity is None:
                exclusions.append(
                    ExcludedRow(
                        fact_id=f"{node.node_id}:row:{index}-{item_index}",
                        reason="NON_FINITE_MEASURE",
                    )
                )
                continue
            rows.append({
                "purchaseOrder": _text(item.get("purchaseOrder"))
                or _text(raw_header.get("purchaseOrder")),
                "purchaseOrderItem": _text(item.get("purchaseOrderItem"))
                or _text(raw_header.get("purchaseOrderItem")),
                "supplier": _text(raw_header.get("supplier"))
                or _text(item.get("supplier")),
                "material": _text(item.get("material"))
                or _text(node.parameters.get("material"))
                or _text(raw_header.get("material")),
                "plant": _text(item.get("plant"))
                or _text(node.parameters.get("plant"))
                or _text(raw_header.get("plant")),
                "orderQuantity": quantity,
                "purchaseOrderUnit": _text(item.get("purchaseOrderUnit"))
                or _text(raw_header.get("purchaseOrderUnit")),
            })
    return rows

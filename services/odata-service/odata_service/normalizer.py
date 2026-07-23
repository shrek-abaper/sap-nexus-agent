"""OData response normalizer.

Parses a raw SAP OData JSON response (v2 ``d.results`` or v4 ``value``) into the
service contract: ``{success, purchaseOrders, totalCount, errorType?, messages?}``.

Field mapping (raw SAP field -> normalized key):

    PurchaseOrder               -> purchaseOrder
    Supplier                    -> supplier
    Plant                       -> plant
    Material                    -> material
    OrderQuantity               -> orderQuantity
    PurchaseOrderUnit           -> purchaseOrderUnit
    PurchaseOrderQuantityUnit   -> purchaseOrderUnit   (sap-sto-create variant)

The delivery-date field is intentionally deferred to the live spike (Design Doc
open question); any other non-metadata field passes through unchanged so a
later-confirmed field flows without code changes.
"""

from __future__ import annotations

from typing import Any

FIELD_MAP: dict[str, str] = {
    "PurchaseOrder": "purchaseOrder",
    "PurchaseOrderItem": "purchaseOrderItem",
    "Supplier": "supplier",
    "Plant": "plant",
    "Material": "material",
    "OrderQuantity": "orderQuantity",
    "PurchaseOrderUnit": "purchaseOrderUnit",
    "PurchaseOrderQuantityUnit": "purchaseOrderUnit",
}

# OData metadata keys/prefixes that must never reach the normalized output.
_METADATA_KEYS = {"__metadata", "__deferred", "uri", "type"}
_METADATA_PREFIXES = ("__", "@")


def normalize(json_body: Any) -> dict[str, Any]:
    """Normalize a raw OData JSON body into the service contract dict."""
    if not isinstance(json_body, dict):
        return _failure("INVALID_RESPONSE", "OData response was not a JSON object")

    # OData error envelope (v2 and v4 share the top-level "error" key).
    if "error" in json_body:
        message = _extract_error_message(json_body["error"])
        return _failure("ODATA_ERROR", message)

    results = _extract_results(json_body)
    if results is None:
        return _failure("INVALID_RESPONSE", "OData response had no recognizable result collection")

    count = _extract_count(json_body)
    purchase_orders = [_map_item(item) for item in results]
    return {
        "success": True,
        "purchaseOrders": purchase_orders,
        "totalCount": count if count is not None else len(purchase_orders),
    }


def normalize_items(json_body: Any) -> list[dict[str, Any]]:
    """Normalize an OData item collection into mapped item dictionaries."""
    if not isinstance(json_body, dict) or "error" in json_body:
        return []
    results = _extract_results(json_body)
    if results is None:
        return []
    return [_map_item(item) for item in results]


def _extract_results(body: dict[str, Any]) -> list[dict[str, Any]] | None:
    # OData v4: top-level "value" array.
    if "value" in body and isinstance(body["value"], list):
        return body["value"]
    # OData v2: "d" -> "results" array (or a single object with no results key).
    d = body.get("d")
    if isinstance(d, dict):
        if isinstance(d.get("results"), list):
            return d["results"]
        # v2 single entity (no collection) - treat as a one-element list.
        if "results" not in d:
            return [d]
    return None


def _extract_count(body: dict[str, Any]) -> int | None:
    # v4: @odata.count ; v2: d.__count
    v4_count = body.get("@odata.count")
    if v4_count is not None:
        try:
            return int(v4_count)
        except (TypeError, ValueError):
            return None
    d = body.get("d")
    if isinstance(d, dict):
        v2_count = d.get("__count")
        if v2_count is not None:
            try:
                return int(v2_count)
            except (TypeError, ValueError):
                return None
    return None


def _extract_error_message(error: Any) -> str:
    if isinstance(error, dict):
        message = error.get("message")
        if isinstance(message, dict):
            value = message.get("value")
            if isinstance(value, str) and value:
                return value
        if isinstance(message, str) and message:
            return message
        code = error.get("code")
        if code:
            return f"OData error: {code}"
    return "OData error"


def _map_item(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    mapped: dict[str, Any] = {}
    for key, value in raw.items():
        if key in FIELD_MAP:
            mapped[FIELD_MAP[key]] = value
        elif key in _METADATA_KEYS or key.startswith(_METADATA_PREFIXES) or _is_deferred_navigation(value):
            continue
        else:
            mapped[key] = value
    return mapped


def _is_deferred_navigation(value: Any) -> bool:
    return isinstance(value, dict) and "__deferred" in value


def _failure(error_type: str, message: str) -> dict[str, Any]:
    return {
        "success": False,
        "purchaseOrders": [],
        "totalCount": 0,
        "errorType": error_type,
        "messages": [{"type": "E", "message": message}],
    }

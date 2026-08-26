"""HTTP service entrypoint (:8081).

Exposes ``POST /execute`` which receives the Java gateway proxy payload::

    {serviceRef, entitySet, filterMapping, parameters, topLimit, selectFields, traceId}

and returns the normalized contract::

    {success, purchaseOrders:[...], totalCount, errorType?, messages?, traceId?}

Uses stdlib ``http.server`` (consistent with the agent codebase style). The
OData client is injectable into :class:`ODataService` so tests can mock SAP
without a live connection.
"""

from __future__ import annotations

import json
import logging
from http.server import BaseHTTPRequestHandler
from typing import Any
from urllib import error

from .filter_builder import build as build_filter
from .normalizer import normalize, normalize_items
from .odata_client import ODataClient, ODataHttpError

logger = logging.getLogger(__name__)

_PORT = 8081
_REQUIRED_FIELDS = ("serviceRef", "entitySet")
_ITEM_FILTER_KEYS = {"material", "plant", "openOnly"}
# A_PurchaseOrderItem fields for "未清" (open/outstanding): not yet fully
# delivered and not yet finally invoiced. Hardcoded rather than registry-driven
# (like _ITEM_FILTER_KEYS above) because it expands one boolean param into two
# ANDed clauses, which filter_mapping's flat param->field shape can't express.
_OPEN_ITEM_FIELDS = ("IsCompletelyDelivered", "IsFinallyInvoiced")


class ODataService:
    """Orchestrates $filter assembly, OData GET, and response normalization."""

    def __init__(self, client: Any | None = None):
        # The real client loads destination from env; tests inject a mock.
        self._client = client if client is not None else ODataClient()

    def execute(self, payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
        """Process a parsed ``/execute`` payload.

        Returns ``(response_body, http_status)``.
        """
        trace_id = str(payload.get("traceId", ""))

        missing = [f for f in _REQUIRED_FIELDS if not payload.get(f)]
        if missing:
            return self._error("BAD_REQUEST", f"Missing required field(s): {', '.join(missing)}", trace_id), 400

        service_ref = str(payload["serviceRef"])
        entity_set = str(payload["entitySet"])
        filter_mapping = dict(payload.get("filterMapping") or {})
        parameters = dict(payload.get("parameters") or {})
        top_limit = payload.get("topLimit")
        select_fields = [str(f) for f in (payload.get("selectFields") or [])]

        header_parameters = {key: value for key, value in parameters.items() if key not in _ITEM_FILTER_KEYS}
        header_filter_mapping = {key: value for key, value in filter_mapping.items() if key not in _ITEM_FILTER_KEYS}
        filter_str = build_filter(header_parameters, header_filter_mapping)
        header_select, item_select = _split_select_fields(select_fields, filter_mapping)

        try:
            raw = self._client.get(service_ref, entity_set, filter_str, top_limit, False, header_select)
            result = normalize(raw)
            if result.get("success"):
                self._attach_items(result, service_ref, entity_set, parameters, filter_mapping, item_select)
        except ODataHttpError as exc:
            # SAP responded with an error envelope; normalize it if possible.
            result = normalize(exc.body) if exc.body is not None else self._error("ODATA_HTTP_ERROR", str(exc), trace_id)
            result["traceId"] = trace_id
            return result, 200
        except (error.URLError, ConnectionError, TimeoutError, OSError) as exc:
            # Upstream (SAP) unreachable.
            return self._error("CONNECTION_ERROR", f"SAP OData connection failed: {exc}", trace_id), 502

        result["traceId"] = trace_id
        return result, 200

    @staticmethod
    def _error(error_type: str, message: str, trace_id: str) -> dict[str, Any]:
        return {
            "success": False,
            "purchaseOrders": [],
            "totalCount": 0,
            "errorType": error_type,
            "messages": [{"type": "E", "message": message}],
            "traceId": trace_id,
        }

    def _attach_items(
        self,
        result: dict[str, Any],
        service_ref: str,
        entity_set: str,
        parameters: dict[str, Any],
        filter_mapping: dict[str, Any],
        item_select: list[str],
    ) -> None:
        purchase_orders = result.get("purchaseOrders")
        if not isinstance(purchase_orders, list):
            return

        item_parameters = {key: value for key, value in parameters.items() if key in _ITEM_FILTER_KEYS}
        item_filter_mapping = {key: value for key, value in filter_mapping.items() if key in _ITEM_FILTER_KEYS}
        item_filter_str = build_filter(item_parameters, item_filter_mapping)
        if str(parameters.get("openOnly") or "").lower() == "true":
            open_clause = " and ".join(f"{field} eq false" for field in _OPEN_ITEM_FIELDS)
            item_filter_str = f"{item_filter_str} and {open_clause}" if item_filter_str else open_clause

        filtered_orders = []
        for purchase_order in purchase_orders:
            if not isinstance(purchase_order, dict):
                continue
            po_number = purchase_order.get("purchaseOrder")
            if not po_number:
                filtered_orders.append(purchase_order)
                continue

            entity_path = f"{entity_set}({_odata_string_literal(str(po_number))})/to_PurchaseOrderItem"
            raw_items = self._client.get_path(service_ref, entity_path, item_filter_str, None, False, item_select)
            items = _filter_items(normalize_items(raw_items), parameters)
            purchase_order["items"] = items
            if _has_item_filter(parameters) and not items:
                continue
            filtered_orders.append(purchase_order)

        result["purchaseOrders"] = filtered_orders
        result["totalCount"] = len(filtered_orders)


def _split_select_fields(
    select_fields: list[str], filter_mapping: dict[str, Any]
) -> tuple[list[str], list[str]]:
    """Split a flat ``selectFields`` list into header vs. item entity fields.

    Classification follows the same header/item split ``_ITEM_FILTER_KEYS``
    already uses for filtering: a field is header-level only if it is the
    declared SAP field for a non-item filter param (e.g. ``poNumber`` ->
    ``PurchaseOrder``, ``vendor`` -> ``Supplier``); everything else (including
    output-only fields with no filter param, like ``OrderQuantity``) is
    item-level, since ``A_PurchaseOrder`` (header) does not carry them.
    ``PurchaseOrder`` is always kept in the header selection regardless of
    ``selectFields`` content -- ``_attach_items`` needs it to build the
    ``to_PurchaseOrderItem`` navigation path for each result row.
    """
    if not select_fields:
        return [], []
    header_sap_fields = {
        sap_field for key, sap_field in filter_mapping.items() if key not in _ITEM_FILTER_KEYS
    }
    header_select = [f for f in select_fields if f in header_sap_fields]
    if "PurchaseOrder" not in header_select:
        header_select.insert(0, "PurchaseOrder")
    item_select = [f for f in select_fields if f not in header_sap_fields]
    return header_select, item_select


def _has_item_filter(parameters: dict[str, Any]) -> bool:
    return any(str(parameters.get(key) or "") for key in _ITEM_FILTER_KEYS)


def _filter_items(items: list[dict[str, Any]], parameters: dict[str, Any]) -> list[dict[str, Any]]:
    result = []
    for item in items:
        material = str(parameters.get("material") or "")
        plant = str(parameters.get("plant") or "")
        if material and str(item.get("material") or "") != material:
            continue
        if plant and str(item.get("plant") or "") != plant:
            continue
        result.append(item)
    return result


def _odata_string_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def make_handler(service: ODataService):
    """Build a :class:`BaseHTTPRequestHandler` subclass bound to ``service``."""

    class _Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802 - stdlib naming
            if self.path != "/execute":
                self._send_json({"success": False, "errorType": "NOT_FOUND", "messages": [{"type": "E", "message": "Unknown path"}]}, 404)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length) if length else b"{}"
                payload = json.loads(raw.decode("utf-8"))
            except (ValueError, json.JSONDecodeError):
                self._send_json(
                    {"success": False, "purchaseOrders": [], "totalCount": 0, "errorType": "BAD_REQUEST",
                     "messages": [{"type": "E", "message": "Invalid JSON body"}]},
                    400,
                )
                return

            if not isinstance(payload, dict):
                self._send_json(
                    {"success": False, "purchaseOrders": [], "totalCount": 0, "errorType": "BAD_REQUEST",
                     "messages": [{"type": "E", "message": "Request body must be a JSON object"}]},
                    400,
                )
                return

            body, status = service.execute(payload)
            self._send_json(body, status)

        def _send_json(self, body: dict[str, Any], status: int):
            encoded = json.dumps(body).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, fmt, *args):  # noqa: A003 - stdlib override
            # Keep logs free of destination/credential detail; only path + status.
            logger.debug("odata-service %s", fmt % args)

    return _Handler


def run(port: int = _PORT):  # pragma: no cover - manual run entrypoint
    """Start the OData service on ``port`` (default :8081)."""
    from http.server import HTTPServer

    service = ODataService()
    httpd = HTTPServer(("0.0.0.0", port), make_handler(service))
    logger.info("odata-service listening on :%s", port)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        httpd.shutdown()


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO)
    run()

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
_ITEM_FILTER_KEYS = {"material", "plant"}


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

        header_parameters = {key: value for key, value in parameters.items() if key not in _ITEM_FILTER_KEYS}
        header_filter_mapping = {key: value for key, value in filter_mapping.items() if key not in _ITEM_FILTER_KEYS}
        filter_str = build_filter(header_parameters, header_filter_mapping)

        try:
            raw = self._client.get(service_ref, entity_set, filter_str, top_limit, False)
            result = normalize(raw)
            if result.get("success"):
                self._attach_items(result, service_ref, entity_set, parameters)
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
    ) -> None:
        purchase_orders = result.get("purchaseOrders")
        if not isinstance(purchase_orders, list):
            return

        filtered_orders = []
        for purchase_order in purchase_orders:
            if not isinstance(purchase_order, dict):
                continue
            po_number = purchase_order.get("purchaseOrder")
            if not po_number:
                filtered_orders.append(purchase_order)
                continue

            entity_path = f"{entity_set}({_odata_string_literal(str(po_number))})/to_PurchaseOrderItem"
            raw_items = self._client.get_path(service_ref, entity_path, "", None, False)
            items = _filter_items(normalize_items(raw_items), parameters)
            purchase_order["items"] = items
            if _has_item_filter(parameters) and not items:
                continue
            filtered_orders.append(purchase_order)

        result["purchaseOrders"] = filtered_orders
        result["totalCount"] = len(filtered_orders)


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

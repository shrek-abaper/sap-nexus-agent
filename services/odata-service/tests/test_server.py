from __future__ import annotations

import http.server
import json
import threading
from urllib import error, request

from odata_service.server import ODataService, _split_select_fields, make_handler


class _MockClient:
    """Stand-in for ODataClient used in end-to-end server tests."""

    def __init__(self, response=None, raises=None):
        self._response = response
        self._raises = raises
        self.last_call = None
        self.path_calls = []
        self.path_responses = {}

    def get(self, service_ref, entity_set, filter_str, top, count, select=None):
        self.last_call = {
            "serviceRef": service_ref,
            "entitySet": entity_set,
            "filter": filter_str,
            "top": top,
            "count": count,
            "select": select,
        }
        if self._raises:
            raise self._raises
        return self._response

    def get_path(self, service_ref, entity_path, filter_str="", top=None, count=False, select=None):
        self.path_calls.append(
            {
                "serviceRef": service_ref,
                "entityPath": entity_path,
                "filter": filter_str,
                "top": top,
                "count": count,
                "select": select,
            }
        )
        return self.path_responses.get(entity_path, {"d": {"results": []}})


def _start_server(service):
    handler = make_handler(service)
    httpd = http.server.HTTPServer(("127.0.0.1", 0), handler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd, port


def _post(port, body):
    data = json.dumps(body).encode("utf-8")
    req = request.Request(
        f"http://127.0.0.1:{port}/execute",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    # Bypass any environment HTTP proxy for localhost (mirrors gateway_client).
    opener = request.build_opener(request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


FULL_REQUEST = {
    "serviceRef": "API_PURCHASEORDER_PROCESS_SRV",
    "entitySet": "A_PurchaseOrder",
    "filterMapping": {
        "poNumber": "PurchaseOrder",
        "vendor": "Supplier",
        "plant": "Plant",
        "material": "Material",
    },
    "parameters": {"vendor": "DEMOV1"},
    "topLimit": 50,
    "selectFields": [
        "PurchaseOrder",
        "Supplier",
        "Plant",
        "Material",
        "OrderQuantity",
        "PurchaseOrderQuantityUnit",
    ],
    "traceId": "trace-1",
}


def test_split_select_fields_classifies_header_and_item_fields():
    header, item = _split_select_fields(
        ["PurchaseOrder", "Supplier", "Plant", "Material", "OrderQuantity", "PurchaseOrderQuantityUnit"],
        FULL_REQUEST["filterMapping"],
    )
    assert header == ["PurchaseOrder", "Supplier"]
    assert item == ["Plant", "Material", "OrderQuantity", "PurchaseOrderQuantityUnit"]


def test_split_select_fields_always_keeps_purchase_order_in_header():
    header, item = _split_select_fields(["Plant", "Material"], FULL_REQUEST["filterMapping"])
    assert header == ["PurchaseOrder"]
    assert item == ["Plant", "Material"]


def test_split_select_fields_empty_input_returns_empty_lists():
    assert _split_select_fields([], FULL_REQUEST["filterMapping"]) == ([], [])


def test_execute_normal_list():
    mock = _MockClient(
        response={
            "d": {
                "results": [
                    {
                        "PurchaseOrder": "4500000001",
                        "Supplier": "DEMOV1",
                        "Plant": "1000",
                        "Material": "MAT001",
                        "OrderQuantity": "10",
                        "PurchaseOrderQuantityUnit": "EA",
                    }
                ]
            }
        }
    )
    service = ODataService(client=mock)
    httpd, port = _start_server(service)
    try:
        status, body = _post(port, FULL_REQUEST)
        assert status == 200
        assert body["success"] is True
        assert body["totalCount"] == 1
        assert len(body["purchaseOrders"]) == 1
        assert body["purchaseOrders"][0]["purchaseOrder"] == "4500000001"
        # $filter was assembled and forwarded to the OData client.
        assert mock.last_call["filter"] == "Supplier eq 'DEMOV1'"
        assert mock.last_call["top"] == 50
        # $select is split by entity: header-only fields go to the A_PurchaseOrder
        # GET, item-only fields (including PurchaseOrder itself, always needed to
        # build the to_PurchaseOrderItem path) go to the item GET.
        assert mock.last_call["select"] == ["PurchaseOrder", "Supplier"]
        # Some SAP OData v2 services reject $count=true; the proxy should
        # return the current page count from normalization instead.
        assert mock.last_call["count"] is False
    finally:
        httpd.shutdown()


def test_execute_attaches_purchase_order_items():
    mock = _MockClient(
        response={
            "d": {
                "results": [
                    {
                        "PurchaseOrder": "DEMOPO2",
                        "Supplier": "DEMOV3",
                        "to_PurchaseOrderItem": {
                            "__deferred": {
                                "uri": "http://sap.example/sap/opu/odata/sap/API_PURCHASEORDER_PROCESS_SRV/A_PurchaseOrder('DEMOPO2')/to_PurchaseOrderItem"
                            }
                        },
                    }
                ]
            }
        }
    )
    mock.path_responses["A_PurchaseOrder('DEMOPO2')/to_PurchaseOrderItem"] = {
        "d": {
            "results": [
                {
                    "PurchaseOrder": "DEMOPO2",
                    "PurchaseOrderItem": "00010",
                    "Material": "MAT001",
                    "Plant": "1100",
                    "OrderQuantity": "2",
                    "PurchaseOrderQuantityUnit": "EA",
                    "__metadata": {"uri": "http://sap.example/item"},
                }
            ]
        }
    }
    service = ODataService(client=mock)
    httpd, port = _start_server(service)
    try:
        request_body = dict(FULL_REQUEST)
        request_body["parameters"] = {"poNumber": "DEMOPO2"}
        status, body = _post(port, request_body)
        assert status == 200
        assert body["success"] is True
        po = body["purchaseOrders"][0]
        assert "to_PurchaseOrderItem" not in po
        assert po["items"] == [
            {
                "purchaseOrder": "DEMOPO2",
                "purchaseOrderItem": "00010",
                "material": "MAT001",
                "plant": "1100",
                "orderQuantity": "2",
                "purchaseOrderUnit": "EA",
            }
        ]
        assert mock.path_calls[0]["entityPath"] == "A_PurchaseOrder('DEMOPO2')/to_PurchaseOrderItem"
        assert mock.path_calls[0]["count"] is False
    finally:
        httpd.shutdown()


def test_execute_filters_purchase_order_items_by_material_and_plant():
    mock = _MockClient(
        response={
            "d": {
                "results": [
                    {"PurchaseOrder": "DEMOPO2", "Supplier": "DEMOV3"},
                    {"PurchaseOrder": "DEMOPO3", "Supplier": "DEMOV3"},
                ]
            }
        }
    )
    mock.path_responses["A_PurchaseOrder('DEMOPO2')/to_PurchaseOrderItem"] = {
        "d": {
            "results": [
                {"PurchaseOrder": "DEMOPO2", "PurchaseOrderItem": "00010", "Material": "MAT001", "Plant": "1100"},
                {"PurchaseOrder": "DEMOPO2", "PurchaseOrderItem": "00020", "Material": "MAT002", "Plant": "1100"},
            ]
        }
    }
    mock.path_responses["A_PurchaseOrder('DEMOPO3')/to_PurchaseOrderItem"] = {
        "d": {
            "results": [
                {"PurchaseOrder": "DEMOPO3", "PurchaseOrderItem": "00010", "Material": "MAT001", "Plant": "1200"}
            ]
        }
    }
    service = ODataService(client=mock)
    httpd, port = _start_server(service)
    try:
        request_body = dict(FULL_REQUEST)
        request_body["parameters"] = {"vendor": "DEMOV3", "material": "MAT001", "plant": "1100"}
        status, body = _post(port, request_body)
        assert status == 200
        assert body["success"] is True
        assert body["totalCount"] == 1
        assert [po["purchaseOrder"] for po in body["purchaseOrders"]] == ["DEMOPO2"]
        assert body["purchaseOrders"][0]["items"][0]["purchaseOrderItem"] == "00010"
        assert mock.last_call["filter"] == "Supplier eq 'DEMOV3'"
        # plant/material are now pushed down as a $filter on the item-level GET
        # (previously only filtered client-side after fetching every item).
        assert mock.path_calls[0]["filter"] == "Plant eq '1100' and Material eq 'MAT001'"
        assert mock.path_calls[0]["select"] == ["Plant", "Material", "OrderQuantity", "PurchaseOrderQuantityUnit"]
    finally:
        httpd.shutdown()


def test_execute_open_only_adds_delivery_and_invoice_clauses_to_item_filter():
    mock = _MockClient(response={"d": {"results": [{"PurchaseOrder": "DEMOPO4", "Supplier": "DEMOV3"}]}})
    mock.path_responses["A_PurchaseOrder('DEMOPO4')/to_PurchaseOrderItem"] = {
        "d": {"results": [{"PurchaseOrder": "DEMOPO4", "PurchaseOrderItem": "00010", "Plant": "1100"}]}
    }
    service = ODataService(client=mock)
    httpd, port = _start_server(service)
    try:
        request_body = dict(FULL_REQUEST)
        request_body["parameters"] = {"vendor": "DEMOV3", "plant": "1100", "openOnly": "true"}
        status, body = _post(port, request_body)
        assert status == 200
        assert body["success"] is True
        # openOnly has no filterMapping entry of its own (server.py hardcodes
        # the two SAP fields it expands to); the plant clause still comes from
        # the normal item filter_mapping path.
        assert mock.path_calls[0]["filter"] == (
            "Plant eq '1100' and IsCompletelyDelivered eq false and IsFinallyInvoiced eq false"
        )
    finally:
        httpd.shutdown()


def test_execute_open_only_alone_produces_only_the_open_item_clause():
    mock = _MockClient(response={"d": {"results": [{"PurchaseOrder": "DEMOPO5", "Supplier": "DEMOV3"}]}})
    mock.path_responses["A_PurchaseOrder('DEMOPO5')/to_PurchaseOrderItem"] = {"d": {"results": []}}
    service = ODataService(client=mock)
    httpd, port = _start_server(service)
    try:
        request_body = dict(FULL_REQUEST)
        request_body["parameters"] = {"vendor": "DEMOV3", "openOnly": "true"}
        status, body = _post(port, request_body)
        assert status == 200
        assert mock.path_calls[0]["filter"] == "IsCompletelyDelivered eq false and IsFinallyInvoiced eq false"
    finally:
        httpd.shutdown()


def test_execute_created_since_adds_datetime_clause_to_header_filter():
    mock = _MockClient(response={"d": {"results": []}})
    request_body = dict(FULL_REQUEST)
    request_body["filterMapping"] = {**FULL_REQUEST["filterMapping"], "createdSince": "CreationDate"}
    request_body["parameters"] = {"vendor": "DEMOV3", "createdSince": "2025-08-26"}
    service = ODataService(client=mock)
    httpd, port = _start_server(service)
    try:
        status, body = _post(port, request_body)
        assert status == 200
        assert mock.last_call["filter"] == "Supplier eq 'DEMOV3' and CreationDate ge datetime'2025-08-26T00:00:00'"
    finally:
        httpd.shutdown()


def test_execute_empty():
    mock = _MockClient(response={"d": {"results": []}})
    service = ODataService(client=mock)
    httpd, port = _start_server(service)
    try:
        status, body = _post(port, FULL_REQUEST)
        assert status == 200
        assert body["success"] is True
        assert body["purchaseOrders"] == []
        assert body["totalCount"] == 0
    finally:
        httpd.shutdown()


def test_execute_sap_error():
    mock = _MockClient(response={"error": {"message": {"value": "boom"}}})
    service = ODataService(client=mock)
    httpd, port = _start_server(service)
    try:
        status, body = _post(port, FULL_REQUEST)
        # SAP responded (with an error payload) -> HTTP 200, success=False.
        assert status == 200
        assert body["success"] is False
        assert body["errorType"] == "ODATA_ERROR"
    finally:
        httpd.shutdown()


def test_execute_client_exception():
    mock = _MockClient(raises=ConnectionError("SAP unreachable"))
    service = ODataService(client=mock)
    httpd, port = _start_server(service)
    try:
        status, body = _post(port, FULL_REQUEST)
        # Upstream (SAP) unreachable -> 502 Bad Gateway.
        assert status == 502
        assert body["success"] is False
        assert body["errorType"] == "CONNECTION_ERROR"
        assert any("SAP unreachable" in m["message"] for m in body["messages"])
    finally:
        httpd.shutdown()


def test_execute_missing_service_ref():
    mock = _MockClient(response={"d": {"results": []}})
    service = ODataService(client=mock)
    httpd, port = _start_server(service)
    try:
        bad = dict(FULL_REQUEST)
        del bad["serviceRef"]
        status, body = _post(port, bad)
        assert status == 400
        assert body["success"] is False
        assert body["errorType"] == "BAD_REQUEST"
    finally:
        httpd.shutdown()


def test_execute_redaction_no_destination_in_response():
    mock = _MockClient(response={"d": {"results": [{"PurchaseOrder": "1"}]}})
    service = ODataService(client=mock)
    httpd, port = _start_server(service)
    try:
        status, body = _post(port, FULL_REQUEST)
        assert status == 200
        body_str = json.dumps(body)
        # Destination / credential material must never leak into the response.
        assert "password" not in body_str.lower()
        assert "base_url" not in body_str
        assert "SAP_PASSWORD" not in body_str
        assert "SAP_URL" not in body_str
        allowed = {"success", "purchaseOrders", "totalCount", "errorType", "messages", "traceId"}
        assert set(body.keys()) <= allowed
    finally:
        httpd.shutdown()

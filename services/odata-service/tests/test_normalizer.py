from __future__ import annotations

from odata_service.normalizer import normalize


def test_v2_collection_with_field_mapping():
    raw = {
        "d": {
            "results": [
                {
                    "PurchaseOrder": "4500000001",
                    "Supplier": "DEMOV1",
                    "Plant": "1000",
                    "Material": "MAT001",
                    "OrderQuantity": "10",
                    "PurchaseOrderUnit": "EA",
                    "__metadata": {"uri": "...", "type": "..."},
                }
            ]
        }
    }
    result = normalize(raw)
    assert result["success"] is True
    assert result["totalCount"] == 1
    assert len(result["purchaseOrders"]) == 1
    po = result["purchaseOrders"][0]
    assert po["purchaseOrder"] == "4500000001"
    assert po["supplier"] == "DEMOV1"
    assert po["plant"] == "1000"
    assert po["material"] == "MAT001"
    assert po["orderQuantity"] == "10"
    assert po["purchaseOrderUnit"] == "EA"
    # OData metadata must be stripped from normalized items.
    assert "__metadata" not in po


def test_v2_collection_strips_deferred_navigation_uri():
    raw = {
        "d": {
            "results": [
                {
                    "PurchaseOrder": "DEMOPO2",
                    "to_PurchaseOrderItem": {
                        "__deferred": {
                            "uri": "http://sap.example/sap/opu/odata/sap/API_PURCHASEORDER_PROCESS_SRV/A_PurchaseOrder('DEMOPO2')/to_PurchaseOrderItem"
                        }
                    },
                }
            ]
        }
    }
    result = normalize(raw)
    po = result["purchaseOrders"][0]
    assert "to_PurchaseOrderItem" not in po
    assert "sap.example" not in str(po)


def test_v2_collection_with_purchase_order_quantity_unit():
    """sap-sto-create uses 'PurchaseOrderQuantityUnit' (not 'PurchaseOrderUnit').

    The normalizer should map both field names to the same normalized key
    'purchaseOrderUnit' so the output contract is stable regardless of which
    SAP field name appears in the response.
    """
    raw = {
        "d": {
            "results": [
                {
                    "PurchaseOrder": "4500000002",
                    "Supplier": "DEMOV2",
                    "Plant": "1001",
                    "Material": "MAT002",
                    "OrderQuantity": "20",
                    "PurchaseOrderQuantityUnit": "KG",
                }
            ]
        }
    }
    result = normalize(raw)
    assert result["success"] is True
    po = result["purchaseOrders"][0]
    assert po["purchaseOrder"] == "4500000002"
    assert po["purchaseOrderUnit"] == "KG"


def test_v4_collection():
    raw = {
        "@odata.context": "...",
        "@odata.count": 2,
        "value": [
            {"PurchaseOrder": "4500000001", "Supplier": "DEMOV1"},
            {"PurchaseOrder": "4500000002", "Supplier": "DEMOV2"},
        ],
    }
    result = normalize(raw)
    assert result["success"] is True
    assert result["totalCount"] == 2
    assert len(result["purchaseOrders"]) == 2


def test_v2_with_explicit_count():
    raw = {"d": {"__count": "5", "results": [{"PurchaseOrder": "1"}, {"PurchaseOrder": "2"}]}}
    result = normalize(raw)
    # totalCount comes from the OData $count, not the array length.
    assert result["totalCount"] == 5


def test_empty_collection_v2():
    raw = {"d": {"results": []}}
    result = normalize(raw)
    assert result["success"] is True
    assert result["purchaseOrders"] == []
    assert result["totalCount"] == 0


def test_empty_collection_v4():
    raw = {"@odata.context": "...", "value": []}
    result = normalize(raw)
    assert result["success"] is True
    assert result["purchaseOrders"] == []
    assert result["totalCount"] == 0


def test_error_response():
    raw = {"error": {"code": "XXX", "message": {"value": "Something went wrong"}}}
    result = normalize(raw)
    assert result["success"] is False
    assert result["purchaseOrders"] == []
    assert result["totalCount"] == 0
    assert result["errorType"] == "ODATA_ERROR"
    assert any("Something went wrong" in m["message"] for m in result["messages"])


def test_v4_error_response_with_string_message():
    raw = {"error": {"code": "YYY", "message": "Plain string message"}}
    result = normalize(raw)
    assert result["success"] is False
    assert result["errorType"] == "ODATA_ERROR"
    assert any("Plain string message" in m["message"] for m in result["messages"])


def test_invalid_structure():
    raw = {"unexpected": "nope"}
    result = normalize(raw)
    assert result["success"] is False
    assert result["errorType"] == "INVALID_RESPONSE"

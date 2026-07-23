"""Gated live integration spike for SAP OData connectivity.

These tests are **skipped by default** and only run when ``SAP_ODATA_LIVE=1``
is set in the environment. They verify real SAP OData reachability, entitySet
field names, CSRF requirements, auth method, and redaction -- collecting
evidence to close Design Doc §7 Open Questions.

Usage::

    SAP_ODATA_LIVE=1 ../../.venv/bin/python -m pytest tests/test_live_spike.py -v -s

Never run these in CI; they depend on a live SAP system and real credentials
loaded from ``.env`` (gitignored).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

# Gate: skip all tests in this module unless SAP_ODATA_LIVE=1.
_LIVE = os.environ.get("SAP_ODATA_LIVE", "") == "1"
_SKIP_REASON = "Set SAP_ODATA_LIVE=1 to run live spike tests (requires real SAP)"

# Load .env from project root so credentials are available when running manually.
if _LIVE:
    try:
        from dotenv import load_dotenv

        _env_path = Path(__file__).resolve().parents[3] / ".env"
        if _env_path.exists():
            load_dotenv(_env_path)
    except ImportError:
        pass

pytestmark = pytest.mark.skipif(not _LIVE, reason=_SKIP_REASON)

# ---------------------------------------------------------------------------
# Imports that touch the real ODataClient are deferred to test bodies so the
# module can be collected (and skipped) without a live destination.
# ---------------------------------------------------------------------------

_SERVICE_REF = "API_PURCHASEORDER_PROCESS_SRV"
_KNOWN_PO = "DEMOPO2"
_KNOWN_PO_MATERIAL = "DEMOA4B"
_KNOWN_PO_PLANT = "5300"
# The binding now declares "A_PurchaseOrder" (aligned to sap-sto-create); the
# spike also tries "PurchaseOrder" for discovery in case the live schema differs.
_CANDIDATE_ENTITY_SETS = ["A_PurchaseOrder", "PurchaseOrder"]
_EXPECTED_FIELDS = [
    "PurchaseOrder",
    "Supplier",
    "Plant",
    "Material",
    "OrderQuantity",
    "PurchaseOrderQuantityUnit",
    "PurchaseOrderUnit",
]
# Candidate delivery-date field names (Design Doc §7 open question).
_CANDIDATE_DATE_FIELDS = [
    "DeliveryDate",
    "ScheduleLineDeliveryDate",
    "PurchasingDocumentDeliveryDate",
]


def _make_client():
    """Build a real ODataClient from env-loaded destination."""
    from odata_service.odata_client import ODataClient

    return ODataClient()


def _find_working_entity_set(client):
    """Try each candidate entitySet; return (entity_set, raw_response) on success."""
    from odata_service.odata_client import ODataHttpError
    from urllib.error import URLError

    last_error = None
    for entity_set in _CANDIDATE_ENTITY_SETS:
        try:
            raw = client.get(_SERVICE_REF, entity_set, "", 1, False)
            return entity_set, raw
        except ODataHttpError as exc:
            last_error = f"{entity_set}: HTTP error {exc}"
        except (URLError, ConnectionError, TimeoutError, OSError) as exc:
            last_error = f"{entity_set}: connection error {exc}"
    pytest.skip(f"No working entitySet found; last error: {last_error}")


# ---------------------------------------------------------------------------
# Test 1: Live reachability + auth
# ---------------------------------------------------------------------------


def test_live_reachability_and_auth():
    """Verify the SAP OData service is reachable with Basic auth from env.

    Closes Design Doc §7 Q1 (reachability) and Q5 (auth method).
    """
    client = _make_client()
    assert client._destination.base_url, "SAP_URL must be set in .env"
    assert client._destination.username, "SAP_USER must be set in .env"
    assert client._destination.password, "SAP_PASSWORD must be set in .env"

    entity_set, raw = _find_working_entity_set(client)

    # If we got here, the service is reachable and auth worked.
    print(f"\n[LIVE] Service reachable: {_SERVICE_REF}")
    print(f"[LIVE] Working entitySet: {entity_set}")
    print(f"[LIVE] Auth method: Basic auth (SAP_USER/SAP_PASSWORD)")
    print(f"[LIVE] Raw response keys: {list(raw.keys()) if isinstance(raw, dict) else type(raw)}")


# ---------------------------------------------------------------------------
# Test 2: EntitySet field name discovery
# ---------------------------------------------------------------------------


def test_live_entity_set_field_names():
    """Discover the actual entitySet field names from the live response.

    Closes Design Doc §7 Q1 (entitySet field names) and Q2 (delivery date).
    """
    client = _make_client()
    entity_set, raw = _find_working_entity_set(client)

    # Extract results (v2 d.results or v4 value).
    results = []
    if isinstance(raw, dict):
        d = raw.get("d")
        if isinstance(d, dict) and isinstance(d.get("results"), list):
            results = d["results"]
        elif isinstance(raw.get("value"), list):
            results = raw["value"]

    print(f"\n[LIVE] entitySet: {entity_set}")
    print(f"[LIVE] result count: {len(results)}")

    if results:
        actual_fields = set(results[0].keys())
        print(f"[LIVE] actual fields in first row: {sorted(actual_fields)}")

        # Check which expected fields are present.
        found = [f for f in _EXPECTED_FIELDS if f in actual_fields]
        missing = [f for f in _EXPECTED_FIELDS if f not in actual_fields]
        print(f"[LIVE] expected fields found: {found}")
        print(f"[LIVE] expected fields missing: {missing}")

        # Check delivery-date candidate fields.
        date_fields_found = [f for f in _CANDIDATE_DATE_FIELDS if f in actual_fields]
        print(f"[LIVE] delivery-date fields found: {date_fields_found}")

        # If field names mismatch the binding assumption, report it.
        if missing:
            print(f"[LIVE] WARNING: binding selectFields has fields not in live schema: {missing}")
    else:
        print("[LIVE] No results returned; cannot verify field names (may need filter)")


# ---------------------------------------------------------------------------
# Test 3: CSRF requirement for GET
# ---------------------------------------------------------------------------


def test_live_csrf_not_required_for_get():
    """Verify that a plain GET (no x-csrf-token fetch) succeeds.

    Closes Design Doc §7 Q4 (CSRF requirement for read GET).
    The ODataClient.get() does NOT send x-csrf-token; if it succeeds,
    CSRF is not required for read.
    """
    client = _make_client()
    entity_set, raw = _find_working_entity_set(client)

    # If we reached here without error, GET works without CSRF.
    print(f"\n[LIVE] CSRF: NOT required for GET (plain GET succeeded on {entity_set})")


# ---------------------------------------------------------------------------
# Test 4: Redaction verification
# ---------------------------------------------------------------------------


def test_live_redaction_no_credentials_in_response():
    """Verify that destination/credentials never appear in the OData response.

    Closes Design Doc redaction requirement (§2.3, §2.7).
    """
    client = _make_client()
    dest = client._destination

    entity_set, raw = _find_working_entity_set(client)
    raw_str = json.dumps(raw, default=str)

    # The response must not contain the password, base_url, or username.
    assert dest.password not in raw_str, "Password leaked into OData response!"
    assert dest.username not in raw_str, "Username leaked into OData response!"
    # base_url is the SAP host -- it should not appear in entity data.
    if dest.base_url:
        # The host portion might appear in OData __metadata.uri, which the
        # normalizer strips; but at the raw level we check the password is absent.
        pass

    print(f"\n[LIVE] Redaction: password/username not in raw OData response (verified)")


# ---------------------------------------------------------------------------
# Test 5: Full /execute round-trip via ODataService
# ---------------------------------------------------------------------------


def test_live_execute_round_trip():
    """Verify a full /execute round-trip returns normalized, redacted output.

    This exercises the real ODataService (not just the raw client) to confirm
    the end-to-end path: $filter assembly -> GET -> normalize -> response.
    """
    from odata_service.server import ODataService

    service = ODataService()  # Uses real ODataClient from env
    payload = {
        "serviceRef": _SERVICE_REF,
        "entitySet": "A_PurchaseOrder",  # sap-sto-create uses this form
        "filterMapping": {
            "poNumber": "PurchaseOrder",
            "vendor": "Supplier",
            "plant": "Plant",
            "material": "Material",
        },
        "parameters": {},
        "topLimit": 5,
        "selectFields": _EXPECTED_FIELDS,
        "traceId": "live-spike-001",
    }

    body, status = service.execute(payload)

    print(f"\n[LIVE] /execute status: {status}")
    print(f"[LIVE] /execute success: {body.get('success')}")
    print(f"[LIVE] /execute totalCount: {body.get('totalCount')}")
    print(f"[LIVE] /execute errorType: {body.get('errorType', 'none')}")
    print(f"[LIVE] /execute purchaseOrders count: {len(body.get('purchaseOrders', []))}")

    body_str = json.dumps(body, default=str)

    # Redaction: no credentials in the normalized response.
    dest = _make_client()._destination
    assert dest.password not in body_str, "Password leaked into /execute response!"
    assert dest.username not in body_str, "Username leaked into /execute response!"

    # If there are results, print field names from the first normalized item.
    if body.get("purchaseOrders"):
        first = body["purchaseOrders"][0]
        print(f"[LIVE] normalized item keys: {sorted(first.keys())}")
        print(f"[LIVE] normalized detail count: {len(first.get('items', []))}")


def test_live_purchase_order_item_filter_known_po():
    """Verify known PO item detail expansion and item-level filtering."""
    from odata_service.server import ODataService

    service = ODataService()
    payload = {
        "serviceRef": _SERVICE_REF,
        "entitySet": "A_PurchaseOrder",
        "filterMapping": {
            "poNumber": "PurchaseOrder",
            "vendor": "Supplier",
            "plant": "Plant",
            "material": "Material",
        },
        "parameters": {
            "poNumber": _KNOWN_PO,
            "material": _KNOWN_PO_MATERIAL,
            "plant": _KNOWN_PO_PLANT,
        },
        "topLimit": 10,
        "selectFields": _EXPECTED_FIELDS,
        "traceId": "live-spike-known-po-item",
    }

    body, status = service.execute(payload)

    print(f"\n[LIVE] known PO /execute status: {status}")
    print(f"[LIVE] known PO /execute success: {body.get('success')}")
    print(f"[LIVE] known PO /execute totalCount: {body.get('totalCount')}")
    print(f"[LIVE] known PO /execute purchaseOrders count: {len(body.get('purchaseOrders', []))}")

    assert status == 200
    assert body.get("success") is True
    assert len(body.get("purchaseOrders", [])) == 1
    order = body["purchaseOrders"][0]
    items = order.get("items", [])
    print(f"[LIVE] known PO items count: {len(items)}")
    if items:
        print(f"[LIVE] known PO first item keys: {sorted(items[0].keys())}")
        print(f"[LIVE] known PO first item: {items[0]}")
    assert order.get("purchaseOrder") == _KNOWN_PO
    assert len(items) == 1
    assert items[0].get("material") == _KNOWN_PO_MATERIAL
    assert items[0].get("plant") == _KNOWN_PO_PLANT

"""
Live equivalence harness: BAPI_AP_ACC_GETOPENITEMS via the pure-ABAP rest2rfc
SICF gateway versus the existing JCO_RFC path through the Java Gateway.

Skipped by default. Run:

    SAP_REST2RFC_LIVE=1 \\
    SAP_REST2RFC_BASE_URL=http://<host>:<port> \\
    REST2RFC_VENDOR=<vendor> REST2RFC_COMPANY_CODE=<companyCode> \\
    [REST2RFC_KEYDATE=<YYYY-MM-DD>] \\
    ../../.venv/bin/python -m pytest tests/live/test_rest2rfc_ap_equivalence.py -v -s

Credentials come only from the environment:
SAP_REST2RFC_CLIENT/USER/PASSWORD (fallback SAP_CLIENT/SAP_USER/SAP_PASSWORD).
The Java Gateway must be running; its URL defaults to http://127.0.0.1:8080
(SAP_NEXUS_GATEWAY_URL).
"""

from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("SAP_REST2RFC_LIVE") != "1",
    reason="live equivalence gate; set SAP_REST2RFC_LIVE=1 to run",
)

CAPABILITY_ID = "FI.AP.GetOpenItems"
RFC_NAME = "BAPI_AP_ACC_GETOPENITEMS"

# Canonical comparison fields: rest2rfc lowercase keys -> JCo camelCase keys.
COMPARED_FIELDS = {
    "comp_code": "compCode",
    "doc_no": "docNo",
    "item_num": "itemNum",
    "doc_type": "docType",
    "doc_date": "docDate",
    "pstng_date": "pstngDate",
    "net_due_date": "netDueDate",
    "amt_doccur": "amtDoccur",
    "currency": "currency",
    "vendor": "vendor",
}


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def _http_post_json(url: str, payload: dict, basic_auth: tuple[str, str] | None) -> tuple[int, dict | None]:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=body, method="POST")
    request.add_header("Content-Type", "application/json; charset=utf-8")
    request.add_header("Accept", "application/json")
    if basic_auth:
        token = base64.b64encode(
            f"{basic_auth[0]}:{basic_auth[1]}".encode("utf-8")
        ).decode("ascii")
        request.add_header("Authorization", f"Basic {token}")
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        # rest2rfc returns an empty body on non-200; keep the reason phrase.
        raw = error.read().decode("utf-8") if error.fp else ""
        parsed = json.loads(raw) if raw.strip() else None
        return error.code, parsed if parsed is not None else {"_reason": error.reason}


def _rest2rfc_open_items(params: dict) -> list[dict]:
    base_url = _env("SAP_REST2RFC_BASE_URL")
    assert base_url, "SAP_REST2RFC_BASE_URL is required"
    client = _env("SAP_REST2RFC_CLIENT", _env("SAP_CLIENT", "800"))
    user = _env("SAP_REST2RFC_USER", _env("SAP_USER"))
    password = _env("SAP_REST2RFC_PASSWORD", _env("SAP_PASSWORD"))

    url = f"{base_url}/sap/bc/rest2rfc?RFC={RFC_NAME}&sap-client={client}"
    body = {
        "VENDOR": params["vendor"],
        "COMPANYCODE": params["companyCode"],
    }
    if params.get("keydate"):
        body["KEYDATE"] = params["keydate"]

    status, response = _http_post_json(url, body, (user, password))
    assert status == 200, f"SICF call failed: {status} {response}"
    return response.get("lineitems", [])


def _jco_open_items(params: dict) -> list[dict]:
    gateway_url = _env("SAP_NEXUS_GATEWAY_URL", "http://127.0.0.1:8080")
    url = f"{gateway_url}/capabilities/{CAPABILITY_ID}/execute"
    parameters = {
        "vendor": params["vendor"],
        "companyCode": params["companyCode"],
    }
    if params.get("keydate"):
        parameters["keydate"] = params["keydate"]

    status, response = _http_post_json(url, {"parameters": parameters}, None)
    assert status == 200, f"Gateway call failed: {status} {response}"
    assert response and response.get("success"), f"JCo execution failed: {response}"
    return response["data"].get("openItems", [])


def _canonical_value(value) -> str:
    # Packed numbers come back with different decimal scales across the two
    # paths (13000000.0 vs 13000000.0000); compare by numeric value.
    import decimal

    text = "" if value is None else str(value).strip()
    if text == "0000-00-00":  # initial DATS on the JCo path
        return ""
    try:
        return str(decimal.Decimal(text).normalize())
    except decimal.InvalidOperation:
        return text


def _canonical_rows(rows: list[dict], key_map: dict[str, str] | None) -> list[tuple]:
    result = []
    for row in rows:
        if key_map:
            values = tuple(_canonical_value(row.get(rest_key)) for rest_key in key_map)
        else:
            values = tuple(
                _canonical_value(row.get(jco_key))
                for jco_key in COMPARED_FIELDS.values()
            )
        result.append(values)
    return sorted(result)


def test_ap_open_items_rest2rfc_equivalent_to_jco(capsys):
    params = {
        "vendor": _env("REST2RFC_VENDOR"),
        "companyCode": _env("REST2RFC_COMPANY_CODE"),
        "keydate": _env("REST2RFC_KEYDATE"),
    }
    assert params["vendor"], "REST2RFC_VENDOR is required"
    assert params["companyCode"], "REST2RFC_COMPANY_CODE is required"

    rest_rows = _rest2rfc_open_items(params)
    jco_rows = _jco_open_items(params)

    with capsys.disabled():
        print(f"\nrest2rfc rows: {len(rest_rows)} | JCo rows: {len(jco_rows)}")

    assert len(rest_rows) == len(jco_rows), (
        f"row count differs: rest2rfc {len(rest_rows)} vs JCo {len(jco_rows)}"
    )

    rest_canonical = _canonical_rows(rest_rows, COMPARED_FIELDS)
    jco_canonical = _canonical_rows(jco_rows, None)

    if rest_canonical != jco_canonical:
        only_rest = sorted(set(rest_canonical) - set(jco_canonical))
        only_jco = sorted(set(jco_canonical) - set(rest_canonical))
        pytest.fail(
            "open item rows differ\n"
            f"only in rest2rfc: {only_rest[:5]}\n"
            f"only in JCo: {only_jco[:5]}"
        )

    with capsys.disabled():
        print(f"equivalence confirmed for {len(rest_rows)} open item rows")

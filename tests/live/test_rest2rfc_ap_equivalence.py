"""
Live equivalence harness for the three list capabilities migrated to REST_JSON:
FI.AP.GetOpenItems, FI.AR.GetOpenItems, SD.SalesOrder.GetList.

For each capability it compares the direct SICF rest2rfc JSON with the Java
Gateway result (which routes through the REST_JSON adapter after migration),
and asserts the established baseline row counts.

Skipped by default. Run:

    SAP_REST2RFC_LIVE=1 \\
    SAP_REST2RFC_BASE_URL=http://<host>:<port> \\
    ../../.venv/bin/python -m pytest tests/live/test_rest2rfc_ap_equivalence.py -v -s

Credentials come only from the environment:
SAP_REST2RFC_CLIENT/USER/PASSWORD (fallback SAP_CLIENT/SAP_USER/SAP_PASSWORD).
The Java Gateway must be running; its URL defaults to http://127.0.0.1:8080
(SAP_NEXUS_GATEWAY_URL).
"""

from __future__ import annotations

import base64
import decimal
import json
import os
import urllib.error
import urllib.request

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("SAP_REST2RFC_LIVE") != "1",
    reason="live equivalence gate; set SAP_REST2RFC_LIVE=1 to run",
)

# capability -> (gateway parameter set, SICF body, expected rows, table key)
SCENARIOS = [
    {
        "id": "FI.AP.GetOpenItems",
        "rfc": "BAPI_AP_ACC_GETOPENITEMS",
        "gateway_params": {
            "vendor": "0000003120",
            "companyCode": "2100",
            "keydate": "2026-09-25",
        },
        "sicf_body": {
            "VENDOR": "0000003120",
            "COMPANYCODE": "2100",
            "KEYDATE": "2026-09-25",
        },
        "baseline_rows": 28197,
        "table": "lineitems",
        "gateway_output": "openItems",
    },
    {
        "id": "FI.AR.GetOpenItems",
        "rfc": "BAPI_AR_ACC_GETOPENITEMS",
        "gateway_params": {
            "customer": "C00403",
            "companyCode": "2100",
            "keydate": "2026-09-25",
        },
        "sicf_body": {
            "CUSTOMER": "C00403",
            "COMPANYCODE": "2100",
            "KEYDATE": "2026-09-25",
        },
        "baseline_rows": 1355,
        "table": "lineitems",
        "gateway_output": "openItems",
    },
    {
        "id": "SD.SalesOrder.GetList",
        "rfc": "BAPI_SALESORDER_GETLIST",
        "gateway_params": {
            "customerNumber": "C00002",
            "salesOrganization": "2110",
            "documentDate": "20260112",
        },
        "sicf_body": {
            "CUSTOMER_NUMBER": "C00002",
            "SALES_ORGANIZATION": "2110",
            "DOCUMENT_DATE": "20260112",
        },
        "baseline_rows": 5164,
        "table": "sales_orders",
        "gateway_output": "salesOrders",
    },
]


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def _http_post_json(url, payload, basic_auth=None, timeout=300):
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
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        raw = error.read().decode("utf-8") if error.fp else ""
        parsed = json.loads(raw) if raw.strip() else None
        return error.code, parsed if parsed is not None else {"_reason": error.reason}


def _canonical_value(value) -> str:
    # Different zero/scale representations across paths must compare equal.
    text = "" if value is None else str(value).strip()
    if text in ("0000-00-00",):
        return ""
    try:
        return str(decimal.Decimal(text).normalize())
    except decimal.InvalidOperation:
        return text


def _camel(s: str) -> str:
    out = ""
    upper = False
    for c in s:
        if c == "_":
            upper = True
        elif upper:
            out += c.upper()
            upper = False
        else:
            out += c
    return out


@pytest.mark.parametrize("scenario", SCENARIOS, ids=[s["id"] for s in SCENARIOS])
def test_migrated_capability_equivalent_and_at_baseline(scenario, capsys):
    base_url = _env("SAP_REST2RFC_BASE_URL")
    assert base_url, "SAP_REST2RFC_BASE_URL is required"
    client = _env("SAP_REST2RFC_CLIENT", _env("SAP_CLIENT", "800"))
    user = _env("SAP_REST2RFC_USER", _env("SAP_USER"))
    password = _env("SAP_REST2RFC_PASSWORD", _env("SAP_PASSWORD"))

    # Direct SICF call.
    sicf_url = f"{base_url}/sap/bc/rest2rfc?RFC={scenario['rfc']}&sap-client={client}"
    status, sicf = _http_post_json(
        sicf_url, scenario["sicf_body"], (user, password))
    assert status == 200, f"SICF failed: {status} {sicf}"
    sicf_rows = sicf.get(scenario["table"], [])

    # Gateway call (REST_JSON adapter after migration).
    gateway_url = _env("SAP_NEXUS_GATEWAY_URL", "http://127.0.0.1:8080")
    url = f"{gateway_url}/capabilities/{scenario['id']}/execute"
    status, gw = _http_post_json(
        url, {"parameters": scenario["gateway_params"]})
    assert status == 200, f"Gateway failed: {status} {gw}"
    assert gw and gw.get("success"), f"Gateway execution failed: {gw}"
    assert gw["executor"]["type"] == "REST_JSON", "capability did not migrate"
    gw_rows = gw["data"].get(scenario["gateway_output"], [])

    with capsys.disabled():
        print(f"\nSICF rows: {len(sicf_rows)} | Gateway rows: {len(gw_rows)} "
              f"| baseline: {scenario['baseline_rows']}")

    assert len(sicf_rows) == scenario["baseline_rows"], "SICF drifted from baseline"
    assert len(gw_rows) == scenario["baseline_rows"], "Gateway drifted from baseline"

    # Row shape: direct SICF lowercase keys -> gateway camelCase keys.
    key_map = {k: _camel(k) for k in sicf_rows[0]}
    missing = [k for k, jk in key_map.items() if jk not in gw_rows[0]]
    assert not missing, f"gateway rows missing fields: {missing}"

    def canonical_sicf(row):
        return tuple(_canonical_value(row.get(k)) for k in key_map)

    def canonical_gateway(row):
        return tuple(_canonical_value(row.get(jk)) for jk in key_map.values())

    sicf_canonical = sorted(canonical_sicf(r) for r in sicf_rows)
    gw_canonical = sorted(canonical_gateway(r) for r in gw_rows)
    assert sicf_canonical == gw_canonical, (
        "row content differs\n"
        f"only in SICF: {[r for r in sicf_canonical if r not in gw_canonical][:3]}\n"
        f"only in Gateway: {[r for r in gw_canonical if r not in sicf_canonical][:3]}"
    )

    with capsys.disabled():
        print(f"equivalence confirmed for {len(gw_rows)} rows")

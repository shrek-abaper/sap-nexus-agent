# odata-service

SAP OData **read-only** microservice for the sap-nexus-agent gateway. The Java
gateway (`services/gateway/odata/ODataHttpProxyAdapter`, a thin reverse proxy)
forwards OData capability requests here; this service assembles the OData
`$filter`, issues a GET to SAP OData, and returns a normalized JSON contract.

## Responsibilities

- Assemble `$filter` from semantic parameters + a binding-declared `filterMapping`.
- Issue a read-only GET to SAP OData (`sap-client` header, Basic auth from env).
- Normalize the OData response (v2 `d.results` / v4 `value`) into a stable
  `purchaseOrders` array + `totalCount`.
- Read-only: no write, no deep insert, no `BAPI_TRANSACTION_COMMIT`.

## Run

```bash
python -m odata_service.server   # listens on :8081
```

## POST /execute contract (:8081)

Request:

```json
{
  "serviceRef": "API_PURCHASEORDER_PROCESS_SRV",
  "entitySet": "A_PurchaseOrder",
  "filterMapping": { "poNumber": "PurchaseOrder", "vendor": "Supplier", "plant": "Plant", "material": "Material" },
  "parameters": { "vendor": "DEMOV1" },
  "topLimit": 50,
  "selectFields": ["PurchaseOrder", "Supplier", "Plant", "Material", "OrderQuantity", "PurchaseOrderQuantityUnit"],
  "traceId": "trace-1"
}
```

Response (success / SAP application error -> HTTP 200):

```json
{
  "success": true,
  "purchaseOrders": [ { "purchaseOrder": "...", "supplier": "...", "plant": "...", "material": "...", "orderQuantity": "...", "purchaseOrderUnit": "..." } ],
  "totalCount": 1,
  "traceId": "trace-1"
}
```

Response (error):

```json
{
  "success": false,
  "purchaseOrders": [],
  "totalCount": 0,
  "errorType": "ODATA_ERROR | INVALID_RESPONSE | CONNECTION_ERROR | BAD_REQUEST",
  "messages": [ { "type": "E", "message": "..." } ],
  "traceId": "trace-1"
}
```

HTTP status: `200` (success or SAP-level error), `400` (bad request), `502`
(upstream SAP unreachable).

## Field mapping (normalizer)

| SAP field | normalized key |
|-----------|----------------|
| `PurchaseOrder` | `purchaseOrder` |
| `Supplier` | `supplier` |
| `Plant` | `plant` |
| `Material` | `material` |
| `OrderQuantity` | `orderQuantity` |
| `PurchaseOrderUnit` | `purchaseOrderUnit` |
| `PurchaseOrderQuantityUnit` | `purchaseOrderUnit` (sap-sto-create variant) |

The delivery-date field is deferred to the live spike (Design Doc open question).

## Environment configuration

Destination (base URL / credentials / sap-client) is injected via environment
and **never** appears in responses, logs, or traces. Credential env vars are
shared with the JCo path and `sap-sto-create` so a single `.env` file works for
both OData and JCo.

| Env var | purpose |
|---------|---------|
| `SAP_URL` | SAP OData HTTP base URL (shared with JCo / sap-sto-create) |
| `SAP_CLIENT` | SAP client (default `800`; shared with JCo) |
| `SAP_USER` | Basic auth username (shared with JCo) |
| `SAP_PASSWORD` | Basic auth password (shared with JCo) |
| `SAP_LANG` | `sap-language` (default `EN`; shared with JCo) |
| `SAP_ODATA_TIMEOUT_SECONDS` | OData HTTP timeout in seconds (default `30`; OData-specific) |
| `SAP_ODATA_LIVE` | Set to `1` to enable gated live integration tests (default: skip) |

## Tests

```bash
cd services/odata-service && python -m pytest -v
```

Tests use a mock OData client; no live SAP connection is required.

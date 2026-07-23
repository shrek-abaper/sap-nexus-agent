# Design: PO OData Item Detail Filtering

## Runtime Flow

1. `ODataService.execute()` receives the registered binding payload from the
   Java Gateway proxy.
2. It builds a header `$filter` only from header-safe parameters:
   `poNumber -> PurchaseOrder` and `vendor -> Supplier`.
3. It fetches `A_PurchaseOrder` header rows using the existing read-only
   `ODataClient.get()` path.
4. For each matched header row, it calls a new read-only navigation request for
   `A_PurchaseOrder('<po>')/to_PurchaseOrderItem`.
5. Item rows are normalized and attached to the header result as `items`.
6. If `material` or `plant` are provided, the service keeps only item rows that
   match those values and drops headers with no remaining items.

## Data Contract

Each purchase order result keeps existing normalized header fields and adds:

```json
{
  "items": [
    {
      "purchaseOrder": "DEMOPO2",
      "purchaseOrderItem": "00010",
      "material": "MAT001",
      "plant": "1100",
      "orderQuantity": "1",
      "purchaseOrderUnit": "EA"
    }
  ]
}
```

The service must continue to strip OData metadata and must not expose
destination, credential, token, cookie, or raw authorization data.

## Testing

- Unit test navigation item fetch and item normalization.
- Unit test `material` / `plant` item filtering.
- Keep existing OData service and Gateway regression tests green.
- Run live SAP spike against a known PO to confirm item detail retrieval.

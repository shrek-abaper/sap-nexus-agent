# Proposal: PO OData Item Detail Filtering

## Why

The PO OData read pilot can now query `A_PurchaseOrder` header records, but the
live SAP service exposes material, plant, quantity, and unit through PO item
detail navigation rather than the header entity. The current capability cannot
return or filter by item-level facts.

## What Changes

- Extend the Python OData service to fetch PO item details for matched header
  purchase orders.
- Normalize item detail fields into each returned purchase order as an `items`
  array.
- Support item-level filtering by `material` and `plant` after item detail
  normalization.
- Keep `poNumber` and `vendor` filters on the header query.
- Activate `MM.PurchaseOrder.GetList` after item detail querying and eval
  coverage are validated.
- Keep Gateway as a thin proxy; do not add caller-provided OData URLs or raw
  technical overrides.

## Out Of Scope

- Adding SAP write behavior.
- Adding arbitrary OData endpoint execution.
- Implementing full pagination traversal.

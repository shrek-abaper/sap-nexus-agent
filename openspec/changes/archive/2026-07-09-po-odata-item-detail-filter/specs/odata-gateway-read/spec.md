# Delta: OData Gateway Read

## MODIFIED Requirements

### Requirement: OData list result normalization

The Gateway SHALL normalize OData response entity collections into a capability-level `ExecutionResult` with a list output field, preserving `traceId`, `bindingId`, count, and per-item structured fields without exposing raw OData JSON, credentials, or destination details.

#### Scenario: Normalize purchase order headers with item details

- **WHEN** the OData adapter receives purchase order header records for `MM.PurchaseOrder.GetList`
- **THEN** the capability-level `ExecutionResult` exposes a `purchaseOrders` array with each order's header fields
- **AND** each order MAY include an `items` array with item-level fields such as item number, material, plant, quantity, and unit
- **AND** raw OData metadata, destination URL, token, cookie, and authorization header are not exposed

### Requirement: OData parameter to filter mapping

The Gateway SHALL map registered capability filter parameters to OData `$filter` expressions according to binding metadata, and MUST enforce the capability's parameter required/optional and "at-least-one-filter" semantics before execution.

#### Scenario: Apply header and item filters to purchase order list

- **WHEN** `MM.PurchaseOrder.GetList` is executed with `poNumber` or `vendor` parameters
- **THEN** the OData service applies those filters to the `A_PurchaseOrder` header query
- **WHEN** the same request includes `material` or `plant` parameters
- **THEN** the OData service applies those filters to normalized purchase order item details
- **AND** headers with no remaining matching items are omitted from the normalized result

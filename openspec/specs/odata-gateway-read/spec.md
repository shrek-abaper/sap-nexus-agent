# odata-gateway-read Specification

## Purpose

Define the governed read-only OData executor path for registered SAP capabilities,
including the Java Gateway thin proxy, Python OData service, purchase order
header and item-detail normalization, item-level filtering, and sensitive-data
redaction boundaries.

## Requirements
### Requirement: OData read-only execution via registered binding

The Gateway SHALL execute OData read capabilities through a registered `ODATA` executor binding, resolving `serviceRef`, `entitySet`, and `$filter` mapping from binding metadata without accepting caller-provided OData URLs, service paths, endpoints, HTTP methods, headers, or credentials.

#### Scenario: Execute OData purchase order list query

- **WHEN** a valid capability execution request is accepted for `MM.PurchaseOrder.GetList` with at least one filter parameter
- **THEN** the Gateway builds an OData read request using the capability's registered `executorBinding.bindingId`
- **AND** the request resolves `serviceRef`, `entitySet`, and `$filter` from registered binding metadata
- **AND** the request does not use caller-provided OData URL, service path, endpoint, HTTP method, header, or credential fields

#### Scenario: Reject raw OData endpoint override

- **WHEN** a caller includes a raw OData URL, service path, entity set, `$filter` string, HTTP method, header, or credential override
- **THEN** the Gateway rejects or ignores those fields before OData adapter execution
- **AND** no arbitrary OData HTTP call is attempted with caller-owned technical details

#### Scenario: Java proxy forwards to Python OData service

- **WHEN** the Gateway dispatches an `ODATA` binding to the OData proxy adapter
- **THEN** the Java proxy adapter resolves `serviceRef`, `entitySet`, `filterMapping`, `topLimit` from registered binding metadata and forwards them with the caller's semantic parameters to the Python OData service via HTTP
- **AND** the Python OData service assembles the OData `$filter`, performs the SAP OData HTTP call, and returns a normalized JSON collection
- **AND** the Java proxy adapter normalizes the returned JSON into the standard `TechnicalExecutionResult` and applies redaction
- **AND** the Java proxy adapter does not assemble `$filter`, does not hold OData destination credentials, and does not call SAP directly

### Requirement: OData parameter to filter mapping

The Gateway SHALL map registered capability filter parameters to OData `$filter` expressions according to binding metadata, and MUST enforce the capability's parameter required/optional and "at-least-one-filter" semantics before execution.

#### Scenario: Apply header and item filters to purchase order list

- **WHEN** `MM.PurchaseOrder.GetList` is executed with `poNumber` or `vendor` parameters
- **THEN** the OData service applies those filters to the `A_PurchaseOrder` header query
- **WHEN** the same request includes `material` or `plant` parameters
- **THEN** the OData service applies those filters to normalized purchase order item details
- **AND** headers with no remaining matching items are omitted from the normalized result

### Requirement: OData list result normalization

The Gateway SHALL normalize OData response entity collections into a capability-level `ExecutionResult` with a list output field, preserving `traceId`, `bindingId`, count, and per-item structured fields without exposing raw OData JSON, credentials, or destination details.

#### Scenario: Normalize purchase order headers with item details

- **WHEN** the OData adapter receives purchase order header records for `MM.PurchaseOrder.GetList`
- **THEN** the capability-level `ExecutionResult` exposes a `purchaseOrders` array with each order's header fields
- **AND** each order MAY include an `items` array with item-level fields such as item number, material, plant, quantity, and unit
- **AND** raw OData metadata, destination URL, token, cookie, and authorization header are not exposed

### Requirement: OData read pagination boundary

The Gateway SHALL apply a `$top` upper limit for OData list read capabilities when configured, MUST NOT require `$count`, and MUST NOT implement arbitrary pagination traversal in this change.

#### Scenario: Cap OData list result with top limit

- **WHEN** `MM.PurchaseOrder.GetList` matches more than the configured `$top` limit
- **THEN** the Gateway returns at most the configured maximum number of items
- **AND** the capability-level result or narrative indicates that only the first N items are returned

### Requirement: OData credentials and destination redaction

The Gateway MUST apply sensitive-data redaction at the OData execution boundary so destination config, base URL, token, cookie, authorization header, and credential reference material never appear in response, trace, or log output.

#### Scenario: Redact OData destination and credential material

- **WHEN** an OData technical request, result, trace, or error contains destination base URL, SAP password, token, cookie, authorization header, `.env` content, or credential reference material
- **THEN** the Gateway redacts the sensitive value before returning or writing trace output
- **AND** verification can prove no sensitive value is exposed through normal response, trace, or error paths

#### Scenario: Registry stores only non-sensitive OData binding metadata

- **WHEN** an `ODATA` executor binding is registered for `MM.PurchaseOrder.GetList`
- **THEN** the Registry stores only `serviceRef`, `entitySet`, `$filter` mapping, and other non-sensitive binding metadata
- **AND** the Registry does not store base URL, token, credential, or destination connection details

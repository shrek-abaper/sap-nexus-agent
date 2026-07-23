## ADDED Requirements

### Requirement: Purchase order ExecutionResult to ReasoningFact conversion with nested items

The system SHALL convert a successful purchase order `ExecutionResult` into one `ReasoningFact` per purchase order item, handling the real OData nested structure where item-level fields (`plant`, `material`, `orderQuantity`, `purchaseOrderUnit`) are nested inside a `header.items[]` sub-array. The system SHALL also remain backward-compatible with the flat shape where all fields sit directly on the purchase order entry.

#### Scenario: Nested OData items produce one fact per item

- **WHEN** a successful purchase order execution returns `purchaseOrders` where each entry has a nested `items` array
- **THEN** the Agent creates one `ReasoningFact` per item
- **AND** each fact's evidence carries `purchaseOrder` and `supplier` from the header entry
- **AND** each fact's evidence carries `plant`, `material`, `orderQuantity`, `purchaseOrderUnit` from the nested item
- **AND** the Chinese narrative lists each item without a narrative guard failure

#### Scenario: Flat purchase order entries remain supported

- **WHEN** a successful purchase order execution returns `purchaseOrders` where each entry carries all fields directly (no `items` array)
- **THEN** the Agent creates one `ReasoningFact` per purchase order entry using the entry's own fields
- **AND** existing flat-shape behavior is preserved

#### Scenario: Empty nested items yield no fact for that purchase order

- **WHEN** a purchase order entry has an empty `items` array
- **THEN** the Agent creates no `ReasoningFact` for that entry
- **AND** if all entries have empty items, the narrator returns the no-match message

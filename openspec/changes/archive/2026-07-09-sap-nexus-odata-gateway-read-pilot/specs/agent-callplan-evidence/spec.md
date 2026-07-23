## MODIFIED Requirements

### Requirement: Closed-set capability selection
The system SHALL select capabilities only from the Registry closed set and MUST reject unsupported intent before Gateway execution. The selector SHALL route recognized intents to their registered capability IDs across executor types (for example `inventory_availability` -> `MM.Inventory.GetAvailability` via `JCO_RFC`, `purchase_order_list` -> `MM.PurchaseOrder.GetList` via `ODATA`) without the Agent needing to know the executor type or binding at selection time. LLM-assisted selection MUST be constrained to the same closed set and MUST NOT introduce new executable capability IDs.

#### Scenario: Route inventory intent to inventory capability
- **WHEN** the rule parser identifies `inventory_availability` intent with required `material` and `plant`
- **THEN** the Agent selects `capabilityId=MM.Inventory.GetAvailability` and proceeds to CallPlan and Gateway validation
- **AND** the Agent does not choose an executor type or binding at selection time

#### Scenario: Route purchase order intent to purchase order capability
- **WHEN** the rule parser identifies `purchase_order_list` intent with at least one filter parameter
- **THEN** the Agent selects `capabilityId=MM.PurchaseOrder.GetList` and proceeds to CallPlan and Gateway validation
- **AND** the Agent does not choose an executor type or binding at selection time

#### Scenario: LLM selects registered capability only
- **WHEN** the LLM returns `capabilityId=MM.Inventory.GetAvailability` or `capabilityId=MM.PurchaseOrder.GetList` with required parameters
- **THEN** the Agent accepts the candidate only after deterministic validation confirms the closed-set capability

#### Scenario: LLM returns unknown capability
- **WHEN** the LLM returns an unknown or unsupported `capabilityId`
- **THEN** the Agent rejects that LLM output for execution and does not call Gateway validate or execute from it

## ADDED Requirements

### Requirement: Purchase order list intent parsing
The system SHALL parse Chinese purchase order list queries for `MM.PurchaseOrder.GetList` into normalized intent parameters without using free-form RFC names or raw OData endpoints. The parser MAY use the real LLM intent adapter before deterministic validation, but the LLM output is advisory and MUST be normalized into the same closed-set intent contract before capability selection.

#### Scenario: Parse purchase order query with vendor filter
- **WHEN** the user asks `查供应商 DEMOV1 的采购订单`
- **THEN** the Agent identifies `purchase_order_list` intent and extracts `vendor=DEMOV1`
- **AND** the Agent proceeds through deterministic closed-set capability selection before Gateway validation

#### Scenario: Parse purchase order query with multiple filters
- **WHEN** the user asks `查工厂 1000 物料 MAT001 的采购订单`
- **THEN** the Agent identifies `purchase_order_list` intent and extracts plant and material parameters
- **AND** the Agent maps the parameters to the registered `$filter` fields through the capability contract, not by emitting a raw OData `$filter` string

#### Scenario: Clarify missing filter before Gateway call
- **WHEN** the user asks `帮我看看采购订单` without any of PO number, vendor, plant/purchasing group, or material
- **THEN** the Agent returns a Chinese clarification asking for at least one filter parameter
- **AND** the Agent does not call Gateway validate or execute

#### Scenario: Reject raw OData endpoint in user or LLM input
- **WHEN** the user or LLM output contains a raw OData URL, service path, or `$filter` string
- **THEN** the Agent treats the input as untrusted and does not execute from it
- **AND** Gateway validate and execute are not called unless a safe fallback parser independently produces a valid closed-set capability request

### Requirement: List execution result to reasoning facts
The system SHALL convert a successful list-shaped `ExecutionResult` into one or more deterministic `ReasoningFact` entries before narration, with one fact per returned item, and MUST narrate list results only from fields present in those facts.

#### Scenario: Successful list execution creates per-item facts
- **WHEN** Gateway execute returns success with a non-empty `purchaseOrders` array for `MM.PurchaseOrder.GetList`
- **THEN** the Agent creates one `ReasoningFact` per purchase order item with `predicate=purchaseOrderItem`, `deterministic=true`, `confidence=1.0`, source capability metadata, and per-item evidence fields
- **AND** the Chinese narrative cites only those item fields present in the facts and does not invent additional records

#### Scenario: Empty list execution creates no item facts
- **WHEN** Gateway execute returns success with an empty `purchaseOrders` array for a valid filter
- **THEN** the Agent does not create per-item facts that claim records exist
- **AND** the Chinese narrative states that no matching purchase orders were found

#### Scenario: Narrator rejects list item values not present in facts
- **WHEN** the narrator is asked to output a PO number, vendor, or quantity that is not present in any `ReasoningFact`
- **THEN** the Agent returns or raises a narrative guard failure instead of inventing the value

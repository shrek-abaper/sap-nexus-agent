## MODIFIED Requirements

### Requirement: Capability registry source of truth
The system SHALL provide a lightweight capability registry as the runtime source of truth for executable SAP capabilities. The registry SHALL include executor type metadata so capabilities can later route to different SAP access methods without exposing technical endpoints to callers.

#### Scenario: Load active capability from registry
- **WHEN** the Gateway starts with a valid `registry/capabilities.yaml` containing an active `MM.Inventory.GetAvailability` Function
- **THEN** the Gateway capability catalog includes `MM.Inventory.GetAvailability` with its kind, domain, business object, executor type, and governance metadata
- **AND** the executor type is `JCO_RFC` for the current inventory implementation

#### Scenario: Reject malformed registry entry
- **WHEN** a capability registry entry is missing required identity, executor, input, output, or governance fields
- **THEN** registry validation fails with a structured validation error and the malformed capability is not exposed for execution

### Requirement: Execute registered SAP read capability
The system SHALL execute registered READ Functions through SAP JCo and return a normalized `ExecutionResult`.

#### Scenario: Execute inventory availability capability
- **WHEN** a client executes `MM.Inventory.GetAvailability` with valid parameters
- **THEN** the Gateway maps the registered `capabilityId` to `BAPI_MATERIAL_STOCK_REQ_LIST`
- **AND** invokes SAP through JCo
- **AND** returns an `ExecutionResult` containing `traceId`, `capabilityId`, executor metadata, normalized return messages, data, duration, and success state
- **AND** `data.availableQuantity` is derived from the MD04 current stock row in `MRP_IND_LINES`, not from ATP-only `BAPI_MATERIAL_AVAILABILITY`

#### Scenario: READ capability does not commit
- **WHEN** the Gateway executes a READ Function
- **THEN** it does not call `BAPI_TRANSACTION_COMMIT` or `BAPI_TRANSACTION_ROLLBACK`

#### Scenario: SAP business error is normalized
- **WHEN** SAP returns an error or abort message for a registered capability execution
- **THEN** the Gateway returns a failed `ExecutionResult` with `SAP_BUSINESS_ERROR` and normalized SAP return messages

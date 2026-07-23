# capability-registry-gateway Specification

## Purpose
TBD - created by archiving change sap-nexus-capability-registry-gateway. Update Purpose after archive.
## Requirements
### Requirement: Capability registry source of truth
The system SHALL provide a lightweight capability registry as the runtime source of truth for executable SAP capabilities. The registry SHALL include executor type metadata so capabilities can later route to different SAP access methods without exposing technical endpoints to callers.

#### Scenario: Load active capability from registry
- **WHEN** the Gateway starts with a valid `registry/capabilities.yaml` containing an active `MM.Inventory.GetAvailability` Function
- **THEN** the Gateway capability catalog includes `MM.Inventory.GetAvailability` with its kind, domain, business object, executor type, and governance metadata
- **AND** the executor type is `JCO_RFC` for the current inventory implementation

#### Scenario: Reject malformed registry entry
- **WHEN** a capability registry entry is missing required identity, executor, input, output, or governance fields
- **THEN** registry validation fails with a structured validation error and the malformed capability is not exposed for execution

### Requirement: Capability-level Gateway API
The system SHALL expose SAP execution through capability-level Gateway APIs and MUST NOT expose arbitrary RFC execution.

#### Scenario: List registered capabilities
- **WHEN** a client calls `GET /capabilities`
- **THEN** the Gateway returns only enabled registered capabilities and does not require or expose raw SAP RFC names as callable endpoints

#### Scenario: Reject unknown capability
- **WHEN** a client calls validate or execute for an unregistered `capabilityId`
- **THEN** the Gateway returns `CAPABILITY_NOT_FOUND` and does not invoke SAP JCo

#### Scenario: No arbitrary RFC endpoint
- **WHEN** the Gateway API surface is inspected
- **THEN** there is no endpoint that allows a caller to submit an arbitrary `rfcName` for execution

### Requirement: Validate before execute
The system SHALL validate capability identity, status, required parameters, parameter constraints, and governance rules before SAP execution.

#### Scenario: Missing required parameter is blocked
- **WHEN** a client validates `MM.Inventory.GetAvailability` without required `material` or `plant`
- **THEN** the Gateway returns `MISSING_PARAMETER` and does not invoke SAP JCo

#### Scenario: Invalid parameter is blocked
- **WHEN** a client validates `MM.Inventory.GetAvailability` with a parameter that violates the registry constraints
- **THEN** the Gateway returns `INVALID_PARAMETER` and does not invoke SAP JCo

#### Scenario: Valid read capability passes validation
- **WHEN** a client validates `MM.Inventory.GetAvailability` with valid `material`, `plant`, and optional `unit`
- **THEN** the Gateway returns a successful validation result that includes the `traceId` and selected `capabilityId`

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

### Requirement: Trace capability validation and execution
The system SHALL emit replayable JSONL trace records for capability validation and execution without leaking sensitive SAP configuration.

#### Scenario: Execute writes trace record
- **WHEN** a capability execute call completes successfully or unsuccessfully
- **THEN** the Gateway appends a JSONL trace record containing `traceId`, timestamp, capabilityId, operation, parameter summary, success flag, duration, and errorType

#### Scenario: Trace excludes secrets
- **WHEN** trace records are written
- **THEN** they do not include SAP passwords, full sensitive destination configuration, tokens, or `.env` contents

### Requirement: Engineering skeleton and verification commands
The system SHALL provide an engineering skeleton with documented verification commands for Gateway development.

#### Scenario: Gateway project skeleton is present
- **WHEN** the change is built
- **THEN** the repository contains `gateway-jco/`, `registry/`, `schemas/`, and runtime output ignore rules needed for the capability registry gateway slice

#### Scenario: Fast verification is documented
- **WHEN** a developer reads the Gateway README or runbook
- **THEN** they can find commands for local build/test, health check, capabilities check, and any live SAP smoke test prerequisites

### Requirement: Flexible intent recognition from registry capability set

The Agent SHALL derive the intent recognition capability closed set from active capabilities in the capability registry (`registry/capabilities.yaml`), rather than hardcoding a single capability. The LLM intent path SHALL dynamically inject all active capabilities' `capabilityId`, `description`, and `inputs` into the LLM prompt, and the LLM SHALL select a `capabilityId` directly from that closed set. A capability registered as `status: active` SHALL become selectable by the LLM path without any intent-recognition code change.

#### Scenario: Registered purchase order capability is selectable via natural language

- **WHEN** a user submits `查询采购订单DEMOPO1` and `MM.PurchaseOrder.GetList` is an active registered capability
- **THEN** the Agent intent recognition selects `MM.PurchaseOrder.GetList` (via LLM or rule fallback)
- **AND** extracts `poNumber=DEMOPO1` as a parameter
- **AND** the run proceeds to capability selection, CallPlan, Gateway validate, and Gateway execute for that capability
- **AND** does not return the "仅支持已注册的只读能力" unsupported message

#### Scenario: LLM selects capabilityId from dynamic registry closed set

- **WHEN** the LLM intent path runs with a registry containing both `MM.Inventory.GetAvailability` and `MM.PurchaseOrder.GetList` as active capabilities
- **THEN** the LLM prompt lists both capabilityIds with their descriptions and inputs
- **AND** the LLM returns a `capabilityId` that is a member of the active registry closed set
- **AND** a `capabilityId` not in the active registry closed set is rejected as unsupported

#### Scenario: Required parameters validated against selected capability inputs

- **WHEN** the LLM selects a capabilityId and the registry defines required inputs for that capability
- **THEN** the Agent validates that all required inputs are present
- **AND** if a required input is missing, returns a clarification identifying the missing parameter
- **AND** does not proceed to Gateway execution until required inputs are satisfied

#### Scenario: Rule fallback covers registered explicit intents when LLM unavailable

- **WHEN** the LLM is unavailable (missing configuration or connection failure) in hybrid mode
- **THEN** the Agent falls back to the unified rule parser (`parse_intent`) that recognizes both inventory and purchase order list intents
- **AND** does not fall back to an inventory-only parser
- **AND** a registered explicit-intent query (e.g. `查询采购订单DEMOPO1`) still resolves to the correct capability

#### Scenario: Newly registered active capability is auto-supported by LLM path

- **WHEN** a new capability is added to `registry/capabilities.yaml` with `status: active` and a description and inputs
- **AND** no intent-recognition code is changed
- **THEN** the LLM path can select the new capabilityId from the dynamically injected prompt
- **AND** the rule fallback does not need to know about the new capability for the LLM path to work

#### Scenario: CLI unified entry routes to any registered capability

- **WHEN** the Agent CLI entry processes a query
- **THEN** it uses the unified `run_query` entry that routes by selected capabilityId
- **AND** can route to both inventory and purchase order capabilities
- **AND** does not use an inventory-only entry that prevents purchase order routing


## ADDED Requirements

### Requirement: Capability registry source of truth
The system SHALL provide a lightweight capability registry as the runtime source of truth for executable SAP capabilities.

#### Scenario: Load active capability from registry
- **WHEN** the Gateway starts with a valid `registry/capabilities.yaml` containing an active `MM.Inventory.GetAvailability` Function
- **THEN** the Gateway capability catalog includes `MM.Inventory.GetAvailability` with its kind, domain, business object, executor type, and governance metadata

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
- **THEN** the Gateway maps the registered `capabilityId` to `BAPI_MATERIAL_AVAILABILITY`, invokes SAP through JCo, and returns an `ExecutionResult` containing `traceId`, `capabilityId`, executor metadata, normalized return messages, data, duration, and success state

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

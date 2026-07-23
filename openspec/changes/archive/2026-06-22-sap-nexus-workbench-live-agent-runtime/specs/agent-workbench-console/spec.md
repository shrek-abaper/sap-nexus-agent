## MODIFIED Requirements

### Requirement: Workbench run submission through Agent Runtime Adapter
The system SHALL provide a local Workbench UI that submits natural language Agent queries through an Agent Runtime Adapter. For read-only inventory queries, the Agent Runtime Adapter SHALL invoke the controlled local Python Agent runtime, which calls Gateway validation and execution for registered capabilities. UI components MUST NOT call SAP, Java Gateway, or arbitrary RFC execution directly.

#### Scenario: Submit Chinese inventory query through live Agent runtime
- **WHEN** a user submits `DEMOA1 在 1000 还有多少可用库存？` from the Workbench page
- **THEN** the UI creates an Agent run through the Agent Runtime Adapter
- **AND** the Adapter invokes the local Python Agent runtime for `MM.Inventory.GetAvailability`
- **AND** the Python Agent calls Gateway `validate` before Gateway `execute`
- **AND** the displayed quantity, error, or clarification comes from the Agent/Gateway result rather than deterministic fake Workbench data
- **AND** the UI does not submit or expose a raw `rfcName`

#### Scenario: Reject direct RFC override
- **WHEN** a Workbench request includes an attempted `rfcName` override
- **THEN** the Agent Runtime Adapter rejects or removes the override before execution
- **AND** no frontend route forwards that `rfcName` to the Java Gateway or SAP
- **AND** no Python Agent runner process is invoked for that rejected request

### Requirement: Redacted artifact panels
The system SHALL display redacted Agent artifacts for CallPlan, Gateway validation, ExecutionResult, ReasoningFact, Chinese narrative, and trace metadata.

#### Scenario: Display successful live run artifacts
- **WHEN** a successful inventory availability run produces artifacts from the Python Agent and Gateway
- **THEN** the Workbench displays redacted panels for CallPlan, Gateway validation, ExecutionResult, ReasoningFact, Chinese narrative, agent trace ID, and gateway trace ID
- **AND** `ExecutionResult.data.availableQuantity` reflects the normalized Gateway/SAP result

#### Scenario: Artifact panels preserve harness boundaries
- **WHEN** artifact panels render CallPlan or ExecutionResult data
- **THEN** they display the registered `capabilityId` and safe executor metadata from normalized artifacts
- **AND** they do not provide controls for arbitrary RFC execution

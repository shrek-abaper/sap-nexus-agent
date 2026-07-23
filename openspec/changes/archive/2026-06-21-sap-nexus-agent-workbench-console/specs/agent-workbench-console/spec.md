## ADDED Requirements

### Requirement: Workbench run submission through Agent Runtime Adapter
The system SHALL provide a local Workbench UI that submits natural language Agent queries through an Agent Runtime Adapter and MUST NOT call SAP, Java Gateway, or arbitrary RFC execution directly from UI components.

#### Scenario: Submit Chinese inventory query
- **WHEN** a user submits `DEMOA1 在 1000 还有多少可用库存？` from the Workbench page
- **THEN** the UI creates an Agent run through the Agent Runtime Adapter
- **AND** the UI does not submit or expose a raw `rfcName`

#### Scenario: Reject direct RFC override
- **WHEN** a Workbench request includes an attempted `rfcName` override
- **THEN** the Agent Runtime Adapter rejects or removes the override before execution
- **AND** no frontend route forwards that `rfcName` to the Java Gateway or SAP

### Requirement: SSE Agent run event stream
The system SHALL expose an SSE-first stream of ordered Agent run events for the local Workbench.

#### Scenario: Stream ordered run events
- **WHEN** a Workbench Agent run starts
- **THEN** the stream emits ordered events with stable run ID, sequence number, timestamp, event type, and run state
- **AND** the event sequence covers the major stages from run start through completion or failure

#### Scenario: Stream uses SSE rather than WebSocket
- **WHEN** the first Workbench implementation observes an Agent run
- **THEN** the browser consumes a server-sent event stream
- **AND** no WebSocket protocol is required for the read-only inventory flow

### Requirement: Agent run state machine and timeline visualization
The system SHALL model Agent run progress with a deterministic state machine and render it as a timeline.

#### Scenario: Successful read-only timeline
- **WHEN** the Agent run completes successfully for `MM.Inventory.GetAvailability`
- **THEN** the timeline shows intent parsing, capability selection, CallPlan creation, approval state, Gateway validation, Gateway execution, ReasoningFact creation, narrative creation, trace linkage, and completion

#### Scenario: Failed run timeline
- **WHEN** an Agent run fails during parsing, validation, Gateway execution, or narration
- **THEN** the timeline shows the failed stage, structured error type, safe message, and terminal failed state

### Requirement: Redacted artifact panels
The system SHALL display redacted Agent artifacts for CallPlan, ExecutionResult, ReasoningFact, Chinese narrative, and trace metadata.

#### Scenario: Display successful run artifacts
- **WHEN** a successful inventory availability run produces artifacts
- **THEN** the Workbench displays redacted panels for CallPlan, ExecutionResult, ReasoningFact, Chinese narrative, agent trace ID, and gateway trace ID

#### Scenario: Artifact panels preserve harness boundaries
- **WHEN** artifact panels render CallPlan or ExecutionResult data
- **THEN** they display the registered `capabilityId` and safe executor metadata from normalized artifacts
- **AND** they do not provide controls for arbitrary RFC execution

### Requirement: Secret and runtime redaction guard
The system SHALL redact secrets and sensitive runtime details before any Agent run artifact is displayed in the Workbench.

#### Scenario: Redact known sensitive keys
- **WHEN** an artifact contains keys or values resembling `.env`, SAP password, destination config, token, LLM API key, or raw live LLM response data
- **THEN** the Agent Runtime Adapter redacts those fields before the UI receives the artifact

#### Scenario: Runtime trace content is not committed or displayed raw
- **WHEN** the Workbench links trace metadata
- **THEN** it displays safe trace IDs and status fields only
- **AND** it does not require committing generated runtime trace files or displaying raw live trace contents

### Requirement: Human-in-the-loop state skeleton
The system SHALL include a human-in-the-loop state model without implementing SAP Write Action execution.

#### Scenario: Read-only query requires no approval
- **WHEN** the Workbench runs `MM.Inventory.GetAvailability`
- **THEN** the human-in-the-loop panel displays `approval_not_required`
- **AND** no approval record or SAP write action is created

#### Scenario: Future approval states are representable
- **WHEN** the state machine receives a future approval state such as `approval_required`, `awaiting_human_approval`, `approved`, `rejected`, or `expired`
- **THEN** the Workbench can represent that state without executing a SAP write action

### Requirement: Local verification and regression safety
The system SHALL add repeatable verification for Workbench contracts and preserve existing Agent and OpenSpec regression checks.

#### Scenario: Frontend verification does not require live credentials
- **WHEN** frontend tests or build checks run
- **THEN** they do not require SAP credentials, LLM credentials, live SAP access, raw live LLM responses, or generated runtime traces

#### Scenario: Existing Agent verification remains valid
- **WHEN** the change is verified
- **THEN** `scripts/verify-agent-callplan-evidence.sh` and `openspec validate --all --strict` still pass

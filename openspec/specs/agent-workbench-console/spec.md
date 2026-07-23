# agent-workbench-console Specification

## Purpose
Define the internal SAP Nexus Agent Workbench Console behavior for local-first Agent run submission, SSE timeline observation, redacted evidence panels, trace/audit viewing, and human-in-the-loop state representation.
## Requirements
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

The system SHALL model Agent run progress with a deterministic state machine and render it as a timeline. The timeline SHALL be rendered inside the collapsible process-evidence region beneath the AI reply bubble for the corresponding turn (rather than as a permanent center panel).

#### Scenario: Successful read-only timeline

- **WHEN** the Agent run completes successfully for `MM.Inventory.GetAvailability`
- **THEN** expanding the turn's process evidence shows a timeline with intent parsing, capability selection, CallPlan creation, approval state, Gateway validation, Gateway execution, ReasoningFact creation, narrative creation, trace linkage, and completion

#### Scenario: Failed run timeline

- **WHEN** an Agent run fails during parsing, validation, Gateway execution, or narration
- **THEN** expanding the turn's process evidence shows the failed stage, structured error type, safe message, and terminal failed state

### Requirement: Redacted artifact panels

The system SHALL display redacted Agent artifacts for CallPlan, Gateway validation, ExecutionResult, ReasoningFact, Chinese narrative, and trace metadata. These panels SHALL be rendered inside the collapsible process-evidence region beneath the AI reply bubble for the corresponding turn. The Chinese narrative SHALL additionally surface as the AI reply bubble text.

#### Scenario: Display successful live run artifacts

- **WHEN** a successful inventory availability run produces artifacts from the Python Agent and Gateway
- **THEN** expanding the turn's process evidence displays redacted panels for CallPlan, Gateway validation, ExecutionResult, ReasoningFact, Chinese narrative, agent trace ID, and gateway trace ID
- **AND** the AI reply bubble shows the Chinese narrative as its text
- **AND** `ExecutionResult.data.availableQuantity` reflects the normalized Gateway/SAP result

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

The system SHALL include a human-in-the-loop state model without implementing SAP Write Action execution. The human-approval state SHALL be rendered inside the collapsible process-evidence region beneath the AI reply bubble for the corresponding turn.

#### Scenario: Read-only query requires no approval

- **WHEN** the Workbench runs `MM.Inventory.GetAvailability`
- **THEN** expanding the turn's process evidence displays the human-in-the-loop state as `approval_not_required`
- **AND** no approval record or SAP write action is created

#### Scenario: Future approval states are representable

- **WHEN** the state machine receives a future approval state such as `approval_required`, `awaiting_human_approval`, `approved`, `rejected`, or `expired`
- **THEN** the turn's process evidence can represent that state without executing a SAP write action

### Requirement: Local verification and regression safety
The system SHALL add repeatable verification for Workbench contracts and preserve existing Agent and OpenSpec regression checks.

#### Scenario: Frontend verification does not require live credentials
- **WHEN** frontend tests or build checks run
- **THEN** they do not require SAP credentials, LLM credentials, live SAP access, raw live LLM responses, or generated runtime traces

#### Scenario: Existing Agent verification remains valid
- **WHEN** the change is verified
- **THEN** `scripts/verify-agent-callplan-evidence.sh` and `openspec validate --all --strict` still pass

### Requirement: Notion-style two-column chat layout

The Workbench console SHALL render a two-column layout: a left navigation menu (`side-nav`) and a center chat area (`stage`). The right `copilot` sidebar SHALL be removed. The center area SHALL switch between an empty state and a conversation state.

#### Scenario: Empty state centers the single input

- **WHEN** the Workbench loads with no Agent run history
- **THEN** the center area renders a centered welcome heading, a single query input, and quick-prompt buttons
- **AND** there is exactly one query input visible (no secondary copilot input)

#### Scenario: Conversation state moves input to a fixed bottom composer

- **WHEN** a user submits a query
- **THEN** the center area switches to a conversation state
- **AND** the query input becomes a fixed composer at the bottom of the center area
- **AND** the message stream occupies the area above the composer

### Requirement: Streaming chat message stream

The Workbench SHALL render a streaming chat message stream in the center area during the conversation state. Each conversation turn SHALL render a user message bubble (right-aligned) and an AI reply bubble (left-aligned). The AI reply SHALL update incrementally as SSE run events arrive, without requiring a WebSocket.

#### Scenario: User and AI bubbles render per turn

- **WHEN** a user submits a query in the conversation state
- **THEN** a user bubble showing the submitted query renders right-aligned
- **AND** an AI bubble renders left-aligned and updates incrementally as the run progresses

#### Scenario: AI reply streams reasoning steps then narrative

- **WHEN** SSE run events arrive for the current turn
- **THEN** reasoning steps appear incrementally in the AI bubble as their corresponding events arrive
- **AND** a streaming placeholder with a blinking cursor is shown while the narrative is pending
- **AND** the Chinese narrative conclusion replaces the placeholder once the narrative event arrives

### Requirement: Collapsible process evidence under AI reply

The Workbench SHALL display the structured process evidence (runtime timeline, human-approval state, trace audit, and detailed artifact groups) as a collapsible region beneath the AI reply bubble, collapsed by default. Expanding it SHALL reuse the existing timeline, human-approval, trace-audit, and artifact components driven by the run snapshot.

#### Scenario: Evidence collapsed by default

- **WHEN** an AI reply renders for a turn
- **THEN** a collapsed "view process evidence" control is shown beneath the AI bubble
- **AND** the structured evidence is hidden until the user expands it

#### Scenario: Expanding evidence shows timeline and artifacts

- **WHEN** the user expands the process evidence control for a turn
- **THEN** the runtime timeline, human-approval state, trace audit, and detailed artifact groups render for that turn
- **AND** the displayed artifacts remain redacted per the redaction guard

### Requirement: Multi-turn message accumulation and run history switching

The Workbench SHALL accumulate multiple conversation turns in the message stream on the client side. Each turn corresponds to one independent Agent run. The left Run History SHALL list past turns and allow switching the viewed turn. Submitting a new query SHALL append a new turn rather than continue a prior turn's context.

#### Scenario: Multiple turns accumulate

- **WHEN** a user submits a second query after a completed first turn
- **THEN** the first turn's messages remain in the stream
- **AND** a new turn with its own user bubble and AI reply is appended below

#### Scenario: Run history switches the viewed turn

- **WHEN** the user clicks a past turn in the Run History
- **THEN** the message stream scrolls to and highlights that turn's messages and evidence
- **AND** all accumulated turns remain visible in the stream
- **AND** the bottom composer remains available to append a new independent turn

#### Scenario: Each turn is an independent run without carried context

- **WHEN** a new query is submitted
- **THEN** it creates a new Agent run via the Agent Runtime Adapter without forwarding prior turn history to the backend
- **AND** the prior turn's snapshot is preserved for viewing but does not influence the new run


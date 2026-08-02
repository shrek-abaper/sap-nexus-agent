## MODIFIED Requirements

### Requirement: Durable agent run state
The system SHALL persist agent run state (events, `pendingOutcome`, approval decision) in a durable store keyed by `runId`, replacing the process-local `runs` Map (`globalThis.__SAP_NEXUS_AGENT_RUNS__`). The system SHALL recover run state across process restarts and share it across workers. Each durable Run record SHALL bind to a `principalId` at creation time; the `principalId` SHALL NOT be mutable after creation. Records created without a `principalId` (legacy data) SHALL be backfilled with the local placeholder principal (`local-user-0001`) on load.

#### Scenario: Run recovers across process restart
- **WHEN** a run is in `awaiting_approval` or `awaiting_batch_confirm` state and the backend process restarts
- **THEN** the run is recovered from the durable store with its full event stream and `pendingOutcome`
- **AND** the user can continue the run (approve / reject / confirm) after restart

#### Scenario: Multi-worker shares run state
- **WHEN** worker A creates a run and worker B receives a continuation request for the same `runId`
- **THEN** worker B reads the run state from the durable store
- **AND** both workers observe the same run events and `pendingOutcome`

#### Scenario: Run binds principal at creation
- **WHEN** a new agent run is created by a server-injected principal
- **THEN** the durable Run record stores the principal's `principalId`
- **AND** the `principalId` is immutable for the lifetime of the run

#### Scenario: Legacy run backfilled with placeholder principal
- **WHEN** a durable Run record without a `principalId` is loaded from legacy data
- **THEN** the system backfills the `principalId` with `local-user-0001`
- **AND** the backfilled record behaves identically to a new record

### Requirement: Store-agnostic durable interface
The system SHALL define a store-agnostic interface (`DurableRunStore`, `DurableConversationStore`) for durable persistence. The interface SHALL support save / load / list / lease / claim operations. The `list` method SHALL accept an optional `principalId` filter that returns only runs belonging to that principal. The `DurableConversationStore.load` method SHALL accept an optional `principalId` filter that returns `null` (fail-closed) when the session belongs to a different principal. The implementation SHALL be pluggable; store selection (SQLite / PostgreSQL / Redis) is decided in the design phase, not in this change's open phase.

#### Scenario: Local reference implementation is pluggable
- **WHEN** the system is configured with the local reference implementation (zero-dependency)
- **THEN** durable state persists locally (e.g., SQLite / file)
- **AND** the implementation can be swapped to a production store without changing the interface contract

#### Scenario: Three-layer state stratification
- **WHEN** the system persists run state
- **THEN** `ConversationState` (advisory, compressible), `PlanExecutionState` (authority, incompressible), and `EvidenceState` (authority, incompressible) are persisted per §4.2.1 three-layer stratification
- **AND** only `ConversationState` may be compacted

#### Scenario: List filters by principal
- **WHEN** `list` is called with a `principalId` filter
- **THEN** only runs belonging to that principal are returned
- **AND** runs without a `principalId` (legacy) are backfilled and match the placeholder principal

#### Scenario: Conversation load fails closed on principal mismatch
- **WHEN** `load` is called with a `principalId` and the session belongs to a different principal
- **THEN** the system returns `null` (fail-closed)
- **AND** no session data is leaked to the caller

## ADDED Requirements

### Requirement: Durable agent run state
The system SHALL persist agent run state (events, `pendingOutcome`, approval decision) in a durable store keyed by `runId`, replacing the process-local `runs` Map (`globalThis.__SAP_NEXUS_AGENT_RUNS__`). The system SHALL recover run state across process restarts and share it across workers.

#### Scenario: Run recovers across process restart
- **WHEN** a run is in `awaiting_approval` or `awaiting_batch_confirm` state and the backend process restarts
- **THEN** the run is recovered from the durable store with its full event stream and `pendingOutcome`
- **AND** the user can continue the run (approve / reject / confirm) after restart

#### Scenario: Multi-worker shares run state
- **WHEN** worker A creates a run and worker B receives a continuation request for the same `runId`
- **THEN** worker B reads the run state from the durable store
- **AND** both workers observe the same run events and `pendingOutcome`

### Requirement: Run ownership and lease
The system SHALL bind each active run to a worker via an ownership lease. A run's lease SHALL prevent other workers from taking over while active. The system SHALL fail-closed when a second worker attempts to operate on a run whose lease is held by another worker.

#### Scenario: Lease prevents concurrent takeover
- **WHEN** worker A holds the lease for run R and worker B attempts to continue run R
- **THEN** the system rejects worker B's operation (fail-closed)
- **AND** records the rejected takeover attempt

#### Scenario: Expired lease allows audited takeover
- **WHEN** worker A's lease for run R has expired (worker A crashed or stopped renewing)
- **AND** worker B attempts to continue run R
- **THEN** worker B may claim the run with an audit record of the forced takeover
- **AND** the lease is rebound to worker B

### Requirement: Structured checkpoint reference
The system SHALL persist a structured checkpoint reference for each run's `PlanExecutionState` and `EvidenceState`, binding to the original `RegistrySnapshot` and structured node state. The system SHALL NOT reconstruct run state from summary or Memory. On recovery, the system SHALL load the original `RegistrySnapshot` and structured node state.

#### Scenario: Recovery loads original snapshot
- **WHEN** a run is recovered after restart
- **THEN** the system loads the original `RegistrySnapshot` referenced by the checkpoint
- **AND** loads the structured node state (not a summary)
- **AND** snapshot drift fails closed (reuses the S1 validator)

#### Scenario: Compaction failure preserves checkpoint
- **WHEN** `ConversationState` compaction fails
- **THEN** the system retains the original checkpoint or disables compaction
- **AND** the run is not corrupted

### Requirement: Idempotent continuation
The system SHALL accept an idempotency key for continuation requests (approval approve / reject, batch confirm). The key SHALL be derived from `runId` + continuation type + parameter hash. A duplicate key SHALL return the already-recorded result without re-executing.

#### Scenario: Duplicate approval continuation is idempotent
- **WHEN** an approve continuation for run R is submitted twice with the same idempotency key
- **THEN** the system executes the approval continuation once
- **AND** the second request returns the already-recorded result without re-executing

#### Scenario: Different continuation types are not idempotent to each other
- **WHEN** run R has both an approval continuation and a batch confirm continuation pending
- **THEN** the two continuations have distinct idempotency keys (different continuation type)
- **AND** both can be executed independently

### Requirement: Store-agnostic durable interface
The system SHALL define a store-agnostic interface (`DurableRunStore`, `DurableConversationStore`) for durable persistence. The interface SHALL support save / load / list / lease / claim operations. The implementation SHALL be pluggable; store selection (SQLite / PostgreSQL / Redis) is decided in the design phase, not in this change's open phase.

#### Scenario: Local reference implementation is pluggable
- **WHEN** the system is configured with the local reference implementation (zero-dependency)
- **THEN** durable state persists locally (e.g., SQLite / file)
- **AND** the implementation can be swapped to a production store without changing the interface contract

#### Scenario: Three-layer state stratification
- **WHEN** the system persists run state
- **THEN** `ConversationState` (advisory, compressible), `PlanExecutionState` (authority, incompressible), and `EvidenceState` (authority, incompressible) are persisted per §4.2.1 three-layer stratification
- **AND** only `ConversationState` may be compacted

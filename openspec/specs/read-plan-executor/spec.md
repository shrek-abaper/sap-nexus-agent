# read-plan-executor Specification

## Purpose
TBD - created by archiving change sap-nexus-read-plan-executor. Update Purpose after archive.
## Requirements
### Requirement: PlanExecutor consumes validated PlanGraph v2 readPartition

The system SHALL provide a READ PlanExecutor that consumes a validated PlanGraph v2 `readPartition` and executes only READ nodes. The executor SHALL reject any PlanGraph that is not validator-valid or whose `snapshotId` has drifted from the bound RegistrySnapshot. The executor MUST NOT call the LLM, replan, or bypass the Gateway.

#### Scenario: Valid PlanGraph readPartition consumed

- **WHEN** the executor receives a validator-valid PlanGraph v2 with a readPartition of READ nodes
- **THEN** the executor schedules the readPartition nodes for execution
- **AND** binds the same `snapshotId` as the PlanGraph

#### Scenario: Invalid or drifted PlanGraph rejected

- **WHEN** the executor receives a PlanGraph that fails validation or whose `snapshotId` drifts
- **THEN** the executor rejects the plan fail-closed before any Gateway call
- **AND** records a structured failure

### Requirement: Ready-node scheduling bounded by DAG independence

The system SHALL select dependency-free READY nodes from the readPartition and execute them with bounded concurrency determined solely by DAG independence (edges). A configurable safety cap (default 4, overridable via the `READ_PLAN_EXECUTOR_MAX_CONCURRENCY` environment variable) SHALL bound the maximum number of in-flight nodes as backpressure protection. A node whose dependencies are not all SUCCEEDED SHALL remain `BLOCKED_DEPENDENCY`.

#### Scenario: Two independent READ nodes execute concurrently

- **WHEN** the readPartition contains two READ nodes with no dependency edge between them
- **THEN** both nodes are scheduled as READY and execute concurrently
- **AND** each independently passes through Gateway validate/execute

#### Scenario: Dependent node blocks until prerequisite succeeds

- **WHEN** a node has an unsatisfied dependency (prerequisite not `SUCCEEDED`)
- **THEN** the node stays `BLOCKED_DEPENDENCY`
- **AND** becomes `READY` only after the prerequisite node is `SUCCEEDED`

#### Scenario: Configurable safety cap bounds in-flight nodes

- **WHEN** the readPartition contains more READY nodes than the configured `READ_PLAN_EXECUTOR_MAX_CONCURRENCY` cap (default 4)
- **THEN** the executor schedules at most the cap number of nodes concurrently
- **AND** remaining READY nodes are scheduled as in-flight nodes complete

### Requirement: Per-node Gateway validate and execute without bypass

The system SHALL execute each READ node by calling the existing Gateway `validate` then `execute` per capability. The executor MUST NOT bypass the Gateway, call SAP directly, or use a batch endpoint.

#### Scenario: Node passes validate then execute

- **WHEN** a READY node is executed
- **THEN** the executor calls Gateway validate with the node's `capabilityId` and parameters
- **AND** only on validation success calls Gateway execute

#### Scenario: Validation failure fails the node

- **WHEN** Gateway validate fails for a node
- **THEN** the node transitions to `FAILED` without calling execute
- **AND** independent nodes continue execution

### Requirement: Durable node ledger reuses DurableRunStore

The system SHALL persist a durable node ledger by reusing the P0B `DurableRunStore` (extending `CheckpointRef.nodeState` and the event stream). The system MUST NOT create a second process-local PlanExecution store. Each node state transition SHALL record sequence, attempt, input hash, result ref, and trace span.

#### Scenario: Node state transitions persisted to durable ledger

- **WHEN** a node transitions through `READY` -> `VALIDATING` -> `EXECUTING` -> `SUCCEEDED`
- **THEN** each transition is persisted to the durable ledger with sequence, attempt, input hash, result ref, and trace span
- **AND** the ledger is recoverable across process restarts

#### Scenario: Illegal state transition fail-closed

- **WHEN** a node attempts an illegal state transition (e.g., `SUCCEEDED` -> `EXECUTING`)
- **THEN** the executor rejects the transition fail-closed
- **AND** records the illegal attempt

### Requirement: Action nodes blocked

The system SHALL NOT execute Action nodes or any node whose governance is not read-only. Such nodes SHALL remain `BLOCKED_APPROVAL` and MUST NOT be executed.

#### Scenario: Action node stays BLOCKED_APPROVAL

- **WHEN** a plan includes an Action or non-read-only node
- **THEN** the node stays `BLOCKED_APPROVAL` and is not executed
- **AND** no Gateway execute is called for it

### Requirement: Node timeout and cancellation

The system SHALL support node-level timeout and cancellation. A timed-out node SHALL transition to `TIMED_OUT` without blocking independent nodes. On cancellation, uncompleted nodes SHALL transition to `CANCELLED` while `SUCCEEDED` nodes are preserved.

#### Scenario: Node timeout does not block independent nodes

- **WHEN** a node exceeds its timeout
- **THEN** the node transitions to `TIMED_OUT`
- **AND** independent nodes continue execution

#### Scenario: Cancellation preserves succeeded nodes

- **WHEN** the user cancels an in-progress plan
- **THEN** uncompleted nodes transition to `CANCELLED`
- **AND** already `SUCCEEDED` nodes remain `SUCCEEDED`

### Requirement: Restart recovery and idempotent replay

The system SHALL recover node execution state across process restarts from the durable ledger. On recovery, `SUCCEEDED` nodes SHALL NOT be re-executed; `READY` and uncompleted nodes SHALL resume. `FAILED` nodes SHALL NOT be auto-retried on restart and SHALL remain `FAILED` until an explicit retry is requested with a new attempt. The system SHALL accept an idempotency key for continuation; a duplicate key SHALL return the already-recorded result without re-executing nodes.

#### Scenario: Recovery skips succeeded nodes

- **WHEN** the process restarts mid-plan
- **THEN** the executor loads the durable ledger
- **AND** `SUCCEEDED` nodes are not re-executed
- **AND** `READY` and uncompleted nodes resume

#### Scenario: Failed node not auto-retried on restart

- **WHEN** the process restarts and the durable ledger contains a `FAILED` node
- **THEN** the executor leaves the node `FAILED` without re-executing it
- **AND** an explicit retry is required to re-attempt the node with a new attempt

#### Scenario: Idempotent replay does not re-execute

- **WHEN** the same continuation is submitted twice with the same idempotency key
- **THEN** nodes are executed once
- **AND** the second submission returns the already-recorded result

### Requirement: Lease conflict fail-closed

The system SHALL bind plan execution to the run-level lease. When another worker holds the lease, the executor SHALL fail-closed and not operate on the plan.

#### Scenario: Lease held by another worker

- **WHEN** worker B attempts to operate on a plan whose lease is held by worker A
- **THEN** the executor rejects the operation fail-closed
- **AND** records the rejected takeover attempt

### Requirement: Per-node SSE events

The system SHALL emit per-node SSE events for node state transitions via a single `node_state_changed` event type carrying `nodeId`, `fromState`, `toState`, and `attempt`. The system SHALL reuse the existing SSE framework. Per-node events SHALL NOT break existing single-capability event emission.

#### Scenario: Per-node events emitted on transitions

- **WHEN** a node transitions through its state machine
- **THEN** the executor emits a `node_state_changed` event for each transition with `nodeId`, `fromState`, `toState`, and `attempt`
- **AND** existing single-capability events remain unchanged

### Requirement: Executor exposes projection input facts for succeeded nodes

The system SHALL extend the READ PlanExecutor output so that, alongside `PlanExecutorResult`, the executor exposes the per-node data required to build projection input for `SUCCEEDED` nodes. The exposed data SHALL include an agent-level correlation identifier derived from the current executor `runId` and SHALL be sufficient for a `ProjectionInputAssembler` to construct `ReasoningFact[]` and a `PlanExecutionRecord` without re-calling the Gateway. Every `SUCCEEDED` node with complete fact-building data SHALL retain a `NodeFactRecord`, even when its Gateway trace is missing; in that case `gatewayTraceId` SHALL be `null`, not an empty string, and the record SHALL remain observable to the assembler. The agent-level correlation identifier MUST NOT be derived from or replaced by the Gateway trace identifier. The extension SHALL be backward-compatible: existing `PlanExecutorResult` fields and their semantics, and the node state machine, SHALL remain unchanged. The executor MUST NOT call the LLM, replan, or bypass the Gateway.

#### Scenario: Succeeded node exposes fact-building data

- **WHEN** a READ node reaches `SUCCEEDED` after Gateway execute
- **THEN** the executor output exposes the per-node data needed to build that node's `ReasoningFact`
- **AND** the data is available without re-calling the Gateway

#### Scenario: Existing PlanExecutorResult semantics preserved

- **WHEN** the executor runs against an existing dual-READ `PlanExecutorResult` fixture
- **THEN** the existing `nodeLedger`, `succeeded`, `failed`, `timedOut`, `cancelled`, and `blocked` fields retain their prior semantics
- **AND** existing Runbook 16 executor tests pass without modification

#### Scenario: Agent correlation survives fresh execution and replay

- **WHEN** a node succeeds during fresh execution or its result is rebuilt from an idempotency cache within the same `runId`
- **THEN** its projection input record carries `agentTraceId` equal to that `runId`
- **AND** the agent trace remains distinct in meaning from `gatewayTraceId`
- **AND** replay does not require another Gateway call

#### Scenario: Missing Gateway correlation preserves succeeded projection metadata

- **WHEN** a fresh, cached, or existing-`SUCCEEDED` node has complete fact-building data but its Gateway trace is missing or blank
- **THEN** the executor still exposes that node's `NodeFactRecord` with `gatewayTraceId` = `null`
- **AND** the existing `SUCCEEDED` ledger and result-list semantics remain unchanged
- **AND** cache replay and existing-success hydration do not call the Gateway again


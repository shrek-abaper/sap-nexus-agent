## ADDED Requirements

### Requirement: Executor exposes projection input facts for succeeded nodes

The system SHALL extend the READ PlanExecutor output so that, alongside `PlanExecutorResult`, the executor exposes the per-node data required to build projection input for `SUCCEEDED` nodes. The exposed data SHALL include an agent-level correlation identifier derived from the current executor `runId` and SHALL be sufficient for a `ProjectionInputAssembler` to construct `ReasoningFact[]` and a `PlanExecutionRecord` without re-calling the Gateway. The agent-level correlation identifier MUST NOT be derived from or replaced by the Gateway trace identifier. The extension SHALL be backward-compatible: existing `PlanExecutorResult` fields and their semantics, and the node state machine, SHALL remain unchanged. The executor MUST NOT call the LLM, replan, or bypass the Gateway.

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

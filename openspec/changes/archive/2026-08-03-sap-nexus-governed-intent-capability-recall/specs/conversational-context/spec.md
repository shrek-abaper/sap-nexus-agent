## MODIFIED Requirements

### Requirement: Conversation session state
The system SHALL maintain a per-conversation `ConversationState` in a durable store, keyed by `conversationId`, holding an optional `PendingClarification`, `PendingShowOptions`, or `PendingEscalate` (at most one pending state at any time, mutual exclusivity enforced). The state SHALL be advisory context only and MUST NOT influence `PlanExecutionState` or `EvidenceState`, and MUST NOT influence `CallPlan` / `ApprovalRecord` lifecycle. The system SHALL persist `PendingShowOptions` and `PendingEscalate` via the same durable path as `PendingClarification` (P0B `ConversationState` durable store), ensuring cross-restart recovery and multi-worker shared view. The `ConversationContext` dataclass SHALL expose `pending_show_options` and `pending_escalate` fields alongside `last_context` and `history`. The `IntentAdapter` callable SHALL return `IntentEnvelope` (not `IntentParseResult`), preserving the `ConversationContext` parameter for cross-turn continuation.

#### Scenario: New conversation starts with no pending state
- **WHEN** the frontend generates a new `conversationId` via the "new conversation" button
- **THEN** the backend creates an empty `ConversationState` with `pending_clarification=null`, `pending_show_options=null`, `pending_escalate=null`
- **AND** subsequent queries within that conversation are grouped under the same `conversationId`

#### Scenario: Process restart preserves sessions
- **WHEN** the Workbench backend process restarts
- **THEN** all `ConversationState` is recovered from the durable store
- **AND** a follow-up query with an existing `conversationId` resumes with its prior `PendingClarification` / `PendingShowOptions` / `PendingEscalate` / `LastContext` intact
- **AND** multi-worker deployments share the same `ConversationState` view

#### Scenario: PendingShowOptions durable persistence
- **WHEN** turn N produces `SHOW_OPTIONS` and `PendingShowOptions` is written to `ConversationContext`
- **AND** the backend process restarts before turn N+1
- **THEN** `PendingShowOptions` is recovered from the durable store on restart
- **AND** turn N+1 can still select a candidate from the preserved options

#### Scenario: PendingEscalate durable persistence
- **WHEN** turn N produces `ESCALATE_TO_PLANNER` and `PendingEscalate` is written to `ConversationContext`
- **AND** the backend process restarts before turn N+1
- **THEN** `PendingEscalate` is recovered from the durable store on restart
- **AND** turn N+1 can still confirm continuation to the planner

#### Scenario: IntentAdapter returns IntentEnvelope
- **WHEN** the `IntentAdapter` is invoked with an utterance and a `ConversationContext`
- **THEN** the return type is `IntentEnvelope` (not `IntentParseResult`)
- **AND** the `ConversationContext` is consumed for cross-turn continuation (sticky-CLARIFY / SHOW_OPTIONS / ESCALATE)

## ADDED Requirements

### Requirement: Cross-turn pending state mutual exclusivity
The system SHALL enforce at most one of `PendingClarification`, `PendingShowOptions`, `PendingEscalate` is set in `ConversationContext` at any time. Writing a new pending state SHALL clear any existing pending state. All pending states are advisory only and MUST NOT carry execution authority.

#### Scenario: SHOW_OPTIONS clears pending CLARIFY
- **WHEN** `ConversationContext.pending_clarification` is set and a new turn produces `SHOW_OPTIONS`
- **THEN** `pending_clarification` is cleared before `pending_show_options` is set

#### Scenario: CLARIFY clears pending SHOW_OPTIONS
- **WHEN** `ConversationContext.pending_show_options` is set and a new turn produces `CLARIFY`
- **THEN** `pending_show_options` is cleared before `pending_clarification` is set

#### Scenario: New intent clears all pending states
- **WHEN** a new turn contains a primary keyword for any registered capability
- **THEN** all pending states (`pending_clarification`, `pending_show_options`, `pending_escalate`) are cleared
- **AND** the new turn is processed as a fresh intent

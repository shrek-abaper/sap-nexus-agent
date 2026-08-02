## MODIFIED Requirements

### Requirement: Conversation session state
The system SHALL maintain a per-conversation `ConversationState` in a durable store, keyed by `conversationId`, holding an optional `PendingClarification`. The state SHALL be advisory context only and MUST NOT influence `PlanExecutionState` or `EvidenceState`. The system SHALL persist this state across process restarts (durable persistence; replaces the v1 process-local `sessions` Map). The underlying storage implementation SHALL be pluggable via the store-agnostic interface defined in `durable-run-state`.

#### Scenario: New conversation starts with no pending clarification
- **WHEN** the frontend generates a new `conversationId` via the "new conversation" button
- **THEN** the backend creates an empty `ConversationState` with `pending_clarification=null`
- **AND** subsequent queries within that conversation are grouped under the same `conversationId`

#### Scenario: Process restart preserves sessions
- **WHEN** the Workbench backend process restarts
- **THEN** all `ConversationState` is recovered from the durable store
- **AND** a follow-up query with an existing `conversationId` resumes with its prior `PendingClarification` / `LastContext` intact
- **AND** multi-worker deployments share the same `ConversationState` view

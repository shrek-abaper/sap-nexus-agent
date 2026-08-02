## ADDED Requirements

### Requirement: Trusted principal model
The system SHALL model trusted principal/tenant/role/data scope as server-owned context. The principal SHALL be injected by the backend at the request entry point and SHALL NOT be supplied by request body, prompt, summary, or Memory. Any principal field carried in a request body or LLM output SHALL be ignored or rejected.

#### Scenario: Principal injected server-side
- **WHEN** a request body carries a `principal` field and the backend has a server-injected principal for the session
- **THEN** the system ignores the request-supplied principal field
- **AND** uses the server-injected principal for all durable state binding and authorization context

#### Scenario: Prompt injection cannot supply principal
- **WHEN** an LLM output or prompt summary contains a principal identifier
- **THEN** the system rejects the LLM-supplied principal identifier
- **AND** the server-injected principal remains authoritative

### Requirement: Durable state binds principal
Each durable Run, Approval, and ConversationState SHALL bind to a `principalId`. The `principalId` SHALL be recorded at durable state creation time and SHALL NOT be mutable after creation.

#### Scenario: Run created with principal
- **WHEN** a new agent run is created
- **THEN** the durable Run record stores the `principalId` of the server-injected principal
- **AND** the `principalId` is immutable for the lifetime of the run

#### Scenario: Approval binds principal
- **WHEN** an approval record is created for a run
- **THEN** the durable Approval record stores the `principalId` bound to the run
- **AND** the approval is scoped to that principal

### Requirement: Cross-principal isolation
The system SHALL isolate durable state by principal. Principal A SHALL NOT read, continue, or approve principal B's runs, approvals, or sessions. Cross-principal access SHALL fail-closed.

#### Scenario: Cross-principal access denied
- **WHEN** principal A attempts to read or continue a run owned by principal B
- **THEN** the system denies the access (fail-closed)
- **AND** no principal B durable state is returned to principal A

### Requirement: Local placeholder principal
The system SHALL provide a local single-user placeholder principal for v1 local-first operation. The placeholder principal SHALL be the default server-injected principal when no remote authentication is configured. Authentication runtime (remote authn, token validation) is a non-goal for this change.

#### Scenario: Local dev uses placeholder principal
- **WHEN** the backend runs in local-first mode without remote authentication configured
- **THEN** the system injects the local placeholder principal (fixed `principalId`)
- **AND** all durable state binds to the placeholder principal
- **AND** the principal injection interface remains extensible for future remote authentication

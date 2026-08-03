# trusted-principal-scope Specification

## Purpose
TBD - created by archiving change sap-nexus-trusted-principal-model. Update Purpose after archive.
## Requirements
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

### Requirement: Principal propagated to agent decision layer

The trusted principal SHALL be propagated from the backend durable-authorization layer into the Python agent decision layer (intent recognition, matcher, planner). The backend SHALL pass the server-injected principal to the Python agent CLI, and `run_query` SHALL receive the principal and use it for visibility pre-filter and `GovernedContext` construction. The principal SHALL remain server-owned: request body, prompt, history, or LLM output SHALL NOT supply or override it. When no principal is provided (local CLI default), the system SHALL use the local placeholder principal.

#### Scenario: Backend propagates principal to Python agent

- **WHEN** the backend spawns the Python agent for a run with a server-injected principal
- **THEN** the principal is passed to the Python CLI and into `run_query`
- **AND** `run_query` constructs a `GovernedContext` with that principal for visibility pre-filter

#### Scenario: Local CLI defaults to placeholder principal

- **WHEN** the Python CLI runs without a provided principal (local-first mode)
- **THEN** `run_query` uses the local placeholder principal
- **AND** visibility pre-filter and `GovernedContext` still bind a non-empty principal

#### Scenario: Decision-layer principal cannot be overridden

- **WHEN** a request body or LLM output carries a principal field reaching the Python agent
- **THEN** the system ignores the request/LLM-supplied principal
- **AND** uses the backend-injected (or placeholder) principal for the `GovernedContext`


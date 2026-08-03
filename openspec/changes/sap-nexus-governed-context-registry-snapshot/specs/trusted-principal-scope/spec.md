## ADDED Requirements

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

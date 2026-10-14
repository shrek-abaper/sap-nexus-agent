# Ontology Analysis Chat Tool — model interpreter delta

## ADDED Requirements

### Requirement: Flag-gated model interpreter selection

The DSH ontology tool SHALL send the user's free-form `question` to the paid model interpreter only when `SAP_NEXUS_LLM_LIVE=1`; otherwise it SHALL use the offline fake interpreter keyed by `questionType`. The Python runtime SHALL independently reject `interpreter: "model"` unless the same flag is set, regardless of TS behavior.

#### Scenario: Live flag off stays offline

- **WHEN** a request carries `interpreter: "model"` without `SAP_NEXUS_LLM_LIVE=1`
- **THEN** the response is `rejected` with `MODEL_INTERPRETER_NOT_AUTHORIZED` and no model API call is made

#### Scenario: Live flag on routes free text to the model

- **WHEN** `SAP_NEXUS_LLM_LIVE=1` and the tool receives a `question` utterance
- **THEN** the model is invoked exactly once with a system prompt containing only allowlisted fact fields and the four operator ids, and its output is parsed as SemanticGoalDraft v1

### Requirement: Bounded single repair turn

On an invalid first draft the system SHALL feed the structured validation issues to the model exactly once and retry. It SHALL never make more than two model calls per analysis, and SHALL classify the final outcome using the existing terminal rules: unreleasable fields → semantic_gap; technical keys/bounds/schema violations → rejected.

#### Scenario: Repaired draft succeeds

- **WHEN** the first model draft references a non-allowlisted field and the second draft uses only allowlisted fields
- **THEN** exactly two model calls occur and the analysis completes

#### Scenario: Persistent bad draft terminates

- **WHEN** both drafts fail validation with DRAFT_TECHNICAL_KEY
- **THEN** the response is `rejected`, no execution occurs, and exactly two calls were made

### Requirement: Model prompt confinement

The model SHALL receive no credentials, gateway URLs, capability RFC names, or SAP technical bindings, and its prompt SHALL state the read-only/caliber rules (order quantity is not arrival/ATP; no arrival/demand facts exist in this release).

#### Scenario: Prompt contains only semantic vocabulary

- **THEN** the rendered system prompt lists the allowlisted fact fields and the four operator ids, and contains no `BAPI_` strings or URLs

### Requirement: Offline default regression

With the flag unset, the six `questionType` cases, 24-case matrix, and all existing DSH semantic-tool behavior SHALL remain green without any model call.

#### Scenario: Matrix stays offline

- **THEN** the default test suites pass with no network access required and the fake interpreter path is unchanged

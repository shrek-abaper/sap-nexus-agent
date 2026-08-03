## MODIFIED Requirements

### Requirement: Five-state MatchDecision object
The system SHALL produce a `MatchDecision` as the selector output with `decision_type` exactly one of `SELECT`, `CLARIFY`, `REJECT`, `SHOW_OPTIONS`, `ESCALATE_TO_PLANNER`, plus `candidates`, `rationale`, and `handoff` fields. `SELECT` SHALL carry exactly one `capabilityId` with complete parameters; `CLARIFY` SHALL carry missing parameters; `REJECT` SHALL carry an error type; `SHOW_OPTIONS` SHALL carry visible candidates; `ESCALATE_TO_PLANNER` SHALL carry a record and explanation. The `MatchDecision` SHALL additionally carry `envelope_id`, `recall_candidates`, `rerank_evidence`, and `discard_reasons` fields to support decision replay (tracing back to the `IntentEnvelope`, recall candidates, rerank evidence, filter reasons, and `snapshot_id`). The legacy `SelectionResult` compat wrapper and `to_selection_result()` bridge SHALL be removed (BREAKING).

#### Scenario: SELECT with complete parameters
- **WHEN** a single intent is detected with all required parameters
- **THEN** `MatchDecision.decision_type=SELECT` with the resolved `capabilityId` and parameters
- **AND** `MatchDecision.envelope_id` matches the `IntentEnvelope` that produced the decision
- **AND** `MatchDecision.recall_candidates` and `MatchDecision.rerank_evidence` are non-empty

#### Scenario: CLARIFY on missing parameter
- **WHEN** a single intent is detected but a required parameter is missing
- **THEN** `MatchDecision.decision_type=CLARIFY` with the missing parameter list and clarification text
- **AND** `MatchDecision.envelope_id` is set for replay

#### Scenario: REJECT on technical override
- **WHEN** the utterance contains `rfcName` or OData override
- **THEN** `MatchDecision.decision_type=REJECT` with `error_type=UNSUPPORTED_RFC_NAME`
- **AND** `MatchDecision.discard_reasons` contains the structured reason for the discarded technical field

#### Scenario: REJECT on visibility denial
- **WHEN** the LLM candidate contains a capability not in `VisibleCapabilitySet`
- **THEN** `MatchDecision.decision_type=REJECT` with `error_type=VISIBILITY_DENIED`
- **AND** `MatchDecision.discard_reasons` contains `"unknown_capability:<id>"`

#### Scenario: SelectionResult removed
- **WHEN** any caller previously used `SelectionResult` or `to_selection_result()`
- **THEN** the compat wrapper is no longer available and the caller MUST inspect `decision_type` directly

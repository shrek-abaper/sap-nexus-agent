## ADDED Requirements

### Requirement: Five-state MatchDecision object
The system SHALL produce a `MatchDecision` as the selector output with `decision_type` exactly one of `SELECT`, `CLARIFY`, `REJECT`, `SHOW_OPTIONS`, `ESCALATE_TO_PLANNER`, plus `candidates`, `rationale`, and `handoff` fields. `SELECT` SHALL carry exactly one `capabilityId` with complete parameters; `CLARIFY` SHALL carry missing parameters; `REJECT` SHALL carry an error type; `SHOW_OPTIONS` SHALL carry visible candidates; `ESCALATE_TO_PLANNER` SHALL carry a record and explanation.

#### Scenario: SELECT with complete parameters
- **WHEN** a single intent is detected with all required parameters
- **THEN** `MatchDecision.decision_type=SELECT` with the resolved `capabilityId` and parameters

#### Scenario: CLARIFY on missing parameter
- **WHEN** a single intent is detected but a required parameter is missing
- **THEN** `MatchDecision.decision_type=CLARIFY` with the missing parameter list and clarification text

#### Scenario: REJECT on technical override
- **WHEN** the utterance contains `rfcName` or OData override
- **THEN** `MatchDecision.decision_type=REJECT` with `error_type=UNSUPPORTED_RFC_NAME`

### Requirement: Multi-intent and ambiguity detection
The system SHALL scan all registered capability intent signals in an utterance, not first-match only. When more than one capability intent is detected, the system SHALL emit `ESCALATE_TO_PLANNER`. When multiple candidates are plausible for a single ambiguous goal, the system SHALL emit `SHOW_OPTIONS` with the visible candidate set.

#### Scenario: Multi-intent escalates
- **WHEN** the utterance matches two or more capability intent signals
- **THEN** `MatchDecision.decision_type=ESCALATE_TO_PLANNER` with record and explanation

#### Scenario: Keyword ambiguity shows options
- **WHEN** the utterance weakly matches multiple capability keyword sets without a clear primary intent (keyword ambiguity)
- **THEN** `MatchDecision.decision_type=SHOW_OPTIONS` with the visible candidate list
- **AND** the ambiguity threshold is anchored by matcher Eval cases

### Requirement: Visibility pre-filter
The system SHALL apply a visibility pre-filter to candidate `CapabilityCard`s before `SHOW_OPTIONS`. Candidates with `governance.sideEffect=none` and `dataClassification=internal` SHALL be visible by default; write-capability and restricted-data candidates SHALL be visible in dry-run but not executable until S3 gates are met.

#### Scenario: Read capability visible
- **WHEN** a candidate has `sideEffect=none` and `dataClassification=internal`
- **THEN** the candidate is included in the visible candidate set

#### Scenario: Write capability visible in dry-run only
- **WHEN** a candidate has `sideEffect=sap_write`
- **THEN** the candidate is visible in dry-run and SHOW_OPTIONS but not executable until S3 gates are met

### Requirement: Matcher Eval exit criteria
The system SHALL provide a matcher Eval covering five decision classes: `SELECT` (single intent, complete params), `CLARIFY` (missing params), `REJECT` (technical override), `SHOW_OPTIONS` (ambiguity), `ESCALATE_TO_PLANNER` (multi-goal). A `false SELECT` (multi-goal silently reduced to single `SELECT`) SHALL be a regression failure.

#### Scenario: All five decision classes covered
- **WHEN** the matcher Eval runs
- **THEN** cases cover SELECT, CLARIFY, REJECT, SHOW_OPTIONS, ESCALATE_TO_PLANNER
- **AND** a multi-goal-utterance-as-SELECT case fails the regression

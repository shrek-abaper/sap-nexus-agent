## MODIFIED Requirements

### Requirement: Chinese inventory intent parsing
The system SHALL parse Chinese inventory availability queries for `MM.Inventory.GetAvailability` into normalized intent parameters without using free-form RFC names. The parser MAY use a real LLM intent adapter before deterministic validation, but the LLM output is advisory and MUST be normalized into the same closed-set intent contract before capability selection.

#### Scenario: Parse complete inventory availability query with LLM adapter
- **WHEN** hybrid intent mode is enabled and the LLM returns trusted JSON for `DEMOA1 在 1000 还有多少可用库存？`
- **THEN** the Agent identifies inventory availability intent and extracts `material=DEMOA1` and `plant=1000`
- **AND** the Agent proceeds through deterministic closed-set capability selection before Gateway validation

#### Scenario: Fall back to rule parser when LLM is unavailable
- **WHEN** hybrid intent mode is enabled and the LLM client is missing configuration, times out, returns malformed JSON, or cannot be reached
- **THEN** the Agent falls back to the existing deterministic rule parser
- **AND** executable rule-parser results still follow the normal CallPlan and Gateway path

#### Scenario: Reject LLM-generated RFC name
- **WHEN** the LLM returns JSON containing `rfcName` or a raw SAP BAPI/RFC identifier
- **THEN** the Agent treats the output as untrusted and does not execute from that LLM output
- **AND** Gateway validate and execute are not called unless a safe fallback parser independently produces a valid closed-set capability request

### Requirement: Closed-set capability selection
The system SHALL select capabilities only from the Registry closed set and MUST reject unsupported intent before Gateway execution. LLM-assisted selection MUST be constrained to the same closed set and MUST NOT introduce new executable capability IDs.

#### Scenario: LLM selects registered capability only
- **WHEN** the LLM returns `capabilityId=MM.Inventory.GetAvailability` with required inventory parameters
- **THEN** the Agent accepts the candidate only after deterministic validation confirms the closed-set capability

#### Scenario: LLM returns unknown capability
- **WHEN** the LLM returns an unknown or unsupported `capabilityId`
- **THEN** the Agent rejects that LLM output for execution and does not call Gateway validate or execute from it

### Requirement: Missing parameter clarification
The system MUST clarify missing required inventory parameters before any Gateway validate or execute call, whether missing parameters are detected by rules or by LLM output.

#### Scenario: LLM missing plant is clarified before Gateway call
- **WHEN** the LLM identifies inventory availability intent but omits `plant`
- **THEN** the Agent returns a Chinese clarification asking for `plant`
- **AND** the Agent does not call Gateway validate or execute

### Requirement: Eval and trace evidence
The system SHALL provide repeatable fast eval coverage for the read-only Agent MVP and keep generated runtime evidence out of git. Normal verification MUST NOT require live LLM network access or real model credentials.

#### Scenario: Fake LLM eval covers hybrid behavior
- **WHEN** the Agent test suite runs without live LLM credentials
- **THEN** fake LLM cases verify happy path, missing params, fallback, unknown capability, malformed JSON, and `rfcName` guard behavior

#### Scenario: Optional live LLM smoke is explicitly gated
- **WHEN** live LLM smoke tests exist
- **THEN** they run only when an explicit environment flag is set
- **AND** they skip by default without printing API keys, full model gateway config, or raw sensitive response content

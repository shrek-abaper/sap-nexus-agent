## ADDED Requirements

### Requirement: Chinese inventory intent parsing
The system SHALL parse Chinese inventory availability queries for `MM.Inventory.GetAvailability` into normalized intent parameters without using free-form RFC names.

#### Scenario: Parse complete inventory availability query
- **WHEN** the user asks `DEMOA1 在 1000 还有多少可用库存？`
- **THEN** the Agent identifies inventory availability intent and extracts `material=DEMOA1` and `plant=1000`

#### Scenario: Parse optional unit when present
- **WHEN** the user asks `查一下 DEMOA1 在 1000 的 EA 可用量`
- **THEN** the Agent extracts `material=DEMOA1`, `plant=1000`, and `unit=EA`

### Requirement: Missing parameter clarification
The system MUST clarify missing required inventory parameters before any Gateway validate or execute call.

#### Scenario: Missing plant is clarified before Gateway call
- **WHEN** the user asks `查一下 DEMOA1 的可用量`
- **THEN** the Agent returns a Chinese clarification asking for `plant` and does not call Gateway validate or execute

#### Scenario: Missing material is clarified before Gateway call
- **WHEN** the user asks `查一下 1000 工厂还有多少可用库存`
- **THEN** the Agent returns a Chinese clarification asking for `material` and does not call Gateway validate or execute

### Requirement: Closed-set capability selection
The system SHALL select capabilities only from the Registry closed set and MUST reject unsupported intent before Gateway execution.

#### Scenario: Inventory availability selects registered capability
- **WHEN** a complete inventory availability query includes valid `material` and `plant`
- **THEN** the Agent selects `MM.Inventory.GetAvailability` from the Registry closed set

#### Scenario: Unknown intent is rejected
- **WHEN** the user asks for a non-inventory task such as creating a purchase requisition
- **THEN** the Agent rejects the request as unsupported for this read-only MVP and does not call Gateway validate or execute

#### Scenario: Agent cannot override RFC name
- **WHEN** a user query or internal request includes an `rfcName` value
- **THEN** the Agent ignores or rejects the supplied `rfcName` and uses only the Registry-selected `capabilityId`

### Requirement: CallPlan before Gateway execution
The system SHALL create a structured CallPlan before Gateway validation or execution for every executable request.

#### Scenario: Complete request creates CallPlan before validate
- **WHEN** a complete inventory availability request is executable
- **THEN** the Agent creates a CallPlan containing `traceId`, `capabilityId=MM.Inventory.GetAvailability`, `kind=Function`, normalized parameters, validation policy, creator, and approval requirement before Gateway validate

#### Scenario: CallPlan is read-only
- **WHEN** the Agent creates a CallPlan for `MM.Inventory.GetAvailability`
- **THEN** the CallPlan records `requiresApproval=false` and contains no SAP write action fields

### Requirement: Gateway validate and execute orchestration
The system SHALL call the Java Gateway capability APIs by `capabilityId` and handle validation or execution failure as structured Agent outcomes.

#### Scenario: Valid request calls Gateway validate then execute
- **WHEN** Gateway validate succeeds for a complete CallPlan
- **THEN** the Agent calls Gateway execute for `MM.Inventory.GetAvailability` and parses the returned `ExecutionResult`

#### Scenario: Gateway validation failure stops execution
- **WHEN** Gateway validate returns `INVALID_PARAMETER` or `MISSING_PARAMETER`
- **THEN** the Agent returns a structured Chinese failure response and does not call Gateway execute

#### Scenario: Gateway execution failure is reported without secrets
- **WHEN** Gateway execute returns a failed `ExecutionResult`
- **THEN** the Agent reports the failure using `errorType` and safe return messages without exposing SAP passwords, destination config, tokens, or `.env` contents

### Requirement: ExecutionResult to ReasoningFact conversion
The system SHALL convert successful inventory `ExecutionResult` data into deterministic `ReasoningFact` evidence before narration.

#### Scenario: Successful execution creates availability fact
- **WHEN** Gateway execute returns success with `data.availableQuantity`, `data.material`, `data.plant`, and `data.unit`
- **THEN** the Agent creates a `ReasoningFact` with `predicate=availableQuantity`, `deterministic=true`, `confidence=1.0`, source capability metadata, and evidence fields for the returned quantity and unit

#### Scenario: Failed execution does not create success fact
- **WHEN** Gateway execute returns `success=false`
- **THEN** the Agent does not create a deterministic availability fact that claims a successful quantity

### Requirement: Chinese narration from facts only
The system SHALL render Chinese narrative only from fields present in `ReasoningFact` or structured failure outcomes.

#### Scenario: Narrate available quantity from fact
- **WHEN** a `ReasoningFact` contains material, plant, available quantity, and unit
- **THEN** the Chinese answer includes only those fact values and does not invent additional stock, demand, recommendation, or write-action details

#### Scenario: Narrator rejects missing fact values
- **WHEN** the narrator is asked to output a quantity that is not present in `ReasoningFact`
- **THEN** the Agent returns or raises a narrative guard failure instead of inventing the value

### Requirement: Eval and trace evidence
The system SHALL provide repeatable fast eval coverage for the read-only Agent MVP and keep generated runtime evidence out of git.

#### Scenario: Eval covers core Agent outcomes
- **WHEN** the eval runner executes the inventory availability cases
- **THEN** it verifies happy path, missing params, invalid params, unknown intent, Gateway failure, and sensitive-data guard outcomes

#### Scenario: Missing parameter cases do not call Gateway
- **WHEN** eval cases omit `material` or `plant`
- **THEN** Gateway validate and execute call counts remain zero

#### Scenario: Generated runtime evidence is not committed
- **WHEN** Agent execution writes callplans, facts, traces, or eval outputs under `runtime/`
- **THEN** generated runtime files remain ignored unless explicitly curated as safe fixtures outside runtime output paths

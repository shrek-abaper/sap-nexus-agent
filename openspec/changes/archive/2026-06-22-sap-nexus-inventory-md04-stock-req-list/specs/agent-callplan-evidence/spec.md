## MODIFIED Requirements

### Requirement: ExecutionResult to ReasoningFact conversion
The system SHALL convert successful inventory `ExecutionResult` data into deterministic `ReasoningFact` evidence before narration.

#### Scenario: Successful execution creates availability fact
- **WHEN** Gateway execute returns success with `data.availableQuantity`, `data.material`, `data.plant`, and optional MD04 evidence fields derived from `MRP_IND_LINES`
- **THEN** the Agent creates a `ReasoningFact` with `predicate=availableQuantity`, `deterministic=true`, `confidence=1.0`, source capability metadata, and evidence fields for the returned quantity and source field
- **AND** the Chinese narrative uses the normalized `availableQuantity` without exposing raw SAP table contents or credentials

#### Scenario: Failed execution does not create success fact
- **WHEN** Gateway execute returns `success=false`
- **THEN** the Agent does not create a deterministic availability fact that claims a successful quantity

## ADDED Requirements

### Requirement: Conversation-sequence eval cases cover multi-source parameter binding
The eval suite SHALL include conversation-sequence cases whose input is an ordered sequence of turns and whose assertions cover the resulting decision trajectory, not only a single utterance mapped to a single decision. A sequence case SHALL be able to assert, per turn, the decision type, which fields were elicited, which fields were not elicited, and the provenance of each resolved parameter. Single-utterance cases SHALL remain valid and MUST NOT be deleted or weakened to accommodate the new case shape.

#### Scenario: Derived fields are not elicited

- **WHEN** a sequence case supplies only the identifiers needed by the upstream capability
- **THEN** the fields obtainable from the upstream capability's output are absent from the elicited-field set
- **AND** each such resolved parameter carries `provenance=capability_derived`

#### Scenario: Upstream failure degrades to elicitation

- **WHEN** a sequence case makes the upstream capability return an empty result or fail
- **THEN** the trajectory shows the affected fields being elicited from the user
- **AND** no assertion accepts a fabricated value or an undeclared default in their place

#### Scenario: Conflicting user value follows declared priority

- **WHEN** a sequence case supplies a user value that differs from the value derivable upstream
- **THEN** the resolved value follows the declared source priority
- **AND** the case asserts that the conflict was recorded

#### Scenario: Unreachable upstream capability errors instead of degrading

- **WHEN** a sequence case removes the upstream capability from the governed capability set
- **THEN** the trajectory reports a capability gap and fails closed
- **AND** the case asserts that no degraded attempt at the consuming capability occurred

### Requirement: Eval evidence reports pending cases as unresolved with attribution
Eval evidence SHALL NOT report a case that did not execute as passing. A case that cannot execute SHALL be reported as unresolved together with its case identifier, the reason it cannot execute, and what would make it executable. Verification output MUST NOT summarize an unresolved case as a known issue, a pre-existing failure, or unrelated to core functionality.

#### Scenario: Unresolved case names itself and its cause

- **WHEN** an eval case cannot execute against the governed sources
- **THEN** the evidence output names the case identifier and the concrete reason
- **AND** the case is counted as unresolved rather than passed or silently omitted

#### Scenario: Executable case must not remain pending

- **WHEN** the governed sources allow a previously unexecutable case to be constructed
- **THEN** the case executes and is asserted
- **AND** it is no longer reported as pending

## ADDED Requirements

### Requirement: Missing-producer dry-run gap is exercised against the governed capability set
The dry-run evidence suite SHALL exercise the missing-producer gap against the governed capability set rather than defer it. When a goal or a consuming capability input requires a value that no active capability can produce, the dry-run output SHALL report a capability gap identifying the unproducible requirement. This case SHALL be an executed, asserted case; it MUST NOT be carried as a pending or skipped entry, and it MUST NOT be considered covered solely by a lower-level unit test.

#### Scenario: Unproducible requirement yields a capability gap

- **WHEN** a dry-run is compiled for a goal whose required value no active capability produces
- **THEN** the dry-run output contains a capability gap naming that requirement
- **AND** no Gateway validate or execute call is made

#### Scenario: Missing-producer case executes rather than skips

- **WHEN** the dry-run evidence suite runs
- **THEN** the missing-producer case executes and its assertions are evaluated
- **AND** the evidence output does not report it as pending or skipped

### Requirement: Dry-run reports unbound inputs and derivation diagnostics as gaps
When a consuming capability input cannot be bound because the only candidate producer field requires cardinality reduction, or because more than one candidate producer exists, the dry-run output SHALL report the input as a gap carrying the diagnostic kind. The compiler MUST NOT bind the input by choosing a candidate, applying a reduction, or inserting a default.

#### Scenario: Reduction-required candidate is reported as a gap

- **WHEN** the only candidate producer field for a required scalar input has `cardinality: many`
- **THEN** the dry-run output reports that input as a gap carrying the `needsReduction` diagnostic kind
- **AND** the input is not bound to any parameter source

#### Scenario: Ambiguous candidates are reported as a gap

- **WHEN** more than one candidate producer field could bind the same required input
- **THEN** the dry-run output reports that input as a gap carrying the `ambiguous` diagnostic kind
- **AND** the compiler selects none of the candidates

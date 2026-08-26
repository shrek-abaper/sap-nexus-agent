## ADDED Requirements

### Requirement: A user-supplied value takes precedence over a value derivable from an upstream Fact

When a required input can be satisfied both by a value the user supplied and by a field of an
upstream Fact, the system SHALL bind the user-supplied value and SHALL NOT bind the derived one.
Precedence SHALL be applied at plan-authoring time: the planner SHALL NOT author an upstream-Fact
parameter source for a parameter that already carries a user-supplied source, so exactly one source
is authored per parameter. When a required input is *not* supplied by the user and an upstream Fact
can supply it, the system SHALL bind the derived value and SHALL NOT elicit the field from the user.
A derived value SHALL carry `provenance=capability_derived` and SHALL remain traceable to the
upstream node that produced it.

This requirement governs the planning layer. It does not alter the published source priority of
`binding.sources[]`, which governs resolution inside the extraction layer.

#### Scenario: User-supplied value suppresses derivation

- **WHEN** a required input declares an upstream Fact as an alternative source and the user supplies
  a value for that input
- **THEN** the parameter is bound from the user-supplied value
- **AND** no upstream-Fact parameter source is authored for that parameter
- **AND** the producing capability is not pulled into the plan on that input's account
- **AND** no additional read is executed for that input

#### Scenario: Unsupplied input is derived rather than elicited

- **WHEN** a required input declares an upstream Fact as an alternative source and the user supplies
  no value for it
- **THEN** the parameter is bound from the upstream Fact field
- **AND** no clarification question for that field is raised
- **AND** the bound value carries `provenance=capability_derived` together with the identity of the
  upstream node it came from

#### Scenario: Conflict between a user value and an available derived value is recorded

- **WHEN** the user supplies a value for an input, and an upstream node present in the plan for
  another reason also produces a differing value for that same input
- **THEN** the user-supplied value is the resolved value
- **AND** the evidence records the input name, the user-supplied value, the available derived value,
  and that the user-supplied source won
- **AND** the conflict is not resolved silently

#### Scenario: Matching values record no conflict

- **WHEN** a user-supplied value and an available derived value for the same input are equal
- **THEN** the resolved value is that value
- **AND** no conflict is recorded

### Requirement: Unavailable upstream value degrades to elicitation, never to fabrication

When an upstream-Fact parameter source cannot produce a value — the upstream node returned no value,
returned an empty value, or failed — the system SHALL elicit the field from the user. The system MUST
NOT substitute a value that was not declared as a source, MUST NOT reuse a value from a different
field or a different business object instance, and MUST NOT silently apply a default that the input
did not declare. When the upstream capability itself is unavailable or cannot be planned, the system
SHALL surface a capability gap and fail closed rather than attempt a degraded execution.

#### Scenario: Empty upstream value falls back to asking the user

- **WHEN** an input's only non-user source is an upstream Fact field and the upstream node produced
  no value for that field
- **THEN** the system elicits that field from the user
- **AND** the input is not filled with a fabricated or borrowed value

#### Scenario: Failed upstream node does not invent a default

- **WHEN** the upstream node that would supply the derived value fails
- **AND** the consuming input declares no `default` source
- **THEN** the system elicits that field from the user
- **AND** no default value is applied for that input

#### Scenario: Unreachable upstream capability fails closed

- **WHEN** an input depends on an upstream Fact whose producing capability is not available in the
  governed capability set
- **THEN** the system reports a capability gap
- **AND** it does not attempt a degraded execution of the consuming capability

### Requirement: The capabilityOutput binding source remains unwired

Deriving a parameter from an upstream Fact SHALL NOT require a `capabilityOutput` entry in
`binding.sources[]`. The planning-layer declaration (`satisfiableByFactType` on the consuming input)
SHALL be the sole declaration needed, and the derived field SHALL be computed by semantic-type
equality rather than restated in the registry document. This change SHALL NOT alter the published
source-kind enum, the published source priority, or the status of the `capabilityOutput` execution
path.

#### Scenario: Derivation works without a capabilityOutput source

- **WHEN** a required input declares `satisfiableByFactType` and no `capabilityOutput` source
- **THEN** the parameter is still bound from the upstream Fact field when the user supplied no value
- **AND** the registry document contains no restatement of which field was used

#### Scenario: Published binding-source contract is unchanged

- **WHEN** the source kinds and their priority are inspected after this change
- **THEN** the kinds remain exactly `userUtterance`, `capabilityOutput`, `default`
- **AND** the priority remains `capabilityOutput > userUtterance > default`
- **AND** no `sessionContext` source kind exists
- **AND** the existing placeholder test marking the `capabilityOutput` execution path as
  unimplemented remains in place, unmodified

## ADDED Requirements

### Requirement: Projection field names conform to the authoritative Fact Type field list
Every projection-layer or presentation-layer restatement of a Fact Type's field names SHALL be conformance-checked against the authoritative Fact Type field list. The check SHALL fail when a restated field name does not exist in the authoritative list, and when a restatement drifts from the authoritative list by rename. A restatement MUST NOT introduce a field name that the Fact Type does not declare.

#### Scenario: Renamed authoritative field breaks the restatement

- **WHEN** a field is renamed in the authoritative Fact Type field list
- **THEN** the conformance check fails for every restatement that still carries the old name

#### Scenario: Unknown restated field name is rejected

- **WHEN** a projection-layer restatement names a field that the Fact Type does not declare
- **THEN** the conformance check fails and names the offending field and artifact

### Requirement: Every active primary-fact capability resolves a projection builder
The projection layer SHALL resolve a fact builder for every active capability that declares a primary Fact output. When a capability declares a primary Fact output and no builder resolves for it, the projection layer SHALL fail closed with a structured failure naming the capability, rather than silently producing no fact. A capability whose node produces no fact MUST NOT be treated as a successfully projected node.

#### Scenario: Registered capability without a builder fails closed

- **WHEN** an active capability declares a primary Fact output and the projection layer cannot resolve a builder for it
- **THEN** the projection reports a structured failure naming that capability
- **AND** the node is not reported as having produced a fact

#### Scenario: Derived parameter provenance survives projection

- **WHEN** a consuming node's parameter was resolved from an upstream node's fact field
- **THEN** the projected evidence retains the resolved value, its provenance, and the identity of the upstream node
- **AND** the value is not stripped from the payload presented for human approval

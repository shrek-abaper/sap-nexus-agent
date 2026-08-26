## MODIFIED Requirements

### Requirement: Canonical Fact Types and capability relations have single owners
The system SHALL publish a versioned Fact Type catalog and a versioned capability relation catalog. Capability output `factTypeRef` SHALL be the only authored source for `producesFactType`; fact-bound input `satisfiableByFactType` SHALL be the only authored source for `consumesFactType`; the relation catalog SHALL author only `dependsOn` and `precondition`. Every relation SHALL declare `origin` as either `derived` or `manual`, and an `origin: manual` relation SHALL declare a `justification` stating why the relation cannot be computed. A relation declared `origin: manual` that the deriver can compute from Fact Type field semantic types SHALL fail contract validation: the prohibition on hand-authoring a derivable data dependency is enforced by running the deriver, not by review. The acceptance criterion for a data dependency being present is that the derived view contains it, never that the relation catalog is non-empty.

#### Scenario: Compiler derives production edges
- **WHEN** a primary capability output references a published Fact Type
- **THEN** the semantic graph contains one `producesFactType` edge from the capability to that Fact Type
- **AND** the relation catalog does not repeat that derived edge

#### Scenario: Authored derived edge is rejected
- **WHEN** the relation catalog declares `producesFactType` or `consumesFactType`
- **THEN** contract validation fails before a semantic graph is published

#### Scenario: Manually authored derivable data dependency is rejected
- **WHEN** the relation catalog authors an `origin: manual` relation that reproduces a data dependency the deriver can compute from Fact Type field semantic types
- **THEN** contract validation fails and names the relation and the derivable edge it duplicates
- **AND** no semantic graph or Registry Snapshot is published from that catalog

#### Scenario: Manual relation without justification is rejected
- **WHEN** a relation declares `origin: manual` without a `justification`
- **THEN** contract validation fails and names the relation

#### Scenario: Missing relation endpoint is rejected
- **WHEN** a `dependsOn` capability or `precondition` Fact Type does not exist
- **THEN** contract validation reports `RELATION_ENDPOINT_NOT_FOUND` at the exact JSON Pointer path

## ADDED Requirements

### Requirement: Data dependency edges are derived from field semantic types by strict equality
The system SHALL derive candidate data dependency edges deterministically, without any model call, by matching a producer Fact Type field's `semanticType` against a consuming capability input's `semanticType`. The candidate set for a consuming input SHALL be scoped to the fields of the single Fact Type that input declares as `satisfiableByFactType`, and to the active capabilities that produce that Fact Type; the deriver SHALL NOT search Fact Types the consuming input has not declared. A match SHALL require string equality of the semantic type identifiers. The deriver MUST NOT use similarity, prefix, substring, fuzzy, or embedding comparison, and MUST NOT consult field names, descriptions, or ordering to establish a match. Given the same governed sources the deriver SHALL return the same result.

#### Scenario: Equal semantic types produce a candidate edge
- **WHEN** a consuming capability input declares a `satisfiableByFactType`, and exactly one field of that Fact Type declares the same `semanticType` as the input, and that field is scalar
- **THEN** the derived view contains one candidate edge from that producer field to that consuming input

#### Scenario: Different semantic types produce no edge
- **WHEN** a producer Fact Type field and a consuming capability input declare different `semanticType` values, however similar their names
- **THEN** the derived view contains no candidate edge between them
- **AND** no approximate or partial match is reported as a candidate

#### Scenario: A field of an undeclared Fact Type is not a candidate
- **WHEN** a Fact Type the consuming input does not declare as `satisfiableByFactType` contains a field of the same `semanticType` as that input
- **THEN** that field is not reported as a candidate for that input
- **AND** its presence does not make the input ambiguous

#### Scenario: Derivation is deterministic and non-executing
- **WHEN** the deriver runs repeatedly against the same governed sources
- **THEN** it returns the same candidate edges and the same diagnostics in the same order
- **AND** it performs no model call, Gateway call, or SAP call

### Requirement: Cardinality mismatch and ambiguity are reported, never resolved silently
The deriver SHALL NOT match a producer field whose `cardinality` is `many` to a scalar consuming input; it SHALL instead emit a `needsReduction` diagnostic naming the producer field and the consuming input. No reduction operator SHALL be applied, chosen, or defaulted. When more than one field within the consuming input's declared Fact Type matches that input's `semanticType`, or when more than one active capability produces that Fact Type, the deriver SHALL NOT select one; it SHALL emit an `ambiguous` diagnostic listing every candidate for human resolution. A diagnostic SHALL NOT be silently downgraded into a match, and a diagnosed input SHALL be reported as unbound rather than bound.

#### Scenario: Many-cardinality producer feeding a scalar input needs reduction
- **WHEN** a producer Fact Type field declares `cardinality: many` and a consuming input of the same `semanticType` is scalar
- **THEN** the derived view contains no candidate edge between them
- **AND** a `needsReduction` diagnostic names the producer field and the consuming input

#### Scenario: No reduction operator is applied
- **WHEN** a `needsReduction` diagnostic is emitted
- **THEN** no aggregation, first-element selection, single-element requirement, or extremum is applied to produce a value
- **AND** the consuming input remains unbound by that candidate

#### Scenario: Multiple matching fields within the declared Fact Type are ambiguous
- **WHEN** two or more fields of the consuming input's declared Fact Type match that input's `semanticType`
- **THEN** the derived view contains no candidate edge for that input
- **AND** an `ambiguous` diagnostic lists every candidate producer field

#### Scenario: Multiple producers of the declared Fact Type are ambiguous
- **WHEN** two or more active capabilities produce the Fact Type a consuming input declares
- **THEN** the derived view contains no candidate edge for that input
- **AND** an `ambiguous` diagnostic lists every producing capability

### Requirement: The derived data dependency view is reviewable
The system SHALL expose the derived candidate edges and diagnostics as an inspectable artifact and as a printable command output, so a human can review what the deriver concluded before it is relied upon. The view SHALL identify, for each candidate edge, the producing capability, the producing Fact Type field, the consuming capability, the consuming input, and the matched `semanticType`; and for each diagnostic, its kind and the entities involved. A derived edge SHALL be emitted in the same shape as an authored `dependsOn` relation, so the existing plan compiler consumes it without a new relation type being introduced for derivedness. An empty view SHALL be reported as empty rather than as an error.

#### Scenario: View reports candidate edges with full provenance
- **WHEN** the derived view is produced from the governed sources
- **THEN** each candidate edge names its producing capability, producing Fact Type field, consuming capability, consuming input, and matched `semanticType`
- **AND** the edge is expressed in `dependsOn` shape with `origin: derived`

#### Scenario: Empty view is a valid result
- **WHEN** no producer field semantic type equals any consuming input semantic type
- **THEN** the view reports zero candidate edges without failing

### Requirement: A positive control proves the deriver can produce a match
An empty derived view is indistinguishable at the output from a deriver that can never match anything, so an empty view alone SHALL NOT be accepted as evidence that derivation works. The system SHALL maintain a positive control: a fixture of fabricated capabilities and Fact Type fields constructed so that exactly one data dependency edge must be derived, asserted to produce that edge. The positive control SHALL live in test fixtures and SHALL NOT be published into the governed source set, so it never becomes part of the execution boundary. A green positive control is a required condition for relying on an empty real-capability view.

#### Scenario: Positive control derives its expected edge
- **WHEN** the deriver runs against the positive control fixture
- **THEN** it produces exactly the one expected candidate edge
- **AND** the assertion fails if that edge is absent

#### Scenario: A structurally broken deriver cannot pass
- **WHEN** the deriver is unable to match any field to any input, for example because the two sides are compared across different semantic-type vocabularies
- **THEN** the positive control fails
- **AND** an empty real-capability view is not reported as a satisfied acceptance criterion

#### Scenario: Positive control is not a governed source
- **WHEN** the Registry Snapshot is computed
- **THEN** the positive control fixture contributes nothing to it
- **AND** the fabricated capabilities are absent from the active capability set

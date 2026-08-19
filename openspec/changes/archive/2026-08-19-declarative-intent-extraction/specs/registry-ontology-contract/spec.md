# registry-ontology-contract Specification (delta)

## ADDED Requirements

### Requirement: Extraction declaration validation in registry contract

The registry contract validator SHALL validate intent-extraction declarations
on every active capability: matcher kind SHALL be one of the supported kinds;
keyword matchers with a constant `value` mapping and conditional
`when`/`requiredWhen` structures SHALL reference declared input fields with a
well-formed equality condition; `excludes` entries SHALL resolve to declared
input names of the same capability; `weakKeywords` SHALL be disjoint from
`primaryKeywords`; inline regex matchers SHALL compile successfully; regex
patterns SHALL be rejected when they exceed the backtracking-safety guard
(pattern length and nested-quantifier limits); every `semanticType` extraction
reference SHALL resolve to a published entry in the semantic-type extraction
catalog; and every required or conditionally required input SHALL carry a
`clarifyPrompt` covering the supported locales with well-formed
`cases`/`fallback` structure. A capability with malformed extraction
declarations SHALL fail validation before any runtime intent path can use it.

#### Scenario: Invalid regex rejected at load time

- **WHEN** a capability declares an input extraction matcher with a regex that
  does not compile or exceeds the backtracking-safety limits
- **THEN** registry contract validation fails with the offending capability and
  input identified

#### Scenario: Dangling semantic-type reference rejected

- **WHEN** an input extraction declaration references a `semanticType` that is
  not published in the semantic-type extraction catalog
- **THEN** registry contract validation fails before runtime use

#### Scenario: Missing clarify locale rejected

- **WHEN** a required input's `clarifyPrompt` omits a supported locale
- **THEN** registry contract validation fails for that capability

#### Scenario: Malformed condition or overlapping keyword tier rejected

- **WHEN** a `when`/`requiredWhen` condition references an undeclared input,
  an `excludes` entry does not resolve to a declared input name, or a keyword
  appears in both `primaryKeywords` and `weakKeywords`
- **THEN** registry contract validation fails with the offending capability
  and declaration identified

#### Scenario: Valid declarations pass

- **WHEN** all active capabilities carry well-formed extraction declarations
  that resolve against the catalog and cover required-input locales
- **THEN** registry contract validation succeeds

### Requirement: Semantic-type extraction catalog contract

The system SHALL treat `registry/semantic-types.yaml` as a versioned registry
artifact: each entry SHALL declare a semantic type identifier used as an
extraction reference key, at least one matcher, and an extraction priority;
entries SHALL be validated for regex compile/backtracking safety and duplicate
identifier rejection. The catalog SHALL be loaded atomically with the
capability registry so a snapshot always pairs capabilities with a consistent
catalog version, and gateway runtime behavior SHALL be unaffected by catalog
content (extraction metadata is agent-side).

#### Scenario: Duplicate catalog identifier rejected

- **WHEN** the catalog declares two entries with the same semantic type
  identifier
- **THEN** catalog validation fails

#### Scenario: Capability registry and catalog load as one snapshot

- **WHEN** the agent loads the registry for a governance snapshot
- **THEN** the capability declarations and the semantic-type catalog are
  resolved from the same load, so extraction references never cross catalog
  versions

#### Scenario: Gateway ignores extraction metadata safely

- **WHEN** the gateway loads a registry containing extraction declarations and
  a semantic-type catalog
- **THEN** gateway execution, validation, and governance behavior is unchanged
  compared to a registry without extraction metadata

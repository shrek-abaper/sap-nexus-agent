# semantic-goal-resolution Specification

## Purpose
Accept an untrusted, LLM-produced semantic goal draft for a business question and resolve it deterministically, goal-facts-first, against the pinned visible SemanticRelease: typed facts and constraints, visible READ producer search, dependency closure, and explicit clarify/gap outcomes — without the model ever authoring an executable plan.

## Requirements

### Requirement: SemanticGoalDraft v1 strict intake contract

The system SHALL accept goal proposals only as versioned SemanticGoalDraft v1 documents validating against a strict JSON Schema (`additionalProperties: false`) with fields for requested facts (registered Fact type, output fields, object selectors), typed constraints with provenance (`explicitUser` / `confirmedContext`), analysis nodes referencing registered operators with typed inputs and controlled parameters, requested conclusions with evidence requirements, and explanation-only assumptions. Validation SHALL additionally perform deep technical-key scanning and reject RFC names, binding ids, URLs, credentials, SQL/SPARQL/code/expressions, arbitrary JSONPath, execution-authorization markers, dynamic import markers, non-finite numbers, oversized inputs, abnormal nesting, and over-limit node counts.

#### Scenario: Well-formed draft validates

- **WHEN** a draft contains registered fact requests, typed constraints, and registered operator references within limits
- **THEN** the draft passes schema and deep-scan validation and enters resolution

#### Scenario: Technical content is rejected regardless of nesting

- **WHEN** a draft contains an RFC name, binding id, URL, credential-looking value, SQL/code expression, or arbitrary path in any field including nested analysis parameters
- **THEN** validation rejects the draft with a structured error naming the offending field
- **AND** no planning or execution step runs

#### Scenario: Bounded-input rejection

- **WHEN** a draft contains a non-finite number, exceeds declared node/depth/length limits, or uses an undeclared property
- **THEN** validation rejects the draft with a structured bounds/schema error

### Requirement: Draft is untrusted and never re-serialized through text

The server SHALL treat the draft as advisory only. Any snapshot id, principal, visibility scope, technical binding, or version authority carried in the draft SHALL be ignored and replaced by server-owned values bound to the pinned release and caller scope. The entry point SHALL consume the typed request directly; typed slots SHALL NOT be rendered back into natural-language text and re-parsed.

#### Scenario: Draft-supplied authority is ignored

- **WHEN** a draft echoes a snapshot id, principal, or binding
- **THEN** the bound plan records the server-owned release id and server principal/scope
- **AND** the draft values appear nowhere in the executable plan

#### Scenario: Typed slots bypass text round-tripping

- **WHEN** the typed analysis entry receives structured slots
- **THEN** they reach the resolver as typed values without a build-query-to-text re-parse

### Requirement: Goal-first desired fact resolution

Resolution SHALL begin from the requested Fact types and fields in the draft, resolving them against the pinned SemanticRelease, and only then search for producing capabilities. Requested fields SHALL be restricted to analysis-legal fields in the release allowlist; object selectors SHALL bind registered object keys with organizational/system scope. A field or Fact type absent from the release SHALL produce a structured semantic/capability gap, never a guessed field.

#### Scenario: Requested field outside the allowlist gaps

- **WHEN** a draft requests a field not present in the release Fact-field allowlist
- **THEN** resolution returns a semantic gap naming the Fact type and requested field
- **AND** no capability call is planned for that field

#### Scenario: Object selectors bind typed keys and scope

- **WHEN** a requested fact carries material/plant selectors
- **THEN** resolution binds them as registered object keys with the caller's organizational scope
- **AND** a same-named semantic type without matching object key/scope is not treated as the same object

### Requirement: Visible READ producer search with deterministic ambiguity outcomes

The producer search SHALL consider only capabilities that are active, `kind: Function`, `sideEffect: none`, `requiresApproval: false`, and visible to the caller under the server-owned principal/scope. Visibility filtering SHALL happen before candidates are shown to the interpreter model and SHALL be re-verified at compile and execution. Zero producers SHALL yield `capability_gap`; multiple producers SHALL require a published resolution policy or explicit user clarification and MUST NOT be resolved by list order, model preference, or prompting.

#### Scenario: Zero producer yields capability gap

- **WHEN** a desired Fact type has no visible active READ producer in the release
- **THEN** resolution returns `capability_gap` naming the Fact type
- **AND** no plan node is authored

#### Scenario: Multiple producers never auto-pick

- **WHEN** exactly two visible READ capabilities produce a desired Fact type
- **THEN** resolution records an ambiguity outcome listing the candidates
- **AND** no node is authored until a published policy or user clarification resolves it

#### Scenario: Invisible producer cannot re-enter via clarification or closure

- **WHEN** a capability is invisible to the caller, including through a derived dependency path
- **THEN** it appears in no candidate set, clarification option, or auto-pulled closure

### Requirement: Required input closure and typed clarification

The resolver SHALL close required inputs using the registered derivation rules (producer fields satisfy consumer inputs), preserving the rule that derivable edges are never hand-authored into catalogs. A same field name or semantic type alone SHALL NOT prove object identity; closure SHALL bind object keys and scope. An unknown required value SHALL produce a typed clarification specifying the missing parameter; the system SHALL NOT substitute a default plant, unit, or other value.

#### Scenario: Derived input is closed through a registered producer

- **WHEN** a selected READ capability requires an input satisfiable by a Fact field of another visible producer
- **THEN** the closure includes that producer and binds the field per registered derivation
- **AND** the bound field's cardinality and object key match the consumer input

#### Scenario: Missing required value requests clarification

- **WHEN** a required object key (for example plant) has no explicit or confirmed-context value
- **THEN** resolution returns a clarification outcome naming the missing value
- **AND** no default value is assumed and no SAP call is made

### Requirement: Bounded interpreter interaction with fake default

The interpreter seam SHALL default to a deterministic fake adapter; selecting any remote model requires explicit later authorization (C3). Planning SHALL use at most two model interactions (initial draft plus at most one structural-repair turn); missing parameters and business ambiguities SHALL go directly to clarification rather than iterative repair loops.

#### Scenario: Default offline run uses the fake interpreter

- **WHEN** no model configuration is explicitly authorized
- **THEN** resolution runs entirely offline through the fake adapter with no outbound calls

#### Scenario: Structural repair is bounded to one turn

- **WHEN** the first draft fails only structural validation
- **THEN** at most one repair interaction is attempted
- **AND** a second structural failure terminates with a structured rejection

### Requirement: Combinatorial generality without question-specific recipes

The resolution and compilation path SHALL answer new legal combinations of registered facts and operators without question-specific functions or prompt branches. Correctness SHALL be judged on legal dependencies, necessary evidence, values/units/caliber, and forbidden calls — not on node ordering or an identical graph.

#### Scenario: Distinct questions produce materially different plans

- **WHEN** Q1 (stock plus base unit) and Q2 (purchase-order quantities grouped by supplier and unit alongside stock) are resolved
- **THEN** the resulting plans differ in their capability nodes and/or analysis DAG beyond parameter substitution

#### Scenario: Holdout phrasing passes without code changes

- **WHEN** a human-supplied holdout rephrasing of a legal combination is fed through the fake/typed entry
- **THEN** it resolves and compiles to a valid plan with no business-code or case-specific branch added

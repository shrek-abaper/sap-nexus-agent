# semantic-planning-foundation Specification

## Purpose
TBD - created by archiving change sap-nexus-semantic-planning-foundation. Update Purpose after archive.
## Requirements
### Requirement: Canonical Fact Types and capability relations have single owners
The system SHALL publish a versioned Fact Type catalog and a versioned capability relation catalog. Capability output `factTypeRef` SHALL be the only authored source for `producesFactType`; fact-bound input `satisfiableByFactType` SHALL be the only authored source for `consumesFactType`; the relation catalog SHALL author only `dependsOn` and `precondition`.

#### Scenario: Compiler derives production edges
- **WHEN** a primary capability output references a published Fact Type
- **THEN** the semantic graph contains one `producesFactType` edge from the capability to that Fact Type
- **AND** the relation catalog does not repeat that derived edge

#### Scenario: Authored derived edge is rejected
- **WHEN** the relation catalog declares `producesFactType` or `consumesFactType`
- **THEN** contract validation fails before a semantic graph is published

#### Scenario: Missing relation endpoint is rejected
- **WHEN** a `dependsOn` capability or `precondition` Fact Type does not exist
- **THEN** contract validation reports `RELATION_ENDPOINT_NOT_FOUND` at the exact JSON Pointer path

### Requirement: Semantic graph compilation is deterministic and immutable
The system SHALL compile validated capabilities, Fact Types, and authored relations into an in-process immutable semantic graph. Compilation MUST NOT perform filesystem writes, network calls, clock reads, random ID generation, plan search, policy execution, Gateway calls, or SAP calls.

#### Scenario: Equivalent source content produces the same graph
- **WHEN** the compiler receives the same validated semantic source documents repeatedly
- **THEN** it returns the same sorted node/edge indexes
- **AND** callers cannot mutate graph mappings, nested objects, or edge collections

#### Scenario: Dependency cycle fails closed
- **WHEN** authored `dependsOn` relations form a cycle
- **THEN** contract validation reports `DEPENDENCY_CYCLE`
- **AND** no graph or Registry Snapshot is returned as valid

### Requirement: Registry Snapshot binds plans to four governed sources
The system SHALL build `RegistrySnapshot v1` from canonicalized forms of capability Registry, executor-binding catalog, Fact Type catalog, and capability-relation catalog. Canonicalization SHALL normalize YAML to JSON-compatible data, recursively sort object keys, preserve array order, use stable separators and UTF-8, and compute lowercase SHA-256 identifiers.

#### Scenario: Formatting-only changes preserve snapshot identity
- **WHEN** YAML whitespace or object key order changes without changing normalized content
- **THEN** the computed `snapshotId` remains unchanged

#### Scenario: Governed source content changes snapshot identity
- **WHEN** any normalized value or array order in one of the four governed sources changes
- **THEN** the aggregate `snapshotId` changes

#### Scenario: Plan carries stale snapshot
- **WHEN** a PlanGraph `snapshotId` does not match the supplied Registry Snapshot
- **THEN** plan validation reports `SNAPSHOT_MISMATCH`

### Requirement: GoalSpec reachability uses published Fact Types and governance
The system SHALL validate `GoalSpec v1` with semantic `goalType`, unique desired Fact Types, typed scalar constraints, and execution mode `PLAN_ONLY` or `READ_ONLY`. It SHALL distinguish unknown vocabulary, missing producer capability, and governance incompatibility.

#### Scenario: Published Fact Type is reachable
- **WHEN** each desired Fact Type has at least one active producer compatible with the Goal execution mode
- **THEN** `GoalReachabilityReport.valid` is true
- **AND** all desired Fact Types appear in `reachableFactTypes`

#### Scenario: Unknown Fact Type is not converted into a capability gap
- **WHEN** a desired Fact Type is not published
- **THEN** validation reports `UNKNOWN_FACT_TYPE`
- **AND** it does not report `CAPABILITY_GAP` for that string

#### Scenario: Published Fact Type has no active producer
- **WHEN** a desired Fact Type is published but no active capability produces it
- **THEN** validation reports `CAPABILITY_GAP`

#### Scenario: READ_ONLY goal has only Action producer
- **WHEN** a published Fact Type has active producers but all require write side effects or approval
- **THEN** a `READ_ONLY` Goal reports `GOVERNANCE_VIOLATION`
- **AND** a `PLAN_ONLY` Goal does not authorize execution or approval

### Requirement: PlanGraph validates provenance, graph consistency, and projections
The system SHALL validate `PlanGraph v1` nodes against registered capabilities and the bound Registry Snapshot. Parameter sources SHALL be exactly one of `goalConstraint`, `literal`, or `factField`; edges SHALL be exactly one of `data` or `dependency`; produced Fact Types, governance, topological order, and Goal outputs SHALL match compiler-derived truth.

#### Scenario: Independent material-supply plan validates
- **WHEN** the plan contains `MM.Inventory.GetAvailability` and `MM.PurchaseOrder.GetList`, binds `material` and `plant` from Goal constraints, projects both READ governance contracts, and contains no edges
- **THEN** the plan validates against the current snapshot
- **AND** both desired Fact Types map to their registered producer nodes

#### Scenario: Required parameter provenance is missing or duplicated
- **WHEN** a required capability parameter has no source or more than one source
- **THEN** validation reports `PARAMETER_SOURCE_MISSING` or `PARAMETER_SOURCE_DUPLICATE`

#### Scenario: Fact data edge is inconsistent
- **WHEN** a `factField` source lacks one matching data edge, references a Fact Type the producer does not emit, or cannot satisfy the target fact-bound input
- **THEN** validation reports `EDGE_INCONSISTENT` or `FACT_TYPE_MISMATCH`

#### Scenario: Compiler projection is edited
- **WHEN** a plan changes a node's produced Fact Types, governance projection, order, or Goal-output producer relative to the snapshot-bound graph
- **THEN** validation reports `PLAN_PROJECTION_MISMATCH` or `GOAL_OUTPUT_UNSATISFIED`

#### Scenario: READ_ONLY plan contains Action
- **WHEN** a `READ_ONLY` plan references an Action or any capability whose governance is not read-only
- **THEN** validation reports `GOVERNANCE_VIOLATION`

#### Scenario: Plan attempts technical executor override
- **WHEN** GoalSpec or PlanGraph includes `bindingId`, `rfcName`, URL, credential, header, or executor mapping
- **THEN** schema/plan validation reports `SCHEMA_INVALID`
- **AND** no technical execution request is produced

### Requirement: Validation reports are structured and deterministic
The system SHALL return separate `ContractValidationReport`, `GoalReachabilityReport`, and `PlanValidationReport` values. Every issue SHALL contain an approved error code, JSON Pointer path, and message, sorted by `(path, code, message)`.

#### Scenario: Multiple independent contract errors are stable
- **WHEN** a source document contains independent duplicate identity and unknown Fact Type errors
- **THEN** the report contains `DUPLICATE_ID` and `UNKNOWN_FACT_TYPE`
- **AND** repeated validation returns issues in the same order

### Requirement: S1 remains validation-only
The system SHALL load contracts, compile the semantic graph, build snapshots, and validate hand-authored GoalSpec/PlanGraph fixtures only. It MUST NOT generate a plan, execute Gateway/SAP, or alter the current single-capability runtime.

#### Scenario: S1 regression runs without execution dependencies
- **WHEN** semantic planning contract tests and CLI validation run
- **THEN** they require no LLM credentials, SAP credentials, Gateway service, graph database, OWL runtime, or OpenHarness runtime
- **AND** existing selector, orchestrator, CallPlan, ReasoningFact, Gateway, approval, and eval regressions continue to pass

#### Scenario: Pilot scope is not overstated
- **WHEN** the material-supply fixture validates
- **THEN** it proves two READ nodes, typed Goal constraints, Fact outputs, governance projections, and snapshot consistency
- **AND** it does not claim shortage prediction, purchase quantity, automatic PR creation, runtime parallelism, or persisted result aggregation


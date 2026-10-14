## Purpose

Build and publish one deterministic, content-addressed semantic asset package (SemanticRelease v1) that binds the existing registry snapshot to a new semantic snapshot covering every semantic asset the ontology-governed read analysis path consumes, with distinct structural and business validation states, while leaving all legacy snapshot consumers untouched.

## ADDED Requirements

### Requirement: SemanticRelease v1 versioned contract

The system SHALL produce a SemanticRelease package carrying `schemaVersion`, the existing `registrySnapshotId`, a new `semanticSnapshotId`, `compilerVersion`, `operatorImplementationVersion`, and a per-source digest list for every semantic asset the package contains. The package SHALL validate against an explicit JSON Schema that rejects unknown properties. The package contract SHALL NOT add fields to the legacy GoalSpec, PlanGraph, or RegistrySnapshot contracts.

#### Scenario: Package document validates against its schema

- **WHEN** a SemanticRelease package is built from valid semantic sources
- **THEN** every required field is present with the declared `schemaVersion`
- **AND** the document validates against the SemanticRelease JSON Schema

#### Scenario: Unknown properties are rejected

- **WHEN** a package document contains a property not declared in the schema
- **THEN** schema validation fails naming the unknown property

#### Scenario: Legacy contracts gain no implicit fields

- **WHEN** the SemanticRelease capability is present
- **THEN** existing GoalSpec, PlanGraph, and RegistrySnapshot documents validate exactly as before
- **AND** no legacy consumer is required to read `semanticSnapshotId`

### Requirement: Explicit dual snapshot binding

Every SemanticRelease package SHALL bind exactly one existing `registrySnapshotId` (computed by the unchanged legacy snapshot builder over its current source set) to exactly one `semanticSnapshotId`. The package SHALL record the association between the two ids and the package version. The legacy registry snapshot source set, algorithm, and id computation SHALL remain unchanged.

#### Scenario: Package carries both ids and their association

- **WHEN** a package is built in a repository state with legacy snapshot id `R`
- **THEN** the package records `registrySnapshotId = R` and a non-empty `semanticSnapshotId`
- **AND** records the association between the two ids

#### Scenario: Legacy snapshot is byte-identical

- **WHEN** the legacy registry snapshot is computed before and after this capability exists
- **THEN** its source set, canonicalization, and id are unchanged
- **AND** existing legacy tools and planner paths consume it without adaptation

### Requirement: Versioned semantic asset source set

The `semanticSnapshotId` SHALL cover, with per-source content digests: an MM object-type/key/scope catalog; an analysis-legal Fact field mapping allowlist over the existing three READ facts; the registered analysis operator catalog; and the Definition applicability declarations. Adding, removing, or changing any consumed semantic source, or changing a bound compiler/operator implementation version, SHALL change the set of per-source digests.

#### Scenario: MM object keys are typed and scoped

- **WHEN** the package is built
- **THEN** the object-type catalog declares the minimum MM object set with typed object keys and organizational scope fields
- **AND** each object key references semantic types that resolve in the existing vocabulary

#### Scenario: Analysis Fact field allowlist references only declared fields

- **WHEN** the Fact field mapping allowlist is read from the package
- **THEN** every allowed field exists on `InventoryAvailabilityFact`, `PurchaseOrderSupplyFact`, or `MaterialInfoFact` in the current Fact type catalog
- **AND** fields not on those facts cannot be marked analysis-legal

#### Scenario: Consumed Definitions are referenced by id with applicability

- **WHEN** the package declares a business caliber Definition as applicable
- **THEN** it references an existing Definition by its stable id and records that Definition's grounded/proposed status
- **AND** it does not author new supply, demand, or ATP formulas

### Requirement: Change-sensitive content-addressed semantic snapshot

The `semanticSnapshotId` SHALL be a digest of the canonicalized content of all covered sources and bound version markers. The build SHALL be deterministic: identical inputs in any order produce byte-identical packages and identical ids, with no timestamps, host identifiers, absolute paths, or environment-derived values in the hashed content. Any semantic change to a covered source or bound implementation version MUST produce a different id.

#### Scenario: Same inputs reproduce the same package

- **WHEN** the package is built twice from an unchanged repository, including different working directories and source enumeration orders
- **THEN** both builds produce byte-identical package content and the same `semanticSnapshotId`

#### Scenario: Semantic source change changes the id

- **WHEN** any covered asset (object catalog, field allowlist, operator catalog, Definition applicability, or bound implementation version marker) changes
- **THEN** the rebuilt package gets a different `semanticSnapshotId`
- **AND** the per-source digest identifies the changed source

#### Scenario: Non-semantic changes outside the covered set do not change the id

- **WHEN** only files outside the declared semantic source set change
- **THEN** rebuilding against the same semantic inputs yields the same `semanticSnapshotId`

### Requirement: Registered analysis operator catalog closure

The first release SHALL register exactly four analysis operators: `select_fields`, `filter_eq`, `group_sum`, and `compare`. Each registration SHALL declare a typed input contract, output contract, and applicability constraints. The catalog SHALL be closed: there is no plugin or dynamic registration mechanism, and a reference to an unregistered operator is invalid.

#### Scenario: Four registered operators with typed contracts

- **WHEN** the operator catalog is read from the package
- **THEN** it contains exactly `select_fields`, `filter_eq`, `group_sum`, and `compare`
- **AND** each declares its input fields, output type, and applicability constraints

#### Scenario: Unknown operator reference fails structural validation

- **WHEN** an asset references an operator id not present in the catalog
- **THEN** validation fails with an unresolvable-operator error naming the reference

#### Scenario: No dynamic operator extension point

- **WHEN** the package is consumed
- **THEN** no mechanism exists to load additional operator implementations from package content or external paths

### Requirement: Distinct structural and business validation states

Package validation SHALL separate structural correctness (all references resolve; schema, id, and digest consistency; closed vocabulary) from business validity (applicable Definitions are evidence-grounded). An unresolvable reference, digest mismatch, or id mismatch SHALL fail the build. A reference to a merely `proposed` Definition SHALL produce a distinct, non-passing business-validity state without fabricating grounded status.

#### Scenario: Unresolvable reference fails the build

- **WHEN** the allowlist or applicability section references a Fact field or Definition id that does not exist
- **THEN** the build fails with a structural error naming the missing reference

#### Scenario: Digest or id inconsistency fails the build

- **WHEN** a recorded per-source digest or `semanticSnapshotId` does not match recomputed content
- **THEN** the build fails with a consistency error

#### Scenario: Proposed Definition yields a distinct validity state

- **WHEN** an applicability declaration references a `proposed` Definition
- **THEN** structural validation passes and business validity reports a distinct not-grounded state
- **AND** the package never presents that Definition as grounded

### Requirement: Deterministic build and check entry points

The system SHALL provide a build entry point that emits the package and a read-only check entry point that verifies an existing package without rewriting it or touching external systems. Both entry points SHALL run fully offline, exit non-zero with structured errors on validation failure, and emit no credentials or SAP/network calls.

#### Scenario: Check mode is read-only and offline

- **WHEN** the check entry point runs against a valid package
- **THEN** it exits zero without modifying files or performing network access

#### Scenario: Build failure reports structured errors

- **WHEN** the build entry point runs against invalid semantic sources
- **THEN** it exits non-zero and reports the failing validation state and offending asset id

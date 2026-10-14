# Comet Design Handoff

- Change: semantic-release-asset-pipeline
- Phase: design
- Mode: compact
- Context hash: 70b009d6b2ee4cc190df9ca0e663a37b82b7caa70bb316b35e113c78e4ffea21

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/semantic-release-asset-pipeline/proposal.md

- Source: openspec/changes/semantic-release-asset-pipeline/proposal.md
- Lines: 1-32
- SHA256: dcff77425e796f1eefacea426df6d637361d51617af04e700763f634b998a938

```md
## Why

The future ontology-constrained read analysis path needs a single, auditable semantic asset package: object keys/scopes, the Fact fields legal for analysis, the registered analysis operator catalog, and applicable business-caliber Definitions. Today no such package exists. The `RegistrySnapshot` (`semantic_planning/snapshot.py`) hashes only four registry documents (`registry/capabilities.yaml`, `registry/executor-bindings.yaml`, `ontology/fact-types.yaml`, `ontology/capability-relations.yaml`); Definitions, object links, and business rules are not snapshot inputs, so editing their statements changes neither a snapshot id nor generated artifacts. `ontology/generated/manifest.json` is only a two-file TTL hash list and must not be mistaken for a capability manifest. This change is phase C1 of the plan in `docs/nexus-ontology-planning-handoff.md`: it builds and versions the semantic release **without** introducing the goal resolver/compiler or execution path (C2, separate change `ontology-goal-read-analysis`).

## What Changes

- Add a **SemanticRelease v1** versioned contract (`schemaVersion`, existing `registrySnapshotId`, new `semanticSnapshotId`, `compilerVersion`, `operatorImplementationVersion`, per-source digest list) with an explicit JSON Schema; no silent fields are added to the legacy GoalSpec/PlanGraph/RegistrySnapshot contracts.
- Add the first semantic asset sources consumed exclusively by the new path:
  - MM minimum object-type/key/scope catalog (material, plant, supplier, purchase order/item) with typed object keys;
  - analysis-legal Fact field mapping allowlist over the three existing READ facts (`InventoryAvailabilityFact`, `PurchaseOrderSupplyFact`, `MaterialInfoFact`), grounded in `ontology/fact-types.yaml`;
  - analysis operator catalog registering exactly `select_fields`, `filter_eq`, `group_sum`, `compare` with typed input/output contracts;
  - Definition applicability declarations that reference existing entries by id (no new supply/demand/ATP formula; `proposed` entries are never promoted).
- Add a deterministic SemanticRelease builder/check entry point: canonical-JSON content hashing across the expanded source set and bound implementation-version digests; reproducible, timestamp-free, ordering-stable artifacts; cache keyed by semantic version and scope.
- Extend snapshot inputs **only inside the new package builder**; the legacy `build_registry_snapshot` source set and all old consumers remain byte-for-byte unchanged.
- Validate references (every Fact field/operator/Definition reference resolves) separately from business validity (evidence-grounded caliber), producing distinct validation states.
- Add schema, reference, and determinism tests for the package; C2 will verify the dual-id association at compile/execute time against a package produced by this change.

## Capabilities

### New Capabilities
- `semantic-release-package`: Deterministic build, content hashing, validation, and dual-snapshot binding of the versioned semantic asset package consumed by the future ontology-goal read analysis path, including the MM object-key catalog, analysis Fact-field allowlist, registered operator catalog, and Definition applicability declarations.

### Modified Capabilities
<!-- None. The legacy governed-context-registry-snapshot source set and requirements are unchanged;
     the new semanticSnapshotId is additive and lives only in the new package contract. -->

## Impact

- **New files (planned)**: `schemas/semantic-release.schema.json`; `ontology/object-types.yaml`; `ontology/analysis-operators.yaml`; semantic Fact-field allowlist and Definition applicability asset files; a package builder module under `agent/sap_nexus_agent/` (exact location decided in design); a `scripts/` check entry point; tests under `agent/tests/`.
- **Reused, not modified**: `semantic_planning/snapshot.py` canonicalization/digest primitives, `ontology/fact-types.yaml` version 3 field catalog, `ontology/definitions.yaml` / `object-links.yaml` / `business-rules.yaml` as read-only inputs, `scripts/build-ontology-bundle.py` generation conventions.
- **Consumers**: none yet inside this change; the C2 change `ontology-goal-read-analysis` is the first consumer and enforces compile/execute association. Legacy four semantic tools, PlanGraph v2, the Java Gateway, and WRITE governance are untouched.
- **Verification**: `openspec validate --all --strict`, ontology bundle check, evidence-grounding validation, and the new package tests. No SAP, paid model, network, or deployment dependency; offline by construction.

```

## openspec/changes/semantic-release-asset-pipeline/design.md

- Source: openspec/changes/semantic-release-asset-pipeline/design.md
- Lines: 1-87
- SHA256: 6ba9e96d2d21c9ea1bda87183d30ba21310a6fcaa8dc146f5428b44bdabb6a3e

[TRUNCATED]

```md
## Context

See `proposal.md` - Why. The governed dynamic read-analysis path (planned C2 change `ontology-goal-read-analysis`) can only be trusted if every capability, Fact field, operator, and caliber Definition it consumes comes from one immutable, content-addressed package. Today the immutable surface is the legacy `RegistrySnapshot` (`agent/sap_nexus_agent/semantic_planning/snapshot.py`), which digests exactly four documents via `canonical_json_bytes` + `sha256` (`SnapshotSource` per-document digests already exist). Definitions, object links, business rules, and (future) object-key/operator catalogs are outside that surface. This change adds the packaging layer only; nothing consumes the package yet.

Constraints verified at baseline HEAD `6444144`:

- Legacy snapshot source set is hard-coded in `SemanticSourceDocuments.documents_by_path()` and consumed by matcher, planner, and visibility paths; it must stay byte-identical.
- `ontology/generated/manifest.json` is a two-entry TTL file-hash list, not a capability manifest; the new artifact must not reuse or imitate that name.
- `ontology/definitions.yaml` already distinguishes `grounded` vs `proposed` with evidence/evidenceGap; `scripts/validate-evidence-grounding.py` already enforces evidence resolution and must stay green.
- Fact fields for the three READ facts are fixed in `ontology/fact-types.yaml` v3; PO supply rows expose order quantity, unit, supplier, material/plant, and PO/item identity only — no delivery date, goods-receipt quantity, or receipt status fields exist to allowlist.

## Goals / Non-Goals

**Goals:**

- One deterministic SemanticRelease v1 package binding `registrySnapshotId` + `semanticSnapshotId`, buildable and checkable offline.
- First complete semantic source set: MM object keys/scopes, analysis Fact-field allowlist, four-operator closed catalog, Definition applicability.
- Structural vs business validation states separated; legacy verification commands remain green.
- A package contract C2 can consume without schema churn.

**Non-Goals:**

- No resolver/compiler/interpreter/coordinator/runtime, no CLI analysis command, no fixtures execution (C2).
- No operator implementations or execution semantics; the catalog registers contracts and versions only.
- No frontend/chat, SAP, OWL reasoner, Neo4j, or new executor family.
- No changes to existing Definitions' statuses, no rewriting of proposed entries as grounded, no new formulas.
- No derivable edges authored into relation catalogs.

## Decisions

### D1. Additive dual-id package, not a RegistrySnapshot extension

SemanticRelease v1 is a **new wrapper document** carrying the existing `registrySnapshotId` verbatim plus the new `semanticSnapshotId` and per-source digests. The legacy snapshot object, its schema (`schemas/registry-snapshot.schema.json`), and its four-document source set are untouched.

- Alternative rejected: add the new sources to `SemanticSourceDocuments` and version the legacy snapshot. That mutates ids on every legacy path, breaks the "old four tools unchanged" guarantee, and entangles WRITE governance surfaces with an unbuilt feature.
- Consequence: two ids coexist and their association is a package property; C2 owns compile/execute-time correlation (its spec will require failure on mismatch).

### D2. Reuse the existing canonicalization/digest primitives

The package builder reuses `canonical_json_bytes` / `_sha256_id` conventions (sorted keys, compact separators, UTF-8, `sha256:` prefix) rather than introducing a second hashing style. Sources are loaded as parsed YAML→plain data and canonicalized identically; file ordering in all lists is lexicographic by logical path.

- Alternative rejected: hash raw file bytes. Byte-level hashing breaks on formatting-only changes and cannot cover derived/in-memory assemblies (e.g. the expanded source manifest). Content hashing makes "same semantics → same id" testable.

### D3. Covered source set is explicit and enumerated

The package builder has a closed, declared source manifest covering: the four legacy documents (digested, for association), `ontology/definitions.yaml`, `ontology/object-links.yaml`, `ontology/business-rules.yaml`, the new `ontology/object-types.yaml`, the new `ontology/analysis-operators.yaml`, the new Fact-field analysis allowlist asset, Definition applicability declarations, and explicit version-marker documents for `compilerVersion` / `operatorImplementationVersion`. "Outside the declared set" changes do not affect the id (testable as a scenario). Adding a covered source is itself a reviewed change to the manifest, never a silent directory scan.

### D4. Implementation version markers are checked-in version documents

Because no operator/compiler implementation exists in C1, `compilerVersion` and `operatorImplementationVersion` are read from explicit, checked-in version-marker documents inside the covered source set (constant versions with per-operator entries). C2 replaces/augments the marker when implementation lands (its build will digest actual implementation entry points); until then no digest of nonexistent code is fabricated.

- Alternative rejected: omit the fields in C1 and add them in C2. That would make C2's contract a schema migration of a package C2 tests already depend on; the fields must exist from v1 even though their values are declared, not computed.
- Open follow-up for design phase: exact marker file layout and whether C2 computes digests over one implementation entry-point module listed by path.

### D5. Closed YAML catalogs with explicit JSON Schemas

`ontology/object-types.yaml` and `ontology/analysis-operators.yaml` (plus the allowlist/applicability assets) follow the existing ontology YAML conventions and each get schema validation. Operator entries declare id (closed four), input field contracts (Fact field refs + semantic types), output contract, applicability constraints, and version. There is deliberately no `path`/`module`/arbitrary-expression capability in C1 catalogs; dynamic loading is prohibited by omission and by spec.

### D6. Two-layer validation with distinct result states

Layer 1 (structural): schema, closed vocabulary, reference resolution (Fact fields, semantic types, operator ids, Definition ids), per-source digest and snapshot-id consistency. Any failure fails the build. Layer 2 (business validity): applicability references to `proposed` Definitions produce a distinct `not_grounded` state per declaration; the package can still build structurally but MUST surface the state, and consumers (C2) are required to treat not-grounded Definitions as unavailable for conclusions. Existing evidence-grounding validation remains the authority for Definition evidence and is reused, not duplicated.

### D7. Naming and entry-point conventions

- Package output artifact: `semantic-release.json` (plus a check mode); never named `manifest.json` to avoid confusion with `ontology/generated/manifest.json`.
- Build/check follow the `scripts/build-ontology-bundle.py --check` precedent: a build command and a read-only `--check` command, offline, structured non-zero failures.
- Builder code lives in a new `agent/sap_nexus_agent/` module dedicated to semantic releases (final module name in the Design Doc); no code is added to `semantic_planning/` except possible import reuse.

## Risks / Trade-offs

- [Two ids drift apart] → The package records their association and C2 fails closed on mismatch; a check verifies the recorded `registrySnapshotId` equals a fresh legacy build in the same working tree.
- [Allowlist silently diverges from fact-types.yaml] → Structural validation resolves every allowlisted field against the current Fact catalog; unknown fields fail the build; the existing fact-type field validation tests are extended, not replaced.
- [Definition scope creep: uncalibrated business formulas enter via applicability] → Applicability references existing Definition ids only; no statement authoring; proposed status stays visible and blocks conclusions; reviewers diff the small applicability file.
- [Non-determinism from YAML anchors/key order/timestamps] → Canonicalize parsed data, sort all lists by logical path, exclude timestamps; determinism is a hard gate with a byte-identical rebuild test and an "outsider change cannot move the id" test.
- [C2 needs fields C1 didn't package] → v1 schema is strict but additive versions are anticipated; C1 freeze happens after Design Doc review; C2 may add `schemaVersion: 2`, never silent fields.
- [Generated TTL/SHACL assets not covered] → Accepted: generated SHACL is derived from registry inputs already digested; if Design Doc finds operator shapes must reach SHACL consumers, generation inputs (not generated bytes) are added to the manifest, and the determinism test covers regeneration.

## Migration Plan

- Purely additive: new files, new schemas, new script, new tests. No data migration, no state to move, no flags needed (nothing routes to the package until C2).

```

Full source: openspec/changes/semantic-release-asset-pipeline/design.md

## openspec/changes/semantic-release-asset-pipeline/tasks.md

- Source: openspec/changes/semantic-release-asset-pipeline/tasks.md
- Lines: 1-44
- SHA256: edc429f91e4afe842ec212b70e830e6edbbc8ee2661880c6d7a205b276a99a8a

```md
# Tasks — semantic-release-asset-pipeline (C1)

> Prerequisite: user-confirmed C0 design (this change plus `ontology-goal-read-analysis`).
> Every task states its own verification. No SAP, paid model, network, or deployment dependency.

## 1. Contract and schemas

- [ ] 1.1 Add `schemas/semantic-release.schema.json` (schemaVersion, registrySnapshotId, semanticSnapshotId, compilerVersion, operatorImplementationVersion, per-source digest list; strict additionalProperties) and verify a minimal valid package document validates and an unknown-property document fails
- [ ] 1.2 Add schemas for the new asset documents (object types, operator catalog, Fact-field allowlist, Definition applicability) and verify valid fixtures pass while missing-reference/unknown-enum fixtures fail
- [ ] 1.3 Add a schema contract test asserting legacy GoalSpec, PlanGraph v2, and registry-snapshot schema suites remain unchanged (run existing contract schema tests; zero diffs)

## 2. Semantic asset catalogs

- [ ] 2.1 Create `ontology/object-types.yaml` with the minimum MM object set (material, plant, supplier, purchase order, purchase order item), typed keys and organizational scope fields; verify every referenced semantic type resolves against `registry/semantic-types.yaml` / Fact catalog
- [ ] 2.2 Create the analysis Fact-field allowlist asset covering exactly the fields of `InventoryAvailabilityFact`, `PurchaseOrderSupplyFact`, `MaterialInfoFact` legal for analysis; verify each allowlisted field resolves in `ontology/fact-types.yaml` v3 and no delivery-date/receipt/ATP field appears
- [ ] 2.3 Create `ontology/analysis-operators.yaml` registering exactly `select_fields`, `filter_eq`, `group_sum`, `compare` with typed input/output contracts, applicability constraints, and per-operator version; verify the catalog has no path/module/plugin fields and a sixth/unknown operator fixture fails validation
- [ ] 2.4 Create the Definition applicability asset referencing existing Definition ids (incl. recording `grounded` vs `proposed` status) without authoring new statements; verify `scripts/validate-evidence-grounding.py` still passes and a missing-id reference fails structural validation

## 3. SemanticRelease builder

- [ ] 3.1 Implement the closed source manifest enumerating covered logical paths (four legacy documents plus definitions/object-links/business-rules plus the new assets) and verify adding an undeclared file is impossible without editing the manifest
- [ ] 3.2 Add checked-in compiler/operator implementation version-marker documents covered by the manifest; verify the markers parse and carry per-operator versions
- [ ] 3.3 Implement canonicalized content hashing reusing the existing canonical-JSON/sha256 conventions with lexicographic source ordering; verify per-source digests and `semanticSnapshotId` are produced
- [ ] 3.4 Implement dual-id binding: build the legacy registry snapshot through the unchanged builder and bind its id into the package with the association record; verify a mismatched fresh legacy id is detected
- [ ] 3.5 Implement package emission (`semantic-release.json`) conforming to the schema; verify generated output contains no timestamps, absolute paths, or host identifiers in hashed content

## 4. Two-layer validation

- [ ] 4.1 Implement structural validation (schema, closed vocabulary, Fact-field/operator/Definition/semantic-type reference resolution, digest/id consistency) and verify each failure class produces a structured error naming the offending asset
- [ ] 4.2 Implement the distinct business-validity layer: applicability on `proposed` Definitions yields a `not_grounded` state without failing structural validation and without presenting the Definition as grounded
- [ ] 4.3 Verify structural and business results are separately observable in the check output (distinct states, not one boolean)

## 5. Build and check entry points

- [ ] 5.1 Add a build entry point following the `scripts/build-ontology-bundle.py` precedent and verify it emits the package deterministically
- [ ] 5.2 Add a read-only `--check` mode and verify it exits zero without writing files or performing network access, and non-zero on a tampered package

## 6. Determinism and regression tests

- [ ] 6.1 Add a byte-identical rebuild test (two builds, different enumeration order/working directory, same inputs → identical package and id)
- [ ] 6.2 Add change-sensitivity tests: mutate each covered source kind (object catalog, allowlist, operator catalog, applicability, version marker) → changed id and changed per-source digest
- [ ] 6.3 Add an insulation test: change a file outside the covered set → unchanged `semanticSnapshotId`
- [ ] 6.4 Add legacy compatibility tests: legacy snapshot id, planner v2 dry-run tests, and the four legacy semantic tool suites are unaffected
- [ ] 6.5 Run and record the full affected verification: `openspec list --json && openspec validate --all --strict`, `PYTHONPATH=agent .venv/bin/python scripts/build-ontology-bundle.py --check`, evidence-grounding validation, impact/constraint/codegen pytest targets, and the new package tests; attach actual outputs as the C1 evidence record

```

## openspec/changes/semantic-release-asset-pipeline/specs/semantic-release-package/spec.md

- Source: openspec/changes/semantic-release-asset-pipeline/specs/semantic-release-package/spec.md
- Lines: 1-138
- SHA256: f30859b79f07028b8f2f412179432cfdad6c24e65a3f20b549a602babecde9a5

[TRUNCATED]

```md
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


```

Full source: openspec/changes/semantic-release-asset-pipeline/specs/semantic-release-package/spec.md

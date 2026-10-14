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
- Deploy order: schemas → asset YAMLs → builder → check wired into verification; each step independently mergeable.
- Rollback: remove/revert the new files; legacy snapshot ids and all existing paths are unaffected by construction (verified by unchanged legacy snapshot test outputs).

## Open Questions

- Exact package artifact location (repo-tracked vs generated-under-`ontology/generated/` with a distinct filename) and whether `--check` runs in CI by default — answerable in the Design Doc without spec changes.
- Whether the Fact-field allowlist is one standalone asset or a marked section of an existing/new catalog file; spec behavior (resolved refs, digested content) is identical either way.

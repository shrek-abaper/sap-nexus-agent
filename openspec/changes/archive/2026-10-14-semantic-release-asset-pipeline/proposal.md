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

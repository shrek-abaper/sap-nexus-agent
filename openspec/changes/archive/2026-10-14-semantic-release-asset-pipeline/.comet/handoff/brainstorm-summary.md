# Brainstorm Summary

- Change: semantic-release-asset-pipeline
- Date: 2026-10-14

## Confirmed Technical Approach

Five NEW authored asset files under `ontology/` (the four legacy snapshot documents are never edited):

1. `object-types.yaml` v1 — MM minimum object set (Material, Plant, Supplier, PurchaseOrder, PurchaseOrderItem) with typed object keys and organizational scope fields, referencing existing semantic types.
2. `analysis-operators.yaml` v1 — closed catalog of exactly `select_fields`, `filter_eq`, `group_sum`, `compare`; each entry declares input field contract (Fact field refs + semantic types), output contract, applicability constraints, and per-operator version; no path/module/plugin fields.
3. `analysis-fact-fields.yaml` v1 — analysis-legal field allowlist over exactly InventoryAvailabilityFact (availableQuantity only; opaque mrpElementLines interior not opened), PurchaseOrderSupplyFact (all 7 declared fields), MaterialInfoFact (material, plant, baseUnitOfMeasure, purchasingGroup).
4. `definition-applicability.yaml` v1 — EMPTY applicability list. The only grounded Definition (available-for-commitment) describes MD04 running quantity as "available to promise"; citing it as applicable would authorize ATP labeling the new path must not make. Both grounded/not_grounded business-validity states are exercised by temp-fixture tests.
5. `analysis-versions.yaml` v1 — declared `compilerVersion` constant and per-operator implementation version constants (markers only; C2 binds real implementation digests).

Digested source set (closed manifest coded in the builder; no directory scanning): legacy four documents via `load_semantic_sources`/`build_semantic_contracts` snapshot sources (role=legacy, for association) plus `ontology/definitions.yaml`, `object-links.yaml`, `business-rules.yaml` and the five new files (role=semantic). Hashing reuses `semantic_planning.snapshot.canonical_json_bytes` + sha256 conventions; all source lists sorted lexicographically by logical path.

Output: tracked `ontology/generated/semantic-release.json` built by `scripts/build-semantic-release.py [--check]` with the bundle script's exit-code contract (0 in sync / 1 stale or invalid / 2 usage). Builder package: `agent/sap_nexus_agent/semantic_release/{__init__,assets,contracts,builder,validation}.py`; no edits inside `semantic_planning/`. Five new strict JSON Schemas under `schemas/`.

Package v1 shape: `schemaVersion=1`, `registrySnapshotId`, `semanticSnapshotId`, `compilerVersion`, `operatorImplementationVersion` (map per operator), `sources[]` (path, documentVersion, digest, role), `businessValidity.applicability[]`.

## Key Trade-offs and Risks

- Empty applicability in v1 means no caliber-backed conclusions in C2 — intentional; caliber honesty over completeness.
- New files instead of sections in fact-types.yaml/capabilities.yaml: mandatory to keep legacy registrySnapshotId byte-identical.
- Declared version markers instead of implementation digests: no implementations exist in C1; fabricating code digests is worse than an explicit marker C2 replaces.
- Risks: allowlist drift from fact-types.yaml (structural reference validation), non-determinism (parsed-data canonicalization, sorted lists, rebuild test), accidental legacy-source edits (diff review + unchanged-id test), stale committed package (`--check` gate).

## Testing Strategy

`agent/tests/test_semantic_release_*.py`: byte-identical rebuild across cwd/order; change sensitivity per source kind; outsider-file insulation; unknown Fact field/operator/Definition/semantic-type structural failures; digest and snapshot-id tamper failures; dual-id association mismatch detection; legacy snapshot id unchanged with the package present; check mode is read-only; strict-schema unknown-property rejection; business-validity grounded vs not_grounded on temp fixtures without failing structural build. Project gates: openspec strict validate, build-ontology-bundle --check, evidence-grounding validator, codegen/constraint/impact pytest targets.

## Spec Patches

None. The open-phase delta spec (`specs/semantic-release-package/spec.md`) already covers the accepted behavior; the empty applicability list is authored asset content, not a requirement change.

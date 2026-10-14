---
comet_change: semantic-release-asset-pipeline
role: technical-design
canonical_spec: openspec
archived-with: 2026-10-14-semantic-release-asset-pipeline
status: final
---

# Design Doc — SemanticRelease Asset Pipeline (C1)

Deep technical refinement of `openspec/changes/semantic-release-asset-pipeline/design.md` (D1–D7, user-confirmed in C0). This document is implementation-authoritative; the OpenSpec delta remains the requirements authority.

## 1. Architecture overview

```text
authored sources (repo-tracked)                 builder (new python package)
┌─────────────────────────────────────┐        ┌──────────────────────────────────────┐
│ registry/capabilities.yaml          │── legacy ┐                                      │
│ registry/executor-bindings.yaml     │         │                                      │
│ ontology/fact-types.yaml            │         │ semantic_release.assets             │
│ ontology/capability-relations.yaml  │── legacy┤  (closed path manifest + YAML load) │
│ registry/semantic-types.yaml        │         │                                      │
│                                      │         └──────────────┬───────────────────────┘
│ ontology/definitions.yaml           │── semantic ┐           │
│ ontology/object-links.yaml          │           │           ▼
│ ontology/business-rules.yaml        │           ├──▶ canonicalize (semantic_planning
│ ontology/object-types.yaml        ★ │           │    │   snapshot.canonical_json_bytes)
│ ontology/analysis-operators.yaml  ★ │           │    ▼
│ ontology/analysis-fact-fields.yaml★ │           │ per-source sha256 + semanticSnapshotId
│ ontology/definition-applicability★  │           │    ▼
│ ontology/analysis-versions.yaml   ★ │ ──────────┘ semantic_release.validation
└─────────────────────────────────────┘                 (structural / business, two reports)
                                                              │
                                              legacy registrySnapshotId via
                                              load_semantic_sources +
                                              build_semantic_contracts (unchanged)
                                                              ▼
                                          ontology/generated/semantic-release.json (tracked)
                                                              ▲
                              scripts/build-semantic-release.py [--check]
```

★ = new authored files in this change. The four legacy documents are read through the existing `semantic_planning.loader.load_semantic_sources` path and never modified.

## 2. Authored asset contracts

All new assets are versioned YAML (`version: 1`) validated by strict JSON Schemas in `schemas/`. Naming follows `fact-type-catalog.schema.json` conventions (`$id https://sap-nexus-agent.local/schemas/<file>`, draft 2020-12, `additionalProperties: false`).

### 2.1 `ontology/object-types.yaml`

```yaml
version: 1
objectTypes:
  - objectTypeId: sapnexus:Material
    semanticType: sapnexus:MaterialNumber
    keyFields: [material]
    scopeFields: []
  - objectTypeId: sapnexus:Plant
    semanticType: sapnexus:Plant
    keyFields: [plant]
    scopeFields: [plant]          # organizational scope carrier
  - objectTypeId: sapnexus:Supplier
    semanticType: sapnexus:Supplier
    keyFields: [supplier]
    scopeFields: []
  - objectTypeId: sapnexus:PurchaseOrder
    semanticType: sapnexus:PurchaseOrderNumber
    keyFields: [purchaseOrder]
    scopeFields: [plant]
  - objectTypeId: sapnexus:PurchaseOrderItem
    semanticType: sapnexus:PurchaseOrderItem
    keyFields: [purchaseOrder, purchaseOrderItem]
    scopeFields: [plant]
```

- `semanticType` MUST resolve in `registry/semantic-types.yaml` or `ontology/fact-types.yaml` valueTypes.
- Scope expresses the organizational/system dimension; plant is the only v1 scope dimension (single-user sandbox, no tenant catalog yet).

### 2.2 `ontology/analysis-fact-fields.yaml`

```yaml
version: 1
allowlist:
  - factTypeId: sapnexus:InventoryAvailabilityFact
    fields:
      - name: availableQuantity
        semanticType: sapnexus:AvailableQuantity
  - factTypeId: sapnexus:PurchaseOrderSupplyFact
    fields:
      - {name: purchaseOrder,     semanticType: sapnexus:PurchaseOrderNumber}
      - {name: purchaseOrderItem, semanticType: sapnexus:PurchaseOrderItemNumber}
      - {name: supplier,          semanticType: sapnexus:Supplier}
      - {name: material,          semanticType: sapnexus:MaterialNumber}
      - {name: plant,             semanticType: sapnexus:Plant}
      - {name: orderQuantity,     semanticType: sapnexus:Quantity}
      - {name: purchaseOrderUnit, semanticType: sapnexus:UnitOfMeasure}
  - factTypeId: sapnexus:MaterialInfoFact
    fields:
      - {name: material,           semanticType: sapnexus:MaterialNumber}
      - {name: plant,              semanticType: sapnexus:Plant}
      - {name: baseUnitOfMeasure,  semanticType: sapnexus:UnitOfMeasure}
      - {name: purchasingGroup,    semanticType: sapnexus:PurchasingGroup}
```

- Every `(factTypeId, name, semanticType)` triple MUST exist in the current fact-types catalog; cardinality is taken from the catalog (not redeclared).
- `mrpElementLines` is intentionally absent (opaque list, interior not decomposed).
- No delivery/receipt/ATP field exists to allowlist — this is the structural reason Q5/Q6 gap in C2.

### 2.3 `ontology/analysis-operators.yaml`

```yaml
version: 1
operators:
  - operatorId: select_fields
    version: "0.1.0"
    input: {kind: rows}
    params:
      - {name: fields, type: fieldRefList, required: true}
    output: {kind: rows}
    constraints: [fields-must-be-allowlisted]
  - operatorId: filter_eq
    params:
      - {name: field, type: fieldRef, required: true}
      - {name: value, type: typedLiteral, required: true}
    ...
  - operatorId: group_sum
    params:
      - {name: dimensions, type: fieldRefList, required: true}
      - {name: measure, type: fieldRef, required: true, allowedSemanticTypes: [sapnexus:Quantity]}
      - {name: unitField, type: fieldRef, required: true}
    output: {kind: groupedRows}
    constraints: [dimensions-must-be-allowlisted, unit-grouping-mandatory, decimal-only]
  - operatorId: compare
    params:
      - {name: left, type: measureRef, required: true}
      - {name: right, type: measureRef, required: true}
    constraints: [same-semantic-kind, same-unit, time-point-policy]
    output: {kind: comparison}
```

Closed enum of four ids; schema rejects a fifth. No executable path/module/expression fields exist anywhere in the asset.

### 2.4 `ontology/definition-applicability.yaml`

```yaml
version: 1
# v1 deliberately empty: no existing Definition is declared applicable to
# ontology-goal read-analysis conclusions. The sole grounded Definition
# (sapnexus:def.available-for-commitment) phrases MD04 running quantity as
# "available to promise"; the read-analysis path must not label WB/MD04 as ATP.
applicability: []
```

Schema still defines the entry shape (`definitionId` ref, `status: grounded|proposed`, `applicableScopes`) so C2/future changes add entries without schema migration and tests can build temp fixtures exercising grounded/not_grounded.

### 2.5 `ontology/analysis-versions.yaml`

```yaml
version: 1
compilerVersion: "0.1.0"
operatorImplementations:
  select_fields: "0.1.0"
  filter_eq: "0.1.0"
  group_sum: "0.1.0"
  compare: "0.1.0"
```

Constants in C1 (no implementations exist). C2 replaces values per its release-binding design (digest or version of the actual entry points); changing them changes `semanticSnapshotId` because the file is a covered source.

## 3. Package document v1

`ontology/generated/semantic-release.json`:

```json
{
  "schemaVersion": 1,
  "registrySnapshotId": "sha256:...",
  "semanticSnapshotId": "sha256:...",
  "compilerVersion": "0.1.0",
  "operatorImplementationVersion": {
    "select_fields": "0.1.0", "filter_eq": "0.1.0",
    "group_sum": "0.1.0", "compare": "0.1.0"
  },
  "sources": [
    {"path": "ontology/analysis-fact-fields.yaml", "documentVersion": 1,
     "digest": "sha256:...", "role": "semantic"},
    "... lexicographic order ..."
  ],
  "businessValidity": {
    "applicability": []
  }
}
```

- `semanticSnapshotId = sha256(canonical({"sources": [<semantic-role path,documentVersion,digest,role>...sorted], "compilerVersion": ..., "operatorImplementationVersion": {...}}))` — hashes the eight semantic-role source digests and version markers, not absolute paths or timestamps. Legacy rows are excluded: they are already covered by `registrySnapshotId`, so a legacy registry edit never silently moves the semantic id (independence pinned by `test_semantic_change_moves_semantic_id_only`). Verification (2026-10-14) refined this from the earlier draft formula that included every source row; the structural validator recomputes the id over semantic rows to match (`validation.compute_semantic_snapshot_id`).
- Legacy per-source digests are taken from the unchanged `RegistrySnapshot.sources` for the four legacy paths and emitted with `role: legacy`; their snapshot id is copied verbatim into `registrySnapshotId` (builder recomputes it from the working tree and records it — a fresh build against edited legacy sources naturally yields a different id; the dual-id association check in C2 compares ids inside one package).
- JSON written deterministically: `json.dumps(..., sort_keys=True, ensure_ascii=False, indent=2)` + trailing newline; byte-for-byte reproducible.
- Strict schema: `schemas/semantic-release.schema.json`, `additionalProperties: false`.

## 4. Module design — `agent/sap_nexus_agent/semantic_release/`

| Module | Responsibility | Key symbols (planned) |
|---|---|---|
| `assets.py` | Closed source manifest (logical paths + roles), YAML loading reusing `load_yaml_mapping` | `SEMANTIC_SOURCE_MANIFEST`, `load_release_assets(repo_root)` |
| `contracts.py` | Frozen dataclasses: `ReleaseSource`, `SemanticReleasePackage`, `SemanticReleaseIssue`, structural + business reports | `SemanticReleasePackage`, `StructuralValidationReport`, `BusinessValidityReport` |
| `validation.py` | Schema validation (jsonschema, schemas resolved from repo `schemas/`), closed vocabularies, reference resolution against fact-types/semantic-types/operators/definitions, digest/id consistency | `validate_structure(package, assets, vocabularies)`, `assess_business_validity(assets)` |
| `builder.py` | Load legacy snapshot (`load_semantic_sources` + `build_semantic_contracts`), canonicalize, digest, assemble package, validate, emit dict | `build_semantic_release(repo_root) -> SemanticReleasePackage` |
| `__init__.py` | Re-exports only | — |

Frozen dataclasses reuse the `MappingProxyType` freeze convention from `semantic_planning/contracts.py`. No network, clock, host, or cwd-derived values enter hashed content (the determinism test pins cwd independence).

### Structural issue codes (closed set)

`SR_SCHEMA_INVALID`, `SR_UNKNOWN_FIELD_REF`, `SR_UNKNOWN_FACT_TYPE`, `SR_UNKNOWN_SEMANTIC_TYPE`, `SR_UNKNOWN_OPERATOR`, `SR_OPERATOR_NOT_IN_CLOSED_SET`, `SR_UNKNOWN_DEFINITION_REF`, `SR_DIGEST_MISMATCH`, `SR_SNAPSHOT_ID_MISMATCH`, `SR_DUPLICATE_SOURCE`, `SR_MANIFEST_VIOLATION`.

Business report entries: `{definitionId, declaredStatus, state: grounded|not_grounded}`. A `proposed` reference → `not_grounded`; structural build still succeeds and the package records it; C2 treats such Definitions as unavailable for conclusions.

## 5. Build/check entry point

`scripts/build-semantic-release.py` mirrors `build-ontology-bundle.py`:

- no args: rebuild `ontology/generated/semantic-release.json` (atomic write), exit 0/1/2;
- `--check`: load committed package, rebuild in memory, compare bytes and all ids/digests; print `OUT_OF_SYNC <detail>` lines and exit 1 on drift; read-only (test asserts output file mtime/content unchanged);
- `PYTHONPATH` bootstrapping identical to the bundle script; offline, no credentials.

## 6. Edge cases and failure handling

- YAML parse error or non-mapping root → `SourceLoadError`-style failure naming path; build exit 1.
- Legacy snapshot invalid (pre-existing registry drift) → fail the build; do not mask with a self-computed id.
- Allowlist field whose catalog entry changed semanticType → `SR_UNKNOWN_FIELD_REF` (triple mismatch), fail.
- Duplicate logical path in manifest → `SR_DUPLICATE_SOURCE`.
- Operator catalog listing fewer/more than the closed four in any consuming asset → structural error (the authored catalog itself is the closed set; schema enum pins four ids).
- Empty applicability → structural pass, business report with empty list; explicitly tested.
- File outside the manifest (e.g. a new YAML dropped into `ontology/`) → ignored by construction; insulation test proves the id does not move.

## 7. Test strategy

New files: `agent/tests/test_semantic_release_builder.py`, `..._validation.py`, `..._script.py`.

1. Determinism: build twice with a different cwd and reversed manifest enumeration → byte-identical JSON and identical `semanticSnapshotId`.
2. Change sensitivity: parameterized mutation of each covered source kind (object type, allowlist field, operator param, applicability entry, version marker, and each of definitions/object-links/business-rules) → changed id, changed per-source digest.
3. Insulation: add/touch a non-manifest file → unchanged id.
4. Structural failures: one test per issue code via minimal temp fixtures.
5. Tamper: hand-edit a digest or snapshot id in the package → `--check` exits 1.
6. Legacy compatibility: build legacy snapshot before/after package present → identical id; run existing compiler v2 and semantic-planning contract suites.
7. Check read-only: `--check` does not modify the generated file (stat before/after).
8. Strict schema: unknown top-level/nested property rejected.
9. Business validity: temp applicability fixtures for grounded and proposed → distinct states; proposed never presented as grounded.

Project-level verification recorded in tasks 6.5: openspec strict validate (change scope), `build-ontology-bundle.py --check`, evidence-grounding validator, codegen/constraint/impact pytest targets, plus the new tests. No frontend, SAP, or model dependency.

## 8. Rollback

Purely additive: five YAMLs, five schemas, one python package, one script, one generated JSON, tests. Removing these files leaves legacy snapshot ids and every existing path unchanged (guarded by test 6). No state or data migration exists.

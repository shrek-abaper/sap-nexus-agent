# Tasks — semantic-release-asset-pipeline (C1)

> Prerequisite: user-confirmed C0 design (this change plus `ontology-goal-read-analysis`).
> Every task states its own verification. No SAP, paid model, network, or deployment dependency.

## 1. Contract and schemas

- [x] 1.1 Add `schemas/semantic-release.schema.json` (schemaVersion, registrySnapshotId, semanticSnapshotId, compilerVersion, operatorImplementationVersion, per-source digest list; strict additionalProperties) and verify a minimal valid package document validates and an unknown-property document fails
- [x] 1.2 Add schemas for the new asset documents (object types, operator catalog, Fact-field allowlist, Definition applicability) and verify valid fixtures pass while missing-reference/unknown-enum fixtures fail
- [x] 1.3 Add a schema contract test asserting legacy GoalSpec, PlanGraph v2, and registry-snapshot schema suites remain unchanged (run existing contract schema tests; zero diffs)

## 2. Semantic asset catalogs

- [x] 2.1 Create `ontology/object-types.yaml` with the minimum MM object set (material, plant, supplier, purchase order, purchase order item), typed keys and organizational scope fields; verify every referenced semantic type resolves against `registry/semantic-types.yaml` / Fact catalog
- [x] 2.2 Create the analysis Fact-field allowlist asset covering exactly the fields of `InventoryAvailabilityFact`, `PurchaseOrderSupplyFact`, `MaterialInfoFact` legal for analysis; verify each allowlisted field resolves in `ontology/fact-types.yaml` v3 and no delivery-date/receipt/ATP field appears
- [x] 2.3 Create `ontology/analysis-operators.yaml` registering exactly `select_fields`, `filter_eq`, `group_sum`, `compare` with typed input/output contracts, applicability constraints, and per-operator version; verify the catalog has no path/module/plugin fields and a sixth/unknown operator fixture fails validation
- [x] 2.4 Create the Definition applicability asset referencing existing Definition ids (incl. recording `grounded` vs `proposed` status) without authoring new statements; verify `scripts/validate-evidence-grounding.py` still passes and a missing-id reference fails structural validation

## 3. SemanticRelease builder

- [x] 3.1 Implement the closed source manifest enumerating covered logical paths (four legacy documents plus definitions/object-links/business-rules plus the new assets) and verify adding an undeclared file is impossible without editing the manifest
- [x] 3.2 Add checked-in compiler/operator implementation version-marker documents covered by the manifest; verify the markers parse and carry per-operator versions
- [x] 3.3 Implement canonicalized content hashing reusing the existing canonical-JSON/sha256 conventions with lexicographic source ordering; verify per-source digests and `semanticSnapshotId` are produced
- [x] 3.4 Implement dual-id binding: build the legacy registry snapshot through the unchanged builder and bind its id into the package with the association record; verify a mismatched fresh legacy id is detected
- [x] 3.5 Implement package emission (`semantic-release.json`) conforming to the schema; verify generated output contains no timestamps, absolute paths, or host identifiers in hashed content

## 4. Two-layer validation

- [x] 4.1 Implement structural validation (schema, closed vocabulary, Fact-field/operator/Definition/semantic-type reference resolution, digest/id consistency) and verify each failure class produces a structured error naming the offending asset
- [x] 4.2 Implement the distinct business-validity layer: applicability on `proposed` Definitions yields a `not_grounded` state without failing structural validation and without presenting the Definition as grounded
- [x] 4.3 Verify structural and business results are separately observable in the check output (distinct states, not one boolean)

## 5. Build and check entry points

- [x] 5.1 Add a build entry point following the `scripts/build-ontology-bundle.py` precedent and verify it emits the package deterministically
- [x] 5.2 Add a read-only `--check` mode and verify it exits zero without writing files or performing network access, and non-zero on a tampered package

## 6. Determinism and regression tests

- [x] 6.1 Add a byte-identical rebuild test (two builds, different enumeration order/working directory, same inputs → identical package and id)
- [x] 6.2 Add change-sensitivity tests: mutate each covered source kind (object catalog, allowlist, operator catalog, applicability, version marker) → changed id and changed per-source digest
- [x] 6.3 Add an insulation test: change a file outside the covered set → unchanged `semanticSnapshotId`
- [x] 6.4 Add legacy compatibility tests: legacy snapshot id, planner v2 dry-run tests, and the four legacy semantic tool suites are unaffected
- [x] 6.5 Run and record the full affected verification: `openspec list --json && openspec validate --all --strict`, `PYTHONPATH=agent .venv/bin/python scripts/build-ontology-bundle.py --check`, evidence-grounding validation, impact/constraint/codegen pytest targets, and the new package tests; attach actual outputs as the C1 evidence record

## Verification evidence (C1)

- New package tests: 56 passed (`test_semantic_release_contracts/assets/validation/builder/properties/build_semantic_release_script`).
- Legacy regression: 475 passed (semantic planning v1/v2, compiler v2, derivation, contract files, ontology codegen, evidence grounding, impact analysis, constraint runtime).
- `scripts/build-ontology-bundle.py --check`: in sync; `scripts/build-semantic-release.py --check`: in sync; `scripts/validate-evidence-grounding.py`: OK.
- `openspec validate semantic-release-asset-pipeline --strict`: valid.
- No SAP, network, paid model, or frontend dependency; legacy registrySnapshotId unchanged across semantic-only mutations (property test).

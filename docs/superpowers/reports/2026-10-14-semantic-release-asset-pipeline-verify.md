# Verification Report: semantic-release-asset-pipeline

- Date: 2026-10-14
- Change: semantic-release-asset-pipeline (C1)
- Verify mode: full (22 tasks, 1 delta capability, 26 changed files incl. workflow artifacts)
- Base ref: `6444144a57da8ce34b2248eeab42b6bbf26b1d72`
- Bound branch: `main` (isolation=current)

## Summary

| Dimension | Status |
|---|---|
| Completeness | 23/23 tasks.md items checked; plan 44/44 steps checked; 7/7 requirements implemented |
| Correctness | 57/57 new tests pass; 19/19 spec scenarios mapped to tests; 475/475 legacy regression pass |
| Coherence | design.md D1–D7 followed; Design Doc followed after one documented refinement (see WARNING-1, fixed) |

**Final assessment: all CRITICAL checks pass; one WARNING found and repaired during verification. Ready for archive decision.**

## Fresh evidence (all commands run in this verify phase)

| Command | Result |
|---|---|
| `openspec validate semantic-release-asset-pipeline --strict` | Change is valid |
| `scripts/build-ontology-bundle.py --check` | ontology generated artifacts are in sync (exit 0) |
| `scripts/build-semantic-release.py --check` | semantic release package is in sync (exit 0) |
| `scripts/validate-evidence-grounding.py` | Evidence grounding: OK (exit 0) |
| pytest: six new `test_semantic_release_*` / `test_build_semantic_release_script` modules | **57 passed** |
| pytest: semantic planning v1/v2, compiler v2, derivation, contract files, ontology codegen, evidence grounding, impact, constraint runtime | **475 passed** |
| `git diff --name-status 6444144..HEAD` on legacy four sources + legacy schemas | empty (legacy untouched) |

Not run (out of scope, no relevant code touched): SAP live, paid models, frontend verify, deployment.

## Completeness

- tasks.md: 23/23 `[x]` with an appended evidence block.
- Implementation plan: 44/44 steps `[x]`.
- Delta capability `semantic-release-package`, 7 requirements — every requirement has implementation and tests (mapping below).

## Correctness — requirement/scenario to test mapping

1. **SemanticRelease v1 versioned contract** — package schema acceptance/unknown-property rejection: `test_semantic_release_package_schema_*` (7 cases); legacy-contract-no-implicit-fields: legacy files untouched + 475 regression tests.
2. **Explicit dual snapshot binding** — both ids + association: `test_build_package_happy_path`, `test_built_package_passes_structural_validation`; byte-identical legacy id: `test_legacy_snapshot_id_is_the_unchanged_registry_snapshot`, `test_semantic_change_moves_semantic_id_only` (registry id invariant).
3. **Versioned semantic asset source set** — object keys: `test_object_types_*`; allowlist triples: `test_allowlist_triples_exist_in_fact_catalog`; applicability by id, no new formulas: `test_definition_applicability_*`, `test_business_validity_*`; shipped applicability is empty.
4. **Change-sensitive content-addressed snapshot** — byte determinism: `test_byte_deterministic_and_sorted_sources`, `test_build_is_byte_deterministic`, `test_build_emits_byte_deterministic_artifact`; change sensitivity: `test_semantic_change_moves_semantic_id_only` (8 parameterized source kinds, digest + id move; registry id does not); insulation: `test_outsider_file_does_not_move_ids`.
5. **Registered analysis operator catalog closure** — closed four with typed contracts and no executable properties: `test_operator_catalog_is_closed_four`; unknown/fifth operator: `test_operator_catalog_rejects_bad_shapes`, `test_unknown_operator_ref_fails`, `test_operator_catalog_not_closed_set_fails`.
6. **Distinct structural and business validation states** — structural failures per issue code: one test each for `SR_SCHEMA_INVALID`, `SR_UNKNOWN_FIELD_REF`, `SR_UNKNOWN_FACT_TYPE`, `SR_UNKNOWN_SEMANTIC_TYPE`, `SR_UNKNOWN_OPERATOR`, `SR_OPERATOR_NOT_IN_CLOSED_SET`, `SR_UNKNOWN_DEFINITION_REF`, `SR_DIGEST_MISMATCH` (semantic and legacy rows), `SR_SNAPSHOT_ID_MISMATCH`, `SR_DUPLICATE_SOURCE`, `SR_MANIFEST_VIOLATION`; proposed-Definition distinct state: `test_business_validity_grounded_and_proposed`.
7. **Deterministic build and check entry points** — read-only check incl. mtime/size assertion: `test_check_succeeds_when_in_sync`; stale exit 1 with `OUT_OF_SYNC`: `test_check_detects_stale_artifact`; usage exit 2: `test_usage_error_exit_code`; no network/credentials imported by the build path (code inspection).

## Coherence

- design.md D1 additive dual-id, D2 reuse canonicalization primitives (`canonical_json_bytes` imported, not duplicated), D3 closed in-code manifest (`SEMANTIC_SOURCE_MANIFEST`, no directory scan), D4 checked-in version markers (`ontology/analysis-versions.yaml`), D5 strict YAML+JSON Schemas (five new schemas, recursive `additionalProperties:false`), D6 two-layer validation (`validate_structure` / `assess_business_validity`), D7 naming (`semantic-release.json`, never `manifest.json`) and `scripts/build-semantic-release.py` with bundle-script exit codes — all followed.
- Design Doc module layout (`semantic_release/{__init__,assets,contracts,builder,validation}.py`) matches the tree.
- Build-phase standard review (inline, subagents disabled per user instruction) found one Important issue — legacy per-source digests were not rechecked; fixed with `test_tampered_legacy_digest_fails` (red-green).

## WARNING-1 (found and fixed in verify)

Design Doc §3 originally specified `semanticSnapshotId` over **all** source rows; the implementation hashes only the eight semantic-role rows plus version markers, so legacy registry edits cannot move the semantic id (true dual-id independence, consistent with the delta spec, pinned by property tests). The Design Doc §3 formula was corrected to the implemented behavior with an explicit refinement note. No code or spec change; no re-run impact (the formula is unchanged since build; the 57/475 evidence above postdates the doc-only edit).

## SUGGESTION (non-blocking)

- `validate_structure` runs jsonschema on authored assets during every package validation; a future change could expose a standalone asset lint command for CI. Not needed in C1 (the build/check path enforces it).

## Branch handling

Left pending per workflow: archive owns branch finishing after the archive commit. No push performed.

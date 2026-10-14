---
change: semantic-release-asset-pipeline
design-doc: docs/superpowers/specs/2026-10-14-semantic-release-asset-pipeline-design.md
base-ref: 6444144a57da8ce34b2248eeab42b6bbf26b1d72
---

# SemanticRelease Asset Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task (subagents are explicitly disabled for this change). Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic, content-addressed SemanticRelease v1 package binding the unchanged legacy registry snapshot to a new semantic snapshot over five new authored assets.

**Architecture:** New additive Python package `agent/sap_nexus_agent/semantic_release/` loads five new `ontology/*.yaml` assets plus three existing read-only ontology documents, canonicalizes and hashes them with the existing `semantic_planning.snapshot` primitives, binds the legacy `registrySnapshotId` computed through the unchanged loader/validator, and emits tracked `ontology/generated/semantic-release.json` via a build script with `--check`.

**Tech Stack:** Python 3.12, stdlib + PyYAML + jsonschema (already dependencies), pytest. No network, clock, or host-derived values in hashed content.

**Spec:** `openspec/changes/semantic-release-asset-pipeline/specs/semantic-release-package/spec.md`; Design Doc `docs/superpowers/specs/2026-10-14-semantic-release-asset-pipeline-design.md`.

## Global Constraints

- Additive only: never edit `registry/capabilities.yaml`, `registry/executor-bindings.yaml`, `ontology/fact-types.yaml`, `ontology/capability-relations.yaml`, `registry/semantic-types.yaml`; never edit anything under `semantic_planning/`.
- New asset files are `version: 1`; package `schemaVersion: 1`.
- All new JSON Schemas: draft 2020-12, `$id: https://sap-nexus-agent.local/schemas/<file>`, `additionalProperties: false` at every object.
- Hash convention: reuse `semantic_planning.snapshot.canonical_json_bytes`; ids are `"sha256:" + hexdigest`.
- Source lists sorted lexicographically by logical path; emitted JSON: `json.dumps(..., sort_keys=True, ensure_ascii=False, indent=2)` + one trailing newline.
- Tests resolve repo root as `REPO_ROOT = Path(__file__).resolve().parents[2]`, schemas via `REPO_ROOT / "schemas"`, run with `PYTHONPATH=agent`.
- Temp-fixture tests use `tmp_path`; they never mutate tracked ontology files.
- Every task ends with its own commit on the bound branch; never push.

---

### Task 1: Package skeleton and frozen contracts

**Files:**
- Create: `agent/sap_nexus_agent/semantic_release/__init__.py`
- Create: `agent/sap_nexus_agent/semantic_release/contracts.py`
- Test: `agent/tests/test_semantic_release_contracts.py`

**Interfaces:**
- Produces: frozen dataclasses `ReleaseSource(path: str, document_version: int, digest: str, role: str)`, `SemanticReleasePackage(schema_version: int, registry_snapshot_id: str, semantic_snapshot_id: str, compiler_version: str, operator_implementation_version: Mapping[str,str], sources: tuple[ReleaseSource,...], business_validity: Mapping[str,Any])` with `to_dict()` emitting camelCase keys (`schemaVersion`, `registrySnapshotId`, `semanticSnapshotId`, `compilerVersion`, `operatorImplementationVersion`, `sources[{path,documentVersion,digest,role}]`, `businessValidity`); `StructuralValidationReport(valid: bool, issues: tuple[SemanticReleaseIssue,...])`, `BusinessValidityReport(entries: tuple[BusinessValidityEntry,...])`, `SemanticReleaseIssue(path: str, code: str, message: str)`, `BusinessValidityEntry(definition_id: str, declared_status: str, state: str)`; closed tuple of structural codes `STRUCTURAL_ISSUE_CODES`.

- [x] **Step 1: Write the failing test**

```python
# agent/tests/test_semantic_release_contracts.py
from sap_nexus_agent.semantic_release.contracts import (
    ReleaseSource, SemanticReleasePackage, StructuralValidationReport,
    BusinessValidityReport, SemanticReleaseIssue, STRUCTURAL_ISSUE_CODES,
)

def test_release_source_and_package_to_dict_camelcase():
    pkg = SemanticReleasePackage(
        schema_version=1,
        registry_snapshot_id="sha256:aaa",
        semantic_snapshot_id="sha256:bbb",
        compiler_version="0.1.0",
        operator_implementation_version={"select_fields": "0.1.0"},
        sources=(ReleaseSource("ontology/analysis-versions.yaml", 1, "sha256:c", "semantic"),),
        business_validity={"applicability": []},
    )
    d = pkg.to_dict()
    assert d == {
        "schemaVersion": 1,
        "registrySnapshotId": "sha256:aaa",
        "semanticSnapshotId": "sha256:bbb",
        "compilerVersion": "0.1.0",
        "operatorImplementationVersion": {"select_fields": "0.1.0"},
        "sources": [{"path": "ontology/analysis-versions.yaml",
                     "documentVersion": 1, "digest": "sha256:c", "role": "semantic"}],
        "businessValidity": {"applicability": []},
    }

def test_issue_codes_are_closed():
    expected = {"SR_SCHEMA_INVALID","SR_UNKNOWN_FIELD_REF","SR_UNKNOWN_FACT_TYPE",
                "SR_UNKNOWN_SEMANTIC_TYPE","SR_UNKNOWN_OPERATOR","SR_OPERATOR_NOT_IN_CLOSED_SET",
                "SR_UNKNOWN_DEFINITION_REF","SR_DIGEST_MISMATCH","SR_SNAPSHOT_ID_MISMATCH",
                "SR_DUPLICATE_SOURCE","SR_MANIFEST_VIOLATION"}
    assert set(STRUCTURAL_ISSUE_CODES) == expected

def test_reports_are_frozen():
    import pytest
    with pytest.raises(Exception):
        StructuralValidationReport(True, ()).valid = False
```

- [x] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=agent .venv/bin/python -m pytest agent/tests/test_semantic_release_contracts.py -v`
Expected: FAIL with ModuleNotFoundError `sap_nexus_agent.semantic_release`.

- [x] **Step 3: Implement**

`__init__.py` exports the public symbols re-exported from submodules added in later tasks (start with contracts re-export). `contracts.py` defines the five frozen dataclasses (`frozen=True`, Mapping fields accepted as-is; `to_dict` builds the camelCase document), and `STRUCTURAL_ISSUE_CODES` tuple in the order listed in the Design Doc §4.

- [x] **Step 4: Run test to verify it passes**

Run the same pytest command; expected PASS (3 tests).

- [x] **Step 5: Commit**

```bash
git add agent/sap_nexus_agent/semantic_release/ agent/tests/test_semantic_release_contracts.py
git commit -m "feat(semantic-release): add frozen package and validation contracts"
```

### Task 2: Versions asset + schema

**Files:**
- Create: `ontology/analysis-versions.yaml`
- Create: `schemas/analysis-versions.schema.json`
- Test: `agent/tests/test_semantic_release_assets.py`

**Interfaces:**
- Produces: asset constant `COMPILER_VERSION = "0.1.0"` and four operator implementation versions `"0.1.0"` (single source for later tasks' expected values).

- [x] **Step 1: Write failing tests** — valid file validates; missing/extra property and fifth operator rejected.

```python
# agent/tests/test_semantic_release_assets.py (created in this task, appended later)
import json
import jsonschema
import pytest
import yaml
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

def _schema(name):
    return json.loads((REPO_ROOT / "schemas" / name).read_text(encoding="utf-8"))

def _yaml(rel):
    return yaml.safe_load((REPO_ROOT / rel).read_text(encoding="utf-8"))

def test_analysis_versions_asset_validates():
    doc = _yaml("ontology/analysis-versions.yaml")
    jsonschema.validate(doc, _schema("analysis-versions.schema.json"))
    assert doc["compilerVersion"] == "0.1.0"
    assert set(doc["operatorImplementations"]) == {
        "select_fields", "filter_eq", "group_sum", "compare"}

@pytest.mark.parametrize("bad", [
    {"version": 1, "compilerVersion": "0.1.0"},  # missing operatorImplementations
    {"version": 1, "compilerVersion": "0.1.0",
     "operatorImplementations": {"select_fields": "0.1.0"}, "extra": 1},  # unknown prop
    {"version": 1, "compilerVersion": "0.1.0",
     "operatorImplementations": {"select_fields": "0.1.0", "filter_eq": "0.1.0",
                                 "group_sum": "0.1.0", "compare": "0.1.0",
                                 "fifth_op": "0.1.0"}},  # enum closed
])
def test_analysis_versions_rejects_bad_shapes(bad):
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, _schema("analysis-versions.schema.json"))
```

- [x] **Step 2: Run to verify fail** — schema file missing → FileNotFoundError.

- [x] **Step 3: Implement**
  - `ontology/analysis-versions.yaml`: exact content from Design Doc §2.5 (camelCase keys `compilerVersion`, `operatorImplementations`).
  - `schemas/analysis-versions.schema.json`: draft 2020-12 schema; required `version` (const 1), `compilerVersion` (semver-ish string pattern `^0\\.1\\.0$`), `operatorImplementations` object with `additionalProperties: false`, `required` exactly the four operator ids as properties (string), and no fifth key possible.

- [x] **Step 4: Run to verify pass** — 4 tests pass.

- [x] **Step 5: Commit** — `feat(semantic-release): add analysis version markers and schema`

### Task 3: Object types asset + schema

**Files:**
- Create: `ontology/object-types.yaml`; Create: `schemas/object-types.schema.json`; append tests to `test_semantic_release_assets.py`.

**Interfaces:**
- Produces: five entries from Design Doc §2.1 keyed `objectTypes[]` with fields `objectTypeId`, `semanticType`, `keyFields` (non-empty string array), `scopeFields` (string array).

- [x] **Step 1: Failing tests** — tracked file validates; every `semanticType` belongs to the ontology vocabulary (fixture vocabulary built from capability inputs/outputs semanticType values + fact-types valueTypes/factTypes fields — reuse the SAME vocabulary source as the existing `_validate_vocabulary_references` by importing its collector; if not importable, assert against the concrete five expected ids); unknown property rejected; duplicate objectTypeId rejected (`uniqueItems` on ids).

```python
def test_object_types_asset_validates_and_uses_ontology_vocabulary():
    doc = _yaml("ontology/object-types.yaml")
    jsonschema.validate(doc, _schema("object-types.schema.json"))
    allowed = {"sapnexus:MaterialNumber", "sapnexus:Plant", "sapnexus:Supplier",
               "sapnexus:PurchaseOrderNumber", "sapnexus:PurchaseOrderItem"}
    assert {o["semanticType"] for o in doc["objectTypes"]} <= allowed
    assert len({o["objectTypeId"] for o in doc["objectTypes"]}) == len(doc["objectTypes"])
```

- [x] **Step 2: Verify fail**; **Step 3: Implement** the YAML (Design Doc §2.1 content, camelCase) and strict schema (`objectTypeId` pattern `^sapnexus:[A-Za-z]+$`, keyField names pattern `^[a-z][a-zA-Z]*$`).
- [x] **Step 4: Verify pass**; **Step 5: Commit** `feat(semantic-release): add MM object-type catalog and schema`.

### Task 4: Fact-field allowlist asset + schema

**Files:**
- Create: `ontology/analysis-fact-fields.yaml`; Create: `schemas/analysis-fact-fields.schema.json`; append tests.

**Interfaces:**
- Produces: `allowlist[]` entries `{factTypeId, fields[{name, semanticType}]}` exactly matching Design Doc §2.2 triples.

- [x] **Step 1: Failing tests**
  - Tracked file validates; exactly the three fact type ids; every triple exists in `ontology/fact-types.yaml` v3:
```python
def test_allowlist_triples_exist_in_fact_catalog():
    doc = _yaml("ontology/analysis-fact-fields.yaml")
    facts = {f["factTypeId"]: f for f in _yaml("ontology/fact-types.yaml")["factTypes"]}
    for entry in doc["allowlist"]:
        catalog = facts[entry["factTypeId"]]
        catalog_fields = {f["name"]: f["semanticType"] for f in catalog["fields"]}
        for f in entry["fields"]:
            assert catalog_fields[f["name"]] == f["semanticType"]
    assert "mrpElementLines" not in {f["name"] for e in doc["allowlist"] for f in e["fields"]}
```
  - Bad-shape param tests: unknown fact type id still passes generic schema (refs are semantic, validated structurally in Task 8) but duplicate `(factTypeId, name)` pairs are rejected by `uniqueItems` on a `[factTypeId, name]` tuple via array `contains` — simplest: require unique field names within one entry using schema `uniqueItems` on field objects.
- [x] **Step 2: Verify fail**; **Step 3: Implement YAML + strict schema** (`fields` array `uniqueItems: true` on full object).
- [x] **Step 4: Verify pass**; **Step 5: Commit** `feat(semantic-release): add analysis Fact-field allowlist and schema`.

### Task 5: Operator catalog asset + schema

**Files:**
- Create: `ontology/analysis-operators.yaml`; Create: `schemas/analysis-operators.schema.json`; append tests.

- [x] **Step 1: Failing tests** — validates; ids equal closed four in fixed order; no `path`/`module`/`expression`/`code` properties anywhere (schema `additionalProperties:false` recursively makes this structural — add explicit test attempting `path: x` at operator and param level); each operator has `version` string, `params` array, `output.kind` in `{rows, groupedRows, comparison}`, `constraints` string array.
- [x] **Step 2: Verify fail**; **Step 3: Implement YAML (Design Doc §2.3, filled for all four operators) and schema** with operator id enum `[select_fields, filter_eq, group_sum, compare]`, `minItems:4, maxItems:4, uniqueItems:true` on operator ids; param `type` enum `[fieldRef, fieldRefList, typedLiteral, measureRef]`.
- [x] **Step 4: Verify pass**; **Step 5: Commit** `feat(semantic-release): add closed analysis operator catalog and schema`.

### Task 6: Definition applicability asset + schema (empty v1)

**Files:**
- Create: `ontology/definition-applicability.yaml`; Create: `schemas/definition-applicability.schema.json`; append tests.

- [x] **Step 1: Failing tests** — tracked file validates with `applicability: []`; schema for future entries: items require `definitionId` (pattern `^sapnexus:def\.[a-z0-9-]+$`), `status` enum `[grounded, proposed]`, `applicableScopes` array of strings; unknown property rejected; a hand-built valid entry validates in-memory.
- [x] **Step 2: Verify fail**; **Step 3: Implement** exact Design Doc §2.4 content plus strict schema; **Step 4: verify pass**; **Step 5: Commit** `feat(semantic-release): add empty definition applicability catalog and schema`.

### Task 7: SemanticRelease package schema

**Files:**
- Create: `schemas/semantic-release.schema.json`; Test: append to assets test module.

- [x] **Step 1: Failing tests** — minimal valid package doc validates; unknown top-level and nested unknown source property rejected; bad role enum (`role` ∈ `legacy|semantic`) rejected; id pattern `^sha256:[0-9a-f]{64}$` enforced.
- [x] **Step 2: Verify fail**; **Step 3: Implement strict schema** for Design Doc §3 document including `sources` item `required [path, documentVersion, digest, role]`, `businessValidity.applicability` array reusing the applicability item shape via `$defs` (duplicate minimal def or `$ref` to a shared fragment — keep the package schema self-contained).
- [x] **Step 4: Verify pass**; **Step 5: Commit** `feat(semantic-release): add SemanticRelease v1 package schema`.

### Task 8: Asset loading manifest and structural validation

**Files:**
- Create: `agent/sap_nexus_agent/semantic_release/assets.py`
- Create: `agent/sap_nexus_agent/semantic_release/validation.py`
- Test: `agent/tests/test_semantic_release_validation.py`

**Interfaces:**
- Consumes: `load_yaml_mapping` from `semantic_planning.loader`; schemas dir resolved from repo root.
- Produces:
  - `SEMANTIC_SOURCE_MANIFEST: tuple[tuple[str, str], ...]` — ordered tuples `(logical_path, role)` for the eight semantic-role inputs: `ontology/analysis-fact-fields.yaml`, `ontology/analysis-operators.yaml`, `ontology/analysis-versions.yaml`, `ontology/definition-applicability.yaml`, `ontology/object-types.yaml`, `ontology/definitions.yaml`, `ontology/object-links.yaml`, `ontology/business-rules.yaml` (builder sorts lexicographically; manifest order is irrelevant but list all eight).
  - `load_release_assets(repo_root: Path) -> dict[str, dict]` keyed by logical path.
  - `validate_structure(package_dict, assets, legacy_sources) -> StructuralValidationReport` implementing issue codes: schema validation (`SR_SCHEMA_INVALID`, one issue per json schema error path), field/fact/semantic-type refs (`SR_UNKNOWN_FIELD_REF`/`SR_UNKNOWN_FACT_TYPE`/`SR_UNKNOWN_SEMANTIC_TYPE` against fact-types catalog + capability-declared semantic types), operator closed set (`SR_UNKNOWN_OPERATOR`, `SR_OPERATOR_NOT_IN_CLOSED_SET`), applicability definition refs against definitions.yaml ids (`SR_UNKNOWN_DEFINITION_REF`), duplicate paths (`SR_DUPLICATE_SOURCE`), per-source digest recomputation (`SR_DIGEST_MISMATCH`), legacy id match (`SR_SNAPSHOT_ID_MISMATCH`), manifest violation when a semantic-role path is absent/unknown (`SR_MANIFEST_VIOLATION`).

- [x] **Step 1: Failing tests** — one test per issue code built on `tmp_path` fixtures (minimal copy of real assets mutated per failure), plus a happy-path test validating a package dict the builder will produce in Task 10 (construct minimally here). Each assertion checks `report.valid is False` and the exact code appears once.
- [x] **Step 2: Verify fail** (module missing).
- [x] **Step 3: Implement**
  - Vocabulary collector: gather `semanticType` from all capability `inputs`/`outputs` of `registry/capabilities.yaml`, plus fact-type field `semanticType`s and valueType `id`s of `ontology/fact-types.yaml` — this is exactly the ontology vocabulary the existing contract validation uses; do not include bare matcher ids from semantic-types.yaml.
  - `jsonschema.validate` per document against its schema by file basename map.
  - Digest recompute via `canonical_json_bytes(document)` and the same `sha256:` prefix helper used by `snapshot.py` (import, do not duplicate).
- [x] **Step 4: Verify pass**; **Step 5: Commit** `feat(semantic-release): validate release assets and package structure`.

### Task 9: Business validity assessment

**Files:**
- `agent/sap_nexus_agent/semantic_release/validation.py` (add `assess_business_validity(assets) -> BusinessValidityReport`); test append.

- [x] **Step 1: Failing tests** — empty applicability → empty report; temp asset with one `grounded` ref to an existing grounded definition id → entry state `grounded`; `proposed` ref → `not_grounded`; ref to a grounded id but declared `proposed` → `not_grounded` (declaration controls).
- [x] **Step 2: Verify fail**; **Step 3: Implement** by joining applicability declarations to definitions.yaml statuses; structural existence is Task 8's job.
- [x] **Step 4: Verify pass**; **Step 5: Commit** `feat(semantic-release): separate business validity assessment`.

### Task 10: Builder assembly and semantic snapshot id

**Files:**
- Create: `agent/sap_nexus_agent/semantic_release/builder.py`; update `__init__.py` exports; Test: `agent/tests/test_semantic_release_builder.py`.

**Interfaces:**
- Produces: `build_semantic_release(repo_root: Path) -> SemanticReleasePackage`.
  - Loads legacy sources via `load_semantic_sources(repo_root)` and `build_semantic_contracts(sources)`; on invalid legacy report raises `RuntimeError` naming the first issues (never mask drift).
  - Legacy four + semantic-types digest rows: reuse `contract.snapshot.sources` entries (`path`, `documentVersion`, `digest`) with `role="legacy"`; note legacy paths use registry/ontology logical paths exactly as `documents_by_path()` emits.
  - Semantic rows: eight manifest documents, each `version` field, digest, `role="semantic"`.
  - `semanticSnapshotId = "sha256:" + sha256(canonical_json_bytes({"sources": [sorted semantic+legacy rows as {path,documentVersion,digest,role}], "compilerVersion": ..., "operatorImplementationVersion": {...}}))`.
  - `businessValidity = {"applicability": [...]}` from `assess_business_validity`, each item `{definitionId, declaredStatus, state}`.
  - Structural validation runs on the assembled dict; invalid raises `RuntimeError` listing issues.

- [x] **Step 1: Failing tests**
```python
def test_build_package_happy_path():
    pkg = build_semantic_release(REPO_ROOT)
    d = pkg.to_dict()
    assert d["schemaVersion"] == 1
    assert d["registrySnapshotId"].startswith("sha256:")
    assert d["semanticSnapshotId"].startswith("sha256:")
    assert {s["role"] for s in d["sources"]} == {"legacy", "semantic"}
    assert len([s for s in d["sources"] if s["role"] == "legacy"]) == 5
    assert d["businessValidity"] == {"applicability": []}

def test_build_is_byte_deterministic():
    a = build_semantic_release(REPO_ROOT).to_dict()
    b = build_semantic_release(REPO_ROOT).to_dict()
    assert canonical_json_bytes(a) == canonical_json_bytes(b)
```
- [x] **Step 2: Verify fail**; **Step 3: Implement** per interface; **Step 4: verify pass**; **Step 5: Commit** `feat(semantic-release): assemble deterministic SemanticRelease package`.

### Task 11: Determinism, sensitivity, insulation, tamper tests

**Files:**
- Test: `agent/tests/test_semantic_release_properties.py` (uses `tmp_path` copies of the minimal required repo files; helper `_mini_repo(tmp_path)` materializes the five new assets, three read-only ontology docs, and the five legacy documents by copying the tracked files, so mutations never touch the working tree).

- [x] **Step 1–2: Failing tests first**
  - Different cwd (`monkeypatch.chdir`) and reversed manifest enumeration → identical `semanticSnapshotId` and identical emitted bytes.
  - Parameterized mutation of each of: object-types, allowlist (one field), operators (one constraint), applicability (add temp entry), versions (`compilerVersion`), definitions.yaml statement, object-links.yaml, business-rules.yaml → changed `semanticSnapshotId` AND changed that source's digest; legacy `registrySnapshotId` unchanged for mutations to the eight semantic files.
  - Touch a non-manifest file (`tmp_path/"ontology/random.yaml"`) → unchanged id.
  - Tamper one source digest in the assembled dict → `validate_structure` reports `SR_DIGEST_MISMATCH`; tamper `registrySnapshotId` → `SR_SNAPSHOT_ID_MISMATCH`.
  - Legacy compatibility: build legacy snapshot from pristine files before/after removing the five new asset files → identical id (assets are not legacy inputs).
- [x] **Step 3: minimal implementation adjustments** if any non-determinism appears (sorting gaps); otherwise no production change.
- [x] **Step 4: all pass**; **Step 5: Commit** `test(semantic-release): pin determinism, sensitivity, insulation, tamper behavior`.

### Task 12: Build/check script and generated artifact

**Files:**
- Create: `scripts/build-semantic-release.py`
- Generate: `ontology/generated/semantic-release.json` (tracked)
- Test: `agent/tests/test_build_semantic_release_script.py`

**Interfaces:** mirrors `scripts/build-ontology-bundle.py`: no args regenerate; `--check` in-memory rebuild compares bytes to the committed file, prints `OUT_OF_SYNC ...` lines and exits 1; usage error exits 2; check is read-only.

- [x] **Step 1: Failing tests** — subprocess tests like existing script tests: run `--check` on synced repo → exit 0 + message; corrupt the generated file in `tmp_path` copy → exit 1 with OUT_OF_SYNC; bad arg → exit 2; after `--check`, `stat` mtime/size unchanged on the real file; `--check` performs no network (no monkeypatch needed — code path imports nothing networked).
- [x] **Step 2: Verify fail** (script missing).
- [x] **Step 3: Implement** script (REPO_ROOT bootstrap identical to bundle script; atomic write via temp file + `os.replace`; fixed json emission with trailing newline); then run it once to generate the artifact.
- [x] **Step 4: Verify pass**; **Step 5: Commit** script + generated file: `feat(semantic-release): add build/check CLI and generated v1 package`.

### Task 13: Legacy regression and project verification gates

**Files:** none new; tasks.md checkoff evidence recorded in commit body.

- [x] **Step 1: Run legacy compiler/planning suites**
  - `PYTHONPATH=agent .venv/bin/python -m pytest agent/tests/test_semantic_planning_contract.py agent/tests/test_semantic_planning_v2.py agent/tests/test_planner_plan_compiler_v2.py agent/tests/test_derived_dependencies.py agent/tests/test_contract_files.py agent/tests/test_ontology_codegen.py agent/tests/test_evidence_grounding.py agent/tests/test_impact_analysis.py agent/tests/test_constraint_runtime.py -q` → all pass.
- [x] **Step 2: Run bundle and release checks**
  - `PYTHONPATH=agent .venv/bin/python scripts/build-ontology-bundle.py --check` → in sync.
  - `PYTHONPATH=agent .venv/bin/python scripts/build-semantic-release.py --check` → in sync.
  - `PYTHONPATH=agent .venv/bin/python scripts/validate-evidence-grounding.py` → passes.
- [x] **Step 3: Run OpenSpec validation**
  - `openspec validate semantic-release-asset-pipeline --strict` → valid; record the pre-existing 16 archived-spec warnings as unrelated (do not edit tracked specs).
- [x] **Step 4: Commit tasks.md checkoffs** — tick all 23 boxes in `openspec/changes/semantic-release-asset-pipeline/tasks.md` mapping each to the task that delivered it, commit: `chore(semantic-release): check off C1 tasks with verification evidence` with the command outputs summarized in the body.

## Self-review

- Spec coverage: package contract (T1,T7), dual binding (T10,T11), asset source set (T2–T6,T10), content addressing/change sensitivity/determinism (T10,T11), operator closure (T5), two-layer validation (T8,T9), build/check entry (T12), legacy compatibility (T11,T13). All seven requirements mapped.
- Q1/Q-style scenarios in the spec map: byte-identical rebuild (T11), per-source change (T11), outsider insulation (T11), unknown refs (T8), digest/id mismatch (T8,T11), proposed-definition state (T9), read-only offline check (T12).
- Type consistency: `build_semantic_release` returns `SemanticReleasePackage`; validation takes package dict + assets; reports use contracts from T1 throughout.
- Open follow-ups (C2-side; not built here): compiler/operator digest replacement of version markers, package consumption — explicitly out of this change.

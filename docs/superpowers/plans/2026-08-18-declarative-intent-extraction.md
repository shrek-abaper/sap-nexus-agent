---
change: declarative-intent-extraction
design-doc: docs/superpowers/specs/2026-08-18-declarative-intent-extraction-design.md
base-ref: 2d4af9451ab1516a775de367d5b8bf347136eee2
---

# Declarative Intent Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the hardcoded rule-path intent extraction (`intent.py` keyword sets/builders, `pr_intent.py`, sticky dispatch in `llm_intent.py`) with registry declarations plus one generic extraction engine, under strict byte-parity, and delete the legacy path at the end.

**Architecture:** Capabilities gain a capability-level `intent` block (keywords, CLARIFY templates) and per-input `extraction` blocks (ordered matchers, priority, exclusion, conditions). Shared concept matchers live in `registry/semantic-types.yaml`. A new engine module (`agent/sap_nexus_agent/extraction/`) interprets declarations with zero capability branches; a temporary per-capability seam in `parse_intent`/`resolve_with_context` migrates PR -> Inventory -> PO, each as a standalone commit, guarded by a frozen differential parity harness.

**Tech Stack:** Python 3.12 (agent), PyYAML, jsonschema, pytest; Java 17 / Gradle (gateway test only); OpenSpec change artifacts.

**Spec:** `docs/superpowers/specs/2026-08-18-declarative-intent-extraction-design.md` (technical design) and `openspec/changes/declarative-intent-extraction/` (proposal.md, design.md, specs/*/spec.md, tasks.md). Read both before starting; this plan argues from them.

## Global Constraints

- Strict parity: decisions, parameters, missing lists, clarification text, ambiguity
  flags, and matched-intent sets MUST be byte-identical across the switch. Existing
  agent tests (baseline: 1145 passed) and all eval cases MUST stay green without
  modifying their expectations. Sanctioned deviations are listed in
  "Design Reconciliations" below - nothing else may drift.
- Migration order: PR (`MM.PR.CreateDraft`) -> Inventory (`MM.Inventory.GetAvailability`)
  -> PO (`MM.PurchaseOrder.GetList`). Single-turn and sticky are migrated together per
  capability. Each migration step is a standalone commit.
- Matcher DSL: kinds `keyword` / `regex` / `semanticType` only. Matcher attributes:
  `pattern`, `value` (keyword constant), `ref` (semanticType), `ignoreCase`, `scan`
  (`first` | `all`). Input-level `extraction` attributes: `matchers`, `priority`,
  `excludes`, `resolver` (`date`|`quantity`|`text`), `when`, `requiredWhen`,
  `reaskSuspect`. No new kinds, no capability branches in the engine.
- READ capabilities must not call `BAPI_TRANSACTION_COMMIT`/`ROLLBACK`; the SAP WRITE
  path is not touched by this change.
- Gateway must remain indifferent to extraction metadata (verified by a gateway test).
- Never commit `.env`, credentials, or tokens.
- Frontend is untouched. Do NOT run `npm --prefix frontend run verify` (no frontend
  files change; run it only if a frontend file was accidentally modified - that would
  be a plan violation to fix, not to verify).
- All commands run from the repo root
  `/home/shrek/projects/GitHub_Projects/sap-nexus-agent` unless stated otherwise.
  Python is `.venv/bin/python`.
- Verification commands (use the ones each task names, not the full suite):
  - Registry contract: `.venv/bin/python scripts/validate-registry-contract.py registry/capabilities.yaml`
  - Agent tests: `.venv/bin/python -m pytest agent/tests -q` (or targeted file/test)
  - Call-plan eval + suite: `PYTHONPATH=agent scripts/verify-agent-callplan-evidence.sh`
  - Gateway: `scripts/comet-verify-gateway.sh`
  - OpenSpec: `openspec list --json && openspec validate --all --strict`

## Design Reconciliations (read first)

The design doc's DSL as literally written cannot reproduce legacy behavior in five
places. These reconciliations are the binding interpretation for this plan; each is
the minimal extension that keeps every existing test and eval green (which the delta
spec's "Behavioral parity" requirement mandates):

1. **`triggerKeywords` added to the intent block.** Legacy trigger sets differ from
   the primary/weak ambiguity tables: inventory triggers on `有没有` (a weak keyword);
   PO triggers on `订单` and boundary-aware `PO` (both weak); `采购` is weak for PO/PR
   and never triggers; PR's trigger list (`PR_CREATE_KEYWORDS`, 7 entries) lacks
   `创建采购` while its ambiguity primary list (`PR_CREATE_PRIMARY_KEYWORDS`, 8 entries)
   has it. `weakKeywords` still never triggers by itself (spec scenario preserved:
   an utterance containing only `采购` triggers nothing and is flagged ambiguous).
   `triggerKeywords` defaults to `primaryKeywords` when absent. Ambiguity counting
   and sticky new-turn detection use `primaryKeywords`/`weakKeywords` only.
2. **`clarifyPrompt` lives at capability level** (`intent.clarifyPrompt.<locale>`),
   not inside a single input. Design §1.4 already describes cases as exact
   missing-set matches spanning inputs and `fieldNames` as capability-level, so a
   capability-level prompt is the faithful shape. PO's virtual `filter` missing name
   is only expressible there.
3. **`requireAny` group requiredness.** PO has no required inputs; legacy synthesizes
   `missing_parameters=["filter"]` when no filter was extracted. Expressed as
   `intent.requireAny: {inputs: [...], missingName: filter}` - engine-generic
   any-of requiredness, not a PO branch.
4. **`toUpperCase` split into `toUpperCaseCompare` / `toUpperCaseOutput`.** Inventory
   material compares uppercased but returns the original token; PR unit and
   purchasing group return uppercased values. One boolean cannot express both.
   `toUpperCaseCompare` also governs `excludes` value comparison (inventory material
   excludes plant/unit values uppercased; PO number excludes exactly).
5. **Sticky non-inventory clarification text changes (sanctioned micro-deviation).**
   Legacy sticky CLARIFY for PR uses the generic `请提供以下参数：{names}。`
   (`llm_intent._clarification_for`); the declaration renders `请提供: 物料编号, ...`
   No test or eval pins the legacy sticky text. The parity harness marks these rows
   `clarification_strict: false` during differential mode; decision, capability,
   parameters, and missing stay byte-identical. Sticky inventory texts coincide
   exactly and stay strict everywhere else.
6. **`agent/tests/test_semantic_planning_contract.py::test_loads_exactly_four_snapshot_sources`**
   is updated to five sources. Task 2.1 of the change explicitly requires the
   snapshot id to cover `registry/semantic-types.yaml`; this existing test pins the
   old four-path list and must move with the contract (this is the only existing
   test this plan modifies).

## File Structure

New files:

- `schemas/extraction-declaration.schema.json` - JSON Schema for capability intent
  blocks and per-input extraction declarations (Task 1).
- `schemas/semantic-type-catalog.schema.json` - JSON Schema for the catalog (Task 2).
- `registry/semantic-types.yaml` - shared semantic-type matcher catalog (Task 3).
- `agent/sap_nexus_agent/extraction/__init__.py` - package exports (Task 8).
- `agent/sap_nexus_agent/extraction/resolvers.py` - `date`/`quantity`/`text` value
  resolvers (Task 9).
- `agent/sap_nexus_agent/extraction/engine.py` - trigger scan, slot extraction,
  missing computation, CLARIFY rendering, full declared parse + sticky (Task 10).
- `agent/sap_nexus_agent/extraction/clarify.py` - deterministic template rendering +
  optional LLM rephrase with closed-set check (Tasks 10, 17).
- `agent/tests/fixtures/parity/{pr,inventory,po}.yaml` - frozen fixture tables
  (Task 11).
- `agent/tests/legacy_intent_reference.py` - frozen copy of the pre-change legacy
  parse/sticky logic for differential mode; deleted in Task 18 (Task 11).
- `agent/tests/test_extraction_parity.py` - differential + frozen parity harness
  (Task 11).
- `agent/tests/test_extraction_engine.py` - engine unit tests (Task 10).
- `agent/tests/test_extraction_declarations.py` - declaration/schema/validator
  acceptance tests over the real registry (Tasks 1-5).
- `agent/tests/test_clarify_rendering.py` - CLARIFY rendering + LLM rephrase tests
  (Tasks 16-17).
- `services/gateway/core/src/test/java/com/sapnexus/gateway/registry/ExtractionMetadataIndifferenceTest.java`
  (Task 6).

Modified files:

- `scripts/validate_registry_contract.py` - extraction + catalog validation rules
  (Task 4).
- `registry/capabilities.yaml` - three capabilities gain `intent` blocks and input
  `extraction` blocks (Task 5).
- `agent/sap_nexus_agent/registry_loader.py` - declaration dataclasses + atomic
  catalog load (Task 8).
- `agent/sap_nexus_agent/semantic_planning/contracts.py`, `loader.py` - snapshot
  covers the catalog (Task 8).
- `agent/sap_nexus_agent/intent.py` - migration seam, then legacy deletion
  (Tasks 12-18).
- `agent/sap_nexus_agent/llm_intent.py` - sticky seam, then `_extract_params_for`/
  `_PRIMARY_KEYWORD_SETS`/`_clarification_for` removal (Tasks 12, 16, 18).
- `agent/sap_nexus_agent/pr_intent.py` - DELETED in Task 18.
- `README.md` / `docs/` rule-path references (Task 21).

---

### Task 1: Extraction declaration JSON Schema  (tasks.md 1.1)

**Files:**
- Create: `schemas/extraction-declaration.schema.json`
- Test: `agent/tests/test_extraction_declarations.py`

**Interfaces:**
- Produces: JSON Schema id `urn:sap-nexus:extraction-declaration:v1`. Validates a
  capability-level object `{intent: {...}}` (the schema validates the `intent` value;
  the capabilities.yaml integration is checked by the validator in Task 4). Consumed
  by Task 4 (validator mirrors it) and Task 5 (real registry declarations).

- [ ] **Step 1: Write the failing schema test**

Create `agent/tests/test_extraction_declarations.py`:

```python
"""Schema + validator acceptance tests for extraction declarations."""
from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "schemas" / "extraction-declaration.schema.json"

VALID_INTENT = {
    "intentName": "pr_create",
    "primaryKeywords": ["采购申请", "创建采购"],
    "weakKeywords": ["采购"],
    "triggerKeywords": ["采购申请"],
    "fieldNames": {"zh-CN": {"material": "物料编号", "plant": "工厂"}},
    "requireAny": {"inputs": ["poNumber", "vendor"], "missingName": "filter"},
    "clarifyPrompt": {
        "zh-CN": {
            "cases": [{"missing": ["material"], "text": "请提供物料编号。"}],
            "fallback": {"template": "请提供: {fields}"},
        }
    },
}

VALID_INPUT_EXTRACTION = {
    "matchers": [
        {"kind": "keyword", "pattern": "间采|账号分配\\s*[Kk]", "value": "K"},
        {"kind": "regex", "pattern": "成本中心\\s*(\\d+)"},
        {"kind": "semanticType", "ref": "MaterialNumber"},
    ],
    "priority": 10,
    "excludes": ["plant", "unit"],
    "resolver": "text",
    "when": {"field": "acct_assgn_cat", "equals": "K"},
    "requiredWhen": {"field": "acct_assgn_cat", "equals": "K"},
    "reaskSuspect": True,
}


def _load(name: str) -> dict:
    return json.loads((REPO_ROOT / "schemas" / name).read_text(encoding="utf-8"))


def test_valid_intent_block_passes():
    schema = _load("extraction-declaration.schema.json")
    jsonschema.validate(VALID_INTENT, schema)


@pytest.mark.parametrize("mutation", [
    {"intentName": 123},                                # intentName must be string
    {"primaryKeywords": []},                            # at least one primary
    {"primaryKeywords": "库存"},                        # must be a list
    {"weakKeywords": ["采购", 5]},                      # entries are strings
    {"requireAny": {"inputs": [], "missingName": "x"}}, # non-empty inputs
    {"clarifyPrompt": {"zh-CN": {"cases": "nope"}}},    # cases must be a list
])
def test_invalid_intent_block_rejected(mutation):
    schema = _load("extraction-declaration.schema.json")
    payload = {**VALID_INTENT, **mutation}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)


def test_valid_input_extraction_passes():
    schema = _load("extraction-declaration.schema.json")
    resolver = schema["definitions"]["inputExtraction"]
    jsonschema.validate(VALID_INPUT_EXTRACTION, resolver)


@pytest.mark.parametrize("mutation", [
    {"matchers": [{"kind": "embedding", "pattern": "x"}]},   # unknown kind
    {"matchers": [{"kind": "regex"}]},                       # regex needs pattern
    {"matchers": [{"kind": "keyword", "pattern": "x"}]},     # keyword needs value
    {"matchers": [{"kind": "semanticType", "pattern": "x"}]},# semanticType needs ref
    {"resolver": "decimal"},                                 # unknown resolver
    {"when": {"field": "x"}},                                # equals required
    {"scan": "every"},                                       # scan: first|all (matcher-level)
])
def test_invalid_input_extraction_rejected(mutation):
    schema = _load("extraction-declaration.schema.json")
    resolver = schema["definitions"]["inputExtraction"]
    payload = {**VALID_INPUT_EXTRACTION, **mutation}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, resolver)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest agent/tests/test_extraction_declarations.py -q`
Expected: FAIL / ERROR (`schemas/extraction-declaration.schema.json` does not exist).

- [ ] **Step 3: Write the schema**

Create `schemas/extraction-declaration.schema.json`. Structure (abridged to the
load-bearing parts - write it fully, no `TBD`):

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "urn:sap-nexus:extraction-declaration:v1",
  "title": "Capability intent extraction declaration",
  "type": "object",
  "additionalProperties": false,
  "required": ["intentName", "primaryKeywords"],
  "properties": {
    "intentName": {"type": "string", "minLength": 1},
    "primaryKeywords": {"type": "array", "minItems": 1, "items": {"type": "string", "minLength": 1}},
    "weakKeywords": {"type": "array", "items": {"type": "string", "minLength": 1}},
    "triggerKeywords": {"type": "array", "minItems": 1, "items": {"type": "string", "minLength": 1}},
    "fieldNames": {
      "type": "object",
      "minProperties": 1,
      "additionalProperties": {
        "type": "object", "minProperties": 1,
        "additionalProperties": {"type": "string", "minLength": 1}
      }
    },
    "requireAny": {
      "type": "object", "additionalProperties": false,
      "required": ["inputs", "missingName"],
      "properties": {
        "inputs": {"type": "array", "minItems": 1, "items": {"type": "string"}},
        "missingName": {"type": "string", "minLength": 1}
      }
    },
    "clarifyPrompt": {
      "type": "object",
      "minProperties": 1,
      "additionalProperties": {"$ref": "#/$defs/localePrompt"}
    }
  },
  "$defs": {
    "localePrompt": {
      "type": "object", "additionalProperties": false,
      "properties": {
        "cases": {
          "type": "array",
          "items": {
            "type": "object", "additionalProperties": false,
            "required": ["missing", "text"],
            "properties": {
              "missing": {"type": "array", "minItems": 1, "items": {"type": "string"}},
              "text": {"type": "string", "minLength": 1}
            }
          }
        },
        "fallback": {
          "type": "object", "additionalProperties": false,
          "required": ["template"],
          "properties": {"template": {"type": "string", "minLength": 1}}
        }
      }
    },
    "matcher": {
      "type": "object",
      "required": ["kind"],
      "properties": {
        "kind": {"enum": ["keyword", "regex", "semanticType"]},
        "pattern": {"type": "string", "minLength": 1},
        "value": {"type": "string", "minLength": 1},
        "ref": {"type": "string", "minLength": 1},
        "ignoreCase": {"type": "boolean"},
        "scan": {"enum": ["first", "all"]}
      },
      "allOf": [
        {"if": {"properties": {"kind": {"const": "keyword"}}},
         "then": {"required": ["pattern", "value"]}},
        {"if": {"properties": {"kind": {"const": "regex"}}},
         "then": {"required": ["pattern"]}},
        {"if": {"properties": {"kind": {"const": "semanticType"}}},
         "then": {"required": ["ref"]}}
      ]
    },
    "condition": {
      "type": "object", "additionalProperties": false,
      "required": ["field", "equals"],
      "properties": {"field": {"type": "string", "minLength": 1}, "equals": {"type": "string"}}
    },
    "inputExtraction": {
      "type": "object",
      "additionalProperties": false,
      "required": ["matchers"],
      "properties": {
        "matchers": {"type": "array", "minItems": 1, "items": {"$ref": "#/$defs/matcher"}},
        "priority": {"type": "integer"},
        "excludes": {"type": "array", "items": {"type": "string"}},
        "resolver": {"enum": ["date", "quantity", "text"]},
        "when": {"$ref": "#/$defs/condition"},
        "requiredWhen": {"$ref": "#/$defs/condition"},
        "reaskSuspect": {"type": "boolean"}
      }
    }
  }
}
```

Note: the schema uses `$defs` (2020-12) and also exposes
`definitions.inputExtraction` by adding
`"definitions": {"inputExtraction": {"$ref": "#/$defs/inputExtraction"}}` at the
root so the test can validate a bare extraction object. JSON Schema keyword choice:
the repo's existing schemas (e.g. `schemas/capability.schema.json`) use draft 2020-12;
follow whichever draft the existing files declare if different.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest agent/tests/test_extraction_declarations.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add schemas/extraction-declaration.schema.json agent/tests/test_extraction_declarations.py
git commit -m "feat: JSON Schema for capability extraction declarations"
```

---

### Task 2: Semantic-type catalog JSON Schema  (tasks.md 1.2)

**Files:**
- Create: `schemas/semantic-type-catalog.schema.json`
- Test: `agent/tests/test_extraction_declarations.py` (append)

**Interfaces:**
- Produces: JSON Schema id `urn:sap-nexus:semantic-type-catalog:v1` validating the
  whole `registry/semantic-types.yaml` document: versioned root, `semanticTypes`
  list, each entry `id` + at least one matcher + `priority`; entry-level `filters`
  (`minLength`, `notIn`, `prefixBlacklist`, `toUpperCaseCompare`, `toUpperCaseOutput`).
  Matcher shape reuses Task 1's matcher definition (duplicate it inline; catalog
  entries use `id` instead of `ref`).

- [ ] **Step 1: Write the failing test** (append to `agent/tests/test_extraction_declarations.py`)

```python
VALID_CATALOG = {
    "version": 1,
    "semanticTypes": [
        {
            "id": "MaterialNumber",
            "priority": 10,
            "matchers": [
                {"kind": "regex", "pattern": "[A-Z0-9]+", "scan": "all"}
            ],
            "filters": {
                "minLength": 5,
                "notIn": ["RFCNAME"],
                "prefixBlacklist": ["BAPI_"],
                "toUpperCaseCompare": True,
                "toUpperCaseOutput": False,
            },
        }
    ],
}


def test_valid_catalog_passes():
    jsonschema.validate(VALID_CATALOG, _load("semantic-type-catalog.schema.json"))


@pytest.mark.parametrize("mutation", [
    {"version": 1},                                        # semanticTypes required
    {"semanticTypes": [{"id": "X"}]},                      # matcher + priority required
    {"semanticTypes": [{"id": "X", "priority": 1,
                        "matchers": [{"kind": "regex"}]}]},# pattern required
    {"semanticTypes": [{"id": "X", "priority": 1,
                        "matchers": [{"kind": "regex", "pattern": "x"}]},
                      {"id": "X", "priority": 2,
                        "matchers": [{"kind": "regex", "pattern": "y"}]}]},
                                                           # duplicate id -> Task 4 rejects;
                                                           # schema allows, validator owns it
    {"semanticTypes": [{"id": "X", "priority": 1,
                        "matchers": [{"kind": "regex", "pattern": "x"}],
                        "filters": {"minLength": "five"}}]},# minLength integer
])
def test_invalid_catalog_rejected(mutation):
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({**VALID_CATALOG, **mutation},
                            _load("semantic-type-catalog.schema.json"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest agent/tests/test_extraction_declarations.py -q`
Expected: FAIL (schema file missing)

- [ ] **Step 3: Write the schema**

Create `schemas/semantic-type-catalog.schema.json`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "urn:sap-nexus:semantic-type-catalog:v1",
  "title": "Semantic-type extraction catalog",
  "type": "object",
  "additionalProperties": false,
  "required": ["version", "semanticTypes"],
  "properties": {
    "version": {"type": "integer", "minimum": 1},
    "semanticTypes": {
      "type": "array",
      "minItems": 1,
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["id", "matchers", "priority"],
        "properties": {
          "id": {"type": "string", "minLength": 1},
          "description": {"type": "string"},
          "priority": {"type": "integer"},
          "matchers": {
            "type": "array", "minItems": 1,
            "items": {
              "type": "object", "required": ["kind"],
              "properties": {
                "kind": {"enum": ["keyword", "regex", "semanticType"]},
                "pattern": {"type": "string", "minLength": 1},
                "value": {"type": "string", "minLength": 1},
                "ref": {"type": "string", "minLength": 1},
                "ignoreCase": {"type": "boolean"},
                "scan": {"enum": ["first", "all"]}
              }
            }
          },
          "filters": {
            "type": "object", "additionalProperties": false,
            "properties": {
              "minLength": {"type": "integer", "minimum": 1},
              "notIn": {"type": "array", "items": {"type": "string"}},
              "prefixBlacklist": {"type": "array", "items": {"type": "string"}},
              "toUpperCaseCompare": {"type": "boolean"},
              "toUpperCaseOutput": {"type": "boolean"}
            }
          }
        }
      }
    }
  }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest agent/tests/test_extraction_declarations.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add schemas/semantic-type-catalog.schema.json agent/tests/test_extraction_declarations.py
git commit -m "feat: JSON Schema for the semantic-type extraction catalog"
```

---

### Task 3: Create the semantic-type catalog  (tasks.md 1.3)

**Files:**
- Create: `registry/semantic-types.yaml`
- Test: `agent/tests/test_extraction_declarations.py` (append)

**Interfaces:**
- Produces: catalog entries with ids `Plant`, `MaterialNumber`, `Quantity`, `Unit`,
  `Date`, `PurchasingGroup`, `Vendor`, `PONumber`. All patterns lifted verbatim from
  `agent/sap_nexus_agent/intent.py` / `pr_intent.py` constants (see table in the
  design doc §3). Consumed by Task 4 (reference resolution), Task 5 (declarations),
  Task 8 (loader), Task 10 (engine).

- [ ] **Step 1: Write the failing test** (append to `agent/tests/test_extraction_declarations.py`)

The test pins "lifted verbatim" mechanically: every catalog pattern must equal the
legacy compiled pattern source, so drift is caught at test time.

```python
import yaml

from sap_nexus_agent import intent as legacy_intent
from sap_nexus_agent import pr_intent as legacy_pr

CATALOG_PATH = REPO_ROOT / "registry" / "semantic-types.yaml"

EXPECTED_PATTERN_PARITY = {
    "Plant": [
        legacy_intent.PLANT_PATTERN.pattern,
        r"(?<!\d)([A-Z]\d{3}|\d{4})(?!\d)",
    ],
    "MaterialNumber": [legacy_intent.TOKEN_PATTERN.pattern],
    "Quantity": [legacy_pr.QUANTITY_PATTERN.pattern],
    "Unit": [legacy_pr.UNIT_PATTERN.pattern],
    "Date": [legacy_pr.DATE_PATTERN.pattern],
    "PurchasingGroup": [legacy_pr.PURCHASING_GROUP_PATTERN.pattern],
    "Vendor": [legacy_intent.PO_VENDOR_PATTERN.pattern],
    "PONumber": [legacy_intent.PO_NUMBER_PATTERN.pattern],
}


def _load_catalog() -> dict:
    return yaml.safe_load(CATALOG_PATH.read_text(encoding="utf-8"))


def test_catalog_matches_json_schema():
    jsonschema.validate(_load_catalog(), _load("semantic-type-catalog.schema.json"))


def test_catalog_patterns_are_lifted_verbatim_from_legacy_extractors():
    catalog = {e["id"]: e for e in _load_catalog()["semanticTypes"]}
    assert set(catalog) == set(EXPECTED_PATTERN_PARITY)
    for entry_id, patterns in EXPECTED_PATTERN_PARITY.items():
        assert [m["pattern"] for m in catalog[entry_id]["matchers"]] == patterns, entry_id


def test_material_filters_reproduce_legacy_guards():
    catalog = {e["id"]: e for e in _load_catalog()["semanticTypes"]}
    filters = catalog["MaterialNumber"]["filters"]
    assert filters == {
        "minLength": 5,             # legacy: len(token) > 4
        "notIn": ["RFCNAME"],       # legacy: excluded.update({"RFCNAME"})
        "prefixBlacklist": ["BAPI_"],
        "toUpperCaseCompare": True, # legacy: token.upper() in excluded
        "toUpperCaseOutput": False, # legacy returns the original token
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest agent/tests/test_extraction_declarations.py -q`
Expected: FAIL (`registry/semantic-types.yaml` missing)

- [ ] **Step 3: Write the catalog**

Create `registry/semantic-types.yaml`. In YAML single-quoted scalars a backslash is
literal - write patterns exactly as the Python source strings:

```yaml
version: 1
semanticTypes:
  - id: Plant
    description: SAP plant code - 工厂-prefixed form first, bare 4-char code fallback with lookaround guards
    priority: 20
    matchers:
      - kind: regex
        pattern: '(?:在\s*([A-Z]\d{3}|\d{4}))|(?:([A-Z]\d{3}|\d{4})\s*工厂)'
      - kind: regex
        pattern: '(?<!\d)([A-Z]\d{3}|\d{4})(?!\d)'
  - id: MaterialNumber
    description: Bare uppercase token scan with material guards
    priority: 10
    matchers:
      - kind: regex
        pattern: '(?<![A-Za-z0-9-])[A-Z0-9][A-Z0-9-]{1,39}(?![A-Za-z0-9-])'
        scan: all
    filters:
      minLength: 5
      notIn: ['RFCNAME']
      prefixBlacklist: ['BAPI_']
      toUpperCaseCompare: true
      toUpperCaseOutput: false
  - id: Quantity
    description: Numeric capture optionally followed by a unit token
    priority: 30
    matchers:
      - kind: regex
        pattern: '(\d+(?:\.\d+)?)\s*(?:EA|PC|KG|G|L|M)'
        ignoreCase: true
  - id: Unit
    description: Unit-of-measure token, uppercased on output
    priority: 25
    matchers:
      - kind: regex
        pattern: '\b(EA|PC|KG|G|L|M)\b'
        ignoreCase: true
    filters:
      toUpperCaseOutput: true
  - id: Date
    description: ISO date capture
    priority: 20
    matchers:
      - kind: regex
        pattern: '(\d{4}-\d{2}-\d{2})'
  - id: PurchasingGroup
    description: 采购组-prefixed code, uppercased on output
    priority: 15
    matchers:
      - kind: regex
        pattern: '采购组\s*([A-Za-z0-9]{1,3})'
    filters:
      toUpperCaseOutput: true
  - id: Vendor
    description: PO vendor number, 供应商-prefixed
    priority: 40
    matchers:
      - kind: regex
        pattern: '供应商\s*(\d+)'
  - id: PONumber
    description: 10-digit PO number, iterated so value exclusions can skip matches
    priority: 10
    matchers:
      - kind: regex
        pattern: '(?<!\d)(\d{10})(?!\d)'
        scan: all
```

Semantics notes that Tasks 4/8/10 implement (also written into the schema file's
`description` fields where useful):
- `scan: all` iterates every match and returns the first whose value passes filters
  and exclusions (reproduces `_extract_material` and `_extract_po_number` loops).
  Default `scan: first` returns the first regex match only.
- Regex value selection: the value is the first non-`None` capture group (covers
  `PLANT_PATTERN`'s two-alternative groups); if the pattern has no groups, the whole
  match.
- `Unit` here is the PR-shaped entry (case-insensitive, uppercased output, leftmost
  match). Inventory uses keyword-constant matchers instead (Task 5) because
  `_extract_unit` iterates unit values in list order (`EA` first) rather than taking
  the leftmost match, and is case-sensitive.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest agent/tests/test_extraction_declarations.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add registry/semantic-types.yaml agent/tests/test_extraction_declarations.py
git commit -m "feat: semantic-type extraction catalog lifted verbatim from legacy extractors"
```

---

### Task 4: Registry contract validator rules  (tasks.md 1.4)

**Files:**
- Modify: `scripts/validate_registry_contract.py`
- Test: `agent/tests/test_extraction_declarations.py` (append)

**Interfaces:**
- Consumes: Task 1/2 schemas, Task 3 catalog file layout.
- Produces: function
  `validate_extraction_declarations(contract: RegistryContract, catalog_entries: dict[str, dict], repo_root: Path) -> list[str]`
  (returns human-readable error strings, mirroring the module's existing style), and
  helpers `load_semantic_type_catalog(repo_root: Path) -> tuple[dict[str, dict], list[str]]`
  (returns entries-by-id plus errors; duplicate ids and file-level problems are
  errors) and `regex_backtracking_guard(pattern: str) -> str | None` (returns an
  error message or `None`). Wired into `validate_registry_contract()` so every
  invocation validates extraction declarations and the catalog.

- [ ] **Step 1: Write the failing tests** (append to `agent/tests/test_extraction_declarations.py`)

```python
from scripts.validate_registry_contract import (
    load_registry_contract,
    load_semantic_type_catalog,
    regex_backtracking_guard,
    validate_registry_contract,
)


def _capability_yaml(intent_block=None, extraction=None, inputs=None):
    """Minimal valid capability with optional extraction metadata."""
    base_inputs = inputs or [
        {"name": "material", "semanticType": "sapnexus:MaterialNumber",
         "required": True, "type": "string"},
    ]
    if extraction is not None:
        base_inputs[0]["extraction"] = extraction
    cap = {
        "capabilityId": "T.Capability.One", "name": "T", "description": "d",
        "status": "active", "kind": "Function", "domain": "T", "businessObject": "T",
        "ontologyIri": "sapnexus:T_Capability_One", "semanticType": "sapnexus:T_Fn",
        "executor": {"type": "JCO_RFC"},
        "executorBinding": {"type": "JCO_RFC", "bindingId": "test.read.binding"},
        "governance": {"sideEffect": "none", "requiresApproval": False,
                       "approvalPolicy": "not_required"},
        "inputs": base_inputs,
        "outputs": [{"name": "out", "semanticType": "sapnexus:Out", "type": "string"}],
    }
    if intent_block is not None:
        cap["intent"] = intent_block
    return {"version": 2, "capabilities": [cap]}


def _write_registry(tmp_path, doc):
    path = tmp_path / "capabilities.yaml"
    path.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
    return path


VALID_EXTRACTION = {
    "matchers": [{"kind": "semanticType", "ref": "Date"}],
    "resolver": "date",
}


def _valid_intent(**overrides):
    block = {
        "intentName": "t_one",
        "primaryKeywords": ["库存"],
        "clarifyPrompt": {
            "zh-CN": {
                "cases": [{"missing": ["material"], "text": "请提供物料。"}],
                "fallback": {"template": "请提供: {fields}"},
            }
        },
    }
    block.update(overrides)
    return block


def test_real_registry_validates_with_catalog(tmp_path):
    contract = load_registry_contract(REPO_ROOT / "registry" / "capabilities.yaml")
    errors = validate_registry_contract(contract, repo_root=REPO_ROOT)
    assert errors == []


def test_real_catalog_loads_without_errors():
    entries, errors = load_semantic_type_catalog(REPO_ROOT)
    assert errors == []
    assert set(entries) >= {"Plant", "MaterialNumber", "Quantity", "Unit",
                            "Date", "PurchasingGroup", "Vendor", "PONumber"}


def test_dangling_semantic_type_reference_rejected(tmp_path):
    doc = _capability_yaml(_valid_intent(), {"matchers": [{"kind": "semanticType", "ref": "Missing"}]})
    contract = load_registry_contract(_write_registry(tmp_path, doc))
    errors = validate_registry_contract(contract, repo_root=REPO_ROOT)
    assert any("semanticType" in e and "Missing" in e for e in errors)


def test_non_compiling_regex_rejected(tmp_path):
    doc = _capability_yaml(_valid_intent(), {"matchers": [{"kind": "regex", "pattern": "([unclosed"}]})
    contract = load_registry_contract(_write_registry(tmp_path, doc))
    errors = validate_registry_contract(contract, repo_root=REPO_ROOT)
    assert any("compile" in e for e in errors)


def test_catastrophic_backtracking_regex_rejected():
    assert regex_backtracking_guard("(a+)+$") is not None
    assert regex_backtracking_guard("a".ljust(300, "a")) is not None  # length guard
    assert regex_backtracking_guard(r"物料\s*([A-Za-z0-9\-/]+)") is None


def test_missing_clarify_locale_rejected(tmp_path):
    intent = _valid_intent(clarifyPrompt={"en-US": {"fallback": {"template": "provide {fields}"}}})
    doc = _capability_yaml(intent, VALID_EXTRACTION)
    contract = load_registry_contract(_write_registry(tmp_path, doc))
    errors = validate_registry_contract(contract, repo_root=REPO_ROOT)
    assert any("clarifyPrompt" in e and "zh-CN" in e for e in errors)


def test_weak_primary_keyword_overlap_rejected(tmp_path):
    intent = _valid_intent(weakKeywords=["库存"])
    doc = _capability_yaml(intent, VALID_EXTRACTION)
    contract = load_registry_contract(_write_registry(tmp_path, doc))
    errors = validate_registry_contract(contract, repo_root=REPO_ROOT)
    assert any("weakKeywords" in e for e in errors)


def test_when_references_undeclared_input_rejected(tmp_path):
    intent = _valid_intent()
    extraction = {"matchers": [{"kind": "regex", "pattern": "(\\d+)"}],
                  "when": {"field": "nonexistent", "equals": "K"}}
    doc = _capability_yaml(intent, extraction)
    contract = load_registry_contract(_write_registry(tmp_path, doc))
    errors = validate_registry_contract(contract, repo_root=REPO_ROOT)
    assert any("when" in e and "nonexistent" in e for e in errors)


def test_excludes_reference_undeclared_input_rejected(tmp_path):
    intent = _valid_intent()
    extraction = {"matchers": [{"kind": "semanticType", "ref": "Date"}],
                  "excludes": ["ghost"]}
    doc = _capability_yaml(intent, extraction)
    contract = load_registry_contract(_write_registry(tmp_path, doc))
    errors = validate_registry_contract(contract, repo_root=REPO_ROOT)
    assert any("excludes" in e and "ghost" in e for e in errors)
```

Note: `test_real_registry_validates_with_catalog` stays red until Task 5 adds the
declarations; mark the two "real registry" tests with
`@pytest.mark.xfail(reason="declarations land in tasks.md 1.5", strict=True)` inside
Task 4 and remove the marker in Task 5. Alternatively implement Task 5 first within
the same session - but keep the commits separate as ordered.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest agent/tests/test_extraction_declarations.py -q`
Expected: FAIL (`load_semantic_type_catalog` not importable)

- [ ] **Step 3: Implement the validator additions**

In `scripts/validate_registry_contract.py`:

```python
import re
import time

SUPPORTED_LOCALES = ("zh-CN",)
MAX_REGEX_LENGTH = 200
_NESTED_QUANTIFIER = re.compile(r"\((?:[^()]*[*+])[^()]*\)[*+{]")
_BACKTRACKING_SAMPLES = ("a" * 64, "a" * 64 + "!", "a" * 32 + "b", "0" * 64)
_SAMPLE_TIME_BUDGET_SECONDS = 0.05


def regex_backtracking_guard(pattern: str) -> str | None:
    """Compile + backtracking-safety guard (length, nested quantifiers, bounded sample timeout)."""
    if len(pattern) > MAX_REGEX_LENGTH:
        return f"regex exceeds length limit {MAX_REGEX_LENGTH}: {pattern[:60]!r}..."
    try:
        compiled = re.compile(pattern)
    except re.error as exc:
        return f"regex does not compile: {exc}"
    if _NESTED_QUANTIFIER.search(pattern):
        return f"regex contains nested quantifiers (backtracking risk): {pattern[:60]!r}"
    for sample in _BACKTRACKING_SAMPLES:
        started = time.perf_counter()
        compiled.search(sample)
        if time.perf_counter() - started > _SAMPLE_TIME_BUDGET_SECONDS:
            return f"regex exceeds sample timeout on input of length {len(sample)}: {pattern[:60]!r}"
    return None


def load_semantic_type_catalog(repo_root: Path) -> tuple[dict[str, dict], list[str]]:
    """Load registry/semantic-types.yaml -> (entries by id, errors)."""
    path = repo_root / "registry" / "semantic-types.yaml"
    if not path.exists():
        return {}, ["semantic-type catalog missing: registry/semantic-types.yaml"]
    import yaml
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        return {}, [f"semantic-type catalog unreadable: {exc}"]
    entries: dict[str, dict] = {}
    errors: list[str] = []
    for raw in (doc or {}).get("semanticTypes", []) or []:
        if not isinstance(raw, dict):
            errors.append("semantic-type catalog entry must be a mapping")
            continue
        entry_id = str(raw.get("id") or "")
        if not entry_id:
            errors.append("semantic-type catalog entry requires id")
        elif entry_id in entries:
            errors.append(f"duplicate semantic-type id: {entry_id}")
        else:
            entries[entry_id] = raw
    return entries, errors
```

Then `validate_extraction_declarations(contract, catalog_entries, repo_root)` walks
every capability: for each `intent` block validate via the Task 1 JSON Schema
(`jsonschema.Draft202012Validator(...).iter_errors`, prefix errors with the
capability id), check `weakKeywords ∩ primaryKeywords == ∅` (string equality),
validate every `semanticType.ref` against `catalog_entries`, compile+guard every
inline `pattern` (capability-level keywords and matchers, and every catalog entry's
matchers via `regex_backtracking_guard`), resolve `when`/`requiredWhen`/`excludes`
field names against the capability's declared input names, and check clarifyPrompt
locale completeness: for every locale in `SUPPORTED_LOCALES`, every
`required`/`requiredWhen` input name (plus `requireAny.missingName` when declared)
must be covered - covered means appearing in some `case.missing` of that locale or a
`fallback.template` existing for that locale. Finally call it from
`validate_registry_contract()`:

```python
    # inside validate_registry_contract(), after the existing per-capability loop:
    catalog_entries, catalog_errors = load_semantic_type_catalog(repo_root)
    errors.extend(catalog_errors)
    errors.extend(validate_extraction_declarations(contract, catalog_entries, repo_root))
```

- [ ] **Step 4: Run tests to verify they pass (except the two xfail-marked real-registry ones)**

Run: `.venv/bin/python -m pytest agent/tests/test_extraction_declarations.py -q`
Expected: PASS

Also run the existing validator suite for regressions:
`.venv/bin/python -m pytest agent/tests/test_registry_contract.py -q` - PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/validate_registry_contract.py agent/tests/test_extraction_declarations.py
git commit -m "feat: extraction declaration + catalog validation in registry contract validator"
```

---

### Task 5: Extraction declarations for the three capabilities  (tasks.md 1.5)

**Files:**
- Modify: `registry/capabilities.yaml`
- Test: `agent/tests/test_extraction_declarations.py` (remove xfail markers; append)

**Interfaces:**
- Produces: complete `intent` blocks + input `extraction` blocks for
  `MM.Inventory.GetAvailability`, `MM.PurchaseOrder.GetList`, `MM.PR.CreateDraft`
  with strict-parity values (patterns and strings copied verbatim from
  `intent.py` / `pr_intent.py`). Consumed by Tasks 8 and 10.

- [ ] **Step 1: Write the failing test** (append; and un-xfail the Task 4 real-registry tests)

```python
def _registry_intent_blocks() -> dict:
    doc = yaml.safe_load((REPO_ROOT / "registry" / "capabilities.yaml").read_text(encoding="utf-8"))
    return {c["capabilityId"]: c for c in doc["capabilities"]}


def test_inventory_declaration_parity_constants():
    cap = _registry_intent_blocks()["MM.Inventory.GetAvailability"]
    intent = cap["intent"]
    assert intent["intentName"] == "inventory_availability"
    assert intent["primaryKeywords"] == ["库存", "可用量", "可用库存", "还有多少"]
    assert intent["weakKeywords"] == ["有没有"]
    assert intent["triggerKeywords"] == ["库存", "可用量", "可用库存", "还有多少", "有没有"]
    inputs = {i["name"]: i for i in cap["inputs"]}
    assert inputs["material"]["extraction"]["excludes"] == ["plant", "unit"]
    assert inputs["material"]["extraction"]["reaskSuspect"] is True
    assert inputs["material"]["extraction"]["matchers"] == [{"kind": "semanticType", "ref": "MaterialNumber"}]
    assert inputs["plant"]["extraction"]["matchers"] == [{"kind": "semanticType", "ref": "Plant"}]
    unit_patterns = [(m.get("value"), m["pattern"]) for m in inputs["unit"]["extraction"]["matchers"]]
    assert unit_patterns == [
        ("EA", r"\bEA\b"), ("PC", r"\bPC\b"), ("KG", r"\bKG\b"),
        ("G", r"\bG\b"), ("L", r"\bL\b"), ("M", r"\bM\b"),
    ]
    zh = intent["clarifyPrompt"]["zh-CN"]
    assert zh["cases"] == [
        {"missing": ["material"], "text": "请提供要查询的物料编号。"},
        {"missing": ["plant"], "text": "请提供要查询的工厂。"},
    ]
    assert zh["fallback"] == {"template": "请提供要查询的物料编号和工厂。"}


def test_po_declaration_parity_constants():
    cap = _registry_intent_blocks()["MM.PurchaseOrder.GetList"]
    intent = cap["intent"]
    assert intent["intentName"] == "purchase_order_list"
    assert intent["primaryKeywords"] == ["采购订单"]
    assert intent["weakKeywords"] == ["订单", r"(?<![A-Za-z])PO(?![A-Za-z])", "采购"]
    assert intent["triggerKeywords"] == ["采购订单", "订单", r"(?<![A-Za-z])PO(?![A-Za-z])"]
    assert intent["requireAny"] == {
        "inputs": ["poNumber", "vendor", "plant", "material"], "missingName": "filter",
    }
    inputs = {i["name"]: i for i in cap["inputs"]}
    assert inputs["vendor"]["extraction"]["matchers"] == [
        {"kind": "regex", "pattern": r"供应商\s*(\d+)"}]
    assert inputs["plant"]["extraction"]["matchers"] == [
        {"kind": "regex",
         "pattern": r"(?:工厂\s*(\d{4}|[A-Z]\d{3}))|(?:(\d{4}|[A-Z]\d{3})\s*工厂)"}]
    assert inputs["material"]["extraction"]["matchers"] == [
        {"kind": "regex", "pattern": r"物料\s*([A-Za-z0-9][A-Za-z0-9\-/]+)"}]
    assert inputs["poNumber"]["extraction"]["matchers"] == [
        {"kind": "regex", "pattern": r"(?<!\d)(\d{10})(?!\d)", "scan": "all"}]
    assert inputs["poNumber"]["extraction"]["excludes"] == ["vendor", "plant"]
    zh = intent["clarifyPrompt"]["zh-CN"]
    assert zh["cases"] == [
        {"missing": ["filter"], "text": "请至少提供一个过滤条件（采购订单号、供应商、工厂或物料）。"}]


def test_pr_declaration_parity_constants():
    cap = _registry_intent_blocks()["MM.PR.CreateDraft"]
    intent = cap["intent"]
    assert intent["intentName"] == "pr_create"
    assert intent["primaryKeywords"] == [
        "采购申请", "创建采购", "建PR", "建 PR", "创建PR", "创建 PR", "PR草稿", "PR 草稿",
    ]
    assert intent["weakKeywords"] == ["采购"]
    assert intent["triggerKeywords"] == [
        "采购申请", "建PR", "建 PR", "创建PR", "创建 PR", "PR草稿", "PR 草稿",
    ]
    assert intent["clarifyPrompt"]["zh-CN"]["fallback"] == {"template": "请提供: {fields}"}
    assert intent["fieldNames"]["zh-CN"] == {
        "material": "物料编号", "plant": "工厂", "quantity": "数量", "unit": "单位",
        "delivery_date": "交货日期", "purchasing_group": "采购组",
        "cost_center": "成本中心(间采 PR 需提供)",
    }
    inputs = {i["name"]: i for i in cap["inputs"]}
    assert inputs["material"]["extraction"]["matchers"] == [
        {"kind": "regex", "pattern": r"物料\s*([A-Za-z0-9][A-Za-z0-9\-/]+)"}]
    assert inputs["plant"]["extraction"]["matchers"] == [
        {"kind": "regex", "pattern": r"工厂\s*(\d{4}|[A-Z]\d{3})"}]
    assert inputs["quantity"]["extraction"]["matchers"] == [
        {"kind": "semanticType", "ref": "Quantity"}]
    assert inputs["unit"]["extraction"]["matchers"] == [
        {"kind": "semanticType", "ref": "Unit"}]
    assert inputs["delivery_date"]["extraction"] == {
        "matchers": [{"kind": "semanticType", "ref": "Date"}], "resolver": "date"}
    assert inputs["purchasing_group"]["extraction"]["matchers"] == [
        {"kind": "semanticType", "ref": "PurchasingGroup"}]
    assert inputs["acct_assgn_cat"]["extraction"]["matchers"] == [
        {"kind": "keyword", "pattern": r"(?:间采|账号分配)\s*[Kk]", "value": "K"}]
    assert inputs["cost_center"]["extraction"]["when"] == {"field": "acct_assgn_cat", "equals": "K"}
    assert inputs["cost_center"]["extraction"]["requiredWhen"] == {"field": "acct_assgn_cat", "equals": "K"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest agent/tests/test_extraction_declarations.py -q`
Expected: FAIL (no `intent` blocks in the registry yet)

- [ ] **Step 3: Add the declarations to `registry/capabilities.yaml`**

Add a capability-level `intent` block and per-input `extraction` blocks. Full YAML
for each capability (input entries show only the added keys - keep every existing
key untouched):

`MM.Inventory.GetAvailability`:

```yaml
    intent:
      intentName: inventory_availability
      primaryKeywords: ['库存', '可用量', '可用库存', '还有多少']
      weakKeywords: ['有没有']
      triggerKeywords: ['库存', '可用量', '可用库存', '还有多少', '有没有']
      fieldNames:
        zh-CN:
          material: 物料编号
          plant: 工厂
          unit: 单位
      clarifyPrompt:
        zh-CN:
          cases:
            - missing: [material]
              text: '请提供要查询的物料编号。'
            - missing: [plant]
              text: '请提供要查询的工厂。'
          fallback:
            template: '请提供要查询的物料编号和工厂。'
```

Inputs:

```yaml
      - name: material
        # ...existing keys unchanged...
        extraction:
          matchers:
            - kind: semanticType
              ref: MaterialNumber
          priority: 10
          excludes: [plant, unit]
          resolver: text
          reaskSuspect: true
      - name: plant
        extraction:
          matchers:
            - kind: semanticType
              ref: Plant
          priority: 20
          resolver: text
      - name: unit
        extraction:
          matchers:
            - kind: keyword
              pattern: '\bEA\b'
              value: EA
            - kind: keyword
              pattern: '\bPC\b'
              value: PC
            - kind: keyword
              pattern: '\bKG\b'
              value: KG
            - kind: keyword
              pattern: '\bG\b'
              value: G
            - kind: keyword
              pattern: '\bL\b'
              value: L
            - kind: keyword
              pattern: '\bM\b'
              value: M
          priority: 15
          resolver: text
```

`MM.PurchaseOrder.GetList`:

```yaml
    intent:
      intentName: purchase_order_list
      primaryKeywords: ['采购订单']
      weakKeywords: ['订单', '(?<![A-Za-z])PO(?![A-Za-z])', '采购']
      triggerKeywords: ['采购订单', '订单', '(?<![A-Za-z])PO(?![A-Za-z])']
      fieldNames:
        zh-CN:
          poNumber: 采购订单号
          vendor: 供应商
          plant: 工厂
          material: 物料
      requireAny:
        inputs: [poNumber, vendor, plant, material]
        missingName: filter
      clarifyPrompt:
        zh-CN:
          cases:
            - missing: [filter]
              text: '请至少提供一个过滤条件（采购订单号、供应商、工厂或物料）。'
```

Inputs (all four individually optional - keep `required: false`):

```yaml
      - name: poNumber
        extraction:
          matchers:
            - kind: regex
              pattern: '(?<!\d)(\d{10})(?!\d)'
              scan: all
          priority: 10
          excludes: [vendor, plant]
          resolver: text
      - name: vendor
        extraction:
          matchers:
            - kind: regex
              pattern: '供应商\s*(\d+)'
          priority: 40
          resolver: text
      - name: plant
        extraction:
          matchers:
            - kind: regex
              pattern: '(?:工厂\s*(\d{4}|[A-Z]\d{3}))|(?:(\d{4}|[A-Z]\d{3})\s*工厂)'
          priority: 30
          resolver: text
      - name: material
        extraction:
          matchers:
            - kind: regex
              pattern: '物料\s*([A-Za-z0-9][A-Za-z0-9\-/]+)'
          priority: 20
          resolver: text
```

`MM.PR.CreateDraft`:

```yaml
    intent:
      intentName: pr_create
      primaryKeywords: ['采购申请', '创建采购', '建PR', '建 PR', '创建PR', '创建 PR', 'PR草稿', 'PR 草稿']
      weakKeywords: ['采购']
      triggerKeywords: ['采购申请', '建PR', '建 PR', '创建PR', '创建 PR', 'PR草稿', 'PR 草稿']
      fieldNames:
        zh-CN:
          material: 物料编号
          plant: 工厂
          quantity: 数量
          unit: 单位
          delivery_date: 交货日期
          purchasing_group: 采购组
          cost_center: 成本中心(间采 PR 需提供)
      clarifyPrompt:
        zh-CN:
          fallback:
            template: '请提供: {fields}'
```

Inputs:

```yaml
      - name: material
        extraction:
          matchers:
            - kind: regex
              pattern: '物料\s*([A-Za-z0-9][A-Za-z0-9\-/]+)'
          priority: 50
          resolver: text
      - name: plant
        extraction:
          matchers:
            - kind: regex
              pattern: '工厂\s*(\d{4}|[A-Z]\d{3})'
          priority: 40
          resolver: text
      - name: quantity
        extraction:
          matchers:
            - kind: semanticType
              ref: Quantity
          priority: 30
          resolver: quantity
      - name: unit
        extraction:
          matchers:
            - kind: semanticType
              ref: Unit
          priority: 25
          resolver: text
      - name: delivery_date
        extraction:
          matchers:
            - kind: semanticType
              ref: Date
          priority: 20
          resolver: date
      - name: purchasing_group
        extraction:
          matchers:
            - kind: semanticType
              ref: PurchasingGroup
          priority: 15
          resolver: text
      - name: acct_assgn_cat
        extraction:
          matchers:
            - kind: keyword
              pattern: '(?:间采|账号分配)\s*[Kk]'
              value: K
          priority: 10
          resolver: text
      - name: cost_center
        extraction:
          matchers:
            - kind: regex
              pattern: '成本中心\s*(\d+)'
          priority: 5
          resolver: text
          when: { field: acct_assgn_cat, equals: K }
          requiredWhen: { field: acct_assgn_cat, equals: K }
```

Parity rationale (do not "fix" any of these while porting):
- Inventory `unit` uses six keyword-constant matchers because `_extract_unit` tests
  unit values in fixed order (`EA` first) with case-sensitive `\b` boundaries - a
  single leftmost alternation or the case-insensitive catalog `Unit` entry would
  produce different values on multi-unit utterances.
- PO `plant` is an inline pattern (no bare-code fallback) - PO never had the
  fallback; PR material/plant are prefixed patterns, not the token-scan catalog
  entry.
- PR `triggerKeywords` omits `创建采购` (legacy trigger list lacks it) while
  `primaryKeywords` includes it (legacy ambiguity list has it).
- Missing-parameter order comes from declaration order sorted by descending
  `priority`, which matches legacy `REQUIRED_FIELDS` order for PR and
  `("material", "plant")` for inventory; PR's `cost_center` has the lowest priority
  so it lands last, reproducing the legacy append.

- [ ] **Step 4: Run tests and the registry validator**

Run: `.venv/bin/python -m pytest agent/tests/test_extraction_declarations.py agent/tests/test_registry_contract.py -q`
Expected: PASS (remove the xfail markers added in Task 4)

Run: `.venv/bin/python scripts/validate-registry-contract.py registry/capabilities.yaml`
Expected: `Registry contract valid: registry/capabilities.yaml`

- [ ] **Step 5: Commit**

```bash
git add registry/capabilities.yaml agent/tests/test_extraction_declarations.py
git commit -m "feat: strict-parity extraction declarations for inventory, PO, and PR capabilities"
```

---

### Task 6: Gateway indifference test  (tasks.md 1.6)

**Files:**
- Create: `services/gateway/core/src/test/java/com/sapnexus/gateway/registry/ExtractionMetadataIndifferenceTest.java`

**Interfaces:**
- Consumes: `CapabilityRegistryLoader`, `CapabilityRegistry`, `CapabilityDefinition`
  (existing gateway classes); the real `registry/capabilities.yaml` (which now
  carries extraction metadata after Task 5) plus an inline stripped copy.
- Produces: proof that loading a registry with extraction metadata yields an
  identical registry to the same registry without the metadata.

- [ ] **Step 1: Read the existing test conventions**

Read
`services/gateway/core/src/test/java/com/sapnexus/gateway/registry/CapabilityRegistryLoaderTest.java`
and mirror its YAML fixture style (inline strings or temp files) and its assertions.

- [ ] **Step 2: Write the test**

```java
package com.sapnexus.gateway.registry;

import static org.junit.jupiter.api.Assertions.assertEquals;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.stream.Collectors;

/**
 * Extraction metadata is agent-side data: the gateway loader must be indifferent
 * to it (registry-ontology-contract delta, "Gateway ignores extraction metadata
 * safely").
 */
class ExtractionMetadataIndifferenceTest {

    @TempDir
    Path tempDir;

    private static final String REGISTRY_WITH_METADATA = """
            version: 2
            capabilities:
              - capabilityId: MM.Inventory.GetAvailability
                name: Inventory Availability
                description: d
                status: active
                kind: Function
                domain: MM
                businessObject: InventoryStock
                ontologyIri: sapnexus:MM_Inventory_GetAvailability
                semanticType: sapnexus:InventoryAvailabilityReadFunction
                intent:
                  intentName: inventory_availability
                  primaryKeywords: ['库存']
                  weakKeywords: ['有没有']
                  triggerKeywords: ['库存', '有没有']
                  clarifyPrompt:
                    zh-CN:
                      fallback:
                        template: '请提供: {fields}'
                inputs:
                  - name: material
                    semanticName: materialNumber
                    semanticType: sapnexus:MaterialNumber
                    required: true
                    type: string
                    extraction:
                      matchers:
                        - kind: semanticType
                          ref: MaterialNumber
                      priority: 10
                      excludes: [plant]
                      resolver: text
                outputs:
                  - name: availableQuantity
                    semanticType: sapnexus:AvailableQuantity
                    type: number
                executor:
                  type: JCO_RFC
                executorBinding:
                  type: JCO_RFC
                  bindingId: sap.mm.inventory.md04-stock-req-list
                governance:
                  sideEffect: none
                  requiresApproval: false
                  approvalPolicy: not_required
            """;

    private static final String REGISTRY_WITHOUT_METADATA = """
            version: 2
            capabilities:
              - capabilityId: MM.Inventory.GetAvailability
                name: Inventory Availability
                description: d
                status: active
                kind: Function
                domain: MM
                businessObject: InventoryStock
                ontologyIri: sapnexus:MM_Inventory_GetAvailability
                semanticType: sapnexus:InventoryAvailabilityReadFunction
                inputs:
                  - name: material
                    semanticName: materialNumber
                    semanticType: sapnexus:MaterialNumber
                    required: true
                    type: string
                outputs:
                  - name: availableQuantity
                    semanticType: sapnexus:AvailableQuantity
                    type: number
                executor:
                  type: JCO_RFC
                executorBinding:
                  type: JCO_RFC
                  bindingId: sap.mm.inventory.md04-stock-req-list
                governance:
                  sideEffect: none
                  requiresApproval: false
                  approvalPolicy: not_required
            """;

    @Test
    void loadingExtractionMetadataLeavesRegistryUnchanged() throws Exception {
        Path withMeta = tempDir.resolve("with-meta.yaml");
        Path withoutMeta = tempDir.resolve("without-meta.yaml");
        Files.writeString(withMeta, REGISTRY_WITH_METADATA);
        Files.writeString(withoutMeta, REGISTRY_WITHOUT_METADATA);

        CapabilityRegistry loadedWith = new CapabilityRegistryLoader().load(withMeta);
        CapabilityRegistry loadedWithout = new CapabilityRegistryLoader().load(withoutMeta);

        assertEquals(
                loadedWithout.capabilities().stream()
                        .map(CapabilityDefinition::capabilityId).collect(Collectors.toList()),
                loadedWith.capabilities().stream()
                        .map(CapabilityDefinition::capabilityId).collect(Collectors.toList()));
        assertEquals(loadedWithout.version(), loadedWith.version());
    }

    @Test
    void realRegistryWithExtractionMetadataLoads() throws Exception {
        // The repository registry carries extraction metadata after tasks.md 1.5.
        Path repo = Path.of("..", "..", "..", "..", "registry", "capabilities.yaml")
                .toAbsolutePath().normalize();
        org.junit.jupiter.api.Assumptions.assumeTrue(Files.exists(repo),
                "repository registry not reachable from gateway module dir");
        CapabilityRegistry registry = new CapabilityRegistryLoader().load(repo);
        assertEquals(3, registry.capabilities().size());
    }
}
```

Adapt accessor names to the actual `CapabilityDefinition`/`CapabilityRegistry`
API (check the class - if it is a record, `capabilityId()` and `capabilities()`
exist; adjust to the real accessors and to how the existing loader test reaches
fixture files). If the loader test uses a resources directory instead of temp
files, follow that pattern instead of `@TempDir`.

- [ ] **Step 3: Run the gateway test**

Run: `scripts/comet-verify-gateway.sh`
Expected: BUILD SUCCESSFUL (all gateway tests, including the two new ones, pass).
If `CapabilityDefinition` exposes `equals`, tighten the first assertion to
`assertEquals(loadedWithout, loadedWith)`.

- [ ] **Step 4: Run the agent suite to confirm nothing regressed**

Run: `.venv/bin/python -m pytest agent/tests -q`
Expected: PASS (1145 passed baseline + new tests; no failures)

- [ ] **Step 5: Commit**

```bash
git add services/gateway/core/src/test/java/com/sapnexus/gateway/registry/ExtractionMetadataIndifferenceTest.java
git commit -m "test: gateway indifference to extraction metadata"
```

---

### Task 7: Group 1 verification sweep  (tasks.md 1.7)

**Files:** none (verification only)

- [ ] **Step 1: Run the sweep**

```bash
git status --short
.venv/bin/python scripts/validate-registry-contract.py registry/capabilities.yaml
.venv/bin/python -m pytest agent/tests -q
openspec list --json && openspec validate --all --strict
```

Expected: working tree contains only this change's files; registry valid; full
agent suite green; openspec validation passes.

- [ ] **Step 2: Record the baseline test count**

Note the pytest total in the transcript (e.g. `1234 passed`) - this is the parity
baseline every later task must preserve. No commit needed (no file changes beyond
what Tasks 1-6 already committed).

---

### Task 8: Atomic declaration loading in the agent  (tasks.md 2.1)

**Files:**
- Modify: `agent/sap_nexus_agent/registry_loader.py`
- Modify: `agent/sap_nexus_agent/semantic_planning/contracts.py`, `agent/sap_nexus_agent/semantic_planning/loader.py`
- Test: `agent/tests/test_registry_loader.py` (append), `agent/tests/test_semantic_planning_contract.py` (update one test)

**Interfaces:**
- Produces (in `registry_loader.py`):
  - `@dataclass(frozen=True) MatcherConfig(kind: str, pattern: str | None = None, value: str | None = None, ref: str | None = None, ignore_case: bool = False, scan: str = "first")`
  - `@dataclass(frozen=True) ConditionConfig(field: str, equals: str)`
  - `@dataclass(frozen=True) ValueFilters(min_length: int | None = None, not_in: tuple[str, ...] = (), prefix_blacklist: tuple[str, ...] = (), to_upper_compare: bool = False, to_upper_output: bool = False)`
  - `@dataclass(frozen=True) ExtractionConfig(matchers: tuple[MatcherConfig, ...], priority: int = 0, excludes: tuple[str, ...] = (), resolver: str = "text", when: ConditionConfig | None = None, required_when: ConditionConfig | None = None, reask_suspect: bool = False)`
  - `@dataclass(frozen=True) ClarifyCase(missing: frozenset[str], text: str)`
  - `@dataclass(frozen=True) ClarifyPromptConfig(cases: tuple[ClarifyCase, ...] = (), fallback_template: str | None = None)`
  - `@dataclass(frozen=True) RequireAnyConfig(inputs: tuple[str, ...], missing_name: str)`
  - `@dataclass(frozen=True) IntentConfig(intent_name: str, primary_keywords: tuple[str, ...], weak_keywords: tuple[str, ...] = (), trigger_keywords: tuple[str, ...] | None = None, field_names: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = (), clarify_prompt: tuple[tuple[str, ClarifyPromptConfig], ...] = (), require_any: RequireAnyConfig | None = None)`
  - `@dataclass(frozen=True) SemanticTypeEntry(entry_id: str, priority: int, matchers: tuple[MatcherConfig, ...], filters: ValueFilters)`
  - `@dataclass(frozen=True) SemanticTypeCatalog(entries: tuple[SemanticTypeEntry, ...])` with `.find(entry_id) -> SemanticTypeEntry | None`
  - `InputDescriptor` gains `extraction: ExtractionConfig | None = None`
  - `CapabilityDescriptor` gains `intent_config: IntentConfig | None = None`
  - `IntentCatalog` gains `semantic_types: SemanticTypeCatalog = field(default_factory=...)` (default empty, backward compatible)
  - `load_intent_catalog()` reads `registry/capabilities.yaml` AND
    `registry/semantic-types.yaml` in the same call (atomic pairing; catalog
    resolved from the same root as the capabilities file; missing/unreadable
    catalog -> empty entries, matching the loader's existing non-throwing style).
- Produces (semantic_planning): `SemanticSourceDocuments` gains
  `semantic_types: Mapping[str, Any]` (last field, default empty) and
  `documents_by_path()` includes `"registry/semantic-types.yaml"` so
  `build_registry_snapshot` covers both artifacts under one snapshot id;
  `load_semantic_sources` loads the new file.

- [ ] **Step 1: Write the failing tests** (append to `agent/tests/test_registry_loader.py`)

```python
def test_load_intent_catalog_pairs_declarations_with_catalog_atomically():
    catalog = load_intent_catalog()
    pr = catalog.find("MM.PR.CreateDraft")
    assert pr is not None and pr.intent_config is not None
    assert pr.intent_config.intent_name == "pr_create"
    inputs = {i.name: i for i in pr.inputs}
    assert inputs["cost_center"].extraction is not None
    assert inputs["cost_center"].extraction.required_when == ConditionConfig(
        field="acct_assgn_cat", equals="K")
    material_entry = catalog.semantic_types.find("MaterialNumber")
    assert material_entry is not None
    assert material_entry.filters.to_upper_compare is True
    assert material_entry.filters.min_length == 5
    # same call returned both artifacts
    assert {e.entry_id for e in catalog.semantic_types.entries} >= {
        "Plant", "MaterialNumber", "Quantity", "Unit", "Date",
        "PurchasingGroup", "Vendor", "PONumber"}


def test_load_intent_catalog_without_catalog_file_degrades(tmp_path, monkeypatch):
    # capabilities.yaml present, semantic-types.yaml absent -> capabilities still load
    (tmp_path / "capabilities.yaml").write_text(
        "version: 2\ncapabilities: []\n", encoding="utf-8")
    monkeypatch.setenv("SAP_NEXUS_AGENT_ROOT", str(tmp_path))
    catalog = load_intent_catalog()
    assert catalog.capabilities == ()
    assert catalog.semantic_types.entries == ()
```

And in `agent/tests/test_semantic_planning_contract.py`, update the pinned source
list test (rename included - this is the one sanctioned existing-test edit,
reconciliation #6):

```python
def test_loads_exactly_five_snapshot_sources():
    sources = load_semantic_sources(REPO_ROOT)
    assert tuple(sources.documents_by_path()) == (
        "ontology/capability-relations.yaml",
        "ontology/fact-types.yaml",
        "registry/capabilities.yaml",
        "registry/executor-bindings.yaml",
        "registry/semantic-types.yaml",
    )
```

Add one new assertion to the same file (new test):

```python
def test_snapshot_id_changes_when_catalog_changes():
    sources = load_semantic_sources(REPO_ROOT)
    first = build_registry_snapshot(sources)
    changed = replace(
        sources,
        semantic_types={**dict(sources.semantic_types), "version": 999},
    )
    assert build_registry_snapshot(changed).snapshot_id != first.snapshot_id
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest agent/tests/test_registry_loader.py agent/tests/test_semantic_planning_contract.py -q`
Expected: FAIL (no `intent_config`, four-source pin, no `semantic_types`)

- [ ] **Step 3: Implement**

In `registry_loader.py`, add the dataclasses above plus parsers mirroring the
existing `_parse_narrative` style (return `None` on malformed input rather than
raising):

```python
def _parse_matcher(raw: object) -> MatcherConfig | None:
    if not isinstance(raw, dict) or "kind" not in raw:
        return None
    return MatcherConfig(
        kind=str(raw["kind"]),
        pattern=str(raw["pattern"]) if raw.get("pattern") is not None else None,
        value=str(raw["value"]) if raw.get("value") is not None else None,
        ref=str(raw["ref"]) if raw.get("ref") is not None else None,
        ignore_case=bool(raw.get("ignoreCase", False)),
        scan=str(raw.get("scan", "first")),
    )


def _parse_condition(raw: object) -> ConditionConfig | None:
    if not isinstance(raw, dict) or "field" not in raw or "equals" not in raw:
        return None
    return ConditionConfig(field=str(raw["field"]), equals=str(raw["equals"]))


def _parse_extraction(raw: object) -> ExtractionConfig | None:
    if not isinstance(raw, dict):
        return None
    matchers = tuple(m for m in (_parse_matcher(x) for x in raw.get("matchers") or []) if m)
    if not matchers:
        return None
    return ExtractionConfig(
        matchers=matchers,
        priority=int(raw.get("priority", 0)),
        excludes=tuple(str(x) for x in raw.get("excludes") or []),
        resolver=str(raw.get("resolver", "text")),
        when=_parse_condition(raw.get("when")),
        required_when=_parse_condition(raw.get("requiredWhen")),
        reask_suspect=bool(raw.get("reaskSuspect", False)),
    )
```

Write `_parse_intent_block(raw)` similarly (locale maps converted to nested
tuples of pairs to stay hashable/frozen, matching the `NarrativeConfig.field_mapping`
convention), and `_parse_semantic_type_catalog(raw)` for the catalog document. In
`load_intent_catalog()`, resolve the catalog path from the same root as the
capabilities file (derive `Path(registry_path).parent / "semantic-types.yaml"` so
explicit `repo_root`, `SAP_NEXUS_AGENT_ROOT`, and walk-up resolution all pair
correctly) and attach both to the returned `IntentCatalog`.

In `semantic_planning/contracts.py` add the field
(`semantic_types: Mapping[str, Any] = MappingProxyType({})` before
`__post_init__` processes it - add it to the freeze loop) and the
`documents_by_path()` entry; in `semantic_planning/loader.py` add
`semantic_types=load_yaml_mapping(repo_root / "registry/semantic-types.yaml")`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest agent/tests/test_registry_loader.py agent/tests/test_semantic_planning_contract.py agent/tests/test_governed_context.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agent/sap_nexus_agent/registry_loader.py agent/sap_nexus_agent/semantic_planning/contracts.py agent/sap_nexus_agent/semantic_planning/loader.py agent/tests/test_registry_loader.py agent/tests/test_semantic_planning_contract.py
git commit -m "feat: atomic agent-side load of extraction declarations and semantic-type catalog"
```

---

### Task 9: Generic value resolvers  (tasks.md 2.2)

**Files:**
- Create: `agent/sap_nexus_agent/extraction/__init__.py`, `agent/sap_nexus_agent/extraction/resolvers.py`
- Test: `agent/tests/test_extraction_engine.py` (create)

**Interfaces:**
- Produces: `resolve(value: str, resolver: str, filters: ValueFilters) -> str`
  in `extraction/resolvers.py`, plus `RESOLVERS = {"text", "date", "quantity"}`.
  Behavior lifted verbatim: `text` returns the capture, applying
  `filters.to_upper_output`; `date` returns the ISO capture verbatim (no
  transformation - legacy `DATE_PATTERN` group 1 is stored as-is); `quantity`
  returns the numeric capture verbatim (legacy stores `group(1)` as-is). Unknown
  resolver name raises `ValueError` (validator prevents this from firing at
  runtime).

- [ ] **Step 1: Write the failing test** (create `agent/tests/test_extraction_engine.py`)

```python
from sap_nexus_agent.extraction.resolvers import resolve
from sap_nexus_agent.registry_loader import ValueFilters


def test_text_resolver_verbatim():
    assert resolve("DEMOA2", "text", ValueFilters()) == "DEMOA2"
    assert resolve("demoa2", "text", ValueFilters()) == "demoa2"


def test_text_resolver_uppercases_output_when_declared():
    assert resolve("ea", "text", ValueFilters(to_upper_output=True)) == "EA"
    assert resolve("001", "text", ValueFilters(to_upper_output=True)) == "001"


def test_date_resolver_iso_verbatim():
    assert resolve("2026-08-18", "date", ValueFilters()) == "2026-08-18"


def test_quantity_resolver_numeric_verbatim():
    assert resolve("10", "quantity", ValueFilters()) == "10"
    assert resolve("1.5", "quantity", ValueFilters()) == "1.5"


def test_unknown_resolver_raises():
    import pytest
    with pytest.raises(ValueError):
        resolve("x", "decimal", ValueFilters())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest agent/tests/test_extraction_engine.py -q`
Expected: FAIL (module missing)

- [ ] **Step 3: Implement**

Create `agent/sap_nexus_agent/extraction/__init__.py` (empty for now) and
`agent/sap_nexus_agent/extraction/resolvers.py`:

```python
"""Generic value resolvers. Behavior lifted verbatim from the legacy extractors
(pr_intent.py / intent.py) to guarantee migration parity."""
from __future__ import annotations

from sap_nexus_agent.registry_loader import ValueFilters

RESOLVERS = ("text", "date", "quantity")


def resolve(value: str, resolver: str, filters: ValueFilters) -> str:
    if resolver not in RESOLVERS:
        raise ValueError(f"unknown resolver: {resolver}")
    if resolver in ("date", "quantity"):
        return value  # ISO date / numeric capture stored verbatim (legacy behavior)
    if filters.to_upper_output:
        return value.upper()
    return value
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest agent/tests/test_extraction_engine.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agent/sap_nexus_agent/extraction/__init__.py agent/sap_nexus_agent/extraction/resolvers.py agent/tests/test_extraction_engine.py
git commit -m "feat: generic date/quantity/text value resolvers lifted verbatim"
```

---

### Task 10: The extraction engine  (tasks.md 2.3)

**Files:**
- Create: `agent/sap_nexus_agent/extraction/engine.py`, `agent/sap_nexus_agent/extraction/clarify.py`
- Modify: `agent/sap_nexus_agent/extraction/__init__.py`
- Test: `agent/tests/test_extraction_engine.py` (append), create `agent/tests/test_clarify_rendering.py`

**Interfaces:**
- Consumes: Task 8 loader dataclasses, Task 9 resolvers,
  `IntentParseResult`/`MatchedIntent` (imported lazily to avoid the existing
  `intent -> match_decision` import cycle).
- Produces (all in `sap_nexus_agent.extraction.engine`):
  - `keyword_hits(text: str, cap: CapabilityDescriptor) -> tuple[bool, bool]` - `(primary_hit, weak_hit)`
  - `triggered(text: str, cap: CapabilityDescriptor) -> bool` - triggerKeywords hit
  - `is_ambiguous(hits: Iterable[tuple[bool, bool]]) -> bool` - `matched >= 2 and primary == 0`
  - `any_primary_keyword(text: str, catalog: IntentCatalog) -> bool` - union of all declared `primaryKeywords`
  - `extract_parameters(text: str, cap: CapabilityDescriptor, catalog: IntentCatalog, base: Mapping[str, str] | None = None) -> dict[str, str]` - slot extraction (with optional merge base for sticky)
  - `missing_parameters(cap: CapabilityDescriptor, parameters: Mapping[str, str]) -> list[str]` - required + requiredWhen + requireAny
  - `build_capability_result(text: str, cap: CapabilityDescriptor, catalog: IntentCatalog, *, contains_rfc_name: bool = False, contains_odata_override: bool = False) -> IntentParseResult`
  - `parse_declared(text: str, catalog: IntentCatalog, *, contains_rfc_name: bool, contains_odata_override: bool) -> IntentParseResult` - full single-turn flow over all declared capabilities (trigger scan, ambiguity, single/multi composition)
  - `sticky_parse(text: str, context: ConversationContext, catalog: IntentCatalog) -> IntentParseResult` - sticky continuation via declarations (new-turn detection, D3 material inherit, reask quirk, merge, recompute missing)
- Produces (in `sap_nexus_agent.extraction.clarify`):
  - `render_clarify(cap: CapabilityDescriptor, missing: list[str], locale: str = "zh-CN") -> str | None` - deterministic cases/fallback rendering with `{fields}` expansion via `fieldNames`; default-locale-derived prompt when the locale entry is missing (never fails)
  - `ACTIVE_LOCALE = "zh-CN"`

- [ ] **Step 1: Write the failing engine tests** (append to `agent/tests/test_extraction_engine.py`)

```python
from sap_nexus_agent.extraction import engine
from sap_nexus_agent.registry_loader import load_intent_catalog


def _catalog():
    return load_intent_catalog()


def _cap(catalog, cap_id):
    cap = catalog.find(cap_id)
    assert cap is not None and cap.intent_config is not None
    return cap


def test_trigger_scan_inventory_weak_keyword_triggers():
    catalog = _catalog()
    inv = _cap(catalog, "MM.Inventory.GetAvailability")
    assert engine.triggered("有没有 DEMOA2", inv) is True
    assert engine.keyword_hits("有没有 DEMOA2", inv) == (False, True)


def test_trigger_scan_po_bounded_po():
    catalog = _catalog()
    po = _cap(catalog, "MM.PurchaseOrder.GetList")
    assert engine.triggered("IMPORT 4500000001", po) is False   # no false positive
    assert engine.triggered("PO 4500000001", po) is True
    assert engine.triggered("采购", po) is False                  # weak never triggers


def test_trigger_scan_pr_create_purchase_does_not_trigger():
    catalog = _catalog()
    pr = _cap(catalog, "MM.PR.CreateDraft")
    assert engine.triggered("采购", pr) is False
    assert engine.triggered("帮我创建PR 物料 DEMOA2", pr) is True


def test_ambiguity_condition():
    assert engine.is_ambiguous([(False, True), (False, True), (False, True)]) is True
    assert engine.is_ambiguous([(True, False), (False, True)]) is False
    assert engine.is_ambiguous([(False, True)]) is False


def test_extract_parameters_inventory_exclusion_and_priority():
    catalog = _catalog()
    inv = _cap(catalog, "MM.Inventory.GetAvailability")
    params = engine.extract_parameters("DEMOA2 1000 的库存 EA", inv, catalog)
    assert params == {"material": "DEMOA2", "plant": "1000", "unit": "EA"}


def test_extract_parameters_po_number_value_exclusion():
    catalog = _catalog()
    po = _cap(catalog, "MM.PurchaseOrder.GetList")
    params = engine.extract_parameters("采购订单 4500000001 供应商 4500000001", po, catalog)
    assert params == {"vendor": "4500000001"}  # poNumber excluded (value equality)


def test_extract_parameters_pr_conditional_cost_center():
    catalog = _catalog()
    pr = _cap(catalog, "MM.PR.CreateDraft")
    with_acct = engine.extract_parameters(
        "创建PR 间采 物料 DEMOA2 工厂 1000 数量 10 EA 交货日期 2026-10-01 采购组 002 成本中心 4700", pr, catalog)
    assert with_acct["acct_assgn_cat"] == "K"
    assert with_acct["cost_center"] == "4700"
    without = engine.extract_parameters(
        "创建PR 物料 DEMOA2 工厂 1000 数量 10 EA 交货日期 2026-10-01 采购组 002", pr, catalog)
    assert "acct_assgn_cat" not in without
    assert "cost_center" not in without  # when-gated


def test_missing_parameters_pr_required_when():
    catalog = _catalog()
    pr = _cap(catalog, "MM.PR.CreateDraft")
    assert engine.missing_parameters(pr, {"acct_assgn_cat": "K", "material": "DEMOA2"}) == [
        "plant", "quantity", "unit", "delivery_date", "purchasing_group", "cost_center"]


def test_missing_parameters_po_require_any():
    catalog = _catalog()
    po = _cap(catalog, "MM.PurchaseOrder.GetList")
    assert engine.missing_parameters(po, {}) == ["filter"]
    assert engine.missing_parameters(po, {"vendor": "1000"}) == []


def test_build_capability_result_inventory_clarify():
    catalog = _catalog()
    inv = _cap(catalog, "MM.Inventory.GetAvailability")
    result = engine.build_capability_result("查物料 DEMOA2 的库存", inv, catalog)
    assert result.intent == "inventory_availability"
    assert result.parameters == {"material": "DEMOA2"}
    assert result.missing_parameters == ["plant"]
    assert result.clarification == "请提供要查询的工厂。"


def test_parse_declared_single_and_multi():
    catalog = _catalog()
    single = engine.parse_declared("查物料 DEMOA2 在 1000 工厂的可用库存", catalog,
                                   contains_rfc_name=False, contains_odata_override=False)
    assert single.intent == "inventory_availability"
    assert single.capability_id == "MM.Inventory.GetAvailability"
    multi = engine.parse_declared(
        "DEMOA2 在 5100 的库存，再列出近 30 天未清采购订单", catalog,
        contains_rfc_name=False, contains_odata_override=False)
    assert len(multi.matched_intents) == 2
    assert multi.capability_id is None
    amb = engine.parse_declared("有没有采购", catalog,
                                contains_rfc_name=False, contains_odata_override=False)
    assert amb.is_ambiguous is True
    assert [m.capability_id for m in amb.matched_intents] == ["MM.Inventory.GetAvailability"]
```

And create `agent/tests/test_clarify_rendering.py`:

```python
from sap_nexus_agent.extraction.clarify import render_clarify
from sap_nexus_agent.registry_loader import load_intent_catalog


def _cap(cap_id):
    catalog = load_intent_catalog()
    cap = catalog.find(cap_id)
    assert cap is not None and cap.intent_config is not None
    return cap


def test_inventory_cases_exact_missing_sets():
    inv = _cap("MM.Inventory.GetAvailability")
    assert render_clarify(inv, ["material"]) == "请提供要查询的物料编号。"
    assert render_clarify(inv, ["plant"]) == "请提供要查询的工厂。"
    assert render_clarify(inv, ["material", "plant"]) == "请提供要查询的物料编号和工厂。"
    assert render_clarify(inv, []) is None


def test_pr_fallback_join_template():
    pr = _cap("MM.PR.CreateDraft")
    assert render_clarify(pr, ["quantity", "unit"]) == "请提供: 数量, 单位"
    assert render_clarify(pr, ["material", "plant"]) == "请提供: 物料编号, 工厂"


def test_missing_locale_falls_back_to_names():
    pr = _cap("MM.PR.CreateDraft")
    # no en-US entry declared -> derive from input names, never raise
    assert render_clarify(pr, ["material"], locale="en-US") is not None


def test_po_filter_case():
    po = _cap("MM.PurchaseOrder.GetList")
    assert render_clarify(po, ["filter"]) == "请至少提供一个过滤条件（采购订单号、供应商、工厂或物料）。"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest agent/tests/test_extraction_engine.py agent/tests/test_clarify_rendering.py -q`
Expected: FAIL (engine/clarify modules missing)

- [ ] **Step 3: Implement `clarify.py`**

```python
"""Deterministic CLARIFY rendering from clarifyPrompt declarations (rule mode)."""
from __future__ import annotations

from sap_nexus_agent.registry_loader import CapabilityDescriptor

ACTIVE_LOCALE = "zh-CN"


def _field_names(cap: CapabilityDescriptor, locale: str) -> dict[str, str]:
    for loc, names in cap.intent_config.field_names:
        if loc == locale:
            return dict(names)
    return {}


def render_clarify(cap: CapabilityDescriptor, missing: list[str], locale: str = ACTIVE_LOCALE) -> str | None:
    if not missing or cap.intent_config is None:
        return None
    prompt = None
    for loc, cfg in cap.intent_config.clarify_prompt:
        if loc == locale:
            prompt = cfg
            break
    if prompt is None:
        # Missing locale declaration -> default-locale prompt derived from input names (never fails)
        return "请提供: " + ", ".join(missing) if locale != ACTIVE_LOCALE else None
    missing_set = frozenset(missing)
    for case in prompt.cases:
        if case.missing == missing_set:
            return case.text
    if prompt.fallback_template is not None:
        names = _field_names(cap, locale)
        fields = ", ".join(names.get(name, name) for name in missing)
        return prompt.fallback_template.replace("{fields}", fields)
    return None
```

- [ ] **Step 4: Implement `engine.py`**

Core algorithm (write the full module; the load-bearing pieces):

```python
"""Declaration-driven extraction engine. Zero capability branches."""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

from sap_nexus_agent.extraction.clarify import render_clarify
from sap_nexus_agent.extraction.resolvers import resolve
from sap_nexus_agent.intent import IntentParseResult
from sap_nexus_agent.registry_loader import (
    CapabilityDescriptor, ExtractionConfig, IntentCatalog, MatcherConfig, ValueFilters,
)

if TYPE_CHECKING:
    from sap_nexus_agent.conversation_context import ConversationContext

EMPTY_FILTERS = ValueFilters()
# Reask-suspect token heuristic, lifted verbatim from llm_intent's inventory quirk.
_SUSPECT_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{4,}")


def _match_value(matcher: MatcherConfig, text: str, catalog: IntentCatalog,
                 filters: ValueFilters, excluded_values: set[str]) -> str | None:
    if matcher.kind == "semanticType":
        entry = catalog.semantic_types.find(matcher.ref or "")
        if entry is None:
            return None
        merged = matcher  # capability may add attributes around the ref
        for entry_matcher in entry.matchers:
            value = _match_value(_merge_matcher(entry_matcher, merged), text, catalog,
                                 entry.filters if not _has_filters(filters) else filters,
                                 excluded_values)
            if value is not None:
                return value
        return None
    flags = re.IGNORECASE if matcher.ignore_case else 0
    try:
        compiled = re.compile(matcher.pattern or "", flags)
    except re.error:
        return None
    if matcher.scan == "all":
        for m in compiled.finditer(text):
            value = _capture(m)
            if _passes_filters(value, filters) and not _is_excluded(value, excluded_values, filters):
                return value
        return None
    m = compiled.search(text)
    if m is None:
        return None
    if matcher.kind == "keyword":
        return matcher.value  # constant mapping, no capture
    value = _capture(m)
    if _passes_filters(value, filters) and not _is_excluded(value, excluded_values, filters):
        return value
    return None


def _capture(m: re.Match) -> str:
    groups = [g for g in m.groups() if g is not None]
    return groups[0] if groups else m.group(0)


def _passes_filters(value: str, filters: ValueFilters) -> bool:
    if filters.min_length is not None and len(value) < filters.min_length:
        return False
    compare = value.upper() if filters.to_upper_compare else value
    if compare in filters.not_in:
        return False
    if any(value.startswith(p) for p in filters.prefix_blacklist):
        return False
    return True


def _is_excluded(value: str, excluded_values: set[str], filters: ValueFilters) -> bool:
    compare = value.upper() if filters.to_upper_compare else value
    return compare in excluded_values
```

`extract_parameters`: iterate `cap.inputs` carrying `extraction` sorted by
`(-priority, declaration order)`; skip inputs whose `when` condition is unmet
(condition reads already-extracted parameters, which is why priority order matters);
for each input run matchers in order, first value wins; build the exclusion set from
the values of inputs listed in `excludes` (compare mode from the input's effective
filters - inventory material compares uppercased via the catalog entry, PO number
compares exactly); apply `resolve(value, extraction.resolver, filters)`.

```python
def extract_parameters(text, cap, catalog, base=None):
    parameters: dict[str, str] = dict(base or {})
    ordered = [(idx, inp) for idx, inp in enumerate(cap.inputs) if inp.extraction]
    ordered.sort(key=lambda pair: (-pair[1].extraction.priority, pair[0]))
    for _, inp in ordered:
        ext = inp.extraction
        if ext.when is not None and parameters.get(ext.when.field) != ext.when.equals:
            continue
        excluded_values = set()
        for other_name in ext.excludes:
            if other_name in parameters:
                excluded_values.add(parameters[other_name])
        for matcher in ext.matchers:
            value = _match_value(matcher, text, catalog, EMPTY_FILTERS, excluded_values)
            if value is not None:
                parameters[inp.name] = resolve(value, ext.resolver, _input_filters(matcher, catalog))
                break
    return parameters
```

Notes you must honor while implementing `_match_value` and helpers:
- `_input_filters(matcher, catalog)` resolves the effective `ValueFilters`: for a
  `semanticType` matcher it is the catalog entry's filters; for keyword/regex it is
  empty filters. Exclusion comparison must use the SAME effective filters the value
  was filtered with (uppercase for inventory material via the catalog's
  `to_upper_compare`, exact for PO number) - the `excluded_values` set is compared
  inside `_match_value` using those filters.
- `missing_parameters(cap, parameters)`: iterate `cap.inputs` in declaration order;
  include `inp.name` when (`inp.required` or (`extraction.required_when` holds
  against `parameters`)) and the name is absent from `parameters`; if
  `intent_config.require_any` is declared and none of its inputs has a value and
  the result is otherwise empty, the result is `[require_any.missing_name]`.
- `build_capability_result(text, cap, catalog, ...)`:
  `parameters = extract_parameters(...)`; `missing = missing_parameters(cap, parameters)`;
  `clarification = render_clarify(cap, missing)`; return
  `IntentParseResult(intent=cap.intent_config.intent_name, parameters=parameters,
  missing_parameters=missing, clarification=clarification, contains_rfc_name=...,
  contains_odata_override=..., capability_id=cap.capability_id)`.
  PO parity detail: legacy `_build_purchase_order_result` returns
  `missing_parameters=["filter"]` with that exact clarification when no parameter
  was extracted - `requireAny` + the `filter` case reproduce it.
- `parse_declared(text, catalog, ...)`: scan every capability with an
  `intent_config` (`triggered`), collect `keyword_hits` for all of them, compute
  `is_ambiguous` over all hits, build a result per triggered capability
  (catalog order), and compose exactly like `parse_intent` today: 0 -> empty
  result, 1 -> mirror single result with `matched_intents` length 1,
  >1 -> top-level `intent`/`capability_id` `None` with per-capability
  `MatchedIntent`s (import `MatchedIntent` lazily inside the function).
- `sticky_parse(text, context, catalog)`: port `resolve_with_context`'s algorithm
  (`llm_intent.py` lines 524-620) with declared primitives: new-turn check via
  `any_primary_keyword(text, catalog)`; inherit/merge via
  `extract_parameters(text, cap, catalog, base=context.last_context.parameters)`;
  missing via `missing_parameters`; the D3 material-inherit block is preserved
  verbatim (it special-cases the input literally named `material` - legacy quirk,
  marked with a `# TODO(follow-up): generalize field-name special cases` comment);
  the inventory reask quirk becomes generic: if any input of the inherited
  capability carries `reask_suspect`, its value exists in
  `context.last_context.parameters`, was not re-extracted this turn, and
  `_SUSPECT_TOKEN.search(text)`, drop it from merged and prepend to missing.
  Clarification via `render_clarify` (reconciliation #5).

Export from `agent/sap_nexus_agent/extraction/__init__.py`:

```python
from sap_nexus_agent.extraction import engine
from sap_nexus_agent.extraction import clarify, resolvers

__all__ = ["engine", "clarify", "resolvers"]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest agent/tests/test_extraction_engine.py agent/tests/test_clarify_rendering.py -q`
Expected: PASS. Iterate on parity-sensitive details (unit matcher order, plant
fallback, PO exclusion) until green - if a fixture-level mismatch appears, fix the
engine, never the expectation.

- [ ] **Step 6: Commit**

```bash
git add agent/sap_nexus_agent/extraction/ agent/tests/test_extraction_engine.py agent/tests/test_clarify_rendering.py
git commit -m "feat: generic declaration-driven extraction engine and CLARIFY rendering"
```

---

### Task 11: Frozen parity tables and differential harness  (tasks.md 2.4)

**Files:**
- Create: `agent/tests/fixtures/parity/{pr,inventory,po}.yaml`
- Create: `agent/tests/legacy_intent_reference.py`
- Create: `agent/tests/test_extraction_parity.py`

**Interfaces:**
- Produces: fixture tables (one YAML per capability) frozen from CURRENT legacy
  behavior; a legacy reference module (frozen copy of today's
  `parse_intent`/`resolve_with_context` composition calling the still-present legacy
  functions); a differential test asserting
  `legacy == engine == frozen expectations` for every row, and a production test
  asserting `parse_intent`/`resolve_with_context` output matches the frozen table
  (this stays green at every later migration step and becomes the permanent
  regression test after Task 18 deletes the legacy reference).
- Consumes: `engine.parse_declared` (single-turn rows), `engine.sticky_parse`
  (sticky rows), legacy reference module, `select_capability` for decision types.

- [ ] **Step 1: Freeze the legacy reference**

Create `agent/tests/legacy_intent_reference.py` as a verbatim copy of today's
`parse_intent` body (trigger scan, ambiguity, per-capability builders, single/multi
composition) and `resolve_with_context` body, calling
`intent._build_inventory_result`, `intent._build_purchase_order_result`,
`pr_intent.parse_pr_create_intent`, `intent._detect_keyword_ambiguity`, and the
`llm_intent._extract_params_for` dispatch. Expose:

```python
def parse(text: str, context=None) -> IntentParseResult: ...
def sticky(text: str, context: ConversationContext) -> IntentParseResult: ...
```

Do not "clean up" the copy - it is the frozen oracle. Header comment:
`# FROZEN legacy oracle for differential parity. Deleted with the legacy path (tasks.md 4.3).`

- [ ] **Step 2: Author the fixture tables**

Freeze each row's `expect` from the legacy oracle by actually running it (write the
rows, then a one-off command prints any mismatch; adjust the table, not the
oracle). Row schema:

```yaml
capability: MM.PR.CreateDraft
rows:
  - name: pr-full-direct          # unique within the file
    mode: single                   # single | sticky
    utterance: '创建PR 物料 DEMOA2 工厂 1000 数量 100 EA 交货日期 2026-09-01 采购组 001'
    last_context:                  # sticky rows only
      capability_id: MM.PR.CreateDraft
      decision_type: CLARIFY
      parameters: { material: DEMOA2 }
    expect:
      decision_type: SELECT        # SELECT|CLARIFY|ESCALATE_TO_PLANNER|SHOW_OPTIONS|REJECT
      capability_id: MM.PR.CreateDraft   # null for multi-intent / rejection rows
      parameters: { material: DEMOA2, plant: '1000', quantity: '100', unit: EA,
                    delivery_date: '2026-09-01', purchasing_group: '001' }
      missing: []
      clarification: null
      is_ambiguous: false
      clarification_strict: true   # false only for the sanctioned sticky PR rows (reconciliation #5)
```

Required rows per file (utterances chosen to exercise every mechanism; freeze the
exact values from the oracle):

`pr.yaml` (capability `MM.PR.CreateDraft`):
1. `pr-full-direct` - the full direct utterance above -> SELECT, no missing.
2. `pr-missing-most` - `建PR 物料 DEMOA2 工厂 1000` -> CLARIFY, missing
   `[quantity, unit, delivery_date, purchasing_group]`, clarification
   `请提供: 数量, 单位, 交货日期, 采购组`.
3. `pr-indirect-full` - `帮我建一个采购申请 间采 物料 DEMOA2 工厂 1000 数量 10 PC 成本中心 4700 交货日期 2026-10-01 采购组 002`
   -> SELECT with `acct_assgn_cat: K`, `cost_center: '4700'`, `unit: PC`.
4. `pr-indirect-missing-cost-center` - same without `成本中心 4700` -> CLARIFY,
   missing ends with `cost_center` (appended last).
5. `pr-lowercase-unit` - `创建PR 物料 DEMOA2 工厂 1000 数量 5 ea 交货日期 2026-01-01 采购组 001`
   -> `unit: EA` (uppercase output).
6. `pr-no-trigger` - `今天天气怎么样` -> REJECT, no matched intents.
7. `pr-technical-override` - `创建PR rfcName=BAPI_PR_CREATE 物料 DEMOA2` -> REJECT
   technical override, no matched intents.
8. `pr-multi-with-inventory` - `创建PR 物料 DEMOA2 工厂 1000，顺便查一下库存 DEMOA1 在 5100`
   -> ESCALATE_TO_PLANNER, two matched intents, top-level capability_id null.
9. `pr-ambiguous-show-options` - `有没有采购` -> SHOW_OPTIONS, single matched intent
   `MM.Inventory.GetAvailability`, `is_ambiguous: true`.
10. `pr-sticky-merge` (sticky) - last_context PR `{material: DEMOA2}`, follow-up
    `工厂 1000 数量 50` -> merged parameters, missing
    `[unit, delivery_date, purchasing_group]`, `clarification_strict: false`.
11. `pr-sticky-new-turn` (sticky) - last_context PR, follow-up
    `查一下库存 DEMOA1 在 5100` -> new turn, inventory SELECT.
12. `pr-sticky-new-turn-inherit` (sticky) - last_context PR
    `{material: DEMOA2, plant: '1000', ...complete}`, follow-up `数量 20` -> sticky
    merge -> SELECT (this row pins overlay merge for PR).

`inventory.yaml` (capability `MM.Inventory.GetAvailability`):
1. `inv-full` - `查物料 DEMOA2 在 1000 工厂的可用库存` -> SELECT
   `{material: DEMOA2, plant: '1000'}`.
2. `inv-missing-plant` - `查物料 DEMOA2 的库存` -> CLARIFY missing `[plant]`,
   clarification `请提供要查询的工厂。`
3. `inv-missing-material` - `5100 工厂还有多少库存` -> CLARIFY missing `[material]`,
   clarification `请提供要查询的物料编号。` (bare-code plant fallback).
4. `inv-missing-both` - `查询库存` -> CLARIFY missing `[material, plant]`,
   clarification `请提供要查询的物料编号和工厂。`
5. `inv-unit-optional` - `DEMOA2 在 5100 有多少 EA 库存` -> SELECT with `unit: EA`.
6. `inv-plant-exclusion` - `DEMOA2 1000 的库存` -> plant `1000` (bare) and material
   `DEMOA2` (token `1000` excluded by value).
7. `inv-bapi-blacklist` - `BAPI_MATERIAL_STOCK_REQ_LIST 的库存` -> no material
   extracted (prefix blacklist) -> CLARIFY missing `[material, plant]`.
8. `inv-ambiguous-show-options` - `有没有采购` -> SHOW_OPTIONS (as above).
9. `inv-multi-with-po` - `DEMOA2 在 5100 的库存，再列出近 30 天未清采购订单`
   -> ESCALATE_TO_PLANNER, `is_ambiguous: false`.
10. `inv-technical-override` - `库存 $filter=Material eq 'DEMOA2'` -> REJECT.
11. `inv-sticky-overlay` (sticky) - last_context inventory
    `{material: DEMOA2, plant: '5100'}`, follow-up `工厂 5200` -> merged
    `{material: DEMOA2, plant: '5200'}` -> SELECT.
12. `inv-sticky-reask-suspect` (sticky) - last_context inventory
    `{material: DEMOA2, plant: '5100'}`, follow-up `还是查 demoa2 在 5200 吧`
    -> lowercase material not re-extracted, suspect token present -> material
    dropped, CLARIFY missing `[material]` first, clarification
    `请提供要查询的物料编号。` (the quirk preserved via `reaskSuspect`).
13. `inv-sticky-new-turn-inherit` (sticky) - last_context inventory
    `{material: DEMOA2, plant: '5100'}`, follow-up `查一下库存` -> primary-keyword
    new turn, same capability, material inherited (D3) -> SELECT `{material: DEMOA2, plant: '5100'}`.

`po.yaml` (capability `MM.PurchaseOrder.GetList`):
1. `po-by-number` - `查询采购订单 DEMOPO2 的明细`... use a 10-digit number:
   `查询采购订单 4500000001 的明细` -> SELECT `{poNumber: '4500000001'}`.
2. `po-by-vendor` - `查供应商 DEMOV1 的采购订单`... vendor pattern is digits:
   `查供应商 1000 的采购订单` -> SELECT `{vendor: '1000'}` (no bare-plant fallback).
3. `po-by-material-and-plant` - `查工厂 5300 物料 DEMOA4B 的采购订单` -> SELECT
   `{plant: '5300', material: DEMOA4B}`.
4. `po-no-filter` - `帮我查一下采购订单` -> CLARIFY missing `[filter]`,
   clarification `请至少提供一个过滤条件（采购订单号、供应商、工厂或物料）。`
5. `po-number-value-excluded` - `采购订单 4500000001 供应商 4500000001` -> poNumber
   excluded by value equality with vendor -> SELECT `{vendor: '4500000001'}` only.
6. `po-bare-po-trigger` - `PO 4500000001` -> SELECT (boundary-aware PO trigger).
7. `po-import-no-false-positive` - `IMPORT 4500000001` -> no trigger -> REJECT.
8. `po-weak-ambiguous-escalate` - `有没有订单` -> inventory weak + PO trigger ->
   two matched intents -> ESCALATE_TO_PLANNER, `is_ambiguous: true`.
9. `po-technical-override` - `采购订单 $select=PurchaseOrder` -> REJECT.
10. `po-sticky-merge` (sticky) - last_context PO `{vendor: '1000'}`, follow-up
    `工厂 5300` -> merged `{vendor: '1000', plant: '5300'}`, missing `[]` -> SELECT.

Add one cross-cutting row to `po.yaml` (or a shared `common.yaml` if you prefer -
keep it in `po.yaml` to avoid a fourth file):
11. `weak-only-no-trigger-ambiguous` - `采购` -> no matched intents,
    `is_ambiguous: true`, decision REJECT (spec scenario "Weak keyword alone does
    not trigger but counts toward ambiguity" made executable).

- [ ] **Step 3: Write the harness test**

Create `agent/tests/test_extraction_parity.py`:

```python
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

import pytest
import yaml

from sap_nexus_agent.capability_selector import select_capability
from sap_nexus_agent.conversation_context import ConversationContext, LastContext
from sap_nexus_agent.extraction import engine
from sap_nexus_agent.registry_loader import load_intent_catalog
from sap_nexus_agent.intent import parse_intent

from legacy_intent_reference import parse as legacy_parse, sticky as legacy_sticky

FIXTURES = Path(__file__).parent / "fixtures" / "parity"
TABLES = ["pr", "inventory", "po"]


def _rows(table: str):
    doc = yaml.safe_load((FIXTURES / f"{table}.yaml").read_text(encoding="utf-8"))
    return [(row["name"], row) for row in doc["rows"]]


def _all_rows():
    return [(table, name, row) for table in TABLES for name, row in _rows(table)]


def _context(row) -> ConversationContext:
    lc = row["last_context"]
    return ConversationContext(
        history=(),
        last_context=LastContext(
            capability_id=lc["capability_id"],
            decision_type=lc.get("decision_type", "CLARIFY"),
            parameters=lc.get("parameters", {}),
        ),
    )


def _summary(result) -> dict:
    decision = select_capability(result)
    return {
        "decision_type": decision.decision_type,
        "capability_id": result.capability_id,
        "parameters": result.parameters,
        "missing": result.missing_parameters,
        "clarification": result.clarification,
        "is_ambiguous": result.is_ambiguous,
    }


def _assert_row(row, result, produced_by: str):
    expect = row["expect"]
    summary = _summary(result)
    decision = summary.pop("decision_type")
    assert decision == expect["decision_type"], (produced_by, row["name"], decision)
    if expect.get("capability_id") is None and len(result.matched_intents) == 1:
        assert summary["capability_id"] == result.matched_intents[0].capability_id
    else:
        assert summary["capability_id"] == expect["capability_id"], (produced_by, row["name"])
    assert summary["parameters"] == expect["parameters"], (produced_by, row["name"])
    assert summary["missing"] == expect["missing"], (produced_by, row["name"])
    assert summary["is_ambiguous"] == expect["is_ambiguous"], (produced_by, row["name"])
    if expect.get("clarification_strict", True):
        assert summary["clarification"] == expect["clarification"], (produced_by, row["name"])
    else:
        assert bool(summary["clarification"]) == (expect["clarification"] is not None)


@pytest.mark.parametrize("table,name,row", [(t, n, r) for t, n, r in _all_rows()])
def test_legacy_matches_frozen_table(table, name, row):
    """Differential leg 1: the frozen legacy oracle reproduces the frozen table."""
    result = (legacy_sticky(row["utterance"], _context(row))
              if row["mode"] == "sticky" else legacy_parse(row["utterance"]))
    _assert_row(row, result, "legacy")


@pytest.mark.parametrize("table,name,row", [(t, n, r) for t, n, r in _all_rows()])
def test_engine_matches_frozen_table(table, name, row):
    """Differential leg 2: the declaration-driven engine reproduces the frozen table."""
    catalog = load_intent_catalog()
    if row["mode"] == "sticky":
        result = engine.sticky_parse(row["utterance"], _context(row), catalog)
    else:
        result = engine.parse_declared(
            row["utterance"], catalog,
            contains_rfc_name=False, contains_odata_override=False)
    _assert_row(row, result, "engine")


@pytest.mark.parametrize("table,name,row", [(t, n, r) for t, n, r in _all_rows()])
def test_production_parse_matches_frozen_table(table, name, row):
    """Production leg: whatever the seam currently routes to matches the frozen table.

    Stays green at every migration step and becomes the permanent regression test
    after the legacy deletion (tasks.md 4.3).
    """
    if row["mode"] == "sticky":
        from sap_nexus_agent.llm_intent import resolve_with_context
        result = resolve_with_context(row["utterance"], _context(row), load_intent_catalog())
    else:
        result = parse_intent(row["utterance"])
    _assert_row(row, result, "production")
```

Notes:
- Technical-override rows: the engine leg must reproduce the rejection - but the
  rejection happens in `parse_intent` before the engine. For those rows, run the
  engine leg through `parse_intent` with the seam NOT yet wired (Task 12 keeps
  `parse_intent`'s override short-circuit untouched, so the production leg covers
  it; for the engine leg call `parse_intent` too and note in a comment that
  override detection stays in `intent.py` by design - or, cleaner, give
  `engine.parse_declared` the `contains_*` flags as shown and have the engine-leg
  test itself call `intent._detect_rfc_name`/`_detect_odata_override` and pass the
  flags, asserting the same empty rejection result shape). Implement the cleaner
  variant: the engine-leg test for override rows asserts
  `IntentParseResult(intent=None, parameters={}, missing_parameters=[],
  contains_rfc_name=..., contains_odata_override=...)`.
- The sticky engine leg for `clarification_strict: false` rows compares everything
  but the exact clarification text (reconciliation #5).
- `LastContext`/`ConversationContext` field names: check
  `agent/sap_nexus_agent/conversation_context.py` for the exact constructor
  (fields like `capability_id`, `decision_type`, `parameters`, `reference_turn_id`)
  and adapt `_context` accordingly.

- [ ] **Step 4: Run the harness**

Run: `.venv/bin/python -m pytest agent/tests/test_extraction_parity.py -q`
Expected: PASS (all three legs). If a leg disagrees, the frozen table is wrong only
if the oracle disagrees with reality - re-run the oracle to regenerate; otherwise
fix the engine (never weaken an assertion).

- [ ] **Step 5: Run the full agent suite + commit**

Run: `.venv/bin/python -m pytest agent/tests -q` - PASS.

```bash
git add agent/tests/fixtures/parity agent/tests/legacy_intent_reference.py agent/tests/test_extraction_parity.py
git commit -m "test: frozen parity fixture tables and differential legacy-vs-engine harness"
```

---

### Task 12: Migration seam in `parse_intent` and sticky continuation  (tasks.md 2.5)

**Files:**
- Modify: `agent/sap_nexus_agent/intent.py`
- Modify: `agent/sap_nexus_agent/llm_intent.py`
- Test: `agent/tests/test_extraction_parity.py` (production leg covers it; no new test file)

**Interfaces:**
- Produces: `_ENGINE_MIGRATED_CAPABILITIES: set[str]` in `intent.py` - initially
  EMPTY, so this task lands with zero behavior change. Each Task 13-15 adds one id.
  Deleted in Task 18.
- Seam semantics: for a capability that is declared AND in the migrated set, the
  trigger scan uses `engine.triggered`, the per-capability build uses
  `engine.build_capability_result`, ambiguity hits come from
  `engine.keyword_hits`; undeclared/unmigrated capabilities keep the legacy scan
  and builders. Sticky: `_extract_params_for` dispatches migrated+declared
  capabilities to `engine.extract_parameters`; `_contains_any_primary_keyword`
  ORs `engine.any_primary_keyword` with the legacy primary sets.

- [ ] **Step 1: Add the seam to `parse_intent`**

In `intent.py`, after the override-rejection and sticky-routing blocks (both stay
exactly as they are), replace the keyword-scan/build section with a merged scan:

```python
# Migration seam (tasks.md 2.5, removed by 4.3): declared+migrated capabilities
# run on the extraction engine; everything else keeps this module's legacy path.
_ENGINE_MIGRATED_CAPABILITIES: set[str] = set()


def _parse_single_turn(normalized: str) -> IntentParseResult:
    from sap_nexus_agent.extraction import engine
    from sap_nexus_agent.match_decision import MatchedIntent
    from sap_nexus_agent.pr_intent import PR_CREATE_KEYWORDS, parse_pr_create_intent
    from sap_nexus_agent.registry_loader import load_intent_catalog

    catalog = load_intent_catalog()
    hits: list[tuple[str, bool, bool]] = []          # (cap_id, primary, weak)
    per_capability: list[tuple[str, IntentParseResult]] = []

    # Declared, migrated capabilities (engine) - catalog order.
    for cap in catalog.capabilities:
        if cap.intent_config is None or cap.capability_id not in _ENGINE_MIGRATED_CAPABILITIES:
            continue
        hits.append((cap.capability_id, *engine.keyword_hits(normalized, cap)))
        if engine.triggered(normalized, cap):
            per_capability.append((
                cap.capability_id,
                engine.build_capability_result(normalized, cap, catalog),
            ))

    # Legacy capabilities - fixed inventory -> PO -> PR order (unchanged).
    matches_inventory = any(k in normalized for k in INVENTORY_KEYWORDS) \
        and _INVENTORY_CAPABILITY_ID not in _ENGINE_MIGRATED_CAPABILITIES
    matches_po = _PURCHASE_ORDER_KEYWORD_PATTERN.search(normalized) is not None \
        and _PURCHASE_ORDER_CAPABILITY_ID not in _ENGINE_MIGRATED_CAPABILITIES
    matches_pr = any(k in normalized for k in PR_CREATE_KEYWORDS) \
        and _PR_CREATE_CAPABILITY_ID not in _ENGINE_MIGRATED_CAPABILITIES

    legacy_primary_flags = (
        any(k in normalized for k in INVENTORY_PRIMARY_KEYWORDS) or matches_inventory is False,
    )  # see Step 2: ambiguity needs (primary, weak) per legacy capability
    hits.extend(_legacy_keyword_hits(normalized))
    if matches_inventory:
        per_capability.append((_INVENTORY_CAPABILITY_ID,
                               _build_inventory_result(normalized, False, False)))
    if matches_po:
        per_capability.append((_PURCHASE_ORDER_CAPABILITY_ID,
                               _build_purchase_order_result(normalized, False, False)))
    if matches_pr:
        per_capability.append((_PR_CREATE_CAPABILITY_ID, parse_pr_create_intent(normalized)))

    is_ambiguous = engine.is_ambiguous(hits)
    matched_intents = [MatchedIntent(capability_id=c, parameters=r.parameters,
                                     missing=list(r.missing_parameters))
                       for c, r in per_capability]
    # ...compose 0/1/>1 exactly as the current parse_intent tail does (copy it)...
```

Add `_legacy_keyword_hits(normalized) -> list[tuple[str, bool, bool]]` returning the
legacy (primary, weak) pair per capability using
`INVENTORY_PRIMARY_KEYWORDS`/`INVENTORY_WEAK_KEYWORDS`/`PURCHASE_ORDER_*`/
`PR_CREATE_*`, but ONLY for capabilities not in
`_ENGINE_MIGRATED_CAPABILITIES` (a capability must never be double-counted after
migration). Keep the 0/1/multi composition tail byte-identical to the current
code. `parse_intent` then calls `_parse_single_turn(normalized)`; the contains
flags flow through as today.

- [ ] **Step 2: Add the seam to sticky continuation**

In `llm_intent.py`:

```python
def _extract_params_for(capability_id: str, text: str) -> dict[str, str]:
    from sap_nexus_agent.intent import _ENGINE_MIGRATED_CAPABILITIES
    from sap_nexus_agent.extraction import engine
    from sap_nexus_agent.registry_loader import load_intent_catalog

    catalog = load_intent_catalog()
    cap = catalog.find(capability_id)
    if (cap is not None and cap.intent_config is not None
            and capability_id in _ENGINE_MIGRATED_CAPABILITIES):
        return engine.extract_parameters(text, cap, catalog)
    # legacy dispatch (unchanged, deleted in tasks.md 4.3)
    if capability_id == _INVENTORY_CAPABILITY_ID:
        return _build_inventory_result(text, False, False).parameters
    ...
```

And `_contains_any_primary_keyword`:

```python
def _contains_any_primary_keyword(text: str) -> bool:
    from sap_nexus_agent.intent import _ENGINE_MIGRATED_CAPABILITIES
    from sap_nexus_agent.extraction import engine
    from sap_nexus_agent.registry_loader import load_intent_catalog

    if engine.any_primary_keyword_for(
            text, load_intent_catalog(), skip=_ENGINE_MIGRATED_CAPABILITIES
            and None or None)  # declared primary keywords of migrated caps:
        ...
```

Implement it as: union of (a) `engine.any_primary_keyword(text, catalog)` computed
over migrated+declared capabilities only, and (b) the legacy
`_PRIMARY_KEYWORD_SETS` check restricted to non-migrated capabilities. Add a
`restrict_to: set[str] | None = None` parameter to
`engine.any_primary_keyword` (default `None` = all declared capabilities) rather
than contorting the call site. Do NOT change `resolve_with_context`'s algorithm.

- [ ] **Step 3: Verify zero behavior change**

Run: `.venv/bin/python -m pytest agent/tests -q`
Expected: PASS - identical count to the Task 7 baseline. The seam is inert
(`_ENGINE_MIGRATED_CAPABILITIES` is empty), so every existing test and the parity
production leg must be untouched.

- [ ] **Step 4: Commit**

```bash
git add agent/sap_nexus_agent/intent.py agent/sap_nexus_agent/llm_intent.py
git commit -m "feat: per-capability migration seam between legacy extractors and the engine"
```

---

### Task 13: Migrate `MM.PR.CreateDraft`  (tasks.md 3.1)

**Files:**
- Modify: `agent/sap_nexus_agent/intent.py` (one line)

**Interfaces:**
- Consumes: Task 12 seam, Task 11 harness.
- Produces: `_ENGINE_MIGRATED_CAPABILITIES = {"MM.PR.CreateDraft"}`.

- [ ] **Step 1: Flip the seam**

```python
_ENGINE_MIGRATED_CAPABILITIES: set[str] = {"MM.PR.CreateDraft"}
```

- [ ] **Step 2: Run the parity harness and full suite**

```bash
.venv/bin/python -m pytest agent/tests/test_extraction_parity.py -q
.venv/bin/python -m pytest agent/tests -q
```

Expected: both PASS. Failures here mean an engine parity gap for PR (single-turn
or sticky) - fix the engine or the declaration (e.g. matcher order, priority,
clarification template), never a fixture or an existing test.

- [ ] **Step 3: Run the call-plan eval**

Run: `PYTHONPATH=agent scripts/verify-agent-callplan-evidence.sh`
Expected: exit 0 (includes the full agent suite plus all eval files, among them
`evals/pr_create_cases.json`).

- [ ] **Step 4: Standalone commit (required: one commit per migration step)**

```bash
git add agent/sap_nexus_agent/intent.py
git commit -m "feat: migrate MM.PR.CreateDraft to declaration-driven extraction"
```

---

### Task 14: Migrate `MM.Inventory.GetAvailability`  (tasks.md 3.2)

**Files:**
- Modify: `agent/sap_nexus_agent/intent.py` (one line)

**Interfaces:**
- Produces: `_ENGINE_MIGRATED_CAPABILITIES = {"MM.PR.CreateDraft", "MM.Inventory.GetAvailability"}`.

- [ ] **Step 1: Flip the seam**

Add `"MM.Inventory.GetAvailability"` to the set.

- [ ] **Step 2: Run parity + full suite + eval**

```bash
.venv/bin/python -m pytest agent/tests/test_extraction_parity.py -q
.venv/bin/python -m pytest agent/tests -q
PYTHONPATH=agent scripts/verify-agent-callplan-evidence.sh
```

Expected: all green. The inventory-specific sticky material-CLARIFY quirk
(`inv-sticky-reask-suspect`) is now served by the `reaskSuspect` declaration flag -
this row is the one most likely to fail if the flag's generic logic drifted; if it
fails, fix `engine.sticky_parse`'s reask block, not the fixture.

- [ ] **Step 3: Standalone commit**

```bash
git add agent/sap_nexus_agent/intent.py
git commit -m "feat: migrate MM.Inventory.GetAvailability to declaration-driven extraction"
```

---

### Task 15: Migrate `MM.PurchaseOrder.GetList`  (tasks.md 3.3)

**Files:**
- Modify: `agent/sap_nexus_agent/intent.py` (one line)

**Interfaces:**
- Produces: `_ENGINE_MIGRATED_CAPABILITIES = {"MM.PR.CreateDraft", "MM.Inventory.GetAvailability", "MM.PurchaseOrder.GetList"}`.

- [ ] **Step 1: Flip the seam**

Add `"MM.PurchaseOrder.GetList"`.

- [ ] **Step 2: Run parity + full suite + eval**

```bash
.venv/bin/python -m pytest agent/tests/test_extraction_parity.py -q
.venv/bin/python -m pytest agent/tests -q
PYTHONPATH=agent scripts/verify-agent-callplan-evidence.sh
```

Expected: all green. Watch `po-number-value-excluded` and `po-no-filter`
(`requireAny`) - the exclusion-heavy PO logic is the most entangled.

- [ ] **Step 3: Standalone commit**

```bash
git add agent/sap_nexus_agent/intent.py
git commit -m "feat: migrate MM.PurchaseOrder.GetList to declaration-driven extraction"
```

---

### Task 16: Sticky CLARIFY switches to declaration rendering  (tasks.md 4.1)

**Files:**
- Modify: `agent/sap_nexus_agent/llm_intent.py`
- Test: `agent/tests/test_clarify_rendering.py` (append)

**Interfaces:**
- Consumes: Task 10 `extraction.clarify.render_clarify`; Task 12 seam (all three
  capabilities already migrated by Task 15, so `resolve_with_context`'s
  clarification is the last legacy text source).
- Produces: `resolve_with_context` renders clarification via
  `render_clarify(descriptor, missing)`; `_clarification_for` and its per-text
  tables are deleted from `llm_intent.py`. This completes tasks.md 4.1: every
  rule-mode clarification (single-turn via Task 10, sticky via this task) is
  declaration-driven and deterministic.

- [ ] **Step 1: Write the failing test** (append to `agent/tests/test_clarify_rendering.py`)

```python
def test_sticky_clarify_rendered_from_declaration():
    from sap_nexus_agent.conversation_context import ConversationContext, LastContext
    from sap_nexus_agent.llm_intent import resolve_with_context
    from sap_nexus_agent.registry_loader import load_intent_catalog

    context = ConversationContext(
        history=(),
        last_context=LastContext(
            capability_id="MM.PR.CreateDraft",
            decision_type="CLARIFY",
            parameters={"material": "DEMOA2"},
        ),
    )
    result = resolve_with_context("工厂 1000 数量 50", context, load_intent_catalog())
    # Reconciliation #5: sticky PR clarification is now the declared text
    assert result.clarification == "请提供: 单位, 交货日期, 采购组"
    assert result.missing_parameters == ["unit", "delivery_date", "purchasing_group"]


def test_sticky_inventory_clarify_matches_legacy_exactly():
    from sap_nexus_agent.conversation_context import ConversationContext, LastContext
    from sap_nexus_agent.llm_intent import resolve_with_context
    from sap_nexus_agent.registry_loader import load_intent_catalog

    context = ConversationContext(
        history=(),
        last_context=LastContext(
            capability_id="MM.Inventory.GetAvailability",
            decision_type="CLARIFY",
            parameters={"plant": "1000"},
        ),
    )
    result = resolve_with_context("查一下库存", context, load_intent_catalog())
    # inventory single-turn and sticky texts coincide - stays strict
    assert result.clarification == "请提供要查询的物料编号。"
```

(Adapt `LastContext` field names to `conversation_context.py` if they differ.)

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest agent/tests/test_clarify_rendering.py -q`
Expected: FAIL (sticky still renders `请提供以下参数：...` via `_clarification_for`).

- [ ] **Step 3: Implement**

In `resolve_with_context`, replace `clarification = _clarification_for(cap_id, missing)`
with `clarification = render_clarify(descriptor, missing)` (`descriptor` is already
resolved above the call site). Delete `_clarification_for` and every clarification
string table it owned. Grep for remaining `_clarification_for` references
(`grep -rn "_clarification_for" agent/`) and remove them all.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest agent/tests -q`
Expected: PASS - including the parity production leg (sticky PR rows carry
`clarification_strict: false` during differential mode per reconciliation #5, so
the sanctioned text change does not break the harness).

- [ ] **Step 5: Commit**

```bash
git add agent/sap_nexus_agent/llm_intent.py agent/tests/test_clarify_rendering.py
git commit -m "feat: sticky CLARIFY rendered from declarations, legacy text tables removed"
```

---

### Task 17: Optional grounded LLM rephrase for llm/hybrid CLARIFY  (tasks.md 4.2)

**Files:**
- Modify: `agent/sap_nexus_agent/extraction/clarify.py`
- Modify: `agent/sap_nexus_agent/llm_intent.py`
- Test: `agent/tests/test_clarify_rendering.py` (append)

**Interfaces:**
- Produces in `clarify.py`:

```python
def rephrase_clarify(
    template_text: str,
    missing: list[str],
    field_names: dict[str, str],
    all_declared_fields: set[str],
    model,                                # NarrativeModel-like: chat_json
    timeout_ms: int = 3000,
) -> str | None
```

  Sends a minimal JSON-schema prompt (system: rephrase the question, ask ONLY
  about the listed missing fields, return `{"question": "..."}`); validates the
  response: non-empty string, does not mention any declared field display name
  or input name that is NOT in `missing` (closed-set negative check against
  `all_declared_fields`), and mentions at least one missing field. Returns
  `None` on timeout, malformed JSON, validation failure, or any exception -
  the caller then uses `template_text` unchanged.
- Produces in `llm_intent.py`: in the LLM leg of `parse_with_llm` and the LLM
  path of `parse_with_hybrid`, when the parse result carries a clarification
  and an LLM client is available, attempt `rephrase_clarify(...)` with the
  declared `fieldNames`; on `None`, keep the template text. The rule fallback
  leg of hybrid NEVER calls the model (fallback contract preserved). Rule mode
  has no client and never reaches this code.
- Consumes: existing `OpenAiCompatibleLlmClient.chat_json`.

- [ ] **Step 1: Write the failing tests** (append; use a fake model object)

```python
class _FakeModel:
    def __init__(self, payload, *, delay=None, raise_exc=None): ...
    def chat_json(self, messages, temperature=0.0, max_tokens=200): ...

def test_rephrase_accepts_in_scope_question():      # mentions only missing fields -> rephrased
def test_rephrase_rejects_out_of_scope_field():     # mentions a declared-but-not-missing field -> None
def test_rephrase_rejects_malformed_json():         # -> None
def test_rephrase_rejects_timeout():                # -> None (template used by caller)
def test_hybrid_clarify_falls_back_to_template_on_model_failure():  # llm_intent wiring
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest agent/tests/test_clarify_rendering.py -q`
Expected: FAIL (`rephrase_clarify` missing).

- [ ] **Step 3: Implement** per Interfaces. Keep the rephrase prompt free of any
  capability-specific text; the closed set comes entirely from the declaration.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest agent/tests/test_clarify_rendering.py agent/tests -q`
Expected: PASS (existing tests unaffected - rephrase only fires when a client is
present and its output passes the closed-set check; all recorded-model tests use
fixtures whose clarification path stays templated).

- [ ] **Step 5: Commit**

```bash
git add agent/sap_nexus_agent/extraction/clarify.py agent/sap_nexus_agent/llm_intent.py agent/tests/test_clarify_rendering.py
git commit -m "feat: optional grounded LLM rephrase for CLARIFY in llm/hybrid modes"
```

---

### Task 18: Delete the legacy path and the seam  (tasks.md 4.3)

**Files:**
- Modify: `agent/sap_nexus_agent/intent.py`
- Modify: `agent/sap_nexus_agent/llm_intent.py`
- Delete: `agent/sap_nexus_agent/pr_intent.py`
- Delete: `agent/tests/legacy_intent_reference.py`
- Modify: `agent/tests/test_extraction_parity.py`
- Modify: any test importing `pr_intent` (grep first; expectations unchanged,
  only the import/source of truth moves)

**Interfaces:**
- Produces: `parse_intent` = engine-only (trigger scan, ambiguity, single/multi
  composition all from declarations; the override-rejection guards
  `_detect_rfc_name`/`_detect_odata_override` and the sticky-routing head stay
  in `intent.py` unchanged). `_ENGINE_MIGRATED_CAPABILITIES`,
  `_legacy_keyword_hits`, `INVENTORY_KEYWORDS`, `INVENTORY_PRIMARY_KEYWORDS`,
  `INVENTORY_WEAK_KEYWORDS`, `PURCHASE_ORDER_*`, `PR_CREATE_*` constant tables,
  `_build_inventory_result`, `_build_purchase_order_result`,
  `_detect_keyword_ambiguity` legacy implementation, `_extract_params_for`,
  `_PRIMARY_KEYWORD_SETS`, `_contains_any_primary_keyword` legacy halves are
  all deleted. The parity harness loses its differential legs
  (`test_legacy_matches_frozen_table`, `test_engine_matches_frozen_table` when
  they only wrap the deleted oracle) - the frozen-table production leg becomes
  the permanent regression test.

- [ ] **Step 1: Survey blast radius**

```bash
grep -rn "pr_intent\|_build_inventory_result\|_build_purchase_order_result\|INVENTORY_KEYWORDS\|PR_CREATE_KEYWORDS\|_PRIMARY_KEYWORD_SETS\|_extract_params_for\|legacy_intent_reference" agent/ --include="*.py" | grep -v "extraction/"
```

For each hit in tests: the test's expectations stay; rewrite it to call the
engine/production path (e.g. `parse_intent`) or use the parity fixture tables.
If a test exercises a legacy-only quirk that has a sanctioned deviation
(reconciliation #5), update the expectation and note the reconciliation number
in a comment.

- [ ] **Step 2: Delete in dependency order**

1. `intent.py`: collapse `_parse_single_turn` to engine-only (remove the legacy
   scan branch and the migrated-set checks); delete the constant tables and
   legacy builders; keep `parse_inventory_intent` only if a non-test caller
   remains (grep `run_inventory_query` adapter wiring) - otherwise delete it too.
2. `llm_intent.py`: `_extract_params_for` body becomes the engine call only;
   `_contains_any_primary_keyword` becomes `engine.any_primary_keyword` only.
3. `rm agent/sap_nexus_agent/pr_intent.py`
4. `rm agent/tests/legacy_intent_reference.py`; strip the two differential legs
   from `test_extraction_parity.py` (keep `test_production_parse_matches_frozen_table`).

- [ ] **Step 3: Verify nothing regressed**

```bash
.venv/bin/python -m pytest agent/tests -q
PYTHONPATH=agent scripts/verify-agent-callplan-evidence.sh
```

Expected: PASS with the same passing count as the Task 15 state (minus deleted
differential-leg tests). Any failure = a legacy behavior still depended on -
fix by declaration or engine, never by reintroducing legacy code.

- [ ] **Step 4: Commit**

```bash
git add -A agent/
git commit -m "refactor: delete legacy extraction path; engine is the only rule-mode path"
```

---

### Task 19: Declaration-only fixture capability end-to-end proof  (tasks.md 4.4)

**Files:**
- Test: `agent/tests/test_declaration_only_capability.py` (create)

**Interfaces:**
- Produces: a test that writes a temporary `capabilities.yaml` +
  `semantic-types.yaml` pair containing ONLY a brand-new capability
  (e.g. `Test.Sample.GetStockNote`, primaryKeywords `["样本备注"]`, one required
  input with a `semanticType` matcher referencing a new catalog entry, and a
  `clarifyPrompt` case), loads them via `load_intent_catalog(registry_path=...)`
  (or `SAP_NEXUS_AGENT_ROOT` monkeypatch - use whatever Task 8 actually
  exposed), and asserts through the PRODUCTION `parse_intent`: trigger,
  slot fill, missing computation, and CLARIFY text - with zero agent code
  referencing the capability. This is the executable form of the delta spec's
  "Declared capability recognized without code change" scenario.

- [ ] **Step 1: Write the test** (it passes only if Tasks 8-18 are complete)

```python
def test_declaration_only_capability_full_rule_mode_flow(tmp_path, monkeypatch):
    # write registry pair; load catalog; parse via sap_nexus_agent.intent.parse_intent
    # assert: triggered, parameter extracted, missing -> CLARIFY with declared text
    # assert: no source change needed - capability id appears nowhere in agent/sap_nexus_agent
```

- [ ] **Step 2: Run** - `.venv/bin/python -m pytest agent/tests/test_declaration_only_capability.py -q` -> PASS.

- [ ] **Step 3: Commit**

```bash
git add agent/tests/test_declaration_only_capability.py
git commit -m "test: declaration-only capability is rule-mode usable end to end"
```

---

### Task 20: Closeout verification sweep  (tasks.md 5.1)

**Files:** none (verification only; fixes follow the debug gate if anything fails)

- [ ] **Step 1: Run the full matrix**

```bash
git status --short                     # expect only tracked-change files, no strays
.venv/bin/python scripts/validate-registry-contract.py registry/capabilities.yaml
.venv/bin/python -m pytest agent/tests -v --tb=short -q
PYTHONPATH=agent scripts/verify-agent-callplan-evidence.sh
openspec list --json && openspec validate --all --strict
git diff --stat 2d4af9451ab1516a775de367d5b8bf347136eee2..HEAD -- frontend/   # expect empty
```

Gateway test (Task 6): re-run once via the same gradle invocation used there.

- [ ] **Step 2: Record results** in the change's verification notes
  (`openspec/changes/declarative-intent-extraction/` - append to the Design Doc's
  verification section or a `verification.md`), including the final agent suite
  pass count and the parity-table row count. No claim without output.

---

### Task 21: Documentation updates  (tasks.md 5.2)

**Files:**
- Modify: `README.md`, `README.en.md` (rule-path description in 核心特性/架构)
- Modify: `docs/superpowers/specs/2026-08-18-declarative-intent-extraction-design.md`
  (append verification record from Task 20; mark reconciliations as applied)

- [ ] **Step 1: Update READMEs** - one bullet each (zh + en): rule-mode intent
  extraction is declaration-driven (`registry/capabilities.yaml` intent blocks +
  `registry/semantic-types.yaml`); adding a capability needs no agent code.
  Keep it to the existing maturity/feature bullet style; do not restructure.

- [ ] **Step 2: Append the parity baseline** (frozen-table row counts per
  capability, final suite counts, sanctioned deviation list) to the Design Doc
  as a "Verification Record" section.

- [ ] **Step 3: Commit**

```bash
git add README.md README.en.md docs/superpowers/specs/2026-08-18-declarative-intent-extraction-design.md
git commit -m "docs: declarative intent extraction verification record and README updates"
```

---

## Completion Criteria

- All tasks above checked; every commit green on: full agent suite, parity
  harness (frozen tables), call-plan eval, registry contract validation.
- `pr_intent.py` and the legacy tables no longer exist; `parse_intent` has zero
  capability-id literals outside the migration-seam removal (grep
  `grep -rn "MM\." agent/sap_nexus_agent/intent.py` -> empty).
- The declaration-only capability test (Task 19) proves the extension contract.
- Frontend untouched; gateway behavior unchanged (Task 6 test green).


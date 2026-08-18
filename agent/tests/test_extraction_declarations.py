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


# Sentinel for mutations that must REMOVE a top-level key (dict-merge cannot).
_MISSING = object()


def _apply_catalog_mutation(mutation: dict) -> dict:
    payload = {**VALID_CATALOG}
    for key, value in mutation.items():
        if value is _MISSING:
            payload.pop(key, None)
        else:
            payload[key] = value
    return payload


@pytest.mark.parametrize("mutation", [
    {"semanticTypes": _MISSING},                           # semanticTypes required
    {"semanticTypes": [{"id": "X"}]},                      # matcher + priority required
    {"semanticTypes": [{"id": "X", "priority": 1,
                        "matchers": [{"kind": "regex"}]}]},# pattern required
    {"semanticTypes": [{"id": "X", "priority": 1,
                        "matchers": [{"kind": "regex", "pattern": "x"}],
                        "filters": {"minLength": "five"}}]},# minLength integer
])
def test_invalid_catalog_rejected(mutation):
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(_apply_catalog_mutation(mutation),
                            _load("semantic-type-catalog.schema.json"))


def test_duplicate_catalog_id_allowed_by_schema():
    # Duplicate ids are rejected by the registry validator (Task 4), not here.
    payload = {
        **VALID_CATALOG,
        "semanticTypes": [
            {"id": "X", "priority": 1,
             "matchers": [{"kind": "regex", "pattern": "x"}]},
            {"id": "X", "priority": 2,
             "matchers": [{"kind": "regex", "pattern": "y"}]},
        ],
    }
    jsonschema.validate(payload, _load("semantic-type-catalog.schema.json"))

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

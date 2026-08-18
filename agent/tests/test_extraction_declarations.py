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


# --- Semantic-type catalog parity (Task 3) ---

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


# --- Registry contract validator rules (Task 4) ---

from scripts.validate_registry_contract import (
    load_registry_contract,
    load_semantic_type_catalog,
    regex_backtracking_guard,
    validate_registry_contract,
)


class _IndentedDumper(yaml.SafeDumper):
    """Block sequences indented under their key.

    The registry contract validator parses capabilities.yaml with its own
    indentation-based parser: list items must sit deeper than their parent key.
    PyYAML's default dump style emits them at the parent indent, which that
    parser rejects, so tests serialize with this dumper instead.
    """

    def increase_indent(self, flow=False, indentless=False):
        return super().increase_indent(flow, False)


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
    path.write_text(
        yaml.dump(doc, Dumper=_IndentedDumper, allow_unicode=True,
                  default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )
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


def test_real_registry_validates_with_catalog():
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


def test_evasive_backtracking_regex_rejected():
    # Alternation-based blowup evades the nested-quantifier heuristic; the
    # bounded sample timeout must abort it instead of hanging the validator.
    assert regex_backtracking_guard(r"(a|a)+$") is not None


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


# --- Fix round 1: malformed declarations and off-thread guard bounding ---

def test_malformed_intent_block_rejected(tmp_path):
    # Present-but-not-a-mapping intent must be a validation error, not a silent skip.
    doc = _capability_yaml(intent_block=[])
    contract = load_registry_contract(_write_registry(tmp_path, doc))
    errors = validate_registry_contract(contract, repo_root=REPO_ROOT)
    assert any("intent must be a mapping" in e for e in errors)


def test_malformed_input_extraction_rejected(tmp_path):
    # Present-but-not-a-mapping extraction must be a validation error naming the input.
    doc = _capability_yaml(_valid_intent(), extraction=[])
    contract = load_registry_contract(_write_registry(tmp_path, doc))
    errors = validate_registry_contract(contract, repo_root=REPO_ROOT)
    assert any(
        "extraction must be a mapping" in e and "material" in e for e in errors
    )


def test_off_thread_backtracking_guard_is_bounded():
    # SIGALRM is unavailable off the main thread; the fallback path must still
    # terminate (worker thread + join timeout) instead of hanging.
    import threading
    import time as _time

    result: dict = {}

    def run():
        result["error"] = regex_backtracking_guard(r"(a|a)+$")

    thread = threading.Thread(target=run, daemon=True)
    started = _time.perf_counter()
    thread.start()
    thread.join(timeout=5)
    assert not thread.is_alive(), "off-thread guard ran unbounded"
    assert _time.perf_counter() - started < 5
    assert result.get("error") is not None

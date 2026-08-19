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
                {"kind": "regex", "pattern": "[A-Z0-9]+", "scan": "all",
                 "justification": "synthetic fixture"}
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
             "matchers": [{"kind": "regex", "pattern": "x",
                           "justification": "synthetic fixture"}]},
            {"id": "X", "priority": 2,
             "matchers": [{"kind": "regex", "pattern": "y",
                           "justification": "synthetic fixture"}]},
        ],
    }
    jsonschema.validate(payload, _load("semantic-type-catalog.schema.json"))


# --- Semantic-type catalog parity (Task 3) ---

import yaml

CATALOG_PATH = REPO_ROOT / "registry" / "semantic-types.yaml"

EXPECTED_PATTERN_PARITY = {
    "MaterialNumber": [r"(?<![A-Za-z0-9-])[A-Z0-9][A-Z0-9-]{1,39}(?![A-Za-z0-9-])"],
    "Quantity": [r"(\d+(?:\.\d+)?)\s*(?:EA|PC|KG|G|L|M)"],
    "Unit": [r"\b(EA|PC|KG|G|L|M)\b"],
    "Date": [r"(\d{4}-\d{2}-\d{2})"],
    "PurchasingGroup": [r"采购组\s*([A-Za-z0-9]{1,3})"],
    # Deliberate departure from the verbatim legacy lift: the legacy digit-only
    # pattern never matched sanitized (DEMOV1) or real (V72719) vendor codes.
    "Vendor": [r"供应商\s*([A-Z0-9]{1,10})"],
    # Deliberate departure from the verbatim legacy lift: the legacy bare
    # 10-digit pattern never matched sanitized PO codes (DEMOPO1); the
    # 采购订单-anchored alphanumeric matcher is added as a second form.
    "PONumber": [
        r"(?<!\d)(\d{10})(?!\d)",
        r"采购订单\s*([A-Z0-9]{4,10})",
    ],
}

EXPECTED_PLANT_MATCHERS = [
    {"kind": "prefixed", "prefix": ["在"], "valueShape": "plantCode"},
    {"kind": "suffixed", "suffix": ["工厂"], "valueShape": "plantCode"},
    {
        "kind": "regex",
        "pattern": r"(?<!\d)([A-Z]\d{3}|\d{4})(?!\d)",
        "justification": (
            "Bare 4-char code scan with digit-only lookaround guards; the "
            "named-kind bare scan uses alnum guards and would change behavior "
            "for digit-adjacent tokens."
        ),
    },
]


def _load_catalog() -> dict:
    return yaml.safe_load(CATALOG_PATH.read_text(encoding="utf-8"))


def test_catalog_matches_json_schema():
    jsonschema.validate(_load_catalog(), _load("semantic-type-catalog.schema.json"))


def test_catalog_patterns_are_lifted_verbatim_from_legacy_extractors():
    catalog = {e["id"]: e for e in _load_catalog()["semanticTypes"]}
    assert set(catalog) == set(EXPECTED_PATTERN_PARITY) | {"Plant"}
    for entry_id, patterns in EXPECTED_PATTERN_PARITY.items():
        assert [m["pattern"] for m in catalog[entry_id]["matchers"]] == patterns, entry_id
    assert catalog["Plant"]["matchers"] == EXPECTED_PLANT_MATCHERS


def test_catalog_value_shapes_plant_code():
    assert _load_catalog()["valueShapes"] == {"plantCode": "^[A-Z0-9]{4}$"}


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

from copy import deepcopy

from sap_nexus_agent.semantic_planning.loader import load_semantic_sources
from sap_nexus_agent.semantic_planning.validation import build_semantic_contracts

from scripts.validate_registry_contract import (
    count_regex_matchers,
    load_registry_contract,
    load_semantic_type_catalog,
    regex_backtracking_guard,
    validate_extraction_declarations,
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


# --- Registry declaration parity (Task 5) ---


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
    # Deliberate departure from the verbatim legacy lift: digit-only vendor
    # extraction never matched sanitized (DEMOV1) or real (V72719) codes.
    assert inputs["vendor"]["extraction"]["matchers"] == [
        {"kind": "regex", "pattern": r"供应商\s*([A-Z0-9]{1,10})"}]
    assert inputs["plant"]["extraction"]["matchers"] == [
        {"kind": "regex",
         "pattern": r"(?:工厂\s*(\d{4}|[A-Z]\d{3}))|(?:(\d{4}|[A-Z]\d{3})\s*工厂)"}]
    assert inputs["material"]["extraction"]["matchers"] == [
        {"kind": "regex", "pattern": r"物料\s*([A-Za-z0-9][A-Za-z0-9\-/]+)"}]
    # Deliberate departure from the verbatim legacy lift: bare 10-digit poNumber
    # extraction never matched sanitized PO codes (DEMOPO1); the anchored
    # alphanumeric matcher is the second form.
    assert inputs["poNumber"]["extraction"]["matchers"] == [
        {"kind": "regex", "pattern": r"(?<!\d)(\d{10})(?!\d)", "scan": "all"},
        {"kind": "regex", "pattern": r"采购订单\s*([A-Z0-9]{4,10})"}]
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
    assert inputs["plant"]["pattern"] == "^[A-Z0-9]{4}$"
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


# --- Task 5b: capability.schema.json embedding + drift guard against
# extraction-declaration.schema.json (the shape authority) ---


def test_real_registry_sources_build_valid_semantic_contract():
    # Regression: capability.schema.json ($defs.capability uses
    # additionalProperties: false) must allowlist the capability-level
    # `intent` block and per-input `extraction` blocks, otherwise
    # build_semantic_contracts fails on the real registry with
    # SCHEMA_INVALID "unexpected property: intent".
    result = build_semantic_contracts(load_semantic_sources(REPO_ROOT))
    assert result.report.valid, [
        (issue.path, issue.code, issue.message) for issue in result.report.issues
    ]
    assert result.graph is not None and result.snapshot is not None


def _capability_block_schema(block_name: str) -> dict:
    """Wrap a $defs block of capability.schema.json as a standalone schema."""
    capability_schema = _load("capability.schema.json")
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$defs": capability_schema["$defs"],
        "$ref": f"#/$defs/{block_name}",
    }


def _assert_block_parity(instance: dict, authority_schema: dict, block_name: str) -> None:
    embedded = _capability_block_schema(block_name)
    authority_valid = jsonschema.Draft202012Validator(authority_schema).is_valid(instance)
    embedded_valid = jsonschema.Draft202012Validator(embedded).is_valid(instance)
    assert embedded_valid == authority_valid


def _mutated(base: dict, mutation: dict) -> dict:
    payload = deepcopy(base)
    for key, value in mutation.items():
        if value is _MISSING:
            payload.pop(key, None)
        else:
            payload[key] = value
    return payload


INTENT_PARITY_MUTATIONS = [
    {},                                                     # canonical: both accept
    {"intentName": 123},
    {"intentName": ""},
    {"primaryKeywords": []},
    {"primaryKeywords": "库存"},
    {"weakKeywords": ["采购", 5]},
    {"triggerKeywords": []},
    {"fieldNames": {}},
    {"fieldNames": {"zh-CN": {}}},
    {"requireAny": {"inputs": [], "missingName": "x"}},
    {"requireAny": {"inputs": ["a"]}},                     # missingName required
    {"requireAny": {"inputs": ["a"], "missingName": "x", "extra": 1}},
    {"clarifyPrompt": {}},
    {"clarifyPrompt": {"zh-CN": {"cases": "nope"}}},
    {"clarifyPrompt": {"zh-CN": {"fallback": {"template": ""}}}},
    {"clarifyPrompt": {"zh-CN": {"cases": [], "fallback": {"template": "t"}}}},
    {"unknownProperty": True},
]


@pytest.mark.parametrize("mutation", INTENT_PARITY_MUTATIONS)
def test_intent_block_parity_with_extraction_declaration(mutation):
    # Drift guard: the embedded $defs.intentBlock in capability.schema.json
    # must accept/reject exactly what extraction-declaration.schema.json
    # (root) accepts/rejects for the intent block.
    schema = _load("extraction-declaration.schema.json")
    _assert_block_parity(
        _mutated(VALID_INTENT, mutation), schema, "intentBlock"
    )


def test_canonical_intent_block_accepted_by_both_schemas():
    schema = _load("extraction-declaration.schema.json")
    assert jsonschema.Draft202012Validator(schema).is_valid(VALID_INTENT)
    assert jsonschema.Draft202012Validator(
        _capability_block_schema("intentBlock")
    ).is_valid(VALID_INTENT)


EXTRACTION_PARITY_MUTATIONS = [
    {},                                                     # canonical: both accept
    {"matchers": []},
    {"matchers": "all"},
    {"matchers": [{"kind": "embedding", "pattern": "x"}]},
    {"matchers": [{"kind": "regex"}]},
    {"matchers": [{"kind": "keyword", "pattern": "x"}]},
    {"matchers": [{"kind": "semanticType", "pattern": "x"}]},
    {"matchers": [{"kind": "keyword", "pattern": "x", "value": "K", "scan": "every"}]},
    {"priority": "high"},
    {"resolver": "decimal"},
    {"when": {"field": "x"}},
    {"when": {"field": "x", "equals": "K", "extra": 0}},
    {"reaskSuspect": "yes"},
    {"unknownProperty": True},
]


@pytest.mark.parametrize("mutation", EXTRACTION_PARITY_MUTATIONS)
def test_extraction_block_parity_with_extraction_declaration(mutation):
    # Drift guard: the embedded $defs.extractionBlock in capability.schema.json
    # must accept/reject exactly what extraction-declaration.schema.json
    # (definitions.inputExtraction) accepts/rejects for input extractions.
    schema = _load("extraction-declaration.schema.json")
    _assert_block_parity(
        _mutated(VALID_INPUT_EXTRACTION, mutation),
        schema["definitions"]["inputExtraction"],
        "extractionBlock",
    )


def test_canonical_extraction_block_accepted_by_both_schemas():
    schema = _load("extraction-declaration.schema.json")
    assert jsonschema.Draft202012Validator(
        schema["definitions"]["inputExtraction"]
    ).is_valid(VALID_INPUT_EXTRACTION)
    assert jsonschema.Draft202012Validator(
        _capability_block_schema("extractionBlock")
    ).is_valid(VALID_INPUT_EXTRACTION)


# --- Task 1.1: named matcher kinds, valueShapes, regex justification ---


def test_catalog_schema_accepts_named_kinds_and_value_shapes():
    payload = {
        **VALID_CATALOG,
        "valueShapes": {"plantCode": "^[A-Z0-9]{4}$"},
        "semanticTypes": [
            {"id": "P", "priority": 1, "matchers": [
                {"kind": "prefixed", "prefix": ["在"], "valueShape": "plantCode"},
                {"kind": "suffixed", "suffix": ["工厂"], "valueShape": "plantCode"},
                {"kind": "valueShape", "valueShape": "plantCode"},
            ]},
        ],
    }
    jsonschema.validate(payload, _load("semantic-type-catalog.schema.json"))


def test_catalog_schema_rejects_regex_without_justification():
    payload = {**VALID_CATALOG, "semanticTypes": [
        {"id": "P", "priority": 1, "matchers": [{"kind": "regex", "pattern": "x"}]},
    ]}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, _load("semantic-type-catalog.schema.json"))


def test_unjustified_catalog_regex_rejected(tmp_path):
    contract = load_registry_contract(_write_registry(tmp_path, _capability_yaml(_valid_intent(), VALID_EXTRACTION)))
    errors = validate_extraction_declarations(
        contract, {"X": {"id": "X", "matchers": [{"kind": "regex", "pattern": "x"}]}}, REPO_ROOT
    )
    assert any("justification" in e and "X" in e for e in errors)


def test_justified_catalog_regex_accepted(tmp_path):
    contract = load_registry_contract(_write_registry(tmp_path, _capability_yaml(_valid_intent(), VALID_EXTRACTION)))
    errors = validate_extraction_declarations(
        contract,
        {"X": {"id": "X", "matchers": [{"kind": "regex", "pattern": "x", "justification": "synthetic"}]}},
        REPO_ROOT,
    )
    assert not any("justification" in e for e in errors)


def test_regex_matcher_count_is_observable_metric():
    contract = load_registry_contract(REPO_ROOT / "registry" / "capabilities.yaml")
    entries, _ = load_semantic_type_catalog(REPO_ROOT)
    catalog_count, capability_count = count_regex_matchers(contract, entries)
    # Catalog: Plant 1 + MaterialNumber/Quantity/Unit/Date/PurchasingGroup/
    # Vendor 1 each + PONumber 2 = 9. Capability-level regexes: all current
    # declarations still use extraction with inline regexes (e.g. PR material).
    assert catalog_count == 9
    assert capability_count >= 1

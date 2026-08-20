---
change: declarative-intent-hardening
design-doc: docs/superpowers/specs/2026-08-19-declarative-intent-hardening-design.md
base-ref: 06966c7
---

# Declarative Intent Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the three structural weaknesses of the declarative intent layer before the registry contract freeze: whitelist matcher kinds (B1), de-enumerate clarify prompts with a round budget (B2), and generalize extraction into binding sources with priority (B3).

**Architecture:** Registry declarations (`registry/capabilities.yaml` + `registry/semantic-types.yaml`) drive extraction and clarification. B1 adds named matcher kinds (`prefixed`/`suffixed`/`valueShape`) compiled at load time in `_matching.py`, plus a justified regex escape hatch and an observable regex count from the registry validator. B2 replaces hand-enumerated clarify cases with a `groupByBindingKind` strategy rendered per source group, bounded by a durable per-capability round budget stored in `ConversationReadState`. B3 introduces `binding.sources[]` (userUtterance / capabilityOutput / default) with fixed priority; the legacy `extraction:` alias is normalized by the loader into a single userUtterance source and emits a validator warning.

**Tech Stack:** Python 3 (dataclasses, `re`), JSON Schema draft 2020-12 (`jsonschema`), PyYAML, pytest. No new dependencies.

## Global Constraints

- Follow the design doc exactly (`docs/superpowers/specs/2026-08-19-declarative-intent-hardening-design.md`): decisions §3.1–§3.7, migration order §5, Plant rewrite YAML verbatim (§3.1), exact xfail marker and reason (§3.6).
- Work on the current branch (`main`); commit per item with test names and root causes in messages; commit series boundaries: B1 items (1.1–1.5) one series, B2 (2.1–2.5) another, B3 (3.1–3.4) another, closeout (4.1–4.2) last (Design §5).
- `evals/matcher_cases.yaml` is the B1 equivalence gate: file stays unchanged, 23/23 cases must stay green at the end of every B1 task.
- `matcher_cases` plant codes are 4-char digit values (`1000`/`5100`); the AB12 letter-mixed acceptance is a deliberate, documented contract loosening (§3.2) pinned by a unit test — never by changing eval cases.
- No new dependencies; frontend/Gateway untouched; READ capabilities must never invoke `BAPI_TRANSACTION_COMMIT`/`ROLLBACK` (no SAP code is touched by this change).
- The capabilityOutput execution path is NOT wired this batch: `resolve_input_binding` skips capabilityOutput sources (`_WIRED_SOURCE_KINDS`), and the xfail placeholder test FAILS today (strict XFAIL, suite green). Do not "fix" the xfail into an XPASS — that is the deliberate signal for the future dependency-edge change.
- The regex `justification` gate is catalog-scoped: the schema and validator require `justification` on semantic-type catalog regex matchers only; capability-level regex matchers are counted by the metric but not gated (they get no justification field).
- `ConversationReadState.to_dict()` MUST omit `clarifyRounds` when empty so legacy payloads round-trip byte-identically (`test_read_state_and_conversation_context_round_trip_without_legacy_json_changes`).
- The clarify round budget is tracked on the sticky-continuation path only (`resolve_with_context`, `engine.sticky_parse`); the single-turn path (`build_capability_result`) renders without incrementing because a primary-keyword turn is a fresh selection (documented boundary).
- Every code step below is complete code, not a sketch. If a step says "add a test", the test code is inline.

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `schemas/semantic-type-catalog.schema.json` | Catalog schema: named kinds, valueShapes, regex justification | B1 (task 1.1) |
| `schemas/extraction-declaration.schema.json` | Extraction authority schema: localePrompt strategy, inputBinding defs | B2 (2.1), B3 (3.1) |
| `schemas/capability.schema.json` | Capability embedding: localePrompt strategy, ioField binding, deprecated extraction | B2 (2.1), B3 (3.1) |
| `agent/sap_nexus_agent/registry_loader.py` | Loader models: MatcherConfig fields, SemanticTypeCatalog.value_shapes, ClarifyPromptConfig.strategy/max_rounds, BindingConfig/BindingSource, `_parse_input_binding` | 1.1, 2.1, 3.2 |
| `agent/sap_nexus_agent/extraction/_matching.py` | `_compile_named_kind`, match_value dispatch, `_merge_matcher` propagation | 1.2 |
| `registry/semantic-types.yaml` | Plant rewrite, valueShapes, justifications, version 2 | 1.3 |
| `scripts/validate_registry_contract.py` | Justification gate, regex count metric, deprecation warnings, binding validation, clarify coverage | 1.4, 2.1, 3.1 |
| `scripts/validate-registry-contract.py` | CLI prints count + warnings | 1.4, 3.1 |
| `registry/capabilities.yaml` | PR clarifyPrompt strategy + plant pattern | 1.5, 2.2 |
| `agent/sap_nexus_agent/extraction/clarify.py` | Strategy rendering, group-by-kind, round budget helpers | 2.3 |
| `agent/sap_nexus_agent/read_context.py` | `ConversationReadState.clarify_rounds` | 2.4 |
| `agent/sap_nexus_agent/intent.py` | `IntentParseResult.clarify_rounds` | 2.4 |
| `agent/sap_nexus_agent/llm_intent.py` | `resolve_with_context` budget-aware, reask via binding | 2.4, 3.2 |
| `agent/sap_nexus_agent/extraction/engine.py` | Binding resolution with priority, binding-based missing/reask | 3.2, 3.3 |
| `agent/sap_nexus_agent/orchestrator.py` | `_resolved_non_read_outcome` merges parsed rounds | 2.4 |
| `agent/tests/test_registry_loader.py` | Loader tests for new matcher fields, valueShapes, strategy | 1.1, 2.1 |
| `agent/tests/test_named_kind_matching.py` | NEW: compiled-regex pins, AB12 contract, equivalence | 1.2 |
| `agent/tests/test_extraction_declarations.py` | Schema/parity/validator contract tests | 1.1, 1.3, 1.4, 2.1, 3.1 |
| `agent/tests/test_clarify_rendering.py` | Strategy/budget/override rendering tests | 2.3, 2.5 |
| `agent/tests/test_read_context.py` | clarify_rounds round-trip tests | 2.4 |
| `agent/tests/test_binding_sources.py` | NEW: priority, alias normalization, xfail placeholder | 3.2, 3.3, 3.4 |

Test command convention (run from repo root): `cd agent && python3 -m pytest tests/<file>.py -q`.

## Commit Strategy

- **B1 series** (tasks 1.1–1.5): one commit per task. Message format: `feat(declarative-intent): <item> — <test names>; root cause <...>`.
- **B2 series** (tasks 2.1–2.5): one commit per task.
- **B3 series** (tasks 3.1–3.4): one commit per task.
- **Closeout** (tasks 4.1–4.2): 4.1 produces the verification evidence; 4.2 audits spec mapping and is the final commit of the change.

Note on transient red between 1.1 and 1.3: task 1.1 makes the catalog schema require `justification` on regex matchers, so `test_catalog_matches_json_schema` (validates the real catalog) is red until task 1.3 adds the registry data. This is the intended order (Design §5: schemas → registry data); 1.3's commit restores green.

---

## B1 — Matcher kind whitelist

### Task 1.1: Catalog schema: named kinds, valueShapes, regex justification + loader parsing

**Files:**
- Modify: `schemas/semantic-type-catalog.schema.json` (matcher items at lines 36–56, top-level properties at lines 9–14)
- Modify: `agent/sap_nexus_agent/registry_loader.py` (MatcherConfig at line 25, `_parse_matcher` at line 177, SemanticTypeCatalog at line 104, `_parse_semantic_type_catalog` at line 309)
- Modify: `agent/tests/test_extraction_declarations.py` (VALID_CATALOG at line 90, `test_duplicate_catalog_id_allowed_by_schema` at line 144)
- Modify: `agent/tests/test_registry_loader.py` (append loader tests)

**Interfaces:**
- Consumes: existing `MatcherConfig`, `SemanticTypeCatalog`, `_parse_matcher`, `_parse_semantic_type_catalog`.
- Produces (later tasks rely on these):
  - `MatcherConfig` gains `prefix: tuple[str, ...] = ()`, `suffix: tuple[str, ...] = ()`, `value_shape: str | None = None`, `justification: str | None = None` (appended after `scan`, all defaulted — existing keyword constructions keep working).
  - `SemanticTypeCatalog` gains `value_shapes: Mapping[str, str] = field(default_factory=dict)` (constructed via `SemanticTypeCatalog(entries=..., value_shapes=...)`; existing `SemanticTypeCatalog(entries=())` call sites unchanged).
  - `_parse_matcher(raw)` parses `prefix`/`suffix` (list of strings), `valueShape` (string), `justification` (string).
  - Catalog schema accepts matcher kinds `prefixed`/`suffixed`/`valueShape` and requires `justification` on `regex`.

- [x] **Step 1: Write the failing schema tests** (append to `agent/tests/test_extraction_declarations.py`; `_load` and `pytest`/`jsonschema` are already imported there)

```python
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
```

Also update the two existing fixtures that now violate the justification rule (they must keep passing):
- `VALID_CATALOG` line 97: `{"kind": "regex", "pattern": "[A-Z0-9]+", "scan": "all"}` → add `"justification": "synthetic fixture"`.
- `test_duplicate_catalog_id_allowed_by_schema` lines 150 and 152: add `"justification": "synthetic fixture"` to both regex matchers.

- [x] **Step 2: Run the schema tests to verify they fail**

Run: `cd agent && python3 -m pytest tests/test_extraction_declarations.py -q`
Expected: FAIL — `ValidationError` raised for the accepted payload, or the regex-without-justification payload unexpectedly passes; the two fixture tests FAIL because `justification` is now required.

- [x] **Step 3: Write the failing loader tests** (append to `agent/tests/test_registry_loader.py`; check the file's existing import style and mirror it — it already imports `load_intent_catalog`)

```python
def test_parse_matcher_accepts_named_kind_fields():
    from sap_nexus_agent.registry_loader import _parse_matcher

    prefixed = _parse_matcher({"kind": "prefixed", "prefix": ["在"], "valueShape": "plantCode"})
    assert prefixed is not None
    assert prefixed.prefix == ("在",)
    assert prefixed.value_shape == "plantCode"
    assert prefixed.pattern is None

    regex = _parse_matcher({"kind": "regex", "pattern": "x", "justification": "why"})
    assert regex is not None and regex.justification == "why"


def test_catalog_value_shapes_parsed_from_document():
    from sap_nexus_agent.registry_loader import _parse_semantic_type_catalog

    catalog = _parse_semantic_type_catalog({
        "valueShapes": {"plantCode": "^[A-Z0-9]{4}$"},
        "semanticTypes": [{
            "id": "X",
            "priority": 1,
            "matchers": [{"kind": "valueShape", "valueShape": "plantCode"}],
        }],
    })
    assert catalog.value_shapes == {"plantCode": "^[A-Z0-9]{4}$"}
    assert catalog.find("X") is not None
    assert catalog.find("X").matchers[0].value_shape == "plantCode"
```

- [x] **Step 4: Run the loader tests to verify they fail**

Run: `cd agent && python3 -m pytest tests/test_registry_loader.py -q`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'prefix'` / `MatcherConfig` has no field `prefix` / `SemanticTypeCatalog` has no attribute `value_shapes`.

- [x] **Step 5: Implement the schema change** in `schemas/semantic-type-catalog.schema.json`

Add `valueShapes` to top-level `properties` (after `semanticTypes`, before the closing brace of `properties`):

```json
    "valueShapes": {
      "type": "object",
      "additionalProperties": {"type": "string", "minLength": 1},
      "description": "Named value shapes referenced by prefixed/suffixed/valueShape matchers via the matcher's valueShape key (e.g. plantCode: '^[A-Z0-9]{4}$')."
    },
```

Replace the matcher `properties` block (currently lines 39–46) and its `allOf` (lines 47–54):

```json
              "properties": {
                "kind": {"enum": ["keyword", "regex", "semanticType", "prefixed", "suffixed", "valueShape"]},
                "pattern": {"type": "string", "minLength": 1},
                "value": {"type": "string", "minLength": 1},
                "ref": {"type": "string", "minLength": 1},
                "ignoreCase": {"type": "boolean"},
                "scan": {"enum": ["first", "all"]},
                "prefix": {
                  "type": "array",
                  "minItems": 1,
                  "items": {"type": "string", "minLength": 1},
                  "description": "Literal tokens anchoring the value BEFORE them; alternated when multiple."
                },
                "suffix": {
                  "type": "array",
                  "minItems": 1,
                  "items": {"type": "string", "minLength": 1},
                  "description": "Literal tokens anchoring the value AFTER them; alternated when multiple."
                },
                "valueShape": {
                  "type": "string",
                  "minLength": 1,
                  "description": "Name of a catalog-level valueShapes entry supplying the capture shape."
                },
                "justification": {
                  "type": "string",
                  "minLength": 1,
                  "description": "Required for kind regex: why the named kinds cannot express this matcher (escape hatch)."
                }
              },
              "allOf": [
                {"if": {"properties": {"kind": {"const": "keyword"}}},
                 "then": {"required": ["pattern", "value"]}},
                {"if": {"properties": {"kind": {"const": "regex"}}},
                 "then": {"required": ["pattern", "justification"]}},
                {"if": {"properties": {"kind": {"const": "semanticType"}}},
                 "then": {"required": ["ref"]}},
                {"if": {"properties": {"kind": {"const": "prefixed"}}},
                 "then": {"required": ["prefix", "valueShape"]}},
                {"if": {"properties": {"kind": {"const": "suffixed"}}},
                 "then": {"required": ["suffix", "valueShape"]}},
                {"if": {"properties": {"kind": {"const": "valueShape"}}},
                 "then": {"required": ["valueShape"]}}
              ]
```

- [x] **Step 6: Implement the loader change** in `agent/sap_nexus_agent/registry_loader.py`

Append the four fields to `MatcherConfig` (after `scan`):

```python
    scan: str = "first"
    prefix: tuple[str, ...] = ()
    suffix: tuple[str, ...] = ()
    value_shape: str | None = None
    justification: str | None = None
```

Update `_parse_matcher` (line 177):

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
        prefix=tuple(str(token) for token in raw.get("prefix") or []),
        suffix=tuple(str(token) for token in raw.get("suffix") or []),
        value_shape=str(raw["valueShape"]) if raw.get("valueShape") is not None else None,
        justification=str(raw["justification"]) if raw.get("justification") is not None else None,
    )
```

Update `SemanticTypeCatalog` (line 104): add the field and ensure `field` is imported (add `field` to the existing `from dataclasses import ...` line):

```python
@dataclass(frozen=True)
class SemanticTypeCatalog:
    entries: tuple[SemanticTypeEntry, ...] = ()
    value_shapes: Mapping[str, str] = field(default_factory=dict)
```

(If `Mapping` is not imported in this module, add `from typing import Mapping`.)

Update `_parse_semantic_type_catalog` (line 309) — replace the final `return SemanticTypeCatalog(entries=tuple(entries))` with:

```python
    value_shapes: dict[str, str] = {}
    raw_shapes = raw.get("valueShapes")
    if isinstance(raw_shapes, dict):
        value_shapes = {str(key): str(shape) for key, shape in raw_shapes.items() if shape}
    return SemanticTypeCatalog(entries=tuple(entries), value_shapes=value_shapes)
```

- [x] **Step 7: Run all tests to verify they pass**

Run: `cd agent && python3 -m pytest tests/test_extraction_declarations.py tests/test_registry_loader.py -q`
Expected: PASS (all new tests; the two updated fixtures; note `test_catalog_matches_json_schema` may be red here — it validates the real catalog which lacks justifications until task 1.3; that is expected and resolved in 1.3).

- [x] **Step 8: Commit**

```bash
git add schemas/semantic-type-catalog.schema.json agent/sap_nexus_agent/registry_loader.py agent/tests/test_extraction_declarations.py agent/tests/test_registry_loader.py
git commit -m "feat(declarative-intent): B1.1 catalog schema named kinds + valueShapes + regex justification, loader parses them — test_catalog_schema_accepts_named_kinds_and_value_shapes, test_catalog_schema_rejects_regex_without_justification, test_parse_matcher_accepts_named_kind_fields, test_catalog_value_shapes_parsed_from_document; root cause: free-form regex matchers need a whitelist"
```

---

### Task 1.2: Named-kind compilation in `_matching.py`

**Files:**
- Modify: `agent/sap_nexus_agent/extraction/_matching.py` (`match_value` at line 19, `_compile_matcher` at line 62, `_merge_matcher` at line 101)
- Create: `agent/tests/test_named_kind_matching.py`

**Interfaces:**
- Consumes: `MatcherConfig.prefix/suffix/value_shape` (task 1.1), `SemanticTypeCatalog.value_shapes` (task 1.1).
- Produces (later tasks rely on these):
  - `_compile_named_kind(matcher: MatcherConfig, catalog: IntentCatalog) -> re.Pattern[str] | None` — returns the compiled pattern for `prefixed`/`suffixed`/`valueShape` kinds, `None` when the shape is unknown.
  - `match_value` now dispatches named kinds to `_compile_named_kind`; everything else (capture extraction, filters, exclusions, scan) is unchanged.
  - `_merge_matcher` propagates the new fields.

- [x] **Step 1: Write the failing tests** — create `agent/tests/test_named_kind_matching.py`

```python
"""Compiled-regex behavior of the named matcher kinds (Design §3.1, §3.2)."""
from sap_nexus_agent.extraction._matching import (
    EMPTY_FILTERS,
    _compile_named_kind,
    _merge_matcher,
    match_value,
)
from sap_nexus_agent.registry_loader import MatcherConfig, load_intent_catalog

CATALOG = load_intent_catalog()


def _matcher(kind, **kwargs):
    return MatcherConfig(kind=kind, **kwargs)


def test_named_kind_compiled_patterns_pinned():
    # Design §3.7: unit tests pin the compiled regex per kind.
    assert _compile_named_kind(
        _matcher("prefixed", prefix=("在",), value_shape="plantCode"), CATALOG
    ).pattern == r"(?:在)\s*([A-Z0-9]{4})"
    assert _compile_named_kind(
        _matcher("suffixed", suffix=("工厂",), value_shape="plantCode"), CATALOG
    ).pattern == r"([A-Z0-9]{4})\s*(?:工厂)"
    assert _compile_named_kind(
        _matcher("valueShape", value_shape="plantCode"), CATALOG
    ).pattern == r"(?<![A-Za-z0-9])([A-Z0-9]{4})(?![A-Za-z0-9])"
    # Unknown shape -> None (matcher never matches; safe degrade).
    assert _compile_named_kind(_matcher("prefixed", prefix=("在",), value_shape="nope"), CATALOG) is None
    # Anchor stripping: shape '^...$' anchors live at shape level, not in the
    # composed matcher.
    assert _compile_named_kind(
        _matcher("prefixed", prefix=("在",), value_shape="plantCode"), CATALOG
    ).search("在 1000") is not None


def test_prefixed_matches_value_after_token():
    m = _matcher("prefixed", prefix=("在",), value_shape="plantCode")
    assert match_value(m, "在 1000 创建采购申请", CATALOG, EMPTY_FILTERS, set()) == "1000"
    assert match_value(m, "在1000", CATALOG, EMPTY_FILTERS, set()) == "1000"
    assert match_value(m, "采购申请 1000", CATALOG, EMPTY_FILTERS, set()) is None


def test_suffixed_matches_value_before_token():
    m = _matcher("suffixed", suffix=("工厂",), value_shape="plantCode")
    assert match_value(m, "采购申请 1000 工厂", CATALOG, EMPTY_FILTERS, set()) == "1000"
    assert match_value(m, "1000工厂", CATALOG, EMPTY_FILTERS, set()) == "1000"
    assert match_value(m, "采购申请 1000", CATALOG, EMPTY_FILTERS, set()) is None


def test_value_shape_bare_scan_uses_alnum_boundary_guards():
    m = _matcher("valueShape", value_shape="plantCode")
    assert match_value(m, "工厂 1000", CATALOG, EMPTY_FILTERS, set()) == "1000"
    assert match_value(m, "AB12", CATALOG, EMPTY_FILTERS, set()) == "AB12"
    assert match_value(m, "x1000x", CATALOG, EMPTY_FILTERS, set()) is None
    assert match_value(m, "10000", CATALOG, EMPTY_FILTERS, set()) is None


def test_plant_named_kinds_extract_letter_mixed_code_ab12():
    # Design §3.2: contract, not accident — plantCode ^[A-Z0-9]{4}$ accepts
    # letter-mixed codes the legacy [A-Z]\d{3}|\d{4} rejected.
    plant = CATALOG.semantic_types.find("Plant")
    assert plant is not None
    prefixed, suffixed, _bare = plant.matchers
    assert match_value(prefixed, "在 AB12", CATALOG, EMPTY_FILTERS, set()) == "AB12"
    assert match_value(suffixed, "AB12 工厂", CATALOG, EMPTY_FILTERS, set()) == "AB12"


def test_plant_named_kinds_preserve_legacy_alternation():
    # Design §3.1 equivalence boundary: the old single regex accepted
    # "在 X" OR "X 工厂"; two named matchers preserve that alternation, and
    # "在 X 工厂" hits the prefixed matcher first, same as the legacy first
    # alternative.
    plant = CATALOG.semantic_types.find("Plant")
    assert match_value(plant.matchers[0], "在 1000", CATALOG, EMPTY_FILTERS, set()) == "1000"
    assert match_value(plant.matchers[1], "1000 工厂", CATALOG, EMPTY_FILTERS, set()) == "1000"
    assert match_value(plant.matchers[0], "在 1000 工厂", CATALOG, EMPTY_FILTERS, set()) == "1000"


def test_semantic_type_wrapper_merges_named_kind_fields():
    plant = CATALOG.semantic_types.find("Plant")
    wrapper = MatcherConfig(kind="semanticType", ref="Plant")
    merged = _merge_matcher(plant.matchers[0], wrapper)
    assert merged.kind == "prefixed"
    assert merged.prefix == ("在",)
    assert merged.value_shape == "plantCode"
    # The wrapper path (semanticType ref) extracts through the named kind.
    assert match_value(wrapper, "在 1000", CATALOG, EMPTY_FILTERS, set()) == "1000"
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `cd agent && python3 -m pytest tests/test_named_kind_matching.py -q`
Expected: FAIL — `AttributeError: 'MatcherConfig' object has no attribute 'prefix'` (task 1.1's fields exist, but `match_value` has no named-kind dispatch yet: prefixed/suffixed kinds fall through to `_compile_matcher` which compiles `pattern or ""` → empty pattern, so nothing matches).

- [x] **Step 3: Implement the compilation** in `agent/sap_nexus_agent/extraction/_matching.py`

Update `match_value` (line 19) — insert the named-kind dispatch between the `semanticType` branch and `_compile_matcher`:

```python
    if matcher.kind in ("prefixed", "suffixed", "valueShape"):
        compiled = _compile_named_kind(matcher, catalog)
    else:
        compiled = _compile_matcher(matcher)
```

Add `_compile_named_kind` after `_compile_matcher`:

```python
def _compile_named_kind(matcher: MatcherConfig, catalog: IntentCatalog) -> re.Pattern[str] | None:
    """Compile a named-kind matcher against a catalog-level value shape.

    The shape's ^/$ anchors are stripped: in a prefixed/suffixed composition
    the prefix/suffix tokens provide the left/right anchor; in the bare
    valueShape scan alphanumeric lookaround guards provide both.
    """
    shape = (catalog.semantic_types.value_shapes or {}).get(matcher.value_shape or "")
    if not shape:
        return None
    inner = shape
    if inner.startswith("^"):
        inner = inner[1:]
    if inner.endswith("$"):
        inner = inner[:-1]
    flags = re.IGNORECASE if matcher.ignore_case else 0
    if matcher.kind == "prefixed":
        tokens = "|".join(re.escape(token) for token in matcher.prefix)
        if not tokens:
            return None
        return re.compile(rf"(?:{tokens})\s*({inner})", flags)
    if matcher.kind == "suffixed":
        tokens = "|".join(re.escape(token) for token in matcher.suffix)
        if not tokens:
            return None
        return re.compile(rf"({inner})\s*(?:{tokens})", flags)
    if matcher.kind == "valueShape":
        return re.compile(rf"(?<![A-Za-z0-9])({inner})(?![A-Za-z0-9])", flags)
    return None
```

Update `_merge_matcher` (line 101) so the wrapper path propagates the named-kind structure:

```python
def _merge_matcher(entry_matcher: MatcherConfig, wrapper: MatcherConfig) -> MatcherConfig:
    scan = wrapper.scan if wrapper.scan != "first" else entry_matcher.scan
    return MatcherConfig(
        kind=entry_matcher.kind,
        pattern=wrapper.pattern or entry_matcher.pattern,
        value=wrapper.value or entry_matcher.value,
        ref=entry_matcher.ref,
        ignore_case=entry_matcher.ignore_case or wrapper.ignore_case,
        scan=scan,
        prefix=wrapper.prefix or entry_matcher.prefix,
        suffix=wrapper.suffix or entry_matcher.suffix,
        value_shape=wrapper.value_shape or entry_matcher.value_shape,
        justification=wrapper.justification or entry_matcher.justification,
    )
```

- [x] **Step 4: Run the tests to verify they pass**

Run: `cd agent && python3 -m pytest tests/test_named_kind_matching.py -q`
Expected: PASS (all 7 tests; the file has 7 test functions — the original "8" was a miscount). Note: green only after task 1.3 lands the registry data.

- [x] **Step 5: Verify the B1 equivalence gate is untouched**

Run: `cd agent && python3 -m pytest tests/test_eval_runner.py -q`
Expected: PASS — `test_matcher_eval_file_passes` (matcher_cases 23 active cases, total >= 5). The file itself is unchanged.

- [x] **Step 6: Commit**

```bash
git add agent/sap_nexus_agent/extraction/_matching.py agent/tests/test_named_kind_matching.py
git commit -m "feat(declarative-intent): B1.2 named-kind compilation prefixed/suffixed/valueShape with value-shape lookup — test_named_kind_compiled_patterns_pinned, test_prefixed_matches_value_after_token, test_suffixed_matches_value_before_token, test_value_shape_bare_scan_uses_alnum_boundary_guards, test_plant_named_kinds_extract_letter_mixed_code_ab12, test_plant_named_kinds_preserve_legacy_alternation, test_semantic_type_wrapper_merges_named_kind_fields; root cause: free-form regex matchers cannot be whitelisted"
```

---

### Task 1.3: Registry data — Plant rewrite, valueShapes, justifications

**Files:**
- Modify: `registry/semantic-types.yaml` (Plant entry, `valueShapes` section, version, justification on all 7 remaining regex entries)
- Modify: `agent/tests/test_extraction_declarations.py` (`EXPECTED_PATTERN_PARITY` at line 164, `test_catalog_patterns_are_lifted_verbatim_from_legacy_extractors` at line 195)

**Interfaces:**
- Consumes: task 1.1 schema (regex justification now required), task 1.2 compilation.
- Produces: the real catalog data driving tasks 1.4/1.5 and the whole B2/B3 batch.

- [x] **Step 1: Run the pre-change gate**

Run: `cd agent && python3 -m pytest tests/test_extraction_declarations.py::test_catalog_matches_json_schema -q`
Expected: FAIL — the real catalog now violates the task 1.1 schema (regex matchers lack `justification`). This is the red this task resolves.

- [x] **Step 2: Rewrite `registry/semantic-types.yaml`**

- Bump `version: 1` → `version: 2` (schema: "bumped on every structural change").
- Add the catalog-level `valueShapes` section after `semanticTypes:` block (top level, sibling of `semanticTypes`):

```yaml
valueShapes:
  # Deliberate loosening vs the legacy [A-Z]\d{3}|\d{4}: letter-mixed codes
  # (AB12) are now valid plant codes. All existing eval/test utterances use
  # digit codes, so matcher_cases 23/23 holds; the AB12 contract is pinned by
  # test_plant_named_kinds_extract_letter_mixed_code_ab12 (Design §3.2).
  plantCode: '^[A-Z0-9]{4}$'
```

- Replace the Plant entry's matchers with the design doc §3.1 verbatim:

```yaml
  - id: Plant
    description: SAP plant code - 在-prefixed and 工厂-suffixed named kinds, bare 4-char code regex fallback with lookaround guards
    priority: 20
    matchers:
      - kind: prefixed
        prefix: ['在']
        valueShape: plantCode
      - kind: suffixed
        suffix: ['工厂']
        valueShape: plantCode
      - kind: regex
        pattern: '(?<!\d)([A-Z]\d{3}|\d{4})(?!\d)'
        justification: >-
          Bare 4-char code scan with digit-only lookaround guards; the
          named-kind bare scan uses alnum guards and would change behavior
          for digit-adjacent tokens.
```

- Add a one-line `justification` to every remaining regex matcher (all 7 entries, 8 matchers — PONumber has two). Each explains why named kinds cannot express it:

```yaml
  # MaterialNumber
        justification: >-
          Bare uppercase token scan with negated character-class guards; a
          named shape cannot express the negated alnum boundary.
  # Quantity
        justification: >-
          Numeric capture with an optional alternated unit token set and
          case-insensitive match; named kinds cannot express the alternation.
  # Unit
        justification: >-
          Unit-of-measure token set with word boundaries; named kinds cannot
          express the alternated token set.
  # Date
        justification: >-
          ISO date capture; a named shape matches one literal only and Date
          is its sole user, so no duplication exists to consolidate.
  # PurchasingGroup
        justification: >-
          采购组-prefixed code capture; named kinds cannot express the 1-3
          character width constraint on the captured value.
  # Vendor
        justification: >-
          供应商-prefixed alphanumeric code capture; named kinds cannot
          express the 1-10 character width constraint on the captured value.
  # PONumber matcher 1
        justification: >-
          Bare 10-digit scan with digit-only lookaround guards; alnum guards
          would change behavior for digit-adjacent tokens.
  # PONumber matcher 2
        justification: >-
          采购订单-prefixed alphanumeric code capture; named kinds cannot
          express the 4-10 character width constraint on the captured value.
```

- [x] **Step 3: Update the parity pins** in `agent/tests/test_extraction_declarations.py`

Remove `"Plant"` from `EXPECTED_PATTERN_PARITY` and add the named-kind pin below it:

```python
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
```

Update `test_catalog_patterns_are_lifted_verbatim_from_legacy_extractors` (line 195):

```python
def test_catalog_patterns_are_lifted_verbatim_from_legacy_extractors():
    catalog = {e["id"]: e for e in _load_catalog()["semanticTypes"]}
    assert set(catalog) == set(EXPECTED_PATTERN_PARITY) | {"Plant"}
    for entry_id, patterns in EXPECTED_PATTERN_PARITY.items():
        assert [m["pattern"] for m in catalog[entry_id]["matchers"]] == patterns, entry_id
    assert catalog["Plant"]["matchers"] == EXPECTED_PLANT_MATCHERS
```

Add the valueShapes pin:

```python
def test_catalog_value_shapes_plant_code():
    assert _load_catalog()["valueShapes"] == {"plantCode": "^[A-Z0-9]{4}$"}
```

- [x] **Step 4: Run the registry and test gates**

Run:
```bash
cd agent && python3 -m pytest tests/test_extraction_declarations.py tests/test_named_kind_matching.py tests/test_registry_loader.py -q
cd agent && python3 -m pytest tests/test_eval_runner.py -q
```
Expected: PASS — schema/parity/loader/matching tests green, `test_catalog_matches_json_schema` green again, matcher_cases 23/23 (`test_matcher_eval_file_passes`).

- [x] **Step 5: Commit**

```bash
git add registry/semantic-types.yaml agent/tests/test_extraction_declarations.py
git commit -m "feat(declarative-intent): B1.3 registry Plant rewrite to named kinds + valueShapes.plantCode + regex justifications (version 2) — test_catalog_value_shapes_plant_code, EXPECTED_PLANT_MATCHERS pin; root cause: Plant matchers must move off free-form regex before contract freeze"
```

---

### Task 1.4: Validator — justification gate + regex count metric

**Files:**
- Modify: `scripts/validate_registry_contract.py` (`_validate_matcher` at line 214, catalog loop at lines 124–128, new `count_regex_matchers`, new `collect_deprecation_warnings` placeholder is NOT part of this task)
- Modify: `scripts/validate-registry-contract.py` (`main` at line 10)
- Modify: `agent/tests/test_extraction_declarations.py` (validator import block at line 221, append tests)

**Interfaces:**
- Consumes: task 1.3 registry data (all catalog regex matchers justified).
- Produces (later tasks rely on these):
  - `_validate_matcher(matcher, catalog_entries, context, require_justification=False)` — new keyword param.
  - `count_regex_matchers(contract: RegistryContract, catalog_entries: dict[str, dict]) -> tuple[int, int]` → `(catalog_count, capability_count)`.
  - CLI prints `regex matchers in use: N (semantic-type catalog M + capability-level K)` after "valid" — a count, never a gate.

- [x] **Step 1: Write the failing tests** (append to `agent/tests/test_extraction_declarations.py`; extend the import from `scripts.validate_registry_contract` with `count_regex_matchers`, `validate_extraction_declarations`)

```python
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
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `cd agent && python3 -m pytest tests/test_extraction_declarations.py -q -k "justification or regex_matcher_count"`
Expected: FAIL — `TypeError: _validate_matcher() got an unexpected keyword argument 'require_justification'` / `ImportError: cannot import name 'count_regex_matchers'`.

- [x] **Step 3: Implement the validator changes** in `scripts/validate_registry_contract.py`

Update `_validate_matcher` (line 214):

```python
def _validate_matcher(matcher: Any, catalog_entries: dict[str, dict], context: str, require_justification: bool = False) -> list[str]:
    """Resolve semanticType refs and guard every inline regex/keyword pattern."""
    if not isinstance(matcher, dict):
        return [f"{context}: matcher must be a mapping"]
    if matcher.get("kind") == "semanticType":
        ref = matcher.get("ref")
        if ref not in catalog_entries:
            return [f"{context}: semanticType ref not found in catalog: {ref}"]
        return []
    if require_justification and matcher.get("kind") == "regex":
        justification = matcher.get("justification")
        if not isinstance(justification, str) or not justification.strip():
            return [f"{context}: regex matcher requires a non-empty justification (escape hatch)"]
    pattern = matcher.get("pattern")
    if isinstance(pattern, str):
        guard_error = regex_backtracking_guard(pattern)
        if guard_error:
            return [f"{context}: {guard_error}"]
    return []
```

Update the catalog matcher loop in `validate_extraction_declarations` (lines 124–128) to pass `require_justification=True` (catalog-scoped gate; the capability-level `_validate_matcher` calls at line 196 stay unchanged — capability regexes are counted, not gated):

```python
    for entry_id, entry in catalog_entries.items():
        for matcher in (entry.get("matchers") or []) if isinstance(entry, dict) else []:
            errors.extend(
                _validate_matcher(
                    matcher,
                    catalog_entries,
                    f"semantic-type catalog entry {entry_id}",
                    require_justification=True,
                )
            )
```

Add the metric function after `validate_extraction_declarations`:

```python
def count_regex_matchers(contract: RegistryContract, catalog_entries: dict[str, dict]) -> tuple[int, int]:
    """Count regex matchers: (semantic-type catalog, capability-level).

    Observable metric only (Design §3.3): a count, never a gate. The
    justification gate applies to catalog regex matchers; capability-level
    regexes remain legal but visible.
    """
    catalog_count = sum(
        1
        for entry in catalog_entries.values()
        for matcher in (entry.get("matchers") or []) if isinstance(entry, dict)
        if isinstance(matcher, dict) and matcher.get("kind") == "regex"
    )
    capability_count = 0
    for capability in contract.capabilities:
        raw = capability.raw if isinstance(capability.raw, dict) else {}
        inputs = raw.get("inputs") if isinstance(raw.get("inputs"), list) else []
        for input_field in inputs:
            if not isinstance(input_field, dict):
                continue
            extraction = input_field.get("extraction")
            if not isinstance(extraction, dict):
                continue
            capability_count += sum(
                1
                for matcher in extraction.get("matchers") or []
                if isinstance(matcher, dict) and matcher.get("kind") == "regex"
            )
    return catalog_count, capability_count
```

- [x] **Step 4: Update the CLI** in `scripts/validate-registry-contract.py`

```python
#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

from validate_registry_contract import (
    count_regex_matchers,
    load_registry_contract,
    load_semantic_type_catalog,
    validate_registry_contract,
)


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 1:
        print("Usage: validate-registry-contract.py <registry-file>", file=sys.stderr)
        return 2
    repo_root = Path(".")
    contract = load_registry_contract(Path(args[0]))
    errors = validate_registry_contract(contract, repo_root=repo_root)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    catalog_entries, _catalog_errors = load_semantic_type_catalog(repo_root)
    catalog_count, capability_count = count_regex_matchers(contract, catalog_entries)
    print(
        f"regex matchers in use: {catalog_count + capability_count} "
        f"(semantic-type catalog {catalog_count} + capability-level {capability_count})"
    )
    print(f"Registry contract valid: {args[0]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [x] **Step 5: Run tests and the CLI to verify**

Run:
```bash
cd agent && python3 -m pytest tests/test_extraction_declarations.py -q
python3 scripts/validate-registry-contract.py registry/capabilities.yaml
```
Expected: tests PASS; CLI prints `regex matchers in use: 17 (semantic-type catalog 9 + capability-level 8)` followed by `Registry contract valid: registry/capabilities.yaml`, exit 0. (Counts verified against the post-1.3 registry: catalog = Plant 1 + MaterialNumber/Quantity/Unit/Date/PurchasingGroup/Vendor 1 each + PONumber 2 = 9; capability-level = 8 inline extraction regexes, unchanged by this batch.)

- [x] **Step 6: Commit**

```bash
git add scripts/validate_registry_contract.py scripts/validate-registry-contract.py agent/tests/test_extraction_declarations.py
git commit -m "feat(declarative-intent): B1.4 validator rejects un-justified catalog regex + regex count metric — test_unjustified_catalog_regex_rejected, test_justified_catalog_regex_accepted, test_regex_matcher_count_is_observable_metric; root cause: regex escape hatch must be gated and observable"
```

---

### Task 1.5: PR.CreateDraft.plant pattern + equivalence gate

**Files:**
- Modify: `registry/capabilities.yaml` (PR plant input, `pattern` after `maxLength: 4`)

**Interfaces:**
- Consumes: tasks 1.1–1.4.
- Produces: the PR plant input contract `^[A-Z0-9]{4}$` aligned with `plantCode`; B2/B3 build on this registry.

- [x] **Step 1: Pre-change grep gate** (Design §3.4)

Run:
```bash
grep -rn "工厂" evals/*.json evals/*.yaml | grep -vE "[A-Z0-9]{4}([^0-9A-Za-z]|$)"
grep -rnE "[a-z][0-9A-Za-z]{3}|[0-9A-Za-z]{5,}" evals/*.json evals/*.yaml | grep "工厂" || true
```
Expected: no hit pairs a PR plant value violating `^[A-Z0-9]{4}$` (lowercase or length != 4) with 工厂/在 context. All PR eval plant values are `1000`/`5100` (verified against `evals/pr_create_cases.json` and `evals/matcher_cases.yaml`). If a violating case is found, it may be updated ONLY with an explicit semantic justification, and that update must be noted in the commit message.

- [x] **Step 2: Add the pattern** to the PR.CreateDraft plant input (`registry/capabilities.yaml`, plant input at line ~383, after `maxLength: 4`):

```yaml
        maxLength: 4
        pattern: '^[A-Z0-9]{4}$'
```

Also update `test_pr_declaration_parity_constants` (line 477) so the parity constants pin the new contract (the registry change breaks the old assertion):

```python
    assert inputs["plant"]["pattern"] == "^[A-Z0-9]{4}$"
```

- [x] **Step 3: Verify the equivalence gates**

Run:
```bash
cd agent && python3 -m pytest tests/test_eval_runner.py tests/test_extraction_declarations.py -q
cd agent && python3 -m pytest tests/ -q
```
Expected: PASS — matcher_cases 23/23; full agent suite green (any pre-existing failures recorded in the closeout task 4.1 baseline, not introduced here).

- [x] **Step 4: Commit**

```bash
git add registry/capabilities.yaml agent/tests/test_extraction_declarations.py
git commit -m "feat(declarative-intent): B1.5 PR.CreateDraft.plant pattern ^[A-Z0-9]{4}\$ aligned with plantCode — test_pr_declaration_parity_constants; root cause: PR plant validation was looser than the shared shape; grep gate confirmed no eval case depends on loose behavior"
```

---

## B2 — Clarify de-enumeration

### Task 2.1: clarifyPrompt schema — strategy + maxRounds

**Files:**
- Modify: `schemas/extraction-declaration.schema.json` (`$defs.localePrompt` at lines 64–91)
- Modify: `schemas/capability.schema.json` (`$defs.localePrompt`, mirrored)
- Modify: `agent/sap_nexus_agent/registry_loader.py` (`ClarifyPromptConfig`, `_parse_clarify_prompt` at line 222)
- Modify: `scripts/validate_registry_contract.py` (`_clarify_locale_errors` at line 231)
- Modify: `agent/tests/test_extraction_declarations.py` (`INTENT_PARITY_MUTATIONS` at line 557, new tests)

**Interfaces:**
- Consumes: existing `ClarifyPromptConfig(cases, fallback_template)`.
- Produces (later tasks rely on these):
  - `ClarifyPromptConfig` gains `strategy: str | None = None`, `max_rounds: int | None = None`.
  - `_parse_clarify_prompt(raw)` accepts a strategy-only prompt (no cases, no fallback) and parses `maxRounds`.
  - `_clarify_locale_errors` treats `strategy` as covering every required input.
  - localePrompt schema (both files, identical): `strategy` enum `["groupByBindingKind"]`, `maxRounds` integer minimum 1 default 2, `cases` documented as optional override.

- [x] **Step 1: Write the failing tests** (append to `agent/tests/test_extraction_declarations.py`; extend `INTENT_PARITY_MUTATIONS`)

```python
INTENT_PARITY_MUTATIONS += [
    {"clarifyPrompt": {"zh-CN": {"strategy": "freeText"}}},                     # unknown strategy
    {"clarifyPrompt": {"zh-CN": {"strategy": "groupByBindingKind", "maxRounds": 0}}},  # maxRounds >= 1
]


def test_strategy_only_clarify_prompt_accepted():
    schema = _load("extraction-declaration.schema.json")
    jsonschema.validate(
        {**VALID_INTENT, "clarifyPrompt": {"zh-CN": {"strategy": "groupByBindingKind", "maxRounds": 2}}},
        schema,
    )


def test_loader_parses_strategy_and_max_rounds():
    from sap_nexus_agent.registry_loader import _parse_clarify_prompt

    prompt = _parse_clarify_prompt({"strategy": "groupByBindingKind", "maxRounds": 3})
    assert prompt is not None
    assert prompt.strategy == "groupByBindingKind"
    assert prompt.max_rounds == 3
    assert prompt.cases == () and prompt.fallback_template is None

    assert _parse_clarify_prompt({"cases": [{"missing": ["a"], "text": "t"}]}).strategy is None
    assert _parse_clarify_prompt({"fallback": {"template": "t"}}).max_rounds is None
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `cd agent && python3 -m pytest tests/test_extraction_declarations.py -q -k "strategy or clarify_prompt or clarify_locale or parity"`
Expected: FAIL — unknown `strategy` property rejected by `additionalProperties: false` on both schemas; `_parse_clarify_prompt` returns None for strategy-only input (`ClarifyPromptConfig` has no strategy/max_rounds attributes).

- [x] **Step 3: Implement the schema changes**

In `schemas/extraction-declaration.schema.json`, replace `$defs.localePrompt` (lines 64–91):

```json
    "localePrompt": {
      "type": "object",
      "additionalProperties": false,
      "properties": {
        "strategy": {
          "enum": ["groupByBindingKind"],
          "description": "Rendering strategy: missing fields are grouped by binding source kind; at most one prompt per group per round, rendered from fieldNames display names."
        },
        "maxRounds": {
          "type": "integer",
          "minimum": 1,
          "default": 2,
          "description": "Clarify round budget per capability; exhaustion degrades to the fallback template."
        },
        "cases": {
          "type": "array",
          "items": {
            "type": "object",
            "additionalProperties": false,
            "required": ["missing", "text"],
            "properties": {
              "missing": {
                "type": "array",
                "minItems": 1,
                "items": {"type": "string", "minLength": 1}
              },
              "text": {"type": "string", "minLength": 1}
            }
          },
          "description": "Optional exact missing-set override, checked before strategy rendering."
        },
        "fallback": {
          "type": "object",
          "additionalProperties": false,
          "required": ["template"],
          "properties": {"template": {"type": "string", "minLength": 1}},
          "description": "Template rendered when the strategy budget is exhausted (or when no strategy is declared and no case matches)."
        }
      }
    }
```

Mirror the identical change into `schemas/capability.schema.json` `$defs.localePrompt` (the drift-guard parity tests require both to accept/reject the same instances).

- [x] **Step 4: Implement the loader change** in `agent/sap_nexus_agent/registry_loader.py`

Extend `ClarifyPromptConfig` (add the two fields with defaults) and replace `_parse_clarify_prompt`:

```python
def _parse_clarify_prompt(raw: object) -> ClarifyPromptConfig | None:
    if not isinstance(raw, dict):
        return None
    cases = tuple(
        c for c in (_parse_clarify_case(x) for x in raw.get("cases") or []) if c
    )
    fallback = raw.get("fallback")
    fallback_template = (
        str(fallback["template"])
        if isinstance(fallback, dict) and fallback.get("template") is not None
        else None
    )
    strategy = raw.get("strategy")
    if not cases and fallback_template is None and strategy is None:
        return None
    max_rounds = raw.get("maxRounds")
    return ClarifyPromptConfig(
        cases=cases,
        fallback_template=fallback_template,
        strategy=str(strategy) if strategy is not None else None,
        max_rounds=int(max_rounds) if isinstance(max_rounds, int) else None,
    )
```

- [x] **Step 5: Implement the validator change** in `scripts/validate_registry_contract.py`

Update `_clarify_locale_errors` (line 231) — strategy rendering covers every required input of the group, so no coverage error is reported:

```python
        fallback = prompt.get("fallback")
        has_fallback = isinstance(fallback, dict) and bool(fallback.get("template"))
        strategy = prompt.get("strategy")
        covered: set[str] = set()
        for case in prompt.get("cases") or []:
            if isinstance(case, dict):
                covered.update(str(name) for name in case.get("missing") or [])
        if strategy is not None:
            # groupByBindingKind renders every required input of a group; with
            # a single userUtterance group (all current declarations) that is
            # every required input of the capability.
            covered.update(required_fields)
        missing = sorted(
            name for name in required_fields if name not in covered and not has_fallback
        )
```

- [x] **Step 6: Run the tests and CLI to verify**

Run:
```bash
cd agent && python3 -m pytest tests/test_extraction_declarations.py -q
python3 scripts/validate-registry-contract.py registry/capabilities.yaml
```
Expected: PASS — parity mutation tests (both schemas reject/accept identically, including the new strategy/maxRounds mutations), loader tests pass, validator unchanged for the current registry (PR still covered via fallback; strategy not yet in data).

- [x] **Step 7: Commit**

```bash
git add schemas/extraction-declaration.schema.json schemas/capability.schema.json agent/sap_nexus_agent/registry_loader.py scripts/validate_registry_contract.py agent/tests/test_extraction_declarations.py
git commit -m "feat(declarative-intent): B2.1 clarifyPrompt strategy groupByBindingKind + maxRounds (default 2), cases as optional override — test_strategy_only_clarify_prompt_accepted, test_loader_parses_strategy_and_max_rounds, INTENT_PARITY_MUTATIONS strategy cases; root cause: hand-enumerated case combinations do not scale to six required fields"
```

---

### Task 2.2: PR.CreateDraft clarifyPrompt restructure

**Files:**
- Modify: `registry/capabilities.yaml` (PR.CreateDraft clarifyPrompt at lines 364–367)
- Modify: `agent/tests/test_extraction_declarations.py` (`test_pr_declaration_parity_constants` at line 477)

**Interfaces:**
- Consumes: task 2.1 schema/loader.
- Produces: PR declares `strategy: groupByBindingKind` + `maxRounds: 2`; Inventory keeps its two cases entries as the override mechanism (untouched).

- [x] **Step 1: Restructure the PR declaration**

Replace the PR.CreateDraft clarifyPrompt block (currently fallback-only):

```yaml
      clarifyPrompt:
        zh-CN:
          strategy: groupByBindingKind
          maxRounds: 2
          fallback:
            template: '请提供: {fields}'
```

(`MM.Inventory.GetAvailability` and `MM.PurchaseOrder.GetList` clarifyPrompt blocks stay unchanged.)

- [x] **Step 2: Update the parity constants** in `agent/tests/test_extraction_declarations.py`

Replace line 488:

```python
    assert intent["clarifyPrompt"]["zh-CN"]["strategy"] == "groupByBindingKind"
    assert intent["clarifyPrompt"]["zh-CN"]["maxRounds"] == 2
    assert intent["clarifyPrompt"]["zh-CN"]["fallback"] == {"template": "请提供: {fields}"}
```

- [x] **Step 3: Run the tests to verify**

Run: `cd agent && python3 -m pytest tests/test_extraction_declarations.py tests/test_clarify_rendering.py -q`
Expected: PASS — parity constants updated; rendering behavior is unchanged in round 1 because the strategy template equals the fallback template ("请提供: {fields}"), so `test_pr_fallback_join_template` and `test_sticky_clarify_rendered_from_declaration` stay green.

- [x] **Step 4: Commit**

```bash
git add registry/capabilities.yaml agent/tests/test_extraction_declarations.py
git commit -m "feat(declarative-intent): B2.2 PR.CreateDraft clarifyPrompt -> strategy groupByBindingKind + maxRounds 2, no hand-written cases — test_pr_declaration_parity_constants; root cause: six required fields made case enumeration unmanageable"
```

---

### Task 2.3: Strategy rendering in `clarify.py`

**Files:**
- Modify: `agent/sap_nexus_agent/extraction/clarify.py` (`render_clarify` at line 32; add `_prompt_for_locale`, `render_clarify_with_kind`, `_missing_by_group`, `render_clarify_round`)
- Modify: `agent/tests/test_clarify_rendering.py`

**Interfaces:**
- Consumes: `ClarifyPromptConfig.strategy/max_rounds` (2.1), `InputDescriptor.binding` sources for grouping (populated from task 3.2; until then the loader normalizes extraction → userUtterance group, so PR already groups correctly).
- Produces (later tasks rely on these):
  - `render_clarify(cap, missing, locale=ACTIVE_LOCALE) -> str | None` — signature unchanged; delegates to `render_clarify_with_kind`.
  - `render_clarify_with_kind(cap, missing, locale=ACTIVE_LOCALE, clarify_rounds=None) -> tuple[str | None, str]` — kind in `{"none", "cases", "strategy", "fallback"}`.
  - `render_clarify_round(cap, missing, clarify_rounds, locale=ACTIVE_LOCALE) -> tuple[str | None, Mapping[str, int] | None]` — returns the incremented round counter when a strategy prompt was rendered, else `None`.
  - `_missing_by_group(cap, missing) -> dict[str, list[str]]` — group key is the input's first binding source kind; default `"userUtterance"` when the input has no binding.

- [x] **Step 1: Write the failing tests** (append to `agent/tests/test_clarify_rendering.py`)

```python
def test_pr_strategy_renders_one_prompt_per_group():
    pr = _cap("MM.PR.CreateDraft")
    # One prompt carries all missing fields of the (single) group.
    assert render_clarify(pr, ["quantity"]) == "请提供: 数量"
    assert render_clarify(pr, ["quantity", "unit"]) == "请提供: 数量, 单位"
    assert render_clarify(
        pr, ["material", "plant", "quantity", "unit", "delivery_date", "purchasing_group"]
    ) == "请提供: 物料编号, 工厂, 数量, 单位, 交货日期, 采购组"


def test_strategy_round_budget_respected_and_degrades_to_fallback():
    from sap_nexus_agent.extraction.clarify import render_clarify_round

    pr = _cap("MM.PR.CreateDraft")
    missing = ["plant", "unit", "delivery_date"]
    text, rounds = render_clarify_round(pr, missing, {})
    assert text == "请提供: 工厂, 单位, 交货日期"
    assert rounds == {"MM.PR.CreateDraft": 1}
    text, rounds = render_clarify_round(pr, missing, rounds)
    assert text == "请提供: 工厂, 单位, 交货日期"
    assert rounds == {"MM.PR.CreateDraft": 2}
    # Budget exhausted: degrade to the declared fallback template; no increment.
    text, rounds = render_clarify_round(pr, missing, rounds)
    assert text == "请提供: 工厂, 单位, 交货日期"
    assert rounds is None


def test_strategy_rounds_reset_on_capability_switch():
    from sap_nexus_agent.extraction.clarify import render_clarify_round

    pr = _cap("MM.PR.CreateDraft")
    text, rounds = render_clarify_round(pr, ["plant"], {"MM.Inventory.GetAvailability": 2})
    assert rounds == {"MM.PR.CreateDraft": 1}  # different capability: reset, then count


def test_strategy_groups_by_binding_source_kind(tmp_path):
    from sap_nexus_agent.extraction.clarify import render_clarify_with_kind
    from sap_nexus_agent.registry_loader import load_intent_catalog

    registry = tmp_path / "registry"
    registry.mkdir()
    (registry / "semantic-types.yaml").write_text(
        "version: 2\nsemanticTypes:\n  - id: MaterialNumber\n    description: synthetic\n"
        "    priority: 1\n    matchers:\n      - kind: regex\n        pattern: '[A-Z0-9]+'\n"
        "        justification: synthetic fixture\n",
        encoding="utf-8",
    )
    (registry / "capabilities.yaml").write_text(
        "capabilities:\n"
        "  - capabilityId: Test.Groups\n"
        "    status: active\n"
        "    intent:\n"
        "      intentName: test_groups\n"
        "      primaryKeywords: [测试]\n"
        "      fieldNames:\n"
        "        zh-CN:\n"
        "          vendor: 供应商\n"
        "          quantity: 数量\n"
        "      clarifyPrompt:\n"
        "        zh-CN:\n"
        "          strategy: groupByBindingKind\n"
        "          maxRounds: 2\n"
        "          cases:\n"
        "            - missing: [vendor]\n"
        "              text: '请提供供应商。'\n"
        "          fallback:\n"
        "            template: '请提供: {fields}'\n"
        "    inputs:\n"
        "      - name: vendor\n"
        "        semanticName: supplier\n"
        "        semanticType: sapnexus:Supplier\n"
        "        bindingKind: identifier\n"
        "        required: true\n"
        "        type: string\n"
        "        sapParameter: VENDOR\n"
        "        binding:\n"
        "          sources:\n"
        "            - kind: userUtterance\n"
        "              matchers:\n"
        "                - kind: regex\n"
        "                  pattern: '供应商\\s*([A-Z0-9]+)'\n"
        "      - name: quantity\n"
        "        semanticName: quantity\n"
        "        semanticType: sapnexus:Quantity\n"
        "        bindingKind: identifier\n"
        "        required: true\n"
        "        type: number\n"
        "        sapParameter: QTY\n"
        "        binding:\n"
        "          sources:\n"
        "            - kind: default\n"
        "              value: '1'\n",
        encoding="utf-8",
    )
    catalog = load_intent_catalog(str(tmp_path))
    cap = catalog.find("Test.Groups")
    assert cap is not None

    text, kind = render_clarify_with_kind(cap, ["vendor", "quantity"])
    assert kind == "strategy"
    # One prompt per group, groups in first-seen order of missing fields.
    assert text == "请提供: 供应商 请提供: 数量"

    # Explicit cases override strategy rendering (spec scenario).
    text, kind = render_clarify_with_kind(cap, ["vendor"])
    assert (text, kind) == ("请提供供应商。", "cases")
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `cd agent && python3 -m pytest tests/test_clarify_rendering.py -q`
Expected: FAIL — no `strategy` handling in `render_clarify`: PR (strategy + fallback, no cases) falls through to the fallback template in round 1, so `render_clarify_round`/`render_clarify_with_kind` don't exist (ImportError) and the group test's `Test.Groups` renders fallback, not grouped prompts.

- [x] **Step 3: Implement the rendering** in `agent/sap_nexus_agent/extraction/clarify.py`

Add the constants and imports at the top (extend the existing `from typing import Final, Protocol` import with `Mapping`):

```python
ACTIVE_LOCALE: Final = "zh-CN"
_STRATEGY_TEMPLATE: Final = "请提供: {fields}"
_STRATEGY_MAX_ROUNDS_DEFAULT: Final = 2
```

Add `_prompt_for_locale` after `_field_names`:

```python
def _prompt_for_locale(cap: CapabilityDescriptor, locale: str):
    intent_config = cap.intent_config
    if intent_config is None:
        return None
    for loc, cfg in intent_config.clarify_prompt:
        if loc == locale:
            return cfg
    return None
```

Replace `render_clarify` (line 32) with the delegation plus the new functions:

```python
def render_clarify(
    cap: CapabilityDescriptor,
    missing: list[str],
    locale: str = ACTIVE_LOCALE,
) -> str | None:
    text, _kind = render_clarify_with_kind(cap, missing, locale=locale)
    return text


def render_clarify_with_kind(
    cap: CapabilityDescriptor,
    missing: list[str],
    locale: str = ACTIVE_LOCALE,
    clarify_rounds: Mapping[str, int] | None = None,
) -> tuple[str | None, str]:
    """Render a clarification; return (text, kind) with kind in
    {"none", "cases", "strategy", "fallback"}.

    Order (Design §3.5): exact cases override -> strategy rendering under the
    round budget -> declared fallback template.
    """
    if not missing or cap.intent_config is None:
        return None, "none"

    prompt = _prompt_for_locale(cap, locale)
    if prompt is None:
        if locale != ACTIVE_LOCALE:
            names = _field_names(cap, ACTIVE_LOCALE)
            fields = ", ".join(names.get(name, name) for name in missing)
            return f"请提供: {fields}", "fallback"
        return None, "none"

    missing_set = frozenset(missing)
    for case in prompt.cases:
        if case.missing == missing_set:
            return case.text, "cases"

    if prompt.strategy is not None:
        rounds = clarify_rounds or {}
        max_rounds = (
            prompt.max_rounds
            if prompt.max_rounds is not None
            else _STRATEGY_MAX_ROUNDS_DEFAULT
        )
        if rounds.get(cap.capability_id, 0) < max_rounds:
            template = prompt.fallback_template or _STRATEGY_TEMPLATE
            parts = []
            for _group, fields in _missing_by_group(cap, missing).items():
                names = _field_names(cap, locale)
                parts.append(
                    template.replace("{fields}", ", ".join(names.get(name, name) for name in fields))
                )
            return " ".join(parts), "strategy"

    if prompt.fallback_template is None:
        return None, "none"
    names = _field_names(cap, locale)
    fields = ", ".join(names.get(name, name) for name in missing)
    return prompt.fallback_template.replace("{fields}", fields), "fallback"


def render_clarify_round(
    cap: CapabilityDescriptor,
    missing: list[str],
    clarify_rounds: Mapping[str, int] | None,
    locale: str = ACTIVE_LOCALE,
) -> tuple[str | None, Mapping[str, int] | None]:
    """Render against the round budget.

    Returns (text, next_rounds): next_rounds carries the incremented counter
    for the capability when a strategy prompt was rendered, else None
    (fallback rendering does not increment - the budget is already exhausted).
    """
    text, kind = render_clarify_with_kind(
        cap, missing, locale=locale, clarify_rounds=clarify_rounds
    )
    if kind != "strategy":
        return text, None
    rounds = dict(clarify_rounds or {})
    if cap.capability_id not in rounds:
        # Coordinator ruling (2026-08-20): reset the budget when the turn's
        # capability is not yet tracked (pins test_strategy_rounds_reset_on_capability_switch).
        # The sticky callers (2.4) reset before calling; this internal reset
        # is redundant-but-harmless there and makes the function total.
        rounds = {}
    rounds[cap.capability_id] = rounds.get(cap.capability_id, 0) + 1
    return text, rounds


def _missing_by_group(cap: CapabilityDescriptor, missing: list[str]) -> dict[str, list[str]]:
    """Group missing fields by their input's first binding source kind."""
    groups: dict[str, list[str]] = {}
    for name in missing:
        group = "userUtterance"
        inp = next((i for i in cap.inputs if i.name == name), None)
        # Coordinator ruling (2026-08-20): InputDescriptor.binding lands in task 3.2;
        # until then every input falls into the default userUtterance group
        # (plan Interfaces: "until then the loader normalizes extraction →
        # userUtterance group"). getattr keeps 2.3 tests green pre-3.2.
        binding = getattr(inp, "binding", None)
        if binding is not None and binding.sources:
            group = binding.sources[0].kind
        groups.setdefault(group, []).append(name)
    return groups
```

- [x] **Step 4: Run the tests to verify they pass**

Run: `cd agent && python3 -m pytest tests/test_clarify_rendering.py -q`
Expected: PASS — all new tests plus the pre-existing ones (`test_pr_fallback_join_template`, `test_sticky_clarify_rendered_from_declaration`, `test_inventory_cases_exact_missing_sets`, `test_po_filter_case`, `test_missing_locale_falls_back_to_names`, rephrase tests).
Coordinator ruling (2026-08-20): `test_strategy_groups_by_binding_source_kind`'s grouping assertion is transiently red until task 3.2 lands `InputDescriptor.binding` (the test's synthetic registry declares `binding.sources`, which the loader cannot parse before 3.2; the cases-override assertion within the same test passes at 2.3). This is an extension of the documented transient-red window; task 3.2's regression gate turns it green. Do not weaken the test.

- [x] **Step 5: Commit**

```bash
git add agent/sap_nexus_agent/extraction/clarify.py agent/tests/test_clarify_rendering.py
git commit -m "feat(declarative-intent): B2.3 strategy rendering groupByBindingKind with cases-override-first and budget-aware fallback — test_pr_strategy_renders_one_prompt_per_group, test_strategy_round_budget_respected_and_degrades_to_fallback, test_strategy_rounds_reset_on_capability_switch, test_strategy_groups_by_binding_source_kind; root cause: clarify copy must be derived from declarations, not enumerated"
```

---

### Task 2.4: Round-budget tracking in turn state

**Files:**
- Modify: `agent/sap_nexus_agent/read_context.py` (`ConversationReadState` at line 465)
- Modify: `agent/sap_nexus_agent/intent.py` (`IntentParseResult`)
- Modify: `agent/sap_nexus_agent/llm_intent.py` (`resolve_with_context` at line 533)
- Modify: `agent/sap_nexus_agent/extraction/engine.py` (`sticky_parse` at line 163)
- Modify: `agent/sap_nexus_agent/orchestrator.py` (`_resolved_non_read_outcome` at line 958)
- Modify: `agent/tests/test_read_context.py`
- Modify: `agent/tests/test_clarify_rendering.py`

**Interfaces:**
- Consumes: `render_clarify_round` (2.3).
- Produces (later tasks rely on these):
  - `ConversationReadState.clarify_rounds: Mapping[str, int]` (default `{}`); `to_dict()` includes `"clarifyRounds"` ONLY when non-empty; `from_dict()` maps absent → `{}`.
  - `IntentParseResult.clarify_rounds: Mapping[str, int] | None = None` (last field, defaulted — all existing constructions unchanged).
  - `resolve_with_context` and `engine.sticky_parse` set `clarify_rounds` on the result when a strategy prompt was rendered; reset the counter when the turn's capability differs from the accumulated one.
  - `orchestrator._resolved_non_read_outcome` persists the parsed rounds into `next_state` for CLARIFY decisions.

- [x] **Step 1: Write the failing tests** (append to `agent/tests/test_read_context.py`)

```python
def test_read_state_clarify_rounds_round_trip_and_omitted_when_empty():
    from sap_nexus_agent.read_context import ConversationReadState

    state = ConversationReadState(active_frame=None, pending_interaction=None, state_version=0)
    assert "clarifyRounds" not in state.to_dict()  # legacy payloads round-trip unchanged

    state = ConversationReadState(
        active_frame=None,
        pending_interaction=None,
        state_version=0,
        clarify_rounds={"MM.PR.CreateDraft": 2},
    )
    assert state.to_dict()["clarifyRounds"] == {"MM.PR.CreateDraft": 2}
    assert ConversationReadState.from_dict(state.to_dict()).clarify_rounds == {
        "MM.PR.CreateDraft": 2
    }

    legacy = {"activeFrame": None, "pendingInteraction": None, "stateVersion": 0, "recentFrames": []}
    assert ConversationReadState.from_dict(legacy).clarify_rounds == {}
```

Also append to `agent/tests/test_clarify_rendering.py`:

```python
def test_sticky_clarify_rounds_capped_via_read_state():
    from sap_nexus_agent.conversation_context import ConversationContext, LastContext
    from sap_nexus_agent.llm_intent import resolve_with_context
    from sap_nexus_agent.read_context import ConversationReadState

    def _sticky(rounds):
        context = ConversationContext(
            history=(),
            last_context=LastContext(
                capability_id="MM.PR.CreateDraft",
                decision_type="CLARIFY",
                parameters={"material": "DEMOA2", "quantity": "50"},
                missing_parameters=["plant", "unit", "delivery_date", "purchasing_group"],
            ),
            read_state=ConversationReadState(
                active_frame=None,
                pending_interaction=None,
                state_version=1,
                clarify_rounds=rounds or {},
            ),
        )
        return resolve_with_context("工厂 1000", context, load_intent_catalog())

    first = _sticky({})
    assert first.clarification == "请提供: 单位, 交货日期, 采购组"
    assert first.clarify_rounds == {"MM.PR.CreateDraft": 1}

    second = _sticky(first.clarify_rounds)
    assert second.clarify_rounds == {"MM.PR.CreateDraft": 2}

    third = _sticky(second.clarify_rounds)
    # Budget exhausted: fallback template, rounds not incremented.
    assert third.clarification == "请提供: 单位, 交货日期, 采购组"
    assert third.clarify_rounds is None
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `cd agent && python3 -m pytest tests/test_read_context.py tests/test_clarify_rendering.py -q`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'clarify_rounds'` and `AttributeError: 'IntentParseResult' object has no attribute 'clarify_rounds'`.

- [x] **Step 3: Implement `ConversationReadState.clarify_rounds`** in `agent/sap_nexus_agent/read_context.py`

Add the field (ensure `field` is in the module's `from dataclasses import ...`):

```python
@dataclass(frozen=True)
class ConversationReadState:
    active_frame: ReadContextFrame | None
    pending_interaction: PendingInteraction | None
    state_version: int
    recent_frames: tuple[ReadContextFrame, ...] = ()
    clarify_rounds: Mapping[str, int] = field(default_factory=dict)
```

In `__post_init__`, after the `recent_frames` validation, add:

```python
        if not isinstance(self.clarify_rounds, Mapping):
            raise ValueError("ConversationReadState.clarify_rounds must be a mapping")
        if not all(
            isinstance(cap_id, str)
            and isinstance(rounds, int)
            and not isinstance(rounds, bool)
            and rounds >= 0
            for cap_id, rounds in self.clarify_rounds.items()
        ):
            raise ValueError(
                "ConversationReadState.clarify_rounds must map capabilityId to non-negative integers"
            )
        object.__setattr__(self, "clarify_rounds", dict(self.clarify_rounds))
```

Replace `to_dict` (line 494):

```python
    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "activeFrame": self.active_frame.to_dict() if self.active_frame else None,
            "pendingInteraction": self.pending_interaction.to_dict() if self.pending_interaction else None,
            "stateVersion": self.state_version,
            "recentFrames": [frame.to_dict() for frame in self.recent_frames],
        }
        if self.clarify_rounds:
            payload["clarifyRounds"] = dict(sorted(self.clarify_rounds.items()))
        return payload
```

In `from_dict` (line 502), add the parsing before the `return cls(...)`:

```python
        clarify_rounds = raw.get("clarifyRounds")
        rounds: dict[str, int] = {}
        if isinstance(clarify_rounds, Mapping):
            rounds = {str(cap_id): int(count) for cap_id, count in clarify_rounds.items()}
        return cls(
            active_frame=ReadContextFrame.from_dict(active_frame)
            if isinstance(active_frame, Mapping)
            else None,
            pending_interaction=PendingInteraction.from_dict(pending)
            if isinstance(pending, Mapping)
            else None,
            state_version=raw.get("stateVersion", 0),  # type: ignore[arg-type]
            recent_frames=tuple(ReadContextFrame.from_dict(frame) for frame in recent_frames),
            clarify_rounds=rounds,
        )
```

- [x] **Step 4: Implement `IntentParseResult.clarify_rounds`** in `agent/sap_nexus_agent/intent.py`

Append the field (last, defaulted) to the frozen dataclass; add `Mapping` to the module's typing imports if not present:

```python
    matched_intents: tuple[MatchedIntent, ...] = ()
    clarify_rounds: Mapping[str, int] | None = None
```

- [x] **Step 5: Wire the budget into `resolve_with_context`** in `agent/sap_nexus_agent/llm_intent.py`

Replace the final block of `resolve_with_context` (currently `clarification = render_clarify(descriptor, missing)` at line 618 through the `return IntentParseResult(...)`):

```python
    prev_rounds: dict[str, int] = {}
    if context.read_state is not None:
        prev_rounds = dict(context.read_state.clarify_rounds)
    if prev_rounds and cap_id not in prev_rounds:
        prev_rounds = {}  # the turn selected a different capability: reset the budget

    clarification, next_rounds = render_clarify_round(descriptor, missing, prev_rounds)
    result = IntentParseResult(
        intent=None,
        capability_id=cap_id,
        parameters=merged,
        missing_parameters=missing,
        clarification=clarification,
        contains_rfc_name=False,
        contains_odata_override=False,
        matched_intents=[
            MatchedIntent(capability_id=cap_id, parameters=merged, missing=list(missing))
        ],
    )
    if next_rounds is not None:
        result = replace(result, clarify_rounds=next_rounds)
    return result
```

Update the `render_clarify` import at the top of `llm_intent.py` to include `render_clarify_round` (import both; `render_clarify` remains used by other callers in the module, if any — keep it imported).

- [x] **Step 6: Wire the budget into `engine.sticky_parse`** in `agent/sap_nexus_agent/extraction/engine.py`

Replace the final return (line 181, `return _sticky_result(cap_id, merged, missing, render_clarify(descriptor, missing))`):

```python
    prev_rounds: dict[str, int] = {}
    if context.read_state is not None:
        prev_rounds = dict(context.read_state.clarify_rounds)
    if prev_rounds and cap_id not in prev_rounds:
        prev_rounds = {}
    clarification, next_rounds = render_clarify_round(descriptor, missing, prev_rounds)
    result = _sticky_result(cap_id, merged, missing, clarification)
    if next_rounds is not None:
        result = replace(result, clarify_rounds=next_rounds)
    return result
```

Ensure `from dataclasses import replace` and `render_clarify_round` are imported in `engine.py` (add `replace` to the dataclasses import; change the clarify import to include `render_clarify_round`).

- [x] **Step 7: Persist rounds in the orchestrator** — in `agent/sap_nexus_agent/orchestrator.py`, modify `_resolved_non_read_outcome` (line 970):

```python
    parsed_rounds = getattr(parsed, "clarify_rounds", None)
    next_state = ConversationReadState(
        active_frame=prior_state.active_frame,
        pending_interaction=None,
        state_version=prior_state.state_version + 1,
        recent_frames=prior_state.recent_frames,
        clarify_rounds=dict(parsed_rounds) if parsed_rounds else dict(prior_state.clarify_rounds),
    )
```

`_bound_pending_outcome` (line 914) stays untouched — CLARIFY decisions never route through it.

- [x] **Step 8: Run the tests to verify**

Run: `cd agent && python3 -m pytest tests/test_read_context.py tests/test_clarify_rendering.py tests/test_llm_intent.py tests/test_orchestrator.py -q`
Expected: PASS — new round-trip and sticky-budget tests; the legacy round-trip test (`test_read_state_and_conversation_context_round_trip_without_legacy_json_changes`) stays green because `clarifyRounds` is omitted when empty; orchestrator CLARIFY tests stay green.
Note: if any `test_llm_intent.py`/`test_orchestrator.py` test asserts full `IntentParseResult` equality on a sticky result, add `clarify_rounds=None` to the expected literal — the budget only populates the field on sticky CLARIFY turns.

- [x] **Step 9: Commit**

```bash
git add agent/sap_nexus_agent/read_context.py agent/sap_nexus_agent/intent.py agent/sap_nexus_agent/llm_intent.py agent/sap_nexus_agent/extraction/engine.py agent/sap_nexus_agent/orchestrator.py agent/tests/test_read_context.py agent/tests/test_clarify_rendering.py
git commit -m "feat(declarative-intent): B2.4 durable clarify round budget in ConversationReadState, sticky path increments and resets on capability switch — test_read_state_clarify_rounds_round_trip_and_omitted_when_empty, test_sticky_clarify_rounds_capped_via_read_state; root cause: clarify loops had no durable budget"
```

---

### Task 2.5: B2 tests — PR missing 1 / 2 / 3+ fields

**Files:**
- Modify: `agent/tests/test_clarify_rendering.py` (already extended by 2.3/2.4; add the explicit scenario test below)

**Interfaces:**
- Consumes: 2.1–2.4.
- Produces: the B2 contract evidence: rounds never exceed `maxRounds`; one prompt carries all missing fields of a group; cases override still wins.

- [x] **Step 1: Write the final B2 scenario tests**

```python
def test_pr_missing_1_2_3_plus_fields_rounds_never_exceed_max_rounds():
    from sap_nexus_agent.extraction.clarify import render_clarify_round

    pr = _cap("MM.PR.CreateDraft")
    missing = ["quantity"]
    rounds = {}
    for _ in range(5):
        text, next_rounds = render_clarify_round(pr, missing, rounds)
        assert text is not None
        if next_rounds is None:
            break
        assert next_rounds["MM.PR.CreateDraft"] <= 2  # never exceeds maxRounds
        rounds = next_rounds
    else:
        raise AssertionError("strategy prompt rendered more than maxRounds times")
    # The loop above breaks only via budget exhaustion; assert it happened.
    assert rounds == {"MM.PR.CreateDraft": 2}


def test_inventory_cases_still_override_strategy_path():
    inv = _cap("MM.Inventory.GetAvailability")
    # Inventory declares cases + fallback (no strategy): the exact-set override
    # is the main path and must stay intact (spec: cases override checked first).
    assert render_clarify(inv, ["material"]) == "请提供要查询的物料编号。"
    assert render_clarify(inv, ["plant"]) == "请提供要查询的工厂。"
    assert render_clarify(inv, ["material", "plant"]) == "请提供要查询的物料编号和工厂。"
    assert render_clarify(inv, []) is None
```

- [x] **Step 2: Run to verify fail then pass**

Run: `cd agent && python3 -m pytest tests/test_clarify_rendering.py -q`
Expected: PASS (these tests are already green after 2.3/2.4 — run them to confirm; if they fail, they pin a regression introduced between 2.3 and 2.5, fix the rendering, do not weaken the tests).

- [x] **Step 3: Run the full agent suite**

Run: `cd agent && python3 -m pytest tests/ -q`
Expected: PASS.

- [x] **Step 4: Commit**

```bash
git add agent/tests/test_clarify_rendering.py
git commit -m "test(declarative-intent): B2.5 PR missing 1/2/3+ fields — test_pr_missing_1_2_3_plus_fields_rounds_never_exceed_max_rounds, test_inventory_cases_still_override_strategy_path; root cause: no pin that rounds never exceed maxRounds"
```

---

## B3 — Extraction generalized to binding

### Task 3.1: binding.sources[] schema + deprecated extraction + validator warning

**Files:**
- Modify: `schemas/extraction-declaration.schema.json` (`definitions.inputBinding`, `$defs.bindingSource`, deprecated description on `inputExtraction`)
- Modify: `schemas/capability.schema.json` (`$defs.inputBindingBlock` mirror, `ioField.binding` property, deprecated description on `extractionBlock`)
- Modify: `scripts/validate_registry_contract.py` (binding validation + `collect_deprecation_warnings`)
- Modify: `scripts/validate-registry-contract.py` (print warnings)
- Modify: `agent/tests/test_extraction_declarations.py`

**Interfaces:**
- Consumes: task 2.1 localePrompt changes (shared defs file).
- Produces (later tasks rely on these):
  - Schema `definitions.inputBinding` (extraction-declaration) / `$defs.inputBindingBlock` (capability, identical): `{sources[], elicitIfMissing, priority, excludes, resolver, when, requiredWhen, reaskSuspect}`, `required: ["sources"]`.
  - Schema `$defs.bindingSource`: `kind` in `["userUtterance", "capabilityOutput", "default"]` with kind-specific requirements: userUtterance→`matchers` (minItems 1), capabilityOutput→`factType`+`field`, default→`value`; `additionalProperties: false`.
  - Validator: binding blocks validated against `inputBinding`; matchers inside userUtterance sources validated by `_validate_matcher`; `binding`+`extraction` together → error; `collect_deprecation_warnings(contract) -> list[str]` with the migration text; CLI prints `warning: ...` lines.

- [x] **Step 1: Write the failing tests** (append to `agent/tests/test_extraction_declarations.py`)

```python
VALID_BINDING = {
    "sources": [
        {"kind": "userUtterance", "matchers": [{"kind": "semanticType", "ref": "MaterialNumber"}]},
        {"kind": "capabilityOutput", "factType": "vendor", "field": "vendor"},
        {"kind": "default", "value": "K"},
    ],
    "elicitIfMissing": True,
    "priority": 10,
    "excludes": ["plant"],
    "resolver": "text",
    "when": {"field": "acct_assgn_cat", "equals": "K"},
    "requiredWhen": {"field": "acct_assgn_cat", "equals": "K"},
    "reaskSuspect": True,
}

BINDING_PARITY_MUTATIONS = [
    {},
    {"sources": []},                                                          # at least one source
    {"sources": [{"kind": "embedding"}]},                                     # unknown kind
    {"sources": [{"kind": "userUtterance"}]},                                 # needs matchers
    {"sources": [{"kind": "capabilityOutput", "field": "x"}]},                # needs factType
    {"sources": [{"kind": "default"}]},                                       # needs value
    {"sources": [{"kind": "default", "value": "1", "matchers": [{"kind": "regex", "pattern": "x"}]}]},  # source extra property
    {"elicitIfMissing": "nope"},
    {"priority": "high"},
    {"resolver": "decimal"},
    {"when": {"field": "x"}},
    {"unknownProperty": True},
]


def test_valid_input_binding_passes():
    schema = _load("extraction-declaration.schema.json")
    jsonschema.validate(VALID_BINDING, schema["definitions"]["inputBinding"])


@pytest.mark.parametrize("mutation", BINDING_PARITY_MUTATIONS)
def test_input_binding_block_parity_with_extraction_declaration(mutation):
    # Drift guard: the embedded $defs.inputBindingBlock in capability.schema.json
    # must accept/reject exactly what extraction-declaration.schema.json's
    # definitions.inputBinding accepts/rejects.
    schema = _load("extraction-declaration.schema.json")
    _assert_block_parity(_mutated(VALID_BINDING, mutation), schema, "inputBindingBlock")


def test_capability_schema_io_field_accepts_binding():
    capability_schema = _load("capability.schema.json")
    io_field = {
        "name": "vendor",
        "semanticType": "sapnexus:Supplier",
        "bindingKind": "identifier",
        "required": True,
        "type": "string",
        "sapParameter": "VENDOR",
        "binding": {"sources": [{"kind": "userUtterance", "matchers": [{"kind": "regex", "pattern": "x"}]}]},
    }
    jsonschema.validate(io_field, capability_schema["$defs"]["ioField"])


def test_extraction_alias_emits_deprecation_warning_with_migration_text():
    from scripts.validate_registry_contract import collect_deprecation_warnings

    contract = load_registry_contract(REPO_ROOT / "registry" / "capabilities.yaml")
    warnings = collect_deprecation_warnings(contract)
    assert len(warnings) >= 1
    assert all("extraction" in w and "binding.sources" in w for w in warnings)
    assert any("MM.PR.CreateDraft" in w for w in warnings)
    assert any("extraction.matchers" in w and "kind: userUtterance" in w for w in warnings)


def test_binding_shape_validates_without_warnings(tmp_path):
    from scripts.validate_registry_contract import collect_deprecation_warnings

    doc = _capability_yaml(
        _valid_intent(),
        inputs=[{
            "name": "vendor",
            "semanticType": "sapnexus:Supplier",
            "required": True,
            "type": "string",
            "binding": {"sources": [{"kind": "default", "value": "V1"}]},
        }],
    )
    contract = load_registry_contract(_write_registry(tmp_path, doc))
    errors = validate_registry_contract(contract, repo_root=REPO_ROOT)
    assert errors == []
    assert collect_deprecation_warnings(contract) == []


def test_binding_and_extraction_together_rejected(tmp_path):
    doc = _capability_yaml(
        _valid_intent(),
        inputs=[{
            "name": "vendor",
            "semanticType": "sapnexus:Supplier",
            "required": True,
            "type": "string",
            "extraction": {"matchers": [{"kind": "regex", "pattern": "x"}]},
            "binding": {"sources": [{"kind": "default", "value": "V1"}]},
        }],
    )
    contract = load_registry_contract(_write_registry(tmp_path, doc))
    errors = validate_registry_contract(contract, repo_root=REPO_ROOT)
    assert any("both binding and deprecated extraction" in e for e in errors)
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `cd agent && python3 -m pytest tests/test_extraction_declarations.py -q -k "binding or deprecation"`
Expected: FAIL — `KeyError: 'inputBinding'` (schema), `ImportError: cannot import name 'collect_deprecation_warnings'`, and `ioField` rejects the `binding` property (`additionalProperties: false`).

- [x] **Step 3: Implement the schema changes** in `schemas/extraction-declaration.schema.json`

- Mark `inputExtraction` deprecated: add `"description": "DEPRECATED: use definitions.inputBinding instead. Replace extraction.matchers with binding.sources[{kind: userUtterance, matchers: [...]}]."` to the `inputExtraction` definition object.
- Add `definitions.inputBinding` (sibling of `inputExtraction`):

```json
    "inputBinding": {
      "type": "object",
      "additionalProperties": false,
      "required": ["sources"],
      "properties": {
        "sources": {
          "type": "array",
          "minItems": 1,
          "items": {"$ref": "#/$defs/bindingSource"}
        },
        "elicitIfMissing": {
          "type": "boolean",
          "description": "False skips clarification for the field even when no source produces a value."
        },
        "priority": {"type": "integer"},
        "excludes": {
          "type": "array",
          "items": {"type": "string", "minLength": 1}
        },
        "resolver": {"enum": ["date", "quantity", "text"]},
        "when": {"$ref": "#/$defs/condition"},
        "requiredWhen": {"$ref": "#/$defs/condition"},
        "reaskSuspect": {"type": "boolean"}
      },
      "description": "Binding sources for an input: userUtterance (matcher-driven), capabilityOutput (reserved for future dependency edges; accepted and validated, execution unimplemented), default (constant). Sources are evaluated in priority capabilityOutput > userUtterance > default; the first produced value wins."
    }
```

- Add `$defs.bindingSource` (sibling of `$defs.localePrompt`):

```json
    "bindingSource": {
      "type": "object",
      "additionalProperties": false,
      "required": ["kind"],
      "properties": {
        "kind": {"enum": ["userUtterance", "capabilityOutput", "default"]},
        "matchers": {
          "type": "array",
          "minItems": 1,
          "items": {"$ref": "#/$defs/matcher"}
        },
        "factType": {"type": "string", "minLength": 1},
        "field": {"type": "string", "minLength": 1},
        "value": {"type": "string", "minLength": 1}
      },
      "allOf": [
        {"if": {"properties": {"kind": {"const": "userUtterance"}}},
         "then": {"required": ["matchers"]}},
        {"if": {"properties": {"kind": {"const": "capabilityOutput"}}},
         "then": {"required": ["factType", "field"]}},
        {"if": {"properties": {"kind": {"const": "default"}}},
         "then": {"required": ["value"]}}
      ]
    }
```

In `schemas/capability.schema.json`:
- Add the identical `$defs.inputBindingBlock` (the parity test above pins them identical).
- In `$defs.ioField.properties`, add `"binding": {"$ref": "#/$defs/inputBindingBlock"}`.
- Mark `extractionBlock` deprecated with the same description text as `inputExtraction`.

- [x] **Step 4: Implement the validator changes** in `scripts/validate_registry_contract.py`

In `validate_extraction_declarations`, load the binding validator alongside the extraction validator (after line 134):

```python
        binding_validator = jsonschema.Draft202012Validator(schema["definitions"]["inputBinding"])
```

Replace the extraction-collection block (lines 146–159) with a declared-inputs block that handles both shapes:

```python
        inputs = raw.get("inputs") if isinstance(raw.get("inputs"), list) else []
        declared: list[tuple[str, dict]] = []
        for input_field in inputs:
            if not isinstance(input_field, dict):
                continue
            input_name = str(input_field.get("name") or "<unknown>")
            extraction = input_field.get("extraction")
            binding = input_field.get("binding")
            has_extraction = isinstance(extraction, dict)
            has_binding = isinstance(binding, dict)
            if has_extraction and has_binding:
                errors.append(
                    f"{cap_id}: inputs[{input_name}] declares both binding and deprecated extraction; use binding only"
                )
            if has_binding:
                declared.append((input_name, binding))
            elif has_extraction:
                declared.append((input_name, extraction))
        if intent is None and not declared:
            continue
```

Update the `required_fields` line (line 182) to read from `declared`:

```python
        required_fields.update(
            name for name, declaration in declared if declaration.get("requiredWhen")
        )
```

Replace the per-input validation loop (lines 191–210) with the shape-dispatched version:

```python
        for input_name, declaration in declared:
            if "sources" in declaration:
                for schema_error in binding_validator.iter_errors(declaration):
                    errors.append(f"{cap_id}: inputs[{input_name}].binding: {schema_error.message}")
                for source in declaration.get("sources") or []:
                    if not isinstance(source, dict):
                        continue
                    for matcher in source.get("matchers") or []:
                        errors.extend(
                            _validate_matcher(
                                matcher,
                                catalog_entries,
                                f"{cap_id}: inputs[{input_name}].binding source",
                            )
                        )
            else:
                for schema_error in extraction_validator.iter_errors(declaration):
                    errors.append(f"{cap_id}: inputs[{input_name}].extraction: {schema_error.message}")
                for matcher in declaration.get("matchers") or []:
                    errors.extend(
                        _validate_matcher(matcher, catalog_entries, f"{cap_id}: inputs[{input_name}].extraction")
                    )
            for condition_key in ("when", "requiredWhen"):
                condition = declaration.get(condition_key)
                if isinstance(condition, dict) and condition.get("field") not in input_names:
                    errors.append(
                        f"{cap_id}: inputs[{input_name}].{condition_key} "
                        f"references undeclared input: {condition.get('field')}"
                    )
            for excluded in declaration.get("excludes") or []:
                if excluded not in input_names:
                    errors.append(
                        f"{cap_id}: inputs[{input_name}].excludes "
                        f"references undeclared input: {excluded}"
                    )
```

Add `collect_deprecation_warnings` after `count_regex_matchers`:

```python
def collect_deprecation_warnings(contract: RegistryContract) -> list[str]:
    """Warn per legacy extraction: usage with binding.sources[] migration text."""
    warnings: list[str] = []
    for capability in contract.capabilities:
        cap_id = capability.capability_id or "<unknown>"
        raw = capability.raw if isinstance(capability.raw, dict) else {}
        inputs = raw.get("inputs") if isinstance(raw.get("inputs"), list) else []
        for input_field in inputs:
            if not isinstance(input_field, dict) or not isinstance(input_field.get("extraction"), dict):
                continue
            input_name = str(input_field.get("name") or "<unknown>")
            warnings.append(
                f"{cap_id}: inputs[{input_name}].extraction is deprecated; "
                "replace extraction.matchers with "
                "binding.sources[{kind: userUtterance, matchers: [...]}]"
            )
    return warnings
```

Update the CLI `main` in `scripts/validate-registry-contract.py` (after the metric print, before "valid"):

```python
    for warning in collect_deprecation_warnings(contract):
        print(f"warning: {warning}")
```

(add `collect_deprecation_warnings` to the import from `validate_registry_contract`.)

- [x] **Step 5: Run the tests and CLI to verify**

Run:
```bash
cd agent && python3 -m pytest tests/test_extraction_declarations.py -q
python3 scripts/validate-registry-contract.py registry/capabilities.yaml
```
Expected: PASS — binding schema/parity tests green; real registry still valid (extraction alias accepted with warnings); CLI prints the metric, then the `warning:` lines, then `Registry contract valid: registry/capabilities.yaml`, exit 0.
Note: the condition/excludes error message lost the `.extraction` qualifier for shared paths — if any existing test pins the old full string, update that assertion; no current test does (verified: existing assertions match substrings like "semanticType"/"compile").

- [x] **Step 6: Commit**

```bash
git add schemas/extraction-declaration.schema.json schemas/capability.schema.json scripts/validate_registry_contract.py scripts/validate-registry-contract.py agent/tests/test_extraction_declarations.py
git commit -m "feat(declarative-intent): B3.1 binding.sources[] schema + deprecated extraction alias with validator warning — test_valid_input_binding_passes, test_input_binding_block_parity_with_extraction_declaration, test_capability_schema_io_field_accepts_binding, test_extraction_alias_emits_deprecation_warning_with_migration_text, test_binding_shape_validates_without_warnings, test_binding_and_extraction_together_rejected; root cause: extraction's single-source assumption blocks dependency edges"
```

---

### Task 3.2: Loader normalization + engine binding resolution with priority

**Files:**
- Modify: `agent/sap_nexus_agent/registry_loader.py` (`BindingSource`/`BindingConfig` dataclasses, `_parse_binding_source`, `_parse_input_binding`, `InputDescriptor.binding`, `load_intent_catalog` wiring)
- Modify: `agent/sap_nexus_agent/extraction/engine.py` (`extract_parameters` at line 62, `missing_parameters` at line 90, `_drop_reask_suspects` at line 256, new `resolve_input_binding`/`_resolve_source`/`_SOURCE_PRIORITY`/`_WIRED_SOURCE_KINDS`)
- Modify: `agent/sap_nexus_agent/llm_intent.py` (reask block at lines 606–613 switches to `inp.binding`)
- Create: `agent/tests/test_binding_sources.py`

**Interfaces:**
- Consumes: schema/validator shapes from 3.1.
- Produces (later tasks rely on these):
  - `BindingSource(kind, matchers=(), fact_type=None, field=None, value=None)` frozen dataclass.
  - `BindingConfig(sources, elicit_if_missing=True, priority=0, excludes=(), resolver="text", when=None, required_when=None, reask_suspect=False)` frozen dataclass (input-level concerns carried per Design §3.6).
  - `_parse_binding_source(raw) -> BindingSource | None`; `_parse_input_binding(raw) -> BindingConfig | None` (explicit `binding` wins; else legacy `extraction` normalized to a single `userUtterance` source carrying priority/excludes/resolver/when/requiredWhen/reaskSuspect; else None).
  - `InputDescriptor.binding: BindingConfig | None = None` (last field, defaulted); `load_intent_catalog` populates it via `_parse_input_binding(inp)`.
  - `engine.resolve_input_binding(text, inp, catalog, excluded_values) -> str | None`; `engine._resolve_source(kind, source, text, catalog, excluded_values, resolver) -> str | None`; `_SOURCE_PRIORITY = ("capabilityOutput", "userUtterance", "default")`; `_WIRED_SOURCE_KINDS: frozenset[str] = frozenset({"userUtterance", "default"})`.
  - `extract_parameters`/`missing_parameters`/`_drop_reask_suspects` read `inp.binding` (behavior-preserving: binding present exactly when extraction was).

- [x] **Step 1: Write the failing tests** — create `agent/tests/test_binding_sources.py`

```python
"""Binding-source resolution, loader normalization, and the xfail placeholder (Design §3.6)."""
import pytest

from sap_nexus_agent.extraction import engine
from sap_nexus_agent.registry_loader import load_intent_catalog


BINDING_PRIORITY_YAML = """\
capabilities:
  - capabilityId: Test.Priority
    status: active
    intent:
      intentName: test_priority
      primaryKeywords: [测试]
      fieldNames:
        zh-CN:
          vendor: 供应商
      clarifyPrompt:
        zh-CN:
          strategy: groupByBindingKind
          maxRounds: 2
          fallback:
            template: '请提供: {fields}'
    inputs:
      - name: vendor
        semanticName: supplier
        semanticType: sapnexus:Supplier
        bindingKind: identifier
        required: true
        type: string
        sapParameter: VENDOR
        binding:
          sources:
            - kind: capabilityOutput
              factType: vendor
              field: vendor
            - kind: userUtterance
              matchers:
                - kind: regex
                  pattern: '供应商\\s*([A-Z0-9]{1,10})'
            - kind: default
              value: 'V-DEFAULT'
"""


def _load_binding_fixture(tmp_path, yaml_doc):
    registry = tmp_path / "registry"
    registry.mkdir()
    (registry / "capabilities.yaml").write_text(yaml_doc, encoding="utf-8")
    (registry / "semantic-types.yaml").write_text(
        "version: 2\nsemanticTypes:\n  - id: MaterialNumber\n    description: synthetic\n"
        "    priority: 1\n    matchers:\n      - kind: regex\n        pattern: '[A-Z0-9]+'\n"
        "        justification: synthetic fixture\n",
        encoding="utf-8",
    )
    catalog = load_intent_catalog(str(tmp_path))
    cap = catalog.find("Test.Priority")
    assert cap is not None
    return catalog, cap


def test_extraction_alias_normalizes_to_single_user_utterance_source():
    from sap_nexus_agent.registry_loader import ConditionConfig, _parse_input_binding

    binding = _parse_input_binding({
        "extraction": {
            "matchers": [{"kind": "semanticType", "ref": "MaterialNumber"}],
            "priority": 10,
            "excludes": ["plant"],
            "resolver": "text",
            "when": {"field": "acct_assgn_cat", "equals": "K"},
            "requiredWhen": {"field": "acct_assgn_cat", "equals": "K"},
            "reaskSuspect": True,
        }
    })
    assert binding is not None
    assert [s.kind for s in binding.sources] == ["userUtterance"]
    assert binding.sources[0].matchers[0].kind == "semanticType"
    assert binding.priority == 10
    assert binding.excludes == ("plant",)
    assert binding.resolver == "text"
    assert binding.when == ConditionConfig(field="acct_assgn_cat", equals="K")
    assert binding.required_when == ConditionConfig(field="acct_assgn_cat", equals="K")
    assert binding.reask_suspect is True
    assert binding.elicit_if_missing is True


def test_explicit_binding_wins_over_deprecated_extraction():
    from sap_nexus_agent.registry_loader import _parse_input_binding

    binding = _parse_input_binding({
        "extraction": {"matchers": [{"kind": "keyword", "pattern": "x", "value": "y"}]},
        "binding": {"sources": [{"kind": "default", "value": "Z"}]},
    })
    assert binding is not None
    assert [s.kind for s in binding.sources] == ["default"]
    assert binding.sources[0].value == "Z"


def test_loader_populates_binding_for_alias_declarations(tmp_path):
    catalog, cap = _load_binding_fixture(tmp_path, BINDING_PRIORITY_YAML)
    inp = cap.inputs[0]
    assert inp.binding is not None
    assert [s.kind for s in inp.binding.sources] == ["capabilityOutput", "userUtterance", "default"]


def test_user_utterance_beats_default_when_matcher_hits(tmp_path):
    catalog, cap = _load_binding_fixture(tmp_path, BINDING_PRIORITY_YAML)
    inp = cap.inputs[0]
    # capabilityOutput is unwired this batch: skipped, never raises.
    assert engine.resolve_input_binding("供应商 V72719", inp, catalog, set()) == "V72719"


def test_default_fills_only_when_no_other_source_produces(tmp_path):
    catalog, cap = _load_binding_fixture(tmp_path, BINDING_PRIORITY_YAML)
    inp = cap.inputs[0]
    assert engine.resolve_input_binding("没有任何匹配内容", inp, catalog, set()) == "V-DEFAULT"


def test_capability_output_beats_user_utterance_when_wired(monkeypatch, tmp_path):
    catalog, cap = _load_binding_fixture(tmp_path, BINDING_PRIORITY_YAML)
    inp = cap.inputs[0]
    monkeypatch.setattr(
        engine, "_WIRED_SOURCE_KINDS",
        frozenset({"capabilityOutput", "userUtterance", "default"}),
    )
    monkeypatch.setattr(engine, "_resolve_source", _fake_resolve_source)
    assert engine.resolve_input_binding("供应商 V72719", inp, catalog, set()) == "EDGE"


def _fake_resolve_source(kind, source, text, catalog, excluded_values, resolver):
    values = {"capabilityOutput": "EDGE", "userUtterance": "UTT", "default": "DEF"}
    return values.get(kind)


def test_default_source_suppresses_clarify_for_the_field(tmp_path):
    catalog, cap = _load_binding_fixture(tmp_path, BINDING_PRIORITY_YAML)
    parameters = engine.extract_parameters("没有任何匹配内容", cap, catalog)
    assert parameters["vendor"] == "V-DEFAULT"
    assert engine.missing_parameters(cap, parameters) == []


ELICIT_FALSE_YAML = BINDING_PRIORITY_YAML.replace(
    "        binding:\n          sources:\n",
    "        binding:\n          elicitIfMissing: false\n          sources:\n",
)


def test_elicit_if_missing_false_skips_clarification(tmp_path):
    catalog, cap = _load_binding_fixture(tmp_path, ELICIT_FALSE_YAML)
    parameters = engine.extract_parameters("没有任何匹配内容", cap, catalog)
    assert engine.missing_parameters(cap, parameters) == []
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `cd agent && python3 -m pytest tests/test_binding_sources.py -q`
Expected: FAIL — `ImportError: cannot import name 'BindingConfig'` / `_parse_input_binding` missing; `engine.resolve_input_binding` missing; `extract_parameters` returns `{}` (no `binding` on the descriptor, so nothing extracts).

- [x] **Step 3: Implement the loader models and normalization** in `agent/sap_nexus_agent/registry_loader.py`

Add the two dataclasses after `ExtractionConfig` (line 52) — `MatcherConfig` (line 25) is already defined above them:

```python
@dataclass(frozen=True)
class BindingSource:
    """One source of an input's value: userUtterance | capabilityOutput | default."""
    kind: str
    matchers: tuple[MatcherConfig, ...] = ()
    fact_type: str | None = None
    field: str | None = None
    value: str | None = None


@dataclass(frozen=True)
class BindingConfig:
    """Input-level binding declaration (normalized from `extraction` when absent).

    priority/excludes/resolver/when/requiredWhen/reaskSuspect stay input-level
    concerns (Design §3.6), not per-source.
    """
    sources: tuple[BindingSource, ...]
    elicit_if_missing: bool = True
    priority: int = 0
    excludes: tuple[str, ...] = ()
    resolver: str = "text"
    when: ConditionConfig | None = None
    required_when: ConditionConfig | None = None
    reask_suspect: bool = False
```

Add `binding: BindingConfig | None = None` to `InputDescriptor` (line 11, last field, defaulted — `load_intent_catalog`'s inline construction keeps working).

Add the parsers after `_parse_extraction`:

```python
def _parse_binding_source(raw: object) -> BindingSource | None:
    if not isinstance(raw, dict) or "kind" not in raw:
        return None
    return BindingSource(
        kind=str(raw["kind"]),
        matchers=tuple(
            m for m in (_parse_matcher(x) for x in raw.get("matchers") or []) if m
        ),
        fact_type=str(raw["factType"]) if raw.get("factType") is not None else None,
        field=str(raw["field"]) if raw.get("field") is not None else None,
        value=str(raw["value"]) if raw.get("value") is not None else None,
    )


def _parse_input_binding(raw: object) -> BindingConfig | None:
    """Parse an input's `binding` block, or normalize the deprecated
    `extraction` alias into a single userUtterance source (Design §3.6)."""
    if not isinstance(raw, dict):
        return None
    binding_raw = raw.get("binding")
    if isinstance(binding_raw, dict):
        sources = tuple(
            s for s in (_parse_binding_source(x) for x in binding_raw.get("sources") or []) if s
        )
        if not sources:
            return None
        return BindingConfig(
            sources=sources,
            elicit_if_missing=bool(binding_raw.get("elicitIfMissing", True)),
        )
    extraction = _parse_extraction(raw.get("extraction"))
    if extraction is None:
        return None
    return BindingConfig(
        sources=(BindingSource(kind="userUtterance", matchers=extraction.matchers),),
        priority=extraction.priority,
        excludes=extraction.excludes,
        resolver=extraction.resolver,
        when=extraction.when,
        required_when=extraction.required_when,
        reask_suspect=extraction.reask_suspect,
    )
```

In `load_intent_catalog` (line 405), add `binding=_parse_input_binding(inp)` to the `InputDescriptor(...)` construction.

- [x] **Step 4: Implement the engine resolution** in `agent/sap_nexus_agent/extraction/engine.py`

Add the module constants near the top (after imports):

```python
_SOURCE_PRIORITY: Final = ("capabilityOutput", "userUtterance", "default")
_WIRED_SOURCE_KINDS: frozenset[str] = frozenset({"userUtterance", "default"})
```

(Ensure `Final` is imported from `typing`; `engine.py` already imports from `typing` — extend it.)

Replace `extract_parameters` (line 62):

```python
def extract_parameters(
    text: str,
    cap: CapabilityDescriptor,
    catalog: IntentCatalog,
    base: Mapping[str, str] | None = None,
) -> dict[str, str]:
    parameters = dict(base or {})
    ordered = [(idx, inp) for idx, inp in enumerate(cap.inputs) if inp.binding is not None]
    ordered.sort(key=lambda pair: (-pair[1].binding.priority, pair[0]))

    for _idx, inp in ordered:
        binding = inp.binding
        if binding is None or (binding.when is not None and parameters.get(binding.when.field) != binding.when.equals):
            continue
        excluded_values = {
            parameters[other_name]
            for other_name in binding.excludes
            if other_name in parameters
        }
        value = resolve_input_binding(text, inp, catalog, excluded_values)
        if value is not None:
            parameters[inp.name] = value
    return parameters
```

Add `resolve_input_binding` and `_resolve_source` after `extract_parameters`:

```python
def resolve_input_binding(
    text: str,
    inp: InputDescriptor,
    catalog: IntentCatalog,
    excluded_values: set[str],
) -> str | None:
    """Resolve the input's value from its binding sources in priority order.

    Priority: capabilityOutput > userUtterance > default (Design §3.6); the
    first produced value wins. capabilityOutput is NOT wired this batch
    (_WIRED_SOURCE_KINDS): its sources are skipped so no production path can
    reach the NotImplemented branch; the xfail placeholder test pins the
    future landing point.
    """
    binding = inp.binding
    if binding is None:
        return None
    for kind in _SOURCE_PRIORITY:
        if kind not in _WIRED_SOURCE_KINDS:
            continue
        for source in binding.sources:
            if source.kind != kind:
                continue
            value = _resolve_source(kind, source, text, catalog, excluded_values, binding.resolver)
            if value is not None:
                return value
    return None


def _resolve_source(
    kind: str,
    source: BindingSource,
    text: str,
    catalog: IntentCatalog,
    excluded_values: set[str],
    resolver: str,
) -> str | None:
    if kind == "capabilityOutput":
        # NotImplemented on purpose: dependency-edge binding (D2) is the
        # landing point for capabilityOutput sources. The branch is unwired
        # from resolve_input_binding this batch, so production never reaches
        # this raise; the xfail placeholder test pins this contract.
        raise NotImplementedError(
            "capabilityOutput binding source is not implemented; "
            "landing point: dependency-edge binding"
        )
    if kind == "userUtterance":
        for matcher in source.matchers:
            filters = input_filters(matcher, catalog)
            value = match_value(matcher, text, catalog, filters, excluded_values)
            if value is not None:
                return resolve(value, resolver, filters)
        return None
    if kind == "default":
        return source.value
    return None
```

(Add `InputDescriptor` and `BindingSource` to the module's `from sap_nexus_agent.registry_loader import ...` line.)

Update `missing_parameters` (line 90) — behavior-preserving (binding present exactly where extraction was; the old `inp.required or required_when` semantics kept, plus the new `elicit_if_missing` skip):

```python
def missing_parameters(cap: CapabilityDescriptor, parameters: Mapping[str, str]) -> list[str]:
    missing = []
    for inp in cap.inputs:
        binding = inp.binding
        if binding is not None and not binding.elicit_if_missing:
            continue
        required_when = (
            binding is not None
            and binding.required_when is not None
            and parameters.get(binding.required_when.field) == binding.required_when.equals
        )
        if (inp.required or required_when) and inp.name not in parameters:
            missing.append(inp.name)

    intent_config = cap.intent_config
    if missing or intent_config is None or intent_config.require_any is None:
        return missing
    if not any(name in parameters for name in intent_config.require_any.inputs):
        return [intent_config.require_any.missing_name]
    return []
```

Update `_drop_reask_suspects` (line 269):

```python
    reask_fields = [
        inp.name
        for inp in cap.inputs
        if inp.binding is not None
        and inp.binding.reask_suspect
        and inp.name in previous
        and inp.name not in extracted
    ]
```

Update the reask block in `llm_intent.resolve_with_context` (lines 606–613) the same way:

```python
        reask_fields = [
            inp.name
            for inp in descriptor.inputs
            if inp.binding is not None
            and inp.binding.reask_suspect
            and inp.name in context.last_context.parameters
            and inp.name not in extracted
        ]
```

- [x] **Step 5: Run the tests to verify they pass**

Run: `cd agent && python3 -m pytest tests/test_binding_sources.py -q`
Expected: PASS (all 8 tests).
Then run the broader suite for regressions: `cd agent && python3 -m pytest tests/test_extraction_engine.py tests/test_registry_loader.py tests/test_llm_intent.py tests/test_clarify_rendering.py -q` — Expected: PASS (engine now consumes `inp.binding`; the alias normalization makes behavior identical for every current declaration).

- [x] **Step 6: Commit**

```bash
git add agent/sap_nexus_agent/registry_loader.py agent/sap_nexus_agent/extraction/engine.py agent/sap_nexus_agent/llm_intent.py agent/tests/test_binding_sources.py
git commit -m "feat(declarative-intent): B3.2 loader normalizes extraction alias to single userUtterance source; engine resolves binding sources in priority capabilityOutput > userUtterance > default — test_extraction_alias_normalizes_to_single_user_utterance_source, test_explicit_binding_wins_over_deprecated_extraction, test_loader_populates_binding_for_alias_declarations, test_user_utterance_beats_default_when_matcher_hits, test_default_fills_only_when_no_other_source_produces, test_capability_output_beats_user_utterance_when_wired, test_default_source_suppresses_clarify_for_the_field, test_elicit_if_missing_false_skips_clarification; root cause: engine consumed the deprecated extraction shape directly"
```

---

### Task 3.3: capabilityOutput NotImplemented branch + xfail placeholder

**Files:**
- Modify: `agent/sap_nexus_agent/extraction/engine.py` (`_resolve_source` — already implemented in 3.2; this task adds the pinning test and verifies the branch contract)
- Modify: `agent/tests/test_binding_sources.py` (add the xfail test)

**Interfaces:**
- Consumes: `_resolve_source` capabilityOutput branch (3.2), `resolve_input_binding` (3.2).
- Produces: the failing xfail placeholder per spec ("an unimplemented path SHALL be surfaced by a failing xfail placeholder test so future implementation has a fixed landing point").

- [ ] **Step 1: Write the xfail placeholder test** (append to `agent/tests/test_binding_sources.py`)

```python
@pytest.mark.xfail(strict=True, reason="capabilityOutput execution is out of scope for declarative-intent-hardening")
def test_binding_capability_output_not_implemented(tmp_path):
    """Failing placeholder (Design §3.6): asserts that resolving a
    capabilityOutput source raises NotImplementedError naming the future
    landing point (dependency-edge binding).

    Today capabilityOutput sources are unwired (_WIRED_SOURCE_KINDS), so
    resolution skips them and this raise-assertion FAILS with the
    not-implemented message -> strict XFAIL, suite green. When dependency-edge
    binding lands and wires the branch, _resolve_source raises
    NotImplementedError with the landing-point message, this test PASSES ->
    XPASS(strict) red -> the D2 change removes the marker and rewrites the
    assertion to value resolution.
    """
    catalog, cap = _load_binding_fixture(tmp_path, BINDING_PRIORITY_YAML)
    inp = cap.inputs[0]
    with pytest.raises(NotImplementedError, match="dependency-edge binding"):
        engine.resolve_input_binding("供应商 V72719", inp, catalog, set())
```

- [ ] **Step 2: Run to verify the placeholder fails as expected**

Run: `cd agent && python3 -m pytest tests/test_binding_sources.py::test_binding_capability_output_not_implemented -rx`
Expected: XFAIL (strict) — the run reports `XFAIL` with the reason `capabilityOutput execution is out of scope for declarative-intent-hardening`; the test body failed with `DID NOT RAISE <class 'NotImplementedError'>` because the branch is unwired. The suite stays green.

- [ ] **Step 3: Commit**

```bash
git add agent/tests/test_binding_sources.py
git commit -m "test(declarative-intent): B3.3 xfail placeholder pins capabilityOutput landing point — test_binding_capability_output_not_implemented (strict xfail, fails with not-implemented reason until dependency-edge binding exists); root cause: unimplemented paths must be visible, not silently absent"
```

---

### Task 3.4: B3 tests — priority, alias warning, xfail

**Files:**
- Modify: `agent/tests/test_binding_sources.py` (priority/alias/xfail tests already added in 3.2/3.3 — this task runs the full B3 verification)
- Modify: `agent/tests/test_extraction_declarations.py` (alias-warning tests added in 3.1)

**Interfaces:**
- Consumes: 3.1–3.3.
- Produces: the B3 contract evidence per Design §3.7 matrix rows (priority, alias, xfail).

- [ ] **Step 1: Run the B3 test files**

Run: `cd agent && python3 -m pytest tests/test_binding_sources.py tests/test_extraction_declarations.py -q`
Expected: PASS — 8 binding-resolution tests, 6 binding/schema/validator tests, plus the strict XFAIL placeholder (reported as expected failure, not counted as failure).

- [ ] **Step 2: Run the full agent suite**

Run: `cd agent && python3 -m pytest tests/ -q`
Expected: PASS (including the xfail placeholder and matcher_cases 23/23 via `test_eval_runner.py`).

- [ ] **Step 3: Verify the real registry end-to-end**

Run: `python3 scripts/validate-registry-contract.py registry/capabilities.yaml`
Expected: metric line, deprecation warning lines, `Registry contract valid`, exit 0.

- [ ] **Step 4: Commit**

```bash
git add agent/tests/test_binding_sources.py agent/tests/test_extraction_declarations.py
git commit -m "test(declarative-intent): B3.4 binding priority ordering, alias deprecation warning, xfail placeholder verified — test_capability_output_beats_user_utterance_when_wired, test_user_utterance_beats_default_when_matcher_hits, test_default_fills_only_when_no_other_source_produces, test_extraction_alias_emits_deprecation_warning_with_migration_text, test_binding_capability_output_not_implemented; root cause: B3 contract needed pinned evidence"
```

---

## Closeout

### Task 4.1: Full verification

**Files:**
- None (evidence only).

- [ ] **Step 1: Run the full verification battery**

```bash
git status --short
python3 scripts/validate-registry-contract.py registry/capabilities.yaml
cd agent && python3 -m pytest tests/ -q
cd agent && python3 -m pytest tests/test_eval_runner.py -q
npm --prefix frontend run verify
openspec validate --all --strict
git status --short
```

Expected:
- Validator: `regex matchers in use: ...` metric line, `warning: ...` deprecation lines, `Registry contract valid: registry/capabilities.yaml`, exit 0.
- Pytest: all green, including the strict XFAIL placeholder (`test_binding_capability_output_not_implemented` reported as expected failure) and `test_matcher_eval_file_passes` (matcher_cases 23/23).
- Frontend verify: green (no frontend code touched; regression check only).
- OpenSpec: green (schemas and spec artifacts consistent).
- `git status --short`: only intended files changed.

- [ ] **Step 2: Record the evidence** in the change's verification log (per the project's Classic closeout flow, keep the output of the four gates; do not hand-edit `.comet.yaml`).

---

### Task 4.2: Spec delta mapping + commit series audit

**Files:**
- None (audit only).

- [ ] **Step 1: Map every spec-delta scenario to its test** (1:1, from `openspec/changes/declarative-intent-hardening/specs/declarative-intent-extraction/spec.md`):

| Spec scenario | Pinning test |
|---|---|
| capabilityOutput beats user utterance | `test_capability_output_beats_user_utterance_when_wired` |
| default only fills when no other source produces | `test_default_fills_only_when_no_other_source_produces`, `test_default_source_suppresses_clarify_for_the_field` |
| unimplemented capabilityOutput has a failing placeholder | `test_binding_capability_output_not_implemented` (strict XFAIL) |
| extraction alias still works with a warning | `test_extraction_alias_emits_deprecation_warning_with_migration_text` |
| binding shape validates without warnings | `test_binding_shape_validates_without_warnings` |
| two capabilities share one concept matcher | `test_semantic_type_wrapper_merges_named_kind_fields` (wrapper path), matcher_cases 23/23 |
| exclusion prevents value reuse | existing matcher_cases (unchanged), `test_user_utterance_beats_default_when_matcher_hits` uses excluded-values path |
| conditional field extraction (when/requiredWhen) | `test_extraction_alias_normalizes_to_single_user_utterance_source` (alias carries when/requiredWhen), PR parity constants |
| regex escape hatch requires justification | `test_catalog_schema_rejects_regex_without_justification`, `test_unjustified_catalog_regex_rejected` |
| named shape consolidates duplicated patterns | `test_catalog_value_shapes_plant_code`, `test_catalog_value_shapes_parsed_from_document`, PR plant `pattern: '^[A-Z0-9]{4}$'` |
| named kinds rewrite preserves matcher behavior | `test_plant_named_kinds_preserve_legacy_alternation`, matcher_cases 23/23 |
| rule mode renders declared prompt deterministically | `test_pr_strategy_renders_one_prompt_per_group` (no model call — template only) |
| LLM rephrasing stays inside declared field set | existing `test_rephrase_*` / `test_hybrid_clarify_falls_back_to_template_on_model_failure` (unchanged) |
| missing locale declaration falls back | `test_missing_locale_falls_back_to_names` (unchanged) |
| grouped prompt carries all missing fields of one group | `test_pr_strategy_renders_one_prompt_per_group`, `test_pr_missing_1_2_3_plus_fields_rounds_never_exceed_max_rounds` |
| budget exhaustion degrades to fallback | `test_strategy_round_budget_respected_and_degrades_to_fallback`, `test_sticky_clarify_rounds_capped_via_read_state` |
| explicit cases still override strategy rendering | `test_inventory_cases_exact_missing_sets`, `test_inventory_cases_still_override_strategy_path`, `test_strategy_groups_by_binding_source_kind` (cases branch) |

- [ ] **Step 2: Audit the commit series**

Run: `git log --oneline main..HEAD` (or the change branch) and confirm the series: B1 (1.1–1.5) → B2 (2.1–2.5) → B3 (3.1–3.4) → closeout, each message naming its tests and root cause (Design §5). Rebase/squash only if the series is not in order — do not reorder commits across the B-item boundaries.

- [ ] **Step 3: Final closeout commit** (only if 4.1/4.2 produced a tracked artifact, e.g. a verification note in the change folder; otherwise the last B3.4 commit is the final commit)

```bash
git add <verification artifact>
git commit -m "chore(declarative-intent): closeout — full verification battery green, spec delta scenarios map 1:1 to tests (B1 series, B2 series, B3 series)"
```

---

## Self-Review

**1. Spec coverage** (checked against the spec delta): all 17 scenarios map to concrete tests (table in 4.2). Requirements covered: binding sources + priority (3.1–3.4), deprecated alias + warning (3.1), shared catalog with named kinds (1.1–1.3), regex escape hatch + justification + metric (1.1, 1.3, 1.4), named-shape consolidation (1.3, 1.5), declaration-driven CLARIFY with strategy + budget + cases override (2.1–2.5). No requirement lacks a task.

**2. Placeholder scan**: every code step contains complete code; no "TBD"/"similar to task N"/"add validation" phrasing. The two deliberately "failing" artifacts (strict XFAIL placeholder, transient red of `test_catalog_matches_json_schema` between 1.1 and 1.3) are pinned with explicit reasons and resolution commits.

**3. Type consistency**: names are consistent across tasks — `MatcherConfig.prefix/suffix/value_shape/justification` (1.1 ↔ 1.2 ↔ 1.3); `SemanticTypeCatalog.value_shapes` (1.1 ↔ 1.2); `ClarifyPromptConfig.strategy/max_rounds` (2.1 ↔ 2.3); `render_clarify_with_kind`/`render_clarify_round`/`_missing_by_group` (2.3 ↔ 2.4 ↔ 2.5); `ConversationReadState.clarify_rounds` and `IntentParseResult.clarify_rounds` (2.4 ↔ 2.5); `BindingSource`/`BindingConfig`/`_parse_input_binding`/`resolve_input_binding`/`_resolve_source`/`_SOURCE_PRIORITY`/`_WIRED_SOURCE_KINDS` (3.1 ↔ 3.2 ↔ 3.3 ↔ 3.4); `count_regex_matchers`/`collect_deprecation_warnings`/`_validate_matcher(..., require_justification=...)` (1.4 ↔ 3.1). `render_clarify` keeps its signature throughout (2.3 backward-compatible delegation), so pre-existing callers (`build_capability_result`, `parse_with_hybrid`, engine `sticky_parse`) need no signature changes.

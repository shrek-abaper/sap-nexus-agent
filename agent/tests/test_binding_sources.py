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


# Fix round 1 (coordinator ruling): in BINDING_PRIORITY_YAML the declared source
# order already equals _SOURCE_PRIORITY, so iterating binding.sources in
# DECLARATION order would pass every priority test above. Here `default` is
# declared BEFORE `userUtterance` so the two orders disagree.
_USER_UTTERANCE_SOURCE = (
    "            - kind: userUtterance\n"
    "              matchers:\n"
    "                - kind: regex\n"
    "                  pattern: '供应商\\s*([A-Z0-9]{1,10})'\n"
)
_DEFAULT_SOURCE = "            - kind: default\n              value: 'V-DEFAULT'\n"
DECLARATION_ORDER_REVERSED_YAML = BINDING_PRIORITY_YAML.replace(
    _USER_UTTERANCE_SOURCE + _DEFAULT_SOURCE,
    _DEFAULT_SOURCE + _USER_UTTERANCE_SOURCE,
)


def test_source_priority_beats_declaration_order(tmp_path):
    catalog, cap = _load_binding_fixture(tmp_path, DECLARATION_ORDER_REVERSED_YAML)
    inp = cap.inputs[0]
    # Fixture guard: the reorder must have actually happened, otherwise this
    # test silently degrades into a duplicate of the priority tests above.
    assert [s.kind for s in inp.binding.sources] == [
        "capabilityOutput",
        "default",
        "userUtterance",
    ]
    # Declaration order would return 'V-DEFAULT'; priority order returns the hit.
    assert engine.resolve_input_binding("供应商 V72719", inp, catalog, set()) == "V72719"


@pytest.mark.xfail(
    raises=NotImplementedError,
    strict=True,
    reason="capabilityOutput binding source lands with dependency-edge binding (D2)",
)
def test_capability_output_source_resolution_is_not_implemented_yet(tmp_path):
    catalog, cap = _load_binding_fixture(tmp_path, BINDING_PRIORITY_YAML)
    source = cap.inputs[0].binding.sources[0]
    assert source.kind == "capabilityOutput"
    engine._resolve_source("capabilityOutput", source, "供应商 V72719", catalog, set(), "text")


def test_default_source_suppresses_clarify_for_the_field(tmp_path):
    catalog, cap = _load_binding_fixture(tmp_path, BINDING_PRIORITY_YAML)
    parameters = engine.extract_parameters("没有任何匹配内容", cap, catalog)
    assert parameters["vendor"] == "V-DEFAULT"
    assert engine.missing_parameters(cap, parameters) == []


ELICIT_FALSE_YAML = BINDING_PRIORITY_YAML.replace(
    "        binding:\n          sources:\n",
    "        binding:\n          elicitIfMissing: false\n          sources:\n",
)

# Fix round 1 (coordinator ruling): ELICIT_FALSE_YAML keeps the `default`
# source, so `vendor` is always filled and `missing == []` holds regardless of
# the elicit_if_missing skip — the original assertion was tautological. Drop the
# default source so NOTHING can fill the field; then `missing == []` can only
# come from the skip itself.
_NO_DEFAULT_SOURCE_YAML = BINDING_PRIORITY_YAML.replace(
    "            - kind: default\n              value: 'V-DEFAULT'\n", ""
)
ELICIT_FALSE_UNFILLABLE_YAML = _NO_DEFAULT_SOURCE_YAML.replace(
    "        binding:\n          sources:\n",
    "        binding:\n          elicitIfMissing: false\n          sources:\n",
)
ELICIT_TRUE_UNFILLABLE_YAML = _NO_DEFAULT_SOURCE_YAML.replace(
    "        binding:\n          sources:\n",
    "        binding:\n          elicitIfMissing: true\n          sources:\n",
)


def test_elicit_if_missing_false_skips_clarification(tmp_path):
    catalog, cap = _load_binding_fixture(tmp_path, ELICIT_FALSE_UNFILLABLE_YAML)
    inp = cap.inputs[0]
    # Fixture guard: required, and no source can produce a value for it.
    assert inp.required is True
    assert inp.binding.elicit_if_missing is False
    assert [s.kind for s in inp.binding.sources] == ["capabilityOutput", "userUtterance"]

    parameters = engine.extract_parameters("没有任何匹配内容", cap, catalog)
    assert "vendor" not in parameters
    # Only the elicit_if_missing skip can make this empty now.
    assert engine.missing_parameters(cap, parameters) == []


def test_elicit_if_missing_true_still_clarifies_the_same_unfillable_field(tmp_path):
    """Contrast case proving causation: the sole difference is the elicit flag."""
    catalog, cap = _load_binding_fixture(tmp_path, ELICIT_TRUE_UNFILLABLE_YAML)
    inp = cap.inputs[0]
    assert inp.binding.elicit_if_missing is True

    parameters = engine.extract_parameters("没有任何匹配内容", cap, catalog)
    assert "vendor" not in parameters
    assert engine.missing_parameters(cap, parameters) == ["vendor"]


def test_default_source_still_fills_and_suppresses_clarify_with_elicit_false(tmp_path):
    """The original default-source case, kept — it pins filling, not the skip."""
    catalog, cap = _load_binding_fixture(tmp_path, ELICIT_FALSE_YAML)
    parameters = engine.extract_parameters("没有任何匹配内容", cap, catalog)
    assert parameters["vendor"] == "V-DEFAULT"
    assert engine.missing_parameters(cap, parameters) == []


@pytest.mark.xfail(
    raises=pytest.fail.Exception,
    strict=True,
    reason=(
        "capabilityOutput execution is out of scope for declarative-intent-hardening: "
        "the public path skips the unwired source, so the raise-assertion DID NOT RAISE"
    ),
)
def test_binding_capability_output_not_implemented(tmp_path):
    """Failing placeholder (Design §3.6) pinning the capabilityOutput landing
    point on the PUBLIC resolution path.

    Today `capabilityOutput` is absent from `_WIRED_SOURCE_KINDS`, so
    `resolve_input_binding` skips that source and falls through to
    `userUtterance`: it returns a value instead of raising. The `pytest.raises`
    block therefore fails with `Failed: DID NOT RAISE NotImplementedError` ->
    strict XFAIL, suite green. `raises=` is pinned to `pytest.fail.Exception`
    (the DID-NOT-RAISE outcome) instead of being left blank, so ONLY that exact
    failure mode is absorbed by the marker.

    When dependency-edge binding (D2) wires the source, the precondition assert
    below fails with `AssertionError` — not the pinned `raises=` type — so this
    test becomes a real FAILURE rather than a silent XFAIL, and D2 must drop the
    marker and rewrite the body to assert value resolution. The sibling
    placeholder `test_capability_output_source_resolution_is_not_implemented_yet`
    pins the private branch body and its message; this one pins the *unwired*
    state of the public path. Both go red in D2, by design.
    """
    catalog, cap = _load_binding_fixture(tmp_path, BINDING_PRIORITY_YAML)
    inp = cap.inputs[0]
    # Precondition: the source is still unwired. If it ever gets wired, this
    # AssertionError is not the pinned raises= type -> real failure, not xfail.
    assert "capabilityOutput" not in engine._WIRED_SOURCE_KINDS
    with pytest.raises(NotImplementedError, match="dependency-edge binding"):
        engine.resolve_input_binding("供应商 V72719", inp, catalog, set())

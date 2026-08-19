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


def test_elicit_if_missing_false_skips_clarification(tmp_path):
    catalog, cap = _load_binding_fixture(tmp_path, ELICIT_FALSE_YAML)
    parameters = engine.extract_parameters("没有任何匹配内容", cap, catalog)
    assert engine.missing_parameters(cap, parameters) == []

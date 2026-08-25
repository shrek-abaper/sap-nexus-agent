"""T0' — identifier inputs may declare ``satisfiableByFactType``.

``bindingKind`` describes *what the parameter is*; ``satisfiableByFactType``
describes *where it may additionally come from*. An ``identifier`` input MAY
declare one published ``satisfiableByFactType`` so an upstream Fact can supply
it, while a user-supplied value still binds as an identifier.

Authorising requirement: ``registry-ontology-contract`` — "Registry schema
validates semantic capability contract", scenarios "Identifier input declares
Fact Type reference" and "Identifier input references an unpublished Fact Type".

Every check here keeps its Fact-Type equality assertion; only the
``bindingKind`` test is dropped, so no check becomes weaker.
"""

from dataclasses import replace
from pathlib import Path

import jsonschema
import pytest
import yaml

from sap_nexus_agent.semantic_planning.loader import load_semantic_sources
from sap_nexus_agent.semantic_planning.validation import build_semantic_contracts
from scripts.validate_registry_contract import (
    RegistryContract,
    load_registry_contract,
    validate_registry_contract,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
PUBLISHED_FACT_TYPE = "sapnexus:InventoryAvailabilityFact"
UNPUBLISHED_FACT_TYPE = "sapnexus:NoSuchFact"


def _mutable(document):
    if hasattr(document, "items"):
        return {key: _mutable(value) for key, value in document.items()}
    if isinstance(document, (list, tuple)):
        return [_mutable(value) for value in document]
    return document


def _capabilities_with_first_input(**overrides):
    """Return the real capability document with overrides on capability 0 input 0."""
    sources = load_semantic_sources(REPO_ROOT)
    capabilities = _mutable(sources.capabilities)
    first_input = capabilities["capabilities"][0]["inputs"][0]
    for key, value in overrides.items():
        if value is None:
            first_input.pop(key, None)
        else:
            first_input[key] = value
    return sources, capabilities


def _issues_at(result, path):
    return {issue.code for issue in result.report.issues if issue.path == path}


def _capability_schema():
    return yaml.safe_load(
        (REPO_ROOT / "schemas/capability.schema.json").read_text(encoding="utf-8")
    )


# --- regression guards: these already pass and must keep passing -------------


def test_fact_input_without_fact_type_reference_still_fails():
    """The `fact` branch is untouched — a fact input still REQUIRES the field."""
    sources, capabilities = _capabilities_with_first_input(
        bindingKind="fact", satisfiableByFactType=None
    )

    result = build_semantic_contracts(replace(sources, capabilities=capabilities))

    assert result.report.valid is False
    assert "SCHEMA_INVALID" in _issues_at(
        result, "/capabilities/0/inputs/0/satisfiableByFactType"
    )


def test_identifier_input_without_fact_type_reference_still_validates():
    """The unmodified registry — every input is `identifier` with no reference."""
    result = build_semantic_contracts(load_semantic_sources(REPO_ROOT))

    assert result.report.valid is True


# --- the relaxation ---------------------------------------------------------


def test_capability_schema_accepts_identifier_declaring_published_fact_type():
    _, capabilities = _capabilities_with_first_input(
        satisfiableByFactType=PUBLISHED_FACT_TYPE
    )

    jsonschema.validate(capabilities, _capability_schema())


def test_identifier_input_declaring_published_fact_type_validates():
    sources, capabilities = _capabilities_with_first_input(
        satisfiableByFactType=PUBLISHED_FACT_TYPE
    )

    result = build_semantic_contracts(replace(sources, capabilities=capabilities))

    assert result.report.valid is True
    assert capabilities["capabilities"][0]["inputs"][0]["bindingKind"] == "identifier"


def test_legacy_validator_accepts_identifier_declaring_published_fact_type():
    contract = load_registry_contract(REPO_ROOT / "registry/capabilities.yaml")
    capability = contract.capabilities[0]
    raw = _mutable(capability.raw)
    raw["inputs"][0]["satisfiableByFactType"] = PUBLISHED_FACT_TYPE

    errors = validate_registry_contract(
        RegistryContract([replace(capability, raw=raw)]), repo_root=REPO_ROOT
    )

    assert not any("satisfiableByFactType" in error for error in errors)


def test_identifier_input_declaring_unpublished_fact_type_fails_as_unknown():
    """Relaxing the coupling must not lose the Fact Type existence check."""
    sources, capabilities = _capabilities_with_first_input(
        satisfiableByFactType=UNPUBLISHED_FACT_TYPE
    )

    result = build_semantic_contracts(replace(sources, capabilities=capabilities))

    assert result.report.valid is False
    assert _issues_at(result, "/capabilities/0/inputs/0/satisfiableByFactType") == {
        "UNKNOWN_FACT_TYPE"
    }


def test_identifier_input_declaring_fact_type_records_consumes_fact_type_edge():
    """The edge the T3 auto-pull closure walks."""
    sources, capabilities = _capabilities_with_first_input(
        satisfiableByFactType=PUBLISHED_FACT_TYPE
    )
    capability_id = capabilities["capabilities"][0]["capabilityId"]

    result = build_semantic_contracts(replace(sources, capabilities=capabilities))

    assert result.graph is not None
    edge_tuples = {
        (edge.relation_type, edge.source_id, edge.target_id)
        for edge in result.graph.edges
    }
    assert ("consumesFactType", capability_id, PUBLISHED_FACT_TYPE) in edge_tuples


@pytest.mark.parametrize("binding_kind", ["identifier", "fact"])
def test_fact_field_source_eligibility_keys_on_declaration_not_binding_kind(
    binding_kind,
):
    """`factField` eligibility follows `satisfiableByFactType`, not `bindingKind`.

    Authorising requirement: ``semantic-plan-authoring-v2`` — "Eligibility for a
    `factField` source SHALL be determined by the consuming input declaring
    `satisfiableByFactType`, not by its `bindingKind`."
    """
    from sap_nexus_agent.semantic_planning import validation

    issues: list = []
    input_field = {
        "name": "unit",
        "semanticType": "sapnexus:UnitOfMeasure",
        "bindingKind": binding_kind,
        "satisfiableByFactType": PUBLISHED_FACT_TYPE,
    }
    source = {
        "kind": "factField",
        "producerNodeId": "node.producer",
        "factTypeId": PUBLISHED_FACT_TYPE,
        "field": "availableQuantity",
    }
    producer_capability = {
        "outputs": [
            {"name": "availableQuantity", "factTypeRef": PUBLISHED_FACT_TYPE}
        ]
    }
    node_index = {"node.producer": (0, {}, producer_capability)}

    validation._validate_parameter_source(
        0, 0, input_field, source, {}, node_index, issues
    )

    assert issues == []


def test_the_unknown_fact_type_failure_names_the_capability_and_the_input():
    """R3 — the spec clause "names the offending capability and input".

    Previously the message was only `unknown Fact Type: <id>`, so the offending
    capability and input were identified positionally by JSON Pointer, which a
    human reading CI output has to resolve by counting array indices. Asserted on
    the message text rather than the pointer, because the pointer was already
    there and the clause is about naming.
    """
    sources, capabilities = _capabilities_with_first_input(
        satisfiableByFactType=UNPUBLISHED_FACT_TYPE
    )
    expected_capability = capabilities["capabilities"][0]["capabilityId"]
    expected_input = capabilities["capabilities"][0]["inputs"][0]["name"]

    result = build_semantic_contracts(replace(sources, capabilities=capabilities))

    unknown = [i for i in result.report.issues if i.code == "UNKNOWN_FACT_TYPE"]
    assert unknown, result.report.issues
    assert any(
        expected_capability in issue.message and expected_input in issue.message
        for issue in unknown
    ), [i.message for i in unknown]

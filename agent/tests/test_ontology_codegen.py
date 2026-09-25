"""Tests for registry YAML -> SKOS/SHACL codegen."""

from __future__ import annotations

import json
from pathlib import Path

from rdflib import BNode, Graph, URIRef
from rdflib.namespace import RDF
from rdflib.namespace import Namespace

from sap_nexus_agent.ontology_codegen import (
    build_bundle,
    is_in_sync,
    load_capabilities,
    sha256,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
GENERATED_DIR = REPO_ROOT / "ontology" / "generated"
SH = Namespace("http://www.w3.org/ns/shacl#")
SKOS = Namespace("http://www.w3.org/2004/02/skos/core#")


def _capabilities():
    return load_capabilities(REPO_ROOT / "registry" / "capabilities.yaml")


def test_generated_artifacts_are_in_sync():
    in_sync, problems = is_in_sync(GENERATED_DIR)

    assert in_sync, problems


def test_codegen_is_deterministic():
    capabilities = _capabilities()
    first = build_bundle(capabilities)
    second = build_bundle(capabilities)

    assert first.skos == second.skos
    assert first.shacl == second.shacl
    assert first.manifest() == second.manifest()


def test_committed_manifest_hashes_match_build():
    bundle = build_bundle(_capabilities())
    manifest = json.loads(
        (GENERATED_DIR / "manifest.json").read_text(encoding="utf-8")
    )

    assert manifest == bundle.manifest()
    assert manifest["skos-capabilities.ttl"] == sha256(bundle.skos)
    assert manifest["shacl-inputs.ttl"] == sha256(bundle.shacl)


def test_generated_files_have_no_blank_nodes():
    bundle = build_bundle(_capabilities())
    for content in (bundle.skos, bundle.shacl):
        graph = Graph(); graph.parse(data=content, format="turtle")
        terms = set(graph.subjects()) | set(graph.objects())

        assert not any(isinstance(term, BNode) for term in terms)


def test_one_skos_concept_per_active_capability():
    bundle = build_bundle(_capabilities())
    graph = Graph(); graph.parse(data=bundle.skos)
    capabilities = _capabilities()
    concepts = set(graph.subjects(RDF.type, SKOS.Concept))

    assert len(concepts) == len(capabilities)
    assert graph.value(predicate=RDF.type, object=SKOS.ConceptScheme) is not None


def test_concepts_cover_registry_nodes_with_labels():
    bundle = build_bundle(_capabilities())
    graph = Graph(); graph.parse(data=bundle.skos)

    def expanded(curie: str) -> str:
        return "https://sap-nexus-agent.local/ontology#" + curie.split(":", 1)[1]

    expected = {expanded(cap["ontologyIri"]) for cap in _capabilities()}
    found = {str(node) for node in graph.subjects(RDF.type, SKOS.Concept)}

    assert expected <= found
    node = URIRef(
        "https://sap-nexus-agent.local/ontology#MM_Inventory_GetAvailability"
    )
    assert graph.value(node, SKOS.prefLabel) is not None
    assert len(list(graph.objects(node, SKOS.altLabel))) >= 1


def test_regex_shaped_keywords_are_not_labels():
    bundle = build_bundle(_capabilities())
    graph = Graph(); graph.parse(data=bundle.skos)

    for label in graph.objects(predicate=SKOS.altLabel):
        assert "(?" not in str(label)
        assert not str(label).startswith("^")


def test_one_shape_per_constrained_input():
    capabilities = _capabilities()
    bundle = build_bundle(capabilities)
    graph = Graph(); graph.parse(data=bundle.shacl)

    expected = 0
    for cap in capabilities:
        for inp in cap["inputs"]:
            if any(
                inp.get(key) is not None
                for key in ("minLength", "maxLength", "pattern")
            ) or inp.get("type") in ("string", "number"):
                expected += 1

    assert len(set(graph.subjects(RDF.type, SH.NodeShape))) == expected == 29


def test_shape_constraints_match_registry():
    capabilities = _capabilities()
    bundle = build_bundle(capabilities)
    graph = Graph(); graph.parse(data=bundle.shacl)

    for cap in capabilities:
        for inp in cap["inputs"]:
            shape = URIRef(
                "https://sap-nexus-agent.local/ontology#Shape."
                + cap["capabilityId"].replace(".", "_").replace("-", "_")
                + f".{inp['name']}"
            )
            if inp.get("pattern"):
                assert str(graph.value(shape, SH.pattern)) == inp["pattern"]
            if inp.get("minLength") is not None:
                assert int(graph.value(shape, SH.minLength)) == inp["minLength"]
            if inp.get("maxLength") is not None:
                assert int(graph.value(shape, SH.maxLength)) == inp["maxLength"]

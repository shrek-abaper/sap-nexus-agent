"""Matcher catalog ↔ ontology vocabulary integrity (T1: tasks 2.2 + 2.3 + 2.4).

Requirement: openspec/changes/derived-parameter-binding/specs/
registry-ontology-contract/spec.md, design Decision 1 — the semantic-type
authority is the `sapnexus:*` ontology vocabulary, and
`registry/semantic-types.yaml` is *only* the extraction matcher catalog. The
two vocabularies stay separate, joined by a **one-way** `extracts:` mapping
from matcher id to ontology type.

One-way means: every matcher must say which ontology type it extracts, but not
every ontology type needs a matcher. `sapnexus:AvailableQuantity` is produced
by a capability, never typed by a user, and therefore has no matcher entry —
that is correct, not a gap to back-fill.

Correction C8 scopes the vocabulary rules. The `sapnexus:` namespace holds five
disjoint tiers, and only tier ① — value types, i.e. the set declared by
capability `inputs`/`outputs.semanticType` — is a vocabulary anything can be
checked against. Tier ② (Fact Type ids) is already governed by
`UNKNOWN_FACT_TYPE`; tiers ③ Fact class types (`factType.semanticType`) and ④
predicates (`factType.predicate`) are self-declaring, so no rule can check them
without inventing a registry; tier ⑤ (`ontologyIri`) is validated against the
OWL skeleton by the registry validator. The two rules here therefore cover the
two remaining tier-① reference sites: `factType.keyedBy` (2.4.1) and
`extracts:` (2.4.2).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

import jsonschema
import pytest
import yaml

from sap_nexus_agent.semantic_planning import (
    SemanticSourceDocuments,
    load_semantic_sources,
)
from sap_nexus_agent.semantic_planning.validation import build_semantic_contracts

REPO_ROOT = Path(__file__).resolve().parents[2]


def _matcher_catalog() -> dict:
    return yaml.safe_load(
        (REPO_ROOT / "registry" / "semantic-types.yaml").read_text(encoding="utf-8")
    )


def _matcher_schema() -> dict:
    return json.loads(
        (REPO_ROOT / "schemas" / "semantic-type-catalog.schema.json").read_text(
            encoding="utf-8"
        )
    )


def _mutable(value):
    """Thaw a deep-frozen source document.

    `SemanticSourceDocuments` freezes mappings to `MappingProxyType` and lists
    to tuples, and a `mappingproxy` is *not* a `dict` instance — so the check
    below must be on the abstract `Mapping`, not on `dict`.
    """
    if isinstance(value, Mapping):
        return {key: _mutable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_mutable(item) for item in value]
    return value


def _sources(**overrides) -> SemanticSourceDocuments:
    """All five governed sources, mutable, with the matcher catalog included.

    `load_semantic_sources` deep-freezes, and the frozen mappings are not `dict`
    instances, so a fixture that needs to mutate must thaw first.
    """
    base = load_semantic_sources(REPO_ROOT)
    documents = {
        "capabilities": _mutable(base.capabilities),
        "executor_bindings": _mutable(base.executor_bindings),
        "fact_types": _mutable(base.fact_types),
        "relations": _mutable(base.relations),
        "semantic_types": _mutable(base.semantic_types),
    }
    documents.update(overrides)
    return SemanticSourceDocuments(**documents)


def _entry(catalog: dict, entry_id: str) -> dict:
    for entry in catalog["semanticTypes"]:
        if entry["id"] == entry_id:
            return entry
    raise AssertionError(f"no matcher catalog entry {entry_id}")


def _ontology_vocabulary() -> set[str]:
    """Tier ①: the semantic types declared by capability inputs/outputs."""
    capabilities = yaml.safe_load(
        (REPO_ROOT / "registry" / "capabilities.yaml").read_text(encoding="utf-8")
    )
    return {
        field["semanticType"]
        for capability in capabilities["capabilities"]
        for section in ("inputs", "outputs")
        for field in capability.get(section) or []
        if field.get("semanticType")
    }


def _issues(result) -> list[tuple[str, str, str]]:
    return [
        (issue.path, issue.code, issue.message) for issue in result.report.issues
    ]


def _codes(result) -> set[str]:
    return {issue.code for issue in result.report.issues}


# --- Task 2.2: the file is labelled as the matcher catalog ------------------


def test_matcher_catalog_header_disclaims_semantic_type_authority():
    """2.2.1 — the file must say what it is, in the file, not only in a doc."""
    text = (REPO_ROOT / "registry" / "semantic-types.yaml").read_text(
        encoding="utf-8"
    )
    header = text.split("version:", 1)[0]

    assert header.strip(), "semantic-types.yaml has no header comment"
    assert "matcher catalog" in header.lower()
    assert "sapnexus:" in header, "the header must name the actual authority"


def test_every_capability_matcher_ref_still_resolves():
    """2.2.2 — labelling the file renames nothing; every `ref:` still resolves."""
    capabilities = yaml.safe_load(
        (REPO_ROOT / "registry" / "capabilities.yaml").read_text(encoding="utf-8")
    )
    entry_ids = {entry["id"] for entry in _matcher_catalog()["semanticTypes"]}

    refs: list[tuple[str, str]] = []

    def walk(node, capability_id):
        if isinstance(node, dict):
            if node.get("kind") == "semanticType" and node.get("ref"):
                refs.append((capability_id, node["ref"]))
            for value in node.values():
                walk(value, capability_id)
        elif isinstance(node, list):
            for item in node:
                walk(item, capability_id)

    for capability in capabilities["capabilities"]:
        walk(capability, capability["capabilityId"])

    assert refs, "no `kind: semanticType` refs found — the check would be vacuous"
    for capability_id, ref in refs:
        assert ref in entry_ids, f"{capability_id} references unknown matcher {ref}"


# --- Task 2.3: the one-way `extracts:` mapping ------------------------------


def test_every_matcher_entry_declares_an_extracts_target():
    """2.3.1 — the mapping is total on the matcher side."""
    catalog = _matcher_catalog()
    vocabulary = _ontology_vocabulary()

    for entry in catalog["semanticTypes"]:
        target = entry.get("extracts")
        assert target, f"{entry['id']}: no extracts target"
        assert target.startswith("sapnexus:"), f"{entry['id']}: {target}"
        assert target in vocabulary, f"{entry['id']}: {target} not in vocabulary"


def test_schema_requires_extracts():
    """2.3.1 — a matcher with no declared target must not validate."""
    catalog = _matcher_catalog()
    _entry(catalog, "Unit").pop("extracts")

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(catalog, _matcher_schema())


def test_schema_rejects_two_extracts_targets_on_one_matcher():
    """2.3.3 — a matcher extracts exactly one ontology type, never a list."""
    catalog = _matcher_catalog()
    _entry(catalog, "Unit")["extracts"] = [
        "sapnexus:UnitOfMeasure",
        "sapnexus:Quantity",
    ]

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(catalog, _matcher_schema())


def test_several_matchers_may_extract_one_ontology_type():
    """2.3.2 — many-to-one is legal: two ways of typing the same thing."""
    catalog = _matcher_catalog()
    clone = _mutable(_entry(catalog, "Unit"))
    clone["id"] = "UnitAlias"
    catalog["semanticTypes"].append(clone)

    jsonschema.validate(catalog, _matcher_schema())

    targets = [entry["extracts"] for entry in catalog["semanticTypes"]]
    assert targets.count("sapnexus:UnitOfMeasure") == 2

    result = build_semantic_contracts(_sources(semantic_types=catalog))

    assert result.report.valid is True, _issues(result)


def test_ontology_type_with_no_matcher_entry_is_accepted():
    """2.3.4 — one-way: a derived-only type needs no matcher and no back-fill."""
    targets = {entry["extracts"] for entry in _matcher_catalog()["semanticTypes"]}

    assert "sapnexus:AvailableQuantity" in _ontology_vocabulary()
    assert "sapnexus:AvailableQuantity" not in targets

    result = build_semantic_contracts(load_semantic_sources(REPO_ROOT))

    assert result.report.valid is True, _issues(result)


# --- Task 2.4: the two vocabulary-integrity rules ---------------------------


def test_unknown_extracts_target_is_rejected_naming_the_entry():
    """2.4.2 + 2.4.3 — the target must exist in the ontology vocabulary."""
    catalog = _matcher_catalog()
    _entry(catalog, "Unit")["extracts"] = "sapnexus:Nonexistent"
    index = [entry["id"] for entry in catalog["semanticTypes"]].index("Unit")

    result = build_semantic_contracts(_sources(semantic_types=catalog))

    assert result.report.valid is False
    assert (
        f"/semanticTypes/{index}/extracts",
        "UNKNOWN_SEMANTIC_TYPE",
        "Unit: unknown semantic type: sapnexus:Nonexistent",
    ) in _issues(result)


def test_bare_matcher_id_as_extracts_target_is_rejected():
    """2.4.2 — the mapping is one-way; the target cannot be a matcher id."""
    catalog = _matcher_catalog()
    _entry(catalog, "Unit")["extracts"] = "Unit"

    result = build_semantic_contracts(_sources(semantic_types=catalog))

    assert result.report.valid is False
    assert "UNKNOWN_SEMANTIC_TYPE" in _codes(result)


def test_keyed_by_must_be_in_the_ontology_vocabulary():
    """2.4.1 + 2.4.3 — `keyedBy` is the last uncovered tier-① reference site."""
    fact_types = _mutable(load_semantic_sources(REPO_ROOT).fact_types)
    fact_type = fact_types["factTypes"][0]
    fact_type["keyedBy"] = ["sapnexus:Nonexistent", *fact_type["keyedBy"][1:]]

    result = build_semantic_contracts(_sources(fact_types=fact_types))

    assert result.report.valid is False
    assert (
        "/factTypes/0/keyedBy/0",
        "UNKNOWN_SEMANTIC_TYPE",
        f"{fact_type['factTypeId']}: unknown semantic type: sapnexus:Nonexistent",
    ) in _issues(result)


def test_keyed_by_rejects_a_bare_matcher_id():
    """2.4.1 — a matcher-catalog id is not a semantic type here either."""
    fact_types = _mutable(load_semantic_sources(REPO_ROOT).fact_types)
    fact_types["factTypes"][0]["keyedBy"] = ["Plant"]

    result = build_semantic_contracts(_sources(fact_types=fact_types))

    assert result.report.valid is False
    assert "UNKNOWN_SEMANTIC_TYPE" in _codes(result)


def test_published_sources_pass_every_vocabulary_rule():
    """Positive control: the rules above are satisfied as committed."""
    catalog = _matcher_catalog()
    jsonschema.validate(catalog, _matcher_schema())

    result = build_semantic_contracts(load_semantic_sources(REPO_ROOT))

    assert result.report.valid is True, _issues(result)
    assert result.snapshot is not None
    versions = {
        source.path: source.document_version for source in result.snapshot.sources
    }
    assert versions["registry/semantic-types.yaml"] == catalog["version"]

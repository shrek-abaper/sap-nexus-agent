"""GoalResolver tests: goal-first producer resolution and terminal outcomes."""

from __future__ import annotations

from pathlib import Path

import pytest

from sap_nexus_agent.ontology_planning.contracts import (
    AnalysisNodeDraft,
    ObjectSelector,
    RequestedConclusion,
    RequestedFact,
    SemanticGoalDraft,
    TypedConstraint,
)
from sap_nexus_agent.ontology_planning.release import pin_release
from sap_nexus_agent.ontology_planning.resolver import resolve
from sap_nexus_agent.semantic_planning.loader import load_semantic_sources
from sap_nexus_agent.semantic_planning.validation import build_semantic_contracts

REPO_ROOT = Path(__file__).resolve().parents[2]
PRINCIPAL = {"principalId": "local-user-0001", "dataScope": {"tenantId": "default"}}


@pytest.fixture(scope="module")
def pinned():
    return pin_release(REPO_ROOT)


@pytest.fixture(scope="module")
def built():
    sources = load_semantic_sources(REPO_ROOT)
    contracts = build_semantic_contracts(sources)
    assert contracts.report.valid
    assert contracts.snapshot is not None
    assert contracts.graph is not None
    return sources, contracts.snapshot, contracts.graph


def _draft(facts, constraints=(), nodes=(), conclusions=("c1",)):
    return SemanticGoalDraft(
        schema_version=1,
        requested_facts=tuple(facts),
        constraints=tuple(constraints),
        analysis_nodes=tuple(nodes),
        requested_conclusions=tuple(
            RequestedConclusion(cid, "q", "evidence") for cid in conclusions
        ),
        assumptions=(),
    )


def _fact(fact_type, fields, selectors):
    return RequestedFact(fact_type, tuple(fields), tuple(selectors))


def _sel(object_type, key, value):
    return ObjectSelector(object_type, key, value)


def _con(name, semantic_type, value, source="explicitUser"):
    return TypedConstraint(name, semantic_type, value, source)


def test_q1_resolves_inventory_and_material_producers(pinned, built):
    sources, snapshot, graph = built
    draft = _draft(
        [
            _fact("sapnexus:InventoryAvailabilityFact", ["availableQuantity"],
                  [_sel("sapnexus:Material", "material", "DEMOA2"),
                   _sel("sapnexus:Plant", "plant", "1000")]),
            _fact("sapnexus:MaterialInfoFact", ["baseUnitOfMeasure"],
                  [_sel("sapnexus:Material", "material", "DEMOA2"),
                   _sel("sapnexus:Plant", "plant", "1000")]),
        ]
    )
    resolution = resolve(draft, pinned, sources, snapshot, graph, PRINCIPAL)
    assert resolution.status == "complete"
    producers = dict(resolution.producers)
    assert producers["sapnexus:InventoryAvailabilityFact"] == "MM.Inventory.GetAvailability"
    assert producers["sapnexus:MaterialInfoFact"] == "MM.Material.GetInfo"


def test_field_not_allowlisted_is_semantic_gap(pinned, built):
    sources, snapshot, graph = built
    draft = _draft([
        _fact("sapnexus:PurchaseOrderSupplyFact", ["deliveryDate"],
              [_sel("sapnexus:Material", "material", "DEMOA2"),
               _sel("sapnexus:Plant", "plant", "1000")])
    ])
    resolution = resolve(draft, pinned, sources, snapshot, graph, PRINCIPAL)
    # Draft validation normally rejects this first; resolver independently gaps.
    assert resolution.status == "semantic_gap"
    assert any("FIELD_NOT_ALLOWLISTED" in g for g in resolution.gaps)


def test_no_producer_is_capability_gap(pinned, built, tmp_path):
    import shutil

    sources, snapshot, graph = built
    # Use the real draft but pretend the fact has no READ producer by passing
    # a fact id that exists in no card: not in allowlist -> fact gap first;
    # instead craft allowlist-only fact via pinned override is not allowed,
    # so assert gap path through an unknown field is covered above; here use a
    # custom release double exposing a produced-by-nobody fact id.
    from types import SimpleNamespace

    fake_release = SimpleNamespace(
        allowlist_fields={"sapnexus:NebulaFact": frozenset({"x"})},
        operators=pinned.operators,
        package=pinned.package,
        assets=pinned.assets,
        object_types=pinned.object_types,
        compiler_version=pinned.compiler_version,
        operator_versions=pinned.operator_versions,
    )
    draft = _draft([
        _fact("sapnexus:NebulaFact", ["x"], [])
    ])
    resolution = resolve(draft, fake_release, sources, snapshot, graph, PRINCIPAL)
    assert resolution.status == "capability_gap"
    assert any(g.startswith("NO_PRODUCER:sapnexus:NebulaFact") for g in resolution.gaps)


def test_ambiguous_producers_require_clarification(pinned, built, tmp_path):
    import copy
    import shutil
    import yaml

    sources, snapshot, graph = built
    mini = tmp_path / "registry"
    mini.mkdir(parents=True)
    onto = tmp_path / "ontology"
    onto.mkdir(parents=True)
    for rel in ("registry/capabilities.yaml", "registry/executor-bindings.yaml",
                "registry/semantic-types.yaml", "ontology/fact-types.yaml",
                "ontology/capability-relations.yaml"):
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO_ROOT / rel, target)
    caps = yaml.safe_load((tmp_path / "registry/capabilities.yaml").read_text())
    second = copy.deepcopy(
        next(c for c in caps["capabilities"] if c["capabilityId"] == "MM.Inventory.GetAvailability")
    )
    second["capabilityId"] = "MM.Inventory.GetAvailabilityAlt"
    second["ontologyIri"] = "sapnexus:alt"
    caps["capabilities"].append(second)
    (tmp_path / "registry/capabilities.yaml").write_text(yaml.safe_dump(caps))
    tmp_sources = load_semantic_sources(tmp_path)
    contracts = build_semantic_contracts(tmp_sources)
    draft = _draft([
        _fact("sapnexus:InventoryAvailabilityFact", ["availableQuantity"],
              [_sel("sapnexus:Material", "material", "DEMOA2"),
               _sel("sapnexus:Plant", "plant", "1000")])
    ])
    resolution = resolve(draft, pinned, tmp_sources, contracts.snapshot, contracts.graph, PRINCIPAL)
    assert resolution.status == "clarification"
    candidates = resolution.candidates["sapnexus:InventoryAvailabilityFact"]
    assert set(candidates) == {"MM.Inventory.GetAvailability", "MM.Inventory.GetAvailabilityAlt"}
    assert "sapnexus:InventoryAvailabilityFact" not in dict(resolution.producers)


def test_missing_required_selector_clarifies(pinned, built):
    sources, snapshot, graph = built
    draft = _draft([
        _fact("sapnexus:InventoryAvailabilityFact", ["availableQuantity"],
              [_sel("sapnexus:Material", "material", "DEMOA2")])
    ])
    resolution = resolve(draft, pinned, sources, snapshot, graph, PRINCIPAL)
    assert resolution.status == "clarification"
    assert any("MISSING_SELECTOR_VALUE" in c for c in resolution.clarification)


def _tmp_registry_with_derived_input(tmp_path: Path, many: bool = False):
    import shutil
    import yaml

    for rel in ("registry/capabilities.yaml", "registry/executor-bindings.yaml",
                "registry/semantic-types.yaml", "ontology/fact-types.yaml",
                "ontology/capability-relations.yaml"):
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO_ROOT / rel, target)
    caps_path = tmp_path / "registry/capabilities.yaml"
    caps = yaml.safe_load(caps_path.read_text())
    inventory = next(
        c for c in caps["capabilities"] if c["capabilityId"] == "MM.Inventory.GetAvailability"
    )
    derived_input = {
        "name": "baseUnitOfMeasure",
        "semanticName": "baseUnitOfMeasure",
        "semanticType": "sapnexus:UnitOfMeasure",
        "bindingKind": "identifier",
        "required": True,
        "type": "string",
        "sapParameter": "MEINS",
        "satisfiableByFactType": "sapnexus:MaterialInfoFact",
    }
    if many:
        derived_input["name"] = "supplier"
        derived_input["semanticName"] = "supplier"
        derived_input["semanticType"] = "sapnexus:Supplier"
        derived_input["sapParameter"] = "LIFNR"
        derived_input["satisfiableByFactType"] = "sapnexus:PurchaseOrderSupplyFact"
    inventory["inputs"].append(derived_input)
    caps_path.write_text(yaml.safe_dump(caps, allow_unicode=True))
    tmp_sources = load_semantic_sources(tmp_path)
    contracts = build_semantic_contracts(tmp_sources)
    assert contracts.report.valid, [str(i) for i in contracts.report.issues]
    return tmp_sources, contracts


def test_closure_auto_pulls_registered_producer(pinned, tmp_path):
    sources, contracts = _tmp_registry_with_derived_input(tmp_path)
    draft = _draft([
        _fact("sapnexus:InventoryAvailabilityFact", ["availableQuantity"],
              [_sel("sapnexus:Material", "material", "DEMOA2"),
               _sel("sapnexus:Plant", "plant", "1000")])
    ])
    resolution = resolve(draft, pinned, sources, contracts.snapshot, contracts.graph, PRINCIPAL)
    assert resolution.status == "complete"
    assert "MM.Material.GetInfo" in resolution.closure_capabilities
    binding = next(
        b for b in resolution.closure
        if b.consumer_capability_id == "MM.Inventory.GetAvailability"
        and b.consumer_input_name == "baseUnitOfMeasure"
    )
    assert binding.producer_capability_id == "MM.Material.GetInfo"
    assert binding.fact_field_name == "baseUnitOfMeasure"


def test_closure_many_cardinality_stays_unbound(pinned, tmp_path):
    sources, contracts = _tmp_registry_with_derived_input(tmp_path, many=True)
    draft = _draft([
        _fact("sapnexus:InventoryAvailabilityFact", ["availableQuantity"],
              [_sel("sapnexus:Material", "material", "DEMOA2"),
               _sel("sapnexus:Plant", "plant", "1000")])
    ])
    resolution = resolve(draft, pinned, sources, contracts.snapshot, contracts.graph, PRINCIPAL)
    assert resolution.status == "clarification"
    assert any("NEEDS_REDUCTION" in c or "MISSING_SELECTOR_VALUE:supplier" in c
               for c in resolution.clarification)


def test_user_supplied_value_is_not_derived(pinned, built):
    sources, snapshot, graph = built
    draft = _draft(
        [
            _fact("sapnexus:InventoryAvailabilityFact", ["availableQuantity"],
                  [_sel("sapnexus:Material", "material", "DEMOA2"),
                   _sel("sapnexus:Plant", "plant", "1000")]),
        ],
        constraints=(_con("plant", "sapnexus:Plant", "1000"),),
    )
    resolution = resolve(draft, pinned, sources, snapshot, graph, PRINCIPAL)
    assert resolution.status == "complete"
    assert all(
        b.consumer_input_name != "plant" for b in resolution.closure
    )

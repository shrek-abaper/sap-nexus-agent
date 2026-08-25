"""The deriver's positive control, and its containment (T2: task 3.2).

Requirement: openspec/changes/derived-parameter-binding/specs/
registry-ontology-contract/spec.md — data dependency edges SHALL be derived, and
the acceptance criterion is that the *derived view* is non-empty.

**Why this file exists (3.2.4).** The derived view over the real registry is
empty right now, and will stay empty until `MM.Material.GetInfo` lands at task
5.2. An empty view is only evidence of "nothing derivable yet" if the deriver is
independently proven able to produce a non-empty one — otherwise a deriver that
returns `()` unconditionally would look identical, and task 3.7 would record a
broken deriver as a clean result. So:

* empty real view **+ green** positive control → legitimate empty result;
* empty real view **+ red** positive control → deriver defect.

Task 3.7 must assert both facts together, never the empty one alone.

**Containment (3.2.3).** A positive control has to be a real file with real
capability declarations to be worth anything, which makes it exactly the kind of
thing that can leak into the execution boundary. The registry is that boundary:
polluting it is polluting governance. So the containment here is asserted, not
assumed — the fixture must contribute nothing to the Registry Snapshot, and its
capabilities must be absent from the active set the planner and Gateway see.

The prefix locks are written to catch *any* fabricated id, not only this
fixture's: a future test capability named `T.Something.Else` fails them too.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml
from positive_control import (
    FABRICATED_CAPABILITY_PREFIX,
    FABRICATED_ONTOLOGY_PREFIX,
    POSITIVE_CONTROL_PATH,
    load_positive_control,
    positive_control_capabilities,
    positive_control_documents,
    positive_control_fact_types,
)
from sap_nexus_agent.semantic_planning import (
    build_registry_snapshot,
    load_semantic_sources,
)
from sap_nexus_agent.semantic_planning.derivation import derive_data_dependencies

REPO_ROOT = Path(__file__).resolve().parents[2]

#: The five documents the Registry Snapshot hashes. Restated here on purpose:
#: this test's job is to notice when the governed set changes, and importing the
#: set under test would make it agree with itself.
GOVERNED_SOURCES = (
    "ontology/capability-relations.yaml",
    "ontology/fact-types.yaml",
    "registry/capabilities.yaml",
    "registry/executor-bindings.yaml",
    "registry/semantic-types.yaml",
)


def _real_snapshot():
    return build_registry_snapshot(load_semantic_sources(REPO_ROOT))


# ---- 3.2.1 / 3.2.2: the control produces exactly one edge ----


def test_the_positive_control_declares_two_capabilities():
    """3.2.1 — a producer and a consumer, both fabricated."""
    capability_ids = [item["capabilityId"] for item in positive_control_capabilities()]
    assert capability_ids == ["T.Widget.GetInfo", "T.Widget.Order"]


def test_the_positive_control_yields_exactly_one_derived_edge():
    """3.2.2 — the whole point: the deriver *can* produce a non-empty view.

    If this test ever goes red while `test_the_real_registry_derives_no_edges_yet`
    stays green, the empty real view means nothing and task 3.7's record is void.
    """
    view = derive_data_dependencies(positive_control_documents())
    assert len(view.edges) == 1
    edge = view.edges[0]
    assert edge.consumer_capability_id == "T.Widget.Order"
    assert edge.consumer_input_name == "unit"
    assert edge.producer_capability_id == "T.Widget.GetInfo"
    assert edge.fact_field_name == "widgetUnit"


def test_one_edge_is_a_constraint_not_a_fixture_size_artefact():
    """The consumer declares two `satisfiableByFactType` inputs, not one.

    Without this, "exactly one edge" would be satisfied by a fixture that simply
    had nothing else to derive, and the count would prove nothing about the
    deriver's selectivity.
    """
    consumer = next(
        item
        for item in positive_control_capabilities()
        if item["capabilityId"] == "T.Widget.Order"
    )
    satisfiable = [
        item["name"] for item in consumer["inputs"] if "satisfiableByFactType" in item
    ]
    assert satisfiable == ["unit", "tags"]


# ---- 3.2.3: containment — the fixture never reaches the execution boundary ----


def test_the_fixture_is_not_a_governed_snapshot_source():
    """The snapshot hashes exactly five documents, and this is not one of them."""
    snapshot = _real_snapshot()
    assert tuple(source.path for source in snapshot.sources) == GOVERNED_SOURCES
    fixture_relative = POSITIVE_CONTROL_PATH.relative_to(REPO_ROOT).as_posix()
    assert fixture_relative not in GOVERNED_SOURCES


def test_no_fabricated_id_appears_in_any_governed_source():
    """The strong form of containment: search the governed documents as text.

    Structural checks would only cover the keys someone thought to look at. A
    fabricated id pasted anywhere in these five files — a description, a
    comment, a `dependsOn` endpoint — fails this.

    Matched at a token boundary rather than as a bare substring. A plain
    `"test:" in text` check would fire on any future key spelled `latest:`, and
    a lock that goes off for the wrong reason gets deleted rather than fixed.
    """
    patterns = [
        re.compile(r"(?<![A-Za-z0-9_.])" + re.escape(prefix))
        for prefix in (FABRICATED_CAPABILITY_PREFIX, FABRICATED_ONTOLOGY_PREFIX)
    ]
    fixture_text = POSITIVE_CONTROL_PATH.read_text(encoding="utf-8")
    for pattern in patterns:
        assert pattern.search(fixture_text), (
            f"{pattern.pattern} does not match the fixture it was written for; "
            "the containment lock would be vacuous"
        )
    for relative_path in GOVERNED_SOURCES:
        text = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
        for pattern in patterns:
            assert not pattern.search(text), (
                f"{relative_path} contains a fabricated id matching "
                f"{pattern.pattern}; a test fixture must never reach the "
                "execution boundary"
            )


def test_no_fabricated_capability_is_in_the_active_set():
    """The active set is what the planner recalls and the Gateway executes."""
    capabilities = load_semantic_sources(REPO_ROOT).capabilities["capabilities"]
    for capability in capabilities:
        assert not capability["capabilityId"].startswith(
            FABRICATED_CAPABILITY_PREFIX
        ), capability["capabilityId"]


def test_no_fabricated_fact_type_is_in_the_ontology():
    fact_types = load_semantic_sources(REPO_ROOT).fact_types["factTypes"]
    for fact_type in fact_types:
        assert not fact_type["factTypeId"].startswith(
            FABRICATED_ONTOLOGY_PREFIX
        ), fact_type["factTypeId"]


def test_the_fixture_lives_outside_the_registry_and_ontology_trees():
    """Containment by location as well as by content.

    `registry/` and `ontology/` are the execution boundary's declarations; a
    fixture placed there would be loaded by `load_semantic_sources` no matter
    what its ids looked like.
    """
    relative = POSITIVE_CONTROL_PATH.relative_to(REPO_ROOT).as_posix()
    assert relative.startswith("agent/tests/fixtures/")


def test_loading_the_fixture_does_not_change_the_real_snapshot_id():
    """Reading the fixture must be inert.

    Cheap to assert and worth asserting: a loader that ever merged fixture
    documents into the governed set would move the snapshot id, and every
    approval subject hash pinned to that id with it.
    """
    before = _real_snapshot().snapshot_id
    load_positive_control()
    derive_data_dependencies(positive_control_documents())
    assert _real_snapshot().snapshot_id == before


# ---- the fixture's own declarations stay honest ----


def test_the_fixture_is_valid_yaml_with_both_documents():
    parsed = yaml.safe_load(POSITIVE_CONTROL_PATH.read_text(encoding="utf-8"))
    assert set(parsed) == {"capabilities", "factTypes"}
    assert parsed["capabilities"]["version"] == 2
    assert parsed["factTypes"]["version"] == 3


def test_the_fixture_declares_the_many_field_the_deriver_must_refuse():
    fields = {
        item["name"]: item["cardinality"]
        for item in positive_control_fact_types()[0]["fields"]
    }
    assert fields == {"widgetUnit": "one", "widgetTags": "many"}

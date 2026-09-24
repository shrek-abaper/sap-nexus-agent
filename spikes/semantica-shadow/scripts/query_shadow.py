#!/usr/bin/env python3
"""Four runtime queries over the ontology: validation, preconditions,
permission duty, SKOS recall.

Validation and recall are answered by the graph (SHACL / SKOS). Precondition
and duty *evaluation* additionally read the authored registry / approval
record of the same snapshot: the authored IOPE and ODRL files carry labels
and definitions, not executable condition structures, so the semantics are
enforced by deterministic code against the authoritative data.

The graph is the rdflib merge of ontology/*.owl + bundle/*.ttl; the same
SPARQL runs unchanged on semantica's OxigraphStore.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml
from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF

SPIKE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SPIKE_ROOT.parents[1]

ONTOLOGY_NAMESPACE = "https://sap-nexus-agent.local/ontology#"
SH = URIRef("http://www.w3.org/ns/shacl#")
SKOS = URIRef("http://www.w3.org/2004/02/skos/core#")
ODRL = URIRef("http://www.w3.org/ns/odrl/2/")

REGISTRY_PATH = REPO_ROOT / "registry" / "capabilities.yaml"


def load_graph() -> Graph:
    graph = Graph()
    for owl_path in sorted((REPO_ROOT / "ontology").glob("*.owl")):
        graph.parse(owl_path, format="xml")
    for ttl in ("skos-capabilities.ttl", "shacl-inputs.ttl"):
        graph.parse(SPIKE_ROOT / "bundle" / ttl, format="turtle")
    return graph


def _registry_index() -> dict[str, dict]:
    caps = yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))["capabilities"]
    return {cap["capabilityId"]: cap for cap in caps}


def _shape_iri(capability_id: str, input_name: str) -> URIRef:
    safe = capability_id.replace(".", "_").replace("-", "_")
    return URIRef(f"{ONTOLOGY_NAMESPACE}Shape.{safe}.{input_name}")


# ---------------------------- 1. SHACL validate ----------------------------

def validate_input(graph: Graph, capability_id: str, input_name: str, value: Any) -> dict:
    """Validate one value against its generated SHACL NodeShape via pyshacl."""
    import pyshacl

    shape = _shape_iri(capability_id, input_name)
    target = Literal(value)
    overlay = Graph()
    overlay.add((shape, SH + "targetNode", target))

    data = Graph()
    data.add((URIRef("https://sap-nexus-agent.local/value-dummy"), SH + "holds", target))

    conforms, results_graph, results_text = pyshacl.validate(
        data,
        shacl_graph=graph + overlay,
        ont_graph=None,
        inference=None,
        meta_shacl=False,
        debug=False,
    )
    violations = [line for line in results_text.splitlines() if "Constraint Violated" in line]
    return {"conforms": bool(conforms), "violations": violations or [results_text]}


# ------------------------- 2. Precondition evaluate -------------------------

def evaluate_preconditions(
    graph: Graph, capability_id: str, slots: dict[str, Any]
) -> dict:
    """Required inputs present; plus authored conditional requiredWhen."""
    cap = _registry_index()[capability_id]
    cap_node = URIRef(ONTOLOGY_NAMESPACE + cap["ontologyIri"].split(":", 1)[1])

    query = """
        SELECT ?input ?required WHERE {
            ?shape a sh:NodeShape ;
                   sapnexus:forCapability ?cap ;
                   sapnexus:forInput ?input ;
                   sapnexus:required ?required .
        }
    """
    # Inputs satisfiable by an upstream Fact are present at the execution
    # boundary: the planner pulls the producer node, so they are not missing.
    fact_satisfiable = {
        inp["name"]
        for inp in cap["inputs"]
        if inp.get("satisfiableByFactType")
    }
    provided = {k for k, v in slots.items() if v not in (None, "")}
    missing: list[str] = []
    for row in graph.query(
        query,
        initNs={"sh": SH, "sapnexus": URIRef(ONTOLOGY_NAMESPACE)},
        initBindings={"cap": cap_node},
    ):
        if (
            bool(row.required)
            and str(row.input) not in provided
            and str(row.input) not in fact_satisfiable
        ):
            missing.append(str(row.input))

    # Group precondition requireAny: at least one filter of the group.
    require_any = (cap.get("intent") or {}).get("requireAny")
    if require_any and not any(
        slots.get(name) not in (None, "") for name in require_any["inputs"]
    ):
        missing.append(require_any["missingName"])

    # Conditional preconditions: requiredWhen is authored inside the
    # extraction block of the registry entry.
    for inp in cap["inputs"]:
        cond = (inp.get("extraction") or {}).get("requiredWhen")
        if cond and str(slots.get(cond["field"])) == cond["equals"]:
            if not slots.get(inp["name"]):
                missing.append(inp["name"])

    return {"satisfied": not missing, "missing": missing}


# --------------------------- 3. Permission / duty ---------------------------

def check_permission(
    graph: Graph, capability_id: str, approval: dict, *, parameter_snapshot_hash: str
) -> dict:
    """Resolve the WRITE duty in the ODRL graph, then evaluate the record."""
    cap = _registry_index()[capability_id]
    cap_node = URIRef(ONTOLOGY_NAMESPACE + cap["ontologyIri"].split(":", 1)[1])

    query = """
        SELECT ?dutyAction WHERE {
            ?policy odrl:permission ?permission .
            ?permission odrl:target ?cap ;
                        odrl:duty ?duty .
            ?duty odrl:action ?dutyAction .
        }
    """
    duty_actions = [
        str(row.dutyAction)
        for row in graph.query(query, initNs={"odrl": ODRL}, initBindings={"cap": cap_node})
    ]

    checks = {
        "policy_present": bool(duty_actions),
        "status_approved": approval.get("status") == "approved",
        "capability_matches": approval.get("capabilityId") == capability_id,
        "snapshot_hash_matches": approval.get("parameterSnapshotHash") == parameter_snapshot_hash,
        "not_expired": bool(approval.get("expiresAt")) and approval["expiresAt"] > _now(),
    }
    return {
        "dutyActions": duty_actions,
        "checks": checks,
        "permission_holds": all(checks.values()),
    }


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


# ------------------------------ 4. SKOS recall ------------------------------

def recall_capabilities(graph: Graph, text: str) -> list[dict]:
    """Recall capability concepts by pref/alt label; exact matches rank first."""
    query = """
        SELECT ?cap ?label WHERE {
            ?cap a skos:Concept ;
                 skos:prefLabel|skos:altLabel ?label .
        }
    """
    candidates: dict[str, set[str]] = {}
    lowered = text.lower()
    for row in graph.query(query, initNs={"skos": SKOS}):
        label = str(row.label)
        if label.lower() in lowered:
            cap_id = str(row.cap)
            candidates.setdefault(cap_id, set()).add(label)

    def rank(entry: tuple[str, set[str]]) -> int:
        return 0 if any(label.lower() == lowered for label in entry[1]) else 1

    return [
        {"capabilityNode": cap, "matchedLabels": sorted(labels)}
        for cap, labels in sorted(candidates.items(), key=rank)
    ]

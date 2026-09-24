#!/usr/bin/env python3
"""Positive/negative controls for the four runtime queries."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pyoxigraph  # noqa: E402
from semantica.triplet_store import OxigraphStore  # noqa: E402

from query_shadow import (  # noqa: E402
    check_permission,
    evaluate_preconditions,
    load_graph,
    recall_capabilities,
    validate_input,
)

graph = load_graph()
failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    print(f"{'PASS' if condition else 'FAIL'}  {name}  {detail}")
    if not condition:
        failures.append(name)


# 1. validation: SHACL positive / negative
ok = validate_input(graph, "MM.Inventory.GetAvailability", "plant", "1000")
check("validate plant=1000 conforms", ok["conforms"])
bad = validate_input(graph, "MM.Inventory.GetAvailability", "plant", "12")
check("validate plant=12 rejected", not bad["conforms"], str(bad["violations"]))

# 2. preconditions: satisfied / missing / conditional requiredWhen
ok = evaluate_preconditions(
    graph, "MM.Inventory.GetAvailability", {"material": "DEMOA2", "plant": "1000"}
)
check("preconditions satisfied", ok["satisfied"], str(ok["missing"]))
bad = evaluate_preconditions(graph, "MM.Inventory.GetAvailability", {})
check("preconditions missing reported", not bad["satisfied"] and len(bad["missing"]) == 2, str(bad["missing"]))
cond = evaluate_preconditions(
    graph,
    "MM.PR.CreateDraft",
    {
        "material": "DEMOA2", "plant": "1000", "quantity": "100",
        "unit": "EA", "delivery_date": "2026-10-01", "purchasing_group": "001",
        "acct_assgn_cat": "K",
    },
)
check("conditional K -> cost_center", not cond["satisfied"] and "cost_center" in cond["missing"], str(cond["missing"]))

# 3. permission duty: holds / rejected
approval_ok = {
    "capabilityId": "MM.PR.CreateDraft",
    "parameterSnapshotHash": "hash-1",
    "status": "approved",
    "expiresAt": "2099-01-01T00:00:00+00:00",
}
ok = check_permission(
    graph, "MM.PR.CreateDraft", approval_ok, parameter_snapshot_hash="hash-1"
)
check("permission holds with approved record", ok["permission_holds"], str(ok["checks"]))
bad = check_permission(
    graph,
    "MM.PR.CreateDraft",
    {**approval_ok, "parameterSnapshotHash": "hash-other"},
    parameter_snapshot_hash="hash-1",
)
check("permission denied on hash mismatch", not bad["permission_holds"])

# 4. recall: found / none
ok = recall_capabilities(graph, "查一下物料库存")
inventory_node = "https://sap-nexus-agent.local/ontology#MM_Inventory_GetAvailability"
check("recall hits inventory", any(c["capabilityNode"] == inventory_node for c in ok), str(ok))
bad = recall_capabilities(graph, "zzz无关词xyz")
check("recall empty for unrelated text", bad == [])

# 5. same recall SPARQL runs on the semantica Oxigraph backend
store = OxigraphStore(path="/tmp/control-oxigraph")
native = store.store
repo = Path("/home/shrek/projects/GitHub_Projects/sap-nexus-agent")
for f in sorted((repo / "ontology").glob("*.owl")):
    native.bulk_load(f.read_bytes(), format=pyoxigraph.RdfFormat.RDF_XML)
native.bulk_load(
    (repo / "spikes/semantica-shadow/bundle/skos-capabilities.ttl").read_bytes(),
    format=pyoxigraph.RdfFormat.TURTLE,
)
result = store.execute_sparql(
    "PREFIX skos: <http://www.w3.org/2004/02/skos/core#> "
    "SELECT DISTINCT ?cap WHERE { ?cap a skos:Concept } "
    "LIMIT 100",
)
check("SPARQL works on semantica Oxigraph backend", result["success"] and len(result["bindings"]) >= 7,
      f"{len(result['bindings'])} concepts")

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)

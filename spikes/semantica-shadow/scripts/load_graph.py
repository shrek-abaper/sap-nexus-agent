#!/usr/bin/env python3
"""Load existing ontology/*.owl into an embedded Oxigraph graph for Semantica.

Task 1: verify our authored OWL is accepted as-is. Semantica's Triplet
loader has no blank-node support, but our datatype restrictions contain
blank rdf:Description nodes, so we bulk-load through the underlying
pyoxigraph store (native RDF/XML parsing, bnodes preserved) and then query
the same graph through the Semantica wrapper.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

SPIKE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SPIKE_ROOT.parents[1]

sys.path.insert(0, str(SPIKE_ROOT))

import pyoxigraph  # noqa: E402
from rdflib import Graph  # noqa: E402
from semantica.triplet_store import OxigraphStore  # noqa: E402

ONTOLOGY_DIR = REPO_ROOT / "ontology"
GRAPH_DIR = SPIKE_ROOT / "graph"


def _triple_count(path: Path) -> int:
    graph = Graph()
    graph.parse(path, format="xml")
    return len(graph)


def main() -> int:
    if GRAPH_DIR.exists():
        shutil.rmtree(GRAPH_DIR)
    wrapper = OxigraphStore(path=str(GRAPH_DIR))
    native = wrapper.store  # underlying pyoxigraph Store

    per_file: dict[str, int] = {}
    for owl_path in sorted(ONTOLOGY_DIR.glob("*.owl")):
        native.bulk_load(
            owl_path.read_bytes(),
            format=pyoxigraph.RdfFormat.RDF_XML,
        )
        per_file[owl_path.name] = _triple_count(owl_path)

    wrapper.flush()

    for name, count in per_file.items():
        print(f"{name:32s} {count:5d} triples")
    print("-" * 42)
    print(f"TOTAL                            {sum(per_file.values()):5d} triples")

    query = "SELECT (COUNT(*) AS ?n) WHERE { ?s ?p ?o }"
    print(f"SPARQL via Semantica: {wrapper.execute_sparql(query)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

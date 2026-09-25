"""Runtime constraint resolution: SHACL validation and precondition queries.

Resolve/enforce separation: this module answers "does the value satisfy the
shape" and "are preconditions met" against the versioned, generated SHACL
graph. It never blocks, routes, or executes; deterministic code enforces its
results.

The SHACL/SKOS artifacts are generated at build time (ontology_codegen) and
bound to the registry snapshot. SPARQL queries are prepared once and cached;
the graph is loaded once per process.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF, XSD
from rdflib.plugins.sparql import prepareQuery
import yaml

ONTOLOGY_NAMESPACE = "https://sap-nexus-agent.local/ontology#"
SH = "http://www.w3.org/ns/shacl#"
SKOS = "http://www.w3.org/2004/02/skos/core#"

_DUMMY_SUBJECT = URIRef("https://sap-nexus-agent.local/runtime/value")
_HOLDS = URIRef(f"{SH}holds")


class ConstraintRuntime:
    """Loads generated shapes and resolves validation/preconditions."""

    def __init__(self, repo_root: Path):
        self.repo_root = repo_root
        self.generated = repo_root / "ontology" / "generated"
        self._shapes: Graph | None = None
        self._registry_index: dict[str, dict] | None = None

    # ----------------------------- graph loading -----------------------------

    def _load_shapes(self) -> Graph:
        if self._shapes is None:
            graph = Graph()
            graph.parse(self.generated / "shacl-inputs.ttl", format="turtle")
            self._shapes = graph
        return self._shapes

    def _registry(self) -> dict[str, dict]:
        if self._registry_index is None:
            payload = yaml.safe_load(
                (self.repo_root / "registry" / "capabilities.yaml").read_text(
                    encoding="utf-8"
                )
            )
            self._registry_index = {
                cap["capabilityId"]: cap for cap in payload["capabilities"]
            }
        return self._registry_index

    # ------------------------------ validation -------------------------------

    def validate_value(
        self, capability_id: str, input_name: str, value: Any
    ) -> dict:
        """Validate one value against its generated NodeShape via pyshacl."""
        import pyshacl

        shape = self._shape_iri(capability_id, input_name)
        target = self._as_literal(value)

        data = Graph()
        data.add((_DUMMY_SUBJECT, _HOLDS, target))

        overlay = self._load_shapes() + Graph()
        overlay.add((shape, URIRef(f"{SH}targetNode"), target))

        conforms, _results_graph, results_text = pyshacl.validate(
            data,
            shacl_graph=overlay,
            ont_graph=None,
            inference=None,
            meta_shacl=False,
            debug=False,
        )
        violations = [
            line for line in results_text.splitlines() if "Constraint Violated" in line
        ]
        return {
            "conforms": bool(conforms),
            "violations": violations or [results_text],
        }

    def validate_many(self, slots: dict[str, Any], capability_id: str) -> dict:
        """Validate every slot; conforms only if all shapes pass."""
        results = {
            name: self.validate_value(capability_id, name, value)["conforms"]
            for name, value in slots.items()
        }
        return {"perInput": results, "conforms": all(results.values())}

    # ----------------------------- preconditions -----------------------------

    def evaluate_preconditions(
        self, capability_id: str, slots: dict[str, Any]
    ) -> dict:
        """Required inputs present at execution boundary; plus requiredWhen
        and requireAny group preconditions."""
        graph = self._load_shapes()
        cap = self._registry()[capability_id]
        cap_node = self._capability_node(cap)

        fact_satisfiable = {
            inp["name"]
            for inp in cap["inputs"]
            if inp.get("satisfiableByFactType")
        }
        provided = {k for k, v in slots.items() if v not in (None, "")}

        missing: list[str] = []
        for row in graph.query(
            self._prepared_required(),
            initBindings={"cap": cap_node},
        ):
            name = str(row.input)
            if (
                bool(row.required)
                and name not in provided
                and name not in fact_satisfiable
            ):
                missing.append(name)

        require_any = (cap.get("intent") or {}).get("requireAny")
        if require_any and not any(
            slots.get(name) not in (None, "") for name in require_any["inputs"]
        ):
            group_name = require_any["missingName"]
            if group_name not in missing:
                missing.append(group_name)

        for inp in cap["inputs"]:
            cond = (inp.get("extraction") or {}).get("requiredWhen")
            if cond and str(slots.get(cond["field"])) == cond["equals"]:
                if not slots.get(inp["name"]) and inp["name"] not in missing:
                    missing.append(inp["name"])

        return {"satisfied": not missing, "missing": sorted(missing)}

    # -------------------------------- helpers --------------------------------

    @staticmethod
    def _shape_iri(capability_id: str, input_name: str) -> URIRef:
        safe = capability_id.replace(".", "_").replace("-", "_")
        return URIRef(f"{ONTOLOGY_NAMESPACE}Shape.{safe}.{input_name}")

    @staticmethod
    def _capability_node(cap: dict) -> URIRef:
        local = cap["ontologyIri"].split(":", 1)[1]
        return URIRef(ONTOLOGY_NAMESPACE + local)

    @staticmethod
    def _as_literal(value: Any) -> Literal:
        """Preserve numeric type as xsd:decimal; strings stay strings."""
        if isinstance(value, bool):
            return Literal(value)
        if isinstance(value, int):
            return Literal(value, datatype=XSD.integer)
        if isinstance(value, float):
            return Literal(value, datatype=XSD.decimal)
        from decimal import Decimal

        if isinstance(value, Decimal):
            return Literal(str(value), datatype=XSD.decimal)
        return Literal(str(value))

    @lru_cache(maxsize=4)  # noqa: B019 - prepared queries are immutable
    def _prepared_required(self):
        return prepareQuery(
            """
            PREFIX sh: <http://www.w3.org/ns/shacl#>
            PREFIX sapnexus: <https://sap-nexus-agent.local/ontology#>
            SELECT ?input ?required WHERE {
                ?shape a sh:NodeShape ;
                       sapnexus:forCapability ?cap ;
                       sapnexus:forInput ?input ;
                       sapnexus:required ?required .
            }
            """
        )


@lru_cache(maxsize=4)
def get_runtime(repo_root: str) -> ConstraintRuntime:
    """One cached runtime per project root: graph and plans loaded once."""
    return ConstraintRuntime(Path(repo_root))

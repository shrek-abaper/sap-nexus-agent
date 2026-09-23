"""Serialize ReasoningFact JSON into Turtle.

One-directional escape hatch: facts stay authored and validated as JSON; this
module only projects them into RDF so a future triplestore / SPARQL / Graph RAG
consumer does not have to rebuild the mapping. It never reads facts back and is
not a runtime dependency of intent parsing or execution.

No third-party RDF library: Turtle literals are escaped by hand.
"""

from __future__ import annotations

from typing import Any, Mapping

_ONTOLOGY_NAMESPACE = "https://sap-nexus-agent.local/ontology#"
_FACTS_NAMESPACE = "https://sap-nexus-agent.local/facts/"

_PREFIXES = (
    f"@prefix sapnexus: <{_ONTOLOGY_NAMESPACE}> .\n"
    f"@prefix fact: <{_FACTS_NAMESPACE}> .\n"
    "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .\n"
)


def fact_to_turtle(fact: Mapping[str, Any]) -> str:
    """Render one ReasoningFact mapping as a Turtle individual.

    Only recognized scalar fields are emitted; absent/None fields are skipped.
    ``evidence`` and ``source`` are kept as blank nodes so the provenance
    survives the projection.
    """
    fact_id = str(fact.get("factId") or "").strip()
    if not fact_id:
        raise ValueError("fact must carry a non-empty factId")

    triples: list[str] = []
    triples.append(f"fact:{_local(fact_id)} a sapnexus:ReasoningFact")
    triples.append(f"    sapnexus:factId {_literal(fact_id)}")

    for field in (
        "agentTraceId",
        "traceId",
        "gatewayTraceId",
        "domain",
        "businessObject",
        "predicate",
        "material",
        "plant",
        "unit",
    ):
        value = fact.get(field)
        if value is not None and str(value) != "":
            triples.append(f"    sapnexus:{_camel(field)} {_literal(str(value))}")

    value = fact.get("value")
    if isinstance(value, bool) or isinstance(value, (int, float)):
        triples.append(f"    sapnexus:hasValue {_number(value)}")

    confidence = fact.get("confidence")
    if isinstance(confidence, (int, float)):
        triples.append(f"    sapnexus:confidence {_number(confidence)}")

    deterministic = fact.get("deterministic")
    if isinstance(deterministic, bool):
        triples.append(f"    sapnexus:deterministic {'true' if deterministic else 'false'}")

    source = fact.get("source")
    if isinstance(source, Mapping) and source:
        triples.append(f"    sapnexus:source {_blank_node_map(source)}")

    evidence = fact.get("evidence")
    if isinstance(evidence, list) and evidence:
        nodes = [
            _blank_node_map(item)
            for item in evidence
            if isinstance(item, Mapping) and item
        ]
        if nodes:
            triples.append(f"    sapnexus:evidence {' , '.join(nodes)}")

    return " ;\n".join(triples) + " .\n"


def facts_to_turtle(facts: list[Mapping[str, Any]]) -> str:
    """Render multiple facts under one shared prefix block."""
    bodies = "\n".join(fact_to_turtle(fact) for fact in facts)
    return f"{_PREFIXES}\n{bodies}"


def _blank_node_map(values: Mapping[str, Any]) -> str:
    """Render a flat mapping as an inline Turtle blank node."""
    parts: list[str] = []
    for key, value in values.items():
        if value is None or value == "":
            continue
        if isinstance(value, bool):
            rendered = "true" if value else "false"
        elif isinstance(value, (int, float)):
            rendered = _number(value)
        elif isinstance(value, Mapping):
            rendered = _blank_node_map(value)
        else:
            rendered = _literal(str(value))
        parts.append(f"sapnexus:{_camel(str(key))} {rendered}")
    return "[ " + " ; ".join(parts) + " ]"


def _literal(value: str) -> str:
    escaped = (
        value.replace("\\", "\\\\")
        .replace("\t", "\\t")
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace('"', '\\"')
    )
    return f'"{escaped}"'


def _number(value: int | float | bool) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _camel(name: str) -> str:
    parts = name.split("_")
    return parts[0] + "".join(part[:1].upper() + part[1:] for part in parts[1:])


def _local(identifier: str) -> str:
    """Turtle-safe local name for a fact id (fact-<uuid> already is, but
    sanitize defensively instead of trusting the shape)."""
    safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in identifier)
    return safe or "fact"

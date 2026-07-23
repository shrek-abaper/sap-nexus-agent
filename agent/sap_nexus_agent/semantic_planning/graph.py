from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
import math
from types import MappingProxyType
from typing import Any

from .contracts import SemanticSourceDocuments


def _deep_freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("unsupported graph value: mapping keys must be strings")
        return MappingProxyType(
            {key: _deep_freeze(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_deep_freeze(item) for item in value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise TypeError("unsupported graph value: non-finite float")
        return value
    if value is None or isinstance(value, (str, bool, int)):
        return value
    raise TypeError(f"unsupported graph value: {type(value).__name__}")


@dataclass(frozen=True, order=True)
class SemanticEdge:
    relation_type: str
    source_id: str
    target_id: str


@dataclass(frozen=True)
class ImmutableSemanticGraph:
    capabilities: Mapping[str, Mapping[str, Any]]
    fact_types: Mapping[str, Mapping[str, Any]]
    edges: tuple[SemanticEdge, ...]
    producers_by_fact_type: Mapping[str, tuple[str, ...]]
    consumers_by_fact_type: Mapping[str, tuple[str, ...]]


class SemanticGraphCompiler:
    def compile(self, sources: SemanticSourceDocuments) -> ImmutableSemanticGraph:
        capabilities = {
            item["capabilityId"]: _deep_freeze(item)
            for item in sources.capabilities["capabilities"]
        }
        fact_types = {
            item["factTypeId"]: _deep_freeze(item)
            for item in sources.fact_types["factTypes"]
        }
        edges: set[SemanticEdge] = set()
        for capability_id, capability in capabilities.items():
            for output in capability["outputs"]:
                fact_type_id = output.get("factTypeRef")
                if fact_type_id:
                    edges.add(
                        SemanticEdge(
                            "producesFactType", capability_id, fact_type_id
                        )
                    )
            for input_field in capability["inputs"]:
                if input_field["bindingKind"] == "fact":
                    edges.add(
                        SemanticEdge(
                            "consumesFactType",
                            capability_id,
                            input_field["satisfiableByFactType"],
                        )
                    )
        for relation in sources.relations["relations"]:
            if relation["relationType"] == "dependsOn":
                target = relation["dependsOnCapabilityId"]
            else:
                target = relation["requiredFactType"]
            edges.add(
                SemanticEdge(
                    relation["relationType"], relation["capabilityId"], target
                )
            )

        ordered_edges = tuple(sorted(edges))
        return ImmutableSemanticGraph(
            capabilities=MappingProxyType(capabilities),
            fact_types=MappingProxyType(fact_types),
            edges=ordered_edges,
            producers_by_fact_type=_index_fact_edges(
                ordered_edges, "producesFactType"
            ),
            consumers_by_fact_type=_index_fact_edges(
                ordered_edges, "consumesFactType"
            ),
        )


def _index_fact_edges(
    edges: tuple[SemanticEdge, ...],
    relation_type: str,
) -> Mapping[str, tuple[str, ...]]:
    index: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        if edge.relation_type == relation_type:
            index[edge.target_id].append(edge.source_id)
    return MappingProxyType(
        {
            fact_type_id: tuple(sorted(set(capability_ids)))
            for fact_type_id, capability_ids in sorted(index.items())
        }
    )

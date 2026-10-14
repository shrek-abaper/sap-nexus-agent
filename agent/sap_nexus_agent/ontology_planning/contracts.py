"""Frozen v1 contracts for ontology-governed read analysis.

CamelCase ``to_dict()`` shapes match the JSON Schemas under ``schemas/``.
SemanticGoalDraft is the untrusted interpreter output; later contracts
(TypedFact, AnalysisResult, ReadAnalysisPlan) are server-owned and are
added to this same module by subsequent tasks.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

_CONSTRAINT_SOURCES = ("explicitUser", "confirmedContext")


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({k: _freeze(v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(v) for v in value)
    return value


@dataclass(frozen=True)
class ObjectSelector:
    object_type_id: str
    key: str
    value: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "objectTypeId": self.object_type_id,
            "key": self.key,
            "value": self.value,
        }

    @classmethod
    def from_dict(cls, document: Mapping[str, Any]) -> "ObjectSelector":
        return cls(
            object_type_id=str(document["objectTypeId"]),
            key=str(document["key"]),
            value=str(document["value"]),
        )


@dataclass(frozen=True)
class RequestedFact:
    fact_type_id: str
    fields: tuple[str, ...]
    selectors: tuple[ObjectSelector, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "factTypeId": self.fact_type_id,
            "fields": list(self.fields),
            "objectSelectors": [s.to_dict() for s in self.selectors],
        }

    @classmethod
    def from_dict(cls, document: Mapping[str, Any]) -> "RequestedFact":
        return cls(
            fact_type_id=str(document["factTypeId"]),
            fields=tuple(document.get("fields", ())),
            selectors=tuple(
                ObjectSelector.from_dict(s)
                for s in document.get("objectSelectors", ())
            ),
        )


@dataclass(frozen=True)
class TypedConstraint:
    name: str
    semantic_type: str
    value: str
    source: str

    def __post_init__(self) -> None:
        if self.source not in _CONSTRAINT_SOURCES:
            raise ValueError(
                f"constraint source must be one of {_CONSTRAINT_SOURCES}, "
                f"got {self.source!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "semanticType": self.semantic_type,
            "value": self.value,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, document: Mapping[str, Any]) -> "TypedConstraint":
        return cls(
            name=str(document["name"]),
            semantic_type=str(document["semanticType"]),
            value=str(document["value"]),
            source=str(document["source"]),
        )


@dataclass(frozen=True)
class AnalysisNodeDraft:
    node_id: str
    operator_id: str
    inputs: tuple[Mapping[str, Any], ...]
    params: Mapping[str, Any]
    depends_on: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "inputs", tuple(_freeze(i) for i in self.inputs))
        object.__setattr__(self, "params", _freeze(self.params))

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodeId": self.node_id,
            "operatorId": self.operator_id,
            "inputs": [dict(i) for i in self.inputs],
            "params": dict(self.params),
            "dependsOn": list(self.depends_on),
        }

    @classmethod
    def from_dict(cls, document: Mapping[str, Any]) -> "AnalysisNodeDraft":
        return cls(
            node_id=str(document["nodeId"]),
            operator_id=str(document["operatorId"]),
            inputs=tuple(dict(i) for i in document.get("inputs", ())),
            params=dict(document.get("params", {})),
            depends_on=tuple(document.get("dependsOn", ())),
        )


@dataclass(frozen=True)
class RequestedConclusion:
    id: str
    statement: str
    evidence_requirement: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "statement": self.statement,
            "evidenceRequirement": self.evidence_requirement,
        }

    @classmethod
    def from_dict(cls, document: Mapping[str, Any]) -> "RequestedConclusion":
        return cls(
            id=str(document["id"]),
            statement=str(document["statement"]),
            evidence_requirement=str(document.get("evidenceRequirement", "")),
        )


@dataclass(frozen=True)
class SemanticGoalDraft:
    schema_version: int
    requested_facts: tuple[RequestedFact, ...]
    constraints: tuple[TypedConstraint, ...]
    analysis_nodes: tuple[AnalysisNodeDraft, ...]
    requested_conclusions: tuple[RequestedConclusion, ...]
    assumptions: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schema_version,
            "requestedFacts": [f.to_dict() for f in self.requested_facts],
            "constraints": [c.to_dict() for c in self.constraints],
            "analysisNodes": [n.to_dict() for n in self.analysis_nodes],
            "requestedConclusions": [
                c.to_dict() for c in self.requested_conclusions
            ],
            "assumptions": list(self.assumptions),
        }

    @classmethod
    def from_dict(cls, document: Mapping[str, Any]) -> "SemanticGoalDraft":
        return cls(
            schema_version=int(document["schemaVersion"]),
            requested_facts=tuple(
                RequestedFact.from_dict(f)
                for f in document.get("requestedFacts", ())
            ),
            constraints=tuple(
                TypedConstraint.from_dict(c)
                for c in document.get("constraints", ())
            ),
            analysis_nodes=tuple(
                AnalysisNodeDraft.from_dict(n)
                for n in document.get("analysisNodes", ())
            ),
            requested_conclusions=tuple(
                RequestedConclusion.from_dict(c)
                for c in document.get("requestedConclusions", ())
            ),
            assumptions=tuple(document.get("assumptions", ())),
        )

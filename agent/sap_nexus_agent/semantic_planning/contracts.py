from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Mapping

if TYPE_CHECKING:
    from .graph import ImmutableSemanticGraph


def _deep_freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {key: _deep_freeze(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_deep_freeze(item) for item in value)
    return value


@dataclass(frozen=True, order=True)
class ValidationIssue:
    path: str
    code: str
    message: str


@dataclass(frozen=True)
class ContractValidationReport:
    valid: bool
    issues: tuple[ValidationIssue, ...]


@dataclass(frozen=True)
class GoalReachabilityReport:
    valid: bool
    issues: tuple[ValidationIssue, ...]
    reachable_fact_types: tuple[str, ...]
    capability_gaps: tuple[str, ...]


@dataclass(frozen=True)
class PlanValidationReport:
    valid: bool
    issues: tuple[ValidationIssue, ...]


@dataclass(frozen=True)
class SnapshotSource:
    path: str
    document_version: int
    digest: str


@dataclass(frozen=True)
class RegistrySnapshot:
    snapshot_version: int
    canonicalization_version: int
    snapshot_id: str
    sources: tuple[SnapshotSource, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshotVersion": self.snapshot_version,
            "canonicalizationVersion": self.canonicalization_version,
            "snapshotId": self.snapshot_id,
            "sources": [
                {
                    "path": item.path,
                    "documentVersion": item.document_version,
                    "digest": item.digest,
                }
                for item in self.sources
            ],
        }


@dataclass(frozen=True)
class ContractBuildResult:
    report: ContractValidationReport
    graph: "ImmutableSemanticGraph | None"
    snapshot: RegistrySnapshot | None


@dataclass(frozen=True)
class SemanticSourceDocuments:
    capabilities: Mapping[str, Any]
    executor_bindings: Mapping[str, Any]
    fact_types: Mapping[str, Any]
    relations: Mapping[str, Any]

    def __post_init__(self) -> None:
        for field_name in (
            "capabilities",
            "executor_bindings",
            "fact_types",
            "relations",
        ):
            object.__setattr__(
                self, field_name, _deep_freeze(getattr(self, field_name))
            )

    def documents_by_path(self) -> Mapping[str, Mapping[str, Any]]:
        return MappingProxyType(
            {
                "ontology/capability-relations.yaml": self.relations,
                "ontology/fact-types.yaml": self.fact_types,
                "registry/capabilities.yaml": self.capabilities,
                "registry/executor-bindings.yaml": self.executor_bindings,
            }
        )


def sorted_issues(issues: list[ValidationIssue]) -> tuple[ValidationIssue, ...]:
    return tuple(sorted(issues, key=lambda item: (item.path, item.code, item.message)))

"""Frozen contracts for the SemanticRelease v1 package.

These types describe the versioned semantic asset package consumed by the
ontology-governed read analysis path. They deliberately do not extend the
legacy RegistrySnapshot contracts: a package *binds* an existing legacy
``registrySnapshotId`` to a new ``semanticSnapshotId`` rather than replacing
it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any


def _freeze_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType(dict(value))


@dataclass(frozen=True, order=True)
class ReleaseSource:
    """One hashed document covered by a SemanticRelease package."""

    path: str
    document_version: int
    digest: str
    role: str  # "legacy" | "semantic"

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "documentVersion": self.document_version,
            "digest": self.digest,
            "role": self.role,
        }


@dataclass(frozen=True)
class SemanticReleasePackage:
    """The SemanticRelease v1 package document."""

    schema_version: int
    registry_snapshot_id: str
    semantic_snapshot_id: str
    compiler_version: str
    operator_implementation_version: Mapping[str, str]
    sources: tuple[ReleaseSource, ...]
    business_validity: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "operator_implementation_version",
            _freeze_mapping(self.operator_implementation_version),
        )
        object.__setattr__(
            self, "business_validity", _freeze_mapping(self.business_validity)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schema_version,
            "registrySnapshotId": self.registry_snapshot_id,
            "semanticSnapshotId": self.semantic_snapshot_id,
            "compilerVersion": self.compiler_version,
            "operatorImplementationVersion": dict(
                self.operator_implementation_version
            ),
            "sources": [source.to_dict() for source in self.sources],
            "businessValidity": dict(self.business_validity),
        }


@dataclass(frozen=True, order=True)
class SemanticReleaseIssue:
    """One structural validation finding."""

    path: str
    code: str
    message: str


@dataclass(frozen=True)
class StructuralValidationReport:
    valid: bool
    issues: tuple[SemanticReleaseIssue, ...]


@dataclass(frozen=True, order=True)
class BusinessValidityEntry:
    """Business-validity state for one applicability declaration."""

    definition_id: str
    declared_status: str
    state: str  # "grounded" | "not_grounded"


@dataclass(frozen=True)
class BusinessValidityReport:
    entries: tuple[BusinessValidityEntry, ...]


STRUCTURAL_ISSUE_CODES: tuple[str, ...] = (
    "SR_SCHEMA_INVALID",
    "SR_UNKNOWN_FIELD_REF",
    "SR_UNKNOWN_FACT_TYPE",
    "SR_UNKNOWN_SEMANTIC_TYPE",
    "SR_UNKNOWN_OPERATOR",
    "SR_OPERATOR_NOT_IN_CLOSED_SET",
    "SR_UNKNOWN_DEFINITION_REF",
    "SR_DIGEST_MISMATCH",
    "SR_SNAPSHOT_ID_MISMATCH",
    "SR_DUPLICATE_SOURCE",
    "SR_MANIFEST_VIOLATION",
)

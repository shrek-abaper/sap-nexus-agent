"""Governed context data structures for same-snapshot binding and fail-closed planner.

Design Doc: docs/superpowers/specs/2026-08-03-governed-context-registry-snapshot-design.md
section 3 (核心数据结构).

This module binds principal, visibility, matcher, planner and approval to one
non-empty RegistrySnapshot via ``GovernedContext`` / ``SnapshotLease`` /
``VisibleCapabilitySet`` / ``PlannerFailure``. It replaces the silent
``except Exception: return None`` degradation in ``_compile_dry_run_safely``
with structured fail-closed errors.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Literal

from sap_nexus_agent.planner.capability_card import CapabilityCard
from sap_nexus_agent.semantic_planning.contracts import (
    RegistrySnapshot,
    SemanticSourceDocuments,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TrustedPrincipal:
    """Python-side principal, aligned with frontend TS TrustedPrincipal.

    Fields match ``frontend/src/runtime/principal/types.ts``. Server-owned:
    must not be supplied by request body, prompt, history or LLM output.
    """

    principal_id: str
    role: str  # "admin" | "operator" | "viewer"
    data_scope: dict[str, str]  # {"tenantId": "..."}


PLACEHOLDER_PRINCIPAL = TrustedPrincipal(
    principal_id="local-user-0001",
    role="operator",
    data_scope={"tenantId": "default"},
)


def load_principal_from_env() -> TrustedPrincipal:
    """Read ``SAP_NEXUS_PRINCIPAL`` env var (JSON) -> ``TrustedPrincipal``.

    Missing or malformed -> ``PLACEHOLDER_PRINCIPAL`` (local dev tolerance).
    The principal remains server-owned: the env var is set by the backend
    when spawning the Python CLI, not by request body or LLM output.
    """
    raw = os.environ.get("SAP_NEXUS_PRINCIPAL")
    if not raw:
        return PLACEHOLDER_PRINCIPAL
    try:
        data = json.loads(raw)
        return TrustedPrincipal(
            principal_id=str(data["principalId"]),
            role=str(data.get("role", "operator")),
            data_scope={
                k: str(v)
                for k, v in dict(
                    data.get("dataScope", {"tenantId": "default"})
                ).items()
            },
        )
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        logger.warning(
            "SAP_NEXUS_PRINCIPAL env malformed, falling back to PLACEHOLDER_PRINCIPAL"
        )
        return PLACEHOLDER_PRINCIPAL


class SnapshotDriftError(Exception):
    """Raised when snapshot_id differs between lease and a downstream stage."""

    def __init__(self, expected: str, actual: str, stage: str):
        super().__init__(
            f"snapshot drift at stage '{stage}': expected={expected}, actual={actual}"
        )
        self.expected = expected
        self.actual = actual
        self.stage = stage


@dataclass(frozen=True)
class GovernedContext:
    """Context bound to one RegistrySnapshot for a single Agent run.

    Carries ``principal``, ``scopes``, non-empty ``snapshot_id`` and
    ``registry_version``. intent, recall, matcher, planner and approval all
    bind to the same ``snapshot_id``.
    """

    principal: TrustedPrincipal
    scopes: tuple[str, ...]  # derived from data_scope, reserved
    snapshot_id: str  # non-empty, from RegistrySnapshot.snapshot_id
    registry_version: int  # from RegistrySnapshot.snapshot_version


@dataclass(frozen=True)
class SnapshotLease:
    """Holds a RegistrySnapshot + sources; asserts same-snapshot at each stage.

    matcher and planner consume ``lease.snapshot_id`` and must not reload a
    different snapshot. Drift raises ``SnapshotDriftError`` (translated to
    ``PlannerFailure(SNAPSHOT_DRIFT)`` by the orchestrator).
    """

    snapshot: RegistrySnapshot
    sources: SemanticSourceDocuments

    @property
    def snapshot_id(self) -> str:
        return self.snapshot.snapshot_id

    @property
    def registry_version(self) -> int:
        return self.snapshot.snapshot_version

    def assert_same(self, other_snapshot_id: str, stage: str) -> None:
        if self.snapshot_id != other_snapshot_id:
            raise SnapshotDriftError(self.snapshot_id, other_snapshot_id, stage)


@dataclass(frozen=True)
class VisibleCapabilitySet:
    """Filtered capability cards bound to a snapshot and principal.

    Produced by ``filter_visible`` after principal/visibility pre-filter.
    Sole capability source for intent recognition, matcher decisions and
    candidate recall. Invisible capabilities are removed before entering the
    LLM prompt.
    """

    cards: tuple[CapabilityCard, ...]  # already filter_visible'd
    snapshot_id: str
    principal_id: str


PlannerErrorType = Literal[
    "SNAPSHOT_MISSING",
    "SNAPSHOT_DRIFT",
    "PRINCIPAL_MISMATCH",
    "SOURCE_LOAD_ERROR",
    "VISIBILITY_DENIED",
]


@dataclass(frozen=True)
class PlannerFailure(Exception):
    """Structured planner failure with audit evidence (no silent None).

    Replaces ``_compile_dry_run_safely``'s ``except Exception: return None``.
    ``audit_evidence`` carries ``expected_snapshot_id``, ``actual_snapshot_id``,
    ``principal_id``, ``source_paths`` and ``stage`` for audit/eval.
    """

    error_type: PlannerErrorType
    message: str
    snapshot_id: str | None
    audit_evidence: dict

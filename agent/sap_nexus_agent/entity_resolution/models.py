"""Entity resolution domain models (spec: entity-resolution-contracts).

`EntityMention` (user text), `EntityCandidateView` (display projection of one
candidate), `EntityChoiceSet` (server-side candidate set), and
`ResolvedEntityRef` (bound reference with evidence) are separate concepts and
must never be conflated. The model layer never fabricates canonical codes:
every code here originates from the governed search capability response.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Mapping

_UTC_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$")


def _require(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


def _pairs(value: object, field_name: str) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, (tuple, list)):
        raise ValueError(f"{field_name} must be a list of pairs")
    result = []
    for item in value:
        if not isinstance(item, (tuple, list)) or len(item) != 2:
            raise ValueError(f"{field_name} must contain pairs")
        key, val = item
        if not isinstance(key, str) or not key or not isinstance(val, str):
            raise ValueError(f"{field_name} keys must be non-empty strings, values strings")
        result.append((key, val))
    return tuple(result)


@dataclass(frozen=True)
class EntityMention:
    """The user's unresolved description; never an identifier by itself."""

    text: str
    source_turn_id: str

    def __post_init__(self) -> None:
        _require(self.text, "EntityMention.text")
        _require(self.source_turn_id, "EntityMention.source_turn_id")


@dataclass(frozen=True)
class EntityCandidateView:
    """Display-safe projection of one candidate (server-issued)."""

    index: int
    canonical_code: str
    display_name: str
    distinguishing: tuple[tuple[str, str], ...]
    match_kind: str
    status: str
    org_scopes: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        _require(self.canonical_code, "EntityCandidateView.canonical_code")
        if self.status not in {"active", "inactive"}:
            raise ValueError("EntityCandidateView.status is invalid")
        object.__setattr__(self, "distinguishing", _pairs(self.distinguishing, "distinguishing"))
        object.__setattr__(self, "org_scopes", _pairs(self.org_scopes, "org_scopes"))

    def to_dict(self) -> dict[str, object]:
        return {
            "index": self.index,
            "canonicalCode": self.canonical_code,
            "displayName": self.display_name,
            "distinguishing": dict(self.distinguishing),
            "matchKind": self.match_kind,
            "status": self.status,
            "orgScopes": [{"field": f, "value": v} for f, v in self.org_scopes],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "EntityCandidateView":
        distinguishing = payload.get("distinguishing") or {}
        org_scopes = payload.get("orgScopes") or []
        return cls(
            index=int(payload.get("index", 0)),  # type: ignore[arg-type]
            canonical_code=_require(payload.get("canonicalCode"), "canonicalCode"),
            display_name=str(payload.get("displayName") or ""),
            distinguishing=tuple(sorted((str(k), str(v)) for k, v in distinguishing.items())),  # type: ignore[union-attr]
            match_kind=str(payload.get("matchKind") or ""),
            status=_require(payload.get("status"), "status"),
            org_scopes=tuple(
                (str(scope.get("field")), str(scope.get("value"))) for scope in org_scopes  # type: ignore[union-attr]
            ),
        )


@dataclass(frozen=True)
class EntityChoiceSet:
    """Server-side candidate set bound to frame/principal/snapshot/versions."""

    candidate_set_id: str
    object_type: str
    target_capability_id: str
    target_slot: str
    mention: str
    candidates: tuple[EntityCandidateView, ...]
    snapshot_id: str
    provider: str
    created_at: str
    expires_at: str
    principal_id: str
    registry_snapshot_id: str
    source_extracted_at: str | None = None

    def __post_init__(self) -> None:
        _require(self.candidate_set_id, "EntityChoiceSet.candidate_set_id")
        _require(self.object_type, "EntityChoiceSet.object_type")
        _require(self.target_capability_id, "EntityChoiceSet.target_capability_id")
        _require(self.target_slot, "EntityChoiceSet.target_slot")
        _require(self.snapshot_id, "EntityChoiceSet.snapshot_id")
        _require(self.principal_id, "EntityChoiceSet.principal_id")
        _require(self.registry_snapshot_id, "EntityChoiceSet.registry_snapshot_id")
        if not _UTC_ISO.match(self.created_at) or not _UTC_ISO.match(self.expires_at):
            raise ValueError("EntityChoiceSet timestamps must be UTC ISO")
        if not self.candidates:
            raise ValueError("EntityChoiceSet.candidates must not be empty")
        if not all(isinstance(c, EntityCandidateView) for c in self.candidates):
            raise ValueError("EntityChoiceSet.candidates must contain EntityCandidateView")
        indexes = [c.index for c in self.candidates]
        if indexes != list(range(1, len(self.candidates) + 1)):
            raise ValueError("EntityChoiceSet.candidates must be 1-indexed in display order")

    @staticmethod
    def issue_id(*, object_type: str, target_slot: str, mention: str,
                 codes: tuple[str, ...], snapshot_id: str) -> str:
        payload = json.dumps(
            [object_type, target_slot, mention, list(codes), snapshot_id],
            ensure_ascii=False,
        )
        return "ecs-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    def to_dict(self) -> dict[str, object]:
        return {
            "candidateSetId": self.candidate_set_id,
            "objectType": self.object_type,
            "targetCapabilityId": self.target_capability_id,
            "targetSlot": self.target_slot,
            "mention": self.mention,
            "candidates": [c.to_dict() for c in self.candidates],
            "snapshotId": self.snapshot_id,
            "provider": self.provider,
            "createdAt": self.created_at,
            "expiresAt": self.expires_at,
            "principalId": self.principal_id,
            "registrySnapshotId": self.registry_snapshot_id,
            "sourceExtractedAt": self.source_extracted_at,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "EntityChoiceSet":
        candidates = payload.get("candidates")
        if not isinstance(candidates, (list, tuple)):
            raise ValueError("EntityChoiceSet.candidates must be a list")
        return cls(
            candidate_set_id=_require(payload.get("candidateSetId"), "candidateSetId"),
            object_type=_require(payload.get("objectType"), "objectType"),
            target_capability_id=_require(
                payload.get("targetCapabilityId"), "targetCapabilityId"),
            target_slot=_require(payload.get("targetSlot"), "targetSlot"),
            mention=str(payload.get("mention") or ""),
            candidates=tuple(EntityCandidateView.from_dict(c) for c in candidates),
            snapshot_id=_require(payload.get("snapshotId"), "snapshotId"),
            provider=str(payload.get("provider") or ""),
            created_at=_require(payload.get("createdAt"), "createdAt"),
            expires_at=_require(payload.get("expiresAt"), "expiresAt"),
            principal_id=_require(payload.get("principalId"), "principalId"),
            registry_snapshot_id=_require(
                payload.get("registrySnapshotId"), "registrySnapshotId"),
            source_extracted_at=(
                str(payload["sourceExtractedAt"]) if payload.get("sourceExtractedAt") else None
            ),
        )


@dataclass(frozen=True)
class ResolvedEntityRef:
    """Server-issued evidence that an entity was resolved for a slot."""

    canonical_code: str
    object_type: str
    target_slot: str
    resolution: str  # exact-code | confirmed-choice
    snapshot_id: str
    candidate_set_id: str | None
    frame_id: str

    def __post_init__(self) -> None:
        _require(self.canonical_code, "ResolvedEntityRef.canonical_code")
        _require(self.object_type, "ResolvedEntityRef.object_type")
        _require(self.target_slot, "ResolvedEntityRef.target_slot")
        if self.resolution not in {"exact-code", "confirmed-choice"}:
            raise ValueError("ResolvedEntityRef.resolution is invalid")
        _require(self.snapshot_id, "ResolvedEntityRef.snapshot_id")
        _require(self.frame_id, "ResolvedEntityRef.frame_id")

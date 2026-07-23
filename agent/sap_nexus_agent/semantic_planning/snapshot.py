from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from .contracts import RegistrySnapshot, SemanticSourceDocuments, SnapshotSource


def _json_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        _json_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256_id(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def build_registry_snapshot(sources: SemanticSourceDocuments) -> RegistrySnapshot:
    documents = sources.documents_by_path()
    source_entries = tuple(
        SnapshotSource(
            path=path,
            document_version=int(document["version"]),
            digest=_sha256_id(document),
        )
        for path, document in documents.items()
    )
    return RegistrySnapshot(
        snapshot_version=1,
        canonicalization_version=1,
        snapshot_id=_sha256_id(dict(documents)),
        sources=source_entries,
    )

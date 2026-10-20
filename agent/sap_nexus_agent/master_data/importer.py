"""Explicit local CSV/JSON snapshot importer for the master-data projection.

Guarantees (spec: master-data-snapshot-store):

- validated batch declaration (source system/client/object type/coverage)
- dry-run validation; malformed or identity-duplicate batches never publish
- single-transaction staging + atomic publish; readers never see half a batch
- on failure the previous valid snapshot stays active
- full snapshots only; incremental batches are explicitly rejected
- a full snapshot replaces only its declared coverage
- source extraction time is recorded as unknown (NULL), never faked by load time
- re-importing identical content is idempotent (no-op)

Connection comes from SAP_NEXUS_MD_DSN or peer-auth defaults; never from
command-line arguments, so secrets cannot leak into shell history/logs.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import psycopg
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
RULES_PATH = REPO_ROOT / "ontology" / "entity-resolution.yaml"

ALLOWED_STATUS = {"active", "inactive"}


@dataclass(frozen=True)
class ImportReport:
    snapshot_id: str | None
    object_type: str
    entity_count: int
    dry_run: bool
    idempotent_reuse: bool
    superseded_snapshot_ids: tuple[str, ...] = ()
    errors: tuple[str, ...] = field(default=())


class BatchValidationError(ValueError):
    """Raised when a batch declaration or its entities fail validation."""


def _load_allowed_fields() -> dict[str, dict[str, set[str]]]:
    """Closed attribute/display field sets per object type from the ontology."""
    document = yaml.safe_load(RULES_PATH.read_text(encoding="utf-8"))
    allowed: dict[str, dict[str, set[str]]] = {}
    for entry in document["objectTypes"]:
        identifier = entry["identifierField"]
        display = set(entry["candidateDisplayFields"]) | set(entry["distinguishingFields"])
        searchable = {f["field"] for f in entry["searchableFields"]}
        org_fields = {f["field"] for f in entry["organizationalFilters"]}
        # Attribute columns: everything displayable/searchable that is neither
        # the identifier nor carried by description/alias/org-scope rows.
        attributes = (display | searchable) - {identifier, "description", "name", "alias"}
        allowed[entry["objectTypeId"]] = {
            "attributes": attributes,
            "org_fields": org_fields,
            "languages": set(entry["languages"]),
        }
    return allowed


def _canonical_hash(document: Mapping[str, Any]) -> str:
    payload = json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def validate_batch(document: Mapping[str, Any]) -> list[str]:
    """Collect every validation error; an empty list means publishable."""
    errors: list[str] = []
    batch = document.get("batch")
    if not isinstance(batch, Mapping):
        return ["batch declaration is required"]
    for key in ("sourceSystem", "client", "objectType", "snapshotKind", "coverage"):
        if key not in batch:
            errors.append(f"batch.{key} is required")
    if errors:
        return errors
    if batch["snapshotKind"] != "full":
        errors.append(
            f"snapshotKind {batch['snapshotKind']!r} is not supported; only full snapshots are accepted"
        )
        return errors
    coverage = batch.get("coverage") or {}
    if batch["sourceSystem"] not in coverage.get("sourceSystems", []):
        errors.append("coverage.sourceSystems must contain batch.sourceSystem")
    if batch["client"] not in coverage.get("clients", []):
        errors.append("coverage.clients must contain batch.client")
    if batch["objectType"] not in coverage.get("objectTypes", []):
        errors.append("coverage.objectTypes must contain batch.objectType")

    allowed = _load_allowed_fields().get(batch["objectType"])
    if allowed is None:
        errors.append(f"objectType {batch['objectType']!r} has no entity-resolution rule")
        return errors

    entities = document.get("entities")
    if not isinstance(entities, list) or not entities:
        errors.append("entities must be a non-empty list")
        return errors

    seen_codes: set[str] = set()
    for index, entity in enumerate(entities):
        where = f"entities[{index}]"
        if not isinstance(entity, Mapping):
            errors.append(f"{where} must be a mapping")
            continue
        code = entity.get("canonicalCode")
        if not isinstance(code, str) or not code:
            errors.append(f"{where}.canonicalCode must be a non-empty string")
            continue
        if code in seen_codes:
            errors.append(f"{where}.canonicalCode {code!r} duplicates an earlier entity")
        seen_codes.add(code)
        if entity.get("status") not in ALLOWED_STATUS:
            errors.append(f"{where}({code}).status must be one of {sorted(ALLOWED_STATUS)}")

        descriptions = entity.get("descriptions")
        if not isinstance(descriptions, list) or not descriptions:
            errors.append(f"{where}({code}).descriptions must be a non-empty list")
        else:
            official = 0
            for desc in descriptions:
                if desc.get("language") not in allowed["languages"]:
                    errors.append(
                        f"{where}({code}) language {desc.get('language')!r} not declared for this object type"
                    )
                if not isinstance(desc.get("text"), str) or not desc.get("text"):
                    errors.append(f"{where}({code}) description text must be non-empty")
                official += 1 if desc.get("official") else 0
            if official != 1:
                errors.append(f"{where}({code}) must have exactly one official description")

        attributes = entity.get("attributes") or {}
        for key in attributes:
            if key not in allowed["attributes"]:
                errors.append(f"{where}({code}) attribute {key!r} is not declared for this object type")

        for alias in entity.get("aliases") or []:
            if not isinstance(alias.get("alias"), str) or not alias.get("alias"):
                errors.append(f"{where}({code}) alias must be non-empty")
            for key in ("source", "scope"):
                if not isinstance(alias.get(key), str) or not alias.get(key):
                    errors.append(f"{where}({code}) alias.{key} is required")

        for scope in entity.get("orgScopes") or []:
            if scope.get("field") not in allowed["org_fields"]:
                errors.append(
                    f"{where}({code}) org scope field {scope.get('field')!r} not declared for this object type"
                )
            if not isinstance(scope.get("value"), str) or not scope.get("value"):
                errors.append(f"{where}({code}) org scope value must be non-empty")
    return errors


def _connect():
    dsn = os.environ.get("SAP_NEXUS_MD_DSN")
    if dsn:
        return psycopg.connect(dsn)
    return psycopg.connect(dbname=os.environ.get("SAP_NEXUS_MD_DBNAME", "sap_nexus_dev"))


def import_snapshot(document: Mapping[str, Any], *, dry_run: bool = False) -> ImportReport:
    """Validate and atomically publish one full snapshot batch."""
    errors = validate_batch(document)
    batch = document.get("batch") or {}
    object_type = str(batch.get("objectType", ""))
    entities = document.get("entities") or []
    if errors:
        return ImportReport(None, object_type, 0, dry_run, False, errors=tuple(errors))

    content_hash = _canonical_hash(document)
    snapshot_id = f"{batch['sourceSystem']}:{batch['client']}:{object_type}:{content_hash[:12]}"

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT snapshot_id FROM md.snapshot "
                "WHERE source_system=%s AND client=%s AND object_type=%s AND content_hash=%s "
                "AND status='active'",
                (batch["sourceSystem"], batch["client"], object_type, content_hash),
            )
            existing = cur.fetchone()
            if existing is not None:
                return ImportReport(existing[0], object_type, len(entities), dry_run, True)

            cur.execute(
                "SELECT snapshot_id FROM md.snapshot "
                "WHERE source_system=%s AND client=%s AND object_type=%s AND status='active'",
                (batch["sourceSystem"], batch["client"], object_type),
            )
            superseded = tuple(row[0] for row in cur.fetchall())
            if dry_run:
                return ImportReport(
                    snapshot_id, object_type, len(entities), True, False, superseded_snapshot_ids=superseded
                )

            # Single transaction: staging inserts + supersede + activate.
            with conn.transaction():
                cur.execute(
                    "INSERT INTO md.snapshot (snapshot_id, source_system, client, object_type,"
                    " snapshot_kind, coverage, content_hash, source_extracted_at, status)"
                    " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'loading')",
                    (
                        snapshot_id,
                        batch["sourceSystem"],
                        batch["client"],
                        object_type,
                        batch["snapshotKind"],
                        json.dumps(batch["coverage"], ensure_ascii=False),
                        content_hash,
                        batch.get("sourceExtractedAt"),
                    ),
                )
                for entity in entities:
                    code = entity["canonicalCode"]
                    key = (snapshot_id, batch["sourceSystem"], batch["client"], object_type, code)
                    cur.execute(
                        "INSERT INTO md.entity (snapshot_id, source_system, client, object_type,"
                        " canonical_code, status, attributes) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                        (*key, entity["status"], json.dumps(entity.get("attributes") or {}, ensure_ascii=False)),
                    )
                    for desc in entity.get("descriptions") or []:
                        cur.execute(
                            "INSERT INTO md.entity_description (snapshot_id, source_system, client,"
                            " object_type, canonical_code, language, description, is_official)"
                            " VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                            (*key, desc["language"], desc["text"], bool(desc.get("official"))),
                        )
                    for alias in entity.get("aliases") or []:
                        cur.execute(
                            "INSERT INTO md.entity_alias (snapshot_id, source_system, client,"
                            " object_type, canonical_code, alias, alias_source, scope, active)"
                            " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                            (*key, alias["alias"], alias["source"], alias["scope"], bool(alias.get("active", True))),
                        )
                    for scope in entity.get("orgScopes") or []:
                        cur.execute(
                            "INSERT INTO md.entity_org_scope (snapshot_id, source_system, client,"
                            " object_type, canonical_code, org_field, org_value)"
                            " VALUES (%s,%s,%s,%s,%s,%s,%s)",
                            (*key, scope["field"], scope["value"]),
                        )
                # Replace only the declared coverage: same system/client/object type.
                cur.execute(
                    "UPDATE md.snapshot SET status='superseded'"
                    " WHERE source_system=%s AND client=%s AND object_type=%s AND status='active'",
                    (batch["sourceSystem"], batch["client"], object_type),
                )
                cur.execute(
                    "UPDATE md.snapshot SET status='active' WHERE snapshot_id=%s",
                    (snapshot_id,),
                )
            return ImportReport(
                snapshot_id, object_type, len(entities), False, False, superseded_snapshot_ids=superseded
            )


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Import a master-data full snapshot batch.")
    parser.add_argument("fixture", type=Path, help="batch JSON file (synthetic or authorized export)")
    parser.add_argument("--dry-run", action="store_true", help="validate only; publish nothing")
    args = parser.parse_args(argv)

    document = json.loads(args.fixture.read_text(encoding="utf-8"))
    report = import_snapshot(document, dry_run=args.dry_run)
    if report.errors:
        for error in report.errors:
            print(f"ERROR {error}")
        return 1
    mode = "DRY-RUN" if report.dry_run else ("IDEMPOTENT" if report.idempotent_reuse else "PUBLISHED")
    print(f"{mode} snapshot={report.snapshot_id} entities={report.entity_count}")
    for superseded_id in report.superseded_snapshot_ids:
        print(f"superseded {superseded_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Master-data search Provider over the PostgreSQL projection.

Contract (spec: entity-search-provider):

- narrow interface: search(request, trusted_scope) and get_by_key(key, scope)
- callers never see PG tables/SQL; requests name a registered queryTemplateId
- trusted identity/systems/clients/org scope are server-injected and applied
  BEFORE pagination/ranking; client-supplied org filters may only narrow
- fixed parameterized queries; LIKE wildcards in user input are escaped;
  bounded limits; raw database errors never echo SQL/connection details
- explicit error taxonomy: no-match is not unavailable, not permission
  denied, not stale; exceptions never masquerade as empty candidate sets
- completeness distinguishes complete-result-set from partial/truncated,
  valid only within the authorized scope and declared coverage
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import psycopg
import yaml
from psycopg import errors as pg_errors

REPO_ROOT = Path(__file__).resolve().parents[3]
MAPPINGS_PATH = REPO_ROOT / "master-data" / "physical-mappings.yaml"

MATCH_EXACT_CODE = "exact-code"
MATCH_EXACT_LABEL = "exact-label"
MATCH_APPROVED_ALIAS = "approved-alias"
MATCH_SUBSTRING = "substring"
MATCH_TRIGRAM = "trigram"

COMPLETE = "complete-result-set"
TRUNCATED = "partial-truncated"

DEFAULT_LIMIT = 20
MAX_LIMIT = 50
TRIGRAM_MIN_QUERY_LENGTH = 3
TRIGRAM_THRESHOLD = 0.2


class ProviderError(Exception):
    """Typed provider failure; never carries SQL/connection details."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


@dataclass(frozen=True)
class TrustedScope:
    """Server-injected visibility; requests can only narrow it."""

    principal: str
    source_systems: tuple[str, ...]
    clients: tuple[str, ...]
    org_scopes: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    sandbox: bool = True


@dataclass(frozen=True)
class SearchRequest:
    query_template_id: str
    query: str | None = None
    entity_key: str | None = None
    language: str | None = None
    org_filters: Mapping[str, str] = field(default_factory=dict)
    limit: int = DEFAULT_LIMIT


@dataclass(frozen=True)
class EntityKey:
    source_system: str
    client: str
    object_type: str
    canonical_code: str


@dataclass(frozen=True)
class EntityCandidate:
    key: EntityKey
    display_name: str
    distinguishing: Mapping[str, str]
    match_kind: str
    status: str
    org_scopes: tuple[tuple[str, str], ...]
    score: float | None = None


@dataclass(frozen=True)
class CandidateSet:
    candidates: tuple[EntityCandidate, ...]
    snapshot_id: str
    source_extracted_at: str | None
    loaded_at: str
    completeness: str
    truncated: bool


def _like_escape(value: str) -> str:
    """Escape LIKE metacharacters so user input stays a literal substring."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class MasterDataProvider:
    def __init__(self, conn: psycopg.Connection, mappings_path: Path | None = None):
        self._conn = conn
        document = yaml.safe_load((mappings_path or MAPPINGS_PATH).read_text(encoding="utf-8"))
        self._templates = document["queryTemplates"]

    @classmethod
    def connect(cls, mappings_path: Path | None = None) -> "MasterDataProvider":
        dsn = os.environ.get("SAP_NEXUS_MD_DSN")
        try:
            conn = psycopg.connect(dsn) if dsn else psycopg.connect(
                dbname=os.environ.get("SAP_NEXUS_MD_DBNAME", "sap_nexus_dev")
            )
        except psycopg.OperationalError as exc:
            raise ProviderError("unavailable", "master-data store is not reachable") from exc
        return cls(conn, mappings_path)

    def close(self) -> None:
        self._conn.close()

    def _template(self, query_template_id: str) -> Mapping[str, Any]:
        template = self._templates.get(query_template_id)
        if template is None:
            raise ProviderError("invalid-request", f"unknown query template: {query_template_id}")
        return template

    def _execute(self, sql: str, params: tuple) -> list[tuple]:
        try:
            with self._conn.cursor() as cur:
                cur.execute(sql, params)
                return cur.fetchall()
        except pg_errors.InsufficientPrivilege as exc:
            raise ProviderError("permission-denied", "principal lacks master-data read privilege") from exc
        except psycopg.OperationalError as exc:
            raise ProviderError("unavailable", "master-data store is not reachable") from exc
        except psycopg.Error as exc:
            raise ProviderError("unavailable", "master-data query failed") from exc

    # -- retrieval primitives ------------------------------------------------

    def _entity_rows(self, template: Mapping[str, Any], scope: TrustedScope) -> dict[str, tuple]:
        """All entities of the object type visible inside the trusted scope."""
        rows = self._execute(
            "SELECT source_system, client, object_type, canonical_code, status, attributes,"
            " snapshot_id, loaded_at, source_extracted_at"
            " FROM md.v_entity_current"
            " WHERE object_type = %s AND source_system = ANY(%s) AND client = ANY(%s)",
            (template["objectType"], list(scope.source_systems), list(scope.clients)),
        )
        return {row[3]: row for row in rows}

    def _visible_codes(
        self,
        template: Mapping[str, Any],
        scope: TrustedScope,
        org_filters: Mapping[str, str],
    ) -> set[str] | None:
        """Codes passing org filters, or None when no org filter applies."""
        required = dict(org_filters)
        # Trusted-scope org restrictions always apply, even without a request filter.
        for field, allowed in scope.org_scopes.items():
            if field in required:
                if required[field] not in allowed:
                    raise ProviderError(
                        "permission-denied",
                        f"requested {field}={required[field]} is outside the authorized scope",
                    )
            elif allowed:
                # Narrow to the trusted scope: only one value means implicit filter.
                if len(allowed) == 1:
                    required[field] = allowed[0]
        if not required:
            return None
        codes: set[str] | None = None
        for field, value in required.items():
            # Visibility semantics: an entity is excluded only when it HAS
            # extension rows for this field and none matches. Entities with
            # no extension rows for the field (e.g. client-level objects or
            # scopes not modeled in the projection) stay visible — absence of
            # an imported extension is not proof of unavailability.
            rows = self._execute(
                "SELECT canonical_code FROM md.v_entity_current"
                " WHERE object_type = %s AND ("
                "   canonical_code IN ("
                "     SELECT canonical_code FROM md.v_entity_org_scope_current"
                "     WHERE object_type = %s AND org_field = %s AND org_value = %s)"
                "   OR NOT EXISTS ("
                "     SELECT 1 FROM md.v_entity_org_scope_current o"
                "     WHERE o.object_type = %s AND o.org_field = %s"
                "       AND o.canonical_code = md.v_entity_current.canonical_code)"
                " )",
                (template["objectType"], template["objectType"], field, value,
                 template["objectType"], field),
            )
            matching = {row[0] for row in rows}
            codes = matching if codes is None else codes & matching
        return codes or set()

    def _descriptions(self, codes: tuple[str, ...], template: Mapping[str, Any]) -> dict[str, list[tuple]]:
        if not codes:
            return {}
        rows = self._execute(
            "SELECT canonical_code, language, description, is_official"
            " FROM md.v_entity_description_current"
            " WHERE object_type = %s AND canonical_code = ANY(%s)",
            (template["objectType"], list(codes)),
        )
        result: dict[str, list[tuple]] = {}
        for code, language, description, official in rows:
            result.setdefault(code, []).append((language, description, official))
        return result

    def _org_scopes_of(self, codes: tuple[str, ...], template: Mapping[str, Any]) -> dict[str, tuple[tuple[str, str], ...]]:
        if not codes:
            return {}
        rows = self._execute(
            "SELECT canonical_code, org_field, org_value FROM md.v_entity_org_scope_current"
            " WHERE object_type = %s AND canonical_code = ANY(%s) ORDER BY org_field, org_value",
            (template["objectType"], list(codes)),
        )
        result: dict[str, list[tuple[str, str]]] = {}
        for code, field, value in rows:
            result.setdefault(code, []).append((field, value))
        return {code: tuple(scopes) for code, scopes in result.items()}

    def _snapshot_row(self, template: Mapping[str, Any], scope: TrustedScope) -> tuple:
        rows = self._execute(
            "SELECT snapshot_id, source_extracted_at, loaded_at FROM md.v_snapshot_current"
            " WHERE object_type = %s AND source_system = ANY(%s) AND client = ANY(%s)"
            " ORDER BY loaded_at DESC LIMIT 1",
            (template["objectType"], list(scope.source_systems), list(scope.clients)),
        )
        if not rows:
            raise ProviderError(
                "coverage-incomplete",
                f"no active snapshot covers {template['objectType']} in the authorized scope",
            )
        return rows[0]

    # -- matching steps ------------------------------------------------------

    def _codes_by_exact_label(self, query: str, template: Mapping[str, Any]) -> dict[str, str]:
        rows = self._execute(
            "SELECT canonical_code, description FROM md.v_entity_description_current"
            " WHERE object_type = %s AND lower(description) = lower(%s)",
            (template["objectType"], query),
        )
        return {code: MATCH_EXACT_LABEL for code, _ in rows}

    def _codes_by_alias(self, query: str, template: Mapping[str, Any]) -> dict[str, str]:
        rows = self._execute(
            "SELECT canonical_code, alias FROM md.v_entity_alias_current"
            " WHERE object_type = %s AND active AND lower(alias) = lower(%s)",
            (template["objectType"], query),
        )
        return {code: MATCH_APPROVED_ALIAS for code, _ in rows}

    def _codes_by_substring(self, query: str, template: Mapping[str, Any]) -> dict[str, str]:
        pattern = f"%{_like_escape(query)}%"
        rows = self._execute(
            "SELECT canonical_code, description FROM md.v_entity_description_current"
            " WHERE object_type = %s AND description ILIKE %s ESCAPE '\\'",
            (template["objectType"], pattern),
        )
        return {code: MATCH_SUBSTRING for code, _ in rows}

    def _codes_by_trigram(self, query: str, template: Mapping[str, Any]) -> dict[str, tuple[str, float]]:
        if len(query.strip()) < TRIGRAM_MIN_QUERY_LENGTH:
            # Bounded strategy: trigram cannot work on very short input.
            return {}
        rows = self._execute(
            "SELECT canonical_code, max(similarity(description, %s)) AS score"
            " FROM md.v_entity_description_current"
            " WHERE object_type = %s AND description %% %s"
            " GROUP BY canonical_code ORDER BY score DESC LIMIT %s",
            (query, template["objectType"], query, MAX_LIMIT),
        )
        return {code: (MATCH_TRIGRAM, float(score)) for code, score in rows if score >= TRIGRAM_THRESHOLD}

    # -- public contract -----------------------------------------------------

    def search(self, request: SearchRequest, scope: TrustedScope) -> CandidateSet:
        template = self._template(request.query_template_id)
        if request.limit < 1 or request.limit > MAX_LIMIT:
            raise ProviderError("invalid-request", f"limit must be within 1..{MAX_LIMIT}")

        entity_rows = self._entity_rows(template, scope)
        visible = self._visible_codes(template, scope, request.org_filters)
        snapshot_id, extracted_at, loaded_at = self._snapshot_row(template, scope)

        matches: dict[str, tuple[str, float | None]] = {}
        if request.entity_key:
            for code in entity_rows:
                if code == request.entity_key or code.upper() == request.entity_key.upper():
                    matches[code] = (MATCH_EXACT_CODE, None)
        query = (request.query or "").strip()
        if query and not matches:
            for code in self._codes_by_exact_label(query, template):
                matches.setdefault(code, (MATCH_EXACT_LABEL, None))
            for code in self._codes_by_alias(query, template):
                matches.setdefault(code, (MATCH_APPROVED_ALIAS, None))
            if not matches:
                for code in self._codes_by_substring(query, template):
                    matches.setdefault(code, (MATCH_SUBSTRING, None))
            if not matches:
                for code, (kind, score) in self._codes_by_trigram(query, template).items():
                    matches.setdefault(code, (kind, score))

        # Inactive entities are never search candidates; get_by_key still
        # reports them (with status) so an explicit code can be told apart
        # from a nonexistent one.
        codes = [
            code
            for code in matches
            if code in entity_rows and entity_rows[code][4] == "active"
        ]
        if visible is not None:
            codes = [code for code in codes if code in visible]

        truncated = len(codes) > request.limit
        codes = codes[: request.limit]

        descriptions = self._descriptions(tuple(codes), template)
        org_scopes = self._org_scopes_of(tuple(codes), template)

        candidates: list[EntityCandidate] = []
        for code in codes:
            row = entity_rows[code]
            display = self._display_name(descriptions.get(code, []), request.language)
            kind, score = matches[code]
            distinguishing = {
                key: value
                for key, value in (row[5] or {}).items()
                if value is not None
            }
            candidates.append(
                EntityCandidate(
                    key=EntityKey(row[0], row[1], row[2], row[3]),
                    display_name=display,
                    distinguishing=distinguishing,
                    match_kind=kind,
                    status=row[4],
                    org_scopes=org_scopes.get(code, ()),
                    score=score,
                )
            )
        return CandidateSet(
            candidates=tuple(candidates),
            snapshot_id=snapshot_id,
            source_extracted_at=str(extracted_at) if extracted_at else None,
            loaded_at=str(loaded_at),
            completeness=TRUNCATED if truncated else COMPLETE,
            truncated=truncated,
        )

    def get_by_key(self, entity_key: EntityKey, scope: TrustedScope) -> EntityCandidate | None:
        """Verify a determined code: returns the entity (any status) or None."""
        template = next(
            (t for t in self._templates.values() if t["objectType"] == entity_key.object_type),
            None,
        )
        if template is None:
            raise ProviderError("invalid-request", f"no query template for {entity_key.object_type}")
        rows = self._execute(
            "SELECT source_system, client, object_type, canonical_code, status, attributes"
            " FROM md.v_entity_current"
            " WHERE object_type = %s AND source_system = %s AND client = %s AND canonical_code = %s",
            (entity_key.object_type, entity_key.source_system, entity_key.client, entity_key.canonical_code),
        )
        if not rows:
            return None
        row = rows[0]
        descriptions = self._descriptions((row[3],), template)
        org_scopes = self._org_scopes_of((row[3],), template)
        return EntityCandidate(
            key=EntityKey(row[0], row[1], row[2], row[3]),
            display_name=self._display_name(descriptions.get(row[3], []), None),
            distinguishing={k: v for k, v in (row[5] or {}).items() if v is not None},
            match_kind=MATCH_EXACT_CODE,
            status=row[4],
            org_scopes=org_scopes.get(row[3], ()),
        )

    @staticmethod
    def _display_name(descriptions: list[tuple], language: str | None) -> str:
        if not descriptions:
            return ""
        if language:
            for lang, text, official in descriptions:
                if lang == language and official:
                    return text
            for lang, text, _official in descriptions:
                if lang == language:
                    return text
        for _lang, text, official in descriptions:
            if official:
                return text
        return descriptions[0][1]

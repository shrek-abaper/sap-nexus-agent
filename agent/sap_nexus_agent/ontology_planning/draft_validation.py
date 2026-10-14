"""Strict validation of untrusted SemanticGoalDraft documents.

Three independent layers, all collected (never fail on the first):
1. JSON Schema (strict, recursive additionalProperties:false).
2. Deep technical-key/value scan (RFC names, URLs, paths, shell metachars).
3. Bounds (nodes, facts, nesting, string length) and release-resolved
   references (Fact fields, operators, DAG inputs).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
import json as _json
from pathlib import Path
import re
from typing import Any

import jsonschema

from .bounds import BOUNDS

_SCHEMAS_DIR = Path(__file__).resolve().parents[3] / "schemas"

TECH_KEY_NAMES = re.compile(
    r"rfc|binding|url|credential|token|secret|password|sql|query|path|"
    r"import|exec|eval|script|command",
    re.IGNORECASE,
)
TECH_VALUE_PATTERNS = tuple(
    re.compile(pattern)
    for pattern in (
        r"BAPI_[A-Z_]+",
        r"https?://",
        r"[A-Za-z]:\\",
        r"^\.\.?[/\\]",
        r"[;&|`<>]",
    )
)


@dataclass(frozen=True, order=True)
class DraftIssue:
    path: str
    code: str
    message: str


@dataclass(frozen=True)
class DraftValidationReport:
    valid: bool
    issues: tuple[DraftIssue, ...]


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant not allowed: {value}")


def parse_draft_bytes(data: bytes) -> dict[str, Any]:
    """Parse draft bytes; NaN/Infinity constants are rejected."""
    document = _json.loads(data, parse_constant=_reject_constant)
    if not isinstance(document, Mapping):
        raise ValueError("draft root must be an object")
    return dict(document)


def _load_schema() -> dict[str, Any]:
    return _json.loads(
        (_SCHEMAS_DIR / "semantic-goal-draft.schema.json").read_text(
            encoding="utf-8"
        )
    )


def _scan(
    node: Any,
    path: str,
    depth: int,
    issues: list[DraftIssue],
) -> None:
    if depth > BOUNDS.max_nesting_depth:
        issues.append(
            DraftIssue(path, "DRAFT_BOUNDS", "nesting exceeds max depth")
        )
        return
    if isinstance(node, Mapping):
        for key, value in node.items():
            key_path = f"{path}.{key}" if path else key
            if TECH_KEY_NAMES.search(str(key)):
                issues.append(
                    DraftIssue(
                        key_path,
                        "DRAFT_TECHNICAL_KEY",
                        "technical key not allowed in drafts",
                    )
                )
            _scan(value, key_path, depth + 1, issues)
    elif isinstance(node, (list, tuple)):
        for index, item in enumerate(node):
            _scan(item, f"{path}[{index}]", depth + 1, issues)
    elif isinstance(node, str):
        if len(node) > BOUNDS.max_string_chars:
            issues.append(
                DraftIssue(path, "DRAFT_BOUNDS", "string exceeds max length")
            )
        for pattern in TECH_VALUE_PATTERNS:
            if pattern.search(node):
                issues.append(
                    DraftIssue(
                        path,
                        "DRAFT_TECHNICAL_KEY",
                        f"technical-looking value matched {pattern.pattern}",
                    )
                )
                break


def _topological_order(
    nodes: list[Mapping[str, Any]],
) -> tuple[bool, list[str]]:
    ids = {str(n.get("nodeId")) for n in nodes}
    order: list[str] = []
    visited: dict[str, int] = {}

    def visit(node_id: str) -> bool:
        state = visited.get(node_id, 0)
        if state == 1:
            return False  # cycle
        if state == 2:
            return True
        visited[node_id] = 1
        node = next(n for n in nodes if n.get("nodeId") == node_id)
        for dep in node.get("dependsOn", ()):
            if dep not in ids or not visit(str(dep)):
                return False
        visited[node_id] = 2
        order.append(node_id)
        return True

    return all(visit(str(n["nodeId"])) for n in nodes), order


def validate_draft(document: Mapping[str, Any], release: Any) -> DraftValidationReport:
    issues: list[DraftIssue] = []

    try:
        jsonschema.validate(dict(document), _load_schema())
    except jsonschema.ValidationError as exc:
        issues.append(DraftIssue("$", "DRAFT_SCHEMA_INVALID", exc.message))

    _scan(document, "$", 0, issues)

    facts = document.get("requestedFacts", [])
    if isinstance(facts, list):
        if len(facts) > BOUNDS.max_requested_facts:
            issues.append(
                DraftIssue("$.requestedFacts", "DRAFT_BOUNDS", "too many facts")
            )
        for index, fact in enumerate(facts):
            if not isinstance(fact, Mapping):
                continue
            fact_type = fact.get("factTypeId")
            base = f"$.requestedFacts[{index}]"
            allowed_fields = release.allowlist_fields.get(fact_type)
            if allowed_fields is None:
                issues.append(
                    DraftIssue(
                        f"{base}.factTypeId",
                        "DRAFT_UNKNOWN_FACT_TYPE",
                        f"{fact_type} not in release allowlist",
                    )
                )
                continue
            for field in fact.get("fields", ()):
                if field not in allowed_fields:
                    issues.append(
                        DraftIssue(
                            f"{base}.fields.{field}",
                            "DRAFT_UNKNOWN_FIELD",
                            f"{fact_type}.{field} not analysis-legal",
                        )
                    )

    nodes = document.get("analysisNodes", [])
    node_list = [n for n in nodes if isinstance(n, Mapping)] if isinstance(nodes, list) else []
    if len(node_list) > BOUNDS.max_analysis_nodes:
        issues.append(
            DraftIssue("$.analysisNodes", "DRAFT_BOUNDS", "too many analysis nodes")
        )
    node_ids = {str(n.get("nodeId")) for n in node_list}
    for node in node_list:
        node_id = str(node.get("nodeId"))
        if node.get("operatorId") not in release.operator_ids:
            issues.append(
                DraftIssue(
                    f"$.analysisNodes[{node_id}]",
                    "DRAFT_UNKNOWN_OPERATOR",
                    f"{node.get('operatorId')} is not a registered operator",
                )
            )
        for input_ref in node.get("inputs", ()):
            if not isinstance(input_ref, Mapping):
                continue
            if input_ref.get("kind") == "nodeRef":
                target = input_ref.get("nodeId")
                if target not in node_ids or target == node_id:
                    issues.append(
                        DraftIssue(
                            f"$.analysisNodes[{node_id}]",
                            "DRAFT_UNRESOLVED_INPUT",
                            f"nodeRef {target} does not resolve upstream",
                        )
                    )
            elif input_ref.get("kind") == "factField":
                fact_type = input_ref.get("factTypeId")
                field = input_ref.get("field")
                if (
                    release.allowlist_fields.get(fact_type) is None
                    or field not in release.allowlist_fields[fact_type]
                ):
                    issues.append(
                        DraftIssue(
                            f"$.analysisNodes[{node_id}]",
                            "DRAFT_UNRESOLVED_INPUT",
                            f"factField {fact_type}.{field} not allowed",
                        )
                    )

    if isinstance(nodes, list) and all(isinstance(n, Mapping) for n in nodes):
        acyclic, _order = _topological_order(node_list)
        if not acyclic:
            issues.append(
                DraftIssue("$.analysisNodes", "DRAFT_DAG_CYCLE", "cycle detected")
            )

    deduped = tuple(sorted(set(issues)))
    return DraftValidationReport(valid=not deduped, issues=deduped)

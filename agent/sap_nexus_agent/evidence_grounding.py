"""Evidence-grounding validation for ontology Definitions and object links.

A grounded entry must reference evidence resolving to a real eval case; a
proposed entry must declare an evidence gap. Fail-closed and offline.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

GROUNDED = "grounded"
PROPOSED = "proposed"
VALID_STATUSES = (GROUNDED, PROPOSED)


def load_catalog(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(str(path))
    payload = yaml.safe_load(path.read_text("utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError("catalog root must be a mapping")
    return payload


def _suite_path(repo_root: Path, suite_rel: str) -> Path | None:
    """Resolve a suite path confined to the repo root; None when it escapes."""
    path = (Path(repo_root) / str(suite_rel)).resolve()
    root = Path(repo_root).resolve()
    if root not in path.parents and path != root:
        return None
    return path


def resolve_case_ids(repo_root: Path, suite_rel: str) -> set[str] | None:
    """Case ids in an eval suite.

    None when the suite is missing or its path escapes the repo root; an
    empty set when the suite exists but yields no ids.
    """
    path = _suite_path(repo_root, str(suite_rel))
    if path is None or not path.exists() or not path.is_file():
        return None
    try:
        if str(suite_rel).endswith(".json"):
            payload = json.loads(path.read_text("utf-8"))
        else:
            # The repo's YAML suites hold JSON content; safe_load parses both.
            payload = yaml.safe_load(path.read_text("utf-8"))
    except (json.JSONDecodeError, yaml.YAMLError):
        # A malformed suite cannot provide evidence; treat as unresolvable.
        return None
    if not isinstance(payload, dict):
        return set()
    ids: set[str] = set()
    for case in payload.get("cases") or []:
        if not isinstance(case, dict):
            continue
        case_id = case.get("id") or case.get("caseId")
        if case_id:
            ids.add(str(case_id))
    return ids


def validate_entry(
    entry: Any, id_key: str, repo_root: Path
) -> list[str]:
    """Violation strings for one catalog entry; empty when valid."""
    if not isinstance(entry, dict):
        return [f"<{id_key}>: entry must be a mapping, got {type(entry).__name__}"]
    entry_id = str(entry.get(id_key) or "<unknown>")
    status = entry.get("status")
    if status not in VALID_STATUSES:
        return [f"{entry_id}: invalid status {status!r}"]

    if status == PROPOSED:
        gap = entry.get("evidenceGap")
        if not gap or not str(gap).strip():
            return [f"{entry_id}: proposed entry requires a non-empty evidenceGap"]
        return []

    evidence = entry.get("evidence")
    if not isinstance(evidence, dict) or not evidence:
        return [f"{entry_id}: grounded entry requires an evidence mapping"]
    suite = evidence.get("suite")
    case_id = evidence.get("caseId")
    case_ids = resolve_case_ids(Path(repo_root), str(suite)) if suite else None
    if case_ids is None:
        return [f"{entry_id}: evidence suite does not resolve: {suite}"]
    if str(case_id) not in case_ids:
        return [
            f"{entry_id}: evidence caseId does not resolve: {case_id} in {suite}"
        ]
    return []


def validate_catalogs(
    repo_root: Path,
    definitions_path: Path,
    object_links_path: Path,
) -> list[str]:
    violations: list[str] = []
    catalog_specs = (
        ("definitions", definitions_path, "definitions", "definitionId"),
        ("object-links", object_links_path, "links", "linkId"),
    )
    for catalog_name, path, list_key, id_key in catalog_specs:
        try:
            catalog = load_catalog(Path(path))
        except FileNotFoundError:
            violations.append(f"{catalog_name}: catalog file missing: {path}")
            continue
        except (ValueError, yaml.YAMLError) as exc:
            violations.append(f"{catalog_name}: malformed catalog: {exc}")
            continue
        entries = catalog.get(list_key, [])
        if not isinstance(entries, list):
            violations.append(f"{catalog_name}: {list_key} must be a list")
            continue
        for entry in entries:
            for violation in validate_entry(entry, id_key, Path(repo_root)):
                violations.append(f"{catalog_name}: {violation}")
    return violations

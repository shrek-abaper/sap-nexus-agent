"""Tests for evidence-grounded ontology catalog validation."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

from sap_nexus_agent.evidence_grounding import (
    resolve_case_ids,
    validate_catalogs,
    validate_entry,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _write_suite(base: Path, rel: str, case_ids: list[str]) -> Path:
    path = base / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    key = "caseId" if rel.endswith(".json") else "id"
    path.write_text(json.dumps({"cases": [{key: cid} for cid in case_ids]}), "utf-8")
    return path


def _entry(
    status="grounded",
    *,
    suite="evals/suite.yaml",
    case_id="case-1",
    gap=None,
):
    entry = {"definitionId": "def-1", "status": status}
    if suite is not None:
        entry["evidence"] = {"suite": suite, "caseId": case_id}
    if gap is not None:
        entry["evidenceGap"] = gap
    return entry


# --- evidence resolution -------------------------------------------------------

def test_resolve_case_ids_accepts_both_id_keys(tmp_path):
    _write_suite(tmp_path, "evals/a.yaml", ["x1"])
    _write_suite(tmp_path, "evals/b.json", ["x2"])

    assert resolve_case_ids(tmp_path, "evals/a.yaml") == {"x1"}
    assert resolve_case_ids(tmp_path, "evals/b.json") == {"x2"}


def test_resolve_case_ids_missing_suite_returns_none(tmp_path):
    assert resolve_case_ids(tmp_path, "evals/nope.yaml") is None


# --- entry validation -----------------------------------------------------------

def test_grounded_entry_with_resolvable_evidence(tmp_path):
    _write_suite(tmp_path, "evals/suite.yaml", ["case-1"])

    assert validate_entry(_entry(), "definitionId", tmp_path) == []


def test_grounded_missing_evidence(tmp_path):
    violations = validate_entry(
        {"definitionId": "def-1", "status": "grounded"}, "definitionId", tmp_path
    )

    assert len(violations) == 1
    assert "evidence" in violations[0]


def test_grounded_unknown_suite(tmp_path):
    violations = validate_entry(
        _entry(suite="evals/missing.yaml"), "definitionId", tmp_path
    )

    assert len(violations) == 1
    assert "resolve" in violations[0]


def test_grounded_unknown_case_id(tmp_path):
    _write_suite(tmp_path, "evals/suite.yaml", ["other-case"])

    violations = validate_entry(_entry(), "definitionId", tmp_path)

    assert len(violations) == 1
    assert "case-1" in violations[0]


def test_proposed_with_gap_is_valid(tmp_path):
    entry = _entry("proposed", suite=None, gap="not implemented yet")

    assert validate_entry(entry, "definitionId", tmp_path) == []


def test_proposed_without_gap_fails(tmp_path):
    entry = _entry("proposed", suite=None)

    violations = validate_entry(entry, "definitionId", tmp_path)

    assert len(violations) == 1
    assert "evidenceGap" in violations[0]


def test_invalid_status_fails(tmp_path):
    violations = validate_entry(
        _entry("published"), "definitionId", tmp_path
    )

    assert violations
    assert "status" in violations[0]


# --- catalog aggregation ---------------------------------------------------------

def test_validate_catalogs_collects_prefixed_violations(tmp_path):
    _write_suite(tmp_path, "evals/suite.yaml", ["case-1"])
    definitions = tmp_path / "ontology/definitions.yaml"
    definitions.parent.mkdir(parents=True)
    definitions.write_text(
        'version: 1\ndefinitions:\n'
        '  - definitionId: def-bad\n    status: grounded\n',
        "utf-8",
    )
    links = tmp_path / "ontology/object-links.yaml"
    links.write_text(
        'version: 1\nlinks:\n'
        '  - linkId: link-bad\n    status: proposed\n',
        "utf-8",
    )

    violations = validate_catalogs(tmp_path, definitions, links)

    assert len(violations) == 2
    assert any("definitions" in v and "def-bad" in v for v in violations)
    assert any("object-links" in v and "link-bad" in v for v in violations)


def test_validate_catalogs_clean_set(tmp_path):
    _write_suite(tmp_path, "evals/suite.yaml", ["case-1"])
    catalog = tmp_path / "ontology/catalog.yaml"
    catalog.parent.mkdir(parents=True)
    catalog.write_text(
        'version: 1\n'
        'definitions:\n'
        '  - definitionId: def-1\n    status: grounded\n'
        '    evidence: {suite: evals/suite.yaml, caseId: case-1}\n',
        "utf-8",
    )

    assert validate_catalogs(tmp_path, catalog, catalog) == []


# --- malformed inputs (post-review hardening) ------------------------------------

def test_non_dict_entry_is_violation(tmp_path):
    violations = validate_entry("not-a-mapping", "definitionId", tmp_path)

    assert violations
    assert "mapping" in violations[0]


def test_non_dict_evidence_is_violation(tmp_path):
    _write_suite(tmp_path, "evals/suite.yaml", ["case-1"])
    entry = {"definitionId": "def-1", "status": "grounded", "evidence": "oops"}

    violations = validate_entry(entry, "definitionId", tmp_path)

    assert violations
    assert "evidence mapping" in violations[0]


def test_malformed_catalog_collected_not_aborted(tmp_path):
    catalog = tmp_path / "ontology/catalog.yaml"
    catalog.parent.mkdir(parents=True)
    catalog.write_text("definitions: [\n  - bad: : :\n", "utf-8")
    good = tmp_path / "ontology/good.yaml"
    good.write_text("definitions: []", "utf-8")

    violations = validate_catalogs(tmp_path, catalog, good)

    # Malformed catalog is reported; the second catalog still gets checked.
    assert any("malformed" in v for v in violations)


def test_entries_not_a_list_is_violation(tmp_path):
    catalog = tmp_path / "ontology/catalog.yaml"
    catalog.parent.mkdir(parents=True)
    catalog.write_text("definitions: not-a-list\n", "utf-8")

    violations = validate_catalogs(tmp_path, catalog, catalog)

    assert any("must be a list" in v for v in violations)


def test_absolute_suite_path_cannot_escape_repo(tmp_path):
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps({"cases": [{"caseId": "ext"}]}), "utf-8")
    repo = tmp_path / "repo"
    repo.mkdir()
    entry = {
        "definitionId": "def-1", "status": "grounded",
        "evidence": {"suite": str(outside), "caseId": "ext"},
    }

    violations = validate_entry(entry, "definitionId", repo)

    assert violations
    assert "does not resolve" in violations[0]


def test_numeric_case_id_coerced(tmp_path):
    _write_suite(tmp_path, "evals/suite.json", ["5"])
    entry = {
        "definitionId": "def-1", "status": "grounded",
        "evidence": {"suite": "evals/suite.json", "caseId": 5},
    }

    assert validate_entry(entry, "definitionId", tmp_path) == []


def test_malformed_suite_treated_as_unresolvable(tmp_path):
    suite = tmp_path / "evals/suite.json"
    suite.parent.mkdir(parents=True)
    suite.write_text("{ not json", "utf-8")
    entry = {
        "definitionId": "def-1", "status": "grounded",
        "evidence": {"suite": "evals/suite.json", "caseId": "case-1"},
    }

    violations = validate_entry(entry, "definitionId", tmp_path)

    assert violations
    assert "does not resolve" in violations[0]


# --- shipped catalogs via CLI -----------------------------------------------------

def test_cli_validates_shipped_catalogs():
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts/validate-evidence-grounding.py")],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "OK" in proc.stdout

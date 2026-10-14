"""Schema tests for SemanticRelease authored asset documents."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]

OPERATOR_IDS = {"select_fields", "filter_eq", "group_sum", "compare"}


def _schema(name: str) -> dict:
    return json.loads((REPO_ROOT / "schemas" / name).read_text(encoding="utf-8"))


def _yaml(rel: str) -> dict:
    return yaml.safe_load((REPO_ROOT / rel).read_text(encoding="utf-8"))


def test_analysis_versions_asset_validates():
    doc = _yaml("ontology/analysis-versions.yaml")
    jsonschema.validate(doc, _schema("analysis-versions.schema.json"))
    assert doc["compilerVersion"] == "0.1.0"
    assert set(doc["operatorImplementations"]) == OPERATOR_IDS


@pytest.mark.parametrize(
    "bad",
    [
        # missing operatorImplementations
        {"version": 1, "compilerVersion": "0.1.0"},
        # unknown top-level property
        {
            "version": 1,
            "compilerVersion": "0.1.0",
            "operatorImplementations": {"select_fields": "0.1.0"},
            "extra": 1,
        },
        # fifth operator key
        {
            "version": 1,
            "compilerVersion": "0.1.0",
            "operatorImplementations": {
                "select_fields": "0.1.0",
                "filter_eq": "0.1.0",
                "group_sum": "0.1.0",
                "compare": "0.1.0",
                "fifth_op": "0.1.0",
            },
        },
    ],
)
def test_analysis_versions_rejects_bad_shapes(bad):
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, _schema("analysis-versions.schema.json"))

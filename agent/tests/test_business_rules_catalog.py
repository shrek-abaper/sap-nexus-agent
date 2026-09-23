"""Tests for the business rule catalog (ontology/business-rules.yaml)."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def catalog() -> dict:
    return yaml.safe_load(
        (REPO_ROOT / "ontology" / "business-rules.yaml").read_text(encoding="utf-8")
    )


@pytest.fixture(scope="module")
def schema() -> dict:
    return json.loads(
        (REPO_ROOT / "schemas" / "business-rule-catalog.schema.json").read_text(
            encoding="utf-8"
        )
    )


def test_catalog_validates_against_schema(catalog, schema):
    jsonschema.validate(catalog, schema)


def test_rule_ids_are_unique(catalog):
    ids = [rule["ruleId"] for rule in catalog["rules"]]

    assert len(ids) == len(set(ids))


def test_scope_capabilities_are_registered(catalog):
    registry = yaml.safe_load(
        (REPO_ROOT / "registry" / "capabilities.yaml").read_text(encoding="utf-8")
    )
    registered = {cap["capabilityId"] for cap in registry["capabilities"]}

    for rule in catalog["rules"]:
        assert rule["scope"]["capabilityId"] in registered, rule["ruleId"]


def test_implemented_by_points_to_existing_code(catalog):
    for rule in catalog["rules"]:
        path = rule["source"]["implementedBy"].split(":", 1)[0]

        assert (REPO_ROOT / path).is_file(), (
            f"{rule['ruleId']}: implementation file not found: {path}"
        )


def test_structural_invariants_are_not_cataloged(catalog):
    # The catalog is for business rules; structural enforcement vocabulary
    # must not appear as entries (they belong solely to validators).
    forbidden = ("approval", "closed-set", "validate-before")

    for rule in catalog["rules"]:
        assert not any(word in rule["ruleId"] for word in forbidden)


def test_catalog_rejects_rule_with_missing_provenance(catalog, schema):
    broken = json.loads(json.dumps(catalog))
    del broken["rules"][0]["source"]

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(broken, schema)


def test_catalog_rejects_unknown_constraint_strength(catalog, schema):
    broken = json.loads(json.dumps(catalog))
    broken["rules"][0]["constraintStrength"] = "absolute"

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(broken, schema)

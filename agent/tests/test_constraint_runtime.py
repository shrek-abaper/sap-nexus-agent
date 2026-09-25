"""Tests for runtime constraint resolution (SHACL validation + preconditions)."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from sap_nexus_agent.constraint_runtime import get_runtime

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def runtime():
    return get_runtime(str(REPO_ROOT))


# ------------------------------ validation ------------------------------

def test_validate_plant_conforms(runtime):
    result = runtime.validate_value(
        "MM.Inventory.GetAvailability", "plant", "5260"
    )

    assert result["conforms"] is True


def test_validate_short_plant_rejected(runtime):
    result = runtime.validate_value(
        "MM.Inventory.GetAvailability", "plant", "12"
    )

    assert result["conforms"] is False
    assert result["violations"]


def test_validate_numeric_value_as_decimal(runtime):
    result = runtime.validate_value(
        "MM.Inventory.GetAvailability", "quantity", Decimal("100")
    )

    assert result["conforms"] is True


def test_validate_many_all_or_nothing(runtime):
    ok = runtime.validate_many(
        {"material": "P0226750AD", "plant": "5260"},
        "MM.Inventory.GetAvailability",
    )
    bad = runtime.validate_many(
        {"material": "P0226750AD", "plant": "12"},
        "MM.Inventory.GetAvailability",
    )

    assert ok["conforms"] is True
    assert bad["conforms"] is False
    assert bad["perInput"]["plant"] is False


# ----------------------------- preconditions -----------------------------

def test_preconditions_satisfied(runtime):
    result = runtime.evaluate_preconditions(
        "MM.Inventory.GetAvailability",
        {"material": "P0226750AD", "plant": "5260"},
    )

    assert result == {"satisfied": True, "missing": []}


def test_preconditions_missing_required(runtime):
    result = runtime.evaluate_preconditions(
        "MM.Inventory.GetAvailability", {}
    )

    assert result["satisfied"] is False
    assert set(result["missing"]) == {"material", "plant"}


def test_preconditions_partial_missing(runtime):
    result = runtime.evaluate_preconditions(
        "MM.Inventory.GetAvailability", {"material": "P0226750AD"}
    )

    assert result["missing"] == ["plant"]


def test_fact_satisfiable_inputs_not_missing(runtime):
    # unit / purchasing_group are satisfiableByFactType; with the other
    # required inputs provided they must not be reported missing.
    result = runtime.evaluate_preconditions(
        "MM.PR.CreateDraft",
        {
            "material": "P0226750AD", "plant": "5260", "quantity": Decimal("100"),
            "delivery_date": "2026-10-01",
        },
    )

    assert "unit" not in result["missing"]
    assert "purchasing_group" not in result["missing"]


def test_require_any_group_precondition(runtime):
    result = runtime.evaluate_preconditions(
        "MM.PurchaseOrder.GetList", {}
    )

    assert result["satisfied"] is False
    assert "filter" in result["missing"]

    satisfied = runtime.evaluate_preconditions(
        "MM.PurchaseOrder.GetList", {"material": "P0226750AD"}
    )
    assert satisfied["satisfied"] is True


def test_conditional_required_when_k(runtime):
    base = {
        "material": "P0226750AD", "plant": "5260", "quantity": Decimal("100"),
        "unit": "EA", "delivery_date": "2026-10-01", "purchasing_group": "601",
        "acct_assgn_cat": "K",
    }
    result = runtime.evaluate_preconditions("MM.PR.CreateDraft", base)

    assert result["satisfied"] is False
    assert result["missing"] == ["cost_center"]

    resolved = runtime.evaluate_preconditions(
        "MM.PR.CreateDraft", {**base, "cost_center": "10000001"}
    )
    assert resolved["satisfied"] is True

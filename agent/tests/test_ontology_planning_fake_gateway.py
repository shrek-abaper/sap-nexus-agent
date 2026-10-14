"""Offline FakeGatewayClient tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from sap_nexus_agent.ontology_planning.fake_gateway import (
    FixtureNotFound,
    FakeGatewayClient,
    WriteRejected,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "evals/ontology-read-analysis"


def test_execute_returns_fixture_data_and_logs():
    gateway = FakeGatewayClient(FIXTURES, "q1-stock-and-unit")
    result = gateway.execute(
        "MM.Inventory.GetAvailability",
        {"material": "DEMOA2", "plant": "1000"},
    )
    assert result.success is True
    assert result.data["availableQuantity"] == "12.000"
    assert gateway.calls == ["MM.Inventory.GetAvailability"]
    validate = gateway.validate("MM.Inventory.GetAvailability", {})
    assert validate.success is True


def test_write_capability_rejected():
    gateway = FakeGatewayClient(FIXTURES, "q1-stock-and-unit")
    with pytest.raises(WriteRejected):
        gateway.execute("MM.PR.CreateDraft", {})
    assert gateway.calls == []


def test_missing_fixture_raises():
    gateway = FakeGatewayClient(FIXTURES, "no-such-case")
    with pytest.raises(FixtureNotFound):
        gateway.execute("MM.Inventory.GetAvailability", {})

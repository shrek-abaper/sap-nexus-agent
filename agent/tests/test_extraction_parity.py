from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from legacy_intent_reference import parse as legacy_parse
from legacy_intent_reference import sticky as legacy_sticky
from sap_nexus_agent.capability_selector import select_capability
from sap_nexus_agent.conversation_context import ConversationContext, LastContext
from sap_nexus_agent.extraction import engine
from sap_nexus_agent.intent import _detect_odata_override, _detect_rfc_name, parse_intent
from sap_nexus_agent.llm_intent import resolve_with_context
from sap_nexus_agent.registry_loader import load_intent_catalog


FIXTURES = Path(__file__).parent / "fixtures" / "parity"
TABLES = ("pr", "inventory", "po")


def _rows(table: str) -> list[tuple[str, dict[str, Any]]]:
    doc = yaml.safe_load((FIXTURES / f"{table}.yaml").read_text(encoding="utf-8"))
    return [(row["name"], row) for row in doc["rows"]]


def _all_rows() -> list[tuple[str, str, dict[str, Any]]]:
    return [(table, name, row) for table in TABLES for name, row in _rows(table)]


def _context(row: dict[str, Any]) -> ConversationContext:
    last_context = row["last_context"]
    parameters = dict(last_context.get("parameters") or {})
    return ConversationContext(
        last_context=LastContext(
            capability_id=str(last_context["capability_id"]),
            parameters={str(key): str(value) for key, value in parameters.items()},
            missing_parameters=[str(value) for value in last_context.get("missing_parameters", [])],
            decision_type=str(last_context.get("decision_type", "CLARIFY")),
        ),
        history=(),
    )


def _summary(result) -> dict[str, Any]:
    decision = select_capability(result)
    capability_id = decision.capability_id if decision.decision_type in {"SELECT", "CLARIFY"} else None
    return {
        "decision_type": decision.decision_type,
        "capability_id": capability_id,
        "parameters": result.parameters,
        "missing": result.missing_parameters,
        "clarification": result.clarification,
        "is_ambiguous": result.is_ambiguous,
    }


def _assert_row(row: dict[str, Any], result, produced_by: str) -> None:
    expect = row["expect"]
    summary = _summary(result)
    decision = summary.pop("decision_type")
    assert decision == expect["decision_type"], (produced_by, row["name"], decision)
    assert summary["capability_id"] == expect["capability_id"], (produced_by, row["name"])
    assert summary["parameters"] == expect["parameters"], (produced_by, row["name"])
    assert summary["missing"] == expect["missing"], (produced_by, row["name"])
    assert summary["is_ambiguous"] == expect["is_ambiguous"], (produced_by, row["name"])
    if expect.get("clarification_strict", True):
        assert summary["clarification"] == expect["clarification"], (produced_by, row["name"])
    else:
        assert bool(summary["clarification"]) == (expect["clarification"] is not None)


@pytest.mark.parametrize(("table", "name", "row"), _all_rows())
def test_legacy_matches_frozen_table(table: str, name: str, row: dict[str, Any]) -> None:
    result = legacy_sticky(row["utterance"], _context(row)) if row["mode"] == "sticky" else legacy_parse(row["utterance"])
    _assert_row(row, result, "legacy")


@pytest.mark.parametrize(("table", "name", "row"), _all_rows())
def test_engine_matches_frozen_table(table: str, name: str, row: dict[str, Any]) -> None:
    catalog = load_intent_catalog()
    if row["mode"] == "sticky":
        result = engine.sticky_parse(row["utterance"], _context(row), catalog)
    else:
        result = engine.parse_declared(
            row["utterance"],
            catalog,
            contains_rfc_name=_detect_rfc_name(row["utterance"]),
            contains_odata_override=_detect_odata_override(row["utterance"]),
        )
    _assert_row(row, result, "engine")


@pytest.mark.parametrize(("table", "name", "row"), _all_rows())
def test_production_parse_matches_frozen_table(table: str, name: str, row: dict[str, Any]) -> None:
    if row["mode"] == "sticky":
        result = resolve_with_context(row["utterance"], _context(row), load_intent_catalog())
    else:
        result = parse_intent(row["utterance"])
    _assert_row(row, result, "production")

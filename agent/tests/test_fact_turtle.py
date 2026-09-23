"""Tests for ReasoningFact -> Turtle serialization."""

from __future__ import annotations

import pytest

from sap_nexus_agent.fact_turtle import fact_to_turtle, facts_to_turtle


def _fact(**overrides):
    base = {
        "factId": "fact-abc",
        "agentTraceId": "agent-1",
        "traceId": "agent-1",
        "gatewayTraceId": "gw-1",
        "domain": "MM",
        "businessObject": "InventoryStock",
        "predicate": "availableQuantity",
        "value": 42.5,
        "unit": "EA",
        "deterministic": True,
        "confidence": 1.0,
        "source": {"capabilityId": "MM.Inventory.GetAvailability"},
        "evidence": [{"field": "availableQuantity", "value": 42.5}],
        "material": "DEMOA2",
        "plant": "1000",
    }
    base.update(overrides)
    return base


def test_fact_renders_individual_with_key_fields():
    turtle = fact_to_turtle(_fact())

    assert "fact:fact-abc a sapnexus:ReasoningFact" in turtle
    assert 'sapnexus:factId "fact-abc"' in turtle
    assert 'sapnexus:businessObject "InventoryStock"' in turtle
    assert "sapnexus:hasValue 42.5" in turtle
    assert 'sapnexus:unit "EA"' in turtle
    assert "sapnexus:deterministic true" in turtle
    assert turtle.rstrip().endswith(" .")


def test_absent_and_none_fields_are_skipped():
    fact = _fact(unit=None, material="", plant=None)

    turtle = fact_to_turtle(fact)

    assert "sapnexus:unit" not in turtle
    assert "sapnexus:material" not in turtle
    assert "sapnexus:plant" not in turtle


def test_special_characters_are_escaped():
    fact = _fact(material='A"B\\C', evidence=[{"note": 'line1\nline2\t"x"'}])

    turtle = fact_to_turtle(fact)

    assert r'A\"B\\C' in turtle
    assert r'line1\nline2\t\"x\"' in turtle


def test_unicode_is_preserved():
    turtle = fact_to_turtle(_fact(material="物料Ａ"))

    assert "物料Ａ" in turtle


def test_source_and_evidence_render_as_blank_nodes():
    turtle = fact_to_turtle(_fact())

    assert "sapnexus:source [ sapnexus:capabilityId \"MM.Inventory.GetAvailability\" ]" in turtle
    assert "sapnexus:evidence [ sapnexus:field \"availableQuantity\" ; sapnexus:value 42.5 ]" in turtle


def test_missing_fact_id_rejected():
    with pytest.raises(ValueError):
        fact_to_turtle(_fact(factId=" "))


def test_multiple_facts_share_prefix_block():
    turtle = facts_to_turtle([_fact(), _fact(factId="fact-def")])

    assert turtle.count("@prefix sapnexus:") == 1
    assert "fact:fact-abc a sapnexus:ReasoningFact" in turtle
    assert "fact:fact-def a sapnexus:ReasoningFact" in turtle


def test_non_alphanumeric_fact_id_is_sanitized():
    turtle = fact_to_turtle(_fact(factId="fact x/y"))

    assert "fact:fact_x_y a sapnexus:ReasoningFact" in turtle


def test_output_is_turtle_with_balanced_blank_nodes():
    turtle = facts_to_turtle([_fact()])

    assert turtle.startswith("@prefix")
    assert turtle.count("[") == turtle.count("]")

"""Tests for LLM output discard detection (Runbook 14)."""

from __future__ import annotations

from sap_nexus_agent.discard import detect_discard_reasons, prohibited_field_reason


def test_unknown_capability_discarded_with_reason():
    """LLM payload with capability_hint not in visible_ids is discarded."""
    payload = {
        "goals": [
            {
                "goalText": "查库存",
                "capabilityHint": "Foo.Bar",
                "parameters": {},
                "missing": [],
            }
        ]
    }
    visible_ids = frozenset(("MM.Inventory.GetAvailability",))
    reasons = detect_discard_reasons(payload, visible_ids)
    assert "unknown_capability:Foo.Bar" in reasons


def test_known_capability_not_discarded():
    """LLM payload with capability_hint in visible_ids is NOT discarded."""
    payload = {
        "goals": [
            {
                "goalText": "查库存",
                "capabilityHint": "MM.Inventory.GetAvailability",
                "parameters": {},
                "missing": [],
            }
        ]
    }
    visible_ids = frozenset(("MM.Inventory.GetAvailability",))
    reasons = detect_discard_reasons(payload, visible_ids)
    assert not any(r.startswith("unknown_capability:") for r in reasons)


def test_technical_field_discarded_with_reason():
    """LLM payload with technical field (baseUrl/rfcName/credential) is discarded."""
    payload = {
        "goals": [
            {
                "goalText": "查库存",
                "capabilityHint": "MM.Inventory.GetAvailability",
                "parameters": {"baseUrl": "http://sap.example.com", "material": "DEMOA2"},
                "missing": [],
            }
        ]
    }
    visible_ids = frozenset(("MM.Inventory.GetAvailability",))
    reasons = detect_discard_reasons(payload, visible_ids)
    assert "technical_field:baseUrl" in reasons


def test_rfc_name_field_discarded():
    """rfcName is a technical field and must be discarded."""
    payload = {
        "goals": [
            {
                "goalText": "查库存",
                "capabilityHint": "MM.Inventory.GetAvailability",
                "parameters": {"rfcName": "BAPI_MATERIAL_STOCK_REQ_LIST"},
                "missing": [],
            }
        ]
    }
    visible_ids = frozenset(("MM.Inventory.GetAvailability",))
    reasons = detect_discard_reasons(payload, visible_ids)
    assert "technical_field:rfcName" in reasons


def test_credential_field_discarded():
    """credential is a technical field and must be discarded."""
    payload = {
        "goals": [
            {
                "goalText": "查库存",
                "capabilityHint": "MM.Inventory.GetAvailability",
                "parameters": {"credential": "secret"},
                "missing": [],
            }
        ]
    }
    visible_ids = frozenset(("MM.Inventory.GetAvailability",))
    reasons = detect_discard_reasons(payload, visible_ids)
    assert "technical_field:credential" in reasons


def test_invalid_param_discarded_with_reason():
    """LLM payload with invalid param (__proto__) is discarded."""
    payload = {
        "goals": [
            {
                "goalText": "查库存",
                "capabilityHint": "MM.Inventory.GetAvailability",
                "parameters": {"__proto__": "evil"},
                "missing": [],
            }
        ]
    }
    visible_ids = frozenset(("MM.Inventory.GetAvailability",))
    reasons = detect_discard_reasons(payload, visible_ids)
    assert "invalid_param:__proto__" in reasons


def test_valid_payload_has_empty_discard_reasons():
    """Fully valid LLM payload produces empty discard_reasons."""
    payload = {
        "goals": [
            {
                "goalText": "查库存",
                "capabilityHint": "MM.Inventory.GetAvailability",
                "parameters": {"material": "DEMOA2", "plant": "1000"},
                "missing": [],
            }
        ]
    }
    visible_ids = frozenset(("MM.Inventory.GetAvailability",))
    reasons = detect_discard_reasons(payload, visible_ids)
    assert reasons == []


def test_multiple_discard_reasons_collected():
    """Multiple issues in one payload produce multiple reasons."""
    payload = {
        "goals": [
            {
                "goalText": "查库存",
                "capabilityHint": "Foo.Bar",
                "parameters": {"baseUrl": "http://x", "__proto__": "evil"},
                "missing": [],
            }
        ]
    }
    visible_ids = frozenset(("MM.Inventory.GetAvailability",))
    reasons = detect_discard_reasons(payload, visible_ids)
    assert "unknown_capability:Foo.Bar" in reasons
    assert "technical_field:baseUrl" in reasons
    assert "invalid_param:__proto__" in reasons


def test_top_level_capability_id_discarded_when_unknown():
    """Top-level capabilityId (legacy LLM shape) also checked."""
    payload = {
        "capabilityId": "Foo.Bar",
        "parameters": {},
    }
    visible_ids = frozenset(("MM.Inventory.GetAvailability",))
    reasons = detect_discard_reasons(payload, visible_ids)
    assert "unknown_capability:Foo.Bar" in reasons


def test_top_level_technical_field_discarded():
    """Top-level parameters with technical field also checked."""
    payload = {
        "capabilityId": "MM.Inventory.GetAvailability",
        "parameters": {"token": "abc123"},
    }
    visible_ids = frozenset(("MM.Inventory.GetAvailability",))
    reasons = detect_discard_reasons(payload, visible_ids)
    assert "technical_field:token" in reasons


def test_governance_authority_field_has_a_structured_discard_reason():
    assert prohibited_field_reason("approvalRecord") == "governance_field:approvalRecord"
    assert prohibited_field_reason("principal") == "governance_field:principal"

from sap_nexus_agent.extraction.resolvers import resolve
from sap_nexus_agent.registry_loader import ValueFilters


def test_text_resolver_verbatim():
    assert resolve("DEMOA2", "text", ValueFilters()) == "DEMOA2"
    assert resolve("demoa2", "text", ValueFilters()) == "demoa2"


def test_text_resolver_uppercases_output_when_declared():
    assert resolve("ea", "text", ValueFilters(to_upper_output=True)) == "EA"
    assert resolve("001", "text", ValueFilters(to_upper_output=True)) == "001"


def test_date_resolver_iso_verbatim():
    assert resolve("2026-08-18", "date", ValueFilters()) == "2026-08-18"


def test_quantity_resolver_numeric_verbatim():
    assert resolve("10", "quantity", ValueFilters()) == "10"
    assert resolve("1.5", "quantity", ValueFilters()) == "1.5"


def test_unknown_resolver_raises():
    import pytest

    with pytest.raises(ValueError):
        resolve("x", "decimal", ValueFilters())

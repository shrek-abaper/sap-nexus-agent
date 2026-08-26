from __future__ import annotations

from odata_service.filter_builder import build


def test_single_param():
    mapping = {"vendor": "Supplier"}
    assert build({"vendor": "DEMOV1"}, mapping) == "Supplier eq 'DEMOV1'"


def test_multiple_params_deterministic_order():
    mapping = {
        "poNumber": "PurchaseOrder",
        "vendor": "Supplier",
        "plant": "Plant",
        "material": "Material",
    }
    result = build({"vendor": "DEMOV1", "plant": "1000"}, mapping)
    assert result == "Supplier eq 'DEMOV1' and Plant eq '1000'"


def test_no_params_returns_empty_string():
    assert build({}, {"vendor": "Supplier"}) == ""


def test_empty_value_skipped():
    assert build({"vendor": ""}, {"vendor": "Supplier"}) == ""


def test_none_value_skipped():
    assert build({"vendor": None}, {"vendor": "Supplier"}) == ""


def test_quote_escaping():
    # OData spec: a literal single quote is escaped as two single quotes.
    assert build({"vendor": "O'Brien"}, {"vendor": "Supplier"}) == "Supplier eq 'O''Brien'"


def test_param_not_in_mapping_ignored():
    assert build({"vendor": "DEMOV1", "unknown": "x"}, {"vendor": "Supplier"}) == "Supplier eq 'DEMOV1'"


def test_all_four_params():
    mapping = {
        "poNumber": "PurchaseOrder",
        "vendor": "Supplier",
        "plant": "Plant",
        "material": "Material",
    }
    result = build(
        {
            "poNumber": "4500000001",
            "vendor": "DEMOV1",
            "plant": "1000",
            "material": "MAT001",
        },
        mapping,
    )
    assert result == (
        "PurchaseOrder eq '4500000001' and Supplier eq 'DEMOV1' "
        "and Plant eq '1000' and Material eq 'MAT001'"
    )


def test_created_since_renders_as_datetime_ge_clause_not_string_equality():
    mapping = {"vendor": "Supplier", "createdSince": "CreationDate"}
    result = build({"vendor": "DEMOV1", "createdSince": "2025-08-26"}, mapping)
    assert result == "Supplier eq 'DEMOV1' and CreationDate ge datetime'2025-08-26T00:00:00'"


def test_created_since_alone_skips_string_quoting():
    assert build({"createdSince": "2025-08-26"}, {"createdSince": "CreationDate"}) == (
        "CreationDate ge datetime'2025-08-26T00:00:00'"
    )

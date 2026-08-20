"""Compiled-regex behavior of the named matcher kinds (Design §3.1, §3.2)."""
from sap_nexus_agent.extraction._matching import (
    EMPTY_FILTERS,
    _compile_named_kind,
    _merge_matcher,
    match_value,
)
from sap_nexus_agent.extraction.engine import extract_parameters
from sap_nexus_agent.registry_loader import MatcherConfig, load_intent_catalog

CATALOG = load_intent_catalog()


def _matcher(kind, **kwargs):
    return MatcherConfig(kind=kind, **kwargs)


def test_named_kind_compiled_patterns_pinned():
    # Design §3.7: unit tests pin the compiled regex per kind.
    assert _compile_named_kind(
        _matcher("prefixed", prefix=("在",), value_shape="plantCode"), CATALOG
    ).pattern == r"(?:在)\s*([A-Z0-9]{4})(?![A-Za-z0-9])"
    assert _compile_named_kind(
        _matcher("suffixed", suffix=("工厂",), value_shape="plantCode"), CATALOG
    ).pattern == r"(?<![A-Za-z0-9])([A-Z0-9]{4})\s*(?:工厂)"
    assert _compile_named_kind(
        _matcher("valueShape", value_shape="plantCode"), CATALOG
    ).pattern == r"(?<![A-Za-z0-9])([A-Z0-9]{4})(?![A-Za-z0-9])"
    # Unknown shape -> None (matcher never matches; safe degrade).
    assert _compile_named_kind(_matcher("prefixed", prefix=("在",), value_shape="nope"), CATALOG) is None
    # Anchor stripping: shape '^...$' anchors live at shape level, not in the
    # composed matcher.
    assert _compile_named_kind(
        _matcher("prefixed", prefix=("在",), value_shape="plantCode"), CATALOG
    ).search("在 1000") is not None


def test_prefixed_matches_value_after_token():
    m = _matcher("prefixed", prefix=("在",), value_shape="plantCode")
    assert match_value(m, "在 1000 创建采购申请", CATALOG, EMPTY_FILTERS, set()) == "1000"
    assert match_value(m, "在1000", CATALOG, EMPTY_FILTERS, set()) == "1000"
    assert match_value(m, "采购申请 1000", CATALOG, EMPTY_FILTERS, set()) is None


def test_suffixed_matches_value_before_token():
    m = _matcher("suffixed", suffix=("工厂",), value_shape="plantCode")
    assert match_value(m, "采购申请 1000 工厂", CATALOG, EMPTY_FILTERS, set()) == "1000"
    assert match_value(m, "1000工厂", CATALOG, EMPTY_FILTERS, set()) == "1000"
    assert match_value(m, "采购申请 1000", CATALOG, EMPTY_FILTERS, set()) is None


def test_value_shape_bare_scan_uses_alnum_boundary_guards():
    m = _matcher("valueShape", value_shape="plantCode")
    assert match_value(m, "工厂 1000", CATALOG, EMPTY_FILTERS, set()) == "1000"
    assert match_value(m, "AB12", CATALOG, EMPTY_FILTERS, set()) == "AB12"
    assert match_value(m, "x1000x", CATALOG, EMPTY_FILTERS, set()) is None
    assert match_value(m, "10000", CATALOG, EMPTY_FILTERS, set()) is None


def test_plant_named_kinds_extract_letter_mixed_code_ab12():
    # Design §3.2: contract, not accident — plantCode ^[A-Z0-9]{4}$ accepts
    # letter-mixed codes the legacy [A-Z]\d{3}|\d{4} rejected.
    plant = CATALOG.semantic_types.find("Plant")
    assert plant is not None
    prefixed, suffixed, _bare = plant.matchers
    assert match_value(prefixed, "在 AB12", CATALOG, EMPTY_FILTERS, set()) == "AB12"
    assert match_value(suffixed, "AB12 工厂", CATALOG, EMPTY_FILTERS, set()) == "AB12"


def test_plant_named_kinds_preserve_legacy_alternation():
    # Design §3.1 equivalence boundary: the old single regex accepted
    # "在 X" OR "X 工厂"; two named matchers preserve that alternation, and
    # "在 X 工厂" hits the prefixed matcher first, same as the legacy first
    # alternative.
    plant = CATALOG.semantic_types.find("Plant")
    assert match_value(plant.matchers[0], "在 1000", CATALOG, EMPTY_FILTERS, set()) == "1000"
    assert match_value(plant.matchers[1], "1000 工厂", CATALOG, EMPTY_FILTERS, set()) == "1000"
    assert match_value(plant.matchers[0], "在 1000 工厂", CATALOG, EMPTY_FILTERS, set()) == "1000"


def test_named_kinds_do_not_carve_shape_window_out_of_longer_adjacent_token():
    # Regression: prefixed/suffixed lacked the alnum guard on their free side,
    # so the 4-char plantCode window was carved out of the middle of a longer
    # adjacent token ("DEMOA2 工厂" -> "MOA2", "在 DEMOA2" -> "DEMO").
    plant = CATALOG.semantic_types.find("Plant")
    prefixed, suffixed, _bare = plant.matchers
    assert match_value(suffixed, "DEMOA2 工厂", CATALOG, EMPTY_FILTERS, set()) is None
    assert match_value(prefixed, "在 DEMOA2", CATALOG, EMPTY_FILTERS, set()) is None


def test_inventory_plant_ignores_material_tail_adjacent_to_suffix_token():
    # End-to-end user-visible harm: a wrong plant reached the gateway with
    # missing=[] because "MOA2" still satisfies ^[A-Z0-9]{4}$.
    cap = next(
        c for c in CATALOG.capabilities if c.capability_id == "MM.Inventory.GetAvailability"
    )
    params = extract_parameters("查询库存 DEMOA2 工厂 1000", cap, CATALOG)
    assert params["plant"] == "1000"
    assert params["material"] == "DEMOA2"


def test_semantic_type_wrapper_merges_named_kind_fields():
    plant = CATALOG.semantic_types.find("Plant")
    wrapper = MatcherConfig(kind="semanticType", ref="Plant")
    merged = _merge_matcher(plant.matchers[0], wrapper)
    assert merged.kind == "prefixed"
    assert merged.prefix == ("在",)
    assert merged.value_shape == "plantCode"
    # The wrapper path (semanticType ref) extracts through the named kind.
    assert match_value(wrapper, "在 1000", CATALOG, EMPTY_FILTERS, set()) == "1000"

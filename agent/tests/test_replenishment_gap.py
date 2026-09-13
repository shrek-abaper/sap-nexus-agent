"""Deterministic replenishment-gap calculation.

PR draft proposals must order the supply gap (target requirement minus stock
and in-transit PR/PO due by the target date), never the raw target quantity.
"""

import pytest

from sap_nexus_agent.replenishment import (
    compute_replenishment_gap,
    render_gap_basis,
)


def _data(lines, *, qty=None, unit="EA"):
    data = {"mrpElementLines": lines}
    if qty is not None:
        data.update(availableQuantity=qty, unit=unit)
    return data


def _line(ind, qty, date):
    return {"mrpElementInd": ind, "availQty1": qty, "date": date}


def test_gap_subtracts_stock_and_due_in_transit_pr_and_po():
    data = _data([
        _line("WB", 2, "2026-09-13"),
        _line("BA", 1, "2026-09-20"),
        _line("BE", 2, "2026-08-12"),
    ])
    calc = compute_replenishment_gap(
        required_quantity="10", target_date="2026-09-30", availability_data=data
    )

    assert calc is not None
    assert calc.supply_total == 5
    assert calc.gap_quantity == "5"


def test_in_transit_arriving_after_target_is_excluded_and_listed():
    data = _data([
        _line("WB", 2, "2026-09-13"),
        _line("BE", 3, "2026-10-15"),
    ])
    calc = compute_replenishment_gap(
        required_quantity="10", target_date="2026-09-30", availability_data=data
    )

    assert calc is not None
    assert calc.supply_total == 2
    assert calc.gap_quantity == "8"
    assert len(calc.excluded_lines) == 1
    assert calc.excluded_lines[0].indicator == "BE"
    assert "2026-09-30" in (calc.excluded_lines[0].reason or "")


def test_demand_and_planning_indicators_never_count_as_supply():
    # Fe (planned order), sales order, reservation, independent requirements...
    data = _data([
        _line("WB", 1, "2026-09-13"),
        _line("FE", 9, "2026-09-20"),
        _line("BR", 4, "2026-09-25"),
    ])
    calc = compute_replenishment_gap(
        required_quantity="10", target_date="2026-09-30", availability_data=data
    )

    assert calc is not None
    assert calc.supply_total == 1
    assert calc.gap_quantity == "9"


def test_zero_or_negative_gap_renders_sufficient():
    data = _data([
        _line("WB", 1, "2026-09-13"),
        _line("BA", 3, "2026-09-30"),
        _line("BA", 13, "2026-09-30"),
    ])
    calc = compute_replenishment_gap(
        required_quantity="10", target_date="2026-09-30", availability_data=data
    )

    assert calc is not None
    assert calc.gap <= 0
    text = render_gap_basis(calc, sufficient=True)
    assert "供应合计：17 EA" in text
    assert "无需补货" in text


def test_numeric_string_quantities_are_parsed_exactly():
    data = _data([_line("WB", "2.0", "2026-09-13"), _line("BE", "3.0", "2026-09-20")])
    calc = compute_replenishment_gap(
        required_quantity="10.0", target_date="2026-09-30", availability_data=data
    )

    assert calc is not None
    assert calc.gap_quantity == "5"


def test_unusable_fact_fails_closed_with_none():
    assert compute_replenishment_gap(
        required_quantity="10", target_date="2026-09-30", availability_data={}
    ) is None
    assert compute_replenishment_gap(
        required_quantity="x", target_date="2026-09-30",
        availability_data=_data([_line("WB", 1, "2026-09-13")]),
    ) is None


def test_basis_text_lists_included_and_excluded_lines():
    data = _data([
        _line("WB", 2, "2026-09-13"),
        _line("BE", 3, "2026-08-12"),
        _line("BA", 4, "2026-10-20"),
    ])
    calc = compute_replenishment_gap(
        required_quantity="10", target_date="2026-09-30", availability_data=data
    )

    text = render_gap_basis(calc, sufficient=False)
    assert "目标需求量：10 EA" in text
    assert "在途采购订单：3 EA" in text
    assert "在途采购申请：4 EA" in text
    assert "缺口：5 EA" in text

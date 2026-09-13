"""Deterministic replenishment-gap calculation for PR draft proposals.

The WRITE capability ``MM.PR.CreateDraft`` must not turn the user's target
requirement (``requiredQuantity``) into the PR quantity directly. The proposal
quantity is the supply gap computed from live availability facts:

    gap = target requirement - (current stock + in-transit PR/PO due by target)

The computation is fully deterministic and server-side; the LLM only narrates
the result. Evidence MRP element indicators:

- ``WB`` (Stock)               -> current stock, always counted
- ``BA`` (PurRqs, purchase requisition) -> in-transit supply
- ``BE`` (POitem, purchase order item)   -> in-transit supply

``BA``/``BE`` lines count only when their available date is on or before the
target date. Any other MRP indicator never counts as supply.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

STOCK_INDICATOR = "WB"
IN_TRANSIT_INDICATORS: dict[str, str] = {
    "BA": "采购申请",
    "BE": "采购订单",
}


def _to_decimal(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, AttributeError):
        return None


def _format_quantity(value: Decimal) -> str:
    """Render an integral quantity without a decimal point (PR qty is EA)."""
    if value == value.to_integral_value():
        return str(int(value))
    return format(value.normalize(), "f")


@dataclass(frozen=True)
class SupplyLine:
    """One MRP element line considered in the gap computation."""

    indicator: str
    label: str
    quantity: Decimal
    date: str
    included: bool
    reason: str | None = None


@dataclass(frozen=True)
class GapCalculation:
    required_quantity: Decimal
    stock: Decimal
    included_lines: tuple[SupplyLine, ...]
    excluded_lines: tuple[SupplyLine, ...]
    unit: str | None
    supply_total: Decimal
    gap: Decimal

    @property
    def gap_quantity(self) -> str:
        return _format_quantity(self.gap)

    @property
    def required_quantity_text(self) -> str:
        return _format_quantity(self.required_quantity)

    @property
    def stock_text(self) -> str:
        return _format_quantity(self.stock)


def compute_replenishment_gap(
    *,
    required_quantity: str,
    target_date: str,
    availability_data: Mapping,
    unit: str | None = None,
) -> GapCalculation | None:
    """Compute the supply gap from one availability execution's ``data``.

    Returns ``None`` when the fact is unusable (no quantity / unparseable
    values) so callers fail closed instead of guessing.
    """
    required = _to_decimal(required_quantity)
    if required is None:
        return None

    lines_raw = availability_data.get("mrpElementLines")
    if not isinstance(lines_raw, (list, tuple)):
        return None

    stock = Decimal("0")
    included: list[SupplyLine] = []
    excluded: list[SupplyLine] = []

    for raw in lines_raw:
        if not isinstance(raw, Mapping):
            continue
        indicator = str(raw.get("mrpElementInd") or "").strip().upper()
        qty = _to_decimal(raw.get("availQty1"))
        line_date = str(raw.get("date") or "").strip()
        if not indicator or qty is None:
            continue

        if indicator == STOCK_INDICATOR:
            stock += qty
            included.append(SupplyLine(indicator, "现有库存", qty, line_date, True))
        elif indicator in IN_TRANSIT_INDICATORS:
            label = IN_TRANSIT_INDICATORS[indicator]
            in_time = bool(line_date) and line_date <= target_date
            line = SupplyLine(
                indicator,
                label,
                qty,
                line_date,
                in_time,
                None if in_time else f"晚于目标日期 {target_date}，未计入",
            )
            (included if in_time else excluded).append(line)
        # Other MRP indicators are demand/planning elements, never supply.

    supply_total = stock + sum((line.quantity for line in included if line.indicator != STOCK_INDICATOR), Decimal("0"))
    return GapCalculation(
        required_quantity=required,
        stock=stock,
        included_lines=tuple(included),
        excluded_lines=tuple(excluded),
        unit=unit,
        supply_total=supply_total,
        gap=required - supply_total,
    )


# A type alias that accepts dict-like records without importing Mapping at
# module evaluation time in frozen test contexts.


def render_gap_basis(calc: GapCalculation, *, sufficient: bool) -> str:
    """Deterministic Chinese calculation-basis text for narrative/card."""
    unit = calc.unit or "EA"
    lines = [
        f"目标需求量：{calc.required_quantity_text} {unit}",
        f"当前可用库存：{calc.stock_text} {unit}",
    ]
    for line in calc.included_lines:
        if line.indicator != STOCK_INDICATOR:
            lines.append(
                f"在途{line.label}：{_format_quantity(line.quantity)} {unit}"
                + (f"（{line.date} 到货，计入）" if line.date else "（计入）")
            )
    for line in calc.excluded_lines:
        lines.append(
            f"在途{line.label}：{_format_quantity(line.quantity)} {unit}"
            + (f"（{line.date} 到货，{line.reason}）" if line.reason else "（未计入）")
        )
    lines.append(f"目标日期前可用供应合计：{_format_quantity(calc.supply_total)} {unit}")
    if sufficient:
        lines.append("供应已覆盖目标需求，缺口为 0，无需补货。")
    else:
        lines.append(f"缺口：{calc.gap_quantity} {unit}，建议按缺口数量创建采购申请。")
    return "\n".join(lines)

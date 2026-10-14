"""Four registered analysis operators — single Python Decimal authority.

Operators consume TypedFact rows and emit AnalysisResult rows with full
lineage. No network, no model, no TS arithmetic.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from .contracts import AnalysisResult, ExcludedRow, TypedFact


def _row(fact: TypedFact, fields: list[str] | None = None) -> dict[str, Any]:
    if fields is None:
        values = dict(fact.fields)
    else:
        values = {name: fact.fields[name] for name in fields if name in fact.fields}
    return {
        "factId": fact.fact_id,
        "groupKey": {},
        "fields": {name: value.to_dict() for name, value in values.items()},
        "unit": fact.unit["value"] if fact.unit else None,
        "lineage": [fact.fact_id],
    }


def select_fields(
    node_id: str, facts: tuple[TypedFact, ...], params: dict[str, Any],
    version: str, conflicts: tuple[str, ...] = (),
) -> AnalysisResult:
    if conflicts:
        return _conflict_failure(node_id, "select_fields", version, conflicts)
    field_names = list(params.get("fields", ()))
    rows = tuple(_row(fact, field_names) for fact in facts)
    return AnalysisResult(
        node_id=node_id, operator_id="select_fields", status="complete",
        output_type="rows", rows=rows, excluded_rows=(), operator_version=version,
    )


def filter_eq(
    node_id: str, facts: tuple[TypedFact, ...], params: dict[str, Any],
    version: str, conflicts: tuple[str, ...] = (),
) -> AnalysisResult:
    if conflicts:
        return _conflict_failure(node_id, "filter_eq", version, conflicts)
    field_name = params["field"]
    literal = str(params["value"])
    rows = tuple(
        _row(fact) for fact in facts
        if field_name in fact.fields and fact.fields[field_name].value == literal
    )
    return AnalysisResult(
        node_id=node_id, operator_id="filter_eq", status="complete",
        output_type="rows", rows=rows, excluded_rows=(), operator_version=version,
    )


def group_sum(
    node_id: str, facts: tuple[TypedFact, ...], params: dict[str, Any],
    version: str, conflicts: tuple[str, ...] = (),
) -> AnalysisResult:
    if conflicts:
        return _conflict_failure(node_id, "group_sum", version, conflicts)
    dimensions = tuple(params["dimensions"])
    measure = params["measure"]
    unit_field = params["unitField"]

    groups: dict[tuple[str, ...], dict[str, Any]] = {}
    excluded: list[ExcludedRow] = []
    for fact in facts:
        unit = fact.unit["value"] if fact.unit else None
        if not unit:
            excluded.append(ExcludedRow(fact.fact_id, "MISSING_UNIT"))
            continue
        measure_value = fact.fields.get(measure)
        if measure_value is None:
            excluded.append(ExcludedRow(fact.fact_id, "MEASURE_NOT_PRESENT"))
            continue
        key = tuple(fact.fields[d].value for d in dimensions if d in fact.fields)
        group = groups.setdefault(key, {
            "groupKey": {d: fact.fields[d].value for d in dimensions if d in fact.fields},
            "total": Decimal("0"),
            "unit": unit,
            "lineage": [],
        })
        group["total"] += Decimal(measure_value.value)
        group["lineage"].append(fact.fact_id)

    rows = tuple(
        {
            "groupKey": group["groupKey"],
            "measures": {
                measure: {"decimal": format(group["total"], "f"), "unit": group["unit"]}
            },
            "lineage": group["lineage"],
        }
        for _key, group in sorted(groups.items())
    )
    partial = bool(excluded)
    status = "partial" if partial and rows else ("complete" if rows else "failed")
    return AnalysisResult(
        node_id=node_id, operator_id="group_sum", status=status,
        output_type="groupedRows", rows=rows, excluded_rows=tuple(excluded),
        operator_version=version, partial=partial,
    )


def compare(
    node_id: str, facts: tuple[TypedFact, ...], params: dict[str, Any],
    version: str, conflicts: tuple[str, ...] = (),
) -> AnalysisResult:
    if conflicts:
        return _conflict_failure(node_id, "compare", version, conflicts)
    left_ref = params["left"]
    right_ref = params["right"]
    left = _find(facts, left_ref)
    right = _find(facts, right_ref)
    if left is None or right is None:
        return AnalysisResult(
            node_id=node_id, operator_id="compare", status="failed",
            output_type="comparison", rows=(), excluded_rows=(),
            operator_version=version,
            reasons=("COMPARE_REFERENCE_MISSING",),
        )
    left_field = left.fields[left_ref["field"]]
    right_field = right.fields[right_ref["field"]]
    if left_field.semantic_type != right_field.semantic_type:
        return _incompatible(node_id, version, "semantic kind differs")
    left_unit = left.unit["value"] if left.unit else None
    right_unit = right.unit["value"] if right.unit else None
    if left_unit != right_unit:
        return _incompatible(node_id, version, "unit differs")
    try:
        left_decimal = Decimal(left_field.value)
        right_decimal = Decimal(right_field.value)
    except (InvalidOperation, KeyError):
        return _incompatible(node_id, version, "non-numeric measure")
    return AnalysisResult(
        node_id=node_id, operator_id="compare", status="complete",
        output_type="comparison",
        rows=({
            "left": {"decimal": format(left_decimal, "f"), "unit": left_unit,
                     "factId": left.fact_id},
            "right": {"decimal": format(right_decimal, "f"), "unit": right_unit,
                      "factId": right.fact_id},
            "difference": format(left_decimal - right_decimal, "f"),
        },),
        excluded_rows=(), operator_version=version,
    )


def _find(facts: tuple[TypedFact, ...], ref: dict[str, Any]) -> TypedFact | None:
    fact_id = ref.get("factId")
    return next((f for f in facts if f.fact_id == fact_id), None)


def _incompatible(node_id: str, version: str, detail: str) -> AnalysisResult:
    return AnalysisResult(
        node_id=node_id, operator_id="compare", status="semantic_gap",
        output_type="comparison", rows=(), excluded_rows=(),
        operator_version=version,
        reasons=(f"INCOMPATIBLE_COMPARISON:{detail}",),
    )


def _conflict_failure(
    node_id: str, operator_id: str, version: str, conflicts: tuple[str, ...]
) -> AnalysisResult:
    return AnalysisResult(
        node_id=node_id, operator_id=operator_id, status="failed",
        output_type="groupedRows", rows=(), excluded_rows=(),
        operator_version=version, reasons=tuple(conflicts),
    )

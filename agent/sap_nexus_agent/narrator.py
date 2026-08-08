from __future__ import annotations

import re

from sap_nexus_agent.llm_client import LlmUnavailable, OpenAiCompatibleLlmClient
from sap_nexus_agent.reasoning_fact import ReasoningFact
from sap_nexus_agent.registry_loader import load_intent_catalog


class NarrativeGuardError(ValueError):
    pass


_SYSTEM_CONSTRAINT = (
    "你是一个 SAP 业务结论叙事器。只能使用下方提供的事实字段及其值生成中文叙事，"
    "不得编造任何记录、数值或字段，不得猜测，不得添加未提供的信息，"
    "不得输出 SAP 表名、BAPI/RFC 名或凭据。"
)

_INVENTORY_GUIDANCE = (
    "基于给定的 MRP 元素明细（库存/需求清单，MD04）生成层次化中文叙事：第一行标题说明物料与工厂；"
    "第二段给出当前可用量与单位；第三段对供需关键元素做简要归纳（区分供应与需求）。"
    "只能使用提供的事实字段，不得编造。若无明细，则只陈述可用量。"
    "叙事末尾系统会追加原始 MRP 元素明细表格，你无需重复输出明细行。"
)

_PO_GUIDANCE = (
    "用给定的采购订单条目事实生成中文归纳，列出关键订单（采购订单号、供应商、物料、工厂、数量、单位），"
    "多条时归纳总结。"
)

_GENERIC_GUIDANCE = "用给定事实字段的值生成自然语言中文陈述，只陈述字段中存在的数据。"


def narration_guidance(capability_id: str) -> str:
    """按 businessObject 派生叙事指引；未知能力用通用 fact-based 指引。"""
    catalog = load_intent_catalog()
    descriptor = catalog.find(capability_id)
    business_object = descriptor.business_object if descriptor else ""
    if business_object == "InventoryStock":
        return _INVENTORY_GUIDANCE
    if business_object == "PurchaseOrder":
        return _PO_GUIDANCE
    return _GENERIC_GUIDANCE


_PO_LIMIT = 50
_PO_REQUIRED_EVIDENCE = (
    "purchaseOrder",
    "supplier",
    "plant",
    "material",
    "orderQuantity",
    "purchaseOrderUnit",
)


def _format_mrp_element_lines(evidence: dict) -> str:
    lines = evidence.get("mrpElementLines")
    if not isinstance(lines, list) or not lines:
        return ""
    parts: list[str] = []
    for item in lines:
        if not isinstance(item, dict):
            continue
        parts.append(
            f"元素[{item.get('mrpElementInd', '')}/{item.get('mrpElement', '')}] "
            f"数量={item.get('elementQty', '')} 可用量={item.get('availQty1', '')} 日期={item.get('date', '')}"
        )
    return "\n".join(parts)


def _mrp_detail_rows(evidence: dict) -> list[dict]:
    lines = evidence.get("mrpElementLines")
    if not isinstance(lines, list):
        return []
    return [item for item in lines if isinstance(item, dict)]


def _qty_str(value: object) -> str:
    """Render a quantity without a trailing .0 for integer-valued floats."""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value if value is not None else "")


def _format_mrp_detail_table(evidence: dict) -> str:
    """Deterministic, aligned tabular rendering of MRP element lines.

    Renders the raw MRP_IND_LINES rows as a fixed-width table so the user sees
    the original supply/demand elements alongside the narrative summary.
    """
    rows = _mrp_detail_rows(evidence)
    if not rows:
        return ""
    header = ("元素指示符", "元素描述", "元素数量", "累加可用量", "日期")
    str_rows = [
        (
            str(item.get("mrpElementInd", "") or ""),
            str(item.get("mrpElement", "") or ""),
            _qty_str(item.get("elementQty", "")),
            _qty_str(item.get("availQty1", "")),
            str(item.get("date", "") or ""),
        )
        for item in rows
    ]
    widths = [
        max(len(header[i]), *(len(r[i]) for r in str_rows))
        for i in range(len(header))
    ]
    def _fmt(cells: tuple[str, ...]) -> str:
        return "  ".join(cells[i].ljust(widths[i]) for i in range(len(cells))).rstrip()

    lines = [_fmt(header), _fmt(tuple("─" * widths[i] for i in range(len(header))))]
    lines.extend(_fmt(r) for r in str_rows)
    return "\n".join(lines)


def _inventory_narrative_body(fact: ReasoningFact) -> str:
    """Deterministic structured narrative body for a single inventory fact.

    Layout: title line + blank + 可用量 line, with the raw MRP detail table
    appended when the fact carries mrpElementLines evidence.
    """
    title = f"物料 {fact.material} 在工厂 {fact.plant} 的库存/需求清单（MD04）"
    availability = f"当前可用量：{_qty_str(fact.value)} {fact.unit}"
    evidence = fact.evidence[0] if fact.evidence else {}
    table = _format_mrp_detail_table(evidence)
    body = f"{title}\n\n{availability}"
    if table:
        body += f"\n\nMRP 元素明细：\n{table}"
    return body


def _build_messages(fact: ReasoningFact, capability_id: str) -> list[dict[str, str]]:
    guidance = narration_guidance(capability_id)
    user_content = (
        f"物料: {fact.material}\n"
        f"工厂: {fact.plant}\n"
        f"可用库存: {fact.value}\n"
        f"单位: {fact.unit}\n"
    )
    evidence = fact.evidence[0] if fact.evidence else {}
    detail = _format_mrp_element_lines(evidence)
    if detail:
        user_content += f"MRP 元素明细:\n{detail}\n"
    return [
        {"role": "system", "content": _SYSTEM_CONSTRAINT},
        {"role": "system", "content": guidance},
        {"role": "user", "content": user_content},
    ]


def _build_po_messages(facts: list[ReasoningFact], total_count: int | None) -> list[dict[str, str]]:
    guidance = narration_guidance("MM.PurchaseOrder.GetList")
    lines: list[str] = []
    for fact in facts[:_PO_LIMIT]:
        ev = fact.evidence[0] if fact.evidence else {}
        lines.append(
            f"采购订单: {ev.get('purchaseOrder', '')}，"
            f"供应商: {ev.get('supplier', '')}，"
            f"物料: {ev.get('material', '')}，"
            f"工厂: {ev.get('plant', '')}，"
            f"数量: {ev.get('orderQuantity', '')} {ev.get('purchaseOrderUnit', '')}"
        )
    user_content = "\n".join(lines)
    if total_count is not None:
        user_content += f"\n总记录数: {total_count}"
    return [
        {"role": "system", "content": _SYSTEM_CONSTRAINT},
        {"role": "system", "content": guidance},
        {"role": "user", "content": user_content},
    ]


def _template_inventory(fact: ReasoningFact) -> str:
    """Deterministic template fallback for inventory narration.

    Structured layout: title + available quantity + raw MRP detail table
    (when evidence carries mrpElementLines).
    """
    return _inventory_narrative_body(fact)


def _template_po(facts: list[ReasoningFact], total_count: int | None) -> str:
    """Deterministic template fallback for PO narration; raises guard on missing evidence."""
    lines: list[str] = []
    for fact in facts[:_PO_LIMIT]:
        evidence = fact.evidence[0] if fact.evidence else {}
        missing = [
            field
            for field in _PO_REQUIRED_EVIDENCE
            if field not in evidence or evidence[field] is None
        ]
        if missing:
            raise NarrativeGuardError(
                f"ReasoningFact missing evidence fields for PO narration: {', '.join(missing)}"
            )
        lines.append(
            f"采购订单 {evidence['purchaseOrder']}："
            f"供应商 {evidence['supplier']}，"
            f"物料 {evidence['material']}，"
            f"工厂 {evidence['plant']}，"
            f"数量 {evidence['orderQuantity']} {evidence['purchaseOrderUnit']}。"
        )
    truncated = len(facts) > _PO_LIMIT or (
        total_count is not None and total_count > _PO_LIMIT
    )
    if truncated:
        lines.append("（仅返回前 50 条。）")
    return "\n".join(lines)


def narrate_fact(
    fact: ReasoningFact,
    *,
    capability_id: str = "MM.Inventory.GetAvailability",
    client=None,
) -> str:
    missing = [
        name
        for name, value in {
            "material": fact.material,
            "plant": fact.plant,
            "value": fact.value,
            "unit": fact.unit,
        }.items()
        if value is None or value == ""
    ]
    if missing:
        raise NarrativeGuardError(f"ReasoningFact missing fields for narration: {', '.join(missing)}")
    try:
        llm_client = client or OpenAiCompatibleLlmClient()
        text = llm_client.chat_text(
            _build_messages(fact, capability_id), temperature=0.0, max_tokens=200
        )
        narrative = redact_sensitive(text.strip())
        # Append the deterministic raw-detail table so the user always sees the
        # original MRP element rows, regardless of LLM phrasing.
        evidence = fact.evidence[0] if fact.evidence else {}
        table = _format_mrp_detail_table(evidence)
        if table:
            narrative += f"\n\nMRP 元素明细：\n{table}"
        return narrative
    except LlmUnavailable:
        return _template_inventory(fact)


def narrate_failure(error_type: str, messages: list[str]) -> str:
    safe_messages = [redact_sensitive(message) for message in messages]
    joined = "；".join(safe_messages) if safe_messages else "未提供错误明细"
    return f"库存查询失败（{error_type}）：{joined}"


def redact_sensitive(text: str) -> str:
    redacted = re.sub(
        r"(?i)([\"']?\b(password|passwd|token|secret)[\"']?\s*[:=]\s*)[\"']?[^\"'\s]+[\"']?",
        lambda m: f"{m.group(1)}***",
        text,
    )
    redacted = re.sub(r"\bSAP_[A-Z0-9_]*\s*[:=]\s*\S+", "SAP_CONFIG=***", redacted)
    redacted = re.sub(r"(?i)\bdestination\s+config\b[^；。]*", "destination=***", redacted)
    redacted = re.sub(r"(?i)\bdestination\s*[:=]\s*\S+", "destination=***", redacted)
    redacted = re.sub(r"(?i)\bhost\s*[:=]\s*\S+", "host=***", redacted)
    redacted = redacted.replace(".env", "[redacted-env]")
    return redacted


# ---------------------------------------------------------------------------
# Purchase Order list narrative
# ---------------------------------------------------------------------------


def narrate_purchase_order_facts(
    facts: list[ReasoningFact],
    *,
    total_count: int | None = None,
    client=None,
) -> str:
    """Grounded narrative for a list of purchase-order-item facts.

    - Empty list -> "无匹配记录。" (not an error, no LLM call).
    - Non-empty: LLM main path (chat_text + redact_sensitive).
    - LlmUnavailable -> template concatenation (guard raises on missing evidence).
    - More than 50 items (or totalCount > 50) -> truncation notice (template path).
    """
    if not facts:
        return "无匹配记录。"

    _assert_po_evidence_complete(facts)

    try:
        llm_client = client or OpenAiCompatibleLlmClient()
        text = llm_client.chat_text(
            _build_po_messages(facts, total_count), temperature=0.0, max_tokens=400
        )
        return redact_sensitive(text.strip())
    except LlmUnavailable:
        return _template_po(facts, total_count)


def _assert_po_evidence_complete(facts: list[ReasoningFact]) -> None:
    """Reject incomplete evidence before narration, regardless of LLM availability.

    Mirrors inventory's guard-before-LLM discipline so behavior is deterministic:
    incomplete evidence raises NarrativeGuardError whether the LLM is up or down.
    """
    for fact in facts[:_PO_LIMIT]:
        evidence = fact.evidence[0] if fact.evidence else {}
        missing = [
            field
            for field in _PO_REQUIRED_EVIDENCE
            if field not in evidence or evidence[field] is None
        ]
        if missing:
            raise NarrativeGuardError(
                f"ReasoningFact missing evidence fields for PO narration: {', '.join(missing)}"
            )


# ---------------------------------------------------------------------------
# Inventory batch narrative (multi-value aggregation, Design Doc §4.5)
# ---------------------------------------------------------------------------


def _assert_inventory_fields(facts: list[ReasoningFact]) -> None:
    """Reject incomplete facts before narration, regardless of LLM availability."""
    for fact in facts:
        missing = [
            name
            for name, value in {
                "material": fact.material,
                "plant": fact.plant,
                "value": fact.value,
                "unit": fact.unit,
            }.items()
            if value is None or value == ""
        ]
        if missing:
            raise NarrativeGuardError(
                f"ReasoningFact missing fields for inventory narration: {', '.join(missing)}"
            )


def _build_inventory_batch_messages(
    facts: list[ReasoningFact],
    failures: list[dict] | None,
) -> list[dict[str, str]]:
    guidance = narration_guidance("MM.Inventory.GetAvailability")
    lines: list[str] = []
    for fact in facts:
        lines.append(
            f"物料: {fact.material}，工厂: {fact.plant}，"
            f"可用库存: {fact.value} {fact.unit}"
        )
        evidence = fact.evidence[0] if fact.evidence else {}
        detail = _format_mrp_element_lines(evidence)
        if detail:
            lines.append(f"MRP 元素明细:\n{detail}")
    if failures:
        for fail in failures:
            params = fail.get("parameters", {})
            lines.append(
                f"查询失败: 物料 {params.get('material', '')}，"
                f"工厂 {params.get('plant', '')}，错误: {fail.get('error', '')}"
            )
    user_content = "\n".join(lines)
    return [
        {"role": "system", "content": _SYSTEM_CONSTRAINT},
        {"role": "system", "content": guidance},
        {"role": "user", "content": user_content},
    ]


def _template_inventory_batch(
    facts: list[ReasoningFact],
    failures: list[dict] | None,
) -> str:
    """Deterministic template fallback for batch inventory narration.

    Single fact (one material, one plant) uses the structured body with the
    raw MRP detail table; multi-value aggregations keep the compact inline form.
    """
    if len(facts) == 1 and not failures:
        return _inventory_narrative_body(facts[0])
    materials = {fact.material for fact in facts}
    lines: list[str] = []
    if len(materials) <= 1:
        # 单物料：对齐 spec "5200: 176 EA; 1000: 0 EA"
        material = next(iter(materials), None)
        if material:
            lines.append(f"物料 {material}：")
        plant_lines = [
            f"在工厂 {fact.plant} 为 {fact.value} {fact.unit}" for fact in facts
        ]
        lines.append("；".join(plant_lines) + "。")
    else:
        # 多物料：每条含 material
        for fact in facts:
            lines.append(
                f"物料 {fact.material} 在工厂 {fact.plant} 为 {fact.value} {fact.unit}；"
            )
        lines[-1] = lines[-1].rstrip("；") + "。"
    if failures:
        for fail in failures:
            params = fail.get("parameters", {})
            lines.append(f"工厂 {params.get('plant', '')} 查询失败。")
    return "".join(lines) if len(materials) <= 1 else "\n".join(lines)


def narrate_inventory_facts(
    facts: list[ReasoningFact],
    *,
    failures: list[dict] | None = None,
    client=None,
) -> str:
    """Grounded narrative for a list of inventory facts (multi-value aggregation).

    - Empty facts + no failures -> "无匹配记录。" (no LLM call).
    - Non-empty: LLM main path (chat_text + redact_sensitive).
    - LlmUnavailable -> template fallback (guard raises on missing fields).
    - Partial failures appended as annotations.
    """
    if not facts and not failures:
        return "无匹配记录。"

    _assert_inventory_fields(facts)

    try:
        llm_client = client or OpenAiCompatibleLlmClient()
        text = llm_client.chat_text(
            _build_inventory_batch_messages(facts, failures), temperature=0.0, max_tokens=400
        )
        return redact_sensitive(text.strip())
    except LlmUnavailable:
        return _template_inventory_batch(facts, failures)

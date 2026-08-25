from __future__ import annotations

import re

from sap_nexus_agent.llm_client import LlmUnavailable, OpenAiCompatibleLlmClient
from sap_nexus_agent.reasoning_fact import ReasoningFact
from sap_nexus_agent.registry_loader import NarrativeConfig, load_intent_catalog


class NarrativeGuardError(ValueError):
    pass


_SYSTEM_CONSTRAINT = (
    "你是一个 SAP 业务结论叙事器。只能使用下方提供的事实字段及其值生成中文叙事，"
    "不得编造任何记录、数值或字段，不得猜测，不得添加未提供的信息，"
    "不得输出 SAP 表名、BAPI/RFC 名或凭据。"
)

# ---------------------------------------------------------------------------
# Centralized prompt/fallback template registry (D5: templates are IDs, not
# inline yaml strings). Each prompt template is a guidance string paired with a
# user-content builder; each fallback template is a deterministic renderer.
# Adding a capability's narration only declares the template id in yaml + adds
# the template here (no new narration pipeline).
# ---------------------------------------------------------------------------

_PROMPT_GUIDANCE: dict[str, str] = {
    "inventory-md04": (
        "基于给定的 MRP 元素明细（库存/需求清单，MD04）生成层次化中文叙事：第一行标题说明物料与工厂；"
        "第二段给出当前可用量与单位；第三段对供需关键元素做简要归纳（区分供应与需求）。"
        "只能使用提供的事实字段，不得编造。若无明细，则只陈述可用量。"
        "叙事末尾系统会追加原始 MRP 元素明细表格，你无需重复输出明细行。"
    ),
    "purchase-order-list": (
        "用给定的采购订单条目事实生成中文归纳，列出关键订单（采购订单号、供应商、物料、工厂、数量、单位），"
        "多条时归纳总结。"
    ),
    "pr-create-receipt": (
        "用给定的采购申请创建结果事实生成中文回执，说明 PR 号。"
        "只能使用提供的事实字段，不得编造。"
    ),
}

_GENERIC_GUIDANCE = "用给定事实字段的值生成自然语言中文陈述，只陈述字段中存在的数据。"


def _guidance_for(config: NarrativeConfig | None) -> str:
    if config is None:
        return _GENERIC_GUIDANCE
    return _PROMPT_GUIDANCE.get(config.prompt_template, _GENERIC_GUIDANCE)


_PO_LIMIT = 50
_PO_REQUIRED_EVIDENCE = (
    "purchaseOrder",
    "supplier",
    "plant",
    "material",
    "orderQuantity",
    "purchaseOrderUnit",
)


# ---------------------------------------------------------------------------
# Quantity formatting helper (integer-valued floats render without .0)
# ---------------------------------------------------------------------------


def _qty_str(value: object) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value if value is not None else "")


# ---------------------------------------------------------------------------
# Detail formatter registry (D3: pluggable, keyed by id; unknown -> none)
# ---------------------------------------------------------------------------


def _format_mrp_detail_table(evidence: dict) -> str:
    """Aligned tabular rendering of MRP element lines (mrp-table formatter)."""
    rows = evidence.get("mrpElementLines")
    if not isinstance(rows, list):
        return ""
    rows = [item for item in rows if isinstance(item, dict)]
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


def _format_po_list_detail(facts: list[ReasoningFact]) -> str:
    """Inline list rendering of PO item facts (po-list formatter)."""
    lines: list[str] = []
    for fact in facts[:_PO_LIMIT]:
        ev = fact.evidence[0] if fact.evidence else {}
        lines.append(
            f"采购订单 {ev.get('purchaseOrder', '')}："
            f"供应商 {ev.get('supplier', '')}，"
            f"物料 {ev.get('material', '')}，"
            f"工厂 {ev.get('plant', '')}，"
            f"数量 {ev.get('orderQuantity', '')} {ev.get('purchaseOrderUnit', '')}。"
        )
    return "\n".join(lines)


def _format_no_detail(_evidence: dict) -> str:
    return ""


# detailFormatter id -> function(evidence_or_facts) -> str
_DETAIL_FORMATTERS: dict[str, object] = {
    "mrp-table": _format_mrp_detail_table,
    "po-list": _format_po_list_detail,
    "none": _format_no_detail,
}


def _resolve_detail_formatter(config: NarrativeConfig | None):
    formatter_id = config.detail_formatter if config else "none"
    return _DETAIL_FORMATTERS.get(formatter_id, _format_no_detail)


# ---------------------------------------------------------------------------
# fieldMapping resolution: map fact fixed fields + evidence dynamic fields to
# template variables (D6).
# ---------------------------------------------------------------------------


def _resolve_template_vars(fact: ReasoningFact, config: NarrativeConfig | None) -> dict[str, str]:
    """Resolve fieldMapping to concrete values from a single fact."""
    if config is None:
        return {}
    evidence = fact.evidence[0] if fact.evidence else {}
    vars_: dict[str, str] = {}
    for var_name, source_expr in config.field_mapping:
        vars_[var_name] = _resolve_one_var(source_expr, fact, evidence)
    return vars_


def _resolve_one_var(source_expr: str, fact: ReasoningFact, evidence: dict) -> str:
    """Resolve one fieldMapping source expression to a string value.

    Supports:
      - {material}/{plant}/{value}/{unit} placeholders filled from fact fixed fields
      - a bare evidence field name (e.g. mrpElementLines) -> rendered detail (handled by formatter)
      - comma-separated evidence field names -> kept as-is for list builders
    """
    if "{" in source_expr and "}" in source_expr:
        return source_expr.format(
            material=fact.material or "",
            plant=fact.plant or "",
            value=_qty_str(fact.value),
            unit=fact.unit or "",
        )
    return source_expr


# ---------------------------------------------------------------------------
# Single-value narration (factShape: single-value) - inventory
# ---------------------------------------------------------------------------


def _inventory_narrative_body(fact: ReasoningFact, config: NarrativeConfig | None) -> str:
    """Deterministic structured body: title + 可用量 + detail table (via formatter)."""
    vars_ = _resolve_template_vars(fact, config)
    title_text = vars_.get("title", f"{fact.material} 在工厂 {fact.plant}")
    title = f"物料 {title_text} 的库存/需求清单（MD04）"
    availability = f"当前可用量：{_qty_str(fact.value)} {fact.unit}"
    evidence = fact.evidence[0] if fact.evidence else {}
    formatter = _resolve_detail_formatter(config)
    detail = formatter(evidence) if config and config.detail_formatter != "none" else ""
    body = f"{title}\n\n{availability}"
    if detail:
        body += f"\n\nMRP 元素明细：\n{detail}"
    return body


def _build_single_value_messages(fact: ReasoningFact, config: NarrativeConfig | None) -> list[dict[str, str]]:
    guidance = _guidance_for(config)
    user_content = (
        f"物料: {fact.material}\n"
        f"工厂: {fact.plant}\n"
        f"可用库存: {fact.value}\n"
        f"单位: {fact.unit}\n"
    )
    evidence = fact.evidence[0] if fact.evidence else {}
    # Feed detail rows to the LLM in compact form for grounding.
    lines = evidence.get("mrpElementLines")
    if isinstance(lines, list) and lines:
        parts = []
        for item in lines:
            if not isinstance(item, dict):
                continue
            parts.append(
                f"元素[{item.get('mrpElementInd', '')}/{item.get('mrpElement', '')}] "
                f"数量={item.get('elementQty', '')} 可用量={item.get('availQty1', '')} 日期={item.get('date', '')}"
            )
        user_content += "MRP 元素明细:\n" + "\n".join(parts) + "\n"
    return [
        {"role": "system", "content": _SYSTEM_CONSTRAINT},
        {"role": "system", "content": guidance},
        {"role": "user", "content": user_content},
    ]


def narrate_single_value(
    fact: ReasoningFact,
    config: NarrativeConfig | None = None,
    *,
    client=None,
) -> str:
    """Generic single-value narration (factShape: single-value)."""
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
            _build_single_value_messages(fact, config), temperature=0.0, max_tokens=200
        )
        narrative = redact_sensitive(text.strip())
        evidence = fact.evidence[0] if fact.evidence else {}
        formatter = _resolve_detail_formatter(config)
        detail = formatter(evidence) if config and config.detail_formatter != "none" else ""
        if detail:
            narrative += f"\n\nMRP 元素明细：\n{detail}"
        return narrative
    except LlmUnavailable:
        return _inventory_narrative_body(fact, config)


# ---------------------------------------------------------------------------
# List narration (factShape: list) - purchase order
# ---------------------------------------------------------------------------


def _build_list_messages(facts: list[ReasoningFact], total_count: int | None, config: NarrativeConfig | None) -> list[dict[str, str]]:
    guidance = _guidance_for(config)
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


def _assert_po_evidence_complete(facts: list[ReasoningFact]) -> None:
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


def _list_fallback(facts: list[ReasoningFact], total_count: int | None) -> str:
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


def narrate_list(
    facts: list[ReasoningFact],
    config: NarrativeConfig | None = None,
    *,
    total_count: int | None = None,
    client=None,
) -> str:
    """Generic list narration (factShape: list)."""
    if not facts:
        return "无匹配记录。"
    _assert_po_evidence_complete(facts)
    try:
        llm_client = client or OpenAiCompatibleLlmClient()
        text = llm_client.chat_text(
            _build_list_messages(facts, total_count, config), temperature=0.0, max_tokens=400
        )
        return redact_sensitive(text.strip())
    except LlmUnavailable:
        return _list_fallback(facts, total_count)


# ---------------------------------------------------------------------------
# Action-receipt narration (factShape: action-receipt) - PR create
# ---------------------------------------------------------------------------


def _action_receipt_body(fact: ReasoningFact, config: NarrativeConfig | None) -> str:
    evidence = fact.evidence[0] if fact.evidence else {}
    pr_number = str(evidence.get("value", "") or "")
    if pr_number:
        return f"采购申请创建成功，PR 号：{pr_number}"
    return "采购请求创建成功但未返回 PR 号。"


def narrate_action_receipt(
    fact: ReasoningFact,
    config: NarrativeConfig | None = None,
    *,
    client=None,
) -> str:
    """Generic action-receipt narration (factShape: action-receipt).

    Deterministic: PR create receipt does not call the LLM (it is a structured
    confirmation, not an inductive summary).
    """
    return _action_receipt_body(fact, config)


# ---------------------------------------------------------------------------
# Failure narration (unchanged)
# ---------------------------------------------------------------------------


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
# Backward-compatible dispatch: resolve NarrativeConfig by capability_id and
# route to the factShape entry point. Old per-capability entry points below are
# thin shims so existing callers/tests keep working during the migration.
# ---------------------------------------------------------------------------


def _config_for(capability_id: str) -> NarrativeConfig | None:
    catalog = load_intent_catalog()
    descriptor = catalog.find(capability_id)
    return descriptor.narrative if descriptor else None


def narrate_by_capability(
    fact: ReasoningFact,
    capability_id: str,
    *,
    client=None,
) -> str:
    """Unified single-fact dispatch by capability's narrative.factShape."""
    config = _config_for(capability_id)
    shape = config.fact_shape if config else "single-value"
    if shape == "action-receipt":
        return narrate_action_receipt(fact, config, client=client)
    return narrate_single_value(fact, config, client=client)


def narrate_list_by_capability(
    facts: list[ReasoningFact],
    capability_id: str,
    *,
    total_count: int | None = None,
    client=None,
) -> str:
    """Unified list-fact dispatch by capability's narrative.factShape."""
    config = _config_for(capability_id)
    return narrate_list(facts, config, total_count=total_count, client=client)


# ---------------------------------------------------------------------------
# Backward-compatible shims (preserve existing call sites during migration)
# ---------------------------------------------------------------------------


# Kept for callers that still import narration_guidance / narrate_fact etc.
def narration_guidance(capability_id: str) -> str:
    """Legacy guidance lookup by capability_id; delegates to the template registry."""
    return _guidance_for(_config_for(capability_id))


def narrate_fact(
    fact: ReasoningFact,
    *,
    capability_id: str = "MM.Inventory.GetAvailability",
    client=None,
) -> str:
    """Legacy single-fact entry; delegates to narrate_single_value."""
    return narrate_single_value(fact, _config_for(capability_id), client=client)


def narrate_purchase_order_facts(
    facts: list[ReasoningFact],
    *,
    total_count: int | None = None,
    client=None,
) -> str:
    """Legacy PO list entry; delegates to narrate_list."""
    return narrate_list(facts, _config_for("MM.PurchaseOrder.GetList"), total_count=total_count, client=client)


def _assert_inventory_fields(facts: list[ReasoningFact]) -> None:
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
    config = _config_for("MM.Inventory.GetAvailability")
    guidance = _guidance_for(config)
    lines: list[str] = []
    for fact in facts:
        lines.append(
            f"物料: {fact.material}，工厂: {fact.plant}，"
            f"可用库存: {fact.value} {fact.unit}"
        )
        evidence = fact.evidence[0] if fact.evidence else {}
        rows = evidence.get("mrpElementLines")
        if isinstance(rows, list) and rows:
            parts = []
            for item in rows:
                if not isinstance(item, dict):
                    continue
                parts.append(
                    f"元素[{item.get('mrpElementInd', '')}/{item.get('mrpElement', '')}] "
                    f"数量={item.get('elementQty', '')} 可用量={item.get('availQty1', '')} 日期={item.get('date', '')}"
                )
            lines.append(f"MRP 元素明细:\n" + "\n".join(parts))
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
    config = _config_for("MM.Inventory.GetAvailability")
    if len(facts) == 1 and not failures:
        return _inventory_narrative_body(facts[0], config)
    materials = {fact.material for fact in facts}
    lines: list[str] = []
    if len(materials) <= 1:
        material = next(iter(materials), None)
        if material:
            lines.append(f"物料 {material}：")
        plant_lines = [
            f"在工厂 {fact.plant} 为 {fact.value} {fact.unit}" for fact in facts
        ]
        lines.append("；".join(plant_lines) + "。")
    else:
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
    """Legacy batch inventory entry; delegates to the generic batch path."""
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

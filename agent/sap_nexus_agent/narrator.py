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
    "用给定物料的可用库存事实生成一句中文结论，说明物料在工厂的可用库存量与单位。"
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


def _build_messages(fact: ReasoningFact, capability_id: str) -> list[dict[str, str]]:
    guidance = narration_guidance(capability_id)
    user_content = (
        f"物料: {fact.material}\n"
        f"工厂: {fact.plant}\n"
        f"可用库存: {fact.value}\n"
        f"单位: {fact.unit}\n"
    )
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
    """Deterministic template fallback for inventory narration."""
    return f"物料 {fact.material} 在工厂 {fact.plant} 的可用库存为 {fact.value} {fact.unit}。"


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
        return redact_sensitive(text.strip())
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

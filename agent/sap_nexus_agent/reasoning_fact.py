from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import uuid

from sap_nexus_agent.execution_result import ExecutionResult


@dataclass(frozen=True)
class ReasoningFact:
    fact_id: str
    agent_trace_id: str
    trace_id: str
    gateway_trace_id: str
    domain: str
    business_object: str
    predicate: str
    value: float | int | None
    unit: str | None
    deterministic: bool
    confidence: float
    source: dict[str, Any]
    evidence: list[dict[str, Any]]
    material: str | None = None
    plant: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "factId": self.fact_id,
            "agentTraceId": self.agent_trace_id,
            "traceId": self.trace_id,
            "gatewayTraceId": self.gateway_trace_id,
            "domain": self.domain,
            "businessObject": self.business_object,
            "predicate": self.predicate,
            "value": self.value,
            "unit": self.unit,
            "deterministic": self.deterministic,
            "confidence": self.confidence,
            "source": dict(self.source),
            "evidence": list(self.evidence),
            "material": self.material,
            "plant": self.plant,
        }


def build_availability_fact(
    agent_trace_id: str,
    result: ExecutionResult,
    parameters: dict[str, str] | None = None,
) -> ReasoningFact | None:
    if not result.success:
        return None
    quantity = result.data.get("availableQuantity")
    if quantity is None:
        return None
    context = parameters or {}
    unit = result.data.get("unit") or context.get("unit")
    gateway_trace_id = result.trace_id
    evidence = {
        "field": "availableQuantity",
        "value": quantity,
        "sourceField": result.data.get("sourceField") or "AV_QTY_PLT",
    }
    for key in ("sourceTable", "mrpElementInd", "mrpElement", "availableDate"):
        if key in result.data:
            evidence[key] = result.data[key]
    mrp_element_lines = result.data.get("mrpElementLines")
    if mrp_element_lines:
        evidence["mrpElementLines"] = mrp_element_lines
    return ReasoningFact(
        fact_id=f"fact-{uuid.uuid4()}",
        agent_trace_id=agent_trace_id,
        trace_id=agent_trace_id,
        gateway_trace_id=gateway_trace_id,
        domain="MM",
        business_object="InventoryStock",
        predicate="availableQuantity",
        value=quantity,
        unit=str(unit) if unit is not None else None,
        deterministic=True,
        confidence=1.0,
        source={
            "capabilityId": result.capability_id,
            "executorType": result.executor.get("type"),
            "rfcName": result.executor.get("rfcName"),
        },
        evidence=[evidence],
        material=_optional_text(result.data.get("material") or context.get("material")),
        plant=_optional_text(result.data.get("plant") or context.get("plant")),
    )


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def build_purchase_order_facts(
    agent_trace_id: str,
    result: ExecutionResult,
    parameters: dict[str, str] | None = None,
) -> list[ReasoningFact]:
    """Normalise PO list rows into one ReasoningFact per item.

    Each fact carries predicate=purchaseOrderItem with evidence extracted from
    the camelCase PO item fields returned by the Gateway OData executor.
    An empty list (or failed execution) yields zero facts -- empty is not an error.

    Supports two PO data shapes:
    - Nested (real OData service): header has purchaseOrder/supplier; item-level
      fields (plant/material/orderQuantity/purchaseOrderUnit) live in header.items[].
      One fact is produced per nested item.
    - Flat (legacy/test shape): every field sits directly on the PO entry; one
      fact is produced per entry.
    """
    if not result.success:
        return []
    items = result.data.get("purchaseOrders")
    if not items:
        return []
    context = parameters or {}
    facts: list[ReasoningFact] = []
    for po in items:
        if not isinstance(po, dict):
            continue
        nested_items = po.get("items")
        if isinstance(nested_items, list):
            # Nested OData shape: one fact per item; empty items -> no fact.
            for item in nested_items:
                if isinstance(item, dict):
                    facts.append(_build_po_fact(agent_trace_id, result, po, item, context))
        else:
            facts.append(_build_po_fact(agent_trace_id, result, po, po, context))
    return facts


def _build_po_fact(
    agent_trace_id: str,
    result: ExecutionResult,
    header: dict[str, Any],
    item: dict[str, Any],
    context: dict[str, str],
) -> ReasoningFact:
    """Build one PO item fact. Header supplies purchaseOrder/supplier; item
    supplies plant/material/orderQuantity/purchaseOrderUnit. Item values take
    precedence, falling back to context then header (flat-shape compatibility)."""
    purchase_order = item.get("purchaseOrder") or header.get("purchaseOrder")
    supplier = header.get("supplier") or item.get("supplier")
    plant = item.get("plant") or context.get("plant") or header.get("plant")
    material = item.get("material") or context.get("material") or header.get("material")
    order_quantity = item.get("orderQuantity") or header.get("orderQuantity")
    po_unit = item.get("purchaseOrderUnit") or header.get("purchaseOrderUnit")
    evidence = {
        "purchaseOrder": purchase_order,
        "supplier": supplier,
        "plant": plant,
        "material": material,
        "orderQuantity": order_quantity,
        "purchaseOrderUnit": po_unit,
    }
    return ReasoningFact(
        fact_id=f"fact-{uuid.uuid4()}",
        agent_trace_id=agent_trace_id,
        trace_id=agent_trace_id,
        gateway_trace_id=result.trace_id,
        domain="MM",
        business_object="PurchaseOrder",
        predicate="purchaseOrderItem",
        value=order_quantity if isinstance(order_quantity, (int, float)) else None,
        unit=_optional_text(po_unit),
        deterministic=True,
        confidence=1.0,
        source={
            "capabilityId": result.capability_id,
            "executorType": result.executor.get("type"),
            "rfcName": result.executor.get("rfcName"),
        },
        evidence=[evidence],
        material=_optional_text(material),
        plant=_optional_text(plant),
    )


def build_pr_create_fact(
    agent_trace_id: str,
    result: ExecutionResult,
    parameters: dict[str, str] | None = None,
) -> ReasoningFact | None:
    """Build a fact for a successful PR create (action-receipt).

    Carries the created PR number in evidence. Returns None for a failed
    execution. The fact stays deterministic (deterministic=True, confidence=1.0);
    no LLM text is placed in evidence.
    """
    if not result.success:
        return None
    pr_number = result.data.get("prNumber") or ""
    context = parameters or {}
    evidence = {
        "field": "prNumber",
        "value": pr_number,
    }
    return ReasoningFact(
        fact_id=f"fact-{uuid.uuid4()}",
        agent_trace_id=agent_trace_id,
        trace_id=agent_trace_id,
        gateway_trace_id=result.trace_id,
        domain="MM",
        business_object="PurchaseRequisition",
        predicate="purchaseRequisitionCreated",
        value=None,
        unit=None,
        deterministic=True,
        confidence=1.0,
        source={
            "capabilityId": result.capability_id,
            "executorType": result.executor.get("type"),
            "rfcName": result.executor.get("rfcName"),
        },
        evidence=[evidence],
        material=_optional_text(result.data.get("material") or context.get("material")),
        plant=_optional_text(result.data.get("plant") or context.get("plant")),
    )

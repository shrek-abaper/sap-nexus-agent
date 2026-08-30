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


#: Fact Type field name -> the row key the Gateway's generic TABLES extraction
#: emits for it (camelCased SAP column of BAPIORDERS). Declared here rather than
#: inline in the builder so the mapping between a Fact Type field and the SAP
#: column backing it is readable in one place.
_SALES_ORDER_ROW_FIELDS = {
    "salesOrderNumber": "sdDoc",
    "documentType": "docType",
    "documentDate": "docDate",
    "soldTo": "soldTo",
    "material": "material",
    "netValue": "netValue",
    "currency": "currency",
    "salesOrg": "salesOrg",
    "customerPoNumber": "purchNoC",
}

#: Same, for the AR/AP open item row (BAPI3007_2 / BAPI3008_2 share their column
#: names, so one map serves both open-item Fact Types).
_OPEN_ITEM_ROW_FIELDS = {
    "documentNumber": "docNo",
    "documentDate": "docDate",
    "postingDate": "pstngDate",
    "amount": "amtDoccur",
    "currency": "currency",
    "netDueDate": "blineDate",
    "clearingDate": "clearDate",
}


def _optional_number(value: Any) -> float | int | None:
    """Coerce a row value to the Fact's numeric ``value`` slot, or None.

    The generic TABLES extraction reads SAP columns as text, so a monetary
    column arrives as a string. A value that is not a number is not forced into
    the slot; it stays in evidence only.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return float(value.strip().replace(",", ""))
        except ValueError:
            return None
    return None


def _build_row_facts(
    agent_trace_id: str,
    result: ExecutionResult,
    parameters: dict[str, str] | None,
    *,
    data_key: str,
    domain: str,
    business_object: str,
    predicate: str,
    row_fields: dict[str, str],
    value_field: str,
    unit_field: str,
) -> list[ReasoningFact]:
    """One ReasoningFact per row of a JCo TABLES output.

    Shared by the sales order and AR/AP open item builders: they differ only in
    which output the rows come from, which Fact Type fields the row carries, and
    which of those fields is the salient numeric value. An empty table (or a
    failed execution) yields zero facts -- empty is not an error.
    """
    if not result.success:
        return []
    rows = result.data.get(data_key)
    if not rows:
        return []
    context = parameters or {}
    facts: list[ReasoningFact] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        evidence = {name: row.get(source) for name, source in row_fields.items()}
        facts.append(
            ReasoningFact(
                fact_id=f"fact-{uuid.uuid4()}",
                agent_trace_id=agent_trace_id,
                trace_id=agent_trace_id,
                gateway_trace_id=result.trace_id,
                domain=domain,
                business_object=business_object,
                predicate=predicate,
                value=_optional_number(evidence.get(value_field)),
                unit=_optional_text(evidence.get(unit_field)),
                deterministic=True,
                confidence=1.0,
                source={
                    "capabilityId": result.capability_id,
                    "executorType": result.executor.get("type"),
                    "rfcName": result.executor.get("rfcName"),
                },
                evidence=[evidence],
                material=_optional_text(evidence.get("material") or context.get("material")),
                plant=_optional_text(context.get("plant")),
            )
        )
    return facts


def build_sales_order_facts(
    agent_trace_id: str,
    result: ExecutionResult,
    parameters: dict[str, str] | None = None,
) -> list[ReasoningFact]:
    """Normalise SD.SalesOrder.GetList rows into one Fact per sales order."""
    return _build_row_facts(
        agent_trace_id,
        result,
        parameters,
        data_key="salesOrders",
        domain="SD",
        business_object="SalesOrder",
        predicate="salesOrderItem",
        row_fields=_SALES_ORDER_ROW_FIELDS,
        value_field="netValue",
        unit_field="currency",
    )


def build_ar_open_items_facts(
    agent_trace_id: str,
    result: ExecutionResult,
    parameters: dict[str, str] | None = None,
) -> list[ReasoningFact]:
    """Normalise FI.AR.GetOpenItems rows into one Fact per customer open item."""
    return _build_row_facts(
        agent_trace_id,
        result,
        parameters,
        data_key="openItems",
        domain="FI",
        business_object="CustomerOpenItem",
        predicate="customerOpenItem",
        row_fields=_OPEN_ITEM_ROW_FIELDS,
        value_field="amount",
        unit_field="currency",
    )


def build_ap_open_items_facts(
    agent_trace_id: str,
    result: ExecutionResult,
    parameters: dict[str, str] | None = None,
) -> list[ReasoningFact]:
    """Normalise FI.AP.GetOpenItems rows into one Fact per vendor open item."""
    return _build_row_facts(
        agent_trace_id,
        result,
        parameters,
        data_key="openItems",
        domain="FI",
        business_object="VendorOpenItem",
        predicate="vendorOpenItem",
        row_fields=_OPEN_ITEM_ROW_FIELDS,
        value_field="amount",
        unit_field="currency",
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

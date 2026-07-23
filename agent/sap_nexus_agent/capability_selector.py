from __future__ import annotations

from dataclasses import dataclass

from sap_nexus_agent.intent import IntentParseResult


# Intent -> capabilityId closed set. The Agent never senses the executor type
# (JCO_RFC / ODATA); executor routing is the Gateway dispatcher's job.
INTENT_TO_CAPABILITY = {
    "inventory_availability": "MM.Inventory.GetAvailability",
    "purchase_order_list": "MM.PurchaseOrder.GetList",
    "pr_create": "MM.PR.CreateDraft",
}

# Inventory capability id, retained for the LLM path (still inventory-only until
# the orchestrator unified-entry refactor in Plan Task 10).
CAPABILITY_ID = "MM.Inventory.GetAvailability"


@dataclass(frozen=True)
class SelectionResult:
    capability_id: str | None
    error_type: str | None = None
    message: str | None = None


def select_capability(parse_result: IntentParseResult) -> SelectionResult:
    # Technical-override rejection (rfcName / OData injection) takes priority -
    # same semantics as the Java-side CapabilityRequest guard (Task 6).
    if parse_result.contains_rfc_name or parse_result.contains_odata_override:
        return SelectionResult(
            capability_id=None,
            error_type="UNSUPPORTED_RFC_NAME",
            message="Agent 不接受 rfcName 或 OData 技术覆盖，只能从已注册能力闭集选择。",
        )
    capability_id = parse_result.capability_id or INTENT_TO_CAPABILITY.get(parse_result.intent)
    if capability_id is None:
        return SelectionResult(
            capability_id=None,
            error_type="UNSUPPORTED_INTENT",
            message="当前仅支持已注册的能力（库存可用量查询、采购订单列表、采购申请草稿创建）。",
        )
    if parse_result.missing_parameters:
        return SelectionResult(
            capability_id=None,
            error_type="MISSING_PARAMETER",
            message=parse_result.clarification,
        )
    return SelectionResult(capability_id=capability_id)

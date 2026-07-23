package com.sapnexus.gateway.execution;

import com.sapnexus.gateway.registry.CapabilityDefinition;
import com.sapnexus.gateway.registry.CapabilityKind;
import com.sapnexus.gateway.registry.CapabilityStatus;
import com.sapnexus.gateway.registry.SideEffect;
import com.sapnexus.gateway.result.ExecutionResult;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

class TechnicalExecutionResultTest {

    @Test
    void toExecutionResultFillsRfcNameForJcoCapability() {
        TechnicalExecutionResult technicalResult = TechnicalExecutionResult.success(
                "trace-1",
                "MM.Inventory.GetAvailability",
                "sap.mm.inventory.md04-stock-req-list",
                "JCO_RFC",
                List.of(),
                Map.of("availableQuantity", 42),
                5,
                Map.of("rfcName", "BAPI_MATERIAL_STOCK_REQ_LIST")
        );
        CapabilityDefinition capability = jcoCapability();

        ExecutionResult result = technicalResult.toExecutionResult(capability);

        assertThat(result.success()).isTrue();
        assertThat(result.executor().type()).isEqualTo("JCO_RFC");
        assertThat(result.executor().rfcName()).isEqualTo("BAPI_MATERIAL_STOCK_REQ_LIST");
    }

    @Test
    void toExecutionResultNullsRfcNameForODataCapability() {
        TechnicalExecutionResult technicalResult = TechnicalExecutionResult.success(
                "trace-2",
                "MM.PurchaseOrder.GetList",
                "sap.mm.purchaseorder.list-odata",
                "ODATA",
                List.of(),
                Map.of("purchaseOrders", List.of()),
                10,
                Map.of()
        );
        CapabilityDefinition capability = odataCapability();

        ExecutionResult result = technicalResult.toExecutionResult(capability);

        assertThat(result.success()).isTrue();
        assertThat(result.executor().type()).isEqualTo("ODATA");
        assertThat(result.executor().rfcName()).isNull();
    }

    private static CapabilityDefinition jcoCapability() {
        return new CapabilityDefinition(
                "MM.Inventory.GetAvailability",
                "Inventory Availability",
                "Read material availability.",
                CapabilityStatus.active,
                CapabilityKind.Function,
                "MM",
                "InventoryStock",
                "sapnexus:MM_Inventory_GetAvailability",
                "sapnexus:InventoryAvailabilityReadFunction",
                List.of(),
                List.of(),
                new CapabilityDefinition.Executor("JCO_RFC", "BAPI_MATERIAL_STOCK_REQ_LIST", Map.of(), Map.of()),
                new CapabilityDefinition.ExecutorBinding("JCO_RFC", "sap.mm.inventory.md04-stock-req-list"),
                new CapabilityDefinition.Governance(SideEffect.none, false, "not_required", "internal", true)
        );
    }

    private static CapabilityDefinition odataCapability() {
        return new CapabilityDefinition(
                "MM.PurchaseOrder.GetList",
                "Purchase Order List",
                "List purchase orders via OData.",
                CapabilityStatus.active,
                CapabilityKind.Function,
                "MM",
                "PurchaseOrder",
                "sapnexus:MM_PurchaseOrder_GetList",
                "sapnexus:PurchaseOrderListFunction",
                List.of(),
                List.of(),
                new CapabilityDefinition.Executor("ODATA", null, Map.of(), Map.of()),
                new CapabilityDefinition.ExecutorBinding("ODATA", "sap.mm.purchaseorder.list-odata"),
                new CapabilityDefinition.Governance(SideEffect.none, false, "not_required", "internal", true)
        );
    }
}

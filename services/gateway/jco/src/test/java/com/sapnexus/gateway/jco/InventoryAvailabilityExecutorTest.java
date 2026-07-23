package com.sapnexus.gateway.jco;

import com.sap.conn.jco.JCoDestination;
import com.sap.conn.jco.JCoFunction;
import com.sap.conn.jco.JCoParameterList;
import com.sap.conn.jco.JCoRepository;
import com.sap.conn.jco.JCoTable;
import com.sapnexus.gateway.registry.CapabilityDefinition;
import com.sapnexus.gateway.registry.CapabilityKind;
import com.sapnexus.gateway.registry.CapabilityStatus;
import com.sapnexus.gateway.registry.SideEffect;
import com.sapnexus.gateway.result.ErrorType;
import com.sapnexus.gateway.result.ExecutionResult;
import com.sapnexus.gateway.result.SapReturnNormalizer;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.Mockito.doNothing;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class InventoryAvailabilityExecutorTest {
    @Test
    void stockRequirementListExtractsCurrentMd04StockRowAsAvailableQuantity() throws Exception {
        JCoDestination destination = mock(JCoDestination.class);
        JCoRepository repository = mock(JCoRepository.class);
        JCoFunction function = mock(JCoFunction.class);
        JCoParameterList imports = mock(JCoParameterList.class);
        JCoParameterList exports = mock(JCoParameterList.class);
        JCoParameterList tables = mock(JCoParameterList.class);
        JCoTable mrpLines = mock(JCoTable.class);
        AtomicInteger row = new AtomicInteger(0);

        when(destination.getRepository()).thenReturn(repository);
        when(repository.getFunction("BAPI_MATERIAL_STOCK_REQ_LIST")).thenReturn(function);
        when(function.getImportParameterList()).thenReturn(imports);
        when(function.getExportParameterList()).thenReturn(exports);
        when(function.getTableParameterList()).thenReturn(tables);
        doNothing().when(function).execute(destination);
        when(exports.isInitialized("RETURN")).thenReturn(false);
        when(tables.isInitialized("RETURN")).thenReturn(false);
        when(tables.isInitialized("MRP_IND_LINES")).thenReturn(true);
        when(tables.getTable("MRP_IND_LINES")).thenReturn(mrpLines);
        when(mrpLines.getNumRows()).thenReturn(2);
        doAnswer(invocation -> {
            row.set(invocation.getArgument(0));
            return null;
        }).when(mrpLines).setRow(anyInt());
        when(mrpLines.isInitialized(any())).thenReturn(true);
        when(mrpLines.getString("MRP_ELEMENT_IND")).thenAnswer(invocation -> row.get() == 0 ? "BE" : "WB");
        when(mrpLines.getString("MRP_ELEMNT")).thenAnswer(invocation -> row.get() == 0 ? "POitem" : "Stock");
        when(mrpLines.getString("AVAIL_QTY1")).thenAnswer(invocation -> row.get() == 0 ? "264.000" : "12.000");
        when(mrpLines.getString("AVAIL_DATE")).thenReturn("2026-06-21");

        InventoryAvailabilityExecutor executor = new InventoryAvailabilityExecutor(new FixedDestinationFactory(destination), new SapReturnNormalizer());

        ExecutionResult result = executor.execute(md04InventoryCapability(), Map.of("material", "DEMOA1", "plant", "1000"), "trace-md04");

        assertThat(result.success()).isTrue();
        assertThat(result.executor().rfcName()).isEqualTo("BAPI_MATERIAL_STOCK_REQ_LIST");
        assertThat(result.data()).containsEntry("availableQuantity", 12.0);
        assertThat(result.data()).containsEntry("sourceTable", "MRP_IND_LINES");
        assertThat(result.data()).containsEntry("sourceField", "AVAIL_QTY1");
        assertThat(result.data()).containsEntry("mrpElementInd", "WB");
    }

    @Test
    void missingReturnInTableParametersDoesNotFailExecution() throws Exception {
        JCoDestination destination = mock(JCoDestination.class);
        JCoRepository repository = mock(JCoRepository.class);
        JCoFunction function = mock(JCoFunction.class);
        JCoParameterList imports = mock(JCoParameterList.class);
        JCoParameterList exports = mock(JCoParameterList.class);
        JCoParameterList tables = mock(JCoParameterList.class);

        when(destination.getRepository()).thenReturn(repository);
        when(repository.getFunction("BAPI_MATERIAL_AVAILABILITY")).thenReturn(function);
        when(function.getImportParameterList()).thenReturn(imports);
        when(function.getExportParameterList()).thenReturn(exports);
        when(function.getTableParameterList()).thenReturn(tables);
        doNothing().when(function).execute(destination);
        when(exports.isInitialized("RETURN")).thenReturn(false);
        when(exports.isInitialized("AV_QTY_PLT")).thenReturn(false);
        when(tables.isInitialized("RETURN")).thenThrow(new RuntimeException("Field 'RETURN' is not a member of record 'TABLES'"));

        InventoryAvailabilityExecutor executor = new InventoryAvailabilityExecutor(new FixedDestinationFactory(destination), new SapReturnNormalizer());

        ExecutionResult result = executor.execute(inventoryCapability(), Map.of("material", "MAT-001", "plant", "1000"), "trace-1");

        assertThat(result.success()).isTrue();
        assertThat(result.errorType()).isEqualTo(ErrorType.NONE);
        assertThat(result.executor().rfcName()).isEqualTo("BAPI_MATERIAL_AVAILABILITY");
    }

    @Test
    void jcoFailureKeepsExecutorMetadataForSchemaCompatibility() throws Exception {
        JCoDestination destination = mock(JCoDestination.class);
        when(destination.getRepository()).thenThrow(new com.sap.conn.jco.JCoException(com.sap.conn.jco.JCoException.JCO_ERROR_COMMUNICATION, "network down"));

        InventoryAvailabilityExecutor executor = new InventoryAvailabilityExecutor(new FixedDestinationFactory(destination), new SapReturnNormalizer());

        ExecutionResult result = executor.execute(inventoryCapability(), Map.of("material", "MAT-001", "plant", "1000"), "trace-2");

        assertThat(result.success()).isFalse();
        assertThat(result.executor()).isNotNull();
        assertThat(result.executor().type()).isEqualTo("JCO_RFC");
        assertThat(result.executor().rfcName()).isEqualTo("BAPI_MATERIAL_AVAILABILITY");
    }

    private CapabilityDefinition inventoryCapability() {
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
                List.of(
                        new CapabilityDefinition.InputField("material", "materialNumber", "sapnexus:MaterialNumber", true, "string", 1, 40, "MATERIAL"),
                        new CapabilityDefinition.InputField("plant", "plant", "sapnexus:Plant", true, "string", 1, 4, "PLANT")
                ),
                List.of(),
                new CapabilityDefinition.Executor("JCO_RFC", "BAPI_MATERIAL_AVAILABILITY", Map.of("material", "MATERIAL", "plant", "PLANT"), Map.of("availableQuantity", "AV_QTY_PLT", "returnMessages", "RETURN")),
                new CapabilityDefinition.Governance(SideEffect.none, false, "not_required", "internal", true)
        );
    }

    private CapabilityDefinition md04InventoryCapability() {
        return new CapabilityDefinition(
                "MM.Inventory.GetAvailability",
                "Inventory Availability",
                "Read material availability from MD04 stock requirements list.",
                CapabilityStatus.active,
                CapabilityKind.Function,
                "MM",
                "InventoryStock",
                "sapnexus:MM_Inventory_GetAvailability",
                "sapnexus:InventoryAvailabilityReadFunction",
                List.of(
                        new CapabilityDefinition.InputField("material", "materialNumber", "sapnexus:MaterialNumber", true, "string", 1, 40, "MATERIAL_LONG"),
                        new CapabilityDefinition.InputField("plant", "plant", "sapnexus:Plant", true, "string", 1, 4, "PLANT")
                ),
                List.of(),
                new CapabilityDefinition.Executor("JCO_RFC", "BAPI_MATERIAL_STOCK_REQ_LIST", Map.of("material", "MATERIAL_LONG", "plant", "PLANT"), Map.of("availableQuantity", "MRP_IND_LINES.WB.AVAIL_QTY1", "returnMessages", "RETURN")),
                new CapabilityDefinition.Governance(SideEffect.none, false, "not_required", "internal", true)
        );
    }

    static class FixedDestinationFactory extends JcoDestinationFactory {
        private final JCoDestination destination;

        FixedDestinationFactory(JCoDestination destination) {
            this.destination = destination;
        }

        @Override
        public JCoDestination getDestination() {
            return destination;
        }
    }
}

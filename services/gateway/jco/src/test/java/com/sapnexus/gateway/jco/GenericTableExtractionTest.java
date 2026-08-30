package com.sapnexus.gateway.jco;

import com.sap.conn.jco.JCoDestination;
import com.sap.conn.jco.JCoFunction;
import com.sap.conn.jco.JCoParameterList;
import com.sap.conn.jco.JCoRecordMetaData;
import com.sap.conn.jco.JCoRepository;
import com.sap.conn.jco.JCoTable;
import com.sapnexus.gateway.registry.CapabilityDefinition;
import com.sapnexus.gateway.registry.CapabilityKind;
import com.sapnexus.gateway.registry.CapabilityStatus;
import com.sapnexus.gateway.registry.SideEffect;
import com.sapnexus.gateway.result.ExecutionResult;
import com.sapnexus.gateway.result.SapReturnNormalizer;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.doNothing;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * Generic TABLES extraction: a capability whose primary fact is a table is read from
 * its {@code outputMapping} and the table's own JCo metadata.
 * <p>
 * Before this, the only TABLES parameter the read executor could see was MD04's
 * {@code MRP_IND_LINES}, through a method that hardcoded that table name and five
 * field names. Registering SD.SalesOrder.GetList and FI.AR/AP.GetOpenItems would then
 * have meant three more such methods, i.e. capability behavior living in Java instead
 * of in the registry.
 */
class GenericTableExtractionTest {
    @Test
    void aDeclaredTableOutputYieldsOneRowMapPerRowWithEveryColumn() throws Exception {
        JCoDestination destination = mock(JCoDestination.class);
        JCoRepository repository = mock(JCoRepository.class);
        JCoFunction function = mock(JCoFunction.class);
        JCoParameterList imports = mock(JCoParameterList.class);
        JCoParameterList exports = mock(JCoParameterList.class);
        JCoParameterList tables = mock(JCoParameterList.class);
        JCoTable salesOrders = mock(JCoTable.class);
        AtomicInteger row = new AtomicInteger(0);

        when(destination.getRepository()).thenReturn(repository);
        when(repository.getFunction("BAPI_SALESORDER_GETLIST")).thenReturn(function);
        when(function.getImportParameterList()).thenReturn(imports);
        when(function.getExportParameterList()).thenReturn(exports);
        when(function.getTableParameterList()).thenReturn(tables);
        doNothing().when(function).execute(destination);
        when(exports.isInitialized("RETURN")).thenReturn(false);
        when(exports.isInitialized("SALES_ORDERS")).thenReturn(false);
        when(tables.isInitialized("RETURN")).thenReturn(false);
        when(tables.isInitialized("SALES_ORDERS")).thenReturn(true);
        when(tables.getTable("SALES_ORDERS")).thenReturn(salesOrders);
        JCoRecordMetaData salesOrderMetaData =
                metaData("SD_DOC", "DOC_TYPE", "DOC_DATE", "SOLD_TO", "NET_VALUE", "CURRENCY", "PURCH_NO_C");
        when(salesOrders.getRecordMetaData()).thenReturn(salesOrderMetaData);
        when(salesOrders.getNumRows()).thenReturn(2);
        doAnswer(invocation -> {
            row.set(invocation.getArgument(0));
            return null;
        }).when(salesOrders).setRow(anyInt());
        when(salesOrders.isInitialized(any())).thenReturn(true);
        when(salesOrders.getString("SD_DOC")).thenAnswer(invocation -> row.get() == 0 ? "0000004711" : "0000004712");
        when(salesOrders.getString("DOC_TYPE")).thenReturn("OR");
        when(salesOrders.getString("DOC_DATE")).thenReturn("2026-08-01");
        when(salesOrders.getString("SOLD_TO")).thenReturn("1000");
        when(salesOrders.getString("NET_VALUE")).thenAnswer(invocation -> row.get() == 0 ? "1500.00" : "250.50");
        when(salesOrders.getString("CURRENCY")).thenReturn("EUR");
        when(salesOrders.getString("PURCH_NO_C")).thenReturn("CUSTPO-1");

        InventoryAvailabilityExecutor executor = new InventoryAvailabilityExecutor(
                new FixedDestinationFactory(destination), new SapReturnNormalizer());

        ExecutionResult result = executor.execute(
                salesOrderGetListCapability(), Map.of("customerNumber", "1000"), "trace-so");

        assertThat(result.success()).isTrue();
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> rows = (List<Map<String, Object>>) result.data().get("salesOrders");
        assertThat(rows).hasSize(2);
        // Keys are the camelCase form of the SAP column, and every column the table
        // metadata reports is present -- no hardcoded field list to fall behind.
        assertThat(rows.get(0)).containsOnlyKeys(
                "sdDoc", "docType", "docDate", "soldTo", "netValue", "currency", "purchNoC");
        assertThat(rows.get(0)).containsEntry("sdDoc", "0000004711");
        assertThat(rows.get(0)).containsEntry("netValue", "1500.00");
        assertThat(rows.get(0)).containsEntry("purchNoC", "CUSTPO-1");
        assertThat(rows.get(1)).containsEntry("sdDoc", "0000004712");
        assertThat(rows.get(1)).containsEntry("netValue", "250.50");
    }

    @Test
    void theOpenItemTableIsReadUnderTheDeclaredOutputNameNotTheSapTableName() throws Exception {
        // The registry maps openItems -> LINEITEMS (BAPI_AR_ACC_GETOPENITEMS returns
        // LINEITEMS, not OPENITEMS). The Agent must receive the declared output name.
        JCoDestination destination = mock(JCoDestination.class);
        JCoRepository repository = mock(JCoRepository.class);
        JCoFunction function = mock(JCoFunction.class);
        JCoParameterList imports = mock(JCoParameterList.class);
        JCoParameterList exports = mock(JCoParameterList.class);
        JCoParameterList tables = mock(JCoParameterList.class);
        JCoTable lineItems = mock(JCoTable.class);

        when(destination.getRepository()).thenReturn(repository);
        when(repository.getFunction("BAPI_AR_ACC_GETOPENITEMS")).thenReturn(function);
        when(function.getImportParameterList()).thenReturn(imports);
        when(function.getExportParameterList()).thenReturn(exports);
        when(function.getTableParameterList()).thenReturn(tables);
        doNothing().when(function).execute(destination);
        when(exports.isInitialized("RETURN")).thenReturn(false);
        when(exports.isInitialized("LINEITEMS")).thenReturn(false);
        when(tables.isInitialized("RETURN")).thenReturn(false);
        when(tables.isInitialized("LINEITEMS")).thenReturn(true);
        when(tables.getTable("LINEITEMS")).thenReturn(lineItems);
        JCoRecordMetaData lineItemMetaData =
                metaData("DOC_NO", "AMT_DOCCUR", "CURRENCY", "BLINE_DATE", "CLEAR_DATE");
        when(lineItems.getRecordMetaData()).thenReturn(lineItemMetaData);
        when(lineItems.getNumRows()).thenReturn(1);
        doNothing().when(lineItems).setRow(anyInt());
        when(lineItems.isInitialized(any())).thenReturn(true);
        when(lineItems.getString("DOC_NO")).thenReturn("1800000001");
        when(lineItems.getString("AMT_DOCCUR")).thenReturn("2500.00");
        when(lineItems.getString("CURRENCY")).thenReturn("EUR");
        when(lineItems.getString("BLINE_DATE")).thenReturn("2026-07-15");
        when(lineItems.getString("CLEAR_DATE")).thenReturn("");

        InventoryAvailabilityExecutor executor = new InventoryAvailabilityExecutor(
                new FixedDestinationFactory(destination), new SapReturnNormalizer());

        ExecutionResult result = executor.execute(
                arOpenItemsCapability(), Map.of("customer", "1000", "companyCode", "1000"), "trace-ar");

        assertThat(result.success()).isTrue();
        assertThat(result.data()).doesNotContainKey("LINEITEMS");
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> rows = (List<Map<String, Object>>) result.data().get("openItems");
        assertThat(rows).hasSize(1);
        assertThat(rows.get(0)).containsEntry("docNo", "1800000001");
        assertThat(rows.get(0)).containsEntry("amtDoccur", "2500.00");
        assertThat(rows.get(0)).containsEntry("blineDate", "2026-07-15");
        // An open item is open: the blank clearing date is carried, not dropped.
        assertThat(rows.get(0)).containsEntry("clearDate", "");
    }

    @Test
    void anEmptyDeclaredTableYieldsAnEmptyListRatherThanNoKey() throws Exception {
        JCoDestination destination = mock(JCoDestination.class);
        JCoRepository repository = mock(JCoRepository.class);
        JCoFunction function = mock(JCoFunction.class);
        JCoParameterList imports = mock(JCoParameterList.class);
        JCoParameterList exports = mock(JCoParameterList.class);
        JCoParameterList tables = mock(JCoParameterList.class);
        JCoTable lineItems = mock(JCoTable.class);

        when(destination.getRepository()).thenReturn(repository);
        when(repository.getFunction("BAPI_AR_ACC_GETOPENITEMS")).thenReturn(function);
        when(function.getImportParameterList()).thenReturn(imports);
        when(function.getExportParameterList()).thenReturn(exports);
        when(function.getTableParameterList()).thenReturn(tables);
        doNothing().when(function).execute(destination);
        when(exports.isInitialized("RETURN")).thenReturn(false);
        when(exports.isInitialized("LINEITEMS")).thenReturn(false);
        when(tables.isInitialized("RETURN")).thenReturn(false);
        when(tables.isInitialized("LINEITEMS")).thenReturn(true);
        when(tables.getTable("LINEITEMS")).thenReturn(lineItems);
        JCoRecordMetaData emptyTableMetaData = metaData("DOC_NO");
        when(lineItems.getRecordMetaData()).thenReturn(emptyTableMetaData);
        when(lineItems.getNumRows()).thenReturn(0);

        InventoryAvailabilityExecutor executor = new InventoryAvailabilityExecutor(
                new FixedDestinationFactory(destination), new SapReturnNormalizer());

        ExecutionResult result = executor.execute(
                arOpenItemsCapability(), Map.of("customer", "1000", "companyCode", "1000"), "trace-ar-empty");

        assertThat(result.success()).isTrue();
        assertThat(result.data()).containsEntry("openItems", List.of());
    }

    @Test
    void aDeclaredTableTheReleaseDoesNotExposeLeavesTheReadSuccessful() throws Exception {
        JCoDestination destination = mock(JCoDestination.class);
        JCoRepository repository = mock(JCoRepository.class);
        JCoFunction function = mock(JCoFunction.class);
        JCoParameterList imports = mock(JCoParameterList.class);
        JCoParameterList exports = mock(JCoParameterList.class);
        JCoParameterList tables = mock(JCoParameterList.class);

        when(destination.getRepository()).thenReturn(repository);
        when(repository.getFunction("BAPI_AR_ACC_GETOPENITEMS")).thenReturn(function);
        when(function.getImportParameterList()).thenReturn(imports);
        when(function.getExportParameterList()).thenReturn(exports);
        when(function.getTableParameterList()).thenReturn(tables);
        doNothing().when(function).execute(destination);
        when(exports.isInitialized("RETURN")).thenReturn(false);
        when(exports.isInitialized("LINEITEMS")).thenReturn(false);
        when(tables.isInitialized("RETURN")).thenReturn(false);
        when(tables.isInitialized("LINEITEMS"))
                .thenThrow(new RuntimeException("Field 'LINEITEMS' is not a member of record 'TABLES'"));

        InventoryAvailabilityExecutor executor = new InventoryAvailabilityExecutor(
                new FixedDestinationFactory(destination), new SapReturnNormalizer());

        ExecutionResult result = executor.execute(
                arOpenItemsCapability(), Map.of("customer", "1000", "companyCode", "1000"), "trace-ar-absent");

        assertThat(result.success()).isTrue();
        assertThat(result.data()).doesNotContainKey("openItems");
    }

    @Test
    void md04KeepsItsOwnExtractionBecauseNoCapabilityDeclaresThatTable() throws Exception {
        // Regression boundary for MM.Inventory.GetAvailability: MRP_IND_LINES is not in
        // any outputMapping, so the generic path must not touch it and the scalar
        // availableQuantity derived from the running stock row must stay.
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
        when(exports.isInitialized("AV_QTY_PLT")).thenReturn(false);
        when(tables.isInitialized("RETURN")).thenReturn(false);
        when(tables.isInitialized("AV_QTY_PLT")).thenReturn(false);
        when(tables.isInitialized("MRP_IND_LINES")).thenReturn(true);
        when(tables.getTable("MRP_IND_LINES")).thenReturn(mrpLines);
        when(mrpLines.getNumRows()).thenReturn(1);
        doAnswer(invocation -> {
            row.set(invocation.getArgument(0));
            return null;
        }).when(mrpLines).setRow(anyInt());
        when(mrpLines.isInitialized(any())).thenReturn(true);
        when(mrpLines.getString("MRP_ELEMENT_IND")).thenReturn("WB");
        when(mrpLines.getString("MRP_ELEMNT")).thenReturn("Stock");
        when(mrpLines.getString("AVAIL_QTY1")).thenReturn("12.000");
        when(mrpLines.getString("ELEMENT_QTY")).thenReturn("12.000");
        when(mrpLines.getString("AVAIL_DATE")).thenReturn("2026-06-21");

        InventoryAvailabilityExecutor executor = new InventoryAvailabilityExecutor(
                new FixedDestinationFactory(destination), new SapReturnNormalizer());

        ExecutionResult result = executor.execute(
                md04Capability(), Map.of("material", "DEMOA1", "plant", "1000"), "trace-md04-generic");

        assertThat(result.success()).isTrue();
        assertThat(result.data()).containsEntry("availableQuantity", 12.0);
        assertThat(result.data()).containsEntry("sourceTable", "MRP_IND_LINES");
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> elementLines = (List<Map<String, Object>>) result.data().get("mrpElementLines");
        assertThat(elementLines).hasSize(1);
        // The MD04 rows keep their bespoke keys and parsed quantities.
        assertThat(elementLines.get(0)).containsEntry("availQty1", 12.0);
    }

    private JCoRecordMetaData metaData(String... fieldNames) {
        JCoRecordMetaData metaData = mock(JCoRecordMetaData.class);
        when(metaData.getFieldCount()).thenReturn(fieldNames.length);
        for (int index = 0; index < fieldNames.length; index++) {
            when(metaData.getName(index)).thenReturn(fieldNames[index]);
        }
        return metaData;
    }

    private CapabilityDefinition salesOrderGetListCapability() {
        return new CapabilityDefinition(
                "SD.SalesOrder.GetList",
                "Sales Order List",
                "Read a VA05-style list of sales orders.",
                CapabilityStatus.active,
                CapabilityKind.Function,
                "SD",
                "SalesOrder",
                "sapnexus:SD_SalesOrder_GetList",
                "sapnexus:SalesOrderListReadFunction",
                List.of(
                        new CapabilityDefinition.InputField(
                                "customerNumber", "customerNumber", "sapnexus:CustomerNumber",
                                false, "string", 1, 10, "CUSTOMER_NUMBER")
                ),
                List.of(),
                new CapabilityDefinition.Executor(
                        "JCO_RFC",
                        "BAPI_SALESORDER_GETLIST",
                        Map.of("customerNumber", "CUSTOMER_NUMBER"),
                        Map.of("salesOrders", "SALES_ORDERS", "returnMessages", "RETURN")),
                new CapabilityDefinition.Governance(SideEffect.none, false, "not_required", "internal", true)
        );
    }

    private CapabilityDefinition arOpenItemsCapability() {
        return new CapabilityDefinition(
                "FI.AR.GetOpenItems",
                "Customer Open Items",
                "Read customer open items for a company code.",
                CapabilityStatus.active,
                CapabilityKind.Function,
                "FI",
                "CustomerOpenItem",
                "sapnexus:FI_AR_GetOpenItems",
                "sapnexus:CustomerOpenItemsReadFunction",
                List.of(
                        new CapabilityDefinition.InputField(
                                "customer", "customerNumber", "sapnexus:CustomerNumber",
                                true, "string", 1, 10, "CUSTOMER"),
                        new CapabilityDefinition.InputField(
                                "companyCode", "companyCode", "sapnexus:CompanyCode",
                                true, "string", 1, 4, "COMPANYCODE")
                ),
                List.of(),
                new CapabilityDefinition.Executor(
                        "JCO_RFC",
                        "BAPI_AR_ACC_GETOPENITEMS",
                        Map.of("customer", "CUSTOMER", "companyCode", "COMPANYCODE"),
                        Map.of("openItems", "LINEITEMS", "returnMessages", "RETURN")),
                new CapabilityDefinition.Governance(SideEffect.none, false, "not_required", "internal", true)
        );
    }

    private CapabilityDefinition md04Capability() {
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
                        new CapabilityDefinition.InputField(
                                "material", "materialNumber", "sapnexus:MaterialNumber",
                                true, "string", 1, 40, "MATERIAL"),
                        new CapabilityDefinition.InputField(
                                "plant", "plant", "sapnexus:Plant", true, "string", 1, 4, "PLANT")
                ),
                List.of(),
                new CapabilityDefinition.Executor(
                        "JCO_RFC",
                        "BAPI_MATERIAL_STOCK_REQ_LIST",
                        Map.of("material", "MATERIAL", "plant", "PLANT"),
                        Map.of("availableQuantity", "AV_QTY_PLT", "returnMessages", "RETURN")),
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

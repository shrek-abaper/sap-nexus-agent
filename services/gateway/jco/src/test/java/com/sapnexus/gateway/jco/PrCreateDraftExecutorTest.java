package com.sapnexus.gateway.jco;

import com.sap.conn.jco.JCoDestination;
import com.sap.conn.jco.JCoContext;
import com.sap.conn.jco.JCoException;
import com.sap.conn.jco.JCoFunction;
import com.sap.conn.jco.JCoMetaData;
import com.sap.conn.jco.JCoParameterList;
import com.sap.conn.jco.JCoRepository;
import com.sap.conn.jco.JCoStructure;
import com.sap.conn.jco.JCoTable;
import com.sapnexus.gateway.registry.CapabilityDefinition;
import com.sapnexus.gateway.registry.CapabilityKind;
import com.sapnexus.gateway.registry.CapabilityStatus;
import com.sapnexus.gateway.registry.SideEffect;
import com.sapnexus.gateway.result.ErrorType;
import com.sapnexus.gateway.result.ExecutionResult;
import com.sapnexus.gateway.result.SapReturnNormalizer;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.mockito.MockedStatic;

import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doNothing;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class PrCreateDraftExecutorTest {

    private static final String PR_CREATE = "BAPI_PR_CREATE";
    private static final String COMMIT = "BAPI_TRANSACTION_COMMIT";
    private static final String ROLLBACK = "BAPI_TRANSACTION_ROLLBACK";

    @Test
    void successCommitsAndExtractsPrNumber() throws Exception {
        JCoDestination destination = mock(JCoDestination.class);
        JCoRepository repository = mock(JCoRepository.class);
        JCoFunction prFunction = mock(JCoFunction.class);
        JCoFunction commitFunction = mock(JCoFunction.class);
        JCoParameterList imports = mock(JCoParameterList.class);
        JCoParameterList exports = mock(JCoParameterList.class);
        JCoParameterList tables = mock(JCoParameterList.class);
        JCoParameterList commitImports = mock(JCoParameterList.class);
        JCoMetaData importMetaData = mock(JCoMetaData.class);
        JCoMetaData exportMetaData = mock(JCoMetaData.class);
        JCoMetaData tableMetaData = mock(JCoMetaData.class);
        JCoMetaData prItemMetaData = mock(JCoMetaData.class);
        JCoMetaData prItemXMetaData = mock(JCoMetaData.class);
        JCoStructure prHeader = mock(JCoStructure.class);
        JCoStructure prHeaderX = mock(JCoStructure.class);
        JCoTable returnTable = mock(JCoTable.class);
        JCoTable prItemTable = mock(JCoTable.class);
        JCoTable prItemXTable = mock(JCoTable.class);
        JCoTable prItemExpTable = mock(JCoTable.class);

        when(destination.getRepository()).thenReturn(repository);
        when(repository.getFunction(PR_CREATE)).thenReturn(prFunction);
        when(repository.getFunction(COMMIT)).thenReturn(commitFunction);
        when(prFunction.getImportParameterList()).thenReturn(imports);
        when(prFunction.getExportParameterList()).thenReturn(exports);
        when(prFunction.getTableParameterList()).thenReturn(tables);
        when(imports.getMetaData()).thenReturn(importMetaData);
        when(importMetaData.indexOf(anyString())).thenReturn(-1);
        when(importMetaData.indexOf("PRHEADER")).thenReturn(0);
        when(importMetaData.indexOf("PRHEADERX")).thenReturn(1);
        when(imports.getStructure("PRHEADER")).thenReturn(prHeader);
        when(imports.getStructure("PRHEADERX")).thenReturn(prHeaderX);
        when(exports.getMetaData()).thenReturn(exportMetaData);
        when(exportMetaData.indexOf(anyString())).thenReturn(-1);
        when(exportMetaData.indexOf("NUMBER")).thenReturn(0);
        when(exports.isInitialized("NUMBER")).thenReturn(true);
        when(exports.getString("NUMBER")).thenReturn("10137471");
        when(tables.getMetaData()).thenReturn(tableMetaData);
        when(tableMetaData.indexOf(anyString())).thenReturn(-1);
        when(tableMetaData.indexOf("PRITEM")).thenReturn(0);
        when(tableMetaData.indexOf("PRITEMX")).thenReturn(1);
        doNothing().when(prFunction).execute(destination);
        when(tables.isInitialized("RETURN")).thenReturn(true);
        when(tables.isInitialized("PRITEM")).thenReturn(false);
        when(tables.isInitialized("PRITEMEXP")).thenReturn(true);
        when(tables.getTable("RETURN")).thenReturn(returnTable);
        when(tables.getTable("PRITEM")).thenReturn(prItemTable);
        when(tables.getTable("PRITEMX")).thenReturn(prItemXTable);
        when(tables.getTable("PRITEMEXP")).thenReturn(prItemExpTable);
        when(prItemTable.getMetaData()).thenReturn(prItemMetaData);
        when(prItemMetaData.hasField(anyString())).thenReturn(false);
        when(prItemMetaData.hasField("PREQ_ITEM")).thenReturn(true);
        when(prItemMetaData.hasField("MATERIAL")).thenReturn(true);
        when(prItemMetaData.hasField("PLANT")).thenReturn(true);
        when(prItemMetaData.hasField("QUANTITY")).thenReturn(true);
        when(prItemMetaData.hasField("UNIT")).thenReturn(true);
        when(prItemMetaData.hasField("DELIV_DATE")).thenReturn(true);
        when(prItemMetaData.hasField("PUR_GROUP")).thenReturn(true);
        when(prItemXTable.getMetaData()).thenReturn(prItemXMetaData);
        when(prItemXMetaData.hasField(anyString())).thenReturn(false);
        when(prItemXMetaData.hasField("PREQ_ITEM")).thenReturn(true);
        when(prItemXMetaData.hasField("PREQ_ITEMX")).thenReturn(true);
        when(prItemXMetaData.hasField("MATERIAL")).thenReturn(true);
        when(prItemXMetaData.hasField("PLANT")).thenReturn(true);
        when(prItemXMetaData.hasField("QUANTITY")).thenReturn(true);
        when(prItemXMetaData.hasField("UNIT")).thenReturn(true);
        when(prItemXMetaData.hasField("DELIV_DATE")).thenReturn(true);
        when(prItemXMetaData.hasField("PUR_GROUP")).thenReturn(true);
        when(returnTable.getNumRows()).thenReturn(1);
        when(returnTable.isInitialized(any())).thenReturn(true);
        when(returnTable.getString("TYPE")).thenReturn("S");
        when(returnTable.getString("ID")).thenReturn("M06");
        when(returnTable.getString("NUMBER")).thenReturn("017");
        when(returnTable.getString("MESSAGE")).thenReturn("PR created");
        when(returnTable.getString("FIELD")).thenReturn("");
        when(prItemExpTable.getNumRows()).thenReturn(1);
        when(prItemExpTable.isInitialized(any())).thenReturn(true);
        when(prItemExpTable.getString("PREQ_NO")).thenReturn("");
        when(commitFunction.getImportParameterList()).thenReturn(commitImports);
        when(commitFunction.getExportParameterList()).thenReturn(null);
        doNothing().when(commitFunction).execute(destination);

        PrCreateDraftExecutor executor = new PrCreateDraftExecutor(
                new FixedDestinationFactory(destination), new SapReturnNormalizer());

        ExecutionResult result = executeWithContext(
                executor, destination, Map.of(
                        "material", "DEMOA1",
                        "plant", "1000",
                        "quantity", "10",
                        "unit", "EA",
                        "delivery_date", "2026-08-15",
                        "purchasing_group", "601"
                ), "trace-001");

        assertThat(result.success()).isTrue();
        assertThat(result.errorType()).isEqualTo(ErrorType.NONE);
        assertThat(result.data()).containsEntry("prNumber", "10137471");
        assertThat(result.data()).containsEntry("commitStatus", "committed");
        verify(prHeader).setValue("PR_TYPE", "NB");
        verify(prHeaderX).setValue("PR_TYPE", "X");
        verify(prItemTable).appendRow();
        verify(prItemTable).setValue("PREQ_ITEM", (Object) "00010");
        verify(prItemTable).setValue("MATERIAL", (Object) "DEMOA1");
        verify(prItemTable).setValue("PLANT", (Object) "1000");
        verify(prItemTable).setValue("QUANTITY", (Object) "10");
        verify(prItemTable).setValue("UNIT", (Object) "EA");
        ArgumentCaptor<Object> deliveryDate = ArgumentCaptor.forClass(Object.class);
        verify(prItemTable).setValue(eq("DELIV_DATE"), deliveryDate.capture());
        assertThat(deliveryDate.getValue()).isInstanceOf(java.sql.Date.class);
        assertThat(deliveryDate.getValue().toString()).isEqualTo("2026-08-15");
        verify(prItemTable).setValue("PUR_GROUP", (Object) "601");
        verify(prItemXTable).appendRow();
        verify(prItemXTable).setValue("PREQ_ITEM", (Object) "00010");
        verify(prItemXTable).setValue("PREQ_ITEMX", (Object) "X");
        verify(prItemXTable).setValue("MATERIAL", (Object) "X");
        verify(prItemXTable).setValue("PLANT", (Object) "X");
        verify(prItemXTable).setValue("QUANTITY", (Object) "X");
        verify(prItemXTable).setValue("UNIT", (Object) "X");
        verify(prItemXTable).setValue("DELIV_DATE", (Object) "X");
        verify(prItemXTable).setValue("PUR_GROUP", (Object) "X");
        verify(prFunction).execute(destination);
        verify(commitFunction).execute(destination);
        verify(repository, never()).getFunction(ROLLBACK);
    }

    @Test
    void businessErrorRollsBackAndSkipsCommit() throws Exception {
        JCoDestination destination = mock(JCoDestination.class);
        JCoRepository repository = mock(JCoRepository.class);
        JCoFunction prFunction = mock(JCoFunction.class);
        JCoFunction commitFunction = mock(JCoFunction.class);
        JCoFunction rollbackFunction = mock(JCoFunction.class);
        JCoParameterList tables = mock(JCoParameterList.class);
        JCoTable returnTable = mock(JCoTable.class);

        when(destination.getRepository()).thenReturn(repository);
        when(repository.getFunction(PR_CREATE)).thenReturn(prFunction);
        when(repository.getFunction(COMMIT)).thenReturn(commitFunction);
        when(repository.getFunction(ROLLBACK)).thenReturn(rollbackFunction);
        when(prFunction.getImportParameterList()).thenReturn(mock(JCoParameterList.class));
        when(prFunction.getTableParameterList()).thenReturn(tables);
        doNothing().when(prFunction).execute(destination);
        when(tables.isInitialized("RETURN")).thenReturn(true);
        when(tables.getTable("RETURN")).thenReturn(returnTable);
        when(returnTable.getNumRows()).thenReturn(1);
        when(returnTable.isInitialized(any())).thenReturn(true);
        when(returnTable.getString("TYPE")).thenReturn("E");
        when(returnTable.getString("MESSAGE")).thenReturn("Material not found");
        doNothing().when(rollbackFunction).execute(destination);

        PrCreateDraftExecutor executor = new PrCreateDraftExecutor(
                new FixedDestinationFactory(destination), new SapReturnNormalizer());

        ExecutionResult result = executeWithContext(
                executor, destination, Map.of("material", "INVALID"), "trace-002");

        assertThat(result.success()).isFalse();
        assertThat(result.errorType()).isEqualTo(ErrorType.SAP_BUSINESS_ERROR);
        assertThat(result.data()).containsEntry("commitStatus", "rolled_back");
        verify(prFunction).execute(destination);
        verify(rollbackFunction).execute(destination);
        verify(commitFunction, never()).execute(any());
    }

    @Test
    void commitFailureRollsBackAsFallback() throws Exception {
        JCoDestination destination = mock(JCoDestination.class);
        JCoRepository repository = mock(JCoRepository.class);
        JCoFunction prFunction = mock(JCoFunction.class);
        JCoFunction commitFunction = mock(JCoFunction.class);
        JCoFunction rollbackFunction = mock(JCoFunction.class);
        JCoParameterList tables = mock(JCoParameterList.class);
        JCoParameterList commitImports = mock(JCoParameterList.class);
        JCoParameterList commitExports = mock(JCoParameterList.class);
        JCoStructure commitReturn = mock(JCoStructure.class);
        JCoTable returnTable = mock(JCoTable.class);

        when(destination.getRepository()).thenReturn(repository);
        when(repository.getFunction(PR_CREATE)).thenReturn(prFunction);
        when(repository.getFunction(COMMIT)).thenReturn(commitFunction);
        when(repository.getFunction(ROLLBACK)).thenReturn(rollbackFunction);
        when(prFunction.getImportParameterList()).thenReturn(mock(JCoParameterList.class));
        when(prFunction.getTableParameterList()).thenReturn(tables);
        doNothing().when(prFunction).execute(destination);
        when(tables.isInitialized("RETURN")).thenReturn(true);
        when(tables.getTable("RETURN")).thenReturn(returnTable);
        when(returnTable.getNumRows()).thenReturn(1);
        when(returnTable.isInitialized(any())).thenReturn(true);
        when(returnTable.getString("TYPE")).thenReturn("S");
        when(returnTable.getString("MESSAGE")).thenReturn("PR created");
        when(commitFunction.getImportParameterList()).thenReturn(commitImports);
        when(commitFunction.getExportParameterList()).thenReturn(commitExports);
        doNothing().when(commitFunction).execute(destination);
        when(commitExports.isInitialized("RETURN")).thenReturn(true);
        when(commitExports.getStructure("RETURN")).thenReturn(commitReturn);
        when(commitReturn.isInitialized(any())).thenReturn(true);
        when(commitReturn.getString("TYPE")).thenReturn("E");
        when(commitReturn.getString("MESSAGE")).thenReturn("Commit failed");
        doNothing().when(rollbackFunction).execute(destination);

        PrCreateDraftExecutor executor = new PrCreateDraftExecutor(
                new FixedDestinationFactory(destination), new SapReturnNormalizer());

        ExecutionResult result = executeWithContext(
                executor, destination, Map.of("material", "M001"), "trace-003");

        assertThat(result.success()).isFalse();
        assertThat(result.errorType()).isEqualTo(ErrorType.SAP_COMMIT_ERROR);
        assertThat(result.data()).containsEntry("commitStatus", "rolled_back");
        verify(commitFunction).execute(destination);
        verify(rollbackFunction).execute(destination);
    }

    @Test
    void businessErrorReportsRollbackFailure() throws Exception {
        JCoDestination destination = mock(JCoDestination.class);
        JCoRepository repository = mock(JCoRepository.class);
        JCoFunction prFunction = mock(JCoFunction.class);
        JCoFunction rollbackFunction = mock(JCoFunction.class);
        JCoParameterList tables = mock(JCoParameterList.class);
        JCoTable returnTable = mock(JCoTable.class);

        when(destination.getRepository()).thenReturn(repository);
        when(repository.getFunction(PR_CREATE)).thenReturn(prFunction);
        when(repository.getFunction(ROLLBACK)).thenReturn(rollbackFunction);
        when(prFunction.getImportParameterList()).thenReturn(mock(JCoParameterList.class));
        when(prFunction.getTableParameterList()).thenReturn(tables);
        doNothing().when(prFunction).execute(destination);
        when(tables.isInitialized("RETURN")).thenReturn(true);
        when(tables.getTable("RETURN")).thenReturn(returnTable);
        when(returnTable.getNumRows()).thenReturn(1);
        when(returnTable.isInitialized(any())).thenReturn(true);
        when(returnTable.getString("TYPE")).thenReturn("E");
        when(returnTable.getString("MESSAGE")).thenReturn("Material not found");
        org.mockito.Mockito.doThrow(new RuntimeException("rollback failed"))
                .when(rollbackFunction).execute(destination);

        PrCreateDraftExecutor executor = new PrCreateDraftExecutor(
                new FixedDestinationFactory(destination), new SapReturnNormalizer());

        ExecutionResult result = executeWithContext(
                executor, destination, Map.of("material", "INVALID"), "trace-rollback-failed");

        assertThat(result.success()).isFalse();
        assertThat(result.errorType()).isEqualTo(ErrorType.SAP_BUSINESS_ERROR);
        assertThat(result.data()).containsEntry("commitStatus", "rollback_failed");
        verify(rollbackFunction).execute(destination);
    }

    @Test
    void commitExecutionExceptionRollsBackInSameContext() throws Exception {
        CommitPhaseFailure failure = executeCommitPhaseFailure(false, false);
        ExecutionResult result = failure.result();

        assertThat(result.success()).isFalse();
        assertThat(result.errorType()).isEqualTo(ErrorType.SAP_COMMIT_ERROR);
        assertThat(result.data()).containsEntry("commitStatus", "rolled_back");
        verify(failure.rollbackFunction()).execute(failure.destination());
    }

    @Test
    void missingCommitFunctionRollsBackInSameContext() throws Exception {
        CommitPhaseFailure failure = executeCommitPhaseFailure(true, false);

        assertThat(failure.result().errorType()).isEqualTo(ErrorType.SAP_COMMIT_ERROR);
        assertThat(failure.result().data()).containsEntry("commitStatus", "rolled_back");
        verify(failure.rollbackFunction()).execute(failure.destination());
    }

    @Test
    void commitPhaseRollbackFailureIsExplicit() throws Exception {
        CommitPhaseFailure failure = executeCommitPhaseFailure(false, true);

        assertThat(failure.result().errorType()).isEqualTo(ErrorType.SAP_COMMIT_ERROR);
        assertThat(failure.result().data()).containsEntry("commitStatus", "rollback_failed");
        verify(failure.rollbackFunction()).execute(failure.destination());
    }

    @Test
    void postCommitResultExtractionFailureKeepsCommittedTruth() throws Exception {
        JCoDestination destination = mock(JCoDestination.class);
        JCoRepository repository = mock(JCoRepository.class);
        JCoFunction prFunction = mock(JCoFunction.class);
        JCoFunction commitFunction = mock(JCoFunction.class);
        JCoFunction rollbackFunction = mock(JCoFunction.class);
        JCoParameterList tables = mock(JCoParameterList.class);
        JCoTable returnTable = mock(JCoTable.class);

        when(destination.getRepository()).thenReturn(repository);
        when(repository.getFunction(PR_CREATE)).thenReturn(prFunction);
        when(repository.getFunction(COMMIT)).thenReturn(commitFunction);
        when(repository.getFunction(ROLLBACK)).thenReturn(rollbackFunction);
        when(prFunction.getImportParameterList()).thenReturn(mock(JCoParameterList.class));
        when(prFunction.getTableParameterList()).thenReturn(tables);
        doNothing().when(prFunction).execute(destination);
        when(tables.isInitialized("RETURN")).thenReturn(true);
        when(tables.getTable("RETURN")).thenReturn(returnTable);
        when(returnTable.getNumRows()).thenReturn(1);
        when(returnTable.isInitialized(any())).thenReturn(true);
        when(returnTable.getString("TYPE")).thenReturn("S");
        when(returnTable.getString("MESSAGE")).thenReturn("PR created");
        doNothing().when(commitFunction).execute(destination);
        when(commitFunction.getExportParameterList()).thenReturn(null);
        when(prFunction.getExportParameterList())
                .thenThrow(new IllegalStateException("export metadata unavailable"));

        PrCreateDraftExecutor executor = new PrCreateDraftExecutor(
                new FixedDestinationFactory(destination), new SapReturnNormalizer());

        ExecutionResult result = executeWithContext(
                executor, destination, Map.of("material", "M001"), "trace-post-commit");

        assertThat(result.success()).isFalse();
        assertThat(result.errorType()).isEqualTo(ErrorType.NORMALIZATION_ERROR);
        assertThat(result.data()).containsEntry("commitStatus", "committed");
        verify(rollbackFunction, never()).execute(destination);
    }

    private CommitPhaseFailure executeCommitPhaseFailure(
            boolean missingCommitFunction,
            boolean rollbackFails
    ) throws Exception {
        JCoDestination destination = mock(JCoDestination.class);
        JCoRepository repository = mock(JCoRepository.class);
        JCoFunction prFunction = mock(JCoFunction.class);
        JCoFunction commitFunction = mock(JCoFunction.class);
        JCoFunction rollbackFunction = mock(JCoFunction.class);
        JCoParameterList tables = mock(JCoParameterList.class);
        JCoTable returnTable = mock(JCoTable.class);

        when(destination.getRepository()).thenReturn(repository);
        when(repository.getFunction(PR_CREATE)).thenReturn(prFunction);
        if (!missingCommitFunction) {
            when(repository.getFunction(COMMIT)).thenReturn(commitFunction);
            JCoException commitException = mock(JCoException.class);
            when(commitException.getGroup()).thenReturn(JCoException.JCO_ERROR_COMMUNICATION);
            when(commitException.getMessage()).thenReturn("Commit connection failed");
            org.mockito.Mockito.doThrow(commitException).when(commitFunction).execute(destination);
        }
        when(repository.getFunction(ROLLBACK)).thenReturn(rollbackFunction);
        when(prFunction.getImportParameterList()).thenReturn(mock(JCoParameterList.class));
        when(prFunction.getTableParameterList()).thenReturn(tables);
        doNothing().when(prFunction).execute(destination);
        when(tables.isInitialized("RETURN")).thenReturn(true);
        when(tables.getTable("RETURN")).thenReturn(returnTable);
        when(returnTable.getNumRows()).thenReturn(1);
        when(returnTable.isInitialized(any())).thenReturn(true);
        when(returnTable.getString("TYPE")).thenReturn("S");
        when(returnTable.getString("MESSAGE")).thenReturn("PR created");
        if (rollbackFails) {
            org.mockito.Mockito.doThrow(new RuntimeException("rollback failed"))
                    .when(rollbackFunction).execute(destination);
        } else {
            doNothing().when(rollbackFunction).execute(destination);
        }

        PrCreateDraftExecutor executor = new PrCreateDraftExecutor(
                new FixedDestinationFactory(destination), new SapReturnNormalizer());
        ExecutionResult result = executeWithContext(
                executor, destination, Map.of("material", "M001"), "trace-commit-phase-failure");
        return new CommitPhaseFailure(result, rollbackFunction, destination);
    }

    private record CommitPhaseFailure(
            ExecutionResult result,
            JCoFunction rollbackFunction,
            JCoDestination destination
    ) {
    }

    private ExecutionResult executeWithContext(
            PrCreateDraftExecutor executor,
            JCoDestination destination,
            Map<String, Object> parameters,
            String traceId
    ) throws Exception {
        try (MockedStatic<JCoContext> context = org.mockito.Mockito.mockStatic(JCoContext.class)) {
            ExecutionResult result = executor.execute(prCapability(), parameters, traceId);
            context.verify(() -> JCoContext.begin(destination));
            context.verify(() -> JCoContext.end(destination));
            return result;
        }
    }

    private CapabilityDefinition prCapability() {
        return new CapabilityDefinition(
                "MM.PR.CreateDraft",
                "PR Create",
                "create PR",
                CapabilityStatus.active,
                CapabilityKind.Action,
                "MM",
                "PurchaseRequisition",
                "sapnexus:MM_PR_CreateDraft",
                "sapnexus:PurchaseRequisitionCreateAction",
                List.of(),
                List.of(),
                new CapabilityDefinition.Executor(
                        "JCO_RFC",
                        "BAPI_PR_CREATE",
                        Map.of(
                                "material", "PRITEM.MATERIAL",
                                "plant", "PRITEM.PLANT",
                                "quantity", "PRITEM.QUANTITY",
                                "unit", "PRITEM.UNIT",
                                "delivery_date", "PRITEM.DELIV_DATE",
                                "purchasing_group", "PRITEM.PUR_GROUP"
                        ),
                        Map.of("prNumber", "EXPORTS.NUMBER", "returnMessages", "RETURN")
                ),
                new CapabilityDefinition.ExecutorBinding("JCO_RFC", "sap.mm.pr.create-draft"),
                new CapabilityDefinition.Governance(SideEffect.sap_write, true, "human_required", "internal", true)
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

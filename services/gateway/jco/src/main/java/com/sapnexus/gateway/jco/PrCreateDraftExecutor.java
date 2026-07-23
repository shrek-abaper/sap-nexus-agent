package com.sapnexus.gateway.jco;

import com.sap.conn.jco.JCoDestination;
import com.sap.conn.jco.JCoContext;
import com.sap.conn.jco.JCoException;
import com.sap.conn.jco.JCoFunction;
import com.sap.conn.jco.JCoParameterList;
import com.sap.conn.jco.JCoRecord;
import com.sap.conn.jco.JCoStructure;
import com.sap.conn.jco.JCoTable;
import com.sapnexus.gateway.registry.CapabilityDefinition;
import com.sapnexus.gateway.result.ErrorType;
import com.sapnexus.gateway.result.CommitStatus;
import com.sapnexus.gateway.result.ExecutionResult;
import com.sapnexus.gateway.result.SapReturnMessage;
import com.sapnexus.gateway.result.SapReturnNormalizer;
import org.springframework.stereotype.Component;

import java.sql.Date;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * WRITE executor for MM.PR.CreateDraft (BAPI_PR_CREATE).
 *
 * <p>Implements the D2 design: commit/rollback is enforced INSIDE this executor.
 * The agent and external callers never trigger BAPI_TRANSACTION_COMMIT/ROLLBACK.
 *
 * <p>Sequence (mirrors STO create pattern, design section 5):
 * <ol>
 *   <li>Execute BAPI_PR_CREATE.</li>
 *   <li>If RETURN contains E/A -> BAPI_TRANSACTION_ROLLBACK -> SAP_BUSINESS_ERROR (rolled_back).</li>
 *   <li>Otherwise BAPI_TRANSACTION_COMMIT (WAIT=X).</li>
 *   <li>If commit RETURN contains E/A -> BAPI_TRANSACTION_ROLLBACK -> SAP_COMMIT_ERROR (rolled_back).</li>
 *   <li>Otherwise extract EXPORTS.NUMBER, with PRITEMEXP.PREQ_NO as fallback -> success (committed).</li>
 * </ol>
 *
 * <p>Sensitive data: traces and ActionResult carry only parameter summaries, PR number,
 * commit status, and error type - never SAP credentials or destination identity.
 */
@Component
public class PrCreateDraftExecutor implements JcoCapabilityExecutor {
    private static final String COMMIT_FUNCTION = "BAPI_TRANSACTION_COMMIT";
    private static final String ROLLBACK_FUNCTION = "BAPI_TRANSACTION_ROLLBACK";
    private static final String STANDARD_PR_TYPE = "NB";
    private static final String FIRST_ITEM = "00010";

    private final JcoDestinationFactory destinationFactory;
    private final SapReturnNormalizer returnNormalizer;

    public PrCreateDraftExecutor() {
        this(new JcoDestinationFactory(), new SapReturnNormalizer());
    }

    PrCreateDraftExecutor(JcoDestinationFactory destinationFactory, SapReturnNormalizer returnNormalizer) {
        this.destinationFactory = destinationFactory;
        this.returnNormalizer = returnNormalizer;
    }

    @Override
    public ExecutionResult execute(CapabilityDefinition capability, Map<String, Object> parameters, String traceId) {
        long started = System.nanoTime();
        JCoDestination destination = null;
        boolean contextStarted = false;
        boolean writeAttempted = false;
        boolean commitPhase = false;
        boolean commitSucceeded = false;
        try {
            destination = destinationFactory.getDestination();
            JCoFunction prFunction = destination.getRepository().getFunction(capability.executor().rfcName());
            if (prFunction == null) {
                return failure(traceId, capability, ErrorType.NORMALIZATION_ERROR, "SAP function not found", started);
            }

            applyImportParameters(prFunction.getImportParameterList(), capability, parameters);
            applyPrHeader(prFunction.getImportParameterList());
            applyPrItemTables(prFunction.getTableParameterList(), capability, parameters);
            JCoContext.begin(destination);
            contextStarted = true;
            writeAttempted = true;
            prFunction.execute(destination);

            List<SapReturnMessage> returnMessages = extractReturnMessages(prFunction);
            SapReturnNormalizer.Result normalized = returnNormalizer.normalize(returnMessages);
            if (!normalized.success()) {
                CommitStatus rollbackStatus = rollback(destination);
                return new ExecutionResult(
                        traceId,
                        capability.capabilityId(),
                        false,
                        new ExecutionResult.ExecutorMetadata(capability.executor().type(), capability.executor().rfcName()),
                        normalized.messages(),
                        Map.of("commitStatus", rollbackStatus.name()),
                        elapsedMs(started),
                        ErrorType.SAP_BUSINESS_ERROR
                );
            }

            // Commit with WAIT=X so the LUW is durable before we read back the PR number.
            commitPhase = true;
            JCoFunction commitFunction = destination.getRepository().getFunction(COMMIT_FUNCTION);
            if (commitFunction == null) {
                CommitStatus rollbackStatus = rollback(destination);
                return failure(
                        traceId, capability, ErrorType.SAP_COMMIT_ERROR,
                        "SAP commit function not found", rollbackStatus, started);
            }
            JCoParameterList commitImports = commitFunction.getImportParameterList();
            if (commitImports != null && hasParameter(commitImports, "WAIT")) {
                commitImports.setValue("WAIT", "X");
            }
            commitFunction.execute(destination);

            List<SapReturnMessage> commitReturn = extractCommitReturn(commitFunction);
            SapReturnNormalizer.Result commitNormalized = returnNormalizer.normalize(commitReturn);
            if (!commitNormalized.success()) {
                CommitStatus rollbackStatus = rollback(destination);
                return new ExecutionResult(
                        traceId,
                        capability.capabilityId(),
                        false,
                        new ExecutionResult.ExecutorMetadata(capability.executor().type(), capability.executor().rfcName()),
                        commitNormalized.messages(),
                        Map.of("commitStatus", rollbackStatus.name()),
                        elapsedMs(started),
                        ErrorType.SAP_COMMIT_ERROR
                );
            }
            commitSucceeded = true;

            Map<String, Object> data = extractPrNumber(prFunction, capability);
            data.put("commitStatus", CommitStatus.committed.name());
            return ExecutionResult.success(
                    traceId,
                    capability.capabilityId(),
                    capability.executor().type(),
                    capability.executor().rfcName(),
                    normalized.messages(),
                    data,
                    elapsedMs(started)
            );
        } catch (JCoException exception) {
            CommitStatus commitStatus = commitStatusAfterException(
                    destination, writeAttempted, commitSucceeded);
            ErrorType errorType = commitSucceeded
                    ? ErrorType.NORMALIZATION_ERROR
                    : commitPhase ? ErrorType.SAP_COMMIT_ERROR : mapJcoError(exception);
            return failure(
                    traceId, capability, errorType, sanitize(exception.getMessage()), commitStatus, started);
        } catch (RuntimeException exception) {
            CommitStatus commitStatus = commitStatusAfterException(
                    destination, writeAttempted, commitSucceeded);
            ErrorType errorType = commitSucceeded
                    ? ErrorType.NORMALIZATION_ERROR
                    : commitPhase ? ErrorType.SAP_COMMIT_ERROR : ErrorType.SAP_COMMUNICATION_ERROR;
            return failure(
                    traceId, capability, errorType, sanitize(exception.getMessage()), commitStatus, started);
        } finally {
            if (contextStarted && destination != null) {
                try {
                    JCoContext.end(destination);
                } catch (JCoException | RuntimeException ignored) {
                    // The transaction result is already fixed; cleanup failure must not rewrite it.
                }
            }
        }
    }

    private void applyImportParameters(JCoParameterList imports, CapabilityDefinition capability, Map<String, Object> parameters) {
        if (imports == null) {
            return;
        }
        capability.executor().inputMapping().forEach((requestName, sapName) -> {
            Object value = parameters.get(requestName);
            if (value != null && hasParameter(imports, sapName)) {
                imports.setValue(sapName, value);
            }
        });
    }

    private void applyPrHeader(JCoParameterList imports) {
        if (imports == null || !hasParameter(imports, "PRHEADER") || !hasParameter(imports, "PRHEADERX")) {
            return;
        }

        JCoStructure header = imports.getStructure("PRHEADER");
        JCoStructure headerX = imports.getStructure("PRHEADERX");
        header.setValue("PR_TYPE", STANDARD_PR_TYPE);
        headerX.setValue("PR_TYPE", "X");
    }

    private void applyPrItemTables(JCoParameterList tables, CapabilityDefinition capability, Map<String, Object> parameters) {
        if (tables == null || !hasParameter(tables, "PRITEM") || !hasParameter(tables, "PRITEMX")) {
            return;
        }

        JCoTable prItem = tables.getTable("PRITEM");
        JCoTable prItemX = tables.getTable("PRITEMX");
        prItem.appendRow();
        prItemX.appendRow();
        setIfPresent(prItem, "PREQ_ITEM", FIRST_ITEM);
        setIfPresent(prItemX, "PREQ_ITEM", FIRST_ITEM);
        setIfPresent(prItemX, "PREQ_ITEMX", "X");

        capability.executor().inputMapping().forEach((requestName, sapTarget) -> {
            Object value = parameters.get(requestName);
            String field = prItemField(sapTarget);
            if (value == null || field == null || !prItem.getMetaData().hasField(field)) {
                return;
            }

            Object normalizedValue = "delivery_date".equals(requestName)
                    ? Date.valueOf(LocalDate.parse(value.toString()))
                    : value;
            prItem.setValue(field, normalizedValue);
            setIfPresent(prItemX, field, "X");
        });
    }

    private String prItemField(String sapTarget) {
        String prefix = "PRITEM.";
        return sapTarget != null && sapTarget.startsWith(prefix)
                ? sapTarget.substring(prefix.length())
                : null;
    }

    private void setIfPresent(JCoRecord record, String field, Object value) {
        if (record.getMetaData().hasField(field)) {
            record.setValue(field, value);
        }
    }

    private List<SapReturnMessage> extractReturnMessages(JCoFunction function) {
        List<SapReturnMessage> messages = new ArrayList<>();
        JCoParameterList tables = function.getTableParameterList();
        if (tables != null && safeIsInitialized(tables, "RETURN")) {
            try {
                JCoTable table = tables.getTable("RETURN");
                for (int row = 0; row < table.getNumRows(); row++) {
                    table.setRow(row);
                    messages.add(toReturnMessage(table));
                }
            } catch (RuntimeException ignored) {
                // RETURN shape varies; keep going with whatever was collected.
            }
        }
        return messages;
    }

    private List<SapReturnMessage> extractCommitReturn(JCoFunction commitFunction) {
        List<SapReturnMessage> messages = new ArrayList<>();
        JCoParameterList exports = commitFunction.getExportParameterList();
        if (exports != null && safeIsInitialized(exports, "RETURN")) {
            try {
                messages.add(toReturnMessage(exports.getStructure("RETURN")));
            } catch (RuntimeException ignored) {
                // Commit RETURN is optional on some SAP releases.
            }
        }
        return messages;
    }

    private Map<String, Object> extractPrNumber(JCoFunction function, CapabilityDefinition capability) {
        Map<String, Object> data = new LinkedHashMap<>();
        JCoParameterList exports = function.getExportParameterList();
        if (exports != null && hasParameter(exports, "NUMBER")) {
            String exportedNumber = getString(exports, "NUMBER");
            if (!exportedNumber.isBlank()) {
                data.put("prNumber", exportedNumber);
                return data;
            }
        }

        JCoParameterList tables = function.getTableParameterList();
        if (tables != null && safeIsInitialized(tables, "PRITEMEXP")) {
            try {
                JCoTable prItemExp = tables.getTable("PRITEMEXP");
                if (prItemExp.getNumRows() > 0) {
                    prItemExp.setRow(0);
                    data.put("prNumber", getString(prItemExp, "PREQ_NO"));
                }
            } catch (RuntimeException ignored) {
                // PRITEMEXP may be absent; callers see an empty prNumber.
            }
        }
        return data;
    }

    private CommitStatus rollback(JCoDestination destination) {
        try {
            JCoFunction rollbackFunction = destination.getRepository().getFunction(ROLLBACK_FUNCTION);
            rollbackFunction.execute(destination);
            return CommitStatus.rolled_back;
        } catch (JCoException | RuntimeException ignored) {
            return CommitStatus.rollback_failed;
        }
    }

    private CommitStatus commitStatusAfterException(
            JCoDestination destination,
            boolean writeAttempted,
            boolean commitSucceeded
    ) {
        if (commitSucceeded) {
            return CommitStatus.committed;
        }
        return writeAttempted && destination != null ? rollback(destination) : CommitStatus.none;
    }

    private SapReturnMessage toReturnMessage(JCoRecord record) {
        return new SapReturnMessage(
                getString(record, "TYPE"),
                getString(record, "ID"),
                getString(record, "NUMBER"),
                getString(record, "MESSAGE"),
                getString(record, "FIELD")
        );
    }

    private String getString(JCoRecord record, String field) {
        try {
            return record.isInitialized(field) ? record.getString(field) : "";
        } catch (RuntimeException ignored) {
            return "";
        }
    }

    private boolean safeIsInitialized(JCoRecord record, String field) {
        try {
            return record.isInitialized(field);
        } catch (RuntimeException ignored) {
            return false;
        }
    }

    private boolean hasParameter(JCoParameterList parameters, String field) {
        try {
            return parameters.getMetaData().indexOf(field) >= 0;
        } catch (RuntimeException ignored) {
            return false;
        }
    }

    private ErrorType mapJcoError(JCoException exception) {
        return switch (exception.getGroup()) {
            case JCoException.JCO_ERROR_LOGON_FAILURE, JCoException.JCO_ERROR_PASSWORD_CHANGE_REQUIRED -> ErrorType.SAP_AUTH_ERROR;
            case JCoException.JCO_ERROR_COMMUNICATION, JCoException.JCO_ERROR_TIMEOUT -> ErrorType.SAP_COMMUNICATION_ERROR;
            default -> ErrorType.SAP_BUSINESS_ERROR;
        };
    }

    private ExecutionResult failure(String traceId, CapabilityDefinition capability, ErrorType errorType, String message, long started) {
        return ExecutionResult.failure(
                traceId,
                capability.capabilityId(),
                capability.executor().type(),
                capability.executor().rfcName(),
                errorType,
                message,
                elapsedMs(started)
        );
    }

    private ExecutionResult failure(
            String traceId,
            CapabilityDefinition capability,
            ErrorType errorType,
            String message,
            CommitStatus commitStatus,
            long started
    ) {
        return new ExecutionResult(
                traceId,
                capability.capabilityId(),
                false,
                new ExecutionResult.ExecutorMetadata(
                        capability.executor().type(), capability.executor().rfcName()),
                List.of(new SapReturnMessage("E", "", "", message, "")),
                Map.of("commitStatus", commitStatus.name()),
                elapsedMs(started),
                errorType
        );
    }

    private long elapsedMs(long started) {
        return (System.nanoTime() - started) / 1_000_000;
    }

    private String sanitize(String message) {
        if (message == null || message.isBlank()) {
            return "SAP JCo execution failed";
        }
        return message.replaceAll("(?i)(passwd|password)=\\S+", "$1=***");
    }
}

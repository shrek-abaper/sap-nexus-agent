package com.sapnexus.gateway.jco;

import com.sap.conn.jco.JCoDestination;
import com.sap.conn.jco.JCoException;
import com.sap.conn.jco.JCoFunction;
import com.sap.conn.jco.JCoParameterList;
import com.sap.conn.jco.JCoRecord;
import com.sap.conn.jco.JCoTable;
import com.sapnexus.gateway.registry.CapabilityDefinition;
import com.sapnexus.gateway.result.ErrorType;
import com.sapnexus.gateway.result.ExecutionResult;
import com.sapnexus.gateway.result.SapReturnMessage;
import com.sapnexus.gateway.result.SapReturnNormalizer;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

@Component
public class InventoryAvailabilityExecutor implements JcoCapabilityExecutor {
    private final JcoDestinationFactory destinationFactory;
    private final SapReturnNormalizer returnNormalizer;

    public InventoryAvailabilityExecutor() {
        this(new JcoDestinationFactory(), new SapReturnNormalizer());
    }

    InventoryAvailabilityExecutor(JcoDestinationFactory destinationFactory, SapReturnNormalizer returnNormalizer) {
        this.destinationFactory = destinationFactory;
        this.returnNormalizer = returnNormalizer;
    }

    @Override
    public ExecutionResult execute(CapabilityDefinition capability, Map<String, Object> parameters, String traceId) {
        long started = System.nanoTime();
        try {
            JCoDestination destination = destinationFactory.getDestination();
            JCoFunction function = destination.getRepository().getFunction(capability.executor().rfcName());
            if (function == null) {
                return failure(traceId, capability, ErrorType.NORMALIZATION_ERROR, "SAP function not found", started);
            }

            applyImportParameters(function.getImportParameterList(), capability, parameters);
            function.execute(destination);

            List<SapReturnMessage> returnMessages = extractReturnMessages(function);
            SapReturnNormalizer.Result normalized = returnNormalizer.normalize(returnMessages);
            Map<String, Object> data = extractOutputData(function, capability);
            if (!normalized.success()) {
                return new ExecutionResult(
                        traceId,
                        capability.capabilityId(),
                        false,
                        new ExecutionResult.ExecutorMetadata(capability.executor().type(), capability.executor().rfcName()),
                        normalized.messages(),
                        data,
                        elapsedMs(started),
                        normalized.errorType()
                );
            }
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
            return failure(traceId, capability, mapJcoError(exception), sanitize(exception.getMessage()), started);
        } catch (RuntimeException exception) {
            return failure(traceId, capability, ErrorType.SAP_COMMUNICATION_ERROR, sanitize(exception.getMessage()), started);
        }
    }

    private void applyImportParameters(JCoParameterList imports, CapabilityDefinition capability, Map<String, Object> parameters) {
        if (imports == null) {
            return;
        }
        capability.executor().inputMapping().forEach((requestName, sapName) -> {
            Object value = parameters.get(requestName);
            if (value != null) {
                for (String targetName : sapName.split(",")) {
                    String trimmed = targetName.trim();
                    if (!trimmed.isEmpty() && hasParameter(imports, trimmed)) {
                        imports.setValue(trimmed, value);
                    }
                }
            }
        });
    }

    private List<SapReturnMessage> extractReturnMessages(JCoFunction function) {
        List<SapReturnMessage> messages = new ArrayList<>();
        addReturnStructure(messages, function.getExportParameterList());
        addReturnTable(messages, function.getTableParameterList());
        return messages;
    }

    private void addReturnStructure(List<SapReturnMessage> messages, JCoParameterList parameters) {
        if (parameters == null || !safeIsInitialized(parameters, "RETURN")) {
            return;
        }
        try {
            messages.add(toReturnMessage(parameters.getStructure("RETURN")));
        } catch (RuntimeException ignored) {
            messages.add(toReturnMessage(parameters));
        }
    }

    private void addReturnTable(List<SapReturnMessage> messages, JCoParameterList parameters) {
        if (parameters == null || !safeIsInitialized(parameters, "RETURN")) {
            return;
        }
        try {
            JCoTable table = parameters.getTable("RETURN");
            for (int row = 0; row < table.getNumRows(); row++) {
                table.setRow(row);
                messages.add(toReturnMessage(table));
            }
        } catch (RuntimeException ignored) {
            // Some BAPIs expose RETURN elsewhere or do not expose RETURN.
        }
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

    private Map<String, Object> extractOutputData(JCoFunction function, CapabilityDefinition capability) {
        Map<String, Object> data = new LinkedHashMap<>();
        JCoParameterList exports = function.getExportParameterList();
        if (exports != null) {
            capability.executor().outputMapping().forEach((name, sapName) -> {
                if (!"RETURN".equals(sapName) && safeIsInitialized(exports, sapName)) {
                    data.put(name, exports.getValue(sapName));
                }
            });
        }
        addMd04StockRowData(function.getTableParameterList(), data);
        return data;
    }

    private void addMd04StockRowData(JCoParameterList tables, Map<String, Object> data) {
        if (tables == null || !safeIsInitialized(tables, "MRP_IND_LINES")) {
            return;
        }
        try {
            JCoTable lines = tables.getTable("MRP_IND_LINES");
            for (int row = 0; row < lines.getNumRows(); row++) {
                lines.setRow(row);
                String elementInd = getString(lines, "MRP_ELEMENT_IND");
                String element = getString(lines, "MRP_ELEMNT");
                if ("WB".equals(elementInd) || "Stock".equalsIgnoreCase(element)) {
                    Double quantity = parseQuantity(getString(lines, "AVAIL_QTY1"));
                    if (quantity != null) {
                        data.put("availableQuantity", quantity);
                        data.put("sourceTable", "MRP_IND_LINES");
                        data.put("sourceField", "AVAIL_QTY1");
                        data.put("mrpElementInd", elementInd);
                        data.put("mrpElement", element);
                        data.put("availableDate", getString(lines, "AVAIL_DATE"));
                    }
                    return;
                }
            }
        } catch (RuntimeException ignored) {
            // Some SAP releases or authorizations may omit the MD04 table; keep other normalized outputs.
        }
    }

    private Double parseQuantity(String value) {
        if (value == null || value.isBlank()) {
            return null;
        }
        try {
            return Double.parseDouble(value.trim().replace(",", ""));
        } catch (NumberFormatException ignored) {
            return null;
        }
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

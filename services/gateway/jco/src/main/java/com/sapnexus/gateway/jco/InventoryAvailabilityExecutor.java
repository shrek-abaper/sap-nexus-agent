package com.sapnexus.gateway.jco;

import com.sap.conn.jco.JCoDestination;
import com.sap.conn.jco.JCoException;
import com.sap.conn.jco.JCoFunction;
import com.sap.conn.jco.JCoParameterList;
import com.sap.conn.jco.JCoRecord;
import com.sap.conn.jco.JCoRecordMetaData;
import com.sap.conn.jco.JCoStructure;
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
import java.util.Optional;

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
                if ("RETURN".equals(sapName)) {
                    return;
                }
                if (safeIsInitialized(exports, sapName)) {
                    data.put(name, exports.getValue(sapName));
                    return;
                }
                resolveExportStructureField(exports, sapName).ifPresent(value -> data.put(name, value));
            });
        }
        addDeclaredTableRows(function.getTableParameterList(), capability, data);
        addMd04StockRowData(function.getTableParameterList(), data);
        return data;
    }

    /**
     * Reads every TABLES parameter named by {@code outputMapping} into a list of row
     * maps, driven entirely by the registry and the table's own JCo metadata.
     * <p>
     * Registry-driven for the same reason as {@link #resolveExportStructureField}: a
     * capability whose primary fact is a table (a sales order list, an AR/AP open item
     * list) must be addable by declaring it, not by adding another bespoke
     * {@code addXxxRowData} method per capability. Rows carry every field the table
     * metadata reports, keyed by the camelCase form of the SAP column, so the field set
     * comes from SAP rather than from a hardcoded list that silently drops a column.
     * <p>
     * Values are read as text, like {@link #addMd04StockRowData} does: the executor does
     * not decide which column is a number. Interpretation belongs to the Fact builder
     * that knows what the column means.
     * <p>
     * A name already produced from the export parameters is left alone, and
     * {@code MRP_IND_LINES} is not reachable here because no capability declares it in
     * {@code outputMapping} -- MD04 keeps its own extraction unchanged.
     */
    private void addDeclaredTableRows(JCoParameterList tables, CapabilityDefinition capability, Map<String, Object> data) {
        if (tables == null) {
            return;
        }
        capability.executor().outputMapping().forEach((name, sapName) -> {
            if ("RETURN".equals(sapName) || data.containsKey(name)) {
                return;
            }
            if (!safeIsInitialized(tables, sapName)) {
                return;
            }
            try {
                JCoTable table = tables.getTable(sapName);
                if (table == null) {
                    return;
                }
                List<Map<String, Object>> rows = new ArrayList<>();
                for (int rowIndex = 0; rowIndex < table.getNumRows(); rowIndex++) {
                    table.setRow(rowIndex);
                    rows.add(readRow(table));
                }
                data.put(name, rows);
            } catch (RuntimeException ignored) {
                // A release or authorization may not expose the declared table; keep
                // the other normalized outputs rather than failing the whole read.
            }
        });
    }

    private Map<String, Object> readRow(JCoTable table) {
        Map<String, Object> row = new LinkedHashMap<>();
        JCoRecordMetaData metaData = table.getRecordMetaData();
        for (int field = 0; field < metaData.getFieldCount(); field++) {
            String sapField = metaData.getName(field);
            if (sapField == null || sapField.isBlank()) {
                continue;
            }
            row.put(toCamelCase(sapField), getString(table, sapField));
        }
        return row;
    }

    /**
     * {@code DOC_NO -> docNo}, {@code AMT_DOCCUR -> amtDoccur}, {@code PURCH_NO_C ->
     * purchNoC}. Mechanical, so it carries no per-capability knowledge; the mapping from
     * a camelCase row key to a Fact Type field stays in the Fact builder.
     */
    private String toCamelCase(String sapField) {
        StringBuilder camel = new StringBuilder(sapField.length());
        boolean upperNext = false;
        for (char character : sapField.toCharArray()) {
            if (character == '_') {
                upperNext = true;
                continue;
            }
            char lower = Character.toLowerCase(character);
            camel.append(upperNext ? Character.toUpperCase(lower) : lower);
            upperNext = false;
        }
        return camel.toString();
    }

    /**
     * Resolves an {@code outputMapping} value of the form {@code EXPORT_PARAM.FIELD}
     * against an export structure.
     * <p>
     * Driven entirely by the registry: the export parameter name and the field name
     * both come from {@code outputMapping}, so a capability whose values live inside
     * an export structure needs no executor code of its own. Without this, such a
     * capability could only be added by writing a bespoke per-capability executor,
     * i.e. by force-calling the RFC from code logic instead of declaring it.
     * <p>
     * Deliberately splits on the FIRST separator only, so the field segment is taken
     * verbatim. A three-segment table-row path such as {@code MRP_IND_LINES.WB.AVAIL_QTY1}
     * selects a row by value rather than a field of a structure; it falls out here
     * because no export structure named {@code MRP_IND_LINES} exists, and it stays with
     * {@link #addMd04StockRowData}. An explicit segment-count guard was written first and
     * then removed: mutation M30 showed it unreachable, because the field-level
     * initialization check already rejects a residual dotted name. Unkillable defensive
     * code reads as protection and asserts nothing.
     * <p>
     * An absent or uninitialized structure yields {@link Optional#empty()} so the key
     * stays out of the result, and so does a **blank** field inside a present
     * structure. Finding G5, from the task 5.10 live smoke: a real read returned
     * {@code MATERIALPLANTDATA} initialized with {@code PUR_GROUP} blank, and an empty
     * string is not a purchasing group. Emitting one turns "this could not be derived,
     * ask the user" into "an empty value was derived", which then fails late inside a
     * purchase requisition instead of failing where the fact is missing.
     */
    private Optional<Object> resolveExportStructureField(JCoParameterList exports, String path) {
        int separator = path.indexOf('.');
        if (separator <= 0 || separator == path.length() - 1) {
            return Optional.empty();
        }
        String parameterName = path.substring(0, separator);
        String fieldName = path.substring(separator + 1);
        if (!safeIsInitialized(exports, parameterName)) {
            return Optional.empty();
        }
        try {
            JCoStructure structure = exports.getStructure(parameterName);
            if (structure == null || !safeIsInitialized(structure, fieldName)) {
                return Optional.empty();
            }
            Object value = structure.getValue(fieldName);
            if (value instanceof String text && text.isBlank()) {
                return Optional.empty();
            }
            return Optional.ofNullable(value);
        } catch (RuntimeException ignored) {
            return Optional.empty();
        }
    }

    private void addMd04StockRowData(JCoParameterList tables, Map<String, Object> data) {
        if (tables == null || !safeIsInitialized(tables, "MRP_IND_LINES")) {
            return;
        }
        try {
            JCoTable lines = tables.getTable("MRP_IND_LINES");
            List<Map<String, Object>> mrpElementLines = new ArrayList<>();
            for (int row = 0; row < lines.getNumRows(); row++) {
                lines.setRow(row);
                String elementInd = getString(lines, "MRP_ELEMENT_IND");
                String element = getString(lines, "MRP_ELEMNT");
                Double availQty1 = parseQuantity(getString(lines, "AVAIL_QTY1"));
                Double elementQty = parseQuantity(getString(lines, "ELEMENT_QTY"));
                String date = getString(lines, "AVAIL_DATE");
                Map<String, Object> lineEntry = new LinkedHashMap<>();
                lineEntry.put("mrpElementInd", elementInd);
                lineEntry.put("mrpElement", element);
                lineEntry.put("elementQty", elementQty);
                lineEntry.put("availQty1", availQty1);
                lineEntry.put("date", date);
                mrpElementLines.add(lineEntry);
                // Preserve the existing scalar availableQuantity: the running stock row (WB).
                if (data.get("availableQuantity") == null && ("WB".equals(elementInd) || "Stock".equalsIgnoreCase(element)) && availQty1 != null) {
                    data.put("availableQuantity", availQty1);
                    data.put("sourceTable", "MRP_IND_LINES");
                    data.put("sourceField", "AVAIL_QTY1");
                    data.put("mrpElementInd", elementInd);
                    data.put("mrpElement", element);
                    data.put("availableDate", date);
                }
            }
            if (!mrpElementLines.isEmpty()) {
                data.put("mrpElementLines", mrpElementLines);
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

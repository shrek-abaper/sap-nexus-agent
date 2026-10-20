package com.sapnexus.gateway.masterdata;

import com.sapnexus.gateway.execution.TechnicalAdapter;
import com.sapnexus.gateway.execution.TechnicalExecutionRequest;
import com.sapnexus.gateway.execution.TechnicalExecutionResult;
import com.sapnexus.gateway.registry.BindingDefinition;
import com.sapnexus.gateway.registry.BindingRegistry;
import com.sapnexus.gateway.registry.CapabilityDefinition;
import com.sapnexus.gateway.registry.CapabilityRegistry;
import com.sapnexus.gateway.result.ErrorType;
import com.sapnexus.gateway.result.SapReturnMessage;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.stereotype.Component;

import java.sql.SQLException;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Executes master-data search capabilities (PG_MASTERDATA_READ) against the
 * PostgreSQL projection through fixed parameterized queries.
 *
 * <p>Governance invariants (spec: entity-search-provider):
 * <ul>
 *   <li>no arbitrary SQL/table/column from request, registry, or model —
 *       only the registered {@code queryTemplateId} selects a fixed query;</li>
 *   <li>trusted scope (principal/systems/clients/org) is server-injected via
 *       callerContext and applied before ranking/pagination; request org
 *       filters may only narrow it;</li>
 *   <li>inactive entities are never search candidates; get-by-key still
 *       reports them with their status;</li>
 *   <li>raw database errors never echo SQL, connection details, or secrets.</li>
 * </ul>
 */
@Component("PG_MASTERDATA_READ")
@EnableConfigurationProperties(PgMasterdataProperties.class)
public class PgMasterdataTechnicalAdapter implements TechnicalAdapter {

    private static final String MATCH_EXACT_CODE = "exact-code";
    private static final String MATCH_EXACT_LABEL = "exact-label";
    private static final String MATCH_APPROVED_ALIAS = "approved-alias";
    private static final String MATCH_SUBSTRING = "substring";
    private static final String MATCH_TRIGRAM = "trigram";
    private static final String COMPLETE = "complete-result-set";
    private static final String TRUNCATED = "partial-truncated";

    private final CapabilityRegistry registry;
    private final BindingRegistry bindingRegistry;
    private final PhysicalMappings mappings;
    private final MasterdataQueryRunner.RowExecutor rows;

    @Autowired
    public PgMasterdataTechnicalAdapter(CapabilityRegistry registry,
                                        BindingRegistry bindingRegistry,
                                        PgMasterdataProperties properties) {
        this(registry, bindingRegistry,
                PhysicalMappings.load(java.nio.file.Path.of(properties.getMappingsPath())),
                new MasterdataQueryRunner(properties).rowExecutor());
    }

    /** Test seam: inject mappings and a fake row executor (no live database). */
    PgMasterdataTechnicalAdapter(CapabilityRegistry registry,
                                 BindingRegistry bindingRegistry,
                                 PhysicalMappings mappings,
                                 MasterdataQueryRunner.RowExecutor rows) {
        this.registry = registry;
        this.bindingRegistry = bindingRegistry;
        this.mappings = mappings;
        this.rows = rows;
    }

    @Override
    public TechnicalExecutionResult execute(TechnicalExecutionRequest request) {
        long start = System.currentTimeMillis();
        String traceId = request.traceId();
        try {
            return doExecute(request, start);
        } catch (IllegalArgumentException e) {
            return failure(request, ErrorType.MASTERDATA_INVALID_REQUEST, e.getMessage(), start);
        } catch (SQLException e) {
            if (MasterdataQueryRunner.isPermissionDenied(e)) {
                return failure(request, ErrorType.MASTERDATA_PERMISSION_DENIED,
                        "principal lacks master-data read privilege", start);
            }
            return failure(request, ErrorType.MASTERDATA_UNAVAILABLE,
                    "master-data store is not reachable", start);
        }
    }

    private TechnicalExecutionResult doExecute(TechnicalExecutionRequest request, long start)
            throws SQLException {
        CapabilityDefinition capability = registry.findEnabled(request.capabilityId())
                .orElseThrow(() -> new IllegalArgumentException(
                        "Capability not found or disabled: " + request.capabilityId()));
        BindingDefinition binding = bindingRegistry.find(request.bindingId())
                .orElseThrow(() -> new IllegalArgumentException(
                        "Binding not found: " + request.bindingId()));
        String queryTemplateId = binding.queryTemplateId() != null
                ? binding.queryTemplateId()
                : (capability.executor() == null ? null : capability.executor().queryTemplateId());
        if (queryTemplateId == null) {
            throw new IllegalArgumentException("binding has no queryTemplateId");
        }
        PhysicalMappings.Template template = mappings.require(queryTemplateId);

        Map<String, Object> parameters = request.parameters() == null
                ? Map.of() : request.parameters();
        Map<String, String> inputMapping = capability.executor().inputMapping();
        String query = stringParam(parameters, inputMapping, "query", "QUERY");
        String entityKey = stringParam(parameters, inputMapping, "entityKey", "ENTITY_KEY");
        String language = stringParam(parameters, inputMapping, "language", "LANGUAGE");
        int limit = intParam(parameters, inputMapping, "limit", "LIMIT", 20);
        if (limit < 1 || limit > MasterdataQueries.MAX_LIMIT) {
            throw new IllegalArgumentException(
                    "limit must be within 1.." + MasterdataQueries.MAX_LIMIT);
        }

        TrustedScope scope = TrustedScope.from(request.callerContext());
        String orgFilterField = template.orgFilterField();
        String orgFilterValue = orgFilterField == null ? null
                : stringParam(parameters, inputMapping,
                        logicalInputFor(capability, orgFilterField), orgFilterField.toUpperCase());

        // --- retrieval (fixed order: exact code, label/alias, substring, trigram)
        Map<String, EntityRow> entities = entitiesInScope(template, scope);
        String snapshotId;
        String sourceExtractedAt;
        String loadedAt;
        List<Map<String, Object>> snapshotRows = rows.query(
                MasterdataQueries.CURRENT_SNAPSHOT,
                List.of(template.objectType(), scope.sourceSystems(), scope.clients()));
        if (snapshotRows.isEmpty()) {
            throw new IllegalArgumentException(
                    "no active snapshot covers " + template.objectType() + " in the authorized scope");
        }
        snapshotId = String.valueOf(snapshotRows.get(0).get("snapshot_id"));
        sourceExtractedAt = stringOrNull(snapshotRows.get(0).get("source_extracted_at"));
        loadedAt = stringOrNull(snapshotRows.get(0).get("loaded_at"));

        Map<String, MatchInfo> matches = new LinkedHashMap<>();
        if (entityKey != null && !entityKey.isBlank()) {
            for (EntityRow row : entities.values()) {
                if (row.code.equalsIgnoreCase(entityKey)) {
                    matches.put(row.code, new MatchInfo(MATCH_EXACT_CODE, null));
                }
            }
        }
        if (matches.isEmpty() && query != null && !query.isBlank()) {
            String trimmed = query.trim();
            for (Map<String, Object> row : rows.query(
                    MasterdataQueries.CODES_BY_EXACT_LABEL, List.of(template.objectType(), trimmed))) {
                matches.putIfAbsent(String.valueOf(row.get("canonical_code")),
                        new MatchInfo(MATCH_EXACT_LABEL, null));
            }
            for (Map<String, Object> row : rows.query(
                    MasterdataQueries.CODES_BY_ALIAS, List.of(template.objectType(), trimmed))) {
                matches.putIfAbsent(String.valueOf(row.get("canonical_code")),
                        new MatchInfo(MATCH_APPROVED_ALIAS, null));
            }
            if (matches.isEmpty()) {
                String pattern = "%" + MasterdataQueries.likeEscape(trimmed) + "%";
                for (Map<String, Object> row : rows.query(
                        MasterdataQueries.CODES_BY_SUBSTRING, List.of(template.objectType(), pattern))) {
                    matches.putIfAbsent(String.valueOf(row.get("canonical_code")),
                            new MatchInfo(MATCH_SUBSTRING, null));
                }
            }
            if (matches.isEmpty() && trimmed.length() >= MasterdataQueries.TRIGRAM_MIN_QUERY_LENGTH) {
                for (Map<String, Object> row : rows.query(
                        MasterdataQueries.CODES_BY_TRIGRAM, List.of(trimmed, template.objectType(), trimmed))) {
                    double score = ((Number) row.get("score")).doubleValue();
                    if (score >= MasterdataQueries.TRIGRAM_THRESHOLD) {
                        matches.putIfAbsent(String.valueOf(row.get("canonical_code")),
                                new MatchInfo(MATCH_TRIGRAM, score));
                    }
                }
            }
        }

        // Org narrowing: trusted-scope org restrictions apply first; a request
        // filter outside them is denied rather than widened.
        java.util.Set<String> visible = null;
        Map<String, List<String>> requiredOrg = new LinkedHashMap<>(scope.orgScopes());
        if (orgFilterField != null && orgFilterValue != null && !orgFilterValue.isBlank()) {
            List<String> allowed = scope.orgScopes().get(orgFilterField);
            if (allowed != null && !allowed.isEmpty() && !allowed.contains(orgFilterValue)) {
                return failure(request, ErrorType.MASTERDATA_PERMISSION_DENIED,
                        "requested organizational scope is outside the authorized scope", start);
            }
            requiredOrg.put(orgFilterField, List.of(orgFilterValue));
        }
        for (Map.Entry<String, List<String>> entry : requiredOrg.entrySet()) {
            if (entry.getValue().isEmpty()) {
                continue;
            }
            java.util.Set<String> matching = new java.util.HashSet<>();
            for (String value : entry.getValue()) {
                for (Map<String, Object> row : rows.query(
                        MasterdataQueries.CODES_BY_ORG_SCOPE,
                        List.of(template.objectType(), template.objectType(),
                                entry.getKey(), value, template.objectType(), entry.getKey()))) {
                    matching.add(String.valueOf(row.get("canonical_code")));
                }
            }
            visible = visible == null ? matching : intersect(visible, matching);
        }

        List<String> codes = new ArrayList<>();
        for (String code : matches.keySet()) {
            EntityRow row = entities.get(code);
            if (row == null || !"active".equals(row.status)) {
                continue; // inactive entities are never search candidates
            }
            if (visible != null && !visible.contains(code)) {
                continue;
            }
            codes.add(code);
        }
        boolean truncated = codes.size() > limit;
        codes = codes.subList(0, Math.min(codes.size(), limit));

        Map<String, List<Map<String, Object>>> descriptions = groupBy(
                codes.isEmpty() ? List.of()
                        : rows.query(MasterdataQueries.DESCRIPTIONS,
                                List.of(template.objectType(), codes)));
        Map<String, List<Map<String, Object>>> orgScopes = groupBy(
                codes.isEmpty() ? List.of()
                        : rows.query(MasterdataQueries.ORG_SCOPES,
                                List.of(template.objectType(), codes)));

        List<Map<String, Object>> candidates = new ArrayList<>();
        for (String code : codes) {
            EntityRow row = entities.get(code);
            MatchInfo match = matches.get(code);
            Map<String, Object> candidate = new LinkedHashMap<>();
            candidate.put("sourceSystem", row.sourceSystem);
            candidate.put("client", row.client);
            candidate.put("objectType", row.objectType);
            candidate.put("canonicalCode", row.code);
            candidate.put("displayName", displayName(descriptions.getOrDefault(code, List.of()), language));
            candidate.put("distinguishing", row.attributes);
            candidate.put("matchKind", match.kind);
            candidate.put("status", row.status);
            List<Map<String, String>> scopes = new ArrayList<>();
            for (Map<String, Object> scopeRow : orgScopes.getOrDefault(code, List.of())) {
                scopes.add(Map.of(
                        "field", String.valueOf(scopeRow.get("org_field")),
                        "value", String.valueOf(scopeRow.get("org_value"))));
            }
            candidate.put("orgScopes", scopes);
            if (match.score != null) {
                candidate.put("score", match.score);
            }
            candidates.add(candidate);
        }

        Map<String, Object> response = new LinkedHashMap<>();
        response.put("CANDIDATES", candidates);
        response.put("OBJECT_TYPE", template.objectType());
        response.put("SNAPSHOT_ID", snapshotId);
        response.put("RESULT_COMPLETENESS", truncated ? TRUNCATED : COMPLETE);
        response.put("SOURCE_EXTRACTED_AT", sourceExtractedAt == null ? "unknown" : sourceExtractedAt);

        Map<String, Object> data = new LinkedHashMap<>();
        capability.executor().outputMapping().forEach((logicalName, physicalName) ->
                data.put(logicalName, response.getOrDefault(physicalName, "")));

        long duration = System.currentTimeMillis() - start;
        Map<String, Object> metadata = new LinkedHashMap<>();
        metadata.put("queryTemplateId", queryTemplateId);
        metadata.put("snapshotId", snapshotId);
        metadata.put("sourceExtractedAt", sourceExtractedAt == null ? "unknown" : sourceExtractedAt);
        metadata.put("durationMs", duration);
        return TechnicalExecutionResult.success(
                request.traceId(), request.capabilityId(), request.bindingId(),
                request.executorType(), List.of(), data, duration, metadata);
    }

    // -- helpers --------------------------------------------------------------

    private Map<String, EntityRow> entitiesInScope(PhysicalMappings.Template template,
                                                   TrustedScope scope) throws SQLException {
        Map<String, EntityRow> entities = new LinkedHashMap<>();
        for (Map<String, Object> row : rows.query(
                MasterdataQueries.ENTITIES_IN_SCOPE,
                List.of(template.objectType(), scope.sourceSystems(), scope.clients()))) {
            EntityRow entity = new EntityRow(
                    String.valueOf(row.get("source_system")),
                    String.valueOf(row.get("client")),
                    String.valueOf(row.get("object_type")),
                    String.valueOf(row.get("canonical_code")),
                    String.valueOf(row.get("status")),
                    parseAttributes(row.get("attributes")));
            entities.put(entity.code, entity);
        }
        return entities;
    }

    private static final com.fasterxml.jackson.databind.ObjectMapper JSON =
            new com.fasterxml.jackson.databind.ObjectMapper();

    @SuppressWarnings("unchecked")
    private static Map<String, Object> parseAttributes(Object raw) {
        if (raw instanceof Map<?, ?> map) {
            Map<String, Object> result = new LinkedHashMap<>();
            map.forEach((k, v) -> result.put(String.valueOf(k), v));
            return result;
        }
        if (raw == null) {
            return Map.of();
        }
        try {
            return JSON.readValue(String.valueOf(raw), Map.class);
        } catch (Exception e) {
            return Map.of();
        }
    }

    private static Map<String, List<Map<String, Object>>> groupBy(List<Map<String, Object>> rows) {
        Map<String, List<Map<String, Object>>> grouped = new LinkedHashMap<>();
        for (Map<String, Object> row : rows) {
            grouped.computeIfAbsent(String.valueOf(row.get("canonical_code")), k -> new ArrayList<>())
                    .add(row);
        }
        return grouped;
    }

    private static String displayName(List<Map<String, Object>> descriptions, String language) {
        if (descriptions.isEmpty()) {
            return "";
        }
        if (language != null) {
            for (Map<String, Object> row : descriptions) {
                if (language.equals(row.get("language")) && Boolean.TRUE.equals(row.get("is_official"))) {
                    return String.valueOf(row.get("description"));
                }
            }
            for (Map<String, Object> row : descriptions) {
                if (language.equals(row.get("language"))) {
                    return String.valueOf(row.get("description"));
                }
            }
        }
        for (Map<String, Object> row : descriptions) {
            if (Boolean.TRUE.equals(row.get("is_official"))) {
                return String.valueOf(row.get("description"));
            }
        }
        return String.valueOf(descriptions.get(0).get("description"));
    }

    private static String logicalInputFor(CapabilityDefinition capability, String orgFilterField) {
        for (CapabilityDefinition.InputField input : capability.inputs()) {
            if (input.name().equalsIgnoreCase(orgFilterField)) {
                return input.name();
            }
        }
        return orgFilterField;
    }

    private static String stringParam(Map<String, Object> parameters,
                                      Map<String, String> inputMapping,
                                      String logicalName,
                                      String physicalName) {
        for (Map.Entry<String, String> entry : inputMapping.entrySet()) {
            if (entry.getValue().equalsIgnoreCase(physicalName)
                    || entry.getKey().equalsIgnoreCase(logicalName)) {
                Object value = parameters.get(entry.getKey());
                return value == null ? null : String.valueOf(value);
            }
        }
        return null;
    }

    private static int intParam(Map<String, Object> parameters,
                                Map<String, String> inputMapping,
                                String logicalName,
                                String physicalName,
                                int defaultValue) {
        String value = stringParam(parameters, inputMapping, logicalName, physicalName);
        if (value == null || value.isBlank()) {
            return defaultValue;
        }
        try {
            return Integer.parseInt(value.trim());
        } catch (NumberFormatException e) {
            throw new IllegalArgumentException("limit must be an integer");
        }
    }

    private static java.util.Set<String> intersect(java.util.Set<String> a, java.util.Set<String> b) {
        java.util.Set<String> result = new java.util.HashSet<>(a);
        result.retainAll(b);
        return result;
    }

    private static String stringOrNull(Object value) {
        return value == null ? null : String.valueOf(value);
    }

    private TechnicalExecutionResult failure(TechnicalExecutionRequest request,
                                             ErrorType type, String message, long start) {
        return TechnicalExecutionResult.failure(
                request.traceId(), request.capabilityId(), request.bindingId(),
                request.executorType(), type, message,
                System.currentTimeMillis() - start);
    }

    private record EntityRow(String sourceSystem, String client, String objectType,
                             String code, String status, Map<String, Object> attributes) {
    }

    private record MatchInfo(String kind, Double score) {
    }

    /** Server-injected trusted scope; requests can only narrow it. */
    record TrustedScope(String principal,
                        List<String> sourceSystems,
                        List<String> clients,
                        Map<String, List<String>> orgScopes) {

        @SuppressWarnings("unchecked")
        static TrustedScope from(Map<String, Object> callerContext) {
            Map<String, Object> context = callerContext == null ? Map.of() : callerContext;
            Object scope = context.get("masterDataScope");
            if (scope instanceof Map<?, ?> map) {
                Object principal = map.get("principal");
                return new TrustedScope(
                        principal == null ? "sandbox" : String.valueOf(principal),
                        stringList(map.get("sourceSystems"), List.of("S4H")),
                        stringList(map.get("clients"), List.of("100")),
                        orgScopesOf(map.get("orgScopes")));
            }
            // Placeholder sandbox scope (spec: not production authorization).
            return new TrustedScope("sandbox", List.of("S4H"), List.of("100"), Map.of());
        }

        private static List<String> stringList(Object value, List<String> fallback) {
            if (value instanceof List<?> list && !list.isEmpty()) {
                return list.stream().map(String::valueOf).toList();
            }
            return fallback;
        }

        private static Map<String, List<String>> orgScopesOf(Object value) {
            if (!(value instanceof Map<?, ?> map)) {
                return Map.of();
            }
            Map<String, List<String>> result = new LinkedHashMap<>();
            map.forEach((key, raw) -> result.put(String.valueOf(key), stringList(raw, java.util.List.<String>of())));
            return result;
        }
    }
}

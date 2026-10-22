package com.sapnexus.gateway.masterdata;

import com.sapnexus.gateway.execution.TechnicalExecutionRequest;
import com.sapnexus.gateway.execution.TechnicalExecutionResult;
import com.sapnexus.gateway.registry.BindingDefinition;
import com.sapnexus.gateway.registry.BindingRegistry;
import com.sapnexus.gateway.registry.CapabilityDefinition;
import com.sapnexus.gateway.registry.CapabilityKind;
import com.sapnexus.gateway.registry.CapabilityRegistry;
import com.sapnexus.gateway.registry.CapabilityStatus;
import com.sapnexus.gateway.registry.SideEffect;
import com.sapnexus.gateway.result.ErrorType;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.sql.SQLException;
import java.sql.SQLTransientConnectionException;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * Unit tests for the adapter's orchestration semantics over a fake row
 * executor (no live database). Retrieval semantics against real PostgreSQL
 * are covered by the Python provider integration tests
 * (agent/tests/test_master_data_pg.py); these tests pin the Java path's
 * ordering, narrowing, truncation, and error taxonomy.
 */
@SuppressWarnings("unchecked")
class PgMasterdataTechnicalAdapterTest {

    private static final String CAPABILITY_ID = "MD.Material.Search";
    private static final String BINDING_ID = "md.material.search-pg";

    private CapabilityRegistry registry;
    private PgMasterdataTechnicalAdapter adapter;
    private FakeRows rows;

    /** Scriptable row executor: maps SQL text to queued row sets per call order. */
    private static final class FakeRows implements MasterdataQueryRunner.RowExecutor {
        private final Map<String, List<List<Map<String, Object>>>> scripted = new LinkedHashMap<>();
        final List<String> executedSql = new ArrayList<>();

        void on(String sql, List<Map<String, Object>> result) {
            scripted.computeIfAbsent(sql, k -> new ArrayList<>()).add(result);
        }

        @Override
        public List<Map<String, Object>> query(String sql, List<Object> params) {
            executedSql.add(sql);
            List<List<Map<String, Object>>> queue = scripted.get(sql);
            if (queue == null || queue.isEmpty()) {
                return List.of();
            }
            return queue.remove(0);
        }
    }

    private static Map<String, Object> row(Object... pairs) {
        Map<String, Object> row = new LinkedHashMap<>();
        for (int i = 0; i < pairs.length; i += 2) {
            row.put(String.valueOf(pairs[i]), pairs[i + 1]);
        }
        return row;
    }

    private CapabilityDefinition capability() {
        return new CapabilityDefinition(
                CAPABILITY_ID, "Material Master Search", "desc",
                CapabilityStatus.active, CapabilityKind.Function, "MD", "EntityCandidateSet",
                "sapnexus:MD_Material_Search", "sapnexus:MaterialSearchFunction",
                List.of(), List.of(),
                new CapabilityDefinition.Executor(
                        "PG_MASTERDATA_READ", null,
                        Map.of("query", "QUERY", "entityKey", "ENTITY_KEY", "plant", "PLANT",
                                "language", "LANGUAGE", "limit", "LIMIT"),
                        Map.of("candidates", "CANDIDATES", "objectType", "OBJECT_TYPE",
                                "snapshotId", "SNAPSHOT_ID", "resultCompleteness", "RESULT_COMPLETENESS"),
                        "md.material.search"),
                new CapabilityDefinition.ExecutorBinding("PG_MASTERDATA_READ", BINDING_ID),
                new CapabilityDefinition.Governance(SideEffect.none, false, "not_required", "internal", true));
    }

    private BindingDefinition binding() {
        return new BindingDefinition(
                BINDING_ID, "PG_MASTERDATA_READ", null, null, null,
                Map.of(), null, List.of(), Map.of("sideEffect", "none"),
                null, null, Map.of(), Map.of(), Map.of(), "md.material.search");
    }

    private PhysicalMappings mappings() {
        return new PhysicalMappings(Map.of(
                "md.material.search",
                new PhysicalMappings.Template(
                        "sapnexus:Material", "material",
                        Map.of("material", "canonical_code"), "plant")));
    }

    private void scriptBaseline() {
        rows.on(MasterdataQueries.ENTITIES_IN_SCOPE, List.of(
                row("source_system", "S4H", "client", "100", "object_type", "sapnexus:Material",
                        "canonical_code", "DEMOA1", "status", "active",
                        "attributes", "{\"sizeDimension\":\"20mm\"}", "snapshot_id", "snap1",
                        "loaded_at", "2026-10-20", "source_extracted_at", "2026-10-01"),
                row("source_system", "S4H", "client", "100", "object_type", "sapnexus:Material",
                        "canonical_code", "DEMOA2", "status", "active",
                        "attributes", "{\"sizeDimension\":\"25mm\"}", "snapshot_id", "snap1",
                        "loaded_at", "2026-10-20", "source_extracted_at", "2026-10-01"),
                row("source_system", "S4H", "client", "100", "object_type", "sapnexus:Material",
                        "canonical_code", "DEMOC9", "status", "inactive",
                        "attributes", "{}", "snapshot_id", "snap1",
                        "loaded_at", "2026-10-20", "source_extracted_at", "2026-10-01")));
        rows.on(MasterdataQueries.CURRENT_SNAPSHOT, List.of(
                row("snapshot_id", "snap1", "source_extracted_at", "2026-10-01", "loaded_at", "2026-10-20")));
    }

    @BeforeEach
    void setUp() {
        registry = mock(CapabilityRegistry.class);
        when(registry.findEnabled(CAPABILITY_ID)).thenReturn(Optional.of(capability()));
        rows = new FakeRows();
        adapter = new PgMasterdataTechnicalAdapter(
                registry, new BindingRegistry(1, List.of(binding())), mappings(), rows);
        scriptBaseline();
    }

    private TechnicalExecutionRequest request(Map<String, Object> parameters) {
        return new TechnicalExecutionRequest(
                "trace-1", CAPABILITY_ID, BINDING_ID, "PG_MASTERDATA_READ",
                null, parameters, Map.of(), Map.of());
    }

    @Test
    void substringSearchReturnsActiveCandidatesWithSnapshotMetadata() {
        rows.on(MasterdataQueries.CODES_BY_EXACT_LABEL, List.of());
        rows.on(MasterdataQueries.CODES_BY_ALIAS, List.of());
        rows.on(MasterdataQueries.CODES_BY_SUBSTRING, List.of(
                row("canonical_code", "DEMOA1"),
                row("canonical_code", "DEMOA2"),
                row("canonical_code", "DEMOC9")));
        rows.on(MasterdataQueries.DESCRIPTIONS, List.of(
                row("canonical_code", "DEMOA1", "language", "zh-CN",
                        "description", "蓝色耐高温密封圈 Ø20", "is_official", true),
                row("canonical_code", "DEMOA2", "language", "zh-CN",
                        "description", "蓝色耐高温密封圈 Ø25", "is_official", true)));
        rows.on(MasterdataQueries.ORG_SCOPES, List.of(
                row("canonical_code", "DEMOA1", "org_field", "plant", "org_value", "1000")));

        TechnicalExecutionResult result = adapter.execute(request(Map.of("query", "密封圈")));

        assertThat(result.success()).isTrue();
        List<Map<String, Object>> candidates =
                (List<Map<String, Object>>) result.data().get("candidates");
        // inactive DEMOC9 is excluded; order follows the match set
        assertThat(candidates).extracting(c -> c.get("canonicalCode"))
                .containsExactly("DEMOA1", "DEMOA2");
        assertThat(candidates.get(0).get("matchKind")).isEqualTo("substring");
        assertThat(result.data().get("snapshotId")).isEqualTo("snap1");
        assertThat(result.data().get("resultCompleteness")).isEqualTo("complete-result-set");
    }

    @Test
    void browseWithoutQueryOrKeyListsActiveInScopeEntities() {
        rows.on(MasterdataQueries.DESCRIPTIONS, List.of(
                row("canonical_code", "DEMOA1", "language", "zh-CN",
                        "description", "蓝色耐高温密封圈 Ø20", "is_official", true),
                row("canonical_code", "DEMOA2", "language", "zh-CN",
                        "description", "蓝色耐高温密封圈 Ø25", "is_official", true)));
        rows.on(MasterdataQueries.ORG_SCOPES, List.of(
                row("canonical_code", "DEMOA1", "org_field", "plant", "org_value", "1000")));

        TechnicalExecutionResult result = adapter.execute(request(Map.of()));

        assertThat(result.success()).isTrue();
        List<Map<String, Object>> candidates =
                (List<Map<String, Object>>) result.data().get("candidates");
        // inactive DEMOC9 is excluded; browse lists codes in sorted order
        assertThat(candidates).extracting(c -> c.get("canonicalCode"))
                .containsExactly("DEMOA1", "DEMOA2");
        assertThat(candidates.get(0).get("matchKind")).isEqualTo("browse");
        assertThat(result.data().get("resultCompleteness")).isEqualTo("complete-result-set");
        // no retrieval queries are issued in browse mode
        assertThat(rows.executedSql).doesNotContain(MasterdataQueries.CODES_BY_SUBSTRING);
        assertThat(rows.executedSql).doesNotContain(MasterdataQueries.CODES_BY_TRIGRAM);
    }

    @Test
    void exactCodeMissDoesNotFallIntoBrowse() {
        TechnicalExecutionResult result = adapter.execute(request(Map.of("entityKey", "NOPE")));

        assertThat(result.success()).isTrue();
        List<Map<String, Object>> candidates =
                (List<Map<String, Object>>) result.data().get("candidates");
        assertThat(candidates).isEmpty();
    }

    @Test
    void exactCodeWinsOverTextRetrieval() {
        TechnicalExecutionResult result = adapter.execute(request(Map.of("entityKey", "demoa1")));

        assertThat(result.success()).isTrue();
        List<Map<String, Object>> candidates =
                (List<Map<String, Object>>) result.data().get("candidates");
        assertThat(candidates).hasSize(1);
        assertThat(candidates.get(0).get("canonicalCode")).isEqualTo("DEMOA1");
        assertThat(candidates.get(0).get("matchKind")).isEqualTo("exact-code");
        // no text retrieval queries were issued at all
        assertThat(rows.executedSql).doesNotContain(MasterdataQueries.CODES_BY_SUBSTRING);
        assertThat(rows.executedSql).doesNotContain(MasterdataQueries.CODES_BY_TRIGRAM);
    }

    @Test
    void orgFilterOutsideTrustedScopeIsDeniedNotWidened() {
        TechnicalExecutionRequest scoped = new TechnicalExecutionRequest(
                "trace-2", CAPABILITY_ID, BINDING_ID, "PG_MASTERDATA_READ", null,
                Map.of("query", "密封圈", "plant", "2000"), Map.of(),
                Map.of("masterDataScope",
                        Map.of("principal", "plant-user", "sourceSystems", List.of("S4H"),
                                "clients", List.of("100"), "orgScopes", Map.of("plant", List.of("1000")))));

        TechnicalExecutionResult result = adapter.execute(scoped);

        assertThat(result.success()).isFalse();
        assertThat(result.errorType()).isEqualTo(ErrorType.MASTERDATA_PERMISSION_DENIED);
    }

    @Test
    void limitOutOfBoundsIsInvalidRequest() {
        TechnicalExecutionResult result = adapter.execute(request(Map.of("limit", 500)));
        assertThat(result.success()).isFalse();
        assertThat(result.errorType()).isEqualTo(ErrorType.MASTERDATA_INVALID_REQUEST);
    }

    @Test
    void truncationIsReportedAsPartial() {
        rows.on(MasterdataQueries.CODES_BY_EXACT_LABEL, List.of());
        rows.on(MasterdataQueries.CODES_BY_ALIAS, List.of());
        rows.on(MasterdataQueries.CODES_BY_SUBSTRING, List.of(
                row("canonical_code", "DEMOA1"), row("canonical_code", "DEMOA2")));
        rows.on(MasterdataQueries.DESCRIPTIONS, List.of(
                row("canonical_code", "DEMOA1", "language", "zh-CN", "description", "d1", "is_official", true)));
        rows.on(MasterdataQueries.ORG_SCOPES, List.of());

        TechnicalExecutionResult result = adapter.execute(
                request(Map.of("query", "密封圈", "limit", 1)));

        assertThat(result.success()).isTrue();
        assertThat(result.data().get("resultCompleteness")).isEqualTo("partial-truncated");
        List<Map<String, Object>> candidates =
                (List<Map<String, Object>>) result.data().get("candidates");
        assertThat(candidates).hasSize(1);
    }

    @Test
    void connectionFailureMapsToUnavailableWithoutDetails() {
        MasterdataQueryRunner.RowExecutor failing = (sql, params) -> {
            throw new SQLTransientConnectionException("connection refused: secret-host:5432");
        };
        PgMasterdataTechnicalAdapter broken = new PgMasterdataTechnicalAdapter(
                registry, new BindingRegistry(1, List.of(binding())), mappings(), failing);

        TechnicalExecutionResult result = broken.execute(request(Map.of("query", "x")));

        assertThat(result.success()).isFalse();
        assertThat(result.errorType()).isEqualTo(ErrorType.MASTERDATA_UNAVAILABLE);
        assertThat(result.messages().get(0).message()).doesNotContain("secret-host");
    }

    @Test
    void unknownTemplateIsInvalidRequest() {
        BindingDefinition bad = new BindingDefinition(
                BINDING_ID, "PG_MASTERDATA_READ", null, null, null,
                Map.of(), null, List.of(), Map.of("sideEffect", "none"),
                null, null, Map.of(), Map.of(), Map.of(), "md.ghost.search");
        PgMasterdataTechnicalAdapter ghost = new PgMasterdataTechnicalAdapter(
                registry, new BindingRegistry(1, List.of(bad)), mappings(), rows);

        TechnicalExecutionResult result = ghost.execute(request(Map.of("query", "x")));
        assertThat(result.success()).isFalse();
        assertThat(result.errorType()).isEqualTo(ErrorType.MASTERDATA_INVALID_REQUEST);
    }

    @Test
    void likeEscapeKeepsWildcardsLiteral() {
        assertThat(MasterdataQueries.likeEscape("5% 折扣")).isEqualTo("5\\% 折扣");
        assertThat(MasterdataQueries.likeEscape("A_B\\C")).isEqualTo("A\\_B\\\\C");
    }
}

package com.sapnexus.gateway.approval;

import static org.junit.jupiter.api.Assertions.assertEquals;

import java.nio.file.Path;
import java.time.Instant;
import java.util.Map;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

class PlanApprovalStoreTest {

    @TempDir
    Path tempDir;

    @Test
    void inMemoryStatusTransitionsPreservePlanAwareBindings() {
        InMemoryApprovalStore store = new InMemoryApprovalStore();
        assertPlanAwareBindingsSurviveExecution(store, planAwareRecord("appr-memory"));
    }

    @Test
    void durableStatusTransitionsAndRestartPreservePlanAwareBindings() {
        FileDurableApprovalStore store = new FileDurableApprovalStore(tempDir, "worker-a", 60_000L);
        ApprovalRecord original = planAwareRecord("appr-durable");

        assertPlanAwareBindingsSurviveExecution(store, original);

        FileDurableApprovalStore restarted = new FileDurableApprovalStore(tempDir, "worker-b", 60_000L);
        assertBindings(original, restarted.find(original.approvalId()).orElseThrow());
    }

    private void assertPlanAwareBindingsSurviveExecution(ApprovalStore store, ApprovalRecord original) {
        store.save(original);
        ApprovalRecord executing = store.claimForExecution(original.approvalId()).orElseThrow();
        assertEquals("executing", executing.status());
        assertBindings(original, executing);

        store.markExecuted(original.approvalId());
        ApprovalRecord executed = store.find(original.approvalId()).orElseThrow();
        assertEquals("executed", executed.status());
        assertBindings(original, executed);
    }

    private void assertBindings(ApprovalRecord expected, ApprovalRecord actual) {
        assertEquals(expected.registrySnapshotId(), actual.registrySnapshotId());
        assertEquals(expected.capabilityVersion(), actual.capabilityVersion());
        assertEquals(expected.approvalSubjectHash(), actual.approvalSubjectHash());
    }

    private ApprovalRecord planAwareRecord(String approvalId) {
        Map<String, String> parameters = Map.of("material", "M001");
        return new ApprovalRecord(
                approvalId,
                "MM.PR.CreateDraft",
                new ParameterSnapshotHasher().hash(parameters),
                parameters,
                "run-owner",
                Instant.parse("2026-08-05T08:00:00Z"),
                Instant.parse("2026-08-05T08:10:00Z"),
                "approved",
                "snapshot-21",
                "2.1.0",
                "sha256:subject-21");
    }
}

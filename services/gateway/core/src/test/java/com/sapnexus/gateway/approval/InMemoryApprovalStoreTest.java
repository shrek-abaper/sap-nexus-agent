package com.sapnexus.gateway.approval;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.time.Instant;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.Callable;
import java.util.concurrent.Executors;
import org.junit.jupiter.api.Test;

class InMemoryApprovalStoreTest {

    private ApprovalRecord sampleRecord(String approvalId, String status) {
        return new ApprovalRecord(
                approvalId,
                "MM.PR.CreateDraft",
                "sha256:abc",
                Map.of("material", "M001", "plant", "1000"),
                "user@example.com",
                Instant.now(),
                Instant.now().plusSeconds(600),
                status
        );
    }

    @Test
    void saveAndFindById() {
        InMemoryApprovalStore store = new InMemoryApprovalStore();
        ApprovalRecord record = sampleRecord("appr-001", "approved");
        store.save(record);
        Optional<ApprovalRecord> found = store.find("appr-001");
        assertTrue(found.isPresent());
        assertEquals("approved", found.get().status());
    }

    @Test
    void markExecutedTransitionsStatus() {
        InMemoryApprovalStore store = new InMemoryApprovalStore();
        store.save(sampleRecord("appr-002", "approved"));
        store.claimForExecution("appr-002");
        store.markExecuted("appr-002");
        ApprovalRecord found = store.find("appr-002").orElseThrow();
        assertEquals("executed", found.status());
    }

    @Test
    void findNonexistentReturnsEmpty() {
        InMemoryApprovalStore store = new InMemoryApprovalStore();
        assertTrue(store.find("nonexistent").isEmpty());
    }

    @Test
    void markExecutedPreservesOtherFields() {
        InMemoryApprovalStore store = new InMemoryApprovalStore();
        ApprovalRecord original = sampleRecord("appr-003", "approved");
        store.save(original);
        store.claimForExecution("appr-003");
        store.markExecuted("appr-003");
        ApprovalRecord found = store.find("appr-003").orElseThrow();
        assertEquals(original.approvalId(), found.approvalId());
        assertEquals(original.capabilityId(), found.capabilityId());
        assertEquals(original.parameterSnapshotHash(), found.parameterSnapshotHash());
        assertEquals(original.parameters(), found.parameters());
        assertEquals(original.approver(), found.approver());
        assertEquals(original.approvedAt(), found.approvedAt());
        assertEquals(original.expiresAt(), found.expiresAt());
        assertEquals("executed", found.status());
    }

    @Test
    void markExecutedNonexistentIsNoop() {
        InMemoryApprovalStore store = new InMemoryApprovalStore();
        store.markExecuted("nonexistent");
        assertTrue(store.find("nonexistent").isEmpty());
    }

    @Test
    void claimForExecutionTransitionsOnlyApprovedRecord() {
        InMemoryApprovalStore store = new InMemoryApprovalStore();
        store.save(sampleRecord("appr-claim", "approved"));

        assertTrue(store.claimForExecution("appr-claim").isPresent());
        assertEquals("executing", store.find("appr-claim").orElseThrow().status());
        assertTrue(store.claimForExecution("appr-claim").isEmpty());
    }

    @Test
    void concurrentClaimsHaveExactlyOneWinner() throws Exception {
        InMemoryApprovalStore store = new InMemoryApprovalStore();
        store.save(sampleRecord("appr-race", "approved"));
        var executor = Executors.newFixedThreadPool(8);
        try {
            var claims = java.util.stream.IntStream.range(0, 20)
                    .mapToObj(ignored -> (Callable<Boolean>) () ->
                            store.claimForExecution("appr-race").isPresent())
                    .toList();
            long winners = executor.invokeAll(claims).stream()
                    .filter(future -> {
                        try {
                            return future.get();
                        } catch (Exception exception) {
                            throw new AssertionError(exception);
                        }
                    })
                    .count();
            assertEquals(1, winners);
        } finally {
            executor.shutdownNow();
        }
    }
}

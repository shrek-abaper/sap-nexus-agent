package com.sapnexus.gateway.approval;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.time.Instant;
import java.util.Map;
import java.util.Optional;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import java.nio.file.Path;

class FileDurableApprovalStoreTest {

    @TempDir
    Path tempDir;

    private ApprovalRecord sampleRecord(String approvalId, String status) {
        return new ApprovalRecord(
                approvalId,
                "MM.PR.CreateDraft",
                "sha256:abc",
                Map.of("material", "M001", "plant", "1000"),
                "user@example.com",
                Instant.parse("2026-08-02T10:00:00Z"),
                Instant.parse("2026-08-02T10:10:00Z"),
                status
        );
    }

    @Test
    void saveAndFindById() {
        FileDurableApprovalStore store = new FileDurableApprovalStore(tempDir, "worker-test", 60_000L);
        store.save(sampleRecord("appr-001", "approved"));
        Optional<ApprovalRecord> found = store.find("appr-001");
        assertTrue(found.isPresent());
        assertEquals("approved", found.get().status());
        assertEquals("MM.PR.CreateDraft", found.get().capabilityId());
    }

    @Test
    void saveDuplicateReturnsFalse() {
        FileDurableApprovalStore store = new FileDurableApprovalStore(tempDir, "worker-test", 60_000L);
        assertTrue(store.save(sampleRecord("appr-002", "approved")));
        assertFalse(store.save(sampleRecord("appr-002", "approved")));
    }

    @Test
    void findNonexistentReturnsEmpty() {
        FileDurableApprovalStore store = new FileDurableApprovalStore(tempDir, "worker-test", 60_000L);
        assertTrue(store.find("nonexistent").isEmpty());
    }

    @Test
    void persistsAcrossRestart() {
        FileDurableApprovalStore first = new FileDurableApprovalStore(tempDir, "worker-test", 60_000L);
        first.save(sampleRecord("appr-restart", "approved"));

        FileDurableApprovalStore second = new FileDurableApprovalStore(tempDir, "worker-test", 60_000L);
        Optional<ApprovalRecord> found = second.find("appr-restart");
        assertTrue(found.isPresent());
        assertEquals("approved", found.get().status());
        assertEquals("appr-restart", found.get().approvalId());
    }

    @Test
    void claimTransitionsApprovedToExecuting() {
        FileDurableApprovalStore store = new FileDurableApprovalStore(tempDir, "worker-test", 60_000L);
        store.save(sampleRecord("appr-claim", "approved"));

        Optional<ApprovalRecord> claimed = store.claimForExecution("appr-claim");

        assertTrue(claimed.isPresent());
        assertEquals("executing", claimed.get().status());
        assertEquals("executing", store.find("appr-claim").orElseThrow().status());
    }

    @Test
    void claimNonApprovedReturnsEmpty() {
        FileDurableApprovalStore store = new FileDurableApprovalStore(tempDir, "worker-test", 60_000L);
        store.save(sampleRecord("appr-pending", "pending"));

        assertTrue(store.claimForExecution("appr-pending").isEmpty());
        assertEquals("pending", store.find("appr-pending").orElseThrow().status());
    }

    @Test
    void claimIsIdempotent() {
        FileDurableApprovalStore store = new FileDurableApprovalStore(tempDir, "worker-test", 60_000L);
        store.save(sampleRecord("appr-idem", "approved"));

        assertTrue(store.claimForExecution("appr-idem").isPresent());
        assertTrue(store.claimForExecution("appr-idem").isEmpty());
    }

    @Test
    void claimCreatesLeaseFileWithWorkerAndExpiry() throws Exception {
        FileDurableApprovalStore store = new FileDurableApprovalStore(tempDir, "worker-test", 60_000L);
        store.save(sampleRecord("appr-lease", "approved"));
        store.claimForExecution("appr-lease");

        java.nio.file.Path leaseFile = tempDir.resolve("leases").resolve("appr-lease.json");
        assertTrue(java.nio.file.Files.exists(leaseFile));
        LeaseInfo lease = ApprovalRecordCodec.leaseFromJson(java.nio.file.Files.readString(leaseFile));
        assertEquals("worker-test", lease.workerId());
        assertTrue(lease.expiresAt().isAfter(Instant.now()));
    }

    @Test
    void concurrentClaimsHaveExactlyOneWinner() throws Exception {
        FileDurableApprovalStore store = new FileDurableApprovalStore(tempDir, "worker-test", 60_000L);
        store.save(sampleRecord("appr-race", "approved"));
        var executor = java.util.concurrent.Executors.newFixedThreadPool(8);
        try {
            var claims = java.util.stream.IntStream.range(0, 20)
                    .mapToObj(ignored -> (java.util.concurrent.Callable<Boolean>) () ->
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

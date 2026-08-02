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
}

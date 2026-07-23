package com.sapnexus.gateway.approval;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.time.Instant;
import java.util.HashMap;
import java.util.Map;
import org.junit.jupiter.api.Test;

class ApprovalRecordTest {

    private ApprovalRecord recordWithExpiry(Instant expiresAt, String status) {
        return new ApprovalRecord(
                "appr-100",
                "MM.PR.CreateDraft",
                "sha256:abc",
                Map.of("material", "M001", "plant", "1000"),
                "user@example.com",
                Instant.parse("2026-07-16T10:00:00Z"),
                expiresAt,
                status
        );
    }

    @Test
    void isExpiredReturnsTrueAfterExpiry() {
        ApprovalRecord record = recordWithExpiry(
                Instant.parse("2026-07-16T10:05:00Z"),
                "approved"
        );
        assertTrue(record.isExpired(Instant.parse("2026-07-16T10:05:01Z")));
    }

    @Test
    void isExpiredReturnsFalseBeforeExpiry() {
        ApprovalRecord record = recordWithExpiry(
                Instant.parse("2026-07-16T10:05:00Z"),
                "approved"
        );
        assertFalse(record.isExpired(Instant.parse("2026-07-16T10:04:59Z")));
    }

    @Test
    void isExpiredReturnsFalseAtExactExpiry() {
        ApprovalRecord record = recordWithExpiry(
                Instant.parse("2026-07-16T10:05:00Z"),
                "approved"
        );
        assertFalse(record.isExpired(Instant.parse("2026-07-16T10:05:00Z")));
    }

    @Test
    void isExecutedReturnsTrueForExecutedStatus() {
        ApprovalRecord record = recordWithExpiry(
                Instant.parse("2026-07-16T10:05:00Z"),
                "executed"
        );
        assertTrue(record.isExecuted());
    }

    @Test
    void isExecutedReturnsFalseForNonExecutedStatus() {
        ApprovalRecord pending = recordWithExpiry(
                Instant.parse("2026-07-16T10:05:00Z"),
                "pending"
        );
        ApprovalRecord approved = recordWithExpiry(
                Instant.parse("2026-07-16T10:05:00Z"),
                "approved"
        );
        ApprovalRecord rejected = recordWithExpiry(
                Instant.parse("2026-07-16T10:05:00Z"),
                "rejected"
        );
        assertFalse(pending.isExecuted());
        assertFalse(approved.isExecuted());
        assertFalse(rejected.isExecuted());
    }

    @Test
    void parametersAreDefensivelyCopiedAndImmutable() {
        HashMap<String, String> mutable = new HashMap<>();
        mutable.put("material", "M001");
        mutable.put("plant", "1000");
        ApprovalRecord record = new ApprovalRecord(
                "appr-200",
                "MM.PR.CreateDraft",
                "sha256:abc",
                mutable,
                "user@example.com",
                Instant.parse("2026-07-16T10:00:00Z"),
                Instant.parse("2026-07-16T10:05:00Z"),
                "approved"
        );
        // Mutate the original map after construction
        mutable.put("plant", "TAMPERED");
        mutable.put("extra", "INJECTED");
        // Record must be unaffected by external mutation
        assertEquals("1000", record.parameters().get("plant"));
        assertEquals(2, record.parameters().size());
        assertFalse(record.parameters().containsKey("extra"));
        // Returned map must be unmodifiable
        assertThrows(
                UnsupportedOperationException.class,
                () -> record.parameters().put("x", "y"));
    }

    @Test
    void nullParametersAreReplacedWithEmptyImmutableMap() {
        ApprovalRecord record = new ApprovalRecord(
                "appr-201",
                "MM.PR.CreateDraft",
                "sha256:abc",
                null,
                "user@example.com",
                Instant.parse("2026-07-16T10:00:00Z"),
                Instant.parse("2026-07-16T10:05:00Z"),
                "approved"
        );
        assertNotNull(record.parameters());
        assertTrue(record.parameters().isEmpty());
        assertThrows(
                UnsupportedOperationException.class,
                () -> record.parameters().put("x", "y"));
    }
}

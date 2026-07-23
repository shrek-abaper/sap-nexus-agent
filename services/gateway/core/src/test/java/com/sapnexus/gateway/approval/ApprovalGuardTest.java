package com.sapnexus.gateway.approval;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.time.Instant;
import java.util.Map;

import com.sapnexus.gateway.result.ErrorType;
import org.junit.jupiter.api.Test;

class ApprovalGuardTest {

    private final ApprovalGuard guard = new ApprovalGuard();
    private final ParameterSnapshotHasher hasher = new ParameterSnapshotHasher();
    private final Instant now = Instant.parse("2026-07-16T10:05:00Z");

    private ApprovalRecord record(String status, Instant expiresAt) {
        return new ApprovalRecord(
                "appr-001",
                "MM.PR.CreateDraft",
                hasher.hash(Map.of("material", "M001")),
                Map.of("material", "M001"),
                "user@example.com",
                Instant.parse("2026-07-16T10:00:00Z"),
                expiresAt,
                status
        );
    }

    @Test
    void rejectsWhenRecordMissing() {
        ApprovalGuardResult result = check(null, Map.of("material", "M001"), null);
        assertEquals(ErrorType.APPROVAL_REQUIRED, result.errorType());
        assertTrue(result.rejected());
    }

    @Test
    void rejectsWhenExpired() {
        ApprovalRecord expired = record("approved", Instant.parse("2026-07-16T10:01:00Z"));
        ApprovalGuardResult result = check(expired, expired.parameters(), expired.parameterSnapshotHash());
        assertEquals(ErrorType.APPROVAL_EXPIRED, result.errorType());
    }

    @Test
    void rejectsWhenVersionMismatch() {
        ApprovalRecord approved = record("approved", Instant.parse("2026-07-16T10:10:00Z"));
        ApprovalGuardResult result = check(approved, approved.parameters(), "sha256:different");
        assertEquals(ErrorType.APPROVAL_VERSION_MISMATCH, result.errorType());
    }

    @Test
    void rejectsWhenDuplicateExecuted() {
        ApprovalRecord executed = record("executed", Instant.parse("2026-07-16T10:10:00Z"));
        ApprovalGuardResult result = check(executed, executed.parameters(), executed.parameterSnapshotHash());
        assertEquals(ErrorType.APPROVAL_DUPLICATE, result.errorType());
    }

    @Test
    void passesWhenApprovedAndValid() {
        ApprovalRecord approved = record("approved", Instant.parse("2026-07-16T10:10:00Z"));
        ApprovalGuardResult result = check(approved, approved.parameters(), approved.parameterSnapshotHash());
        assertTrue(result.passed());
        assertEquals(ErrorType.NONE, result.errorType());
    }

    @Test
    void rejectsWhenActualParametersDifferFromApprovedSnapshot() {
        ApprovalRecord approved = record("approved", Instant.parse("2026-07-16T10:10:00Z"));
        ApprovalGuardResult result = check(
                approved, Map.of("material", "M002"), approved.parameterSnapshotHash());
        assertEquals(ErrorType.APPROVAL_VERSION_MISMATCH, result.errorType());
    }

    @Test
    void rejectsWhenStoredParametersDoNotMatchStoredHash() {
        ApprovalRecord approved = new ApprovalRecord(
                "appr-001", "MM.PR.CreateDraft", hasher.hash(Map.of("material", "M001")),
                Map.of("material", "M002"), "user@example.com",
                Instant.parse("2026-07-16T10:00:00Z"),
                Instant.parse("2026-07-16T10:10:00Z"), "approved");
        ApprovalGuardResult result = check(
                approved, Map.of("material", "M001"), approved.parameterSnapshotHash());
        assertEquals(ErrorType.APPROVAL_VERSION_MISMATCH, result.errorType());
    }

    @Test
    void rejectsWhenCapabilityDiffersFromApprovedRecord() {
        ApprovalRecord approved = record("approved", Instant.parse("2026-07-16T10:10:00Z"));
        ApprovalGuardResult result = guard.check(
                approved, "MM.Other.Write", Map.of("material", "M001"),
                approved.parameterSnapshotHash(), now);
        assertEquals(ErrorType.APPROVAL_VERSION_MISMATCH, result.errorType());
    }

    @Test
    void rejectsNonApprovedState() {
        ApprovalRecord pending = record("pending", Instant.parse("2026-07-16T10:10:00Z"));
        ApprovalGuardResult result = check(
                pending, pending.parameters(), pending.parameterSnapshotHash());
        assertEquals(ErrorType.APPROVAL_REQUIRED, result.errorType());
    }

    private ApprovalGuardResult check(
            ApprovalRecord record, Map<String, ?> parameters, String requestHash) {
        Map<String, Object> currentParameters = parameters.entrySet().stream().collect(
                java.util.stream.Collectors.toMap(Map.Entry::getKey, Map.Entry::getValue));
        return guard.check(record, "MM.PR.CreateDraft", currentParameters, requestHash, now);
    }
}

package com.sapnexus.gateway.approval;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.time.Instant;
import java.util.HashMap;
import java.util.Map;

import com.sapnexus.gateway.result.ErrorType;
import org.junit.jupiter.api.Test;

class PlanApprovalGuardTest {

    private static final String SNAPSHOT_ID = "snapshot-21";
    private static final String CAPABILITY_VERSION = "2.1.0";
    private static final String SUBJECT_HASH = "sha256:subject-21";

    private final ApprovalGuard guard = new ApprovalGuard();
    private final ParameterSnapshotHasher hasher = new ParameterSnapshotHasher();
    private final Instant now = Instant.parse("2026-08-05T08:05:00Z");

    @Test
    void acceptsMatchingPlanAwareApprovalBindings() {
        ApprovalRecord approved = planAwareRecord(SNAPSHOT_ID, CAPABILITY_VERSION, SUBJECT_HASH);

        ApprovalGuardResult result = check(
                approved, SNAPSHOT_ID, CAPABILITY_VERSION, SUBJECT_HASH);

        assertTrue(result.passed());
        assertEquals(ErrorType.NONE, result.errorType());
    }

    @Test
    void rejectsEveryPlanAwareBindingMismatch() {
        ApprovalRecord approved = planAwareRecord(SNAPSHOT_ID, CAPABILITY_VERSION, SUBJECT_HASH);

        assertVersionMismatch(check(approved, "snapshot-changed", CAPABILITY_VERSION, SUBJECT_HASH));
        assertVersionMismatch(check(approved, SNAPSHOT_ID, "2.2.0", SUBJECT_HASH));
        assertVersionMismatch(check(approved, SNAPSHOT_ID, CAPABILITY_VERSION, "sha256:changed"));
    }

    @Test
    void rejectsIncompletePlanAwareBindings() {
        ApprovalRecord incomplete = planAwareRecord(SNAPSHOT_ID, null, SUBJECT_HASH);

        assertVersionMismatch(check(incomplete, SNAPSHOT_ID, CAPABILITY_VERSION, SUBJECT_HASH));
    }

    @Test
    void keepsLegacyApprovalCompatibleOnlyWithLegacyRequest() {
        Map<String, String> parameters = Map.of("material", "M001");
        ApprovalRecord legacy = new ApprovalRecord(
                "appr-legacy",
                "MM.PR.CreateDraft",
                hasher.hash(parameters),
                parameters,
                "user@example.com",
                Instant.parse("2026-08-05T08:00:00Z"),
                Instant.parse("2026-08-05T08:10:00Z"),
                "approved");

        ApprovalGuardResult legacyResult = guard.check(
                legacy,
                legacy.capabilityId(),
                new HashMap<>(legacy.parameters()),
                legacy.parameterSnapshotHash(),
                now);
        ApprovalGuardResult upgradedRequestResult = check(
                legacy, SNAPSHOT_ID, CAPABILITY_VERSION, SUBJECT_HASH);

        assertTrue(legacyResult.passed());
        assertVersionMismatch(upgradedRequestResult);
    }

    private ApprovalRecord planAwareRecord(
            String registrySnapshotId,
            String capabilityVersion,
            String approvalSubjectHash
    ) {
        Map<String, String> parameters = Map.of("material", "M001");
        return new ApprovalRecord(
                "appr-plan-21",
                "MM.PR.CreateDraft",
                hasher.hash(parameters),
                parameters,
                "run-owner",
                Instant.parse("2026-08-05T08:00:00Z"),
                Instant.parse("2026-08-05T08:10:00Z"),
                "approved",
                registrySnapshotId,
                capabilityVersion,
                approvalSubjectHash);
    }

    private ApprovalGuardResult check(
            ApprovalRecord record,
            String registrySnapshotId,
            String capabilityVersion,
            String approvalSubjectHash
    ) {
        return guard.check(
                record,
                record.capabilityId(),
                new HashMap<>(record.parameters()),
                record.parameterSnapshotHash(),
                registrySnapshotId,
                capabilityVersion,
                approvalSubjectHash,
                now);
    }

    private void assertVersionMismatch(ApprovalGuardResult result) {
        assertTrue(result.rejected());
        assertEquals(ErrorType.APPROVAL_VERSION_MISMATCH, result.errorType());
    }
}

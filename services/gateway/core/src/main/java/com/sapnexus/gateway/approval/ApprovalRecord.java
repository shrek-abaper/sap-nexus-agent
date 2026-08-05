package com.sapnexus.gateway.approval;

import java.time.Instant;
import java.util.Map;

/**
 * Immutable snapshot of an approval decision for a WRITE capability invocation.
 *
 * <p>Lifecycle: {@code pending} -> {@code approved} -> {@code executed} (or {@code rejected}).
 * The {@code status} field is the authoritative state-machine marker. Duplicate-submit
 * protection relies on {@link #isExecuted()}; TTL expiry relies on {@link #isExpired(Instant)}.
 *
 * <p>Sensitive data: only the parameter snapshot hash and the parameter map are stored.
 * SAP credentials never appear on this record.
 */
public record ApprovalRecord(
        String approvalId,
        String capabilityId,
        String parameterSnapshotHash,
        Map<String, String> parameters,
        String approver,
        Instant approvedAt,
        Instant expiresAt,
        String status,
        String registrySnapshotId,
        String capabilityVersion,
        String approvalSubjectHash
) {
    public ApprovalRecord {
        parameters = parameters == null ? Map.of() : Map.copyOf(parameters);
    }

    public ApprovalRecord(
            String approvalId,
            String capabilityId,
            String parameterSnapshotHash,
            Map<String, String> parameters,
            String approver,
            Instant approvedAt,
            Instant expiresAt,
            String status
    ) {
        this(
                approvalId,
                capabilityId,
                parameterSnapshotHash,
                parameters,
                approver,
                approvedAt,
                expiresAt,
                status,
                null,
                null,
                null);
    }

    public boolean isExpired(Instant now) {
        return now.isAfter(expiresAt);
    }

    public boolean isExecuted() {
        return "executed".equals(status);
    }
}

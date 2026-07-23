package com.sapnexus.gateway.approval;

import java.time.Instant;
import java.util.Map;

import com.sapnexus.gateway.result.ErrorType;
import org.springframework.stereotype.Component;

@Component
public class ApprovalGuard {
    private final ParameterSnapshotHasher parameterSnapshotHasher = new ParameterSnapshotHasher();

    public ApprovalGuardResult check(
            ApprovalRecord record,
            String capabilityId,
            Map<String, Object> currentParameters,
            String requestParameterHash,
            Instant now
    ) {
        if (record == null) {
            return ApprovalGuardResult.rejected(ErrorType.APPROVAL_REQUIRED);
        }
        if (record.expiresAt() == null || record.approvedAt() == null) {
            return ApprovalGuardResult.rejected(ErrorType.APPROVAL_REQUIRED);
        }
        if (record.isExpired(now)) {
            return ApprovalGuardResult.rejected(ErrorType.APPROVAL_EXPIRED);
        }
        if (record.isExecuted() || "executing".equals(record.status())) {
            return ApprovalGuardResult.rejected(ErrorType.APPROVAL_DUPLICATE);
        }
        if (!"approved".equals(record.status())) {
            return ApprovalGuardResult.rejected(ErrorType.APPROVAL_REQUIRED);
        }
        String recordHash = record.parameterSnapshotHash();
        if (!record.capabilityId().equals(capabilityId)
                || !parameterSnapshotHasher.hash(record.parameters()).equals(recordHash)
                || !parameterSnapshotHasher.hash(currentParameters).equals(recordHash)
                || !recordHash.equals(requestParameterHash)) {
            return ApprovalGuardResult.rejected(ErrorType.APPROVAL_VERSION_MISMATCH);
        }
        return new ApprovalGuardResult(ErrorType.NONE, false);
    }
}

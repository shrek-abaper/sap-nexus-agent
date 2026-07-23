package com.sapnexus.gateway.approval;

import java.util.Optional;

/**
 * In-process store for {@link ApprovalRecord}.
 *
 * <p>The ApprovalGuard (Task 5) consults this store to enforce the four approval
 * invariants: presence, TTL, snapshot-hash match, and duplicate-submit. JSONL trace
 * remains the authoritative durable store; this in-memory store provides the
 * process-local index for duplicate protection (per design doc: MVP accepts index
 * loss on restart).
 */
public interface ApprovalStore {

    boolean save(ApprovalRecord record);

    Optional<ApprovalRecord> find(String approvalId);

    Optional<ApprovalRecord> claimForExecution(String approvalId);

    void markExecuted(String approvalId);
}

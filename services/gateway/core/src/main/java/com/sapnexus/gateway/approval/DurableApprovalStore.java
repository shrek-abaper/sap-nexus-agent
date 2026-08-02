package com.sapnexus.gateway.approval;

import java.util.List;

/**
 * Durable extension of {@link ApprovalStore}.
 *
 * <p>Preserves the four-method contract (save / find / claimForExecution / markExecuted)
 * and adds durable recovery + lease management semantics. The four inherited methods
 * are implemented with durable persistence + lease integration:
 * <ul>
 *   <li>{@link #claimForExecution} atomically transitions approved -&gt; executing
 *       and binds a lease (default workerId = worker-${PID}, TTL 60s).</li>
 *   <li>{@link #markExecuted} atomically transitions executing -&gt; executed
 *       and releases the lease.</li>
 * </ul>
 */
public interface DurableApprovalStore extends ApprovalStore {

    /**
     * Recover all approvals from the durable store on restart.
     * Non-terminal states (pending / approved / executing) are recoverable;
     * terminal states (executed / rejected) are loaded for audit queries only.
     */
    List<ApprovalRecord> recoverAll();

    /**
     * Reconcile durable store internal consistency on recovery.
     * Validates lease &lt;-&gt; record status consistency; drift fails closed.
     */
    void reconcile();

    /**
     * Claim lease for an approval (three states: claimed / rejected / force-claimed).
     * Used in recovery scenarios where a worker takes over an expired lease.
     */
    LeaseOutcome claimLease(String approvalId, String workerId, long ttlMs);

    /** Release lease (only if workerId matches the current holder). */
    void releaseLease(String approvalId, String workerId);

    /** Renew lease (only if workerId matches the current holder). */
    void renewLease(String approvalId, String workerId, long ttlMs);
}

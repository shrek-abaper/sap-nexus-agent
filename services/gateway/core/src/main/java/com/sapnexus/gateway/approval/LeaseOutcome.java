package com.sapnexus.gateway.approval;

import java.time.Instant;

/**
 * Lease operation outcome (three states, inspired by item-1 TypeScript LeaseOutcome).
 */
public sealed interface LeaseOutcome {
    /** Normal claim succeeded. */
    record Claimed() implements LeaseOutcome {}

    /** Lease not expired and held by a different worker (fail-closed). */
    record Rejected(String holder, Instant expiresAt) implements LeaseOutcome {}

    /** Lease expired, forcibly taken over (previousHolder recorded for audit). */
    record ForceClaimed(String previousHolder) implements LeaseOutcome {}
}

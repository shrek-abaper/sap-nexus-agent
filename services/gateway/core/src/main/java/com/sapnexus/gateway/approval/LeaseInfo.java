package com.sapnexus.gateway.approval;

import java.time.Instant;

/**
 * Lease file payload: which worker holds the lease and when it expires.
 */
public record LeaseInfo(String workerId, Instant expiresAt) {}

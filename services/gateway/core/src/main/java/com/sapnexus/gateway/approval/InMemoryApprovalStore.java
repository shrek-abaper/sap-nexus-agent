package com.sapnexus.gateway.approval;

import java.util.Optional;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ConcurrentMap;
import java.util.concurrent.atomic.AtomicReference;

import org.springframework.stereotype.Component;

/**
 * Process-local {@link ApprovalStore} backed by a {@link ConcurrentHashMap}.
 *
 * <p>State transitions are applied atomically via {@link ConcurrentMap#compute} so
 * concurrent markExecuted invocations cannot observe a half-updated record.
 */
@Component
public class InMemoryApprovalStore implements ApprovalStore {
    private final ConcurrentMap<String, ApprovalRecord> store = new ConcurrentHashMap<>();

    @Override
    public boolean save(ApprovalRecord record) {
        return store.putIfAbsent(record.approvalId(), record) == null;
    }

    @Override
    public Optional<ApprovalRecord> find(String approvalId) {
        return Optional.ofNullable(store.get(approvalId));
    }

    @Override
    public Optional<ApprovalRecord> claimForExecution(String approvalId) {
        AtomicReference<ApprovalRecord> claimed = new AtomicReference<>();
        store.computeIfPresent(approvalId, (id, existing) -> {
            if (!"approved".equals(existing.status())) {
                return existing;
            }
            ApprovalRecord executing = withStatus(existing, "executing");
            claimed.set(executing);
            return executing;
        });
        return Optional.ofNullable(claimed.get());
    }

    @Override
    public void markExecuted(String approvalId) {
        store.compute(approvalId, (id, existing) -> {
            if (existing == null || !"executing".equals(existing.status())) {
                return existing;
            }
            return withStatus(existing, "executed");
        });
    }

    private ApprovalRecord withStatus(ApprovalRecord existing, String status) {
        return new ApprovalRecord(
                existing.approvalId(),
                existing.capabilityId(),
                existing.parameterSnapshotHash(),
                existing.parameters(),
                existing.approver(),
                existing.approvedAt(),
                existing.expiresAt(),
                status,
                existing.registrySnapshotId(),
                existing.capabilityVersion(),
                existing.approvalSubjectHash()
        );
    }
}

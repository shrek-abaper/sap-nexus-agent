package com.sapnexus.gateway.approval;

import java.io.IOException;
import java.nio.channels.FileChannel;
import java.nio.channels.FileLock;
import java.nio.channels.OverlappingFileLockException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.nio.file.StandardOpenOption;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.locks.ReentrantLock;
import java.util.function.Supplier;
import java.util.stream.Stream;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Primary;
import org.springframework.stereotype.Component;

/**
 * File-backed reference implementation of {@link DurableApprovalStore}.
 *
 * <p>Layout under {@code <baseDir>/}:
 * <ul>
 *   <li>{@code approvals/<approvalId>.json} - full {@link ApprovalRecord} JSON (tmp+rename).</li>
 *   <li>{@code approvals/<approvalId>.lock} - exclusive lock file (never renamed).</li>
 *   <li>{@code leases/<approvalId>.json} - {@link LeaseInfo} JSON (tmp+rename).</li>
 * </ul>
 *
 * <p>Atomicity: read-modify-write sequences are guarded by a per-approvalId
 * {@link ReentrantLock} (in-process) plus {@link FileChannel#lock()} on the
 * dedicated {@code .lock} file (cross-process, for future multi-worker).
 * Content writes use tmp + {@link Files#move} with REPLACE_EXISTING + ATOMIC_MOVE.
 */
@Component
@Primary
public class FileDurableApprovalStore implements DurableApprovalStore {

    private static final Logger log = LoggerFactory.getLogger(FileDurableApprovalStore.class);
    private static final String DEFAULT_WORKER_ID = "worker-" + ProcessHandle.current().pid();
    private static final long DEFAULT_LEASE_TTL_MS = 60_000L;

    private final Path approvalsDir;
    private final Path leasesDir;
    private final String workerId;
    private final long leaseTtlMs;
    private final ConcurrentHashMap<String, ReentrantLock> locks = new ConcurrentHashMap<>();

    @Autowired
    public FileDurableApprovalStore(
            @Value("${SAP_NEXUS_GATEWAY_DATA_DIR:.gateway-data}") String dataDir) {
        this(java.nio.file.Path.of(dataDir, "durable"), DEFAULT_WORKER_ID, DEFAULT_LEASE_TTL_MS);
    }

    FileDurableApprovalStore(Path baseDir, String workerId, long leaseTtlMs) {
        this.approvalsDir = baseDir.resolve("approvals");
        this.leasesDir = baseDir.resolve("leases");
        this.workerId = workerId;
        this.leaseTtlMs = leaseTtlMs;
        try {
            Files.createDirectories(approvalsDir);
            Files.createDirectories(leasesDir);
        } catch (IOException e) {
            throw new IllegalStateException("Failed to create durable store directories", e);
        }
    }

    // --- ApprovalStore contract (real: save, find; stubs: claim, markExecuted) ---

    @Override
    public boolean save(ApprovalRecord record) {
        String approvalId = record.approvalId();
        return withFileLock(approvalId, () -> {
            Path file = approvalFile(approvalId);
            if (Files.exists(file)) {
                return false;
            }
            try {
                atomicWrite(file, ApprovalRecordCodec.toJson(record));
                return true;
            } catch (IOException e) {
                throw new IllegalStateException("Failed to save approval " + approvalId, e);
            }
        });
    }

    @Override
    public Optional<ApprovalRecord> find(String approvalId) {
        Path file = approvalFile(approvalId);
        if (!Files.exists(file)) {
            return Optional.empty();
        }
        try {
            return Optional.of(ApprovalRecordCodec.fromJson(Files.readString(file)));
        } catch (IOException e) {
            throw new IllegalStateException("Failed to read approval " + approvalId, e);
        }
    }

    @Override
    public Optional<ApprovalRecord> claimForExecution(String approvalId) {
        return withFileLock(approvalId, () -> {
            Path file = approvalFile(approvalId);
            if (!Files.exists(file)) {
                return Optional.<ApprovalRecord>empty();
            }
            try {
                ApprovalRecord existing = ApprovalRecordCodec.fromJson(Files.readString(file));
                if (!"approved".equals(existing.status())) {
                    return Optional.empty();
                }
                ApprovalRecord executing = withStatus(existing, "executing");
                atomicWrite(file, ApprovalRecordCodec.toJson(executing));
                writeLease(approvalId, workerId, leaseTtlMs);
                return Optional.of(executing);
            } catch (IOException e) {
                throw new IllegalStateException("Failed to claim approval " + approvalId, e);
            }
        });
    }

    @Override
    public void markExecuted(String approvalId) {
        withFileLock(approvalId, () -> {
            Path file = approvalFile(approvalId);
            if (!Files.exists(file)) {
                return null;
            }
            try {
                ApprovalRecord existing = ApprovalRecordCodec.fromJson(Files.readString(file));
                if (!"executing".equals(existing.status())) {
                    return null;
                }
                ApprovalRecord executed = withStatus(existing, "executed");
                atomicWrite(file, ApprovalRecordCodec.toJson(executed));
                deleteLease(approvalId);
                return null;
            } catch (IOException e) {
                throw new IllegalStateException("Failed to mark executed " + approvalId, e);
            }
        });
    }

    // --- DurableApprovalStore contract (stubs - implemented in Tasks 5-6) ---

    @Override
    public List<ApprovalRecord> recoverAll() {
        java.util.List<ApprovalRecord> records = new java.util.ArrayList<>();
        try (Stream<Path> files = Files.list(approvalsDir)) {
            files.filter(p -> p.getFileName().toString().endsWith(".json"))
                 .forEach(p -> {
                     try {
                         records.add(ApprovalRecordCodec.fromJson(Files.readString(p)));
                     } catch (IOException e) {
                         throw new IllegalStateException("Failed to recover " + p, e);
                     }
                 });
        } catch (IOException e) {
            throw new IllegalStateException("Failed to scan approvals dir", e);
        }
        return records;
    }

    @Override
    public void reconcile() {
        try (Stream<Path> approvalFiles = Files.list(approvalsDir)) {
            approvalFiles.filter(p -> p.getFileName().toString().endsWith(".json"))
                .forEach(p -> {
                    String approvalId = stripSuffix(p.getFileName().toString(), ".json");
                    try {
                        ApprovalRecord record = ApprovalRecordCodec.fromJson(Files.readString(p));
                        Optional<LeaseInfo> lease = readLease(approvalId);
                        if (lease.isPresent()) {
                            if ("executed".equals(record.status()) || "rejected".equals(record.status())
                                    || "approved".equals(record.status()) || "pending".equals(record.status())) {
                                log.warn("Reconcile: cleaning residual lease for {} (status={})", approvalId, record.status());
                                deleteLease(approvalId);
                            }
                        }
                        // executing + no lease: fail-closed (leave as executing, no auto-recovery)
                    } catch (IOException e) {
                        throw new IllegalStateException("Reconcile failed for " + approvalId, e);
                    }
                });
        } catch (IOException e) {
            throw new IllegalStateException("Failed to scan approvals dir for reconcile", e);
        }
        // orphan leases: lease file with no matching approval file
        try (Stream<Path> leaseFiles = Files.list(leasesDir)) {
            leaseFiles.filter(p -> p.getFileName().toString().endsWith(".json"))
                .forEach(p -> {
                    String approvalId = stripSuffix(p.getFileName().toString(), ".json");
                    if (!Files.exists(approvalFile(approvalId))) {
                        try {
                            log.warn("Reconcile: deleting orphan lease for {}", approvalId);
                            deleteLease(approvalId);
                        } catch (IOException e) {
                            throw new IllegalStateException("Failed to delete orphan lease " + approvalId, e);
                        }
                    }
                });
        } catch (IOException e) {
            throw new IllegalStateException("Failed to scan leases dir for reconcile", e);
        }
    }

    @Override
    public LeaseOutcome claimLease(String approvalId, String workerId, long ttlMs) {
        return withFileLock(approvalId, () -> {
            try {
                Optional<LeaseInfo> existing = readLease(approvalId);
                Instant now = Instant.now();
                if (existing.isPresent()) {
                    LeaseInfo lease = existing.get();
                    boolean expired = !lease.expiresAt().isAfter(now);
                    if (!expired && !lease.workerId().equals(workerId)) {
                        return new LeaseOutcome.Rejected(lease.workerId(), lease.expiresAt());
                    }
                    if (expired && !lease.workerId().equals(workerId)) {
                        String previousHolder = lease.workerId();
                        writeLease(approvalId, workerId, ttlMs);
                        log.warn("Force-claimed lease for {} from previous holder {}", approvalId, previousHolder);
                        return new LeaseOutcome.ForceClaimed(previousHolder);
                    }
                }
                writeLease(approvalId, workerId, ttlMs);
                return new LeaseOutcome.Claimed();
            } catch (IOException e) {
                throw new IllegalStateException("Failed to claim lease " + approvalId, e);
            }
        });
    }

    @Override
    public void releaseLease(String approvalId, String workerId) {
        withFileLock(approvalId, () -> {
            try {
                Optional<LeaseInfo> existing = readLease(approvalId);
                if (existing.isPresent() && existing.get().workerId().equals(workerId)) {
                    deleteLease(approvalId);
                }
                return null;
            } catch (IOException e) {
                throw new IllegalStateException("Failed to release lease " + approvalId, e);
            }
        });
    }

    @Override
    public void renewLease(String approvalId, String workerId, long ttlMs) {
        withFileLock(approvalId, () -> {
            try {
                Optional<LeaseInfo> existing = readLease(approvalId);
                if (existing.isPresent() && existing.get().workerId().equals(workerId)) {
                    writeLease(approvalId, workerId, ttlMs);
                }
                return null;
            } catch (IOException e) {
                throw new IllegalStateException("Failed to renew lease " + approvalId, e);
            }
        });
    }

    // --- helpers ---

    private static String safeName(String approvalId) {
        if (approvalId == null || !approvalId.matches("[a-zA-Z0-9_-]+")) {
            throw new IllegalArgumentException("Invalid approvalId: " + approvalId);
        }
        return approvalId;
    }

    private Path approvalFile(String approvalId) {
        return approvalsDir.resolve(safeName(approvalId) + ".json");
    }

    private Path leaseFile(String approvalId) {
        return leasesDir.resolve(safeName(approvalId) + ".json");
    }

    private Path lockFile(String approvalId) {
        return approvalsDir.resolve(safeName(approvalId) + ".lock");
    }

    private void atomicWrite(Path target, String content) throws IOException {
        Path tmp = target.resolveSibling(target.getFileName() + ".tmp");
        Files.writeString(tmp, content);
        Files.move(tmp, target, StandardCopyOption.REPLACE_EXISTING, StandardCopyOption.ATOMIC_MOVE);
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
                status
        );
    }

    private void writeLease(String approvalId, String workerId, long ttlMs) throws IOException {
        LeaseInfo lease = new LeaseInfo(workerId, Instant.now().plusMillis(ttlMs));
        atomicWrite(leaseFile(approvalId), ApprovalRecordCodec.toJson(lease));
    }

    private Optional<LeaseInfo> readLease(String approvalId) throws IOException {
        Path file = leaseFile(approvalId);
        if (!Files.exists(file)) {
            return Optional.empty();
        }
        return Optional.of(ApprovalRecordCodec.leaseFromJson(Files.readString(file)));
    }

    private void deleteLease(String approvalId) throws IOException {
        Files.deleteIfExists(leaseFile(approvalId));
    }

    private static String stripSuffix(String value, String suffix) {
        return value.endsWith(suffix) ? value.substring(0, value.length() - suffix.length()) : value;
    }

    private ReentrantLock stripeLock(String approvalId) {
        return locks.computeIfAbsent(approvalId, k -> new ReentrantLock());
    }

    /**
     * Acquire in-process ReentrantLock (serializes same-JVM threads), then a
     * cross-process FileChannel.lock on the dedicated .lock file, then run action.
     * ReentrantLock guarantees FileChannel.lock is never contended within one JVM,
     * so OverlappingFileLockException cannot occur in practice.
     */
    private <T> T withFileLock(String approvalId, Supplier<T> action) {
        ReentrantLock stripe = stripeLock(approvalId);
        stripe.lock();
        try {
            try (FileChannel channel = FileChannel.open(lockFile(approvalId),
                    StandardOpenOption.CREATE, StandardOpenOption.WRITE);
                 FileLock ignored = channel.lock()) {
                return action.get();
            } catch (OverlappingFileLockException e) {
                throw new IllegalStateException("Overlapping file lock for " + approvalId, e);
            } catch (IOException e) {
                throw new IllegalStateException("File lock I/O failed for " + approvalId, e);
            }
        } finally {
            stripe.unlock();
        }
    }
}

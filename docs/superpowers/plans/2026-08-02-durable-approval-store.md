---
change: sap-nexus-durable-approval-store
design-doc: docs/superpowers/specs/2026-08-02-durable-approval-store-design.md
base-ref: a7ac4d1ca69cc05f1bec1c3bc48efc7e323d039d
---

# Durable Approval Store Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the process-local `InMemoryApprovalStore` with a file-backed `DurableApprovalStore` so `ApprovalRecord` persists across restarts and supports cross-worker claim/lease anti-replay, while preserving the `ApprovalStore` four-method contract and `ApprovalGuard` semantics unchanged.

**Architecture:** Define a `DurableApprovalStore` interface extending `ApprovalStore` (adds recovery + lease management). Implement a file-backed reference implementation (`FileDurableApprovalStore`) using tmp+rename atomic writes per approval/lease file, in-process `ReentrantLock` (striped by approvalId) for read-modify-write atomicity, and `FileChannel.lock()` on a per-approval `.lock` file for cross-process safety. `LeaseOutcome` is a sealed interface with three states (Claimed / Rejected / ForceClaimed) inspired by item-1's TypeScript `LeaseOutcome`. `InMemoryApprovalStore` is retained unchanged as a test stub; `@Primary` selects the durable store in production.

**Tech Stack:** Java 17 (records, sealed interfaces, `ProcessHandle`), Spring Boot, Gradle (`services/gateway`), Jackson (`jackson-databind` + `jackson-datatype-jsr310` via `spring-boot-starter-web`), JUnit 5 (`@TempDir`).

## Global Constraints

- **Build command:** all Gradle commands run from `services/gateway/` (e.g. `cd services/gateway && ./gradlew :core:test`).
- **Safety contract (Design "安全契约"):** WRITE capabilities MUST NOT execute until Human Approval confirmed — strengthened to durable + cross-restart + cross-worker anti-replay. `claimForExecution` is idempotent (duplicate claim returns empty). Expired approvals are not executable (`expiresAt` persisted and immutable; `approvedAt` is the fixed TTL baseline, preserving the 600s window). `ApprovalRecord` never stores SAP credentials (only `parameterSnapshotHash` + business `parameters` + `approver` + timestamps + status).
- **Do NOT touch:** SSE / incremental cursor (item 4), trusted principal model (item 2), `CapabilityController` execute flow (`find` -> `check` -> `claimForExecution` -> `dispatch` -> `markExecuted`), `ApprovalGuard` four rejection scenarios, `ApprovalRecord` field set, JSONL trace semantics. `ApprovalGuard.java`, `ApprovalRecord.java`, `ApprovalStore.java`, `CapabilityController.java` are NOT modified.
- **TTL baseline (Design §3 / OQ-1):** `approvedAt` is a fixed benchmark; on recovery `isExpired(now)` uses the persisted `expiresAt` via wall-clock. Never reset `approvedAt` (would breach the 600s safety window).
- **Recovery source (Design §5 / D4):** durable store is the authoritative operational index. Reconcile validates internal consistency only — do NOT read agent-side JSONL across services. Drift fails closed.
- **Item-1 dependency (Design § D5):** borrow design patterns only (lease three-state `LeaseOutcome`, tmp+rename, idempotency). Item-1 is TypeScript; Gateway is Java — no cross-language code reuse.
- **Locking model:** `ReentrantLock` (striped per approvalId) serializes same-JVM threads (required for the concurrent-claim test and single-worker correctness). `FileChannel.lock()` on a separate `<approvalId>.lock` file adds cross-process safety for future multi-worker. The `.lock` file is never renamed (locking the data file then renaming it would break lock semantics, so a dedicated lock file is used).
- **Path safety:** `approvalId` is validated against `[a-zA-Z0-9_-]+` before any filesystem use (prevents path traversal).

## File Structure

All files under `services/gateway/core/src/{main,test}/java/com/sapnexus/gateway/approval/`.

| File | Responsibility | Introduced |
|---|---|---|
| `LeaseOutcome.java` | Public sealed interface: `Claimed` / `Rejected(holder, expiresAt)` / `ForceClaimed(previousHolder)`. | Task 1 |
| `LeaseInfo.java` | Public record `{workerId, expiresAt}` — lease file payload. | Task 1 |
| `DurableApprovalStore.java` | Public interface extending `ApprovalStore`: adds `recoverAll`, `reconcile`, `claimLease`, `releaseLease`, `renewLease`. | Task 1 |
| `ApprovalRecordCodec.java` | Package-private Jackson helper: `ApprovalRecord` + `LeaseInfo` JSON round-trip with `JavaTimeModule`. | Task 1 |
| `ApprovalRecordCodecTest.java` | JUnit tests for codec round-trip + `LeaseOutcome` variants. | Task 1 |
| `FileDurableApprovalStore.java` | Public class implementing `DurableApprovalStore`: file-backed save/find/claim/markExecuted + lease mgmt + recovery. Tasks 2-6 build it incrementally; Task 7 adds Spring `@Primary` wiring. | Task 2 |
| `FileDurableApprovalStoreTest.java` | JUnit tests (`@TempDir`): persistence, claim atomicity, lease states, recovery, reconcile. Grows across Tasks 2-6. | Task 2 |

Helper methods inside `FileDurableApprovalStore` (private, introduced incrementally):

- `safeName(String)` — validates approvalId against `[a-zA-Z0-9_-]+` (Task 2)
- `atomicWrite(Path, String)` — tmp + `Files.move(REPLACE_EXISTING, ATOMIC_MOVE)` (Task 2)
- `stripeLock(String)` / `withFileLock(String, Supplier)` — ReentrantLock + FileChannel.lock (Task 2)
- `withStatus(ApprovalRecord, String)` — copies record with new status (Task 3)
- `writeLease(String, String, long)` / `readLease(String)` — lease file I/O (Task 3)
- `deleteLease(String)` — `Files.deleteIfExists` on lease file (Task 4)

---

### Task 1: LeaseOutcome + LeaseInfo + DurableApprovalStore interface + ApprovalRecordCodec

- [x] Task 1: LeaseOutcome + LeaseInfo + DurableApprovalStore interface + ApprovalRecordCodec

**Files:**
- Create: `services/gateway/core/src/main/java/com/sapnexus/gateway/approval/LeaseOutcome.java`
- Create: `services/gateway/core/src/main/java/com/sapnexus/gateway/approval/LeaseInfo.java`
- Create: `services/gateway/core/src/main/java/com/sapnexus/gateway/approval/DurableApprovalStore.java`
- Create: `services/gateway/core/src/main/java/com/sapnexus/gateway/approval/ApprovalRecordCodec.java`
- Test: `services/gateway/core/src/test/java/com/sapnexus/gateway/approval/ApprovalRecordCodecTest.java`

**Interfaces:**
- Consumes: `ApprovalStore` (existing, 4 methods), `ApprovalRecord` (existing Java record, 8 fields).
- Produces: `LeaseOutcome` (sealed interface, 3 records), `LeaseInfo` (record), `DurableApprovalStore` (interface), `ApprovalRecordCodec` (static JSON helpers). Later tasks implement `DurableApprovalStore` in `FileDurableApprovalStore`.

- [x] **Step 1: Write the failing test**

Create `ApprovalRecordCodecTest.java`:

```java
package com.sapnexus.gateway.approval;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertInstanceOf;

import java.time.Instant;
import java.util.Map;
import org.junit.jupiter.api.Test;

class ApprovalRecordCodecTest {

    @Test
    void approvalRecordRoundTripPreservesAllFields() {
        ApprovalRecord record = new ApprovalRecord(
                "appr-001",
                "MM.PR.CreateDraft",
                "sha256:abc",
                Map.of("material", "M001", "plant", "1000"),
                "user@example.com",
                Instant.parse("2026-08-02T10:00:00Z"),
                Instant.parse("2026-08-02T10:10:00Z"),
                "approved"
        );
        String json = ApprovalRecordCodec.toJson(record);
        ApprovalRecord restored = ApprovalRecordCodec.fromJson(json);
        assertEquals(record, restored);
    }

    @Test
    void leaseInfoRoundTrip() {
        LeaseInfo lease = new LeaseInfo("worker-42", Instant.parse("2026-08-02T10:01:00Z"));
        String json = ApprovalRecordCodec.toJson(lease);
        LeaseInfo restored = ApprovalRecordCodec.leaseFromJson(json);
        assertEquals(lease, restored);
    }

    @Test
    void leaseOutcomeThreeStatesArePatternMatchable() {
        LeaseOutcome claimed = new LeaseOutcome.Claimed();
        LeaseOutcome rejected = new LeaseOutcome.Rejected("worker-1", Instant.parse("2026-08-02T10:01:00Z"));
        LeaseOutcome forceClaimed = new LeaseOutcome.ForceClaimed("worker-1");

        assertInstanceOf(LeaseOutcome.Claimed.class, claimed);
        assertInstanceOf(LeaseOutcome.Rejected.class, rejected);
        assertInstanceOf(LeaseOutcome.ForceClaimed.class, forceClaimed);

        String result = switch (forceClaimed) {
            case LeaseOutcome.Claimed ignored -> "claimed";
            case LeaseOutcome.Rejected r -> "rejected:" + r.holder();
            case LeaseOutcome.ForceClaimed f -> "force:" + f.previousHolder();
        };
        assertEquals("force:worker-1", result);
    }
}
```

- [x] **Step 2: Run test to verify it fails**

Run: `cd services/gateway && ./gradlew :core:test --tests "com.sapnexus.gateway.approval.ApprovalRecordCodecTest"`
Expected: COMPILE FAILURE — `LeaseOutcome`, `LeaseInfo`, `DurableApprovalStore`, `ApprovalRecordCodec` do not exist.

- [x] **Step 3: Write minimal implementation**

Create `LeaseOutcome.java`:

```java
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
```

Create `LeaseInfo.java`:

```java
package com.sapnexus.gateway.approval;

import java.time.Instant;

/**
 * Lease file payload: which worker holds the lease and when it expires.
 */
public record LeaseInfo(String workerId, Instant expiresAt) {}
```

Create `DurableApprovalStore.java`:

```java
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
```

Create `ApprovalRecordCodec.java`:

```java
package com.sapnexus.gateway.approval;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;

/**
 * Jackson helpers for {@link ApprovalRecord} and {@link LeaseInfo} JSON round-trip.
 * Instant is serialized as an ISO-8601 string (WRITE_DATES_AS_TIMESTAMPS disabled).
 */
final class ApprovalRecordCodec {

    private static final ObjectMapper MAPPER = new ObjectMapper()
            .registerModule(new JavaTimeModule())
            .disable(SerializationFeature.WRITE_DATES_AS_TIMESTAMPS);

    private ApprovalRecordCodec() {}

    static String toJson(ApprovalRecord record) {
        try {
            return MAPPER.writeValueAsString(record);
        } catch (JsonProcessingException e) {
            throw new IllegalStateException("Failed to serialize ApprovalRecord", e);
        }
    }

    static ApprovalRecord fromJson(String json) {
        try {
            return MAPPER.readValue(json, ApprovalRecord.class);
        } catch (JsonProcessingException e) {
            throw new IllegalStateException("Failed to deserialize ApprovalRecord", e);
        }
    }

    static String toJson(LeaseInfo lease) {
        try {
            return MAPPER.writeValueAsString(lease);
        } catch (JsonProcessingException e) {
            throw new IllegalStateException("Failed to serialize LeaseInfo", e);
        }
    }

    static LeaseInfo leaseFromJson(String json) {
        try {
            return MAPPER.readValue(json, LeaseInfo.class);
        } catch (JsonProcessingException e) {
            throw new IllegalStateException("Failed to deserialize LeaseInfo", e);
        }
    }
}
```

- [x] **Step 4: Run test to verify it passes**

Run: `cd services/gateway && ./gradlew :core:test --tests "com.sapnexus.gateway.approval.ApprovalRecordCodecTest"`
Expected: PASS (3 tests).

- [x] **Step 5: Commit**

```bash
git add services/gateway/core/src/main/java/com/sapnexus/gateway/approval/LeaseOutcome.java \
  services/gateway/core/src/main/java/com/sapnexus/gateway/approval/LeaseInfo.java \
  services/gateway/core/src/main/java/com/sapnexus/gateway/approval/DurableApprovalStore.java \
  services/gateway/core/src/main/java/com/sapnexus/gateway/approval/ApprovalRecordCodec.java \
  services/gateway/core/src/test/java/com/sapnexus/gateway/approval/ApprovalRecordCodecTest.java
git commit -m "feat(approval): add DurableApprovalStore interface, LeaseOutcome, LeaseInfo, Jackson codec"
```

---

### Task 2: FileDurableApprovalStore save/find (atomic tmp+rename, striped locks)

- [x] Task 2: FileDurableApprovalStore save/find (atomic tmp+rename, striped locks)

**Files:**
- Create: `services/gateway/core/src/main/java/com/sapnexus/gateway/approval/FileDurableApprovalStore.java`
- Test: `services/gateway/core/src/test/java/com/sapnexus/gateway/approval/FileDurableApprovalStoreTest.java`

**Interfaces:**
- Consumes: `DurableApprovalStore` (Task 1), `ApprovalRecordCodec` (Task 1), `ApprovalRecord` (existing).
- Produces: `FileDurableApprovalStore` class with real `save` / `find` and stubs for the remaining 7 interface methods (replaced in Tasks 3-6). Constructor signature for tests: `FileDurableApprovalStore(Path baseDir, String workerId, long leaseTtlMs)` where `baseDir` resolves to `approvals/` and `leases/` subdirs. A `sampleRecord(approvalId, status)` test helper is established here and reused by later tasks.

- [x] **Step 1: Write the failing test**

Create `FileDurableApprovalStoreTest.java`:

```java
package com.sapnexus.gateway.approval;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.time.Instant;
import java.util.Map;
import java.util.Optional;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import java.nio.file.Path;

class FileDurableApprovalStoreTest {

    @TempDir
    Path tempDir;

    private ApprovalRecord sampleRecord(String approvalId, String status) {
        return new ApprovalRecord(
                approvalId,
                "MM.PR.CreateDraft",
                "sha256:abc",
                Map.of("material", "M001", "plant", "1000"),
                "user@example.com",
                Instant.parse("2026-08-02T10:00:00Z"),
                Instant.parse("2026-08-02T10:10:00Z"),
                status
        );
    }

    @Test
    void saveAndFindById() {
        FileDurableApprovalStore store = new FileDurableApprovalStore(tempDir, "worker-test", 60_000L);
        store.save(sampleRecord("appr-001", "approved"));
        Optional<ApprovalRecord> found = store.find("appr-001");
        assertTrue(found.isPresent());
        assertEquals("approved", found.get().status());
        assertEquals("MM.PR.CreateDraft", found.get().capabilityId());
    }

    @Test
    void saveDuplicateReturnsFalse() {
        FileDurableApprovalStore store = new FileDurableApprovalStore(tempDir, "worker-test", 60_000L);
        assertTrue(store.save(sampleRecord("appr-002", "approved")));
        assertFalse(store.save(sampleRecord("appr-002", "approved")));
    }

    @Test
    void findNonexistentReturnsEmpty() {
        FileDurableApprovalStore store = new FileDurableApprovalStore(tempDir, "worker-test", 60_000L);
        assertTrue(store.find("nonexistent").isEmpty());
    }

    @Test
    void persistsAcrossRestart() {
        FileDurableApprovalStore first = new FileDurableApprovalStore(tempDir, "worker-test", 60_000L);
        first.save(sampleRecord("appr-restart", "approved"));

        FileDurableApprovalStore second = new FileDurableApprovalStore(tempDir, "worker-test", 60_000L);
        Optional<ApprovalRecord> found = second.find("appr-restart");
        assertTrue(found.isPresent());
        assertEquals("approved", found.get().status());
        assertEquals("appr-restart", found.get().approvalId());
    }
}
```

- [x] **Step 2: Run test to verify it fails**

Run: `cd services/gateway && ./gradlew :core:test --tests "com.sapnexus.gateway.approval.FileDurableApprovalStoreTest"`
Expected: COMPILE FAILURE — `FileDurableApprovalStore` does not exist.

- [x] **Step 3: Write minimal implementation**

Create `FileDurableApprovalStore.java`. `save` / `find` are real; the other 7 interface methods are stubs replaced in later tasks:

```java
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

/**
 * File-backed reference implementation of {@link DurableApprovalStore}.
 *
 * <p>Layout under {@code <baseDir>/}:
 * <ul>
 *   <li>{@code approvals/<approvalId>.json} — full {@link ApprovalRecord} JSON (tmp+rename).</li>
 *   <li>{@code approvals/<approvalId>.lock} — exclusive lock file (never renamed).</li>
 *   <li>{@code leases/<approvalId>.json} — {@link LeaseInfo} JSON (tmp+rename).</li>
 * </ul>
 *
 * <p>Atomicity: read-modify-write sequences are guarded by a per-approvalId
 * {@link ReentrantLock} (in-process) plus {@link FileChannel#lock()} on the
 * dedicated {@code .lock} file (cross-process, for future multi-worker).
 * Content writes use tmp + {@link Files#move} with REPLACE_EXISTING + ATOMIC_MOVE.
 */
public class FileDurableApprovalStore implements DurableApprovalStore {

    private static final Logger log = LoggerFactory.getLogger(FileDurableApprovalStore.class);

    private final Path approvalsDir;
    private final Path leasesDir;
    private final String workerId;
    private final long leaseTtlMs;
    private final ConcurrentHashMap<String, ReentrantLock> locks = new ConcurrentHashMap<>();

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
        // Stub — implemented in Task 3.
        return Optional.empty();
    }

    @Override
    public void markExecuted(String approvalId) {
        // Stub — implemented in Task 4.
    }

    // --- DurableApprovalStore contract (stubs — implemented in Tasks 5-6) ---

    @Override
    public List<ApprovalRecord> recoverAll() {
        // Stub — implemented in Task 6.
        return List.of();
    }

    @Override
    public void reconcile() {
        // Stub — implemented in Task 6.
    }

    @Override
    public LeaseOutcome claimLease(String approvalId, String workerId, long ttlMs) {
        // Stub — implemented in Task 5.
        throw new UnsupportedOperationException("claimLease not yet implemented");
    }

    @Override
    public void releaseLease(String approvalId, String workerId) {
        // Stub — implemented in Task 5.
    }

    @Override
    public void renewLease(String approvalId, String workerId, long ttlMs) {
        // Stub — implemented in Task 5.
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
```

- [x] **Step 4: Run test to verify it passes**

Run: `cd services/gateway && ./gradlew :core:test --tests "com.sapnexus.gateway.approval.FileDurableApprovalStoreTest"`
Expected: PASS (4 tests).

- [x] **Step 5: Commit**

```bash
git add services/gateway/core/src/main/java/com/sapnexus/gateway/approval/FileDurableApprovalStore.java \
  services/gateway/core/src/test/java/com/sapnexus/gateway/approval/FileDurableApprovalStoreTest.java
git commit -m "feat(approval): file-backed save/find with tmp+rename atomic writes and striped locks"
```

---

### Task 3: claimForExecution (atomic approved->executing + lease binding)

- [x] Task 3: claimForExecution (atomic approved->executing + lease binding)

**Files:**
- Modify: `services/gateway/core/src/main/java/com/sapnexus/gateway/approval/FileDurableApprovalStore.java` (replace `claimForExecution` stub; add `withStatus`, `writeLease`, `readLease` helpers)
- Test: `services/gateway/core/src/test/java/com/sapnexus/gateway/approval/FileDurableApprovalStoreTest.java` (add test methods; `sampleRecord` helper already exists from Task 2)

**Interfaces:**
- Consumes: `withFileLock`, `atomicWrite`, `approvalFile`, `leaseFile` helpers (Task 2); `ApprovalRecordCodec.toJson/fromJson` (Task 1).
- Produces: `claimForExecution` real impl — atomically transitions `approved -> executing`, writes lease file `{workerId, expiresAt=now+ttlMs}`, returns `Optional.of(executingRecord)`. Non-`approved` or missing approval returns `Optional.empty()` (idempotent). New private helpers `withStatus`, `writeLease`, `readLease` are reused by Tasks 4-6.

- [x] **Step 1: Write the failing test**

Append these methods to `FileDurableApprovalStoreTest.java` (inside the class, after `persistsAcrossRestart`):

```java
    @Test
    void claimTransitionsApprovedToExecuting() {
        FileDurableApprovalStore store = new FileDurableApprovalStore(tempDir, "worker-test", 60_000L);
        store.save(sampleRecord("appr-claim", "approved"));

        Optional<ApprovalRecord> claimed = store.claimForExecution("appr-claim");

        assertTrue(claimed.isPresent());
        assertEquals("executing", claimed.get().status());
        assertEquals("executing", store.find("appr-claim").orElseThrow().status());
    }

    @Test
    void claimNonApprovedReturnsEmpty() {
        FileDurableApprovalStore store = new FileDurableApprovalStore(tempDir, "worker-test", 60_000L);
        store.save(sampleRecord("appr-pending", "pending"));

        assertTrue(store.claimForExecution("appr-pending").isEmpty());
        assertEquals("pending", store.find("appr-pending").orElseThrow().status());
    }

    @Test
    void claimIsIdempotent() {
        FileDurableApprovalStore store = new FileDurableApprovalStore(tempDir, "worker-test", 60_000L);
        store.save(sampleRecord("appr-idem", "approved"));

        assertTrue(store.claimForExecution("appr-idem").isPresent());
        assertTrue(store.claimForExecution("appr-idem").isEmpty());
    }

    @Test
    void claimCreatesLeaseFileWithWorkerAndExpiry() throws Exception {
        FileDurableApprovalStore store = new FileDurableApprovalStore(tempDir, "worker-test", 60_000L);
        store.save(sampleRecord("appr-lease", "approved"));
        store.claimForExecution("appr-lease");

        java.nio.file.Path leaseFile = tempDir.resolve("leases").resolve("appr-lease.json");
        assertTrue(java.nio.file.Files.exists(leaseFile));
        LeaseInfo lease = ApprovalRecordCodec.leaseFromJson(java.nio.file.Files.readString(leaseFile));
        assertEquals("worker-test", lease.workerId());
        assertTrue(lease.expiresAt().isAfter(Instant.now()));
    }

    @Test
    void concurrentClaimsHaveExactlyOneWinner() throws Exception {
        FileDurableApprovalStore store = new FileDurableApprovalStore(tempDir, "worker-test", 60_000L);
        store.save(sampleRecord("appr-race", "approved"));
        var executor = java.util.concurrent.Executors.newFixedThreadPool(8);
        try {
            var claims = java.util.stream.IntStream.range(0, 20)
                    .mapToObj(ignored -> (java.util.concurrent.Callable<Boolean>) () ->
                            store.claimForExecution("appr-race").isPresent())
                    .toList();
            long winners = executor.invokeAll(claims).stream()
                    .filter(future -> {
                        try {
                            return future.get();
                        } catch (Exception exception) {
                            throw new AssertionError(exception);
                        }
                    })
                    .count();
            assertEquals(1, winners);
        } finally {
            executor.shutdownNow();
        }
    }
```

- [x] **Step 2: Run test to verify it fails**

Run: `cd services/gateway && ./gradlew :core:test --tests "com.sapnexus.gateway.approval.FileDurableApprovalStoreTest"`
Expected: FAIL — `claimTransitionsApprovedToExecuting` fails (stub returns empty); `claimCreatesLeaseFileWithWorkerAndExpiry` fails (no lease file).

- [x] **Step 3: Write minimal implementation**

In `FileDurableApprovalStore.java`, replace the `claimForExecution` stub with:

```java
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
```

Add these private helpers (after `atomicWrite`, before `stripeLock`):

```java
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
```

- [x] **Step 4: Run test to verify it passes**

Run: `cd services/gateway && ./gradlew :core:test --tests "com.sapnexus.gateway.approval.FileDurableApprovalStoreTest"`
Expected: PASS (9 tests, including the 5 new ones).

- [x] **Step 5: Commit**

```bash
git add services/gateway/core/src/main/java/com/sapnexus/gateway/approval/FileDurableApprovalStore.java \
  services/gateway/core/src/test/java/com/sapnexus/gateway/approval/FileDurableApprovalStoreTest.java
git commit -m "feat(approval): atomic claimForExecution with lease binding and concurrent-claim safety"
```

---

### Task 4: markExecuted (atomic executing->executed + lease release)

- [x] Task 4: markExecuted (atomic executing->executed + lease release)

**Files:**
- Modify: `services/gateway/core/src/main/java/com/sapnexus/gateway/approval/FileDurableApprovalStore.java` (replace `markExecuted` stub; add `deleteLease` helper)
- Test: `services/gateway/core/src/test/java/com/sapnexus/gateway/approval/FileDurableApprovalStoreTest.java` (add test methods)

**Interfaces:**
- Consumes: `withFileLock`, `atomicWrite`, `approvalFile`, `leaseFile`, `withStatus` helpers (Tasks 2-3).
- Produces: `markExecuted` real impl — atomically transitions `executing -> executed`, deletes the lease file. Non-`executing` or missing approval is a no-op (idempotent). New private helper `deleteLease` is reused by Tasks 5-6.

- [x] **Step 1: Write the failing test**

Append these methods to `FileDurableApprovalStoreTest.java`:

```java
    @Test
    void markExecutedTransitionsToExecutedAndReleasesLease() throws Exception {
        FileDurableApprovalStore store = new FileDurableApprovalStore(tempDir, "worker-test", 60_000L);
        store.save(sampleRecord("appr-exec", "approved"));
        store.claimForExecution("appr-exec");

        store.markExecuted("appr-exec");

        ApprovalRecord found = store.find("appr-exec").orElseThrow();
        assertEquals("executed", found.status());
        assertFalse(java.nio.file.Files.exists(tempDir.resolve("leases").resolve("appr-exec.json")));
    }

    @Test
    void markExecutedNonExecutingIsNoop() {
        FileDurableApprovalStore store = new FileDurableApprovalStore(tempDir, "worker-test", 60_000L);
        store.save(sampleRecord("appr-noexec", "approved"));

        store.markExecuted("appr-noexec");

        assertEquals("approved", store.find("appr-noexec").orElseThrow().status());
    }

    @Test
    void markExecutedPreservesAllFields() {
        FileDurableApprovalStore store = new FileDurableApprovalStore(tempDir, "worker-test", 60_000L);
        ApprovalRecord original = sampleRecord("appr-fields", "approved");
        store.save(original);
        store.claimForExecution("appr-fields");
        store.markExecuted("appr-fields");

        ApprovalRecord found = store.find("appr-fields").orElseThrow();
        assertEquals(original.approvalId(), found.approvalId());
        assertEquals(original.capabilityId(), found.capabilityId());
        assertEquals(original.parameterSnapshotHash(), found.parameterSnapshotHash());
        assertEquals(original.parameters(), found.parameters());
        assertEquals(original.approver(), found.approver());
        assertEquals(original.approvedAt(), found.approvedAt());
        assertEquals(original.expiresAt(), found.expiresAt());
        assertEquals("executed", found.status());
    }

    @Test
    void markExecutedNonexistentIsNoop() {
        FileDurableApprovalStore store = new FileDurableApprovalStore(tempDir, "worker-test", 60_000L);
        store.markExecuted("nonexistent");
        assertTrue(store.find("nonexistent").isEmpty());
    }
```

- [x] **Step 2: Run test to verify it fails**

Run: `cd services/gateway && ./gradlew :core:test --tests "com.sapnexus.gateway.approval.FileDurableApprovalStoreTest"`
Expected: FAIL — `markExecutedTransitionsToExecutedAndReleasesLease` fails (stub is no-op; status stays "executing"; lease file not deleted).

- [x] **Step 3: Write minimal implementation**

In `FileDurableApprovalStore.java`, replace the `markExecuted` stub with:

```java
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
```

Add this private helper (after `readLease`):

```java
    private void deleteLease(String approvalId) throws IOException {
        Files.deleteIfExists(leaseFile(approvalId));
    }
```

- [x] **Step 4: Run test to verify it passes**

Run: `cd services/gateway && ./gradlew :core:test --tests "com.sapnexus.gateway.approval.FileDurableApprovalStoreTest"`
Expected: PASS (13 tests).

- [x] **Step 5: Commit**

```bash
git add services/gateway/core/src/main/java/com/sapnexus/gateway/approval/FileDurableApprovalStore.java \
  services/gateway/core/src/test/java/com/sapnexus/gateway/approval/FileDurableApprovalStoreTest.java
git commit -m "feat(approval): atomic markExecuted with lease release"
```

---

### Task 5: claimLease / releaseLease / renewLease (LeaseOutcome three states)

- [x] Task 5: claimLease / releaseLease / renewLease (LeaseOutcome three states)

**Files:**
- Modify: `services/gateway/core/src/main/java/com/sapnexus/gateway/approval/FileDurableApprovalStore.java` (replace 3 lease stubs)
- Test: `services/gateway/core/src/test/java/com/sapnexus/gateway/approval/FileDurableApprovalStoreTest.java` (add test methods)

**Interfaces:**
- Consumes: `withFileLock`, `writeLease`, `readLease`, `deleteLease` helpers (Tasks 2-4); `LeaseOutcome` (Task 1).
- Produces: `claimLease` (three-state: `Claimed` / `Rejected(holder, expiresAt)` / `ForceClaimed(previousHolder)`), `releaseLease` (delete if holder matches), `renewLease` (rewrite if holder matches). These are recovery-scenario methods per Design §4.

- [x] **Step 1: Write the failing test**

Append these methods to `FileDurableApprovalStoreTest.java`:

```java
    @Test
    void claimLeaseNoLeaseReturnsClaimed() {
        FileDurableApprovalStore store = new FileDurableApprovalStore(tempDir, "worker-A", 60_000L);
        LeaseOutcome outcome = store.claimLease("appr-l1", "worker-A", 60_000L);
        assertInstanceOf(LeaseOutcome.Claimed.class, outcome);
    }

    @Test
    void claimLeaseSameWorkerReturnsClaimed() {
        FileDurableApprovalStore store = new FileDurableApprovalStore(tempDir, "worker-A", 60_000L);
        store.claimLease("appr-l2", "worker-A", 60_000L);
        LeaseOutcome outcome = store.claimLease("appr-l2", "worker-A", 60_000L);
        assertInstanceOf(LeaseOutcome.Claimed.class, outcome);
    }

    @Test
    void claimLeaseUnexpiredDifferentWorkerReturnsRejected() {
        FileDurableApprovalStore store = new FileDurableApprovalStore(tempDir, "worker-A", 60_000L);
        store.claimLease("appr-l3", "worker-A", 60_000L);

        LeaseOutcome outcome = store.claimLease("appr-l3", "worker-B", 60_000L);

        assertInstanceOf(LeaseOutcome.Rejected.class, outcome);
        LeaseOutcome.Rejected rejected = (LeaseOutcome.Rejected) outcome;
        assertEquals("worker-A", rejected.holder());
        assertTrue(rejected.expiresAt().isAfter(Instant.now()));
    }

    @Test
    void claimLeaseExpiredDifferentWorkerReturnsForceClaimed() throws Exception {
        FileDurableApprovalStore store = new FileDurableApprovalStore(tempDir, "worker-A", 1L);
        store.claimLease("appr-l4", "worker-A", 1L);
        // wait for lease to expire
        Thread.sleep(20);

        LeaseOutcome outcome = store.claimLease("appr-l4", "worker-B", 60_000L);

        assertInstanceOf(LeaseOutcome.ForceClaimed.class, outcome);
        assertEquals("worker-A", ((LeaseOutcome.ForceClaimed) outcome).previousHolder());
    }

    @Test
    void releaseLeaseByHolderDeletesLease() throws Exception {
        FileDurableApprovalStore store = new FileDurableApprovalStore(tempDir, "worker-A", 60_000L);
        store.claimLease("appr-l5", "worker-A", 60_000L);

        store.releaseLease("appr-l5", "worker-A");

        assertFalse(java.nio.file.Files.exists(tempDir.resolve("leases").resolve("appr-l5.json")));
    }

    @Test
    void releaseLeaseByNonHolderIsNoop() throws Exception {
        FileDurableApprovalStore store = new FileDurableApprovalStore(tempDir, "worker-A", 60_000L);
        store.claimLease("appr-l6", "worker-A", 60_000L);

        store.releaseLease("appr-l6", "worker-B");

        assertTrue(java.nio.file.Files.exists(tempDir.resolve("leases").resolve("appr-l6.json")));
    }

    @Test
    void renewLeaseByHolderExtendsExpiry() throws Exception {
        FileDurableApprovalStore store = new FileDurableApprovalStore(tempDir, "worker-A", 60_000L);
        store.claimLease("appr-l7", "worker-A", 60_000L);
        LeaseInfo before = ApprovalRecordCodec.leaseFromJson(
                java.nio.file.Files.readString(tempDir.resolve("leases").resolve("appr-l7.json")));

        store.renewLease("appr-l7", "worker-A", 120_000L);

        LeaseInfo after = ApprovalRecordCodec.leaseFromJson(
                java.nio.file.Files.readString(tempDir.resolve("leases").resolve("appr-l7.json")));
        assertTrue(after.expiresAt().isAfter(before.expiresAt()));
    }

    @Test
    void renewLeaseByNonHolderIsNoop() throws Exception {
        FileDurableApprovalStore store = new FileDurableApprovalStore(tempDir, "worker-A", 60_000L);
        store.claimLease("appr-l8", "worker-A", 60_000L);

        store.renewLease("appr-l8", "worker-B", 120_000L);

        LeaseInfo lease = ApprovalRecordCodec.leaseFromJson(
                java.nio.file.Files.readString(tempDir.resolve("leases").resolve("appr-l8.json")));
        assertEquals("worker-A", lease.workerId());
    }
```

Add this import at the top of the test file (if not already present):

```java
import static org.junit.jupiter.api.Assertions.assertInstanceOf;
```

- [x] **Step 2: Run test to verify it fails**

Run: `cd services/gateway && ./gradlew :core:test --tests "com.sapnexus.gateway.approval.FileDurableApprovalStoreTest"`
Expected: FAIL — `claimLeaseNoLeaseReturnsClaimed` throws `UnsupportedOperationException` (stub).

- [x] **Step 3: Write minimal implementation**

In `FileDurableApprovalStore.java`, replace the three lease stubs with:

```java
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
```

- [x] **Step 4: Run test to verify it passes**

Run: `cd services/gateway && ./gradlew :core:test --tests "com.sapnexus.gateway.approval.FileDurableApprovalStoreTest"`
Expected: PASS (21 tests).

- [x] **Step 5: Commit**

```bash
git add services/gateway/core/src/main/java/com/sapnexus/gateway/approval/FileDurableApprovalStore.java \
  services/gateway/core/src/test/java/com/sapnexus/gateway/approval/FileDurableApprovalStoreTest.java
git commit -m "feat(approval): lease management with three-state LeaseOutcome (claimed/rejected/force-claimed)"
```

---

### Task 6: recoverAll + reconcile (cross-restart recovery + internal consistency)

- [x] Task 6: recoverAll + reconcile (cross-restart recovery + internal consistency)

**Files:**
- Modify: `services/gateway/core/src/main/java/com/sapnexus/gateway/approval/FileDurableApprovalStore.java` (replace `recoverAll` and `reconcile` stubs; add `stripSuffix` helper)
- Test: `services/gateway/core/src/test/java/com/sapnexus/gateway/approval/FileDurableApprovalStoreTest.java` (add test methods)

**Interfaces:**
- Consumes: `ApprovalRecordCodec`, `approvalFile`, `leaseFile`, `readLease`, `deleteLease`, `safeName` helpers (Tasks 1-4).
- Produces: `recoverAll` (scan `approvals/`, deserialize all records) and `reconcile` (internal consistency: clean orphan/residual leases; leave `executing`+no-lease fail-closed). Recovery uses the durable store only — does NOT read agent JSONL (Design D4). TTL is validated via persisted `expiresAt` (Design §3 — `approvedAt` fixed baseline).

- [x] **Step 1: Write the failing test**

Append these methods to `FileDurableApprovalStoreTest.java`. Add `import java.util.List;` to the test file imports.

```java
    @Test
    void recoverAllLoadsAllRecords() {
        FileDurableApprovalStore store = new FileDurableApprovalStore(tempDir, "worker-test", 60_000L);
        store.save(sampleRecord("appr-r1", "approved"));
        store.save(sampleRecord("appr-r2", "executed"));

        FileDurableApprovalStore restarted = new FileDurableApprovalStore(tempDir, "worker-test", 60_000L);
        List<ApprovalRecord> recovered = restarted.recoverAll();

        assertEquals(2, recovered.size());
        assertTrue(recovered.stream().anyMatch(r -> "appr-r1".equals(r.approvalId())));
        assertTrue(recovered.stream().anyMatch(r -> "appr-r2".equals(r.approvalId())));
    }

    @Test
    void recoverAllEmptyDirReturnsEmpty() {
        FileDurableApprovalStore store = new FileDurableApprovalStore(tempDir, "worker-test", 60_000L);
        assertTrue(store.recoverAll().isEmpty());
    }

    @Test
    void recoveredExpiredApprovalStillExpired() {
        FileDurableApprovalStore store = new FileDurableApprovalStore(tempDir, "worker-test", 60_000L);
        ApprovalRecord expired = new ApprovalRecord(
                "appr-exp", "MM.PR.CreateDraft", "sha256:abc",
                Map.of("material", "M001"), "user@example.com",
                Instant.parse("2026-08-02T10:00:00Z"),
                Instant.parse("2026-08-02T10:00:01Z"),
                "approved"
        );
        store.save(expired);

        FileDurableApprovalStore restarted = new FileDurableApprovalStore(tempDir, "worker-test", 60_000L);
        ApprovalRecord recovered = restarted.find("appr-exp").orElseThrow();

        assertTrue(recovered.isExpired(Instant.now()));
        assertEquals("approved", recovered.status());
    }

    @Test
    void reconcileDeletesOrphanLease() throws Exception {
        FileDurableApprovalStore store = new FileDurableApprovalStore(tempDir, "worker-test", 60_000L);
        // write an orphan lease (no matching approval file)
        java.nio.file.Path orphanLease = tempDir.resolve("leases").resolve("appr-orphan.json");
        java.nio.file.Files.writeString(orphanLease,
                ApprovalRecordCodec.toJson(new LeaseInfo("worker-X", Instant.now().plusSeconds(60))));

        store.reconcile();

        assertFalse(java.nio.file.Files.exists(orphanLease));
    }

    @Test
    void reconcileCleansLeaseForExecutedRecord() {
        FileDurableApprovalStore store = new FileDurableApprovalStore(tempDir, "worker-test", 60_000L);
        store.save(sampleRecord("appr-ex-l", "approved"));
        store.claimForExecution("appr-ex-l");
        store.markExecuted("appr-ex-l");
        // simulate residual lease by writing one back
        store.claimLease("appr-ex-l", "worker-test", 60_000L);

        store.reconcile();

        assertFalse(java.nio.file.Files.exists(tempDir.resolve("leases").resolve("appr-ex-l.json")));
        assertEquals("executed", store.find("appr-ex-l").orElseThrow().status());
    }

    @Test
    void reconcileCleansLeaseForApprovedRecord() {
        FileDurableApprovalStore store = new FileDurableApprovalStore(tempDir, "worker-test", 60_000L);
        store.save(sampleRecord("appr-ap-l", "approved"));
        store.claimLease("appr-ap-l", "worker-test", 60_000L);

        store.reconcile();

        assertFalse(java.nio.file.Files.exists(tempDir.resolve("leases").resolve("appr-ap-l.json")));
        assertEquals("approved", store.find("appr-ap-l").orElseThrow().status());
    }

    @Test
    void reconcileLeavesExecutingWithoutLeaseAsIsFailClosed() {
        FileDurableApprovalStore store = new FileDurableApprovalStore(tempDir, "worker-test", 60_000L);
        store.save(sampleRecord("appr-exec-nol", "approved"));
        store.claimForExecution("appr-exec-nol");
        // simulate crash: delete the lease but leave record as executing
        store.releaseLease("appr-exec-nol", "worker-test");

        store.reconcile();

        // fail-closed: record stays executing, not auto-recovered to approved
        assertEquals("executing", store.find("appr-exec-nol").orElseThrow().status());
    }
```

- [x] **Step 2: Run test to verify it fails**

Run: `cd services/gateway && ./gradlew :core:test --tests "com.sapnexus.gateway.approval.FileDurableApprovalStoreTest"`
Expected: FAIL — `recoverAllLoadsAllRecords` fails (stub returns empty list); reconcile stubs are no-ops so lease-cleanup tests fail.

- [x] **Step 3: Write minimal implementation**

In `FileDurableApprovalStore.java`, replace the `recoverAll` stub with:

```java
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
```

Replace the `reconcile` stub with:

```java
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
```

Add this private helper (after `deleteLease`):

```java
    private static String stripSuffix(String value, String suffix) {
        return value.endsWith(suffix) ? value.substring(0, value.length() - suffix.length()) : value;
    }
```

- [x] **Step 4: Run test to verify it passes**

Run: `cd services/gateway && ./gradlew :core:test --tests "com.sapnexus.gateway.approval.FileDurableApprovalStoreTest"`
Expected: PASS (28 tests).

- [x] **Step 5: Commit**

```bash
git add services/gateway/core/src/main/java/com/sapnexus/gateway/approval/FileDurableApprovalStore.java \
  services/gateway/core/src/test/java/com/sapnexus/gateway/approval/FileDurableApprovalStoreTest.java
git commit -m "feat(approval): recoverAll and reconcile with fail-closed drift handling"
```

---

### Task 7: Spring wiring (@Primary) + full verification

- [x] Task 7: Spring wiring (@Primary) + full verification

**Files:**
- Modify: `services/gateway/core/src/main/java/com/sapnexus/gateway/approval/FileDurableApprovalStore.java` (add `@Component @Primary` + Spring `@Autowired @Value` constructor; add Spring imports)
- No change: `services/gateway/core/src/main/java/com/sapnexus/gateway/approval/InMemoryApprovalStore.java` (stays `@Component`, no `@Primary` — retained as test stub per Design §6)

**Interfaces:**
- Consumes: `FileDurableApprovalStore` (Tasks 2-6), Spring `@Value("${SAP_NEXUS_GATEWAY_DATA_DIR:.gateway-data}")`.
- Produces: `FileDurableApprovalStore` as the production `@Primary` `ApprovalStore` bean. `CapabilityController` injects `ApprovalStore` and Spring now selects the durable store. Existing `@WebMvcTest` tests are unaffected (they provide their own `ApprovalStore @Bean` in `@TestConfiguration`, and `@WebMvcTest` does not scan `@Component`).

- [x] **Step 1: Add Spring annotations and constructor**

In `FileDurableApprovalStore.java`, add these imports:

```java
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Primary;
import org.springframework.stereotype.Component;
```

Add `@Component @Primary` above the class declaration, and add a Spring constructor before the existing test constructor:

```java
@Component
@Primary
public class FileDurableApprovalStore implements DurableApprovalStore {

    private static final Logger log = LoggerFactory.getLogger(FileDurableApprovalStore.class);
    private static final String DEFAULT_WORKER_ID = "worker-" + ProcessHandle.current().pid();
    private static final long DEFAULT_LEASE_TTL_MS = 60_000L;

    @Autowired
    public FileDurableApprovalStore(
            @Value("${SAP_NEXUS_GATEWAY_DATA_DIR:.gateway-data}") String dataDir) {
        this(java.nio.file.Path.of(dataDir, "durable"), DEFAULT_WORKER_ID, DEFAULT_LEASE_TTL_MS);
    }

    FileDurableApprovalStore(Path baseDir, String workerId, long leaseTtlMs) {
        // ... existing body unchanged ...
    }
```

Leave the existing test constructor body exactly as-is; only the field declarations above it change (the two new `static final` constants are new, the `DEFAULT_WORKER_ID`/`DEFAULT_LEASE_TTL_MS` replace any hardcoded uses — but none exist yet since the test constructor takes them as params).

- [x] **Step 2: Verify existing approval tests still pass**

Run: `cd services/gateway && ./gradlew :core:test --tests "com.sapnexus.gateway.approval.*"`
Expected: PASS — `ApprovalRecordCodecTest`, `ApprovalRecordTest`, `ApprovalGuardTest`, `InMemoryApprovalStoreTest`, `FileDurableApprovalStoreTest` all green. `InMemoryApprovalStore` is unchanged.

- [x] **Step 3: Verify app-layer tests are not broken by @Primary**

Run: `cd services/gateway && ./gradlew :app:test`
Expected: PASS. `CapabilityApprovalApiTest` and `CapabilityWriteExecutionApiTest` use `@WebMvcTest` + `@TestConfiguration` providing their own `ApprovalStore @Bean` (an `InMemoryApprovalStore`), so `@Primary` on `FileDurableApprovalStore` is not loaded in those sliced tests. If any full `@SpringBootTest` exists that now picks up the durable store, confirm it starts (the default `.gateway-data/durable/` dir is auto-created by the constructor).

- [x] **Step 4: Run the full Gateway test suite**

Run: `cd services/gateway && ./gradlew test`
Expected: BUILD SUCCESSFUL, all tests pass.

- [x] **Step 5: Run openspec validation**

Run: `openspec validate --all --strict`
Expected: validation passes (no output errors).

- [x] **Step 6: Commit**

```bash
git add services/gateway/core/src/main/java/com/sapnexus/gateway/approval/FileDurableApprovalStore.java
git commit -m "feat(approval): wire FileDurableApprovalStore as @Primary production ApprovalStore"
```

---

## Spec Coverage Map

| Design section / Spec requirement | Task(s) |
|---|---|
| §1 DurableApprovalStore interface (extends ApprovalStore, LeaseOutcome three-state sealed interface) | Task 1 |
| §2 File reference impl (tmp+rename + FileChannel.lock atomic write, item-1 patterns) | Tasks 2-4 (save/find/claim/markExecuted) |
| §2 Lease file layout + serialization (Jackson + JavaTimeModule) | Task 1 (codec), Tasks 3-5 (lease I/O) |
| §3 TTL approvedAt fixed baseline (persist expiresAt, isExpired wall-clock, no reset) | Task 2 (persistsAcrossRestart), Task 6 (recoveredExpiredApprovalStillExpired) |
| §4 claim/lease per-approval (claimForExecution atomic + lease TTL 60s + force-claimed audit) | Task 3 (claim + lease binding), Task 5 (LeaseOutcome three states) |
| §4 claimForExecution idempotent (duplicate returns empty) | Task 3 (claimIsIdempotent) |
| §5 Cross-restart recovery (recoverAll, reconcile, no JSONL cross-service read) | Task 6 |
| §5 reconcile drift rules (orphan/residual lease cleanup, executing+no-lease fail-closed) | Task 6 |
| §6 InMemoryApprovalStore retained as test stub (@Primary/qualifier) | Task 7 |
| 安全契约: durable + cross-restart + cross-worker anti-replay | Tasks 2-6 (persistence + atomicity + lease) |
| 安全契约: claimForExecution idempotent | Task 3 |
| 安全契约: expired not executable (expiresAt immutable) | Task 6 |
| 安全契约: no SAP credentials stored | unchanged ApprovalRecord (no credential fields) |
| tasks.md 7.5 gradle test pass | Task 7 Step 4 |
| tasks.md 7.6 openspec validate pass | Task 7 Step 5 |

**Note on tasks.md 3.3 / 5.2:** those items say "恢复时以 JSONL 审计为准对账", but Design D4 (corrected) supersedes: recovery uses durable store internal consistency only, no cross-service JSONL read. This plan follows D4 (canonical). JSONL trace remains the audit source but is not in the Gateway recovery path.

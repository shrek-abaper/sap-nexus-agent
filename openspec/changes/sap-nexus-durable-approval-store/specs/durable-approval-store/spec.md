## ADDED Requirements

### Requirement: Durable approval persistence
The system SHALL persist `ApprovalRecord` in a durable store replacing the `InMemoryApprovalStore` (`ConcurrentMap<String, ApprovalRecord>` process-local index). Approval state SHALL survive process restart. The durable store SHALL provide the operational index (save / find / claimForExecution / markExecuted).

#### Scenario: Approval recovers across process restart
- **WHEN** an approval is in `pending` or `approved` state and the Gateway process restarts
- **THEN** the approval is recovered from the durable store with its full `ApprovalRecord`
- **AND** the user can continue to approve / claim / execute the approval after restart

#### Scenario: Executing state recovers across restart
- **WHEN** an approval is in `executing` state (claimed but not yet `executed`) and the Gateway process restarts
- **THEN** the approval is recovered with its `executing` status from the durable store
- **AND** the approval can be re-claimed or marked executed per recovery policy

### Requirement: Cross-worker anti-replay
The system SHALL prevent duplicate approval execution across workers via claim/lease. `claimForExecution` SHALL be idempotent per `approvalId`: a second claim for an already-`executing` or `executed` approval SHALL return empty. The durable store SHALL provide atomicity equivalent to `InMemoryApprovalStore`'s `ConcurrentMap.compute`.

#### Scenario: Cross-worker duplicate claim denied
- **WHEN** worker A claims approval X for execution (transitions `approved -> executing`) and worker B attempts to claim the same approval X
- **THEN** worker B's claim returns empty (idempotent rejection)
- **AND** approval X is not doubly-executed

#### Scenario: Concurrent claim is atomic
- **WHEN** two workers concurrently call `claimForExecution` for the same `approvalId`
- **THEN** exactly one claim succeeds atomically (transitions `approved -> executing`)
- **AND** the other claim returns empty

### Requirement: JSONL audit retained as authoritative
The JSONL trace SHALL remain the authoritative audit source for approval decisions. The durable store SHALL be the operational index. On recovery, the durable store SHALL be reconciled against the JSONL audit; drift SHALL fail closed.

#### Scenario: JSONL audit preserved after durable store swap
- **WHEN** `InMemoryApprovalStore` is replaced by `DurableApprovalStore`
- **THEN** the JSONL audit trace continues to record approval decisions as the authoritative audit source
- **AND** the durable store serves as the operational index (save / find / claimForExecution / markExecuted)

### Requirement: Approval TTL re-validation across restart
The system SHALL re-validate `expiresAt` on recovery. Expired approvals SHALL NOT be executable. `claimForExecution` SHALL reject an approval whose `expiresAt` is in the past (per `ApprovalRecord.isExpired(Instant)`).

#### Scenario: Expired approval rejected after restart
- **WHEN** an approval whose `expiresAt` is in the past is recovered after restart
- **THEN** `claimForExecution` rejects the expired approval (returns empty)
- **AND** the approval remains in its recovered state for audit

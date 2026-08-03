## MODIFIED Requirements

### Requirement: Visibility pre-filter

The system SHALL apply a visibility pre-filter to candidate `CapabilityCard`s before the matcher decision (including LLM prompt assembly), not only before `SHOW_OPTIONS`. The pre-filter SHALL be bound to the same non-empty `snapshotId` as the `GovernedContext` and SHALL consider governance (`sideEffect`/`dataClassification`) and bind the `principal` to the `GovernedContext` for same-snapshot/audit provenance; role-based capability visibility is deferred until the Registry carries a `visibilityScope` field. Candidates with `governance.sideEffect=none` and `dataClassification=internal` SHALL be visible by default; write-capability and restricted-data candidates SHALL be visible in dry-run but not executable until S3 gates are met. The filtered set (`VisibleCapabilitySet`) is the sole capability source for intent recognition, matcher decisions, and candidate recall. Gateway execute SHALL re-authorize (double check).

#### Scenario: Read capability visible

- **WHEN** a candidate has `sideEffect=none` and `dataClassification=internal` and the principal is permitted
- **THEN** the candidate is included in the `VisibleCapabilitySet`

#### Scenario: Write capability visible in dry-run only

- **WHEN** a candidate has `sideEffect=sap_write`
- **THEN** the candidate is visible in dry-run and SHOW_OPTIONS but not executable until S3 gates are met

#### Scenario: Pre-filter bound to same snapshotId

- **WHEN** the matcher applies visibility pre-filter
- **THEN** the filter uses `CapabilityCard`s projected from the same `snapshotId` as the `GovernedContext`
- **AND** the `VisibleCapabilitySet` is the sole input to the matcher decision

## ADDED Requirements

### Requirement: Escalation handoff binds non-empty snapshot

When `MatchDecision.decision_type=ESCALATE_TO_PLANNER`, the `EscalationHandoff.registry_snapshot_id` SHALL be non-empty and equal to the `GovernedContext.snapshotId`. The handoff SHALL NOT carry an empty `registry_snapshot_id`; the matcher SHALL populate it from the `GovernedContext` so the planner can be proven to use the same snapshot.

#### Scenario: Handoff carries non-empty snapshotId

- **WHEN** the matcher emits `ESCALATE_TO_PLANNER`
- **THEN** `EscalationHandoff.registry_snapshot_id` is non-empty
- **AND** it equals the `GovernedContext.snapshotId` used by the matcher

#### Scenario: Planner uses handoff snapshotId

- **WHEN** the planner compiles a dry-run from the handoff
- **THEN** the planner uses the same `snapshotId` as the handoff
- **AND** does not reload a different snapshot

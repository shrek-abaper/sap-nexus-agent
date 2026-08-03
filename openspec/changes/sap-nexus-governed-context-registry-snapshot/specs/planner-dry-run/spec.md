## MODIFIED Requirements

### Requirement: CapabilityCard discovery

The system SHALL project registered capabilities into `CapabilityCard`s carrying `capabilityId`, `name`, `inputs`, `governance`, `visibility`, `producesFactTypes` (derived from the capability `outputs.factTypeRef`), and `registry_snapshot_id` (bound to the `RegistrySnapshot` the card was projected from), derived from the Registry closed set and the bound Registry Snapshot. `producesFactTypes` enables the `PlanCompiler` to match candidate capabilities against a `GoalSpec` desired Fact Types. A `CapabilityCard` is advisory and grants no execution authority. `discover_cards` SHALL bind the snapshot and SHALL NOT discard it; each card's `registry_snapshot_id` SHALL equal the `GovernedContext.snapshotId`.

#### Scenario: Project read capability to CapabilityCard

- **WHEN** the planner discovers `MM.Inventory.GetAvailability` from the Registry
- **THEN** a `CapabilityCard` is produced with its inputs, governance (`sideEffect=none`, `requiresApproval=false`), visibility, `producesFactTypes` from its `outputs.factTypeRef`, and non-empty `registry_snapshot_id`

#### Scenario: CapabilityCard binds snapshotId

- **WHEN** `discover_cards` projects capabilities from a snapshot
- **THEN** each `CapabilityCard.registry_snapshot_id` equals the `GovernedContext.snapshotId`
- **AND** the snapshot argument is consumed, not discarded

### Requirement: Deterministic PlanCompiler dry-run

The system SHALL compile `GoalSpec` plus the `RegistrySnapshot` bound to the `GovernedContext` (via `SnapshotLease`) into a `PlanGraph` via a deterministic `PlanCompiler`. The `PlanGraph` SHALL be validated by the S1 `semantic-planning-foundation` validator (provenance, edges, governance, topological order). The `PlanCompiler` MUST NOT execute Gateway or SAP. The planner SHALL consume the `snapshotId` from the `SnapshotLease` and SHALL NOT reload a different snapshot; if the planner `snapshotId` drifts from the `GovernedContext.snapshotId`, the system SHALL fail-closed with a `PlannerFailure(SNAPSHOT_DRIFT)`.

#### Scenario: Dry-run produces auditable PlanGraph

- **WHEN** the `PlanCompiler` runs on a valid `GoalSpec`
- **THEN** it outputs a `PlanGraph` with nodes, edges, parameter sources (`goalConstraint`/`literal`/`factField`), gaps, and governance flags
- **AND** it does not call Gateway validate or execute

#### Scenario: PlanGraph validation reuses S1 validator

- **WHEN** the `PlanCompiler` emits a `PlanGraph`
- **THEN** the S1 `semantic-planning-foundation` validator validates provenance, edges, governance, and topological order

#### Scenario: Planner uses same snapshot as matcher

- **WHEN** the planner compiles a dry-run from an escalation handoff
- **THEN** the planner uses the `snapshotId` from the `SnapshotLease` (same as the handoff and matcher)
- **AND** does not reload a different snapshot

### Requirement: Dry-run output auditable and non-executing

The dry-run output SHALL include `PlanGraph`, `gaps` (missing parameters or capabilities), `governanceFlags` (approval required, write side-effect), and the `snapshotId` bound to the `GovernedContext`. The output SHALL be auditable: candidate, decision rationale, Registry Snapshot, nodes, edges, parameter sources, gaps, and governance. The system MUST NOT execute Gateway or SAP from dry-run output. When source load fails or snapshot drifts, the system SHALL return a structured `PlannerFailure` with stable `error_type` and audit evidence, not a silent `None` dry-run.

#### Scenario: Dry-run output is auditable

- **WHEN** dry-run completes
- **THEN** the output contains PlanGraph, gaps, governanceFlags, snapshotId, and decision rationale
- **AND** no Gateway validate or execute is called

#### Scenario: Dry-run failure is structured

- **WHEN** source load fails or snapshot drifts during dry-run
- **THEN** the system returns a `PlannerFailure` with stable `error_type` and audit evidence
- **AND** does not silently degrade to `dry_run=None`

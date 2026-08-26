# planner-dry-run Specification

## Purpose
TBD - created by archiving change sap-nexus-planner-dry-run. Update Purpose after archive.
## Requirements
### Requirement: CapabilityCard discovery

The system SHALL project registered capabilities into `CapabilityCard`s carrying `capabilityId`, `name`, `inputs`, `governance`, `visibility`, `producesFactTypes` (derived from the capability `outputs.factTypeRef`), and `registry_snapshot_id` (bound to the `RegistrySnapshot` the card was projected from), derived from the Registry closed set and the bound Registry Snapshot. `producesFactTypes` enables the `PlanCompiler` to match candidate capabilities against a `GoalSpec` desired Fact Types. A `CapabilityCard` is advisory and grants no execution authority. `discover_cards` SHALL bind the snapshot and SHALL NOT discard it; each card's `registry_snapshot_id` SHALL equal the `GovernedContext.snapshotId`.

#### Scenario: Project read capability to CapabilityCard

- **WHEN** the planner discovers `MM.Inventory.GetAvailability` from the Registry
- **THEN** a `CapabilityCard` is produced with its inputs, governance (`sideEffect=none`, `requiresApproval=false`), visibility, `producesFactTypes` from its `outputs.factTypeRef`, and non-empty `registry_snapshot_id`

#### Scenario: CapabilityCard binds snapshotId

- **WHEN** `discover_cards` projects capabilities from a snapshot
- **THEN** each `CapabilityCard.registry_snapshot_id` equals the `GovernedContext.snapshotId`
- **AND** the snapshot argument is consumed, not discarded

### Requirement: GoalSpec and PlanDraft candidate generation
The system SHALL generate `GoalSpec` v1 (per `semantic-planning-foundation`) and advisory `PlanDraft` candidates from a `MatchDecision.ESCALATE_TO_PLANNER` handoff. `GoalSpec` and `PlanDraft` are advisory; only deterministic compilation may produce a `PlanGraph`.

#### Scenario: Escalation produces GoalSpec
- **WHEN** `MatchDecision.decision_type=ESCALATE_TO_PLANNER`
- **THEN** the planner generates a `GoalSpec` with desired Fact Types and `executionMode=PLAN_ONLY`

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

### Requirement: Missing-producer dry-run gap is exercised against the governed capability set
The dry-run evidence suite SHALL exercise the missing-producer gap against the governed capability set rather than defer it. When a goal or a consuming capability input requires a value that no active capability can produce, the dry-run output SHALL report a capability gap identifying the unproducible requirement. This case SHALL be an executed, asserted case; it MUST NOT be carried as a pending or skipped entry, and it MUST NOT be considered covered solely by a lower-level unit test.

#### Scenario: Unproducible requirement yields a capability gap

- **WHEN** a dry-run is compiled for a goal whose required value no active capability produces
- **THEN** the dry-run output contains a capability gap naming that requirement
- **AND** no Gateway validate or execute call is made

#### Scenario: Missing-producer case executes rather than skips

- **WHEN** the dry-run evidence suite runs
- **THEN** the missing-producer case executes and its assertions are evaluated
- **AND** the evidence output does not report it as pending or skipped

### Requirement: Dry-run reports unbound inputs and derivation diagnostics as gaps
When a consuming capability input cannot be bound because the only candidate producer field requires cardinality reduction, or because more than one candidate producer exists, the dry-run output SHALL report the input as a gap carrying the diagnostic kind. The compiler MUST NOT bind the input by choosing a candidate, applying a reduction, or inserting a default.

#### Scenario: Reduction-required candidate is reported as a gap

- **WHEN** the only candidate producer field for a required scalar input has `cardinality: many`
- **THEN** the dry-run output reports that input as a gap carrying the `needsReduction` diagnostic kind
- **AND** the input is not bound to any parameter source

#### Scenario: Ambiguous candidates are reported as a gap

- **WHEN** more than one candidate producer field could bind the same required input
- **THEN** the dry-run output reports that input as a gap carrying the `ambiguous` diagnostic kind
- **AND** the compiler selects none of the candidates


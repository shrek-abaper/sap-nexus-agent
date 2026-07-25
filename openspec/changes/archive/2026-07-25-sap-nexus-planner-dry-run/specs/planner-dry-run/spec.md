## ADDED Requirements

### Requirement: CapabilityCard discovery
The system SHALL project registered capabilities into `CapabilityCard`s carrying `capabilityId`, `name`, `inputs`, `governance`, `visibility`, and `producesFactTypes` (derived from the capability `outputs.factTypeRef`), derived from the Registry closed set and the bound Registry Snapshot. `producesFactTypes` enables the `PlanCompiler` to match candidate capabilities against a `GoalSpec` desired Fact Types. A `CapabilityCard` is advisory and grants no execution authority.

#### Scenario: Project read capability to CapabilityCard
- **WHEN** the planner discovers `MM.Inventory.GetAvailability` from the Registry
- **THEN** a `CapabilityCard` is produced with its inputs, governance (`sideEffect=none`, `requiresApproval=false`), visibility, and `producesFactTypes` from its `outputs.factTypeRef`

### Requirement: GoalSpec and PlanDraft candidate generation
The system SHALL generate `GoalSpec` v1 (per `semantic-planning-foundation`) and advisory `PlanDraft` candidates from a `MatchDecision.ESCALATE_TO_PLANNER` handoff. `GoalSpec` and `PlanDraft` are advisory; only deterministic compilation may produce a `PlanGraph`.

#### Scenario: Escalation produces GoalSpec
- **WHEN** `MatchDecision.decision_type=ESCALATE_TO_PLANNER`
- **THEN** the planner generates a `GoalSpec` with desired Fact Types and `executionMode=PLAN_ONLY`

### Requirement: Deterministic PlanCompiler dry-run
The system SHALL compile `GoalSpec` plus Registry Snapshot into a `PlanGraph` via a deterministic `PlanCompiler`. The `PlanGraph` SHALL be validated by the S1 `semantic-planning-foundation` validator (provenance, edges, governance, topological order). The `PlanCompiler` MUST NOT execute Gateway or SAP.

#### Scenario: Dry-run produces auditable PlanGraph
- **WHEN** the `PlanCompiler` runs on a valid `GoalSpec`
- **THEN** it outputs a `PlanGraph` with nodes, edges, parameter sources (`goalConstraint`/`literal`/`factField`), gaps, and governance flags
- **AND** it does not call Gateway validate or execute

#### Scenario: PlanGraph validation reuses S1 validator
- **WHEN** the `PlanCompiler` emits a `PlanGraph`
- **THEN** the S1 `semantic-planning-foundation` validator validates provenance, edges, governance, and topological order

### Requirement: Dry-run output auditable and non-executing
The dry-run output SHALL include `PlanGraph`, `gaps` (missing parameters or capabilities), and `governanceFlags` (approval required, write side-effect). The output SHALL be auditable: candidate, decision rationale, Registry Snapshot, nodes, edges, parameter sources, gaps, and governance. The system MUST NOT execute Gateway or SAP from dry-run output.

#### Scenario: Dry-run output is auditable
- **WHEN** dry-run completes
- **THEN** the output contains PlanGraph, gaps, governanceFlags, and decision rationale
- **AND** no Gateway validate or execute is called

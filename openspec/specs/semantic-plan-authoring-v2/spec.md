# semantic-plan-authoring-v2 Specification

## Purpose
TBD - created by archiving change sap-nexus-semantic-plan-authoring-v2. Update Purpose after archive.
## Requirements
### Requirement: PlanGraph v2 schema expresses partition, provenance, and reserved refs

The system SHALL define a PlanGraph v2 schema (`planGraphVersion: 2`) that carries `readPartition`, `actionPartition`, `projectionRef`, and `ruleSetRefs`, alongside the v1 `nodes` / `edges` / `topologicalOrder` / `goalOutputs` structure. Parameter sources SHALL be exactly one of `goalConstraint`, `literal`, `factField`, or `registeredDefault`. The v1 schema (`planGraphVersion: 1`) SHALL remain unchanged and v1 fixtures SHALL continue to validate against it.

#### Scenario: Dual-READ plan carries read partition

- **WHEN** the v2 compiler compiles a dual-READ goal referencing `MM.Inventory.GetAvailability` and `MM.PurchaseOrder.GetList`
- **THEN** the PlanGraph v2 carries `readPartition` containing both READ node ids and an empty `actionPartition`
- **AND** `projectionRef` and `ruleSetRefs` are empty reserved fields

#### Scenario: v1 schema remains unchanged

- **WHEN** v1 fixtures and the v1 validator run
- **THEN** the v1 `plan-graph.schema.json` (`planGraphVersion: 1`) and v1 validator behave identically to before this change
- **AND** v1 tests pass without modification

### Requirement: v2 compiler authors full parameter provenance and relations

The system SHALL provide a deterministic v2 compiler that compiles `GoalSpec` / `PlanDraft` plus the `RegistrySnapshot`-bound `SemanticSourceDocuments` into a PlanGraph v2. The compiler SHALL author `literal` and `factField` parameter sources in addition to `goalConstraint`, SHALL author `data` and `dependency` edges derived from the snapshot, and SHALL partition nodes into `readPartition` / `actionPartition`. Eligibility for a `factField` source SHALL be determined by the consuming input declaring `satisfiableByFactType`, not by its `bindingKind`. A `factField` source SHALL identify the producer field selected for that specific consuming input by semantic-type equality; the compiler MUST NOT select the producer's first matching field irrespective of which input is being bound, and MUST NOT resolve a Fact Type's producer by position when more than one capability produces it. The compiler SHALL NOT author a `factField` source for a parameter that already carries a `goalConstraint` or `literal` source. When one producer node supplies more than one input of the same consumer node from the same Fact Type, the compiler SHALL author one `factField` source per bound input and exactly one `data` edge for that producer/consumer/Fact Type triple. The `registeredDefault` source kind is defined in the v2 schema as part of the 4-source closed set but SHALL NOT be authored this phase (no capability input declares a registered default); it is reserved for future activation. The compiler MUST NOT call the LLM, the Gateway, or SAP.

#### Scenario: Identifier input bound by goalConstraint

- **WHEN** a required identifier input matches a GoalConstraint by name and semantic type
- **THEN** the v2 compiler authors a `goalConstraint` parameter source

#### Scenario: Fact input bound by factField produces a data edge

- **WHEN** a required fact-bound input carrying no user-supplied source is bound by a `factField` source from a producer node
- **THEN** the v2 compiler authors a `factField` parameter source and a matching `data` edge

#### Scenario: Identifier input declaring a Fact Type is bound by factField

- **WHEN** a required input with `bindingKind=identifier` declares `satisfiableByFactType` and carries no user-supplied source
- **THEN** the v2 compiler authors a `factField` parameter source and a matching `data` edge for it
- **AND** eligibility is determined by the `satisfiableByFactType` declaration rather than by `bindingKind`

#### Scenario: A user-supplied source suppresses the factField source

- **WHEN** a required input declaring `satisfiableByFactType` already carries a `goalConstraint` or `literal` parameter source
- **THEN** the v2 compiler authors no `factField` source for that parameter
- **AND** exactly one parameter source exists for that parameter name

#### Scenario: Field selection is per consuming input

- **WHEN** one producer node can supply two different inputs of the same consumer node from the same Fact Type
- **THEN** each authored `factField` source identifies the producer field whose semantic type equals that input's semantic type
- **AND** the two sources do not identify the same producer field

#### Scenario: Multiple bound inputs share one data edge

- **WHEN** two `factField` sources on one consumer node reference the same producer node and the same Fact Type
- **THEN** the compiler authors exactly one `data` edge for that producer/consumer/Fact Type triple
- **AND** validation does not report a duplicate data edge

#### Scenario: registeredDefault source is reserved this phase

- **WHEN** the v2 schema defines `registeredDefault` as part of the 4-source closed set
- **THEN** the v2 compiler does not author a `registeredDefault` source this phase (no capability input declares a registered default)
- **AND** the source kind is reserved for future activation when capability inputs declare registered defaults

#### Scenario: Dependency relation produces a dependency edge

- **WHEN** the snapshot relation catalog declares a `dependsOn` relation between two capabilities present in the plan
- **THEN** the v2 compiler authors a `dependency` edge from prerequisite to dependent

#### Scenario: Compiler is deterministic and non-executing

- **WHEN** the v2 compiler runs on the same GoalSpec and snapshot repeatedly
- **THEN** it returns the same PlanGraph v2
- **AND** it calls no LLM, Gateway validate, Gateway execute, or SAP

### Requirement: READ/WRITE partition isolates Action nodes

The system SHALL partition PlanGraph v2 nodes so that Action nodes and any capability whose governance is not read-only appear only in `actionPartition` with `requiresApproval=true`, and MUST NOT appear in `readPartition`. READ-only nodes appear only in `readPartition`.

#### Scenario: Action node isolated in action partition

- **WHEN** a plan includes a write or Action capability node
- **THEN** the node appears in `actionPartition` with `requiresApproval=true`
- **AND** the node does not appear in `readPartition`

### Requirement: v2 validator reuses S1 validation and adds partition and ref checks

The system SHALL validate PlanGraph v2 by reusing the S1 `semantic-planning-foundation` validation (provenance, edges, cycle, topological order, governance, snapshot, goalOutputs) and adding partition isolation and projection/rule ref checks. `projectionRef` and `ruleSetRefs`, when non-empty, SHALL reference entities present in the snapshot; when empty (this phase's default) they SHALL pass.

#### Scenario: Action-in-READ fails closed

- **WHEN** a PlanGraph v2 places an Action or non-read-only node in `readPartition`
- **THEN** validation reports a partition governance violation and the plan is invalid

#### Scenario: Unknown capability fails closed

- **WHEN** a PlanGraph v2 node references a capability not present in the snapshot
- **THEN** validation reports `UNKNOWN_CAPABILITY` and the plan is invalid

#### Scenario: Unknown or inconsistent relation fails closed

- **WHEN** a PlanGraph v2 dependency edge does not match an authored `dependsOn` relation in the snapshot
- **THEN** validation reports `EDGE_INCONSISTENT` and the plan is invalid

#### Scenario: Cycle fails closed

- **WHEN** PlanGraph v2 edges form a cycle
- **THEN** validation reports `DEPENDENCY_CYCLE` and the plan is invalid

#### Scenario: Type mismatch fails closed

- **WHEN** a `factField` source references a Fact Type the producer does not emit or cannot satisfy the target fact-bound input
- **THEN** validation reports `FACT_TYPE_MISMATCH` and the plan is invalid

#### Scenario: Missing parameter source fails closed

- **WHEN** a required parameter has no source
- **THEN** validation reports `PARAMETER_SOURCE_MISSING` and the plan is invalid

#### Scenario: Snapshot drift fails closed

- **WHEN** the PlanGraph v2 `snapshotId` does not match the supplied RegistrySnapshot
- **THEN** validation reports `SNAPSHOT_MISMATCH` and the plan is invalid

### Requirement: Validation failures are structured, never None

The system SHALL return structured gaps and failures carrying explicit issues (error code, JSON Pointer path, message) when v2 compilation or validation fails. The system MUST NOT silently degrade to a `None` plan.

#### Scenario: Invalid plan preserves structured issues

- **WHEN** v2 validation fails on one or more bad cases
- **THEN** the result carries structured gaps/failures with error codes and JSON Pointer paths
- **AND** the result is not a silent `None`

### Requirement: v2 dry-run output is auditable and non-executing

The v2 dry-run output SHALL include the PlanGraph v2, gaps, governance, `projectionRef`, `ruleSetRefs`, and the bound `snapshotId`. The system MUST NOT call Gateway validate or execute from v2 dry-run output.

#### Scenario: Dry-run surfaces v2 fields without execution

- **WHEN** the v2 dry-run completes
- **THEN** the output contains plan, gaps, governance, `projectionRef`, `ruleSetRefs`, and `snapshotId`
- **AND** no Gateway validate or execute is called

### Requirement: v2 compiler consumes EscalationHandoff with same-snapshot binding

The v2 compiler SHALL consume `EscalationHandoff` plus `RegistrySnapshot` plus `SemanticSourceDocuments` as its input contract and SHALL bind the same `snapshotId` as the matcher. Snapshot drift SHALL fail closed with a structured `PlannerFailure`.

#### Scenario: Compiler uses same snapshot as matcher

- **WHEN** the v2 compiler compiles from an escalation handoff bound to a `SnapshotLease`
- **THEN** the compiler uses the `snapshotId` from the `SnapshotLease`, identical to the handoff and matcher
- **AND** does not reload a different snapshot

#### Scenario: Snapshot drift produces structured PlannerFailure

- **WHEN** the compiler `snapshotId` drifts from the `GovernedContext.snapshotId`
- **THEN** the system returns a structured `PlannerFailure(SNAPSHOT_DRIFT)` with audit evidence
- **AND** does not silently degrade to `None`

### Requirement: LLM cannot create registry entities

The system SHALL NOT allow LLM output to create capabilities, relations, Fact Types, projections, or RuleSets. Every edge, projection, and RuleSet referenced by a PlanGraph v2 SHALL originate from the RegistrySnapshot.

#### Scenario: Entity not in snapshot is rejected

- **WHEN** a PlanGraph v2 references a projection, RuleSet, relation, or capability not present in the snapshot
- **THEN** validation fails closed and the entity is not created

### Requirement: A derived parameter is produced by plan execution, never by intent-time fetching

A parameter value derived from another capability's output SHALL be produced by executing the upstream node as part of the plan, in the order the plan declares. The intent and planning layers SHALL only author the upstream node, the consuming binding, and the edge between them. The intent layer MUST NOT call the Gateway, an RFC, an OData service, or any other data source while parsing an utterance or resolving a parameter, and MUST NOT obtain the value by any path other than the executed upstream node.

#### Scenario: Derived parameter requires an upstream node and an edge

- **WHEN** a consuming capability input is to be satisfied from another capability's output
- **THEN** the plan contains the producing capability as an upstream node, a `factField` source on the consuming node, and a `data` edge from producer to consumer
- **AND** the producing node precedes the consuming node in topological order

#### Scenario: Intent-time data fetching is not a source of derived values

- **WHEN** the intent layer resolves a parameter whose declared source is another capability's output
- **THEN** it produces a plan declaration and no Gateway validate, Gateway execute, RFC, OData, or SQL call is made during parsing
- **AND** the value appears only after the upstream node has executed

#### Scenario: Derived parameter does not bypass approval

- **WHEN** a write capability's parameter is derived from an upstream node's output
- **THEN** the write node still requires a recorded human confirmation before execution
- **AND** the derivation does not alter, weaken, or pre-satisfy the approval requirement

### Requirement: The planner pulls in a producer for an unbound derivable input, and only a Function producer

When a required input of a planned capability carries no user-supplied value and declares
`satisfiableByFactType`, the planner SHALL add that Fact Type to the goal's desired Fact Types so the
producing capability becomes a node of the plan. The addition SHALL be recorded in the goal
specification, so the reason the additional node exists is auditable from the plan itself rather than
being an implicit side effect of compilation.

The planner SHALL only pull in a producer whose capability is declared `kind: Function`. Because the
capability schema binds `kind: Function` to `sideEffect: none`, `requiresApproval: false`, and
`approvalPolicy: not_required`, this restriction structurally prevents an automatically added node from
being a write or from bypassing human approval. The planner MUST NOT pull in a capability declared
`kind: Action` for this purpose; when the only producer of a needed Fact Type is an Action, the input
SHALL be elicited from the user instead.

When a producer is pulled in automatically, the narration SHALL disclose that an additional read was
performed, and the approval surface SHALL mark a derived parameter value as derived rather than as
user-entered.

#### Scenario: Unbound derivable input pulls in its Function producer

- **WHEN** a planned capability has a required input with no user-supplied value that declares
  `satisfiableByFactType` for a Fact Type produced by a `kind: Function` capability
- **THEN** that Fact Type is added to the goal's desired Fact Types
- **AND** the producing capability appears as an upstream node preceding the consumer in topological order
- **AND** the goal specification records that the Fact Type was added to satisfy that input

#### Scenario: An Action producer is never pulled in automatically

- **WHEN** the only capability producing a needed Fact Type is declared `kind: Action`
- **THEN** the planner does not add that Fact Type to the goal's desired Fact Types
- **AND** no write node is introduced without a human request
- **AND** the consuming input is elicited from the user

#### Scenario: A bound input pulls in nothing

- **WHEN** every required input declaring `satisfiableByFactType` already has a user-supplied value
- **THEN** no additional Fact Type is added to the goal's desired Fact Types
- **AND** the plan contains no producer node on those inputs' account

#### Scenario: An automatically added read is disclosed

- **WHEN** a producer node was added automatically to satisfy an unbound input
- **THEN** the narration states that an additional read was performed
- **AND** the approval surface marks the resulting parameter value as derived rather than user-entered


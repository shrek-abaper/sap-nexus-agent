## MODIFIED Requirements

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

## ADDED Requirements

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


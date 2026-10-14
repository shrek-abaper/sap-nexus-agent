## Purpose

Own the server-side lifecycle of ontology-governed read analysis: pin one SemanticRelease per run, orchestrate the compiled read plan through the existing PlanExecutor with FakeGateway/offline defaults, reject WRITE before the Gateway, handle partial failures and bounded budgets, and emit evidence-grounded results through an offline contract/CLI entry — while legacy tools and the WRITE governance path remain unchanged.

## ADDED Requirements

### Requirement: Release pinning and dual-snapshot association

Each analysis run SHALL bind exactly one SemanticRelease at compile time and execute against that same package; updates published mid-run SHALL NOT mix into an in-flight run. The coordinator SHALL verify the package's `registrySnapshotId` / `semanticSnapshotId` association against the live build and fail closed on mismatch or on a stale plan presented against a new package. Result caches SHALL be isolated by semantic version and scope.

#### Scenario: In-flight run keeps one package

- **WHEN** a new SemanticRelease is published while a run is executing
- **THEN** the run completes against its pinned package
- **AND** its evidence records the pinned ids

#### Scenario: Association mismatch fails closed

- **WHEN** compile inputs present a package whose dual-id association does not verify
- **THEN** the run terminates with a structured release-mismatch failure
- **AND** no capability is executed

### Requirement: Orchestration reuses the existing read execution path

The DynamicReadCoordinator SHALL execute the compiled read plan through the existing PlanExecutor and GatewayClient interface; only that existing client executes SAP calls, and default execution uses FakeGateway offline. The Analysis Runtime SHALL hold no credentials and no network/Gateway client. The coordinator SHALL be independent of the material recommendation CompositionCoordinator and MUST NOT invoke the fixed projection/rule-set recommendation path.

#### Scenario: Default offline run uses FakeGateway

- **WHEN** an analysis run executes with default configuration
- **THEN** all capability reads come from FakeGateway fixtures with zero real network calls
- **AND** analysis values come from the Python runtime over the controlled adapter

#### Scenario: Analysis runtime has no execution credentials

- **WHEN** the analysis subprocess is spawned
- **THEN** it cannot reach SAP regardless of input content

### Requirement: WRITE rejection before Gateway

The path SHALL reject any WRITE, Action, or approval-bearing capability before a Gateway validate/execute call, including WRITE reached through nested derived dependencies or disguised as an analysis node. Rejection SHALL be typed and SHALL NOT auto-invoke or auto-redirect into the governed write proposal flow; it MAY surface the governed path as separate guidance. Rejection SHALL be verified by zero WRITE calls at the Gateway boundary.

#### Scenario: Direct WRITE request is rejected pre-Gateway

- **WHEN** a goal equivalent to "create a purchase requisition" enters the typed entry
- **THEN** the request is rejected with a typed WRITE rejection before any Gateway call
- **AND** the governed write flow is not executed

#### Scenario: Disguised or nested WRITE cannot reach the Gateway

- **WHEN** a draft hides a WRITE capability behind an analysis node or a derived dependency chain
- **THEN** compilation rejects the plan
- **AND** a Gateway call assertion observes zero WRITE capability calls

### Requirement: Server-owned principal, scope, and repeated visibility checks

Principal and scope SHALL be server-owned and bound to the run; draft-supplied principal/scope SHALL be ignored. Capability visibility SHALL be enforced before model candidate exposure, at compile, and again at execution. Graph reachability SHALL NOT imply authorization or provability of a business conclusion.

#### Scenario: Compile and execute re-check visibility

- **WHEN** a capability visible at compile time becomes non-executable at run time
- **THEN** execution refuses that capability with a structured denial
- **AND** affected conclusions are marked unsupported

### Requirement: Partial failures isolate dependent conclusions

When an independent read or analysis node fails, times out, or truncates, unrelated outputs MAY complete as `partial`; conclusions whose evidence chain depends on the failed node SHALL be marked with the appropriate gap/failure status and MUST NOT present inferred values. Node-level timeouts SHALL be bounded by the overall read-only execution budget.

#### Scenario: Independent outputs survive a node failure

- **WHEN** one read node fails while another independent read succeeds
- **THEN** the independent result is delivered with `partial` status and recorded limits
- **AND** conclusions needing the failed node are marked failed/gapped with no fabricated values

### Requirement: Versioned server-owned bounds

Node counts, dependency depth, interpreter interactions, overall and per-node execution timeouts, fact row caps, and response byte caps SHALL be server-configured, versioned, and independent of model-supplied values. Over-limit plans SHALL be rejected at compile time; over-cap data SHALL be handled with explicit incomplete marking.

#### Scenario: Draft cannot raise server bounds

- **WHEN** a draft declares more than six read nodes, six analysis nodes, or depth beyond four
- **THEN** compilation rejects the plan with a bounds error

#### Scenario: Default budgets are offline-safe

- **WHEN** the entry runs with default configuration
- **THEN** the overall read-only execution budget and fake interpreter defaults apply without external configuration

### Requirement: Evidence-grounded deterministic result rendering

Results SHALL render facts, deterministic rule/operator results, supported inferences, and limits distinctly, with every claimed value traceable to TypedFact rows/fields and registered operator/Definition versions. Narrative SHALL use deterministic templates by default; internal chain-of-thought SHALL never be exposed. Every result SHALL carry one of the closed statuses `complete`, `partial`, `clarification`, `capability_gap`, `semantic_gap`, `rejected`, `failed`, with covered and uncovered conclusions listed.

#### Scenario: Rendered answer separates facts, analysis, and gaps

- **WHEN** a mixed question yields one supported number and one unsupported conclusion
- **THEN** the output shows the supported value with evidence references and the uncovered conclusion with its gap type
- **AND** no internal reasoning text is emitted

### Requirement: Offline contract/CLI entry with full execution evidence

The system SHALL provide an offline Python contract/CLI entry accepting the typed request (plus a pinned package and fixtures) and emitting the full record: draft validation outcome, compiled read and analysis plans, release ids, per-node execution evidence, TypedFact rows, analysis results with row lineage, excluded rows and reasons, statuses, and uncovered conclusions. The entry SHALL run with no SAP, no paid model, and no network.

#### Scenario: CLI emits end-to-end evidence offline

- **WHEN** the CLI runs a fixture-backed question
- **THEN** stdout/stderr artifacts include plans, dual release ids, per-node evidence, lineage-bearing results, and status
- **AND** the run completes without network access

#### Scenario: Every negative case type is observable from the entry

- **WHEN** the CLI runs clarification, capability-gap, semantic-gap, and WRITE-rejection fixtures
- **THEN** each emits its typed status with no Gateway WRITE call

### Requirement: Legacy tools and WRITE governance unchanged

The four existing semantic tools, their v2 request/response contracts, the Harness main loop, approval/action governance, the Java Gateway and bindings, and the CompositionCoordinator path SHALL behave identically when the new capability is present but unused. A new tool name SHALL NOT be added to the closed SemanticToolName v2 union in this change; chat registration is a later workstream.

#### Scenario: Legacy regression with the new code present

- **WHEN** the existing semantic-tool regression suites and planner v2 suites run with this change deployed but unused
- **THEN** they pass unchanged
- **AND** no entry point routes legacy traffic through the new coordinator

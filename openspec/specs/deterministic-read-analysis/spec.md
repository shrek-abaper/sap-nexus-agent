# deterministic-read-analysis Specification

## Purpose
Compile resolved goals into a read PlanGraph v2 plus a separate registered-operator AnalysisPlan, then deterministically normalize gateway facts into TypedFacts and evaluate the four registered operators with a single Python authority, preserving row lineage, units, caliber boundaries, and completeness marks.

## Requirements

### Requirement: ValidatedReadAnalysisPlan v1 server-owned contract

The compiler SHALL emit a versioned server-generated plan carrying a server-generated `planId`, the pinned `semanticSnapshotId` and `registrySnapshotId`, principal/scope binding, a legal PlanGraph v2 `readPlan` (`executionMode: READ_ONLY`, `actionPartition: []`), a separate `analysisPlan` typed DAG (typed inputs/outputs, DefinitionRefs, operatorRefs), limits, fact requirements, freshness requirements, and coverage lists for supported and unsupported conclusions. Execution authorization SHALL NOT be grantable by the model: the read-only mode is set by server policy, and an older `PLAN_ONLY` draft cannot be upgraded by the model into execution. Plans SHALL be persisted as server-owned records; a client-uploaded "verified" flag or a client-edited graph cannot trigger execution.

#### Scenario: Read plan is READ_ONLY with empty action partition

- **WHEN** the compiler emits the read plan for a legal question
- **THEN** planGraphVersion is 2 with `executionMode: READ_ONLY` and `actionPartition: []`
- **AND** every read node is a visible active READ capability

#### Scenario: Client cannot authorize execution

- **WHEN** a client uploads a plan marked verified or modifies the DAG
- **THEN** the server rejects client-authored execution authority and recompiles from the release

### Requirement: AnalysisPlan DAG validation

The analysis DAG SHALL reference only registered operatorRefs and only Fact fields allowed by the release allowlist; analysis node inputs SHALL reference declared upstream analysis nodes or allowed Fact fields, never arbitrary JSONPath. The compiler SHALL reject unknown operators, unknown fields, cycles, excessive depth, and excessive node counts. Side-by-side presentation SHALL be expressible as structured output without forcing a numeric comparison.

#### Scenario: Illegal DAGs fail compilation

- **WHEN** an analysis node references an unregistered operator, an unknown field, a cycle, an arbitrary JSONPath, or exceeds node/depth bounds
- **THEN** compilation fails with a structured validation error
- **AND** no execution occurs

#### Scenario: Parallel display does not force compare

- **WHEN** the goal requests stock and order quantities side by side without a confirmed comparison semantics
- **THEN** the analysis plan uses projection/structured presentation only
- **AND** no numeric `compare` node is authored

### Requirement: TypedFact v1 normalized rows with evidence references

The normalizer SHALL produce TypedFact rows carrying object type and key including organizational/system scope, per-row identity, factTypeRef, field values with semantic types, separate unit/currency annotations, separate business time and collection time, a `definitionRef` only where a grounded applicable Definition exists (never a fabricated caliber), and run/node/execution/raw-field evidence references plus completeness and limits metadata.

#### Scenario: Normalized fact rows carry key, unit, time distinction, and evidence

- **WHEN** a read node returns order and inventory payloads through FakeGateway fixtures
- **THEN** each TypedFact row carries object key+scope, row identity, semantic field types, unit, distinct business/collection time, and resolvable evidence refs
- **AND** a payload field not in the allowlist cannot become a TypedFact analysis input

#### Scenario: Definition ref only with a real applicable Definition

- **WHEN** a value has no applicable grounded Definition
- **THEN** its TypedFact has no definitionRef rather than a placeholder caliber
- **AND** conclusions depending on that caliber are marked unsupported

### Requirement: Four registered operators with single-authority semantics

The Analysis Runtime SHALL provide exactly `select_fields`, `filter_eq`, `group_sum`, and `compare`, implemented once in Python using Decimal arithmetic. `group_sum` SHALL aggregate Decimal quantities only along legal object dimensions within equal units, preserving per-row lineage; a missing unit SHALL block quantity aggregation. `compare` SHALL compare only same-kind quantities with compatible caliber, matching units, and a time-point policy; otherwise it returns a semantic gap. Unsupported fields cannot be summed in the model or in TS; if existing fields cannot support an operator, the runtime returns a gap rather than computing client-side.

#### Scenario: Group sum keeps units and lineage

- **WHEN** PO quantities are grouped by supplier and unit
- **THEN** each group total carries its unit and references every contributing row
- **AND** rows with missing unit are excluded with a reported reason and no total is presented as complete across mixed units

#### Scenario: Incompatible compare gaps instead of coercing

- **WHEN** the inputs differ in caliber, unit, or allowed time-point semantics
- **THEN** compare returns a semantic gap naming the incompatibility
- **AND** no numeric result is produced

#### Scenario: Only one math implementation exists

- **WHEN** the TS side needs analysis values
- **THEN** it receives schema-checked results from the controlled Python entry
- **AND** no parallel TS arithmetic implementation for these operators is added

### Requirement: Reduction integrity and row identity

Reductions SHALL preserve row records throughout; multi-valued list fields SHALL NOT be flattened into unrelated columns and cross-multiplied or summed. Duplicate row identities SHALL be reported as a conflict; the system MUST NOT silently dedupe or double count without an explicit Definition.

#### Scenario: Duplicate row identity conflicts are reported

- **WHEN** fixture data contains two rows with the same documented row identity
- **THEN** the result reports a duplicate-identity conflict naming the identity
- **AND** neither silent dedupe nor double counting occurs

#### Scenario: Nested lists do not cross-multiply

- **WHEN** a PO header with multiple line items feeds a reduction
- **THEN** each line contributes exactly once with its own quantity and unit
- **AND** header fields are not multiplied across lines

### Requirement: Caliber boundaries for stock, orders, arrivals, and shortage claims

The system SHALL present the MD04 figure only under its existing evidence-grounded caliber and MUST NOT call it ATP, promised quantity, or guaranteed supply. Purchase order quantity is ordered quantity per material/plant/supplier/unit with PO/item identity; it MUST NOT be treated as received quantity, arrival quantity, or guaranteed in-transit supply. Without target-date demand and qualified due supply (including delivery-date/receipt data that the current facts do not contain), the system MUST NOT infer stockout certainty or guaranteed non-stockout.

#### Scenario: Q5 arrivals question returns a fact gap

- **WHEN** asked how much will arrive next week
- **THEN** the system returns a semantic/fact gap because no due/receipt quantity, delivery date, or receipt-status field exists
- **AND** order quantity is never relabeled as arrival quantity

#### Scenario: Q6 stockout question is not inferred from stock

- **WHEN** asked whether supply will certainly hold next week
- **THEN** the system reports the missing demand-and-supply semantics
- **AND** it does not project stockout certainty from current inventory alone

#### Scenario: WB/MD04 quantity is not presented as ATP

- **WHEN** inventory results are rendered
- **THEN** they are labeled with the MD04 running-available/stock snapshot caliber only
- **AND** no ATP or commitment claim is made

### Requirement: Controlled Python analysis entry point

TS SHALL invoke the Analysis Runtime via a bounded subprocess using an argument vector (no shell), a controlled stdin/stdout JSON protocol, no sensitive command-line values, and redacted logging, reusing the existing agent-runtime-adapter process, timeout, and error patterns. The Analysis Runtime process SHALL have no credentials and no network/Gateway access. Results SHALL validate against the AnalysisResult schema before use.

#### Scenario: Subprocess boundary has no credentials or network

- **WHEN** the adapter launches analysis
- **THEN** the child environment contains no gateway credentials and no network endpoint configuration
- **AND** all input values travel through stdin as JSON with logs redacted

#### Scenario: Schema-invalid child output fails closed

- **WHEN** the child emits malformed or schema-invalid JSON
- **THEN** the adapter returns a structured analysis failure without partial adoption

### Requirement: Bounded results with explicit incomplete marking

Read row counts and response bytes SHALL have server-configured caps. Over-cap results SHALL be explicitly truncated and marked incomplete; an aggregate computed over truncated inputs SHALL be marked incomplete and never reported as a complete total.

#### Scenario: Truncated aggregates are marked incomplete

- **WHEN** fixture rows exceed the configured row cap
- **THEN** the response names the cap and marks affected facts and aggregates incomplete
- **AND** the partial aggregate is never presented as a full group total

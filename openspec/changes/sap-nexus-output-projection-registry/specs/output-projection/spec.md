## ADDED Requirements

### Requirement: Versioned OutputProjection registry with declared input contract

The system SHALL provide an `OutputProjectionRegistry` that registers projections by `projectionId@version`. Each registered projection SHALL declare its required input FactTypes, optional input FactTypes, output schema, time basis (`asOf` policy), and partial policy. The registry SHALL resolve a projection by exact `projectionId` and `version`. A lookup for an unknown `projectionId` or unregistered `version` SHALL fail closed and record a structured failure. The registry MUST NOT call the LLM, the Gateway, or SAP.

#### Scenario: Registered projection resolved by id and version

- **WHEN** the registry resolves a registered `projectionId@version`
- **THEN** the registry returns the matching projection declaration
- **AND** the declaration exposes its required/optional FactTypes, output schema, time basis, and partial policy

#### Scenario: Unknown projection or version rejected

- **WHEN** the registry resolves a `projectionId` or `version` that is not registered
- **THEN** the registry rejects the lookup fail-closed
- **AND** records a structured failure identifying the unknown `projectionId`/`version`

### Requirement: Projection input assembly from PlanExecutorResult

The system SHALL provide a `ProjectionInputAssembler` that consumes a `PlanExecutorResult` plus the per-node Gateway execute results and produces a `PlanExecutionRecord` (carrying `snapshotId`, node ledger summary, and `asOf`) together with the successful `ReasoningFact[]`. Only `SUCCEEDED` nodes SHALL contribute facts. Nodes in `FAILED`, `TIMED_OUT`, `CANCELLED`, `BLOCKED_DEPENDENCY`, or `BLOCKED_APPROVAL` state SHALL NOT contribute facts. The assembler MUST NOT read raw Gateway payload beyond what is needed to build normalized facts, and MUST NOT read conversation text or model output.

#### Scenario: Dual READ success assembles facts

- **WHEN** the assembler receives a `PlanExecutorResult` where both READ nodes are `SUCCEEDED`
- **THEN** the assembler produces a `PlanExecutionRecord` and a `ReasoningFact[]` containing one fact per successful node
- **AND** the `PlanExecutionRecord` carries the bound `snapshotId`

#### Scenario: Non-succeeded nodes excluded from facts

- **WHEN** the assembler receives a `PlanExecutorResult` containing a `FAILED` or `TIMED_OUT` or `CANCELLED` node
- **THEN** the assembler excludes that node from the `ReasoningFact[]`
- **AND** records the node in the `PlanExecutionRecord` node ledger summary

#### Scenario: Missing FactBuilder degrades gracefully

- **WHEN** a `SUCCEEDED` node's `capabilityId` has no registered `FactBuilder`
- **THEN** the assembler contributes no fact for that node
- **AND** records the node's required FactType in `missingFacts` with reason `no_fact_builder`
- **AND** the projection yields `incomplete`

#### Scenario: Fact correlation uses the executor run identity

- **WHEN** a registered FactBuilder builds facts for a successful node
- **THEN** every fact's `agentTraceId` and `traceId` equal the trusted `agentTraceId` carried by that node record
- **AND** `gatewayTraceId` remains the separate Gateway correlation identifier
- **AND** none of those identifiers is an empty placeholder

#### Scenario: Missing Gateway correlation degrades explicitly

- **WHEN** a `SUCCEEDED` node record has `gatewayTraceId` = `null`
- **THEN** the assembler does not invoke its FactBuilder and contributes no fact for that node
- **AND** records every declared FactType in `missingFacts` with reason `missing_gateway_trace`
- **AND** no `ReasoningFact` contains an empty or substituted Gateway correlation identifier

#### Scenario: Purchase-order quantities normalize deterministically

- **WHEN** PO items contain a finite number or a valid finite decimal string quantity
- **THEN** the builder emits the same normalized numeric `value` for equivalent quantities
- **AND** preserves the whitelisted source value in evidence
- **AND** rejects `NaN`, infinity, and invalid numeric strings from numeric value output

#### Scenario: Purchase-order item quantity presence takes precedence

- **WHEN** a nested PO item contains an `orderQuantity` field that is invalid or empty and its header contains a valid quantity
- **THEN** the builder preserves the item's whitelisted source value in evidence
- **AND** emits `value` = `null`
- **AND** does not substitute the header quantity

#### Scenario: Purchase-order fact identity is input-order independent

- **WHEN** multiple PO rows share purchase order, material, and plant but differ in item, quantity, unit, or other whitelisted evidence
- **THEN** the builder applies a total deterministic ordering before assigning fact ids
- **AND** permutations of the same input rows produce identical facts and fact ids

#### Scenario: Malformed freshness falls back to executor time

- **WHEN** `dataAsOf` is malformed or lacks an explicit timezone
- **THEN** the builder falls back to the trusted executor `nodeExecutedAt`

#### Scenario: Freshness aggregates by instant

- **WHEN** successful facts carry valid ISO-8601 times with different timezone offsets
- **THEN** each fact preserves its selected source string
- **AND** `PlanExecutionRecord.asOf` is the earliest instant by epoch, normalized to UTC `toISOString()`
- **AND** equivalent instants expressed with different offsets produce the same aggregate `asOf`

### Requirement: MaterialSupplySnapshot projection produces composite fact bundle

The system SHALL provide a `material-supply-snapshot` projection registered in the `OutputProjectionRegistry` that projects a `PlanExecutionRecord` plus successful `ReasoningFact[]` into a `MaterialSupplySnapshot` consisting of `{ asOf, sourceFreshness, completeness, facts, lineage, missingFacts, failedNodes, limitations }`. The projection SHALL treat the snapshot as a composite fact bundle with lineage and metadata, NOT a derived business metric, and MUST NOT compute procurement quantities, dates, or purchasing groups. Every output fact field SHALL be traceable via `lineage` to its source fact and evidence.

#### Scenario: Dual READ success yields complete snapshot with full lineage

- **WHEN** the projection receives a `PlanExecutionRecord` with both READ facts present, no failed nodes, and all nodes sharing the same `dataAsOf` (no freshness mismatch)
- **THEN** the projection yields a `MaterialSupplySnapshot` with `completeness` = `complete`
- **AND** no `limitations` are produced
- **AND** every output fact field has a `lineage` entry tracing to its source fact/evidence
- **AND** lineage completeness is 100%

### Requirement: Partial and incomplete completeness policy

The projection SHALL derive `completeness` as one of `complete`, `partial`, or `incomplete`. `complete` requires all required FactTypes present and no failed nodes. `partial` applies when optional facts are missing or a `limitation` is present but all required facts exist. `incomplete` applies when any required FactType is missing or any node is `FAILED`, `TIMED_OUT`, or `CANCELLED`. The projection SHALL populate `missingFacts`, `failedNodes`, and `limitations` accordingly. The projection MUST NOT mark a snapshot `complete` when a required fact is missing or a node failed/timed out/was cancelled.

#### Scenario: Single node failure yields incomplete snapshot

- **WHEN** the projection receives a `PlanExecutionRecord` where one READ node is `FAILED`
- **THEN** the projection yields `completeness` = `incomplete`
- **AND** populates `failedNodes` with the failed node id
- **AND** populates `missingFacts` with the required FactType the failed node was to produce

#### Scenario: Missing optional fact yields partial snapshot

- **WHEN** the projection receives a `PlanExecutionRecord` where all required FactTypes are present but an optional FactType is absent
- **THEN** the projection yields `completeness` = `partial`
- **AND** records a `limitation` describing the missing optional fact

### Requirement: Freshness, unit, and conflict determinism

The projection SHALL handle cross-node `asOf` mismatch by preserving each node's own time in `sourceFreshness` and producing a `limitation`; it MUST NOT collapse distinct `asOf` values into a single value. The projection SHALL handle unit incompatibility deterministically (record a `limitation`, exclude the incompatible field from `complete` accounting). The projection SHALL handle duplicate or conflicting facts (same predicate, differing values) deterministically and record a `limitation`. Numeric, unit, and time conversions SHALL be performed only by versioned deterministic rules.

#### Scenario: Freshness mismatch produces limitation

- **WHEN** two successful facts carry different `asOf` times
- **THEN** the projection preserves each `asOf` in `sourceFreshness`
- **AND** produces a `limitation` describing the freshness mismatch

#### Scenario: Unit incompatibility handled deterministically

- **WHEN** two facts carry incompatible units for the same logical field
- **THEN** the projection records a `limitation`
- **AND** excludes the incompatible field from `complete` accounting

#### Scenario: Duplicate fact deduplicated

- **WHEN** two facts share the same predicate (within the same business object/material/plant context) and carry the same value
- **THEN** the projection deduplicates, keeping one fact (stable sort by `factId`)
- **AND** produces no `limitation`

#### Scenario: Conflicting facts kept with conflict marker

- **WHEN** two facts share the same predicate (within the same business object/material/plant context) but carry differing values
- **THEN** the projection keeps both values in `facts` (stable sort by `factId`) marked `conflict: true`
- **AND** records a `conflict` `limitation` describing the conflict
- **AND** excludes the conflicted field from `complete` accounting, yielding `incomplete` when the predicate is required

### Requirement: Deterministic output hash

The projection SHALL compute a deterministic output hash from the normalized facts (sorted), the projection `version`, and the `snapshotId`. The same inputs (facts, projection version, snapshotId) SHALL always produce the same hash. Different inputs SHALL produce a different hash.

#### Scenario: Same inputs produce same hash

- **WHEN** the projection runs twice with the same facts, projection `version`, and `snapshotId`
- **THEN** both runs produce identical output hashes

#### Scenario: Different inputs produce different hash

- **WHEN** the projection runs with facts differing in value or in projection `version` or `snapshotId`
- **THEN** the output hash differs

### Requirement: Projection isolated from raw payload and model output

The projection SHALL consume only normalized `ReasoningFact` values and ledger metadata. The projection MUST NOT read raw Gateway payload, conversation text, or LLM/model output. Numeric, unit, and time transformations SHALL be performed only by versioned deterministic rules declared by the projection.

#### Scenario: Projection consumes only normalized facts

- **WHEN** the projection runs
- **THEN** it reads only normalized `ReasoningFact` values and `PlanExecutionRecord` ledger metadata
- **AND** it does not access raw Gateway payload, conversation text, or model output

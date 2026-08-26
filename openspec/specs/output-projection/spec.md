# output-projection Specification

## Purpose
TBD - created by archiving change sap-nexus-output-projection-registry. Update Purpose after archive.
## Requirements
### Requirement: Versioned OutputProjection registry with declared input contract

The system SHALL provide an `OutputProjectionRegistry` that registers projections by the logical tuple `(projectionId, version)`. Each registered projection SHALL declare its required input FactTypes, optional input FactTypes, output schema, time basis (`asOf` policy), and partial policy. The registry SHALL resolve a projection by exact `projectionId` and `version`, preserving tuple boundaries even when either accepted identifier contains `@`. A lookup for an unknown `projectionId` or unregistered `version` SHALL fail closed and record a structured failure. The registry MUST NOT call the LLM, the Gateway, or SAP.

#### Scenario: Registered projection resolved by id and version

- **WHEN** the registry resolves a registered `projectionId@version`
- **THEN** the registry returns the matching projection declaration
- **AND** the declaration exposes its required/optional FactTypes, output schema, time basis, and partial policy

#### Scenario: Unknown projection or version rejected

- **WHEN** the registry resolves a `projectionId` or `version` that is not registered
- **THEN** the registry rejects the lookup fail-closed
- **AND** records a structured failure identifying the unknown `projectionId`/`version`

#### Scenario: Identifier delimiters do not alias registry tuples

- **WHEN** the registry contains `(projectionId="a@b", version="c")`
- **THEN** resolving `(projectionId="a", version="b@c")` fails closed unless that exact tuple is separately registered
- **AND** both distinct tuples can be registered and resolved independently
- **AND** an exact duplicate tuple is rejected

### Requirement: Projection input assembly from PlanExecutorResult

The system SHALL provide a `ProjectionInputAssembler` that consumes a `PlanExecutorResult` plus the per-node Gateway execute results and produces a `PlanExecutionRecord` (carrying `snapshotId`, node ledger summary, and `asOf`) together with the successful `ReasoningFact[]`. Only `SUCCEEDED` nodes SHALL contribute facts. Nodes in `FAILED`, `TIMED_OUT`, `CANCELLED`, `BLOCKED_DEPENDENCY`, or `BLOCKED_APPROVAL` state SHALL NOT contribute facts. Observable node, fact, ledger-summary, and missing-fact ordering introduced by this pipeline SHALL use explicit code-unit ordering independent of process locale. Aggregate `asOf` SHALL be computed by a single pass over fact epochs without a cardinality-dependent argument spread. The assembler MUST NOT read raw Gateway payload beyond what is needed to build normalized facts, and MUST NOT read conversation text or model output.

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

#### Scenario: Mixed identifier ordering is replay-stable

- **WHEN** successful nodes use mixed-case or non-ASCII node ids
- **THEN** facts, missing facts, succeeded node results, and node ledger summaries use code-unit ordering
- **AND** the order does not depend on the host locale or ICU defaults

### Requirement: Durable projection payload recovery

For a newly completed READ node, the executor SHALL durably persist the complete fact-building payload before recording the authoritative `EXECUTING -> SUCCEEDED` transition. This is an explicit cache-first ordering contract, not a cross-store atomicity claim. On restart, an `EXECUTING` node with a complete matching payload SHALL transition directly to `SUCCEEDED` and hydrate its `NodeFactRecord` without calling Gateway/SAP again. An `EXECUTING` node with no complete payload SHALL transition to `FAILED` without repeating the READ. A historical pre-change `SUCCEEDED` node without a complete payload SHALL remain `SUCCEEDED`, omit the unavailable `NodeFactRecord`, and SHALL NOT be re-executed.

#### Scenario: Persisted payload completes interrupted success

- **WHEN** the payload is durable but execution stops before the `SUCCEEDED` ledger transition
- **THEN** restart performs the legal `EXECUTING -> SUCCEEDED` transition
- **AND** restores the complete node fact record
- **AND** does not call Gateway/SAP again

#### Scenario: Missing payload after interrupted execution fails closed

- **WHEN** restart finds an `EXECUTING` node without a complete matching payload
- **THEN** the node transitions to `FAILED`
- **AND** no Gateway/SAP READ is repeated

#### Scenario: Historical success without payload degrades without replay

- **WHEN** restart finds a pre-change `SUCCEEDED` node without a complete payload
- **THEN** the node remains `SUCCEEDED` and contributes no reconstructed `NodeFactRecord`
- **AND** no Gateway/SAP READ is repeated

### Requirement: MaterialSupplySnapshot projection produces composite fact bundle

The system SHALL provide a `material-supply-snapshot` projection registered in the `OutputProjectionRegistry` that projects a `PlanExecutionRecord` plus successful `ReasoningFact[]` into a `MaterialSupplySnapshot` consisting of `{ asOf, sourceFreshness, completeness, facts, lineage, missingFacts, failedNodes, limitations }`. The projection SHALL treat the snapshot as a composite fact bundle with lineage and metadata, NOT a derived business metric, and MUST NOT compute procurement quantities, dates, or purchasing groups. Every output fact field SHALL be traceable via `lineage` to its source fact and evidence.

#### Scenario: Dual READ success yields complete snapshot with full lineage

- **WHEN** the projection receives a `PlanExecutionRecord` with both READ facts present, no failed nodes, and all nodes sharing the same parsed `dataAsOf` instant (no freshness mismatch)
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

The projection SHALL handle cross-node `asOf` mismatch by comparing distinct parsed epochs, preserving each node's original source string in `sourceFreshness`, and producing a `limitation` only for distinct instants. Offset-different strings representing the same epoch SHALL NOT produce a mismatch. The projection SHALL handle unit incompatibility deterministically (record a `limitation`, exclude the incompatible field from `complete` accounting). The projection SHALL handle duplicate or conflicting facts (same predicate, differing values) deterministically and record a `limitation`. Numeric, unit, and time conversions SHALL be performed only by versioned deterministic rules.

#### Scenario: Freshness mismatch produces limitation

- **WHEN** two successful facts carry `asOf` values with different parsed epochs
- **THEN** the projection preserves each `asOf` in `sourceFreshness`
- **AND** produces a `limitation` describing the freshness mismatch

#### Scenario: Offset-equivalent freshness is not a mismatch

- **WHEN** two successful facts carry `2026-08-04T00:00:00Z` and `2026-08-04T08:00:00+08:00`
- **THEN** the projection preserves both original strings in `sourceFreshness`
- **AND** produces no freshness mismatch limitation

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

The projection SHALL compute `sha256(canonicalJson({ facts: normalizeFacts(facts), version, snapshotId }))`. The canonical object envelope SHALL frame the normalized facts, projection `version`, and `snapshotId` without ambiguous string concatenation. The same inputs (facts, projection version, snapshotId) SHALL always produce the same hash. Different inputs SHALL produce a different hash.

#### Scenario: Same inputs produce same hash

- **WHEN** the projection runs twice with the same facts, projection `version`, and `snapshotId`
- **THEN** both runs produce identical output hashes

#### Scenario: Different inputs produce different hash

- **WHEN** the projection runs with facts differing in value or in projection `version` or `snapshotId`
- **THEN** the output hash differs

#### Scenario: Version and snapshot boundaries cannot collide

- **WHEN** normalized facts are equal but one input uses `(version="1", snapshotId="23")` and another uses `(version="12", snapshotId="3")`
- **THEN** the output hashes differ

### Requirement: Projection isolated from raw payload and model output

The projection SHALL consume only normalized `ReasoningFact` values and ledger metadata. The projection MUST NOT read raw Gateway payload, conversation text, or LLM/model output. Numeric, unit, and time transformations SHALL be performed only by versioned deterministic rules declared by the projection.

#### Scenario: Projection consumes only normalized facts

- **WHEN** the projection runs
- **THEN** it reads only normalized `ReasoningFact` values and `PlanExecutionRecord` ledger metadata
- **AND** it does not access raw Gateway payload, conversation text, or model output

### Requirement: Projection field names conform to the authoritative Fact Type field list
Every projection-layer or presentation-layer restatement of a Fact Type's field names SHALL be conformance-checked against the authoritative Fact Type field list. The check SHALL fail when a restated field name does not exist in the authoritative list, and when a restatement drifts from the authoritative list by rename. A restatement MUST NOT introduce a field name that the Fact Type does not declare.

#### Scenario: Renamed authoritative field breaks the restatement

- **WHEN** a field is renamed in the authoritative Fact Type field list
- **THEN** the conformance check fails for every restatement that still carries the old name

#### Scenario: Unknown restated field name is rejected

- **WHEN** a projection-layer restatement names a field that the Fact Type does not declare
- **THEN** the conformance check fails and names the offending field and artifact

### Requirement: Every active primary-fact capability resolves a projection builder
The projection layer SHALL resolve a fact builder for every active capability that declares a primary Fact output. When a capability declares a primary Fact output and no builder resolves for it, the projection layer SHALL fail closed with a structured failure naming the capability, rather than silently producing no fact. A capability whose node produces no fact MUST NOT be treated as a successfully projected node.

#### Scenario: Registered capability without a builder fails closed

- **WHEN** an active capability declares a primary Fact output and the projection layer cannot resolve a builder for it
- **THEN** the projection reports a structured failure naming that capability
- **AND** the node is not reported as having produced a fact

#### Scenario: Derived parameter provenance survives projection

- **WHEN** a consuming node's parameter was resolved from an upstream node's fact field
- **THEN** the projected evidence retains the resolved value, its provenance, and the identity of the upstream node
- **AND** the value is not stripped from the payload presented for human approval


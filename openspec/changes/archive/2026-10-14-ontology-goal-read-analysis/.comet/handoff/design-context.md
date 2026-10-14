# Comet Design Handoff

- Change: ontology-goal-read-analysis
- Phase: design
- Mode: compact
- Context hash: 7577b066d48d660feb7bece9c1260ff2df35da71710455c59be77cc2c7e7d53f

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/ontology-goal-read-analysis/proposal.md

- Source: openspec/changes/ontology-goal-read-analysis/proposal.md
- Lines: 1-32
- SHA256: 0b813d77b32969c095bb1b3498f288201a2099b441d59e66e11b4f1956ef1319

```md
## Why

New business questions should not require a new question-specific business function. Today planning starts from already-matched capabilities (`compile_plan_v2` consumes an `EscalationHandoff`; the GoalSpec is aggregated from hit capability cards plus an auto-pull closure) — there is no server-owned entry that starts from the facts a question needs and only then chooses capabilities. The `CompositionCoordinator` is hard-wired to the material-supply projection, shortage rule set, and PR recommendation, so it cannot serve as a general read-only analysis coordinator. This change is phase C2 of the plan in `docs/nexus-ontology-planning-handoff.md`: it adds the goal-first, ontology-constrained, deterministic read-only analysis path over the SemanticRelease package delivered by the prerequisite change `semantic-release-asset-pipeline` (C1). New legal combination questions become answerable through registered capabilities and registered operators without new recipes; missing capabilities/caliber/facts stop the related conclusions instead of fabricating them.

## What Changes

- Add **SemanticGoalDraft v1**: an untrusted, strict, versioned draft contract (requested facts with object selectors, typed constraints and their provenance, a bounded analysis DAG of registered operator references, requested conclusions with evidence requirements, explanatory-only assumptions). No RFC names, binding ids, URLs, credentials, SQL/code/expressions, arbitrary JSONPath, execution authorization, or dynamic imports; strict schema plus deep technical-key scanning and bounded-input validation.
- Add a **fake GoalInterpreter with a model-adapter interface** (fake default; no paid-model calls), and a server-owned **GoalResolver + SemanticCompiler** that validate the draft, resolve desired Fact types/fields against the pinned SemanticRelease, search visible active READ capabilities for producers, run the existing dependency derivation closure, and deterministically emit a **ValidatedReadAnalysisPlan v1** containing a legal PlanGraph v2 read plan (`executionMode: READ_ONLY`, `actionPartition: []`) plus a separate registered-operator AnalysisPlan DAG — never a merged "capability" operator.
- Add **TypedFact v1 / AnalysisResult v1** versioned contracts: object keys with organizational scope, row identity, field semantic types, unit/currency, business vs collection time, Definition refs only where a Definition exists, run/node/execution/raw-field evidence refs, completeness/limits, and a closed result status set (`complete`, `partial`, `clarification`, `capability_gap`, `semantic_gap`, `rejected`, `failed`).
- Add a **TypedFactNormalizer** and exactly four deterministic analysis operators (`select_fields`, `filter_eq`, `group_sum`, `compare`) with one Python implementation authority (Decimal), per-row lineage, unit-mandatory aggregation, duplicate-row reporting, and truncation/incomplete handling; TS invokes Python only through a controlled stdin/stdout subprocess adapter reusing the existing agent-runtime-adapter process/timeout pattern — no shell string building, no second math implementation.
- Add a **DynamicReadCoordinator** (TS trusted orchestration) that pins one SemanticRelease per run (dual snapshot association verified, no in-flight mixing), reuses the existing PlanExecutor/GatewayClient/FakeGateway, runs WRITE rejection before any Gateway call (including nested or analysis-disguised WRITE attempts), and renders evidence-grounded results (facts / rule results / inferences / limits) with deterministic templates.
- Add an **offline Python contract/CLI entry** and the synthetic/redacted offline case set emitting complete execution evidence. The DSH chat tool registration and any live/paid evaluation are explicitly C3 and out of scope.

## Capabilities

### New Capabilities
- `semantic-goal-resolution`: Untrusted SemanticGoalDraft v1 intake and validation, goal-first desired-fact resolution against a pinned SemanticRelease, visible READ producer search, deterministic gap/ambiguity/clarification outcomes, and bounded interpreter interaction through a fake-default adapter.
- `deterministic-read-analysis`: Deterministic compilation and execution of the read PlanGraph v2 plus the separate registered-operator AnalysisPlan, TypedFact/AnalysisResult contracts, row-lineage-preserving normalizer and four operators with a single Python authority, and semantic-validity guards (units, object identity, truncation, caliber gaps).
- `dynamic-read-coordinator`: Server-owned plan lifecycle and release pinning, DynamicReadCoordinator orchestration over the existing PlanExecutor, pre-Gateway WRITE rejection, scoped visibility re-checks, partial-failure handling, bounded budgets, and the offline evidence-emitting contract/CLI entry, with legacy tool and WRITE-gate compatibility guarantees.

### Modified Capabilities
<!-- None. PlanGraph v2, the legacy GoalSpec, SemanticToolName v2 contract, Harness main loop,
     CompositionCoordinator, Java Gateway/bindings, and approval governance are reused unchanged;
     any shared compiler primitives are extracted behind wrappers with legacy entry points preserved. -->

## Impact

- **New Python package (planned)**: `agent/sap_nexus_agent/ontology_planning/` (`contracts.py`, `release.py`, `goal_interpreter.py`, `resolver.py`, `compiler.py`, `validation.py`, `fact_normalizer.py`, `analysis_runtime.py`, `cli.py`) plus new JSON schemas and offline eval case files.
- **New TS (planned)**: `frontend/src/runtime/dynamic-analysis/` (`coordinator.ts`, `python-analysis-adapter.ts`, `types.ts`), reusing PlanExecutor, plan-graph-v2-parser, node ledger, durable/principal machinery, and the agent-runtime-adapter subprocess pattern; no DSH server registration in this change.
- **Reused**: `semantic_planning/graph.py`, `derivation.py`, `validation_v2.py`, `planner/plan_compiler_v2.py` primitives (via extraction behind wrappers; legacy entries preserved), existing capability visibility filtering, FakeGateway.
- **Dependency on C1**: consumes the SemanticRelease v1 package; builds and tests run against a package produced by `semantic-release-asset-pipeline`; this change must not archive before C1 is archived (or explicitly handoff-confirmed).
- **Verification**: new Python package tests, direct compiler/derivation/snapshot regression tests, TS adapter/coordinator tests under `npm --prefix frontend run verify`, offline case matrix; everything runs offline with FakeGateway and the fake interpreter. No SAP, paid model, commits, push, or deployment in this change.

```

## openspec/changes/ontology-goal-read-analysis/design.md

- Source: openspec/changes/ontology-goal-read-analysis/design.md
- Lines: 1-93
- SHA256: b92f6e14b193a697e27bf9993297c80cb0c41b9bb3d1ef2550d527cacd626142

[TRUNCATED]

```md
## Context

See `proposal.md` - Why. Baseline facts verified at HEAD `6444144`:

- `compile_plan_v2(handoff, snapshot, sources)` starts from an `EscalationHandoff` of already-matched intents; GoalSpec is aggregated from capability cards and auto-pulled closures. Ambiguity machinery exists (`_ambiguous_producer_fact_types` → gap, no list-order authoring), but there is no goal-first entry and no analysis layer.
- PlanGraph v2 schema already fixes `executionMode` to `PLAN_ONLY | READ_ONLY`; the read partition / action partition model exists and the TS executor blocks approval-required nodes (`BLOCKED_APPROVAL`) before the Gateway.
- TS `PlanExecutor` + node ledger + DAG scheduler + recovery are reusable against the `GatewayClient` interface; `FakeGateway` is a programmable stub. TS `projection/fact-builder.ts` already normalizes PO header/items into typed rows (supplier, order quantity, unit, identity) and is the reference shape for the Python normalizer.
- `agent-runtime-adapter.ts` already spawns Python via arg vector with stdin JSON, `PYTHONPATH=agent`, timeout, and output capture — the pattern for the analysis adapter.
- The three MM READ capabilities are active, Function, `sideEffect: none`, `requiresApproval: false` with verified bindings; PO supply facts contain order quantity/unit/supplier/identity but **no** delivery date, goods-receipt quantity, or receipt status; the MD04 output is running available qty plus opaque MRP lines.
- SemanticToolName v2 is a closed four-name union; typed requests currently go through `buildToolQuery()` text rendering.
- Depends on the C1 package (`semantic-release-asset-pipeline`) for the release contract, allowlist, object catalog, and operator catalog.

## Goals / Non-Goals

**Goals:**

- One offline, deterministic end-to-end path: typed question → validated draft → goal resolution → read PlanGraph v2 + AnalysisPlan → FakeGateway execution → TypedFacts → operator results → evidence-grounded response.
- Negative cases (clarify, capability gap, semantic gap, WRITE rejection) typed and observable before any Gateway WRITE call.
- All new behavior additive; legacy paths byte-identical.

**Non-Goals:** design.md carries only the open-phase framework; deeper module APIs, fixture schemas, and exact config values are finalized in the design-phase Design Doc. Not in scope: DSH chat registration/UI, live SAP, paid models, cross-domain questions, WRITE dynamics, real identity/tenant governance, holdout authoring by the implementation team.

## Decisions

### ADR-1. New typed entry and new versioned contracts — do not extend SemanticToolName v2

The new `analyze_business_question` entry is built on new contracts (`SemanticGoalDraft v1`, `ReadAnalysisPlan v1`, `TypedFact v1`, `AnalysisResult v1`); the SemanticToolName v2 union and its request/response schemas are untouched. Typed slots enter the planner directly.

- Alternative rejected: add a fifth name to the v2 union / add silent fields to GoalSpec. Both force every legacy consumer through dual-version logic and couple an unbuilt feature to WRITE tooling.
- Consequence: chat registration (C3) is a separate change; until then the path is reachable via Python contract/CLI and TS internals only.

### ADR-2. Goal-first resolver/compiler reuses v2 primitives behind wrappers

A new package `agent/sap_nexus_agent/ontology_planning/` owns resolver/compiler/orchestration types. Reusable primitives (producer indexing, raw capability projection, node governance projection, derivation closure, v2 plan-graph validation) are extracted from `plan_compiler_v2.py` / `plan_compiler.py` into shared functions **only where extraction is mechanical**; both the legacy entry and the new compiler call the shared functions. Legacy function signatures and outputs are preserved (regression suites are the contract). The new compiler starts from desired facts in the draft — not from matched intents — and authors read nodes only through the existing ambiguity policy.

- Alternative rejected: fork a v3 compiler copy. Two compilers drift silently and double-maintain producer/derivation semantics.
- Risk mitigation: extraction tasks land behind the existing v2 test suite first; any non-mechanical extraction becomes a wrapper call, never a behavior edit.

### ADR-3. ReadPlan and AnalysisPlan are separate documents

`readPlan` is a legal PlanGraph v2 (`READ_ONLY`, `actionPartition: []`); `analysisPlan` is a separate typed DAG whose nodes carry `operatorRef` + DefinitionRefs, not capability ids. Operators never masquerade as SAP capabilities, so capability graph reachability can never authorize an operator and vice versa. Plan mode is server policy; a model cannot promote `PLAN_ONLY` to execution.

- Alternative rejected: attach operator nodes to the PlanGraph as pseudo-capabilities. Rejected because it breaks the READ/Action partition invariants and executor assumptions.

### ADR-4. Single Python authority for analysis; TS is orchestration-only

All four operators and Decimal arithmetic live once in Python (`analysis_runtime.py`). TS `python-analysis-adapter.ts` follows `agent-runtime-adapter.ts`: arg-vector spawn, stdin JSON, stdout schema-checked JSON, timeout/error parity, redacted logs, no sensitive argv values. The child env carries no credentials and no gateway URL; only the existing TS GatewayClient calls SAP.

- Alternative rejected: TS operator port "to stay consistent" — explicitly forbidden by the handoff; two Decimal-capable runtimes cannot be kept numerically identical.
- Integration shape: TS sends minimized TypedFact inputs + pinned operator versions; child validates inputs against the operator catalog version and returns schema-bound AnalysisResults.

### ADR-5. TypedFactNormalizer consumes the C1 allowlist; one mapping source

Normalization maps registered raw output fields to TypedFact rows strictly through the C1 Fact-field allowlist and object-key catalog. The existing TS `fact-builder.ts` header/item normalization (including `items[]` expansion and header fallback) is the reference for edge cases, but the Python normalizer derives its field map from the release asset — not from a copied table — to avoid dual mapping authority. Rows carry object key+scope, stable row identity (PO + item), unit, business/collection time, and evidence refs; opaque lists (MRP lines) stay opaque.

- Open detail for Design Doc: how much of the header/item fallback logic is itself declared in the mapping asset vs coded once in Python.

### ADR-6. Caliber gaps are structural, not prompt-level

Q5/Q6 are unanswerable by construction in current facts (no delivery/receipt fields; no demand inputs; MD04 WB snapshot is not ATP). The gap is produced by resolution/operator preconditions referencing registered Fact fields and Definition applicability — there is no prompt that can make the values exist. Stock vs order quantities may be presented side by side; `compare` is legal only with matching kind/unit/time policy. Inventory is labeled with the existing MD04 caliber only.

### ADR-7. Defense-in-depth WRITE rejection

WRITE is blocked at four independent points: (1) producer search admits only `sideEffect: none` + `requiresApproval: false` visible actives; (2) compiler asserts `actionPartition: []` and rejects any approval-bearing node reached via closure; (3) analysis DAG validation forbids capability references except declared read outputs; (4) executor-level `BLOCKED_APPROVAL` remains. Tests assert zero WRITE Gateway calls for direct, nested, and disguised attempts. The response may mention the governed write path as guidance but never auto-invokes it.

### ADR-8. Pinned release, server-owned everything

Compile binds one SemanticRelease and its dual ids; association is verified (C1 check) and the run is pinned in its durable record; caches key by (semanticSnapshotId, scope). Snapshot/principal/scope/bounds from the draft are ignored. Bounds (6 read nodes / 6 analysis nodes / depth 4 / ≤2 model turns / 90 s overall / row+byte caps) live in versioned server config; concrete row/byte defaults are set in the Design Doc from existing response contracts.

### ADR-9. Fake interpreter and FakeGateway by default; evidence-first CLI

A deterministic fake GoalInterpreter implements the model-adapter interface from fixture scripts; remote selection is impossible without explicit later authorization. The Python CLI emits the complete evidence chain (plans, release ids, node evidence, TypedFacts, lineage, exclusions, statuses, uncovered conclusions) so offline cases assert evidence, not prose.

## Risks / Trade-offs

- [Shared-primitive extraction regresses the v2 compiler] → extraction tasks gated by the full existing v2/derivation suite before any new code is used; legacy entry test outputs compared unchanged.
- [Two normalizer implementations (existing TS projection vs new Python)] → the new path does not reuse TS rows; the release allowlist is the single field authority; cross-parity fixtures assert identical material values on shared PO fixtures.
- [Subprocess reliability/perf] → reuse proven spawn/capture/timeout path; bounded payloads; structured child failures; no second service. Performance is unmeasured in this phase — recorded, no SLA claimed.
- [Fake interpreter "passing" is mistaken for LLM-quality validation] → fake interpreter asserts deterministic contract behavior only; C3 gates real-model evaluation; docs and task descriptions label every fixture result as contract evidence.
- [Operators get over-applied (sum across units, compare incomparables)] → unit-mandatory and compatibility preconditions are spec scenarios enforced in code; mixed/missing units produce reported exclusions.

```

Full source: openspec/changes/ontology-goal-read-analysis/design.md

## openspec/changes/ontology-goal-read-analysis/tasks.md

- Source: openspec/changes/ontology-goal-read-analysis/tasks.md
- Lines: 1-88
- SHA256: ce2cd713130de5aa624e4cec06c74b7b5771c1a1c2d2247cba0fd8b297032899

[TRUNCATED]

```md
# Tasks — ontology-goal-read-analysis (C2)

> Prerequisites: user-confirmed C0 design; **C1 `semantic-release-asset-pipeline` archived (or explicitly handoff-confirmed by the user) before this build starts**.
> Every task states its own verification. Defaults: fake interpreter + FakeGateway, fully offline, no SAP, no paid model. No subagents.

## 1. Versioned contracts and schemas

- [ ] 1.1 Add `schemas/semantic-goal-draft.schema.json` (strict additionalProperties; requested facts/selectors, typed constraints with provenance, analysis nodes, requested conclusions, assumptions) and verify valid fixtures pass while unknown-property/technical-key/bounds fixtures fail
- [ ] 1.2 Add `schemas/read-analysis-plan.schema.json` (server planId, dual snapshot ids, principal/scope, readPlan PlanGraph v2, separate analysisPlan DAG, limits/freshness/coverage) and verify READ_ONLY+empty action partition is enforced and client-supplied verified flags are not representable
- [ ] 1.3 Add `schemas/analysis-result.schema.json` and TypedFact schema (object keys+scope, row identity, semantic types, unit/currency, business/collection time, definitionRef, evidence refs, completeness; closed status enum) and verify each status and incomplete marker round-trips
- [ ] 1.4 Contract test: legacy goal-spec, plan-graph-v2, semantic-tool-request/response schemas validate unchanged against their existing fixtures

## 2. Legacy-safe primitive extraction

- [ ] 2.1 Extract mechanically-shared primitives (producer indexing, raw capability projection, node governance projection) from `plan_compiler.py`/`plan_compiler_v2.py` into reusable functions without changing outputs; verify the existing compiler test suites pass byte-identical
- [ ] 2.2 Wrap derivation closure and v2 graph validation for reuse from the new compiler; verify `test_planner_plan_compiler_v2.py`, `test_derived_dependencies.py`, and semantic-planning contract suites remain green
- [ ] 2.3 Verify no derivable edge is authored into catalog files (run existing derivation/relation validators)

## 3. Fake interpreter and draft validation

- [ ] 3.1 Implement the model-adapter interface plus deterministic fake GoalInterpreter driven by fixture scripts; verify a default run performs zero network calls
- [ ] 3.2 Implement deep draft validation: strict schema, technical-key scan (RFC/binding/URL/credential/SQL/code/path/import markers at any depth), finite-number/length/nesting/node bounds; verify each rejection class with negative fixtures
- [ ] 3.3 Implement the bounded repair policy (at most one structural repair turn, then structured rejection) and verify a second structural failure terminates without execution
- [ ] 3.4 Verify draft-supplied snapshotId/principal/scope/bindings are discarded and never appear in compiled plans

## 4. GoalResolver

- [ ] 4.1 Resolve requested Fact types/fields against the pinned release allowlist with object-key/scope binding; verify Q1 resolves InventoryAvailabilityFact.availableQuantity and MaterialInfoFact.baseUnitOfMeasure, and an unlisted field returns a semantic gap
- [ ] 4.2 Implement visible-READ-only producer search (active/Function/sideEffect none/approval false + visibility filter before model candidates); verify zero-producer → capability_gap and invisible producers never appear
- [ ] 4.3 Implement multi-producer ambiguity policy (published policy or clarification; never list-order/model choice); verify two-producer fixture authors no node and lists candidates
- [ ] 4.4 Close required inputs via registered derivation with object-key/scope matching; verify derived-not-asked / user-supplied-wins / upstream-empty cases on the MM capabilities and prove same-semantic-type without key match is rejected
- [ ] 4.5 Implement typed clarification for missing required values; verify missing-plant fixtures ask rather than defaulting, with no Gateway call

## 5. SemanticCompiler

- [ ] 5.1 Emit readPlan as PlanGraph v2 `READ_ONLY` with `actionPartition: []` from resolved facts; verify schema validity against `plan-graph-v2.schema.json` and v2 graph validation
- [ ] 5.2 Compile the separate AnalysisPlan DAG from registered operators only; verify unknown operator/field, arbitrary JSONPath, cycles, depth>4, >6 read or >6 analysis nodes are rejected
- [ ] 5.3 Implement plan persistence as server-owned records and verify client-uploaded verified flags/edited graphs cannot execute
- [ ] 5.4 Verify Q1 vs Q2/Q3 compile to materially different read+analysis plans (capability nodes and/or operator DAG), with no question-specific branches

## 6. Release binding and pinning

- [ ] 6.1 Load the SemanticRelease v1 package (C1 output) and verify dual-id association; mismatch fixture fails closed before any node executes
- [ ] 6.2 Pin the package per run in the durable record and verify a mid-run package change cannot affect the in-flight run
- [ ] 6.3 Verify a stale plan presented against a newer package is rejected and cache keys include (semanticSnapshotId, scope)

## 7. TypedFactNormalizer

- [ ] 7.1 Normalize FakeGateway read payloads into TypedFact rows using the release allowlist as the sole field authority (PO header/items expansion, header fallback parity with existing fixture semantics); verify per-row object key+scope, identity, unit, business/collection time, evidence refs
- [ ] 7.2 Verify opaque fields (MRP lines interior) stay opaque and non-allowlisted payload fields cannot become analysis inputs
- [ ] 7.3 Verify definitionRef is emitted only where an applicable grounded Definition exists; missing-caliber values expose none
- [ ] 7.4 Cross-parity test: shared PO fixtures produce identical material values through the new normalizer and existing TS fact-builder semantics

## 8. Deterministic Analysis Runtime (single Python authority)

- [ ] 8.1 Implement `select_fields` and `filter_eq` with registered-field/typed-literal checks; verify projection and filtering keep row lineage and illegal fields gap
- [ ] 8.2 Implement `group_sum` (Decimal, dimensions, unit groups, per-row lineage, missing/mixed-unit exclusion with reasons); verify supplier×unit totals reconcile row-by-row and mixed-unit totals are never presented as complete
- [ ] 8.3 Implement `compare` compatibility preconditions (same kind/unit/time policy) and verify side-by-side presentation needs no compare, while incompatible inputs return semantic gaps
- [ ] 8.4 Implement duplicate-row-identity conflict reporting and nested-list single-contribution reduction; verify no silent dedupe/double count and no cross multiplication
- [ ] 8.5 Implement truncation caps and verify truncated facts/aggregates are marked incomplete
- [ ] 8.6 Implement AnalysisResult statuses (complete/partial/clarification/capability_gap/semantic_gap/rejected/failed) with covered/uncovered conclusions and excluded-row reasons; verify each via fixtures

## 9. TS orchestration: adapter and DynamicReadCoordinator

- [ ] 9.1 Implement `python-analysis-adapter.ts` reusing the agent-runtime-adapter spawn pattern (arg vector, stdin JSON, timeout, redacted logs, no credentials/network in child env); verify schema-invalid child output fails closed
- [ ] 9.2 Implement `frontend/src/runtime/dynamic-analysis/coordinator.ts` orchestrating PlanExecutor → normalizer handoff → Python analysis → evidence-grounded deterministic rendering; verify against FakeGateway end to end
- [ ] 9.3 Implement pre-Gateway WRITE rejection including nested-dependency and analysis-disguised WRITE; Gateway spy asserts zero WRITE calls for the rejection fixtures, and no auto-redirect into the governed write flow
- [ ] 9.4 Implement compile-time and execution-time visibility re-checks and partial-failure isolation (independent outputs partial; dependent conclusions gapped)
- [ ] 9.5 Verify the coordinator never invokes CompositionCoordinator/projection/recommendation paths

## 10. Offline contract/CLI entry

- [ ] 10.1 Add the Python CLI entry (typed request + pinned package + fixture selection) emitting plans, dual release ids, per-node evidence, TypedFact rows, lineage-bearing results, exclusions, statuses, uncovered conclusions; verify Q1–Q7 fixture outputs end to end offline
- [ ] 10.2 Verify zero-network operation (run with networking disabled/unset gateway env) and zero credential requirements

## 11. Offline case matrix and holdout harness

- [ ] 11.1 Build the ~24 synthetic/redacted dev cases: inventory+material; inventory+orders side by side; supplier filter+group; same capability different filters/operator order; paraphrase; missing plant; unknown material; missing field; producer ambiguity; no-permission producer; arrival/demand semantic gaps; unit missing/mismatch; duplicate identity; non-finite; truncation; semantic version change; stale plan vs new package; cyclic/too-deep DAG; unknown operator; technical-key injection; direct/nested/disguised WRITE; partial fetch failure
- [ ] 11.2 Assertions judge legal dependencies, required evidence, values/units/caliber, forbidden calls, and limits — never node order or identical DAG shape; verify the full matrix passes deterministically
- [ ] 11.3 Build the sealed holdout harness accepting human-supplied combination questions after build; verify a representative placeholder holdout passes with zero business-code/branch changes and real holdouts remain sealed for C3 user validation

```

Full source: openspec/changes/ontology-goal-read-analysis/tasks.md

## openspec/changes/ontology-goal-read-analysis/specs/deterministic-read-analysis/spec.md

- Source: openspec/changes/ontology-goal-read-analysis/specs/deterministic-read-analysis/spec.md
- Lines: 1-137
- SHA256: 6a98e5172414401197f2cc492999128671bf221718e6b2510df1c123ce1263bd

[TRUNCATED]

```md
## Purpose

Compile resolved goals into a read PlanGraph v2 plus a separate registered-operator AnalysisPlan, then deterministically normalize gateway facts into TypedFacts and evaluate the four registered operators with a single Python authority, preserving row lineage, units, caliber boundaries, and completeness marks.

## ADDED Requirements

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

```

Full source: openspec/changes/ontology-goal-read-analysis/specs/deterministic-read-analysis/spec.md

## openspec/changes/ontology-goal-read-analysis/specs/dynamic-read-coordinator/spec.md

- Source: openspec/changes/ontology-goal-read-analysis/specs/dynamic-read-coordinator/spec.md
- Lines: 1-121
- SHA256: 93ae7adb6aa53a6be1d43f6c13e65cc55d935baac61d608db50fde78926c06cc

[TRUNCATED]

```md
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

```

Full source: openspec/changes/ontology-goal-read-analysis/specs/dynamic-read-coordinator/spec.md

## openspec/changes/ontology-goal-read-analysis/specs/semantic-goal-resolution/spec.md

- Source: openspec/changes/ontology-goal-read-analysis/specs/semantic-goal-resolution/spec.md
- Lines: 1-122
- SHA256: 2e56f8bc226ff54ac68c0aae393bca84f3dcb91214f03b30e02a16be35496150

[TRUNCATED]

```md
## Purpose

Accept an untrusted, LLM-produced semantic goal draft for a business question and resolve it deterministically, goal-facts-first, against the pinned visible SemanticRelease: typed facts and constraints, visible READ producer search, dependency closure, and explicit clarify/gap outcomes — without the model ever authoring an executable plan.

## ADDED Requirements

### Requirement: SemanticGoalDraft v1 strict intake contract

The system SHALL accept goal proposals only as versioned SemanticGoalDraft v1 documents validating against a strict JSON Schema (`additionalProperties: false`) with fields for requested facts (registered Fact type, output fields, object selectors), typed constraints with provenance (`explicitUser` / `confirmedContext`), analysis nodes referencing registered operators with typed inputs and controlled parameters, requested conclusions with evidence requirements, and explanation-only assumptions. Validation SHALL additionally perform deep technical-key scanning and reject RFC names, binding ids, URLs, credentials, SQL/SPARQL/code/expressions, arbitrary JSONPath, execution-authorization markers, dynamic import markers, non-finite numbers, oversized inputs, abnormal nesting, and over-limit node counts.

#### Scenario: Well-formed draft validates

- **WHEN** a draft contains registered fact requests, typed constraints, and registered operator references within limits
- **THEN** the draft passes schema and deep-scan validation and enters resolution

#### Scenario: Technical content is rejected regardless of nesting

- **WHEN** a draft contains an RFC name, binding id, URL, credential-looking value, SQL/code expression, or arbitrary path in any field including nested analysis parameters
- **THEN** validation rejects the draft with a structured error naming the offending field
- **AND** no planning or execution step runs

#### Scenario: Bounded-input rejection

- **WHEN** a draft contains a non-finite number, exceeds declared node/depth/length limits, or uses an undeclared property
- **THEN** validation rejects the draft with a structured bounds/schema error

### Requirement: Draft is untrusted and never re-serialized through text

The server SHALL treat the draft as advisory only. Any snapshot id, principal, visibility scope, technical binding, or version authority carried in the draft SHALL be ignored and replaced by server-owned values bound to the pinned release and caller scope. The entry point SHALL consume the typed request directly; typed slots SHALL NOT be rendered back into natural-language text and re-parsed.

#### Scenario: Draft-supplied authority is ignored

- **WHEN** a draft echoes a snapshot id, principal, or binding
- **THEN** the bound plan records the server-owned release id and server principal/scope
- **AND** the draft values appear nowhere in the executable plan

#### Scenario: Typed slots bypass text round-tripping

- **WHEN** the typed analysis entry receives structured slots
- **THEN** they reach the resolver as typed values without a build-query-to-text re-parse

### Requirement: Goal-first desired fact resolution

Resolution SHALL begin from the requested Fact types and fields in the draft, resolving them against the pinned SemanticRelease, and only then search for producing capabilities. Requested fields SHALL be restricted to analysis-legal fields in the release allowlist; object selectors SHALL bind registered object keys with organizational/system scope. A field or Fact type absent from the release SHALL produce a structured semantic/capability gap, never a guessed field.

#### Scenario: Requested field outside the allowlist gaps

- **WHEN** a draft requests a field not present in the release Fact-field allowlist
- **THEN** resolution returns a semantic gap naming the Fact type and requested field
- **AND** no capability call is planned for that field

#### Scenario: Object selectors bind typed keys and scope

- **WHEN** a requested fact carries material/plant selectors
- **THEN** resolution binds them as registered object keys with the caller's organizational scope
- **AND** a same-named semantic type without matching object key/scope is not treated as the same object

### Requirement: Visible READ producer search with deterministic ambiguity outcomes

The producer search SHALL consider only capabilities that are active, `kind: Function`, `sideEffect: none`, `requiresApproval: false`, and visible to the caller under the server-owned principal/scope. Visibility filtering SHALL happen before candidates are shown to the interpreter model and SHALL be re-verified at compile and execution. Zero producers SHALL yield `capability_gap`; multiple producers SHALL require a published resolution policy or explicit user clarification and MUST NOT be resolved by list order, model preference, or prompting.

#### Scenario: Zero producer yields capability gap

- **WHEN** a desired Fact type has no visible active READ producer in the release
- **THEN** resolution returns `capability_gap` naming the Fact type
- **AND** no plan node is authored

#### Scenario: Multiple producers never auto-pick

- **WHEN** exactly two visible READ capabilities produce a desired Fact type
- **THEN** resolution records an ambiguity outcome listing the candidates
- **AND** no node is authored until a published policy or user clarification resolves it

#### Scenario: Invisible producer cannot re-enter via clarification or closure

- **WHEN** a capability is invisible to the caller, including through a derived dependency path
- **THEN** it appears in no candidate set, clarification option, or auto-pulled closure

### Requirement: Required input closure and typed clarification


```

Full source: openspec/changes/ontology-goal-read-analysis/specs/semantic-goal-resolution/spec.md

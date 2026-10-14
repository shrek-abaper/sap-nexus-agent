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
- [Scope creep toward replenishment formulas] → `replenishment.py` and TS shortage rules are explicitly out of reach; only registered Definitions may justify a result, and proposed Definitions cannot.

## Migration Plan

- Additive throughout; default-off by absence of any chat/wiring registration.
- Order: C1 package first (dependency), then contract schemas + fake interpreter/resolver/compiler against C1 output, normalizer/runtime, TS coordinator/adapter, CLI + case matrix.
- Rollback: revert the new package directories, schemas, and TS directory; no database/state/schema migration exists; legacy and WRITE paths are never modified. If extraction touched shared compiler helpers, rollback restores them under the unchanged v2 suite.

## Open Questions

- Exact Python package module list vs the handoff candidate list, and the CLI command name/flags (Design Doc).
- Concrete row/byte cap defaults derived from current fixture/response sizes.
- Fixture provenance format for the 24 synthetic/redacted dev cases and the holdout sealing mechanism (human-supplied, not authored to fit) — mechanism design needed before C3, fixture layout needed in the Design Doc.

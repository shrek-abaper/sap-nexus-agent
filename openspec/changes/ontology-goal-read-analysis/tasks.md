# Tasks — ontology-goal-read-analysis (C2)

> Prerequisites: user-confirmed C0 design; **C1 `semantic-release-asset-pipeline` archived (or explicitly handoff-confirmed by the user) before this build starts**.
> Every task states its own verification. Defaults: fake interpreter + FakeGateway, fully offline, no SAP, no paid model. No subagents.

## 1. Versioned contracts and schemas

- [x] 1.1 Add `schemas/semantic-goal-draft.schema.json` (strict additionalProperties; requested facts/selectors, typed constraints with provenance, analysis nodes, requested conclusions, assumptions) and verify valid fixtures pass while unknown-property/technical-key/bounds fixtures fail
- [x] 1.2 Add `schemas/read-analysis-plan.schema.json` (server planId, dual snapshot ids, principal/scope, readPlan PlanGraph v2, separate analysisPlan DAG, limits/freshness/coverage) and verify READ_ONLY+empty action partition is enforced and client-supplied verified flags are not representable
- [x] 1.3 Add `schemas/analysis-result.schema.json` and TypedFact schema (object keys+scope, row identity, semantic types, unit/currency, business/collection time, definitionRef, evidence refs, completeness; closed status enum) and verify each status and incomplete marker round-trips
- [x] 1.4 Contract test: legacy goal-spec, plan-graph-v2, semantic-tool-request/response schemas validate unchanged against their existing fixtures

## 2. Legacy-safe primitive extraction

- [x] 2.1 Extract mechanically-shared primitives (producer indexing, raw capability projection, node governance projection) from `plan_compiler.py`/`plan_compiler_v2.py` into reusable functions without changing outputs; verify the existing compiler test suites pass byte-identical
- [x] 2.2 Wrap derivation closure and v2 graph validation for reuse from the new compiler; verify `test_planner_plan_compiler_v2.py`, `test_derived_dependencies.py`, and semantic-planning contract suites remain green
- [x] 2.3 Verify no derivable edge is authored into catalog files (run existing derivation/relation validators)

## 3. Fake interpreter and draft validation

- [x] 3.1 Implement the model-adapter interface plus deterministic fake GoalInterpreter driven by fixture scripts; verify a default run performs zero network calls
- [x] 3.2 Implement deep draft validation: strict schema, technical-key scan (RFC/binding/URL/credential/SQL/code/path/import markers at any depth), finite-number/length/nesting/node bounds; verify each rejection class with negative fixtures
- [x] 3.3 Implement the bounded repair policy (at most one structural repair turn, then structured rejection) and verify a second structural failure terminates without execution
- [x] 3.4 Verify draft-supplied snapshotId/principal/scope/bindings are discarded and never appear in compiled plans

## 4. GoalResolver

- [x] 4.1 Resolve requested Fact types/fields against the pinned release allowlist with object-key/scope binding; verify Q1 resolves InventoryAvailabilityFact.availableQuantity and MaterialInfoFact.baseUnitOfMeasure, and an unlisted field returns a semantic gap
- [x] 4.2 Implement visible-READ-only producer search (active/Function/sideEffect none/approval false + visibility filter before model candidates); verify zero-producer → capability_gap and invisible producers never appear
- [x] 4.3 Implement multi-producer ambiguity policy (published policy or clarification; never list-order/model choice); verify two-producer fixture authors no node and lists candidates
- [x] 4.4 Close required inputs via registered derivation with object-key/scope matching; verify derived-not-asked / user-supplied-wins / upstream-empty cases on the MM capabilities and prove same-semantic-type without key match is rejected
- [x] 4.5 Implement typed clarification for missing required values; verify missing-plant fixtures ask rather than defaulting, with no Gateway call

## 5. SemanticCompiler

- [x] 5.1 Emit readPlan as PlanGraph v2 `READ_ONLY` with `actionPartition: []` from resolved facts; verify schema validity against `plan-graph-v2.schema.json` and v2 graph validation
- [x] 5.2 Compile the separate AnalysisPlan DAG from registered operators only; verify unknown operator/field, arbitrary JSONPath, cycles, depth>4, >6 read or >6 analysis nodes are rejected
- [x] 5.3 Implement plan persistence as server-owned records and verify client-uploaded verified flags/edited graphs cannot execute
- [x] 5.4 Verify Q1 vs Q2/Q3 compile to materially different read+analysis plans (capability nodes and/or operator DAG), with no question-specific branches

## 6. Release binding and pinning

- [x] 6.1 Load the SemanticRelease v1 package (C1 output) and verify dual-id association; mismatch fixture fails closed before any node executes
- [x] 6.2 Pin the package per run in the durable record and verify a mid-run package change cannot affect the in-flight run
- [x] 6.3 Verify a stale plan presented against a newer package is rejected and cache keys include (semanticSnapshotId, scope)

## 7. TypedFactNormalizer

- [x] 7.1 Normalize FakeGateway read payloads into TypedFact rows using the release allowlist as the sole field authority (PO header/items expansion, header fallback parity with existing fixture semantics); verify per-row object key+scope, identity, unit, business/collection time, evidence refs
- [x] 7.2 Verify opaque fields (MRP lines interior) stay opaque and non-allowlisted payload fields cannot become analysis inputs
- [x] 7.3 Verify definitionRef is emitted only where an applicable grounded Definition exists; missing-caliber values expose none
- [x] 7.4 Cross-parity test: shared PO fixtures produce identical material values through the new normalizer and existing TS fact-builder semantics

## 8. Deterministic Analysis Runtime (single Python authority)

- [x] 8.1 Implement `select_fields` and `filter_eq` with registered-field/typed-literal checks; verify projection and filtering keep row lineage and illegal fields gap
- [x] 8.2 Implement `group_sum` (Decimal, dimensions, unit groups, per-row lineage, missing/mixed-unit exclusion with reasons); verify supplier×unit totals reconcile row-by-row and mixed-unit totals are never presented as complete
- [x] 8.3 Implement `compare` compatibility preconditions (same kind/unit/time policy) and verify side-by-side presentation needs no compare, while incompatible inputs return semantic gaps
- [x] 8.4 Implement duplicate-row-identity conflict reporting and nested-list single-contribution reduction; verify no silent dedupe/double count and no cross multiplication
- [x] 8.5 Implement truncation caps and verify truncated facts/aggregates are marked incomplete
- [x] 8.6 Implement AnalysisResult statuses (complete/partial/clarification/capability_gap/semantic_gap/rejected/failed) with covered/uncovered conclusions and excluded-row reasons; verify each via fixtures

## 9. TS orchestration: adapter and DynamicReadCoordinator

- [x] 9.1 Implement `python-analysis-adapter.ts` reusing the agent-runtime-adapter spawn pattern (arg vector, stdin JSON, timeout, redacted logs, no credentials/network in child env); verify schema-invalid child output fails closed
- [x] 9.2 Implement `frontend/src/runtime/dynamic-analysis/coordinator.ts` orchestrating PlanExecutor → normalizer handoff → Python analysis → evidence-grounded deterministic rendering; verify against FakeGateway end to end
- [x] 9.3 Implement pre-Gateway WRITE rejection including nested-dependency and analysis-disguised WRITE; Gateway spy asserts zero WRITE calls for the rejection fixtures, and no auto-redirect into the governed write flow
- [x] 9.4 Implement compile-time and execution-time visibility re-checks and partial-failure isolation (independent outputs partial; dependent conclusions gapped)
- [x] 9.5 Verify the coordinator never invokes CompositionCoordinator/projection/recommendation paths

## 10. Offline contract/CLI entry

- [x] 10.1 Add the Python CLI entry (typed request + pinned package + fixture selection) emitting plans, dual release ids, per-node evidence, TypedFact rows, lineage-bearing results, exclusions, statuses, uncovered conclusions; verify Q1–Q7 fixture outputs end to end offline
- [x] 10.2 Verify zero-network operation (run with networking disabled/unset gateway env) and zero credential requirements

## 11. Offline case matrix and holdout harness

- [x] 11.1 Build the ~24 synthetic/redacted dev cases: inventory+material; inventory+orders side by side; supplier filter+group; same capability different filters/operator order; paraphrase; missing plant; unknown material; missing field; producer ambiguity; no-permission producer; arrival/demand semantic gaps; unit missing/mismatch; duplicate identity; non-finite; truncation; semantic version change; stale plan vs new package; cyclic/too-deep DAG; unknown operator; technical-key injection; direct/nested/disguised WRITE; partial fetch failure
- [x] 11.2 Assertions judge legal dependencies, required evidence, values/units/caliber, forbidden calls, and limits — never node order or identical DAG shape; verify the full matrix passes deterministically
- [x] 11.3 Build the sealed holdout harness accepting human-supplied combination questions after build; verify a representative placeholder holdout passes with zero business-code/branch changes and real holdouts remain sealed for C3 user validation
- [x] 11.4 Verify deleting a necessary producer yields capability gap and changing an operator/Definition/asset changes semanticSnapshotId-driven behavior; remove-producer and release-mutation tests included

## 12. Regression gates and evidence record

- [x] 12.1 Run and record Python gates: new package tests plus direct compiler/derivation/snapshot regressions, ontology bundle check, evidence grounding, impact/constraint/codegen pytest targets
- [x] 12.2 Run and record `npm --prefix frontend run verify` (adapter/coordinator/parser/executor suites)
- [x] 12.3 Run and record `openspec list --json && openspec validate --all --strict` and `scripts/verify-agent-callplan-evidence.sh`
- [x] 12.4 Run legacy four-tool regression with the new code deployed-but-unused and attach actual command outputs plus explicit "not run" list (SAP live, paid model, C3 chat) as the C2 evidence record

## Verification evidence (C2)

- New ontology_planning Python tests: **100 passed** (contracts, schemas, draft validation, release pin, resolver incl. derivation closure, compiler v2+schema dual validation, fact normalizer, four operators, analysis runtime stdin/stdout, fake gateway, coordinator, CLI, 24-case contract matrix, isolation guard).
- Directly affected regression + C1: **485 passed** (semantic planning v1/v2, compiler v2, derivation, contracts, C1 release modules).
- Frontend `npm run verify`: exit 0; **601 passed | 3 skipped** (3 real-Python integration tests skip by default and pass under RUN_PYTHON_INTEGRATION=1); typecheck and Next build pass.
- `openspec validate ontology-goal-read-analysis --strict`: valid; `build-semantic-release.py --check` / `build-ontology-bundle.py --check`: in sync; evidence grounding OK.
- CLI smoke: Q1/Q2/Q3 complete, Q5 semantic_gap, Q6 capability_gap, WRITE case exit 3; every case `writeGatewayCalls=0`.
- Diff vs base be39b54: additive only; no semantic_planning/planner legacy, Java, or semantic-tools files modified.
- Not run: SAP live, paid model, chat/DSH wiring (C3 scope).

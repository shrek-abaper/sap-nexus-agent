# Subagent Progress: sap-nexus-output-projection-registry

- Plan: `docs/superpowers/plans/2026-08-04-sap-nexus-output-projection-registry.md`
- Branch: `feature/20260804/sap-nexus-output-projection-registry`
- Baseline: `efcbe617a60d395e2e62bcef75b8891aaf68e593`
- Build mode: `subagent-driven-development`
- TDD mode: `tdd`
- Review mode: `thorough`

## Current Task

- Plan task: `Task 4: 实现 FactBuilderRegistry 与 ProjectionInputAssembler`
- OpenSpec mapping:
  - `4.1 实现 ProjectionInputAssembler`
  - `4.2 仅 SUCCEEDED 贡献 facts`
  - `4.3 assembler 隔离 raw/conversation/model input`
  - `4.4 assembler 单测`
  - `Missing FactBuilder graceful degradation`
- Stage: `implementing` (user-confirmed extra fix/re-review round)
- Implementer status: `DONE` (review-fix round 1 committed by fixer)
- Base commit: `010a4500aad2ac47e01326262413f2d7d3899f43`
- Implementation commit: `40d295563e8adadb0e0de6101180a40b736ba160`
- Review-fix commit: `78b542b51a5a0d057312c0d64b2fa2e7cb1d70cc`
- Review-fix round 2 commit: `2d6027733f90aacd2fd35f3f4e2dc6ae91c5ce31`
- Changed files: initial implementation changed `frontend/src/runtime/projection/types.ts`, `frontend/src/runtime/projection/fact-builder.ts`, `frontend/src/runtime/projection/fact-builder.test.ts`, `frontend/src/runtime/projection/assembler.ts`, `frontend/src/runtime/projection/assembler.test.ts`; review-fix round 1 changed `frontend/src/runtime/plan-executor/types.ts`, `frontend/src/runtime/plan-executor/plan-executor.ts`, `frontend/src/runtime/plan-executor/plan-executor.test.ts`, `frontend/src/runtime/plan-executor/plan-executor-recovery.test.ts`, `frontend/src/runtime/projection/fact-builder.ts`, `frontend/src/runtime/projection/fact-builder.test.ts`, `frontend/src/runtime/projection/assembler.test.ts`.
- RED evidence: both focused suites failed with expected missing `./fact-builder` and `./assembler` modules.
- GREEN evidence: focused suites passed (2 files, 8 tests), typecheck and diff check passed; full frontend verify passed (26 files, 194 tests + production build).
- Review-fix RED evidence: focused executor/projection suites failed as intended (4 files, 7 tests failed, 30 passed) for missing agent trace propagation, decimal-string normalization, and permutation stability.
- Review-fix GREEN evidence: the same focused suites passed (4 files, 37 tests); full frontend verify passed (26 files, 196 tests + production build), and `git diff --check` passed.
- Review-fix round 2 RED evidence: focused executor/projection suites failed as intended (2 files failed, 4 tests failed, 37 passed) for fresh/cache missing or blank Gateway traces producing invalid records.
- Review-fix round 2 GREEN evidence: the same focused suites passed (4 files, 41 tests); full frontend verify passed (26 files, 200 tests + production build), and `git diff --check` passed.
- Task review: needs fixes (0 Critical, 3 Important, 0 Minor)
- Re-review round 1: fresh reviewer `task4_rereview1` reviewed `010a450..78b542b`; result needs fixes (0 Critical, 1 Important, 0 Minor). Report: `.superpowers/sdd/task-4-rereview-1.md`.
- Review/fix round: 3/3 (user-authorized exception after the original 2/2 budget)
- Unresolved feedback:
  - Select PO item quantity by field presence before parsing, so an invalid item value cannot fall back to a valid header value.
  - Preserve successful-node projection observability when Gateway trace is missing: either fail closed at the success contract or add explicit projection-missing metadata; silent omission is not acceptable.
  - Validate ISO-8601 freshness, fall back on malformed values, and select earliest fact time by epoch rather than lexical order.
- Review-fix round 2: fresh fixer `task4_fix2` completed and committed; final Task 4 re-review is pending.
- Final Task 4 re-review: fresh reviewer `task4_rereview2` reviewed `010a450..2d60277`; result needs fixes (0 Critical, 3 Important, 0 Minor). Report: `.superpowers/sdd/task-4-rereview-2.md`.
- Review budget: the original 2/2 budget was exhausted; the user explicitly authorized one extra fix/re-review round to implement the approved medium spec increment. Task 4 remains unchecked and Task 5 has not been dispatched.
- Extra-round design decision: retain every complete `SUCCEEDED` `NodeFactRecord` with nullable `gatewayTraceId`; assembler records `missing_gateway_trace` and emits no fact. PO item quantity uses field-presence precedence. Valid source freshness is preserved per fact; aggregate `asOf` uses earliest epoch normalized to UTC.
- Design decision: user selected and confirmed Option A; committed as `c1e302d`. `NodeFactRecord.agentTraceId` is derived from executor `runId`, never from `gatewayTraceId`.
- Written spec review: explicitly confirmed by the user after commit `6456476`; strict OpenSpec validation passed 20/20.
- Updated plan: Task 4 Steps 12-16 define the extra-round RED/GREEN cases, nullable trace and freshness implementation, full frontend/OpenSpec verification, allowed files, and exact commit.
- Risk signals: cross-module, Gateway-data security boundary, public API changes, diff >200, and process-only DONE_WITH_CONCERNS; no implementation concern.

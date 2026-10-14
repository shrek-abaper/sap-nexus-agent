---
change: ontology-goal-read-analysis
design-doc: docs/superpowers/specs/2026-10-14-ontology-goal-read-analysis-design.md
base-ref: be39b54d33e949c7057dab16b69b2969a1ec53d3
archived-with: 2026-10-14-ontology-goal-read-analysis
---

# Ontology-Goal Dynamic Read Analysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task (subagents disabled). Steps use checkbox (`- [x]`) syntax; all steps executed TDD in the main session.

**Goal:** Goal-first, ontology-constrained, deterministic offline read analysis from typed request through fake interpretation, READ_ONLY compilation, fake execution, TypedFact normalization, and four Decimal operators to an evidence response.

**Architecture:** New Python package `sap_nexus_agent.ontology_planning` owns all semantics and the only arithmetic over the archived C1 SemanticRelease; TS adds only a `dynamic-analysis/` orchestration layer executing the read half through existing PlanExecutor and invoking Python once over stdin/stdout. Single fixture authority under `evals/ontology-read-analysis/`.

**Tech Stack:** Python 3.12 (stdlib, PyYAML, jsonschema, Decimal, pytest), TypeScript/vitest, JSON Schema 2020-12.

**Spec:** `openspec/changes/ontology-goal-read-analysis/specs/`; Design Doc `docs/superpowers/specs/2026-10-14-ontology-goal-read-analysis-design.md`.

## Global Constraints

- Additive only; no edits under semantic_planning/planner legacy, Java, or semantic-tools.
- Measures cross every wire as decimal strings; default fake interpreter + FakeGateway; child env carries no SAP_NEXUS_* credentials.
- Run: `PYTHONPATH=agent .venv/bin/python -m pytest`; `npm --prefix frontend run verify`; commit per task, never push.

---

### Task 1: Package skeleton, bounds, draft contracts — `feat ... skeleton` — DONE
- [x] Failing contract/bounds test; [x] implement `__init__.py`, `bounds.py`, `contracts.py`; [x] green (4); [x] commit.

### Task 2: Four v1 JSON Schemas — DONE
- [x] Failing schema tests; [x] create semantic-goal-draft/read-analysis-plan/typed-fact/analysis-result schemas; [x] green (7); [x] commit.

### Task 3: Draft validation — DONE
- [x] Per-issue-code failing tests (schema/technical scan/bounds/DAG/refs/non-finite); [x] `draft_validation.py` + `parse_draft_bytes`; [x] green (12); [x] commit.

### Task 4: Release pinning — DONE
- [x] Failing tests (byte match, stale fail, allowlist/operators); [x] `release.py`; [x] green (3); [x] commit.

### Task 5: GoalResolver outcomes — DONE
- [x] Failing tests (Q1 resolution, field gap, no producer, ambiguity, missing selector); [x] `resolver.py`; [x] green (5); [x] commit.

### Task 6: Derivation closure — DONE
- [x] Failing tests (auto-pull, many-cardinality needsReduction, user wins); [x] worklist closure; [x] green; [x] commit.

### Task 7: SemanticCompiler — DONE
- [x] Failing tests (Q1/Q2 valid v2+schema, deterministic planId, WRITE rejection, cycles); [x] `compiler.py`; [x] green (5); [x] commit.

### Task 8: TypedFactNormalizer — DONE
- [x] Failing tests (header/items, fallback, non-finite, scalar, duplicate, allowlist); [x] contracts + `fact_normalizer.py`; [x] green (6); [x] commit.

### Task 9: Four operators — DONE
- [x] Failing tests (group reconciliation, missing unit, incompatible compare, same-unit, conflict block); [x] `operators.py` + AnalysisResult; [x] green (7); [x] commit.

### Task 10: Analysis runtime stdin/stdout — DONE
- [x] Failing tests (wire grouping, version, env sanitize, module entry, malformed JSON); [x] `analysis_runtime.py`; [x] green (5); [x] commit.

### Task 11: FakeGateway + Q1-Q3 fixtures — DONE
- [x] Failing tests (data/log, WRITE raises, missing fixture); [x] `fake_gateway.py` + gateway payloads; [x] green (3); [x] commit.

### Task 12: Coordinator end-to-end — DONE
- [x] Failing tests (Q1-Q3, totals/lineage/no-ATP, WRITE pre-gateway, arrival gap); [x] interpreter + coordinator; [x] green (6); [x] commit.

### Task 13: Offline evidence CLI — DONE
- [x] Failing subprocess tests (json/text/usage/rejected exit codes); [x] `cli.py`; [x] green (4); [x] commit.

### Task 14: 24-case matrix + sealed holdout — DONE
- [x] Failing matrix/holdout/guard tests; [x] drafts, gateway fixtures, cases.json, truncation + release-mismatch + node-failure support; [x] green (27); [x] commit.

### Task 15: Isolation guard — DONE
- [x] Failing tests (no private compiler reuse, v2 validator, no legacy/java/semantic-tools changes); [x] green (4); [x] commit.

### Task 16: TS adapter — DONE
- [x] Failing tests (env sanitize, real-child grouping, unsupported wire, abort); [x] types.ts + python-analysis-adapter.ts; [x] typecheck + green (4); [x] commit.

### Task 17: TS coordinator — DONE
- [x] Failing tests (read+analyze, non-READ_ONLY reject, fail isolation, import boundary); [x] planner_service.py `--mode plan` + coordinator.ts; [x] green (9); [x] commit.

### Task 18: Gates and evidence — DONE
- [x] Python 100 new + 485 affected regression; [x] `npm run verify` 601 passed | 3 skipped (integration pass under env flag); [x] openspec strict + both build checks + evidence grounding; [x] CLI smoke; [x] additive diff verified; [x] tasks.md checkoff with evidence.

## Self-review

- All 24 spec requirements across the three capabilities map to Tasks 1-18; Q1-Q7 scenarios covered by the 24-case matrix; single arithmetic authority (Python) and single fixture directory enforced.

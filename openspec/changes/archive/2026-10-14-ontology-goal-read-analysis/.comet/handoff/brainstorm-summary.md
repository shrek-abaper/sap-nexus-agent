# Brainstorm Summary

- Change: ontology-goal-read-analysis
- Date: 2026-10-14

## Confirmed Technical Approach

New Python package `agent/sap_nexus_agent/ontology_planning/` with focused modules: contracts (four v1 frozen dataclasses), draft_validation (strict schema + deep technical-key scan + bounds), interpreter (Protocol + fixture-driven FakeGoalInterpreter), resolver (goal-first fact/field resolution via C1 allowlist/object catalog, visible READ producer search on discover_cards, zero/multi producer outcomes, derivation closure, typed clarification), compiler (own node authorship feeding validate_plan_graph_v2; readPlan READ_ONLY actionPartition=[] + separate analysisPlan DAG), fact_normalizer (allowlist-driven, single field authority), analysis_runtime (four Decimal operators with lineage/unit rules; `python -m ...analysis_runtime` stdin/stdout entry), fake_gateway (Python offline gateway over shared fixtures, CLI path only), coordinator (release pin → resolve → compile → execute → normalize → analyze), bounds (versioned server constants; changes bump compilerVersion), and a dedicated `python -m sap_nexus_agent.ontology_planning.cli` stdin JSON entry (legacy CLI untouched).

Single offline fixture authority under `evals/ontology-read-analysis/` (cases.json with expected draft/status/capabilities/gap type, gateway raw payloads, sealed holdout placeholder); Python CLI and TS tests read the same files. TS `frontend/src/runtime/dynamic-analysis/{types,python-analysis-adapter,coordinator}.ts`: PlanExecutor runs first, then ONE Python subprocess call carries raw nodeResults; normalization+analysis happen only in Python; child env carries no SAP_NEXUS_* credentials or gateway URL; stdout schema-checked. No DSH registration. Default bounds: 5000 rows / 2 MiB.

## Key Trade-offs and Risks

- New compiler authors its own nodes instead of extracting plan_compiler_v2 private helpers — avoids regression risk to the legacy entry; cost is a small amount of node-shape code duplicated and pinned against plan-graph-v2 schema tests.
- Two orchestration hosts (Python CLI end-to-end vs TS coordinator + Python analysis) share resolver/compiler/normalizer/operators; divergence prevented by shared fixtures and one wire contract.
- Fake interpreter passing is only contract evidence, not LLM-quality evidence; holdout and real-model evaluation remain C3.
- Bounds live as code constants versioned through compilerVersion rather than a new covered YAML source (avoids modifying archived C1 manifest).

## Testing Strategy

TDD per task; Python pytest for packages/fixtures/CLI with exit-code assertions; TS vitest for adapter (spawn contract, no-credentials env, schema-invalid fail-closed) and coordinator (FakeGateway, zero WRITE calls). ~24 dev cases assert legal dependencies, evidence, values/units/caliber, forbidden calls, limits — never node order. Sealed holdout harness ships placeholder. Gates: affected pytest, npm --prefix frontend run verify, openspec strict, build-semantic-release --check.

## Spec Patches

None anticipated; if build discovers a missing acceptance scenario, a small Spec Patch adds scenarios only.

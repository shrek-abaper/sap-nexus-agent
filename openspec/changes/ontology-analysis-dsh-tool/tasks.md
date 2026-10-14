# Tasks — ontology-analysis-dsh-tool

> TDD per task; no SAP/paid-model calls; commit per task on main; never push.

## 1. Python analyze stdin mode

- [x] 1.1 Add `--mode analyze` to `ontology_planning.analysis_runtime`: stdin typed request → coordinator `run_analysis_request` (repo root resolved from SAP_NEXUS_AGENT_ROOT or module path); exit 0/3/1/2 semantics.
- [x] 1.2 Tests: q1 complete, q5 semantic_gap, write create-pr rejected exit 3, malformed JSON exit 1.

## 2. TS response type and server handler

- [x] 2.1 `OntologyAnalysisToolResponse` type (kind discriminator, 7-value status, facts, results, limitations, narrative) + questionType enum/case map.
- [x] 2.2 `frontend/src/server/dsh/ontology-analysis-handler.ts`: arg-vector spawn of `analysis_runtime --mode analyze`, sanitized env, Chinese deterministic narrative per status, timeout; unit tests with injected runner (no spawn).

## 3. Flag-gated registry integration

- [x] 3.1 `ToolHandler` union + runtime render keyed on `kind`; registry registers the tool only when flag=1; tool spec/description added.
- [x] 3.2 Tests: flag off → tool absent (default registry test stays green); flag on + scripted runtime → tool callable and narrative passed to model; render branch covered.

## 4. Chat card three-section rendering

- [x] 4.1 `ToolCallCard.tsx` ontology branch (事实/分析/限制与缺口) guarded by result.kind; DshToolCall type widened; label/arg entries.
- [x] 4.2 Component tests: ontology card sections, semantic card regression, rejected/gap statuses.

## 5. Verification gates

- [x] 5.1 Python affected pytest; `npm --prefix frontend run verify`; openspec strict; both build checks; record evidence, archive.

## Verification evidence (C3)

- Python affected suites (analyze mode, 24-case matrix, CLI, coordinator): **41 passed**.
- `npm run verify`: exit 0; **615 passed | 4 skipped** across 72 files (3 real-Python-child integration tests skip by default, pass under RUN_PYTHON_INTEGRATION=1); typecheck + Next build pass.
- Fixed pre-existing same-millisecond ordering flake in dsh conversation-store (append-index tiebreaker).
- `openspec validate ontology-analysis-dsh-tool --strict`: valid; semantic-release and ontology bundle checks in sync; evidence grounding OK.
- Flag default off: closed four-tool surface asserted; SemanticToolName union unchanged.
- Not run: SAP live, paid model (C3 future steps).

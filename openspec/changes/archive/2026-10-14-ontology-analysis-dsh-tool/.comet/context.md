# Comet Design Handoff

- Change: ontology-analysis-dsh-tool
- Phase: design
- Mode: compact
- Context hash: 33f86d87f339d76864c9d4520c8eada06e5bfeb68714939c49e6b297c10e60a5

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/ontology-analysis-dsh-tool/proposal.md

- Source: openspec/changes/ontology-analysis-dsh-tool/proposal.md
- Lines: 1-22
- SHA256: 83e06bec17c7eebed8bc40c2bcf4297856b0a75806230f9035285a6ac6b878c9

```md
## Why

C2 shipped the goal-first ontology read analysis engine (Python `ontology_planning`, TS `dynamic-analysis` coordinator) but no chat entry point exists: the four semantic tools remain the closed v2 union, and typed slots still round-trip through natural-language resolution. C3 exposes the ontology path in DSH behind a default-off flag, using only the offline fake interpreter so zero paid-model or SAP connectivity is required.

## What Changes

- Add `analyze_business_question` to the DSH server tool registry, gated by `SAP_NEXUS_ONTOLOGY_ANALYSIS_ENABLED=1`; absent the flag, the closed four-tool surface is unchanged.
- Server-only handler spawns the C2 Python runtime in a new `--mode analyze` stdin mode (offline fake interpreter + fake gateway, credential-free env), maps typed args to the checked-in offline case drafts, and returns a discriminated `OntologyAnalysisToolResponse`.
- DSH runtime renders the model-facing deterministic Chinese narrative from the structured response; the model never receives arbitrary JSON.
- `ToolCallCard` renders the ontology result with three sections (事实 / 分析 / 限制与缺口) when the response kind discriminator is present; existing cards are untouched.
- Tool parameters stay typed (`questionType`, material, plant, vendor); no text round-trip via buildToolQuery.

## Capabilities

- New Capability Spec (C3): `ontology-analysis-chat-tool`
- Modified Capabilities: none (the SemanticToolName closed union is deliberately untouched).

## Impact

- TS: `frontend/src/server/dsh/` (registry/runtime union), new server-only handler, `frontend/src/modules/dsh-chat/ToolCallCard.tsx` render branch.
- Python: one new stdin mode on `ontology_planning.analysis_runtime` (no new business logic; reuses the C2 coordinator).
- Offline by default: fake interpreter + fake gateway; no live model selection beyond the existing DSH loop (which remains unconfigured when no API key is present) and no SAP calls. Not in scope: real model interpreter selection, live gateway, holdout.

```

## openspec/changes/ontology-analysis-dsh-tool/design.md

- Source: openspec/changes/ontology-analysis-dsh-tool/design.md
- Lines: 1-48
- SHA256: 1922e3926776fad2518b2b1dfcf61dfbd3fa30bd38d377297e5b09b30ef70682

```md
## Context

C2 (`ontology-goal-read-analysis`, archived 2026-10-14) shipped the offline engine: Python `ontology_planning` coordinator with fake interpreter/gateway, TS `dynamic-analysis` adapter/coordinator, 24-case matrix. No DSH entry exists yet. C3 step 1+2 exposes it behind a default-off flag; the real model interpreter and live SAP gateway remain future work.

## Goals / Non-Goals

**Goals**:
- One new DSH tool, flag-gated, typed, fully offline.
- Deterministic Chinese narrative for the model; three-section UI.
- Zero changes to the SemanticToolName union and four existing tools.

**Non-goals**: paid-model interpreter, live Gateway calls, real holdout evaluation, role-based visibility, chat-side approval flows (ontology path is READ only).

## Decisions

### D1: New stdin mode, not a second Python entrypoint

`analysis_runtime` gains `--mode analyze`: stdin typed request → `coordinator.run_analysis_request` → EvidenceResponse. One module entry, same sanitized spawn pattern as the C2 adapter.

### D2: questionType is the model-facing selector

Offline drafts are fixture-scripted; the tool exposes a closed enum (`stock-with-unit | po-grouped-by-supplier | po-by-vendor | arrivals-next-week | stockout-certainty | create-pr`) mapped 1:1 to C2 case ids. The model supplies typed slots; no heuristics or NLP in the server handler.

### D3: Discriminated union in DSH runtime types

`ToolHandler` returns `SemanticToolResponse | OntologyAnalysisToolResponse`; runtime render keys on `kind`. ToolCallCard early-renders ontology responses before touching `capabilityChain`.

### D4: Flag semantics

Exactly `SAP_NEXUS_ONTOLOGY_ANALYSIS_ENABLED=1` enables. Flag evaluated at `getDshRuntime` singleton construction; tests inject runtimes directly and test the handler as a pure unit.

### D5: Status mapping

The ontology seven-value status is preserved verbatim; Chinese narrative wording is fixed per status. Clarification/gap/rejected are normal terminal tool outcomes (not thrown), so the DSH loop reports them to the user.

## Risks / Trade-offs

- Fixture-selected answers are demo evidence, not real answers: stated in the tool description and every narrative footer ("离线样例数据").
- Model might call the tool for WRITE intents: `create-pr` maps to the rejection path explicitly; D2 enum leaves no arbitrary draft injection.
- Flag-gated code ships in the server bundle but never executes when off (registry branch + unit test).

## Migration Plan

None — additive, default-off. Remove the flag only after the live interpreter/gateway C3 steps land separately.

## Rollback

Delete the flag/env and the additive files; the four-tool registry and existing cards are untouched.

```

## openspec/changes/ontology-analysis-dsh-tool/tasks.md

- Source: openspec/changes/ontology-analysis-dsh-tool/tasks.md
- Lines: 1-27
- SHA256: e66a6e5e5ae23bee2aa43f2db9af3d9162840f0c0f25f91cb6ed5817f1693491

```md
# Tasks — ontology-analysis-dsh-tool

> TDD per task; no SAP/paid-model calls; commit per task on main; never push.

## 1. Python analyze stdin mode

- [ ] 1.1 Add `--mode analyze` to `ontology_planning.analysis_runtime`: stdin typed request → coordinator `run_analysis_request` (repo root resolved from SAP_NEXUS_AGENT_ROOT or module path); exit 0/3/1/2 semantics.
- [ ] 1.2 Tests: q1 complete, q5 semantic_gap, write create-pr rejected exit 3, malformed JSON exit 1.

## 2. TS response type and server handler

- [ ] 2.1 `OntologyAnalysisToolResponse` type (kind discriminator, 7-value status, facts, results, limitations, narrative) + questionType enum/case map.
- [ ] 2.2 `frontend/src/server/dsh/ontology-analysis-handler.ts`: arg-vector spawn of `analysis_runtime --mode analyze`, sanitized env, Chinese deterministic narrative per status, timeout; unit tests with injected runner (no spawn).

## 3. Flag-gated registry integration

- [ ] 3.1 `ToolHandler` union + runtime render keyed on `kind`; registry registers the tool only when flag=1; tool spec/description added.
- [ ] 3.2 Tests: flag off → tool absent (default registry test stays green); flag on + scripted runtime → tool callable and narrative passed to model; render branch covered.

## 4. Chat card three-section rendering

- [ ] 4.1 `ToolCallCard.tsx` ontology branch (事实/分析/限制与缺口) guarded by result.kind; DshToolCall type widened; label/arg entries.
- [ ] 4.2 Component tests: ontology card sections, semantic card regression, rejected/gap statuses.

## 5. Verification gates

- [ ] 5.1 Python affected pytest; `npm --prefix frontend run verify`; openspec strict; both build checks; record evidence, archive.

```

## openspec/changes/ontology-analysis-dsh-tool/specs/ontology-analysis-chat-tool/spec.md

- Source: openspec/changes/ontology-analysis-dsh-tool/specs/ontology-analysis-chat-tool/spec.md
- Lines: 1-59
- SHA256: 000c6384a9f0418f17a6daf68875d8302cb656b88b74aa79b83f46f051405e50

```md
# Ontology Analysis Chat Tool

## ADDED Requirements

### Requirement: Flag-gated DSH registration

The DSH runtime SHALL register `analyze_business_question` only when the server flag `SAP_NEXUS_ONTOLOGY_ANALYSIS_ENABLED` is exactly `1`. Without the flag the registered tool set SHALL be exactly the four semantic tools, and no ontology code path SHALL execute.

#### Scenario: Flag off leaves closed tool surface

- **WHEN** the DSH runtime is built/started without `SAP_NEXUS_ONTOLOGY_ANALYSIS_ENABLED=1`
- **THEN** the tool registry contains `diagnose_material_supply`, `review_customer_exposure`, `review_vendor_exposure`, `propose_replenishment` and does not contain `analyze_business_question`

#### Scenario: Flag on registers the tool

- **WHEN** `SAP_NEXUS_ONTOLOGY_ANALYSIS_ENABLED=1`
- **THEN** `analyze_business_question` is registered with typed parameters `questionType`, `material`, `plant`, `vendor` and the model-facing description states it returns ontology-constrained read analysis only

### Requirement: Typed offline handler with credential-free subprocess

The server handler SHALL invoke the C2 analysis runtime over stdin JSON via an argument-vector subprocess whose environment contains no `SAP_NEXUS_APPROVAL_TOKEN`, `SAP_NEXUS_GATEWAY_URL`, or `SAP_NEXUS_PRINCIPAL`. Inputs SHALL be typed slots; no buildToolQuery/natural-language round-trip SHALL occur.

#### Scenario: Stock question completes offline

- **WHEN** the handler runs with `questionType: "stock-with-unit"`, material DEMOA2, plant 1000
- **THEN** it returns status `complete`, the MD04 stock fact and base unit appear in `facts`, and zero WRITE calls are recorded

#### Scenario: Arrival question reports semantic gap

- **WHEN** the handler runs with `questionType: "arrivals-next-week"`
- **THEN** the response status is `semantic_gap` and the narrative explains no due/receipt fact exists, without claiming arrival quantities

#### Scenario: WRITE question rejected

- **WHEN** the handler runs with `questionType: "create-pr"`
- **THEN** the response status is `rejected` and the narrative states ontology analysis performs no writes

### Requirement: Discriminated response contract

The tool response SHALL carry `kind: "ontology-analysis"` with structured `facts`, analysis `results`, `limitations`, terminal `status` (the C2 seven-value set), and a deterministic Chinese `narrative.summary`. The DSH runtime SHALL use this narrative as the model-facing tool text.

#### Scenario: Runtime renders ontology narrative

- **WHEN** an ontology tool call completes
- **THEN** the model-facing text is exactly `narrative.summary` and no raw structured envelope is passed as the tool text

### Requirement: Three-section chat rendering

`ToolCallCard` SHALL render ontology responses with 事实, 分析, and 限制与缺口 sections and SHALL NOT access semantic-tool-only fields (`capabilityChain`) for them. Existing semantic-tool rendering SHALL remain unchanged.

#### Scenario: Ontology card does not crash and shows sections

- **WHEN** a tool call result has `kind: "ontology-analysis"` with one fact, one grouped result, and one limitation
- **THEN** the card shows the three sections, the grouped measure with unit, and the limitation text

#### Scenario: Semantic tool card unchanged

- **WHEN** a `diagnose_material_supply` result renders
- **THEN** the existing capability chain, facts, and approval UI behave exactly as before

```

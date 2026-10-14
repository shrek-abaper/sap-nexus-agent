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

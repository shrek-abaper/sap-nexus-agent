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

---
change: ontology-analysis-dsh-tool
design-doc: docs/superpowers/specs/2026-10-14-ontology-analysis-dsh-tool-design.md
base-ref: fcf45204c7b7a4e40487084e56319abfb881cf95
archived-with: 2026-10-14-ontology-analysis-dsh-tool
---

# Ontology Analysis DSH Tool Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans (subagents disabled). Checkbox steps; TDD.

**Goal:** Expose the C2 ontology read analysis behind a default-off DSH chat tool using offline fake execution, with three-section chat rendering.

**Architecture:** One new Python stdin mode; one server-only TS handler with credential-free spawn; DSH runtime response union discriminated by `kind`; ToolCallCard early branch. Additive and flag-gated.

## Global Constraints

- Flag exact value `SAP_NEXUS_ONTOLOGY_ANALYSIS_ENABLED=1`; default closed four-tool surface.
- No SAP/paid-model calls; child env has no SAP_NEXUS_* credentials.
- SemanticToolName union unchanged.

---

### Task 1: Python analyze stdin mode — DONE
- [x] `--mode analyze` on analysis_runtime (coordinator reuse)
- [x] 4 subprocess tests (q1 complete, q5 gap, write exit 3, malformed exit 1)
- [x] commit

### Task 2: TS handler + types — DONE
- [x] `ontology-analysis-handler.ts`: questionType enum/case map, spawn runner, injected-runner seam, Chinese narrative, discriminated response
- [x] 6 unit tests + 1 real-child integration (env-gated)
- [x] commit

### Task 3: Flag-gated registry + runtime union — DONE
- [x] `ontologyAnalysisEnabled`, `buildDshHandlers(options)`, tool spec/description
- [x] ToolHandler/ToolCallRecord union; `toolResultToModelText` kind dispatch; decision-trace narrowing
- [x] 4 registry tests; full src/server/dsh green
- [x] commit

### Task 4: Chat card — DONE
- [x] Pure `ontology-card.ts` sections model + discriminators; DshToolCall result union
- [x] ToolCallCard ontology branch (事实/分析/限制与缺口), semantic path unchanged
- [x] 4 model tests; boundary intact
- [x] commit

### Task 5: Verification + archive — IN PROGRESS
- [x] Python affected suites, npm verify, openspec strict, build checks; checkoff; verify; archive (local, no push).

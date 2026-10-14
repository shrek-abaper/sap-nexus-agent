# Brainstorm Summary

- Change: ontology-analysis-dsh-tool
- Date: 2026-10-14
- Path: architectural-lite (small additive surface; ADR-style decisions already in design.md)
- User directive: proceed autonomously, complete C3 items 1+2 (DSH registration + chat wiring), fake interpreter, flag default off.

## Confirmed approach

- Python: add `--mode analyze` stdin to existing analysis_runtime (reuses coordinator, no new business logic).
- TS server: new `ontology-analysis-handler.ts` spawns the mode with sanitized env; `questionType` closed enum maps 1:1 to C2 offline case ids; Chinese deterministic narrative keyed by terminal status.
- Runtime/type union: discriminated `kind: "ontology-analysis"`; render uses narrative.summary; ToolHandler/ToolCallRecord result types widened.
- Registry includes the tool iff `SAP_NEXUS_ONTOLOGY_ANALYSIS_ENABLED === "1"`.
- UI: ToolCallCard early branch for ontology kind with 事实/分析/限制与缺口 sections; semantic-tool branch unchanged.

## Risks

- Fixture answers are demo data — narrative always carries an offline-sample footer.
- Server bundle ships gated code — registration branch + flag-off test prove no execution.

## Spec patches: none.

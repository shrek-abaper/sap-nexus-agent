---
comet_change: ontology-analysis-dsh-tool
role: technical-design
canonical_spec: openspec
archived-with: 2026-10-14-ontology-analysis-dsh-tool
status: final
---

# Design Doc — Ontology Analysis DSH Tool (C3 step 1+2)

## 1. Flow

```text
DSH chat turn
  └─ model calls analyze_business_question(questionType, material?, plant?, vendor?)   [flag=1 only]
       └─ ontology-analysis-handler (server-only)
            └─ spawn python -m ...analysis_runtime --mode analyze   (stdin JSON, no credentials)
                 └─ coordinator.run_analysis_request (fake interpreter → fake gateway; C2 path)
            └─ OntologyAnalysisToolResponse {kind, status, facts, results, limitations, narrative.zh}
       └─ DSH runtime renders narrative.summary as model-facing text
       └─ ToolCallCard renders 事实 / 分析 / 限制与缺口 from structured fields
```

## 2. questionType → offline case map

| questionType | caseId |
|---|---|
| stock-with-unit | q1-stock-and-unit |
| po-grouped-by-supplier | q2-po-group-by-supplier |
| po-by-vendor | q3-supplier-filter |
| arrivals-next-week | q5-arrivals-next-week |
| stockout-certainty | q6-stockout-certainty |
| create-pr | write-create-pr |

Unknown value → `rejected` (INVALID_QUESTION_TYPE) without spawning.

## 3. Response contract (TS)

```ts
type OntologyAnalysisStatus = "complete"|"partial"|"clarification"|"capability_gap"|"semantic_gap"|"rejected"|"failed";
interface OntologyAnalysisToolResponse {
  kind: "ontology-analysis";
  contractVersion: 1;
  tool: "analyze_business_question";
  status: OntologyAnalysisStatus;
  runId: string;
  facts: { factTypeRef: string; fields: Record<string, {value:string;semanticType:string}>; unit: {field:string;value:string}|null }[];
  results: { nodeId: string; operatorId: string; status: string; rows: unknown[] }[];
  gaps: string[];
  limitations: string[];
  narrative: { summary: string; limitations: string[] };
  error?: { errorType: string; message: string };
}
```

Chinese narrative is built from structured sections only (no model generation): status line, fact lines (`字段=值 单位`), grouped totals with lineage count, gap/reject reasons, and a fixed footer "（离线样例数据，未连接 SAP）".

## 4. Files

- Python: `analysis_runtime.py` (+`--mode analyze`, ~20 lines); tests appended to CLI/runtime test modules.
- TS new: `frontend/src/server/dsh/ontology-analysis-handler.ts` (+test), `frontend/src/server/dsh/ontology-analysis-types.ts`.
- TS edit: `registry.ts` (flag + handler wiring + TOOL_SPECS/description), `runtime.ts` (handler union, kind-keyed render, result record type), `modules/dsh-chat/types.ts` + `ToolCallCard.tsx` (branch + labels).

## 5. Bounds

Subprocess timeout 90s (C2 BOUNDS); env sanitization identical to python-analysis-adapter; input size 2 MiB cap; spawn uses repoRoot/PYTHONPATH conventions from agent-runtime-adapter.

## 6. Rollback

Additive; unset flag → zero execution; delete new files to remove fully.

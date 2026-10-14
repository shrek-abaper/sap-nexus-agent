# Model interpreter live evaluation — 2026-10-14

- Model: DeepSeek-V4-Flash via `LLM_BASE_URL` (OpenAI-compatible), temperature 0, max_tokens 1200
- Gate: `SAP_NEXUS_LLM_LIVE=1`; runner `evals/ontology-read-analysis/model-eval.py` (manual, not in CI)
- Execution: offline FakeGateway fixtures; model produces only the untrusted SemanticGoalDraft; downstream = unchanged C2 pipeline.
- Result: **8/8 expected terminals, 8 paid calls total** (≤1 per question; bounded repair = 2 max).

| Case | Utterance | Terminal | Calls |
|---|---|---|---|
| q1-stock-unit | 库存 + 基本计量单位 | complete | 1 |
| q2-po-grouped | 订单量按供应商/单位汇总，与库存并排 | complete | 1 |
| q3-vendor-filter | 只看 V72719 的订单量（先过滤再汇总） | complete | 2 |
| q4-side-by-side | 库存与订单明细并排，不比较 | complete | 1 |
| q5-arrivals | 下周到货/收货量 | semantic_gap (`FIELD_NOT_ALLOWLISTED … deliveryDate/dueQuantity`) | 1 |
| q6-stockout | 下周会不会断供、能否确定 | capability_gap (DemandForecastFact 无生产者) | 1 |
| q7-write | 创建采购申请 | rejected (`WRITE_REJECTED`) | 1 |
| ambiguous-material | "查库存"（无物料/工厂） | clarification | 1 |

Isolated Q5 reruns: 3/3 semantic_gap.

## Hardening applied after observing model behavior

- Server slots (material/plant/vendor) are injected as per-fact object selectors when the model omits them.
- Model-produced `constraints` are normalized server-side (source defaults, semanticType corrected from known slot names; malformed entries dropped).
- Illegal fields terminate as semantic_gap on the FIRST draft (no repair that would silently change the question); structural/schema errors still get one repair round.
- Prompt explicitly instructs: keep unavailable field names to surface gaps; demand questions use the producer-less demand fact; WRITE intents use the PR fact so the read-only precheck rejects; chained analysis uses nodeRef; no source/parameterBindings/governance fields.

## Boundary evidence

- WRITE attempts: `writeGatewayCalls=0` in all cases; Q7 rejected before any execution.
- No BAPI/URL/credential content in system prompt (unit test enforces).
- Caliber: Q5 never substitutes orderQuantity as arrivals; Q6 never derives certainty from order quantity.

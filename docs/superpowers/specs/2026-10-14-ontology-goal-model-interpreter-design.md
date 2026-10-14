---
comet_change: ontology-goal-model-interpreter
role: technical-design
canonical_spec: openspec
---

# Design Doc — Model Goal Interpreter

## 1. Position

```text
question (free text) ──SAP_NEXUS_LLM_LIVE=1──▶ ModelGoalInterpreter
                                                 │ system: release allowlist +
                                                 │ four operators + READ/caliber rules
                                                 ▼
                                    SemanticGoalDraft v1 (untrusted JSON)
                                                 ▼
              draft_pipeline: write-precheck → validate_draft → (1 repair) → terminal
```

Everything downstream is unchanged from C2/C3: the model chooses facts/fields/operators/values only; it never names capabilities, RFCs, or executes.

## 2. Modules

- `ontology_planning/draft_pipeline.py` (new): `prepare_draft(request, sources, pinned) -> DraftOutcome`
  - selects draftOverride / interpreter (fake|model; model requires env flag)
  - WRITE precheck, validate_draft, one repair round (calls interpreter with feedback)
  - returns either `(draft_document, None)` or `(None, terminal_response_dict)`; shared by coordinator.py and planner_service.py.
- `ontology_planning/model_interpreter.py` (new): `ModelGoalInterpreter(client=None, pinned=None)`
  - `interpret(request, vocabulary, feedback=None) -> dict`; increments `call_count`.
  - user message: question/utterance + (repair) JSON-encoded issues; output parsed via json; SemanticGoalDraft.from_dict round-trip sanity.
- `interpreter.py`: Protocol gains optional `feedback`; FakeGoalInterpreter ignores it.
- Coordinator/planner_service delegate to the pipeline (behavior-preserving refactor).

## 3. Prompt contract

System prompt sections:
1. Role: produce ONLY a SemanticGoalDraft v1 JSON object, nothing else.
2. Allowed facts table from pinned allowlist (fact id → fields); object selectors Material.material / Plant.plant.
3. Operators: exactly the four ids with parameter shapes; analysis nodes reference allowlisted fields or upstream nodes.
4. Constraints: explicitUser values only; no RFC/binding/URL/path/credential keys (would be rejected).
5. Caliber: orderQuantity is ordered quantity, never arrival/ATP; no deliveryDate/dueQuantity fields exist; such questions must still use closest allowlisted fields only (downstream gap classification handles the rest).
6. Example: the Q2 draft.

No BAPI_ tokens, no URLs, no credentials anywhere in the prompt (asserted by test).

## 4. Repair and terminals

| Final validation codes | Terminal |
|---|---|
| DRAFT_UNKNOWN_FIELD / DRAFT_UNKNOWN_FACT_TYPE | semantic_gap |
| DRAFT_SCHEMA_INVALID / TECHNICAL_KEY / BOUNDS / DAG_CYCLE / UNKNOWN_OPERATOR / UNRESOLVED_INPUT | rejected |
| LLM unavailable/non-JSON after call | failed (MODEL_UNAVAILABLE) |

Two chat_json calls maximum (initial + one feedback round); fake client in tests.

## 5. TS side

- ontology-analysis-handler: live check `process.env.SAP_NEXUS_LLM_LIVE === "1"`; when live and `args.question` present → Python request `{interpreter:"model", utterance: question, slots, scope}`; when offline → caseId fake path.
- runtime TOOL_SPECS: add optional `question: string`; description notes live behavior.
- Python subprocess stays credential-free for gateway/principal but keeps LLM_* env (the LLM key is read from .env by load_llm_settings; the sanitize function must strip only SAP_NEXUS_APPROVAL_TOKEN/GATEWAY_URL/PRINCIPAL — it already does; LLM_* pass through).

## 6. Evaluation

`evals/ontology-read-analysis/model-eval.py` runs ~8 utterances (Q1/Q2/Q3/Q4 paraphrase/Q5/Q6/Q7/ambiguous), prints status, draft acceptance, call count; one authorized live run; report committed. Not wired into pytest.

## 7. Rollback

Flag off = zero behavior change; additive otherwise.

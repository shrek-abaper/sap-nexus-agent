## Why

The ontology read-analysis path ships with a fixture-driven `FakeGoalInterpreter`: the new DSH tool only answers the six closed `questionType` cases. The environment already configures a paid OpenAI-compatible model (DeepSeek-V4-Flash via LLM_*). C3 step 3 lets the model act as goal interpreter — producing only an untrusted SemanticGoalDraft — behind an explicit live flag, with one bounded repair turn, while every existing downstream guard (schema, technical scan, allowlist, visible READ producers, WRITE rejection) remains the sole authority.

## What Changes

- New `ModelGoalInterpreter` in `ontology_planning` reusing `OpenAiCompatibleLlmClient.chat_json`: system prompt describes only the release allowlist (fact types, fields, object selectors, four operators, READ-only/caliber rules) and demands the SemanticGoalDraft v1 JSON shape.
- Two-turn bounded draft loop in the Python coordinator/planner service: draft → validate; on failure feed structured issues back once; terminal classification unchanged (unknown field after repair → semantic_gap; technical/bounds → rejected).
- Live gate on both sides: the DSH handler selects the model only when `SAP_NEXUS_LLM_LIVE=1`; the Python side independently rejects `interpreter:"model"` unless the same flag is set. Free-form `question` utterance becomes the model input; `questionType` remains the fake/offline path.
- DSH tool spec gains optional `question` parameter; description states model is draft-only and offline default.
- Live evaluation harness `evals/ontology-read-analysis/model-eval.py` (manual, never in default test runs) for Q1-Q7-style utterances; recorded evidence report.

## Capabilities

- Modified: `ontology-analysis-chat-tool` — model-interpreter selection and live flag.

## Impact

- Python: new `model_interpreter.py`, shared draft pipeline helper; coordinator/planner_service changes; tests with scripted fake clients (no paid calls in CI).
- TS: handler/registry live routing and optional `question` param; unit tests with injected runners.
- Costs only when the flag is on; default behavior stays fully offline.

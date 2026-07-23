## 1. LLM Configuration And Client

- [x] 1.1 Add `openai` and `python-dotenv` dependencies to `agent/pyproject.toml`.
- [x] 1.2 Add safe `.env.example` placeholders for `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL_NAME`, `LLM_MAX_RETRIES`, and `LLM_TIMEOUT_INTENT` without real secrets.
- [x] 1.3 Implement `agent/sap_nexus_agent/llm_client.py` with OpenAI-compatible JSON chat support, config loading, timeout handling, and secret-safe errors.

## 2. LLM Intent Adapter

- [x] 2.1 Implement `agent/sap_nexus_agent/llm_intent.py` that prompts for strict inventory intent JSON and converts trusted output into `IntentParseResult`.
- [x] 2.2 Enforce model-output guardrails for unknown capability, `rfcName`, malformed JSON, non-object parameters, and unsupported intent.
- [x] 2.3 Add `hybrid`, `llm`, and `rule` intent modes while keeping `hybrid` as the CLI default.

## 3. Orchestration And CLI Integration

- [x] 3.1 Update `run_inventory_query` to accept an injectable intent adapter and preserve existing rule-parser behavior in tests.
- [x] 3.2 Update `agent/sap_nexus_agent/cli.py` to construct the selected intent adapter and avoid printing LLM secrets or raw config.
- [x] 3.3 Ensure CallPlan, Gateway validate / execute, ExecutionResult, ReasoningFact, and narrator behavior remain unchanged after intent parsing.

## 4. Tests, Eval, And Verification

- [x] 4.1 Add fake LLM tests for happy path, missing plant clarification, hybrid fallback, malformed JSON, unknown capability, and `rfcName` guard.
- [x] 4.2 Add optional live LLM smoke test gated by `SAP_NEXUS_LLM_LIVE=1` and local `LLM_*` environment variables.
- [x] 4.3 Update eval or test documentation to state normal verification does not require live LLM credentials.
- [x] 4.4 Run `python -m pytest agent/tests`, `python -m sap_nexus_agent.eval evals/inventory_availability_cases.yaml`, and `openspec validate --all --strict`.

<!-- build note: user confirmed hybrid mode and dependency additions. TDD evidence includes RED failures for missing llm_client, missing intent_adapter injection, and real-model semantic aliases (`materialNumber` / `plantCode`) before GREEN. Live smoke passed only with explicit `SAP_NEXUS_LLM_LIVE=1` and local external `.env`; no secrets were printed or committed. -->

## Context

The archived `agent-callplan-evidence` slice currently implements a safe deterministic path:

```text
Chinese text -> rule parser -> closed-set selector -> CallPlan -> Gateway -> ExecutionResult -> ReasoningFact -> deterministic narrator
```

This is safe but too brittle for varied Chinese business language. The project architecture allows LLMs for intent understanding, closed-set capability selection, parameter extraction, clarification, and narration, but forbids LLM-generated RFC names, SAP execution, business calculations, or write actions.

The local reference project `cbu-brain-agent` uses an OpenAI-compatible DeepSeek model gateway with these environment variable names: `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL_NAME`, `LLM_MAX_RETRIES`, and timeout variables such as `LLM_TIMEOUT_INTENT`. This change reuses that configuration shape without copying secrets.

## Goals / Non-Goals

Goals:

- Add a real LLM intent adapter for inventory availability queries.
- Default to `hybrid`: try LLM first, then rule fallback when LLM cannot produce trusted output.
- Keep deterministic validation as the enforcement layer after LLM output.
- Keep existing read-only behavior, CallPlan, Gateway orchestration, ReasoningFact, narrator, and eval guarantees.
- Provide optional live LLM smoke verification gated by an explicit environment flag.

Non-goals:

- No SAP write action.
- No RecommendationPlan.
- No arbitrary RFC or raw tool-calling endpoint.
- No LLM-generated inventory quantity, SAP result, or business conclusion.
- No commit of real `.env`, API key, model gateway token, runtime trace, or live response body.

## Architecture

### Components

- `llm_client.py`
  - Loads `.env` locally using `python-dotenv` if available.
  - Reads `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL_NAME`, `LLM_MAX_RETRIES`, and `LLM_TIMEOUT_INTENT`.
  - Uses the OpenAI SDK with `base_url` to call the configured model gateway.
  - Exposes a small protocol returning parsed JSON or a structured unavailable result.
  - Never logs API key or full request/response payloads.

- `llm_intent.py`
  - Builds a strict system/user prompt for inventory intent extraction.
  - Requests JSON output with `response_format={"type": "json_object"}` when the concrete client supports it.
  - Converts the model JSON into the existing `IntentParseResult` shape.
  - Rejects or downgrades untrusted model output before capability selection.

- `orchestrator.py`
  - Accepts an injected intent adapter function, defaulting to the current rule parser for tests.
  - CLI chooses the adapter based on `--intent-mode rule|llm|hybrid`.
  - `hybrid` calls LLM first; if the LLM is unavailable, malformed, or untrusted, it falls back to the rule parser.

- `cli.py`
  - Adds `--intent-mode`, default `hybrid`.
  - Does not print LLM config or secrets.

### LLM Output Contract

The model may output only this candidate JSON shape:

```json
{
  "intent": "inventory_availability",
  "capabilityId": "MM.Inventory.GetAvailability",
  "parameters": {
    "material": "DEMOA1",
    "plant": "1000",
    "unit": "EA"
  },
  "missingParameters": [],
  "clarification": null
}
```

Allowed intent values:

- `inventory_availability`
- `unsupported`

Allowed capability values:

- `MM.Inventory.GetAvailability`
- `null` for unsupported or missing-parameter cases

Any `rfcName`, unknown `capabilityId`, unexpected intent, non-object `parameters`, or malformed JSON is not trusted. `hybrid` falls back to rules; `llm` mode returns a structured failure or clarification without Gateway calls.

### Safety Boundary

The LLM is advisory. Enforcement remains deterministic:

1. Normalize model output into `IntentParseResult`.
2. Run the existing `select_capability` closed-set selector.
3. Create CallPlan only after required parameters are present.
4. Gateway still receives only `capabilityId` and `parameters`.
5. Narrator still consumes only `ReasoningFact`.

## Error Handling

- Missing `LLM_API_KEY` or `LLM_BASE_URL`: `hybrid` falls back to rule parser; `llm` mode returns `LLM_UNAVAILABLE` without Gateway calls.
- Timeout or connection error: same handling as unavailable.
- API status error or malformed JSON: same handling as unavailable/untrusted.
- Unknown capability or `rfcName` from LLM: reject as untrusted and do not execute from that output.
- Missing `material` or `plant` from trusted LLM JSON: return Chinese clarification before Gateway calls.

## Testing

Normal verification must not require a real model key or network. Tests use fake LLM clients and cover:

- LLM happy path creates the same CallPlan/Gateway behavior as the rule parser.
- LLM missing plant clarifies and does not call Gateway.
- LLM unavailable in `hybrid` falls back to rule parser.
- LLM malformed JSON in `hybrid` falls back to rule parser.
- LLM unknown capability is rejected or falls back without Gateway execution from unknown output.
- LLM `rfcName` output is rejected and does not call Gateway.
- Existing rule parser, eval runner, narrator, and safety tests still pass.

Optional live smoke:

```bash
SAP_NEXUS_LLM_LIVE=1 python -m pytest agent/tests/test_llm_live.py
```

The live test may use local environment variables copied manually from the reference project by the operator. It must skip unless explicitly enabled and must not print secrets or full model responses.

---
comet_change: sap-nexus-agent-llm-intent-adapter
role: technical-design
canonical_spec: openspec
archived-with: 2026-06-20-sap-nexus-agent-llm-intent-adapter
status: final
---

# SAP Nexus Agent LLM Intent Adapter Design

## Context

The current Agent MVP safely handles Chinese inventory availability questions with deterministic keyword and regex parsing. That safety baseline must remain intact, but the user now requires real LLM capability for natural-language intent handling. The implementation must therefore add LLM understanding without turning the product into generic LLM tool calling.

The reference configuration comes from the local CBU Brain Agent `.env` shape, not from committed secrets. The only reusable configuration names are `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL_NAME`, `LLM_MAX_RETRIES`, and `LLM_TIMEOUT_INTENT`. Real values remain local-only.

## Confirmed Approach

Use a hybrid intent adapter:

```text
Chinese user text
-> LLM intent adapter candidate
-> deterministic output guard
-> fallback rule parser when LLM is unavailable or untrusted
-> closed-set capability selection
-> CallPlan
-> Gateway validate / execute
-> ExecutionResult
-> ReasoningFact
-> deterministic Chinese narrator
```

The LLM is advisory. It may propose an intent, capability ID, parameters, missing parameters, and clarification text. It may not generate or override `rfcName`, call Gateway, calculate inventory, write SAP, or narrate facts not present in `ReasoningFact`.

## Components

### `agent/sap_nexus_agent/llm_client.py`

Responsibilities:

- Load local `.env` using `python-dotenv` when available.
- Read `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL_NAME`, `LLM_MAX_RETRIES`, and `LLM_TIMEOUT_INTENT`.
- Use the OpenAI SDK with configurable `base_url`.
- Call `chat.completions.create` with JSON response format for intent parsing.
- Return either parsed JSON or a structured unavailable/untrusted status.
- Never log secrets or full model gateway configuration.

### `agent/sap_nexus_agent/llm_intent.py`

Responsibilities:

- Build a minimal prompt that asks for strict JSON only.
- Convert trusted model JSON into the existing `IntentParseResult` contract.
- Treat missing required fields as clarification cases.
- Treat malformed JSON, unknown capability, unsupported intent, non-object parameters, or `rfcName` as untrusted.
- Implement `hybrid`, `llm`, and `rule` adapter selection helpers.

### `agent/sap_nexus_agent/orchestrator.py`

Responsibilities:

- Accept an injectable `intent_adapter` callable.
- Default to the existing rule parser so existing tests stay stable.
- Preserve all existing downstream behavior after parsing.

### `agent/sap_nexus_agent/cli.py`

Responsibilities:

- Add `--intent-mode rule|llm|hybrid`, defaulting to `hybrid`.
- Construct the selected adapter.
- Print only Agent response text, never model config or raw model response.

## LLM Output Contract

Trusted model output is limited to this shape:

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

Allowed intent values are `inventory_availability` and `unsupported`. The only executable capability ID is `MM.Inventory.GetAvailability`. Any `rfcName` key or raw SAP BAPI/RFC token makes the LLM output untrusted.

## Error Handling

- `hybrid`: LLM unavailable, malformed, timeout, status error, or untrusted output falls back to the rule parser.
- `llm`: LLM unavailable or untrusted output returns a structured Agent failure or clarification without Gateway calls.
- `rule`: skips all LLM code and uses existing behavior.
- Missing `material` or `plant` always clarifies before Gateway validation.

## Testing Strategy

Normal verification must not require network access or real credentials.

Tests:

- Fake LLM happy path produces the same executable outcome as rules.
- Fake LLM missing plant clarifies and does not call Gateway.
- Hybrid fallback handles unavailable LLM and malformed JSON.
- Unknown capability and `rfcName` output do not drive Gateway execution.
- CLI exposes the intent mode option without printing config.
- Optional live LLM smoke skips unless `SAP_NEXUS_LLM_LIVE=1` is set.

Verification commands:

```bash
python -m pytest agent/tests
python -m sap_nexus_agent.eval evals/inventory_availability_cases.yaml
openspec validate --all --strict
```

## Security Notes

`.env.example` may contain placeholders only. Real model API keys, base URLs with sensitive tokens, SAP credentials, destination config, and runtime traces must not be committed. Test output and error messages must not include `LLM_API_KEY` values or raw `.env` contents.

## Why

The current read-only Agent MVP accepts Chinese inventory queries but parses them only with deterministic keyword and regex rules. The next product step needs a real LLM intent adapter so natural-language understanding can handle more varied Chinese phrasing while preserving SAP governance boundaries.

This change adds an OpenAI-compatible LLM adapter using the existing `LLM_*` configuration convention from the local CBU Brain Agent reference, without committing API keys or allowing the model to generate SAP RFC execution details.

## What Changes

- Add a real LLM intent adapter for inventory availability intent extraction.
- Use `hybrid` intent mode by default: call the LLM first, then fall back to the existing rule parser when LLM config, network, timeout, malformed JSON, or unsupported output prevents trusted use.
- Add explicit LLM configuration placeholders to `.env.example` only; do not commit real keys.
- Add OpenAI-compatible client support with `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL_NAME`, `LLM_MAX_RETRIES`, and `LLM_TIMEOUT_INTENT`.
- Keep deterministic validation after LLM output: only `MM.Inventory.GetAvailability` is executable, missing `material` or `plant` still clarifies before Gateway calls, and any `rfcName` output is rejected.
- Add fake-client tests for LLM success, fallback, malformed JSON, unknown capability, missing parameters, and `rfcName` guard.
- Add an optional live LLM smoke path that is explicitly gated by an environment flag and never runs in normal verification.

## Capabilities

### New Capabilities

None. This change does not introduce a new SAP business capability.

### Modified Capabilities

- `agent-callplan-evidence`: Add optional real LLM-assisted intent extraction before deterministic closed-set validation while preserving all existing CallPlan, Gateway, ReasoningFact, narrative, eval, and safety guarantees.

## Impact

- Affected Python package: `agent/sap_nexus_agent/`.
- Affected CLI: default intent mode becomes `hybrid`, with explicit `rule`, `llm`, and `hybrid` options.
- New dependencies: `openai` and `python-dotenv` in `agent/pyproject.toml`.
- Affected tests and evals: add LLM adapter tests; existing rule-parser and Agent evals must continue to pass.
- Security impact: `.env.example` gains placeholder `LLM_*` keys only; real model API keys remain local-only and must not be printed, committed, traced, or returned.

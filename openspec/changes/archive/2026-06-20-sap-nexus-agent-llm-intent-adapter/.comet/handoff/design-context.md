# Comet Design Handoff

- Change: sap-nexus-agent-llm-intent-adapter
- Phase: design
- Mode: compact
- Context hash: fd7d70ecf521a8f6f199d63878a92073008134672270726784573b12beefbe94

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/sap-nexus-agent-llm-intent-adapter/proposal.md

- Source: openspec/changes/sap-nexus-agent-llm-intent-adapter/proposal.md
- Lines: 1-33
- SHA256: 74b8264959b6d608f50d134732c7b81b1eeecee8da811ad23b37a649e23f40a3

```md
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
```

## openspec/changes/sap-nexus-agent-llm-intent-adapter/design.md

- Source: openspec/changes/sap-nexus-agent-llm-intent-adapter/design.md
- Lines: 1-123
- SHA256: cd9a9d2ce998036055fe64f07ac79feb559a91b3eafea67fdff37797b9a2984e

[TRUNCATED]

```md
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
```

Full source: openspec/changes/sap-nexus-agent-llm-intent-adapter/design.md

## openspec/changes/sap-nexus-agent-llm-intent-adapter/tasks.md

- Source: openspec/changes/sap-nexus-agent-llm-intent-adapter/tasks.md
- Lines: 1-24
- SHA256: ab41eba95c349900261d675bd8515d742a1d3bdd087c55052eba7b48e4802373

```md
## 1. LLM Configuration And Client

- [ ] 1.1 Add `openai` and `python-dotenv` dependencies to `agent/pyproject.toml`.
- [ ] 1.2 Add safe `.env.example` placeholders for `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL_NAME`, `LLM_MAX_RETRIES`, and `LLM_TIMEOUT_INTENT` without real secrets.
- [ ] 1.3 Implement `agent/sap_nexus_agent/llm_client.py` with OpenAI-compatible JSON chat support, config loading, timeout handling, and secret-safe errors.

## 2. LLM Intent Adapter

- [ ] 2.1 Implement `agent/sap_nexus_agent/llm_intent.py` that prompts for strict inventory intent JSON and converts trusted output into `IntentParseResult`.
- [ ] 2.2 Enforce model-output guardrails for unknown capability, `rfcName`, malformed JSON, non-object parameters, and unsupported intent.
- [ ] 2.3 Add `hybrid`, `llm`, and `rule` intent modes while keeping `hybrid` as the CLI default.

## 3. Orchestration And CLI Integration

- [ ] 3.1 Update `run_inventory_query` to accept an injectable intent adapter and preserve existing rule-parser behavior in tests.
- [ ] 3.2 Update `agent/sap_nexus_agent/cli.py` to construct the selected intent adapter and avoid printing LLM secrets or raw config.
- [ ] 3.3 Ensure CallPlan, Gateway validate / execute, ExecutionResult, ReasoningFact, and narrator behavior remain unchanged after intent parsing.

## 4. Tests, Eval, And Verification

- [ ] 4.1 Add fake LLM tests for happy path, missing plant clarification, hybrid fallback, malformed JSON, unknown capability, and `rfcName` guard.
- [ ] 4.2 Add optional live LLM smoke test gated by `SAP_NEXUS_LLM_LIVE=1` and local `LLM_*` environment variables.
- [ ] 4.3 Update eval or test documentation to state normal verification does not require live LLM credentials.
- [ ] 4.4 Run `python -m pytest agent/tests`, `python -m sap_nexus_agent.eval evals/inventory_availability_cases.yaml`, and `openspec validate --all --strict`.
```

## openspec/changes/sap-nexus-agent-llm-intent-adapter/specs/agent-callplan-evidence/spec.md

- Source: openspec/changes/sap-nexus-agent-llm-intent-adapter/specs/agent-callplan-evidence/spec.md
- Lines: 1-50
- SHA256: 99febb711f2c717b11240fe9c551d306c34708dddeba331ef13296a3ef03abd7

```md
## MODIFIED Requirements

### Requirement: Chinese inventory intent parsing
The system SHALL parse Chinese inventory availability queries for `MM.Inventory.GetAvailability` into normalized intent parameters without using free-form RFC names. The parser MAY use a real LLM intent adapter before deterministic validation, but the LLM output is advisory and MUST be normalized into the same closed-set intent contract before capability selection.

#### Scenario: Parse complete inventory availability query with LLM adapter
- **WHEN** hybrid intent mode is enabled and the LLM returns trusted JSON for `DEMOA1 在 1000 还有多少可用库存？`
- **THEN** the Agent identifies inventory availability intent and extracts `material=DEMOA1` and `plant=1000`
- **AND** the Agent proceeds through deterministic closed-set capability selection before Gateway validation

#### Scenario: Fall back to rule parser when LLM is unavailable
- **WHEN** hybrid intent mode is enabled and the LLM client is missing configuration, times out, returns malformed JSON, or cannot be reached
- **THEN** the Agent falls back to the existing deterministic rule parser
- **AND** executable rule-parser results still follow the normal CallPlan and Gateway path

#### Scenario: Reject LLM-generated RFC name
- **WHEN** the LLM returns JSON containing `rfcName` or a raw SAP BAPI/RFC identifier
- **THEN** the Agent treats the output as untrusted and does not execute from that LLM output
- **AND** Gateway validate and execute are not called unless a safe fallback parser independently produces a valid closed-set capability request

### Requirement: Closed-set capability selection
The system SHALL select capabilities only from the Registry closed set and MUST reject unsupported intent before Gateway execution. LLM-assisted selection MUST be constrained to the same closed set and MUST NOT introduce new executable capability IDs.

#### Scenario: LLM selects registered capability only
- **WHEN** the LLM returns `capabilityId=MM.Inventory.GetAvailability` with required inventory parameters
- **THEN** the Agent accepts the candidate only after deterministic validation confirms the closed-set capability

#### Scenario: LLM returns unknown capability
- **WHEN** the LLM returns an unknown or unsupported `capabilityId`
- **THEN** the Agent rejects that LLM output for execution and does not call Gateway validate or execute from it

### Requirement: Missing parameter clarification
The system MUST clarify missing required inventory parameters before any Gateway validate or execute call, whether missing parameters are detected by rules or by LLM output.

#### Scenario: LLM missing plant is clarified before Gateway call
- **WHEN** the LLM identifies inventory availability intent but omits `plant`
- **THEN** the Agent returns a Chinese clarification asking for `plant`
- **AND** the Agent does not call Gateway validate or execute

### Requirement: Eval and trace evidence
The system SHALL provide repeatable fast eval coverage for the read-only Agent MVP and keep generated runtime evidence out of git. Normal verification MUST NOT require live LLM network access or real model credentials.

#### Scenario: Fake LLM eval covers hybrid behavior
- **WHEN** the Agent test suite runs without live LLM credentials
- **THEN** fake LLM cases verify happy path, missing params, fallback, unknown capability, malformed JSON, and `rfcName` guard behavior

#### Scenario: Optional live LLM smoke is explicitly gated
- **WHEN** live LLM smoke tests exist
- **THEN** they run only when an explicit environment flag is set
- **AND** they skip by default without printing API keys, full model gateway config, or raw sensitive response content
```


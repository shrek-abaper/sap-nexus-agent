---
archived-with: 2026-06-20-sap-nexus-agent-llm-intent-adapter
status: final
---
# SAP Nexus Agent LLM Intent Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Add a real OpenAI-compatible LLM intent adapter for Chinese inventory availability queries while preserving deterministic SAP governance and rule fallback.

**Architecture:** The CLI defaults to `hybrid`, which calls an LLM intent adapter first and falls back to the existing rule parser when the LLM is unavailable or untrusted. The LLM output is normalized into the existing `IntentParseResult` contract before closed-set capability selection, CallPlan creation, Gateway execution, ReasoningFact creation, and deterministic narration.

**Tech Stack:** Python 3.12, OpenAI Python SDK, python-dotenv, pytest, OpenSpec/Comet.

**Change:** `sap-nexus-agent-llm-intent-adapter`
**Design Doc:** `docs/superpowers/specs/2026-06-20-sap-nexus-agent-llm-intent-adapter-design.md`
**Canonical Spec:** `openspec/changes/sap-nexus-agent-llm-intent-adapter/specs/agent-callplan-evidence/spec.md`

---

## File Structure

- Modify: `agent/pyproject.toml` for `openai` and `python-dotenv` dependencies.
- Modify: `.env.example` for placeholder `LLM_*` variables only.
- Create: `agent/sap_nexus_agent/llm_client.py` for OpenAI-compatible JSON chat and config loading.
- Create: `agent/sap_nexus_agent/llm_intent.py` for prompt, LLM output normalization, and adapter mode helpers.
- Modify: `agent/sap_nexus_agent/orchestrator.py` to accept an injectable `intent_adapter`.
- Modify: `agent/sap_nexus_agent/cli.py` to expose `--intent-mode rule|llm|hybrid`.
- Create: `agent/tests/test_llm_intent.py` for adapter unit tests.
- Modify: `agent/tests/test_orchestrator.py` for injected LLM adapter orchestration cases.
- Create: `agent/tests/test_llm_live.py` for gated live smoke.
- Modify: `openspec/changes/sap-nexus-agent-llm-intent-adapter/tasks.md` as tasks complete.

---

### Task 1: Configuration And LLM Client

**Files:**
- Modify: `agent/pyproject.toml`
- Modify: `.env.example`
- Create: `agent/sap_nexus_agent/llm_client.py`
- Test: `agent/tests/test_llm_intent.py`

- [x] **Step 1: Write failing config/client tests**

Add tests that import `LlmSettings`, verify missing config returns unavailable, and verify secret values are not exposed in error strings.

- [x] **Step 2: Run the targeted test and verify RED**

Run: `cd agent && python -m pytest tests/test_llm_intent.py -q`

Expected: FAIL because `sap_nexus_agent.llm_client` does not exist.

- [x] **Step 3: Implement minimal client/config code**

Create `llm_client.py` with `LlmSettings`, `LlmUnavailable`, `OpenAiCompatibleLlmClient`, and a small `load_llm_settings()` helper.

- [x] **Step 4: Update dependencies and `.env.example` placeholders**

Add `openai>=1.0.0` and `python-dotenv>=1.0.0`; add placeholder-only `LLM_*` variables to `.env.example`.

- [x] **Step 5: Run targeted tests and verify GREEN**

Run: `cd agent && python -m pytest tests/test_llm_intent.py -q`

Expected: PASS for config/client tests.

### Task 2: LLM Intent Normalization And Guardrails

**Files:**
- Create: `agent/sap_nexus_agent/llm_intent.py`
- Test: `agent/tests/test_llm_intent.py`

- [x] **Step 1: Add failing tests for LLM output normalization**

Cover happy path, missing plant, unknown capability, `rfcName`, malformed JSON, and unavailable LLM fallback.

- [x] **Step 2: Run tests and verify RED**

Run: `cd agent && python -m pytest tests/test_llm_intent.py -q`

Expected: FAIL because `llm_intent.py` behavior is not implemented.

- [x] **Step 3: Implement minimal `llm_intent.py`**

Add fake-client friendly protocol, strict prompt builder, `parse_with_llm`, `parse_with_hybrid`, and `build_intent_adapter(mode)`.

- [x] **Step 4: Run tests and verify GREEN**

Run: `cd agent && python -m pytest tests/test_llm_intent.py -q`

Expected: PASS.

### Task 3: Orchestrator And CLI Integration

**Files:**
- Modify: `agent/sap_nexus_agent/orchestrator.py`
- Modify: `agent/sap_nexus_agent/cli.py`
- Test: `agent/tests/test_orchestrator.py`

- [x] **Step 1: Add failing tests for injected adapter and LLM guard behavior**

Add orchestrator tests proving an injected LLM adapter can drive a valid request, missing plant does not call Gateway, and `rfcName` output does not call Gateway.

- [x] **Step 2: Run tests and verify RED**

Run: `cd agent && python -m pytest tests/test_orchestrator.py -q`

Expected: FAIL because `run_inventory_query` does not accept `intent_adapter`.

- [x] **Step 3: Implement orchestrator and CLI changes**

Update `run_inventory_query(text, gateway, intent_adapter=parse_inventory_intent)`. Add CLI `--intent-mode` defaulting to `hybrid` and use `build_intent_adapter`.

- [x] **Step 4: Run tests and verify GREEN**

Run: `cd agent && python -m pytest tests/test_orchestrator.py tests/test_llm_intent.py -q`

Expected: PASS.

### Task 4: Optional Live Smoke And Full Verification

**Files:**
- Create: `agent/tests/test_llm_live.py`
- Modify: `openspec/changes/sap-nexus-agent-llm-intent-adapter/tasks.md`

- [x] **Step 1: Add gated live smoke test**

Create a test that skips unless `SAP_NEXUS_LLM_LIVE=1`, then calls the real LLM adapter using local `LLM_*` env and asserts only normalized intent fields.

- [x] **Step 2: Run normal tests and verify live test skips**

Run: `cd agent && python -m pytest tests/test_llm_live.py -q`

Expected: SKIPPED unless explicitly enabled.

- [x] **Step 3: Run full verification**

Run:

```bash
scripts/verify-agent-callplan-evidence.sh
openspec validate --all --strict
```

Expected: all tests and OpenSpec validation pass. OpenSpec PostHog telemetry network errors are non-blocking after successful validation output.

- [x] **Step 4: Update OpenSpec task checkboxes**

Mark tasks complete only after verification evidence passes.

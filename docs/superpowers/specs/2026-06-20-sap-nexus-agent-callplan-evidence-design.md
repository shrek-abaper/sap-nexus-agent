---
comet_change: sap-nexus-agent-callplan-evidence
role: technical-design
canonical_spec: openspec
archived-with: 2026-06-20-sap-nexus-agent-callplan-evidence
status: final
---

# SAP Nexus Agent CallPlan Evidence Technical Design

## Context

The completed `sap-nexus-capability-registry-gateway` change established the Java Gateway and Registry contract. The Gateway exposes capability-level APIs for `MM.Inventory.GetAvailability`, validates registered parameters, maps the capability to `BAPI_MATERIAL_AVAILABILITY`, returns normalized `ExecutionResult`, and writes Gateway traces.

This change adds the first read-only Python Agent slice on top of that contract:

```text
Chinese user intent
-> Intent Harness
-> closed-set Capability Selection
-> CallPlan
-> Java Gateway validate / execute
-> ExecutionResult
-> ReasoningFact
-> Chinese Narrator
-> Eval / Trace evidence
```

The Agent consumes the existing Registry and Gateway. It must not re-implement Gateway behavior, change Registry executor mappings, expose raw RFC execution, or execute SAP writes.

## Goals

- Parse Chinese inventory availability questions into `material`, `plant`, and optional `unit`.
- Select only `MM.Inventory.GetAvailability` for the read-only MVP.
- Clarify missing `material` or `plant` before any Gateway call.
- Create a CallPlan before Gateway validate.
- Call Gateway validate before Gateway execute.
- Convert successful Gateway `ExecutionResult` data into `ReasoningFact`.
- Render Chinese narrative only from facts.
- Provide deterministic fast tests and evals without requiring live SAP.
- Keep generated runtime evidence and sensitive data out of git.

## Non-Goals

- SAP Write Action.
- `RecommendationPlan`.
- ML uncertainty reasoning.
- Knowledge Graph runtime.
- UI.
- Multi-domain orchestration.
- LLM-based routing.
- Gateway or Registry behavior changes.

## Architecture

The Agent should be organized as small modules under `agent/sap_nexus_agent/`:

| Module | Responsibility |
|---|---|
| `intent.py` | Parse Chinese inventory intent and extract normalized parameters. |
| `capability_selector.py` | Select only registered read-only MVP capabilities from a closed set. |
| `call_plan.py` | Build Agent-side CallPlan with `agentTraceId`. |
| `gateway_client.py` | Call Gateway validate / execute by `capabilityId`. |
| `execution_result.py` | Parse Gateway `ExecutionResult` and safe failure outcomes. |
| `reasoning_fact.py` | Convert successful execution data into deterministic facts. |
| `narrator.py` | Render Chinese responses from facts or structured failures only. |
| `eval_runner.py` | Run YAML eval cases with fake or live Gateway client modes. |
| `cli.py` | Provide a minimal read-only inventory query entrypoint. |

Supporting artifacts:

| Artifact | Purpose |
|---|---|
| `schemas/call-plan.schema.json` | Cross-language CallPlan contract. |
| `schemas/reasoning-fact.schema.json` | Fact/evidence contract used by narrator and evals. |
| `evals/inventory_availability_cases.yaml` | Regression cases for the MVP behavior. |
| `agent/tests/` | Fast unit tests with fake Gateway clients. |

## Data Flow

### Complete Query

```text
User query: "DEMOA1 在 1000 还有多少可用库存？"
-> intent parser extracts material=DEMOA1, plant=1000
-> selector returns MM.Inventory.GetAvailability
-> CallPlan created with agentTraceId
-> Gateway validate request: {"parameters": {"material": "DEMOA1", "plant": "1000"}}
-> Gateway execute request: {"parameters": {"material": "DEMOA1", "plant": "1000"}}
-> ExecutionResult parsed
-> ReasoningFact created with agentTraceId + gatewayTraceId
-> narrator renders Chinese fact answer
```

### Missing Parameter

```text
User query: "查一下 DEMOA1 的可用量"
-> parser extracts material only
-> missing plant detected
-> Agent returns Chinese clarification
-> Gateway validate calls = 0
-> Gateway execute calls = 0
```

### Gateway Failure

```text
Gateway validate/execute returns success=false
-> Agent maps errorType and safe messages into structured failure
-> no successful availability ReasoningFact is created
-> narrator renders failure explanation without secrets
```

## Key Decisions

### 1. Deterministic Parser Before LLM Router

Use deterministic rules for the first slice. This keeps the MVP auditable and prevents LLM-generated capability IDs, RFC names, or unsupported parameters.

Future LLM support can sit behind the same closed-set selector contract, but this change should not introduce it.

### 2. Closed-Set Capability Selection

The selector only returns `MM.Inventory.GetAvailability` when the query is an inventory availability request. Unknown or write-oriented intents fail closed before Gateway calls.

A user-supplied `rfcName` must be ignored or rejected. The Agent never forwards `rfcName`; it only sends `parameters` to Gateway capability endpoints.

### 3. Agent Trace And Gateway Trace Are Correlated, Not Forced Equal

The current Gateway request body accepts only `parameters`, and Gateway validation generates its own `traceId`. The Agent should therefore create an Agent-side trace in the CallPlan and store Gateway-returned trace IDs separately.

Recommended fields:

```json
{
  "agentTraceId": "agent_...",
  "gatewayTraceId": "...",
  "capabilityId": "MM.Inventory.GetAvailability"
}
```

This avoids changing the completed Gateway contract while preserving replay correlation.

### 4. Fast Tests Use Fake Gateway Client

Fast verification must not require SAP credentials, JCo native libraries, or a running Gateway. The orchestrator should accept an injected Gateway client so tests and evals can use deterministic fakes.

Live Gateway smoke remains optional when `gateway-jco` and SAP environment variables are available.

### 5. Narrator Consumes Facts Only

The narrator should not read raw SAP responses. It consumes `ReasoningFact` or structured failure outcomes. If a requested value is absent from facts, it must fail with a narrative guard outcome rather than inventing a number.

## Error Handling

| Error | Agent Behavior |
|---|---|
| Missing `material` | Return Chinese clarification; no Gateway call. |
| Missing `plant` | Return Chinese clarification; no Gateway call. |
| Unknown intent | Return unsupported read-only MVP response; no Gateway call. |
| User-supplied `rfcName` | Ignore or reject; never forward to Gateway. |
| Gateway `MISSING_PARAMETER` | Return structured failure; do not execute. |
| Gateway `INVALID_PARAMETER` | Return structured failure; do not execute. |
| Gateway execute failure | Return safe failure narrative; no success fact. |
| Sensitive text in failure | Redact password, token, secret, destination, `.env`, and SAP config markers. |

## Testing Strategy

### Fast Unit Tests

Run with:

```bash
python -m pytest agent/tests
```

Coverage targets:

- Complete Chinese query extraction.
- Optional `unit` extraction.
- Missing `material` clarification.
- Missing `plant` clarification.
- Unknown intent rejection.
- User-supplied `rfcName` guard.
- CallPlan creation before validate.
- Validate-before-execute ordering.
- Validation failure stops execute.
- Execution failure creates no success fact.
- ReasoningFact includes available quantity evidence.
- Narrator only cites fact fields.
- Sensitive-data redaction.

### Eval Runner

Run with:

```bash
python -m sap_nexus_agent.eval evals/inventory_availability_cases.yaml
```

The eval runner should assert:

- selected capability
- missing parameters
- Gateway validate / execute call counts
- success or failure outcome
- narrative guard behavior
- absence of sensitive strings

### OpenSpec Validation

Run with:

```bash
openspec validate --all --strict
```

### Optional Live Smoke

When the Java Gateway is running locally and SAP/JCo environment variables are available, run a live smoke against `http://localhost:8080`. This is additional evidence, not a prerequisite for fast tests.

## Safety Constraints

- Do not commit `.env`, SAP passwords, destination config, tokens, or generated runtime traces.
- Do not print sensitive SAP configuration.
- Do not add arbitrary RFC endpoints.
- Do not let the Agent submit or override `rfcName`.
- Do not implement SAP writes, approval, or actions in this change.
- Keep generated runtime artifacts under ignored `runtime/` paths.

## Spec Patch

No OpenSpec delta spec patch is required. The existing delta spec already covers the required behavior. The `agentTraceId` / `gatewayTraceId` split is an implementation decision caused by the current Gateway request contract and does not change the requirement scope.

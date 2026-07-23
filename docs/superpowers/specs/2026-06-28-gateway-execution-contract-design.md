---
comet_change: sap-nexus-gateway-execution-contract
role: technical-design
canonical_spec: openspec
archived-with: 2026-06-28-sap-nexus-gateway-execution-contract
status: final
---

# Gateway Execution Contract Technical Design

## Context

SAP Nexus Agent already has a verified read-only inventory vertical slice:

```text
User intent
-> closed-set capability selection
-> CallPlan
-> Java Gateway validate / execute by capabilityId
-> BAPI_MATERIAL_STOCK_REQ_LIST through JCo
-> ExecutionResult
-> ReasoningFact
-> Workbench / narrative / evidence regression
```

The public Gateway API is intentionally semantic:

```text
POST /capabilities/{capabilityId}/validate
POST /capabilities/{capabilityId}/execute
```

The implementation still calls `JcoCapabilityExecutor.execute(CapabilityDefinition, parameters, traceId)`, and the active JCo implementation reads `capability.executor().rfcName()` directly. That remains safe for the current single `JCO_RFC` capability, but it does not yet establish the internal Gateway family contract needed for future `ODATA`, `CDS_ADT`, `CDS_ODATA`, `REST_JSON`, or `SQL_READ` work.

This change introduces a minimal internal execution contract while preserving Agent, Workbench, and `ExecutionResult` compatibility.

## Confirmed Architecture

Use a minimal internal contract facade:

```text
CapabilityController
-> CapabilityValidationService
-> CapabilityRegistry.findEnabled(capabilityId)
-> executorBinding.bindingId from registered capability metadata
-> TechnicalExecutionRequest
-> TechnicalExecutionDispatcher
-> JCO_RFC adapter for current inventory path
-> TechnicalExecutionResult
-> existing ExecutionResult compatibility facade
```

No public binding-level endpoint is added in this change. `POST /bindings/{bindingId}/execute` remains a future operator/API design topic after authorization, request ownership, and redaction rules are proven.

## Contract Model

### TechnicalExecutionRequest

Create this as a Gateway-internal Java type under `gateway-jco/src/main/java/com/sapnexus/gateway/execution/`.

Minimum fields:

```text
traceId
capabilityId
bindingId
executorType
operation
parameters
constraints
callerContext
```

Rules:

- `traceId` comes from validation.
- `capabilityId` comes from the path-selected capability.
- `bindingId` and `executorType` come from Registry metadata, not request payload.
- `parameters` contain only semantic capability inputs that passed validation.
- `operation` may be a stable internal value such as `execute` for the current path.
- `constraints` should carry only registered binding constraints needed by adapters, such as side effect and timeout.
- Request-owned technical override keys are not accepted as technical metadata.

### TechnicalExecutionResult

Create this as a Gateway-internal Java type under `gateway-jco/src/main/java/com/sapnexus/gateway/execution/`.

Minimum fields:

```text
traceId
capabilityId
bindingId
executorType
success
errorType
messages
data
durationMs
redactionApplied
adapterMetadata
```

Rules:

- It is the adapter normalization boundary, not the public response contract.
- It must convert back to the current `ExecutionResult` shape.
- It must not expose SAP destination config, passwords, tokens, `.env`, credential references, sensitive endpoints, headers, or LLM API keys.
- `adapterMetadata` may carry safe technical evidence such as registered `rfcName` for current compatibility, but must be redacted before trace or error output if sensitive keys are present.

## Key Decisions

### 1. Keep `ExecutionResult` as the public compatibility facade

The Python Agent parses the existing response fields: `traceId`, `capabilityId`, `success`, `executor`, `returnMessages`, `data`, `durationMs`, and `errorType`. The Gateway should therefore convert `TechnicalExecutionResult` back into the current `ExecutionResult` instead of changing Python Agent or Workbench contracts.

Implementation implication:

- Keep `com.sapnexus.gateway.result.ExecutionResult` stable.
- Add conversion from `TechnicalExecutionResult` to `ExecutionResult`.
- Preserve `executor.type` and `executor.rfcName` for the current JCo response unless tests show existing consumers do not need `rfcName`.

### 2. Dispatch by registered binding metadata only

Runtime callers may provide semantic parameters such as `material`, `plant`, and `unit`. They must not provide or override `rfcName`, service URL, CDS object, ADT path, REST endpoint, HTTP method, headers, credential references, JSON mapping, raw SQL, or raw protocol payload details.

Implementation implication:

- Extend `CapabilityDefinition` with a minimal nested `ExecutorBinding` record containing `type` and `bindingId`.
- Extend `CapabilityRegistryLoader` to parse `executorBinding` while preserving the legacy `executor` block.
- Prefer `capability.executorBinding().bindingId()` for dispatch.
- Keep `capability.executor()` available for current JCo mapping compatibility.

### 3. Add a closed dispatcher instead of a generic protocol client

The dispatcher should be explicit and fail closed:

```text
JCO_RFC -> current JCo adapter
ODATA -> unsupported technical result
CDS_ADT -> unsupported technical result
CDS_ODATA -> unsupported technical result
REST_JSON -> unsupported technical result
unknown -> unsupported technical result
```

Implementation implication:

- Create `TechnicalAdapter` and `TechnicalExecutionDispatcher`.
- Register the current `JCO_RFC` adapter only.
- Unsupported executor types return deterministic `TechnicalExecutionResult` failures.
- Do not add HTTP, ADT, REST, SQL, or arbitrary RFC runtime clients in this change.

### 4. Adapt the current JCo implementation with minimum behavior change

`InventoryAvailabilityExecutor` already owns current JCo behavior and tests. The safest cutover is to wrap or adapt that path behind the dispatcher, not rewrite SAP extraction logic.

Implementation implication:

- Introduce `JcoRfcTechnicalAdapter`.
- Either move the current JCo body behind the adapter or call the existing JCo implementation from the adapter and convert the result.
- Keep current MD04 data extraction and SAP return normalization behavior.
- Keep `BAPI_MATERIAL_STOCK_REQ_LIST` as registered metadata, never as caller-owned input.

### 5. Centralize redaction at the technical boundary

Current trace summarization removes some unsafe keys, and JCo exception handling masks password-like substrings. Future protocol adapters will carry more sensitive shapes, so this change should add a focused redaction utility used by technical request/result/error paths.

Implementation implication:

- Add a small `TechnicalRedactor` or equivalent package-private utility.
- Cover key names containing password, passwd, token, secret, credential, authorization, api key, destination, endpoint, url, header, config, env, and raw technical override names.
- Prefer deterministic replacement with `***` or key omission, matching existing trace behavior where appropriate.
- Add tests that prove sensitive strings are absent from technical failures and traces.

## File-Level Implementation Shape

Recommended Java placement:

```text
gateway-jco/src/main/java/com/sapnexus/gateway/execution/
  TechnicalExecutionRequest.java
  TechnicalExecutionResult.java
  TechnicalExecutionDispatcher.java
  TechnicalAdapter.java
  JcoRfcTechnicalAdapter.java
  TechnicalRedactor.java
```

Recommended modifications:

```text
gateway-jco/src/main/java/com/sapnexus/gateway/api/CapabilityController.java
gateway-jco/src/main/java/com/sapnexus/gateway/registry/CapabilityDefinition.java
gateway-jco/src/main/java/com/sapnexus/gateway/registry/CapabilityRegistryLoader.java
gateway-jco/src/main/java/com/sapnexus/gateway/result/ErrorType.java
gateway-jco/src/main/java/com/sapnexus/gateway/trace/TraceRecord.java
gateway-jco/src/test/java/com/sapnexus/gateway/api/CapabilityExecutionApiTest.java
gateway-jco/src/test/java/com/sapnexus/gateway/execution/TechnicalExecutionDispatcherTest.java
gateway-jco/src/test/java/com/sapnexus/gateway/execution/TechnicalRedactorTest.java
```

Schema artifacts under `schemas/` are optional for this change if Java types and tests fully cover the internal contract. Add `technical-execution-request.schema.json` and `technical-execution-result.schema.json` only if implementation needs language-neutral artifacts now.

## Test Strategy

Add or update Gateway tests before implementation:

- API compatibility: executing `MM.Inventory.GetAvailability` still returns the existing `ExecutionResult` fields and current JCo metadata.
- Request ownership: request payloads containing `rfcName`, URL, endpoint, HTTP method, headers, `credentialRef`, JSON mapping, raw SQL, or equivalent technical override keys do not reach adapter execution as caller-owned technical metadata.
- Dispatcher routing: registered `JCO_RFC` binding dispatches to the JCo adapter by `bindingId`.
- Fail closed: `ODATA`, `CDS_ADT`, `CDS_ODATA`, `REST_JSON`, and unknown executor types return deterministic failures without external execution.
- Registry compatibility: loader parses `executorBinding.bindingId` while preserving existing `executor` mapping.
- Redaction: technical result, trace, and errors do not expose `.env`, SAP password, destination config, token, API key, credential material, sensitive endpoints, or headers.

Regression verification after implementation:

```bash
cd gateway-jco && /tmp/gradle-8.8/bin/gradle --no-daemon test
.venv/bin/python scripts/validate-registry-contract.py registry/capabilities.yaml
.venv/bin/python -m pytest agent/tests/test_registry_contract.py -v
scripts/verify-agent-callplan-evidence.sh
openspec validate --all --strict
```

Use the repository's actual Gradle wrapper or installed Gradle path if `/tmp/gradle-8.8/bin/gradle` is not available.

## Risks And Mitigations

| Risk | Mitigation |
|---|---|
| Gateway response drift breaks Python Agent or Workbench | Keep `ExecutionResult` stable and run Agent CallPlan/evidence regression |
| Dispatcher becomes a generic protocol executor | Use explicit executor-type switch and unsupported-result tests |
| Java Registry model diverges from YAML contract | Add minimal `ExecutorBinding` parsing and loader tests |
| Redaction misses protocol-specific secrets | Add deterministic sensitive-key tests now and extend per future adapter |
| Scope expands into OData, CDS, REST, or SQL runtime | Return fail-closed results only; open separate changes for each runtime pilot |

## Spec Patch

No OpenSpec delta patch is required. The existing `gateway-execution-contract` delta spec already covers binding-owned requests, closed dispatcher behavior, result compatibility, and technical redaction.

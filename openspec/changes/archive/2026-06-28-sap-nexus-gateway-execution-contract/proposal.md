## Why

The current Java Gateway already protects SAP access at the capability API boundary, but the execution path still couples the active semantic capability directly to `executor.rfcName`. The next multi-executor phase needs a stable technical execution contract so registered `bindingId` entries can dispatch to controlled adapters without exposing raw RFC names, URLs, headers, credentials, JSON mappings, or future SQL details to callers or the LLM.

## What Changes

- Add a Gateway execution contract for allowlisted technical execution by `bindingId`.
- Define `TechnicalExecutionRequest` and `TechnicalExecutionResult` as the Gateway-internal contract between capability lookup and protocol adapters.
- Introduce a closed `bindingId -> technical adapter` dispatcher boundary.
- Adapt the current `JCO_RFC` inventory path to the new contract while preserving the existing capability-level `/capabilities/{capabilityId}/validate|execute` API and current Agent-facing `ExecutionResult` behavior.
- Add fail-closed handling for future executor types that are contract-ready but not implemented in this change.
- Add request-ownership guards that reject caller-owned technical overrides such as `rfcName`, service URLs, REST endpoints, HTTP methods, headers, credential references, JSON mappings, or raw technical payload details.
- Normalize technical error, trace, duration, and redaction behavior at the technical execution boundary.

## Capabilities

### New Capabilities

- `gateway-execution-contract`: Defines Gateway technical execution request/result, binding dispatch, adapter fail-closed behavior, request-owned technical detail rejection, and compatibility with current capability-level execution.

### Modified Capabilities

- None.

## Impact

- Affected code: `gateway-jco/` controller, registry loader/model, JCo execution path, trace/result normalization, and Gateway tests.
- Affected contracts: new technical execution schemas or Java contract types under `schemas/` and/or `gateway-jco/`.
- Affected registry artifacts: `registry/capabilities.yaml` and `registry/executor-bindings.yaml` may need compatibility linkage validation, but the semantic capability contract remains the source of `capabilityId`.
- Affected verification: Gateway tests, Registry contract validation, Agent CallPlan/evidence regression, and OpenSpec strict validation.
- No breaking change is intended for Agent, Workbench, or existing capability-level Gateway clients.

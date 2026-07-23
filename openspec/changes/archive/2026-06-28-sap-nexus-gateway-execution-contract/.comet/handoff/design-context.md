# Comet Design Handoff

- Change: sap-nexus-gateway-execution-contract
- Phase: design
- Mode: compact
- Context hash: eb53e8f906bc4810be2046d1232da7537ef1591578bdff2bf2f1be981ecf0ead

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/sap-nexus-gateway-execution-contract/proposal.md

- Source: openspec/changes/sap-nexus-gateway-execution-contract/proposal.md
- Lines: 1-31
- SHA256: 25d1db1cef4841f380427e15128c2cf2e7f054a33a21f63de2b029b3c5f8a23c

```md
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
```

## openspec/changes/sap-nexus-gateway-execution-contract/design.md

- Source: openspec/changes/sap-nexus-gateway-execution-contract/design.md
- Lines: 1-100
- SHA256: 55f66b686cab47e779f69471e081c11166e7584d4ee1b7eab119a11d7c2d9fff

[TRUNCATED]

```md
## Context

SAP Nexus Agent has completed the read-only inventory vertical slice: Registry-backed capability lookup, Java JCo Gateway validation/execution, Python Agent CallPlan/evidence, LLM intent adapter, Workbench runtime, MD04 inventory correction, and Registry / OWL contract hardening are archived. The current capability API is intentionally semantic:

```text
POST /capabilities/{capabilityId}/validate
POST /capabilities/{capabilityId}/execute
```

The implementation still passes `CapabilityDefinition` directly into `JcoCapabilityExecutor`, and the active JCo executor reads `capability.executor().rfcName()` during execution. That is safe for the single current `JCO_RFC` capability, but it does not yet establish the Gateway family contract needed for future `ODATA`, `CDS_ADT`, `CDS_ODATA`, `REST_JSON`, or `SQL_READ` work.

This change creates the technical execution layer that sits below semantic capability selection and above protocol adapters:

```text
capabilityId
-> Registry capability
-> executorBinding.bindingId
-> TechnicalExecutionRequest
-> binding dispatcher
-> technical adapter
-> TechnicalExecutionResult
-> current ExecutionResult compatibility facade
```

## Goals / Non-Goals

**Goals:**

- Define a Gateway-internal `TechnicalExecutionRequest` model derived from registered metadata.
- Define a `TechnicalExecutionResult` model that records binding, executor type, success, messages, data, duration, error type, and redaction state.
- Introduce a closed dispatcher from `bindingId` / executor type to technical adapter.
- Adapt the current `JCO_RFC` inventory path with minimum behavior change.
- Keep `/capabilities/{capabilityId}/validate|execute`, Agent `ExecutionResult`, Workbench rendering, and `ReasoningFact` behavior compatible.
- Reject or ignore caller-owned raw technical details before execution.
- Fail closed for future executor types that are contract-ready but not implemented here.

**Non-Goals:**

- No new SAP capability.
- No OData, CDS / ADT, REST JSON, or SQL_READ runtime pilot.
- No SAP write action or Human Approval runtime change.
- No arbitrary RFC, URL, SQL, HTTP, ADT, REST, or LLM-generated payload execution.
- No Knowledge Graph runtime dependency.
- No frontend UI changes.

## Decisions

### Decision 1: Keep capability-level API as the public compatibility facade

The existing Gateway API remains the public path for Agent and Workbench callers. The new technical contract is internal to Gateway execution.

Alternative considered: expose `POST /bindings/{bindingId}/execute` now. This is too early because direct binding execution needs separate request ownership, authorization, redaction, and operator experience decisions. Keeping it internal reduces blast radius and preserves current Agent behavior.

### Decision 2: Dispatch by allowlisted `bindingId`, not request-provided technical details

The dispatcher resolves only registered binding metadata. Runtime callers cannot provide or override `rfcName`, URLs, headers, credential references, JSON mappings, SQL, or raw protocol details.

Alternative considered: allow expert clients to pass technical overrides for testing. This would weaken the core SAP Nexus safety boundary and conflicts with the closed capability model.

### Decision 3: Preserve the current JCo adapter first, then introduce future adapters separately

The current inventory implementation remains the only executable adapter path in this change. `ODATA`, `CDS_ADT`, `CDS_ODATA`, `REST_JSON`, and future executor types are recognized only enough to fail closed.

Alternative considered: implement an OData or REST pilot in the same change. That would mix contract refactoring with new runtime integration risk and make verification harder.

### Decision 4: Convert technical results back to the existing `ExecutionResult`

The Python Agent and Workbench already consume current `ExecutionResult` fields. `TechnicalExecutionResult` should be a lower-level normalization boundary, then convert into the existing response shape.

Alternative considered: replace `ExecutionResult` directly. That would create avoidable Agent, eval, and Workbench churn.

### Decision 5: Put redaction at the technical boundary

Sensitive data must be removed before technical results, traces, and errors leave the adapter boundary. Existing response redaction is not enough because future adapters will carry endpoint, header, and credential metadata.

Alternative considered: keep redaction only in controller traces. That misses adapter-level failures and protocol-specific metadata.

## Risks / Trade-offs

- `bindingId` model diverges from current Java Registry model -> Extend the loader/model minimally and keep legacy `executor` compatibility until all callers migrate.
```

Full source: openspec/changes/sap-nexus-gateway-execution-contract/design.md

## openspec/changes/sap-nexus-gateway-execution-contract/tasks.md

- Source: openspec/changes/sap-nexus-gateway-execution-contract/tasks.md
- Lines: 1-26
- SHA256: 7ef4c8a3144426c55153e2c58650410d175fd971baefe94ad068b04a2996f475

```md
## 1. Contract Baseline

- [ ] 1.1 Inspect current Gateway controller, registry loader/model, JCo executor, result, trace, and test structure with CodeGraph.
- [ ] 1.2 Add or update Gateway tests for technical request ownership, raw technical override rejection, binding dispatcher resolution, unsupported executor fail-closed behavior, and current JCo compatibility.
- [ ] 1.3 Define the minimal `TechnicalExecutionRequest` and `TechnicalExecutionResult` contract shape in Java and/or schema artifacts.

## 2. Dispatcher And JCo Compatibility

- [ ] 2.1 Extend Registry loading/model access to resolve the current capability's registered `executorBinding.bindingId` while preserving existing `executor` compatibility.
- [ ] 2.2 Implement a closed technical dispatcher that maps allowlisted `bindingId` / executor type to an adapter.
- [ ] 2.3 Adapt the current `JCO_RFC` inventory execution path to run through the dispatcher and convert back to the existing `ExecutionResult` response.
- [ ] 2.4 Add deterministic fail-closed handling for contract-recognized but unimplemented executor types.

## 3. Redaction, Trace, And Regression

- [ ] 3.1 Centralize technical result / error redaction for destination config, SAP password, `.env`, tokens, headers, credential references, endpoints, and LLM API keys.
- [ ] 3.2 Ensure Gateway trace records include the needed execution evidence without leaking sensitive technical details.
- [ ] 3.3 Run Gateway-focused tests and fix regressions without changing Agent-facing behavior.
- [ ] 3.4 Run Registry contract validation and Agent CallPlan/evidence regression.

## 4. Documentation And OpenSpec Closeout

- [ ] 4.1 Update `docs/runbooks/05-gateway-execution-contract.md` and `docs/runbooks/README.md` with implementation progress, verification evidence, blockers, and next action.
- [ ] 4.2 Update `docs/wiki/sap-nexus-agent-implementation-roadmap.md` stale current-next-step content after this change is verified.
- [ ] 4.3 Run `openspec validate --all --strict` and record verification evidence.
- [ ] 4.4 Complete Comet verify and archive flow for `sap-nexus-gateway-execution-contract`.
```

## openspec/changes/sap-nexus-gateway-execution-contract/specs/gateway-execution-contract/spec.md

- Source: openspec/changes/sap-nexus-gateway-execution-contract/specs/gateway-execution-contract/spec.md
- Lines: 1-60
- SHA256: b4475d683c886eca517247bdd0dc35309e65b26e0cdd3e6f4db8c211e30285f1

```md
## ADDED Requirements

### Requirement: Technical execution requests are binding-owned

The Gateway MUST create technical execution requests from registered capability and executor binding metadata, not from caller-owned raw technical details.

#### Scenario: Build request from registered binding

- **WHEN** a valid capability execution request is accepted for `MM.Inventory.GetAvailability`
- **THEN** the Gateway creates a technical execution request using the capability's registered `executorBinding.bindingId`
- **AND** the request identifies the allowlisted executor type and normalized parameters needed by the adapter
- **AND** the request does not use caller-provided `rfcName`, URL, header, credential, SQL, or payload-mapping fields

#### Scenario: Reject raw technical override

- **WHEN** a caller includes `rfcName`, service URL, CDS object, ADT path, REST endpoint, HTTP method, headers, `credentialRef`, JSON mapping, raw SQL, or equivalent technical override fields
- **THEN** the Gateway rejects or ignores those fields before adapter execution
- **AND** SAP or external execution is not attempted with caller-owned technical details

### Requirement: Dispatcher executes only allowlisted bindings

The Gateway MUST resolve technical execution through a closed dispatcher that maps registered `bindingId` and executor type to an allowed adapter.

#### Scenario: Dispatch current JCO_RFC binding

- **WHEN** the registered inventory binding resolves to executor type `JCO_RFC`
- **THEN** the dispatcher invokes the controlled JCo adapter for the current inventory read path
- **AND** the adapter uses the registered binding metadata rather than arbitrary runtime RFC selection

#### Scenario: Fail closed for unsupported future executor

- **WHEN** a registered binding uses `ODATA`, `CDS_ADT`, `CDS_ODATA`, `REST_JSON`, or another contract-recognized executor without an implemented runtime adapter in this change
- **THEN** the dispatcher returns a deterministic fail-closed technical result
- **AND** the Gateway does not attempt arbitrary HTTP, ADT, CDS, REST, SQL, or RFC execution

### Requirement: Technical results remain compatible with capability execution

The Gateway MUST normalize adapter output into a technical execution result that remains convertible to the current capability-level `ExecutionResult`.

#### Scenario: Preserve Agent-facing execution result

- **WHEN** `MM.Inventory.GetAvailability` executes successfully through the binding dispatcher
- **THEN** the capability-level response preserves the current `ExecutionResult` fields expected by the Python Agent and Workbench
- **AND** existing `ReasoningFact` generation and Agent regression behavior remain unchanged

#### Scenario: Normalize technical failure

- **WHEN** adapter execution fails because of SAP communication, SAP authorization, SAP business error, unsupported executor type, or normalization failure
- **THEN** the technical result records `traceId`, `bindingId`, executor type, success state, error type, messages, duration, and redaction status
- **AND** the converted capability-level result uses deterministic error semantics compatible with the current Gateway API

### Requirement: Technical traces and errors are redacted

The Gateway MUST apply sensitive-data redaction at the technical execution boundary and in trace records.

#### Scenario: Redact sensitive technical details

- **WHEN** a technical request, result, trace, or error contains destination config, SAP password, `.env` content, token, LLM API key, raw credential, sensitive endpoint, header secret, or credential reference material
- **THEN** the Gateway redacts the sensitive value before returning or writing trace output
- **AND** verification can prove no sensitive value is exposed through normal response, trace, or error paths
```


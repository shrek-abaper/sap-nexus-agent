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
- Current Gateway tests may be thin around controller execution -> Add focused unit tests around dispatcher and contract guards before changing behavior.
- Adapter abstraction could become overgeneralized -> Keep only fields required by current JCo compatibility and documented future fail-closed behavior.
- Redaction may be incomplete for future protocols -> Add deterministic redaction tests for known sensitive key patterns now, and extend per future adapter.
- Roadmap docs currently contain one stale "current next step" section -> Update docs during closeout after implementation and verification evidence exists.

## Migration Plan

1. Add contract and dispatcher tests that describe the new boundary.
2. Add minimal Java contract types and dispatcher implementation.
3. Adapt current JCo execution through the dispatcher while preserving existing capability API output.
4. Extend registry model/loading only as needed for `executorBinding.bindingId`.
5. Run Gateway tests, Registry validator, Agent regression, and OpenSpec validation.
6. Update runbook / roadmap closeout notes and archive the change.

Rollback is straightforward before archive: remove the technical execution contract classes/tests and restore direct `JcoCapabilityExecutor` wiring. No data migration is required.

## Open Questions

- The exact Java package names and test command should be confirmed from the current `gateway-jco/` structure during build.
- The first implementation may keep the legacy `executor` block as compatibility metadata while using `executorBinding.bindingId` for dispatch.

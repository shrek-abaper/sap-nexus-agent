# Brainstorm Summary

- Change: sap-nexus-gateway-execution-contract
- Date: 2026-06-28

## 确认的技术方案

- Use a minimal internal contract facade for Runbook 05.
- Keep the existing public Gateway API unchanged: `POST /capabilities/{capabilityId}/validate|execute`.
- Add Gateway-internal `TechnicalExecutionRequest`, `TechnicalExecutionResult`, and a closed dispatcher.
- Let Controller continue entering by `capabilityId`; after validation succeeds, Gateway constructs a technical request from registered metadata.
- Dispatch only by registered `bindingId` / executor type.
- Preserve the current `JCO_RFC` inventory execution path by adapting it behind the dispatcher.
- Convert `TechnicalExecutionResult` back to the existing `ExecutionResult` so Python Agent, Workbench, and `ReasoningFact` behavior remain unchanged.
- Recognize `ODATA`, `CDS_ADT`, `CDS_ODATA`, and `REST_JSON` only enough to fail closed in this change.

## 候选方案

### Approach A - Minimal Internal Contract Facade

Add `TechnicalExecutionRequest`, `TechnicalExecutionResult`, and dispatcher classes inside Gateway, then adapt the current JCo executor behind the dispatcher while keeping current controller and response shape stable.

Trade-off: Lowest blast radius and best compatibility, but keeps legacy `executor` metadata during transition.

### Approach B - Registry-first Binding Catalog Loader

Load `registry/executor-bindings.yaml` into Java immediately and make execution depend on that catalog as the only source of adapter metadata.

Trade-off: Stronger long-term model, but higher loader/schema/test scope and more risk during this compatibility change.

### Approach C - Public Binding Execution API

Add a new binding-level endpoint such as `/bindings/{bindingId}/execute`.

Trade-off: Useful later for operator tooling, but too much request ownership and authorization surface for this change.

## 关键取舍与风险

- Keep current `ExecutionResult` stable for Agent and Workbench.
- Avoid public binding execution until authorization and operator UX are designed.
- Do not complete a broad Java binding-catalog rewrite in this change.
- Add tests before implementation for raw technical override rejection and unsupported executor fail-closed behavior.
- Keep future executor types contract-recognized but non-executable.
- Risk: Java Registry model may lag the YAML `executorBinding` contract; mitigate with a minimal compatibility field and validation.
- Risk: redaction may miss future protocol-specific metadata; mitigate with deterministic sensitive-key tests now and adapter-specific additions later.

## 测试策略

- Gateway unit tests for dispatcher routing, unsupported executor fail-closed, and technical override rejection.
- Existing JCo executor tests remain green and may be extended for technical result conversion.
- Registry contract validator and Agent CallPlan evidence regression must pass.
- OpenSpec strict validation must pass before archive.

## Spec Patch

无。当前 delta spec 已覆盖 binding-owned request、allowlisted dispatcher、result compatibility、redaction 四个核心要求。

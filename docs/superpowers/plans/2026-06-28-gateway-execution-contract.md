---
change: sap-nexus-gateway-execution-contract
design-doc: docs/superpowers/specs/2026-06-28-gateway-execution-contract-design.md
base-ref: cdc8eee6d17b9afa2d9e12f8ad72fd88ee692372
archived-with: 2026-06-28-sap-nexus-gateway-execution-contract
---

# Gateway Execution Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Add a Gateway-internal technical execution request/result and closed binding dispatcher while preserving the public capability-level API and current Agent-facing `ExecutionResult`.

**Architecture:** Keep `POST /capabilities/{capabilityId}/validate|execute` unchanged. The controller validates semantic inputs, rejects caller-owned technical override fields, builds a `TechnicalExecutionRequest` from registered `executorBinding.bindingId`, dispatches only allowlisted executor types, and converts `TechnicalExecutionResult` back to the existing `ExecutionResult`.

**Tech Stack:** Java 17, Spring Boot 3.3.6, JUnit 5, MockMvc, AssertJ, Gradle, Python registry/evidence verification.

## Global Constraints

- Public Gateway callers keep using `capabilityId`; no public `/bindings/{bindingId}/execute` endpoint in this change.
- LLM, user, Agent, and Workbench must not provide or override `rfcName`, URL, endpoint, method, headers, `credentialRef`, JSON mapping, raw SQL, or raw protocol payload details.
- `JCO_RFC` is the only runtime adapter that executes now.
- `ODATA`, `CDS_ADT`, `CDS_ODATA`, `REST_JSON`, and unknown types fail closed without external execution.
- Existing Python Agent, Workbench, `ReasoningFact`, and current `ExecutionResult` behavior must remain compatible.
- Do not implement OData, CDS/ADT, REST JSON, SQL, SAP write actions, arbitrary RFC, arbitrary HTTP, or Knowledge Graph runtime.
- Do not print or commit `.env`, SAP password, destination config, tokens, LLM API keys, credential material, or runtime traces.

archived-with: 2026-06-28-sap-nexus-gateway-execution-contract
---

## File Structure

- Create `gateway-jco/src/main/java/com/sapnexus/gateway/execution/TechnicalExecutionRequest.java` for the internal technical request record.
- Create `gateway-jco/src/main/java/com/sapnexus/gateway/execution/TechnicalExecutionResult.java` for the internal technical result record and `ExecutionResult` conversion.
- Create `gateway-jco/src/main/java/com/sapnexus/gateway/execution/TechnicalAdapter.java` for the adapter interface.
- Create `gateway-jco/src/main/java/com/sapnexus/gateway/execution/TechnicalExecutionDispatcher.java` for closed executor-type routing.
- Create `gateway-jco/src/main/java/com/sapnexus/gateway/execution/JcoRfcTechnicalAdapter.java` to adapt the current `JcoCapabilityExecutor`.
- Create `gateway-jco/src/main/java/com/sapnexus/gateway/execution/TechnicalRedactor.java` for deterministic boundary redaction.
- Modify `gateway-jco/src/main/java/com/sapnexus/gateway/api/CapabilityController.java` to reject technical overrides, build technical requests, dispatch, and convert results.
- Modify `gateway-jco/src/main/java/com/sapnexus/gateway/api/CapabilityRequest.java` to expose forbidden technical override detection.
- Modify `gateway-jco/src/main/java/com/sapnexus/gateway/registry/CapabilityDefinition.java` to add `ExecutorBinding`.
- Modify `gateway-jco/src/main/java/com/sapnexus/gateway/registry/CapabilityRegistryLoader.java` to parse `executorBinding`.
- Modify `gateway-jco/src/main/java/com/sapnexus/gateway/result/ErrorType.java` to add deterministic unsupported-executor semantics.
- Modify `gateway-jco/src/main/java/com/sapnexus/gateway/trace/TraceRecord.java` to reuse stronger redaction coverage.
- Modify `gateway-jco/src/test/java/com/sapnexus/gateway/api/CapabilityExecutionApiTest.java` for API compatibility and override rejection.
- Modify `gateway-jco/src/test/java/com/sapnexus/gateway/api/CapabilityControllerTest.java` constructors for `ExecutorBinding` compatibility if needed.
- Modify `gateway-jco/src/test/java/com/sapnexus/gateway/registry/CapabilityRegistryLoaderTest.java` for binding parsing.
- Create `gateway-jco/src/test/java/com/sapnexus/gateway/execution/TechnicalExecutionDispatcherTest.java`.
- Create `gateway-jco/src/test/java/com/sapnexus/gateway/execution/TechnicalRedactorTest.java`.
- Update `docs/runbooks/05-gateway-execution-contract.md`, `docs/runbooks/README.md`, and `docs/wiki/sap-nexus-agent-implementation-roadmap.md` only after code verification evidence exists.

## Task 1: Contract Baseline And Failing Tests

**Files:**
- Modify: `gateway-jco/src/test/java/com/sapnexus/gateway/api/CapabilityExecutionApiTest.java`
- Modify: `gateway-jco/src/test/java/com/sapnexus/gateway/registry/CapabilityRegistryLoaderTest.java`
- Create: `gateway-jco/src/test/java/com/sapnexus/gateway/execution/TechnicalExecutionDispatcherTest.java`
- Create: `gateway-jco/src/test/java/com/sapnexus/gateway/execution/TechnicalRedactorTest.java`

**Interfaces:**
- Consumes: Existing `CapabilityController`, `JcoCapabilityExecutor`, `CapabilityRegistryLoader`, `ExecutionResult`.
- Produces: Failing tests that pin `ExecutorBinding`, dispatcher routing, override rejection, unsupported executor failure, and redaction.

- [x] **Step 1: Update API happy path to remove unsafe override input**

In `CapabilityExecutionApiTest.executeValidReadCapabilityUsesRegisteredRfcAndReturnsExecutionResult`, change the body from a request containing `rfcName` to:

```java
"{\"parameters\":{\"material\":\"MAT-001\",\"plant\":\"1000\"}}"
```

Keep assertions for `$.executor.rfcName == BAPI_MATERIAL_STOCK_REQ_LIST`, `$.success == true`, and `Config.invocations == 1`.

- [x] **Step 2: Add raw technical override rejection test**

Add this test in `CapabilityExecutionApiTest`:

```java
@Test
void executeRejectsCallerOwnedTechnicalOverrideBeforeAdapterExecution() throws Exception {
    execute("MM.Inventory.GetAvailability", "{\"parameters\":{\"material\":\"MAT-001\",\"plant\":\"1000\",\"rfcName\":\"Z_UNSAFE_RFC\"}}")
            .andExpect(status().isBadRequest())
            .andExpect(jsonPath("$.success", is(false)))
            .andExpect(jsonPath("$.errorType", is("INVALID_PARAMETER")));

    org.assertj.core.api.Assertions.assertThat(Config.invocations.get()).isZero();
}
```

- [x] **Step 3: Add binding metadata to API test fixture**

When `CapabilityDefinition` requires `ExecutorBinding`, construct inventory capability with:

```java
new CapabilityDefinition.ExecutorBinding("JCO_RFC", "sap.mm.inventory.md04-stock-req-list")
```

Use the same binding for disabled or helper capabilities unless a test intentionally needs unsupported executor behavior.

- [x] **Step 4: Add registry loader assertion for `executorBinding.bindingId`**

In `CapabilityRegistryLoaderTest.loadsActiveInventoryAvailabilityCapability`, add:

```java
assertThat(capability.executorBinding().type()).isEqualTo("JCO_RFC");
assertThat(capability.executorBinding().bindingId()).isEqualTo("sap.mm.inventory.md04-stock-req-list");
```

Update `inventoryCapability(...)` fixture YAML to include:

```yaml
executorBinding:
  type: JCO_RFC
  bindingId: sap.mm.inventory.md04-stock-req-list
```

- [x] **Step 5: Create dispatcher routing/fail-closed tests**

Create `TechnicalExecutionDispatcherTest` with tests equivalent to:

```java
class TechnicalExecutionDispatcherTest {
    @Test
    void dispatchesJcoRfcBindingToRegisteredAdapter() {
        TechnicalAdapter adapter = request -> TechnicalExecutionResult.success(
                request.traceId(),
                request.capabilityId(),
                request.bindingId(),
                request.executorType(),
                List.of(),
                Map.of("availableQuantity", 42),
                5,
                Map.of("rfcName", "BAPI_MATERIAL_STOCK_REQ_LIST")
        );
        TechnicalExecutionDispatcher dispatcher = new TechnicalExecutionDispatcher(Map.of("JCO_RFC", adapter));

        TechnicalExecutionResult result = dispatcher.dispatch(new TechnicalExecutionRequest(
                "trace-1",
                "MM.Inventory.GetAvailability",
                "sap.mm.inventory.md04-stock-req-list",
                "JCO_RFC",
                "execute",
                Map.of("material", "MAT-001", "plant", "1000"),
                Map.of("sideEffect", "none"),
                Map.of()
        ));

        assertThat(result.success()).isTrue();
        assertThat(result.bindingId()).isEqualTo("sap.mm.inventory.md04-stock-req-list");
    }

    @Test
    void failsClosedForUnsupportedExecutorType() {
        TechnicalExecutionDispatcher dispatcher = new TechnicalExecutionDispatcher(Map.of());

        TechnicalExecutionResult result = dispatcher.dispatch(new TechnicalExecutionRequest(
                "trace-1",
                "MM.Inventory.GetAvailability",
                "sap.mm.inventory.odata",
                "ODATA",
                "execute",
                Map.of(),
                Map.of(),
                Map.of()
        ));

        assertThat(result.success()).isFalse();
        assertThat(result.errorType()).isEqualTo(ErrorType.UNSUPPORTED_EXECUTOR);
    }
}
```

- [x] **Step 6: Create redaction tests**

Create `TechnicalRedactorTest` with:

```java
class TechnicalRedactorTest {
    @Test
    void redactsSensitiveTechnicalKeysRecursively() {
        Map<String, Object> redacted = TechnicalRedactor.redactMap(Map.of(
                "password", "secret-password",
                "credentialRef", "sap-prod-credential",
                "headers", Map.of("Authorization", "Bearer token-value"),
                "safe", "value"
        ));

        assertThat(redacted.toString()).doesNotContain("secret-password", "sap-prod-credential", "token-value");
        assertThat(redacted).containsEntry("safe", "value");
    }
}
```

- [x] **Step 7: Run focused tests and confirm expected failures**

Run:

```bash
cd gateway-jco && /tmp/gradle-8.8/bin/gradle --no-daemon test --tests '*CapabilityExecutionApiTest' --tests '*CapabilityRegistryLoaderTest' --tests '*TechnicalExecutionDispatcherTest' --tests '*TechnicalRedactorTest'
```

Expected: FAIL because production classes and `ExecutorBinding` parsing do not exist yet.

## Task 2: Registry Binding Model And Request Ownership Guard

**Files:**
- Modify: `gateway-jco/src/main/java/com/sapnexus/gateway/registry/CapabilityDefinition.java`
- Modify: `gateway-jco/src/main/java/com/sapnexus/gateway/registry/CapabilityRegistryLoader.java`
- Modify: `gateway-jco/src/main/java/com/sapnexus/gateway/api/CapabilityRequest.java`
- Modify: `gateway-jco/src/main/java/com/sapnexus/gateway/result/ErrorType.java`
- Modify: `gateway-jco/src/test/java/com/sapnexus/gateway/api/CapabilityControllerTest.java`
- Modify: `gateway-jco/src/test/java/com/sapnexus/gateway/api/CapabilityValidationApiTest.java` if constructor updates require it.

**Interfaces:**
- Consumes: Existing registry YAML `executorBinding.type` and `executorBinding.bindingId`.
- Produces: `CapabilityDefinition.ExecutorBinding` and `CapabilityRequest.technicalOverrideKeys()`.

- [x] **Step 1: Add `ExecutorBinding` to `CapabilityDefinition`**

Add a field before `Governance governance`:

```java
ExecutorBinding executorBinding,
```

Add nested record:

```java
public record ExecutorBinding(String type, String bindingId) {
}
```

Add an overload preserving older test call sites:

```java
public CapabilityDefinition(
        String capabilityId,
        String name,
        String description,
        CapabilityStatus status,
        CapabilityKind kind,
        String domain,
        String businessObject,
        String ontologyIri,
        String semanticType,
        List<InputField> inputs,
        List<OutputField> outputs,
        Executor executor,
        Governance governance
) {
    this(capabilityId, name, description, status, kind, domain, businessObject, ontologyIri, semanticType,
            inputs, outputs, executor, new ExecutorBinding(executor == null ? null : executor.type(), null), governance);
}
```

- [x] **Step 2: Parse `executorBinding` in `CapabilityRegistryLoader`**

In `parseCapability`, pass:

```java
parseExecutorBinding(asMap(raw.get("executorBinding"))),
```

between `parseExecutor(...)` and `parseGovernance(...)`.

Add:

```java
private CapabilityDefinition.ExecutorBinding parseExecutorBinding(Map<String, Object> raw) {
    return new CapabilityDefinition.ExecutorBinding(
            asString(raw.get("type")),
            asString(raw.get("bindingId"))
    );
}
```

If `executorBinding` is absent, derive type from `executor.type` and leave `bindingId` null for backward compatibility only.

- [x] **Step 3: Ensure validator rejects missing binding for active capabilities only if current fixtures allow it**

If `CapabilityRegistryValidator` already validates executor shape, extend it with:

```text
active capability must have executorBinding.bindingId
executorBinding.type must match executor.type
```

Keep disabled or legacy test fixtures compatible only when tests explicitly require old shapes.

- [x] **Step 4: Add `UNSUPPORTED_EXECUTOR` to `ErrorType`**

Add enum value:

```java
UNSUPPORTED_EXECUTOR
```

Place it after `INVALID_PARAMETER` or before SAP-specific errors.

- [x] **Step 5: Add technical override detection to `CapabilityRequest`**

Add:

```java
public java.util.Set<String> technicalOverrideKeys() {
    if (parameters == null) {
        return java.util.Set.of();
    }
    java.util.Set<String> matches = new java.util.LinkedHashSet<>();
    parameters.keySet().forEach(key -> collectTechnicalOverride(matches, key));
    return matches;
}

private static void collectTechnicalOverride(java.util.Set<String> matches, String key) {
    String normalized = key == null ? "" : key.replace("_", "").replace("-", "").toLowerCase();
    if (normalized.equals("rfcname")
            || normalized.contains("serviceurl")
            || normalized.contains("restendpoint")
            || normalized.contains("endpoint")
            || normalized.equals("url")
            || normalized.equals("httpmethod")
            || normalized.equals("method")
            || normalized.equals("headers")
            || normalized.equals("credentialref")
            || normalized.contains("jsonmapping")
            || normalized.equals("rawsql")
            || normalized.equals("sql")
            || normalized.equals("adtpath")
            || normalized.equals("cdsobject")
            || normalized.equals("cdsentity")) {
        matches.add(key);
    }
}
```

- [x] **Step 6: Run registry and API focused tests**

Run:

```bash
cd gateway-jco && /tmp/gradle-8.8/bin/gradle --no-daemon test --tests '*CapabilityRegistryLoaderTest' --tests '*CapabilityExecutionApiTest'
```

Expected after implementation: registry binding tests pass; API override test may still fail until controller rejects overrides in Task 4.

## Task 3: Technical Contract, Dispatcher, Adapter, And Redactor

**Files:**
- Create: `gateway-jco/src/main/java/com/sapnexus/gateway/execution/TechnicalExecutionRequest.java`
- Create: `gateway-jco/src/main/java/com/sapnexus/gateway/execution/TechnicalExecutionResult.java`
- Create: `gateway-jco/src/main/java/com/sapnexus/gateway/execution/TechnicalAdapter.java`
- Create: `gateway-jco/src/main/java/com/sapnexus/gateway/execution/TechnicalExecutionDispatcher.java`
- Create: `gateway-jco/src/main/java/com/sapnexus/gateway/execution/JcoRfcTechnicalAdapter.java`
- Create: `gateway-jco/src/main/java/com/sapnexus/gateway/execution/TechnicalRedactor.java`

**Interfaces:**
- Consumes: `JcoCapabilityExecutor`, `ExecutionResult`, `SapReturnMessage`, `ErrorType`.
- Produces: Internal contract facade and closed dispatcher.

- [x] **Step 1: Add `TechnicalExecutionRequest`**

Create:

```java
package com.sapnexus.gateway.execution;

import java.util.Map;

public record TechnicalExecutionRequest(
        String traceId,
        String capabilityId,
        String bindingId,
        String executorType,
        String operation,
        Map<String, Object> parameters,
        Map<String, Object> constraints,
        Map<String, Object> callerContext
) {
}
```

- [x] **Step 2: Add `TechnicalAdapter`**

Create:

```java
package com.sapnexus.gateway.execution;

public interface TechnicalAdapter {
    TechnicalExecutionResult execute(TechnicalExecutionRequest request);
}
```

- [x] **Step 3: Add `TechnicalExecutionResult` with conversion**

Create static `success`, `failure`, and `toExecutionResult(String rfcName)` methods. The conversion must call:

```java
new ExecutionResult.ExecutorMetadata(executorType, rfcName)
```

and preserve `returnMessages`, `data`, `durationMs`, and `errorType`.

- [x] **Step 4: Add `TechnicalExecutionDispatcher`**

Create a constructor that accepts `Map<String, TechnicalAdapter> adapters` and a `dispatch` method:

```java
public TechnicalExecutionResult dispatch(TechnicalExecutionRequest request) {
    TechnicalAdapter adapter = adapters.get(request.executorType());
    if (adapter == null) {
        return TechnicalExecutionResult.failure(
                request.traceId(),
                request.capabilityId(),
                request.bindingId(),
                request.executorType(),
                ErrorType.UNSUPPORTED_EXECUTOR,
                "Unsupported executor type: " + request.executorType(),
                0
        );
    }
    return adapter.execute(request);
}
```

- [x] **Step 5: Add `JcoRfcTechnicalAdapter`**

Wrap the existing JCo executor:

```java
public class JcoRfcTechnicalAdapter implements TechnicalAdapter {
    private final JcoCapabilityExecutor executor;
    private final CapabilityDefinition capability;

    public JcoRfcTechnicalAdapter(JcoCapabilityExecutor executor, CapabilityDefinition capability) {
        this.executor = executor;
        this.capability = capability;
    }

    @Override
    public TechnicalExecutionResult execute(TechnicalExecutionRequest request) {
        ExecutionResult result = executor.execute(capability, request.parameters(), request.traceId());
        return TechnicalExecutionResult.fromExecutionResult(request.bindingId(), result);
    }
}
```

If dependency injection is cleaner, make the adapter take the capability in the method rather than constructor, but keep the write scope small and update tests accordingly.

- [x] **Step 6: Add `TechnicalRedactor`**

Create package-private static methods:

```java
static Map<String, Object> redactMap(Map<String, Object> input)
static Object redactValue(String key, Object value)
static boolean isSensitiveKey(String key)
```

Make `isSensitiveKey` cover `password`, `passwd`, `token`, `secret`, `credential`, `authorization`, `apikey`, `apiKey`, `destination`, `endpoint`, `url`, `header`, `config`, `env`, `rfcName`, `rawSql`, and `sql`.

- [x] **Step 7: Run execution package tests**

Run:

```bash
cd gateway-jco && /tmp/gradle-8.8/bin/gradle --no-daemon test --tests '*TechnicalExecutionDispatcherTest' --tests '*TechnicalRedactorTest'
```

Expected: PASS.

## Task 4: Controller Integration And Trace Redaction

**Files:**
- Modify: `gateway-jco/src/main/java/com/sapnexus/gateway/api/CapabilityController.java`
- Modify: `gateway-jco/src/main/java/com/sapnexus/gateway/trace/TraceRecord.java`
- Modify: `gateway-jco/src/test/java/com/sapnexus/gateway/api/CapabilityExecutionApiTest.java`
- Modify: `gateway-jco/src/test/java/com/sapnexus/gateway/trace/TraceWriterTest.java` if redaction assertions need stronger coverage.

**Interfaces:**
- Consumes: `CapabilityRequest.technicalOverrideKeys()`, `TechnicalExecutionRequest`, `TechnicalExecutionDispatcher`, `JcoRfcTechnicalAdapter`.
- Produces: API-level execution through the technical contract facade.

- [x] **Step 1: Reject technical overrides before validation/execution**

In `CapabilityController.execute`, before `safeParameters()` or before validation, detect:

```java
java.util.Set<String> technicalOverrides = request == null ? java.util.Set.of() : request.technicalOverrideKeys();
if (!technicalOverrides.isEmpty()) {
    CapabilityResponse response = CapabilityResponse.failure(
            java.util.UUID.randomUUID().toString(),
            capabilityId,
            ErrorType.INVALID_PARAMETER,
            "Technical override fields are not allowed: " + String.join(", ", technicalOverrides)
    );
    writeTrace(response.traceId(), "execute", capabilityId, java.util.Map.of(), false, 0, response.errorType());
    return ResponseEntity.status(statusFor(response.errorType())).body(response);
}
```

Use a helper if this makes the controller easier to read.

- [x] **Step 2: Build and dispatch technical request after validation**

Replace direct `executor.execute(...)` with:

```java
CapabilityDefinition capability = registry.findEnabled(capabilityId).orElseThrow();
TechnicalExecutionRequest technicalRequest = new TechnicalExecutionRequest(
        validation.traceId(),
        capability.capabilityId(),
        capability.executorBinding().bindingId(),
        capability.executorBinding().type(),
        "execute",
        parameters,
        java.util.Map.of("sideEffect", capability.governance().sideEffect().name()),
        java.util.Map.of()
);
TechnicalExecutionDispatcher dispatcher = new TechnicalExecutionDispatcher(java.util.Map.of(
        "JCO_RFC", new JcoRfcTechnicalAdapter(executor, capability)
));
TechnicalExecutionResult technicalResult = dispatcher.dispatch(technicalRequest);
ExecutionResult result = technicalResult.toExecutionResult(capability.executor().rfcName());
```

If creating the dispatcher per request is too noisy, extract a private method in the controller now and leave a Spring bean refactor for a later cleanup.

- [x] **Step 3: Reuse stronger redaction in `TraceRecord`**

Update `TraceRecord.summarize` to use `TechnicalRedactor.redactMap(parameters)` or align its `isUnsafeKey` list with `TechnicalRedactor.isSensitiveKey`.

The trace must omit or mask nested sensitive values, and must not record raw override payload details.

- [x] **Step 4: Run API and trace tests**

Run:

```bash
cd gateway-jco && /tmp/gradle-8.8/bin/gradle --no-daemon test --tests '*CapabilityExecutionApiTest' --tests '*TraceWriterTest'
```

Expected: PASS.

## Task 5: Gateway Regression And Agent Compatibility

**Files:**
- Modify only files required by failing tests from Tasks 1-4.
- Do not edit Python Agent behavior unless a regression proves a compatibility bug in the Java response shape.

**Interfaces:**
- Consumes: Full Gateway test suite and existing Agent evidence suite.
- Produces: Verified compatibility evidence for closeout docs.

- [x] **Step 1: Run full Gateway tests**

Run:

```bash
cd gateway-jco && /tmp/gradle-8.8/bin/gradle --no-daemon test
```

Expected: PASS.

- [x] **Step 2: Run Registry contract validation**

Run:

```bash
.venv/bin/python scripts/validate-registry-contract.py registry/capabilities.yaml
```

Expected output contains:

```text
Registry contract valid: registry/capabilities.yaml
```

- [x] **Step 3: Run Registry Python tests**

Run:

```bash
.venv/bin/python -m pytest agent/tests/test_registry_contract.py -v
```

Expected: all tests pass.

- [x] **Step 4: Run Agent CallPlan/evidence regression**

Run:

```bash
scripts/verify-agent-callplan-evidence.sh
```

Expected: Agent tests and eval pass; OpenSpec validation inside the script passes. Treat PostHog telemetry network errors as non-blocking only if the command exit code is successful and authoritative test output passes.

- [x] **Step 5: Run OpenSpec strict validation**

Run:

```bash
openspec validate --all --strict
```

Expected: all specs pass.

## Task 6: Documentation, Task Checkoff, And Comet Build Guard

**Files:**
- Modify: `openspec/changes/sap-nexus-gateway-execution-contract/tasks.md`
- Modify: `docs/runbooks/05-gateway-execution-contract.md`
- Modify: `docs/runbooks/README.md`
- Modify: `docs/wiki/sap-nexus-agent-implementation-roadmap.md`

**Interfaces:**
- Consumes: Verification evidence from Task 5.
- Produces: Durable runbook/roadmap progress and a build-ready OpenSpec change.

- [x] **Step 1: Update OpenSpec tasks**

Check off completed task lines in `openspec/changes/sap-nexus-gateway-execution-contract/tasks.md` only after each task's tests pass.

- [x] **Step 2: Update Runbook 05**

Set status/current phase from `Planned / Not started` to the verified implementation state. Add a `Session Closeout - 2026-06-28` section with:

```markdown
### Completed

- ...

### Verified

- Command: `...`
- Result: `...`

### Blockers

- None, or exact blocker text.

### Next Start Here

1. ...
```

- [x] **Step 3: Update runbook index**

In `docs/runbooks/README.md`, update the `05` row status/version/date to match Runbook 05.

- [x] **Step 4: Update roadmap stale next-step content**

In `docs/wiki/sap-nexus-agent-implementation-roadmap.md`, update only the sections that still describe Runbook 05 as not started or next recommended work after implementation is verified.

- [x] **Step 5: Run final status and Comet build guard**

Run:

```bash
git status --short
COMET_ENV="${COMET_ENV:-$(find . "$HOME"/.*/skills "$HOME/.config" "$HOME/.gemini" -path '*/comet/scripts/comet-env.sh' -type f -print -quit 2>/dev/null)}"
. "$COMET_ENV"
"$COMET_BASH" "$COMET_GUARD" sap-nexus-gateway-execution-contract build --apply
"$COMET_BASH" "$COMET_STATE" next sap-nexus-gateway-execution-contract
```

Expected: build guard passes, `.comet.yaml` advances to `phase: verify`, and next skill is `comet-verify`.

## Self-Review

- Spec coverage: binding-owned request, closed dispatcher, result compatibility, unsupported executor fail-closed behavior, and technical redaction are covered by Tasks 1-5.
- No placeholders: implementation choices are concrete and scoped to current Java Gateway structure.
- Type consistency: `TechnicalExecutionRequest`, `TechnicalExecutionResult`, `TechnicalAdapter`, `TechnicalExecutionDispatcher`, `JcoRfcTechnicalAdapter`, `TechnicalRedactor`, and `ExecutorBinding` names match the design doc.

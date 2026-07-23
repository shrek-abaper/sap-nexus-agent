---
change: sap-nexus-capability-registry-gateway
design-doc: docs/superpowers/specs/2026-06-19-capability-registry-gateway-design.md
base-ref: 7aec3c1ea319e907b31649ea22f45231adc19862
archived-with: 2026-06-19-sap-nexus-capability-registry-gateway
---

# Capability Registry Gateway Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 建立第一条可运行、可验证、可审计的 SAP capability-level Java JCo Gateway 切片，支持 `MM.Inventory.GetAvailability` 的注册、校验、执行形态、结果归一和 JSONL trace。

**Architecture:** 本计划只实现 Gateway/Registry 边界：`registry/capabilities.yaml` 是运行时 allowlist 和轻量 capability ontology；Spring Boot Gateway 只接受 `capabilityId`，从 Registry 读取 `executor.rfcName`；validate/execute 的输入、输出、trace 都用确定性代码和 schema 约束。SAP JCo 真实连接能力通过 adapter 隔离，fast tests 不依赖 SAP；live smoke 作为单独手工验证。

**Tech Stack:** Java 17 LTS, Spring Boot 3.x, Gradle Wrapper, SnakeYAML, JUnit 5, Spring MVC Test, YAML Registry, JSON Schema contracts, JSONL runtime traces.

archived-with: 2026-06-19-sap-nexus-capability-registry-gateway
---

## Scope Guard

- 本计划不实现 Python Agent、RecommendationPlan、ML reasoning、SAP Write Action、UI、Knowledge Graph runtime。
- Gateway 不允许任意 RFC 执行 endpoint；请求体不得覆盖 `executor.rfcName`。
- 当前项目规则要求不自动创建分支、不自动 commit；若 Comet 后续 guard 要求 commit，必须先取得用户明确确认。
- 当前机器已知 `java -version` 可能是 Java 11；若没有 Java 17，不得静默降级，需先让用户选择安装/切换 JDK 17 或记录临时兼容决策。

## File Map

- Create: `registry/capabilities.yaml` - 首个 capability 的运行时注册定义。
- Create: `schemas/capability.schema.json` - capability 定义契约。
- Create: `schemas/execution-result.schema.json` - Gateway 标准响应契约。
- Modify: `.gitignore` - 忽略 `runtime/` 下生成 trace/callplan/fact/eval/local gateway 输出。
- Create: `gateway-jco/settings.gradle`, `gateway-jco/build.gradle`, `gateway-jco/gradlew`, `gateway-jco/gradlew.bat`, `gateway-jco/gradle/wrapper/*` - Gradle Wrapper Spring Boot 工程。
- Create: `gateway-jco/src/main/resources/application.yml` - registry path 和 trace path 配置。
- Create: `gateway-jco/src/main/java/com/sapnexus/gateway/SapNexusGatewayApplication.java` - 应用入口。
- Create: `gateway-jco/src/main/java/com/sapnexus/gateway/api/*` - REST controllers and DTOs。
- Create: `gateway-jco/src/main/java/com/sapnexus/gateway/registry/*` - registry model/loader/validator。
- Create: `gateway-jco/src/main/java/com/sapnexus/gateway/validation/*` - request validation service and error types。
- Create: `gateway-jco/src/main/java/com/sapnexus/gateway/jco/*` - JCo destination config and executor boundary。
- Create: `gateway-jco/src/main/java/com/sapnexus/gateway/result/*` - ExecutionResult and SAP RETURN normalization。
- Create: `gateway-jco/src/main/java/com/sapnexus/gateway/trace/*` - JSONL trace writer。
- Create: `gateway-jco/src/test/java/com/sapnexus/gateway/**/*Test.java` - fast tests with fake executor, no SAP required。
- Create: `gateway-jco/README.md` - local build/test, SAP/JCo prerequisites, live smoke commands。
- Modify: `openspec/changes/sap-nexus-capability-registry-gateway/tasks.md` - 每个任务验证通过后勾选对应 OpenSpec task。

## Verification Commands

Fast verification, no SAP required:

```bash
cd gateway-jco
./gradlew test
```

Contract/file verification:

```bash
python3 -m json.tool schemas/capability.schema.json >/tmp/capability.schema.check.json
python3 -m json.tool schemas/execution-result.schema.json >/tmp/execution-result.schema.check.json
rg -n "rfcName|MM.Inventory.GetAvailability|BAPI_MATERIAL_AVAILABILITY|CAPABILITY_NOT_FOUND|MISSING_PARAMETER|INVALID_PARAMETER|SAP_BUSINESS_ERROR|BAPI_TRANSACTION_COMMIT|BAPI_TRANSACTION_ROLLBACK" registry schemas gateway-jco openspec/changes/sap-nexus-capability-registry-gateway/tasks.md
```

Live smoke, SAP/JCo required and documented only:

```bash
curl -s http://localhost:8080/health
curl -s http://localhost:8080/capabilities
curl -s -X POST http://localhost:8080/capabilities/MM.Inventory.GetAvailability/validate \
  -H 'Content-Type: application/json' \
  -d '{"parameters":{"material":"MAT-001","plant":"1000","unit":"EA"}}'
```

archived-with: 2026-06-19-sap-nexus-capability-registry-gateway
---

## Task 0: Entry Gate And Tooling Decision

**Files:**
- Read: `AGENTS.md`
- Read: `docs/wiki/sap-nexus-agent-technology-selection.md`
- Read: `docs/superpowers/specs/2026-06-19-capability-registry-gateway-design.md`
- Read: `openspec/changes/sap-nexus-capability-registry-gateway/tasks.md`

- [x] **Step 0.1: Confirm build phase state**

Run:

```bash
git status --short
sed -n '1,80p' openspec/changes/sap-nexus-capability-registry-gateway/.comet.yaml
```

Expected:
- `.comet.yaml` contains `phase: build`.
- Existing user-added `.codex/skills/frontend-design` and `.codex/skills/horizon-design-token` remain untouched.

- [x] **Step 0.2: Confirm Java and Gradle availability**

Run:

```bash
java -version
gradle -v || true
mvn -v || true
```

Expected:
- If Java 17 is available, continue with Spring Boot 3.x.
- If only Java 11 is available, stop before implementation and ask whether to install/switch JDK 17 or explicitly record a temporary Java 11 compatibility decision.
- If neither Gradle nor wrapper is available, request approval for dependency/tool bootstrap or use an approved internal mirror. Do not vendor random binaries.

archived-with: 2026-06-19-sap-nexus-capability-registry-gateway
---

## Task 1: Registry And JSON Contracts

**OpenSpec coverage:** 1.1, 1.2, 1.3, 1.4

**Files:**
- Create: `registry/capabilities.yaml`
- Create: `schemas/capability.schema.json`
- Create: `schemas/execution-result.schema.json`
- Modify: `.gitignore`

- [x] **Step 1.1: Create the capability registry**

Create `registry/capabilities.yaml` with this shape:

```yaml
version: 1
capabilities:
  - capabilityId: MM.Inventory.GetAvailability
    name: Inventory Availability
    description: Read material availability for a plant through SAP BAPI_MATERIAL_AVAILABILITY.
    status: active
    kind: Function
    domain: MM
    businessObject: InventoryStock
    ontologyIri: sapnexus:MM_Inventory_GetAvailability
    semanticType: sapnexus:InventoryAvailabilityReadFunction
    inputs:
      - name: material
        semanticName: materialNumber
        semanticType: sapnexus:MaterialNumber
        required: true
        type: string
        minLength: 1
        maxLength: 40
        sapParameter: MATERIAL
      - name: plant
        semanticName: plant
        semanticType: sapnexus:Plant
        required: true
        type: string
        minLength: 1
        maxLength: 4
        sapParameter: PLANT
      - name: unit
        semanticName: unitOfMeasure
        semanticType: sapnexus:UnitOfMeasure
        required: false
        type: string
        minLength: 1
        maxLength: 3
        sapParameter: UNIT
    outputs:
      - name: availability
        semanticType: sapnexus:AvailableQuantity
        type: object
        evidenceRole: primaryFact
      - name: returnMessages
        semanticType: sapnexus:SapReturnMessage
        type: array
        evidenceRole: executionEvidence
    executor:
      type: JCO_RFC
      rfcName: BAPI_MATERIAL_AVAILABILITY
      inputMapping:
        material: MATERIAL
        plant: PLANT
        unit: UNIT
      outputMapping:
        returnMessages: RETURN
    governance:
      sideEffect: none
      requiresApproval: false
      approvalPolicy: not_required
      dataClassification: internal
      auditRequired: true
```

- [x] **Step 1.2: Add JSON Schema for capabilities**

Create `schemas/capability.schema.json` with required object sections: `capabilityId`, `status`, `kind`, `domain`, `businessObject`, `ontologyIri`, `semanticType`, `inputs`, `outputs`, `executor`, `governance`. Include enums:

```json
{
  "status": { "enum": ["active", "disabled"] },
  "kind": { "enum": ["Function", "Action"] },
  "sideEffect": { "enum": ["none", "read", "write"] },
  "approvalPolicy": { "enum": ["not_required", "human_required"] }
}
```

Implementation detail:
- The final schema must be valid JSON, not the abbreviated example above.
- `executor.rfcName` is required in the registry schema, but it must not be accepted from Gateway request payloads.

- [x] **Step 1.3: Add JSON Schema for ExecutionResult**

Create `schemas/execution-result.schema.json` with these required top-level fields:

```json
[
  "traceId",
  "capabilityId",
  "success",
  "executor",
  "returnMessages",
  "data",
  "durationMs",
  "errorType"
]
```

Error type enum must include:

```json
[
  "NONE",
  "CAPABILITY_NOT_FOUND",
  "CAPABILITY_DISABLED",
  "MISSING_PARAMETER",
  "INVALID_PARAMETER",
  "SAP_BUSINESS_ERROR",
  "SAP_AUTH_ERROR",
  "SAP_COMMUNICATION_ERROR",
  "NORMALIZATION_ERROR"
]
```

- [x] **Step 1.4: Ignore generated runtime outputs**

Modify `.gitignore` to include:

```gitignore
# SAP Nexus generated runtime artifacts
runtime/
!runtime/.gitkeep
```

If a tracked placeholder is useful, create `runtime/.gitkeep`; do not commit generated trace files.

- [x] **Step 1.5: Verify contracts**

Run:

```bash
python3 -m json.tool schemas/capability.schema.json >/tmp/capability.schema.check.json
python3 -m json.tool schemas/execution-result.schema.json >/tmp/execution-result.schema.check.json
rg -n "MM.Inventory.GetAvailability|BAPI_MATERIAL_AVAILABILITY|ontologyIri|semanticType|requiresApproval|sideEffect" registry schemas .gitignore
```

Expected:
- JSON schema files parse successfully.
- Registry contains the canonical capability and future OWL migration fields.
- `.gitignore` ignores generated runtime output.

archived-with: 2026-06-19-sap-nexus-capability-registry-gateway
---

## Task 2: Spring Boot Gateway Skeleton

**OpenSpec coverage:** 2.1, 2.2, 2.3, 2.4

**Files:**
- Create: `gateway-jco/settings.gradle`
- Create: `gateway-jco/build.gradle`
- Create: `gateway-jco/src/main/resources/application.yml`
- Create: `gateway-jco/src/main/java/com/sapnexus/gateway/SapNexusGatewayApplication.java`
- Create: `gateway-jco/src/main/java/com/sapnexus/gateway/api/HealthController.java`
- Create: `gateway-jco/src/main/java/com/sapnexus/gateway/api/HealthResponse.java`
- Create: `gateway-jco/src/test/java/com/sapnexus/gateway/api/HealthControllerTest.java`
- Create: `gateway-jco/README.md`

- [x] **Step 2.1: Bootstrap Gradle project**

Preferred `gateway-jco/build.gradle` baseline:

```groovy
plugins {
    id 'java'
    id 'org.springframework.boot' version '3.3.6'
    id 'io.spring.dependency-management' version '1.1.6'
}

group = 'com.sapnexus'
version = '0.1.0-SNAPSHOT'

java {
    toolchain {
        languageVersion = JavaLanguageVersion.of(17)
    }
}

repositories {
    mavenCentral()
}

dependencies {
    implementation 'org.springframework.boot:spring-boot-starter-web'
    implementation 'org.springframework.boot:spring-boot-starter-validation'
    implementation 'org.yaml:snakeyaml:2.2'
    testImplementation 'org.springframework.boot:spring-boot-starter-test'
}

tasks.named('test') {
    useJUnitPlatform()
}
```

If Gradle wrapper cannot be generated because Gradle/network is unavailable, stop and report the exact blocker before editing around it.

- [x] **Step 2.2: Add application config**

Create `gateway-jco/src/main/resources/application.yml`:

```yaml
server:
  port: 8080
sapnexus:
  registry:
    path: ../registry/capabilities.yaml
  trace:
    path: ../runtime/gateway-jco/traces.jsonl
```

- [x] **Step 2.3: Add application entrypoint**

Create `SapNexusGatewayApplication.java`:

```java
package com.sapnexus.gateway;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

@SpringBootApplication
public class SapNexusGatewayApplication {
    public static void main(String[] args) {
        SpringApplication.run(SapNexusGatewayApplication.class, args);
    }
}
```

- [x] **Step 2.4: Add health API without secrets**

Create `HealthResponse` fields: `status`, `gateway`, `jcoConfigured`, `sapEnvironmentPresent`, `sensitiveFieldsExposed`.

Expected response shape:

```json
{
  "status": "UP",
  "gateway": "sap-nexus-jco-gateway",
  "jcoConfigured": false,
  "sapEnvironmentPresent": false,
  "sensitiveFieldsExposed": false
}
```

- [x] **Step 2.5: Add README**

`gateway-jco/README.md` must include:
- Fast test command: `./gradlew test`
- Local run command: `./gradlew bootRun`
- Required SAP env vars: `SAP_ASHOST`, `SAP_SYSNR`, `SAP_CLIENT`, `SAP_USER`, `SAP_PASSWORD`, `SAP_LANG`, optional `SAP_SAPROUTER`, optional `SAP_JCO_LIB_PATH`
- Statement that fast tests do not require SAP.
- Statement that live execute requires SAP env + JCo native library.

- [x] **Step 2.6: Verify skeleton**

Run:

```bash
cd gateway-jco
./gradlew test
```

Expected:
- `HealthControllerTest` passes.
- No health response includes password or full destination config.

archived-with: 2026-06-19-sap-nexus-capability-registry-gateway
---

## Task 3: Registry Loader And Registry Validation

**OpenSpec coverage:** 3.1, 3.2, 3.3, 3.4

**Files:**
- Create: `gateway-jco/src/main/java/com/sapnexus/gateway/registry/CapabilityDefinition.java`
- Create: `gateway-jco/src/main/java/com/sapnexus/gateway/registry/CapabilityRegistry.java`
- Create: `gateway-jco/src/main/java/com/sapnexus/gateway/registry/CapabilityRegistryLoader.java`
- Create: `gateway-jco/src/main/java/com/sapnexus/gateway/registry/CapabilityRegistryValidator.java`
- Create: `gateway-jco/src/main/java/com/sapnexus/gateway/api/CapabilityController.java`
- Create: `gateway-jco/src/test/java/com/sapnexus/gateway/registry/CapabilityRegistryLoaderTest.java`
- Create: `gateway-jco/src/test/resources/registry/*.yaml`

- [x] **Step 3.1: Add registry model**

Model must include nested records/classes for identity, inputs, outputs, executor, governance. Minimal enum names:

```java
public enum CapabilityKind { Function, Action }
public enum CapabilityStatus { active, disabled }
public enum SideEffect { none, read, write }
```

- [x] **Step 3.2: Add loader from YAML path**

`CapabilityRegistryLoader` behavior:
- Reads the configured YAML file.
- Parses `version` and `capabilities`.
- Validates before exposing any capability.
- Returns enabled capabilities separately from all parsed capabilities.

- [x] **Step 3.3: Add validation rules**

`CapabilityRegistryValidator` must reject:
- missing `capabilityId`, `kind`, `status`, `inputs`, `outputs`, `executor.rfcName`, or `governance`
- duplicate `capabilityId`
- invalid `kind`
- `Function` with `governance.sideEffect` not equal to `none`
- `Action` with `requiresApproval: false`

- [x] **Step 3.4: Add `GET /capabilities` from registry**

Response fields must include: `capabilityId`, `kind`, `domain`, `businessObject`, `ontologyIri`, `executor.type`, `governance.sideEffect`, `governance.requiresApproval`. It may omit raw `executor.rfcName` if API design prefers not to expose RFC internals, but controller must not hardcode the response.

- [x] **Step 3.5: Add registry tests**

Test names:

```java
loadsActiveInventoryAvailabilityCapability()
rejectsMalformedRegistryEntry()
rejectsDuplicateCapabilityIds()
excludesDisabledCapabilitiesFromCatalog()
rejectsFunctionWithSideEffect()
rejectsActionWithoutHumanApproval()
```

- [x] **Step 3.6: Verify registry behavior**

Run:

```bash
cd gateway-jco
./gradlew test --tests '*CapabilityRegistry*'
```

Expected:
- Valid registry loads.
- Malformed/duplicate/governance-invalid registry fails before exposure.
- Disabled capabilities are not listed by `GET /capabilities`.

archived-with: 2026-06-19-sap-nexus-capability-registry-gateway
---

## Task 4: Validate API And No-JCo-On-Validation-Failure

**OpenSpec coverage:** 4.1, 4.2

**Files:**
- Create: `gateway-jco/src/main/java/com/sapnexus/gateway/api/CapabilityRequest.java`
- Create: `gateway-jco/src/main/java/com/sapnexus/gateway/api/CapabilityResponse.java`
- Create: `gateway-jco/src/main/java/com/sapnexus/gateway/validation/CapabilityValidationService.java`
- Create: `gateway-jco/src/main/java/com/sapnexus/gateway/result/ErrorType.java`
- Create: `gateway-jco/src/test/java/com/sapnexus/gateway/api/CapabilityValidationApiTest.java`

- [x] **Step 4.1: Define validate request shape**

Request shape:

```json
{
  "parameters": {
    "material": "MAT-001",
    "plant": "1000",
    "unit": "EA"
  }
}
```

Do not include `rfcName` in accepted DTOs. If a payload contains `rfcName`, ignore it or reject it as an unknown field; it must never override Registry executor mapping.

- [x] **Step 4.2: Implement validation result**

Successful validation returns:

```json
{
  "traceId": "<uuid>",
  "capabilityId": "MM.Inventory.GetAvailability",
  "success": true,
  "errorType": "NONE",
  "messages": []
}
```

Failure returns one of:
- `CAPABILITY_NOT_FOUND`
- `CAPABILITY_DISABLED`
- `MISSING_PARAMETER`
- `INVALID_PARAMETER`

- [x] **Step 4.3: Implement required and constraint validation**

Rules for first capability:
- `material` required, string length 1..40
- `plant` required, string length 1..4
- `unit` optional, string length 1..3

- [x] **Step 4.4: Add tests ensuring validation failure does not invoke JCo**

Use a fake executor bean with an invocation counter. Tests:

```java
unknownCapabilityReturnsCapabilityNotFoundAndDoesNotInvokeExecutor()
missingMaterialReturnsMissingParameterAndDoesNotInvokeExecutor()
invalidPlantReturnsInvalidParameterAndDoesNotInvokeExecutor()
validRequestReturnsSuccessWithTraceId()
```

- [x] **Step 4.5: Verify validate API**

Run:

```bash
cd gateway-jco
./gradlew test --tests '*CapabilityValidationApiTest'
```

Expected:
- Invalid validation cases do not call executor.
- Responses are structured, not generic failures.

archived-with: 2026-06-19-sap-nexus-capability-registry-gateway
---

## Task 5: Execute API, JCo Boundary, And Result Normalization

**OpenSpec coverage:** 4.3, 4.4, 5.1, 5.2, 5.3, 5.4, 5.5

**Files:**
- Create: `gateway-jco/src/main/java/com/sapnexus/gateway/jco/JcoDestinationProperties.java`
- Create: `gateway-jco/src/main/java/com/sapnexus/gateway/jco/JcoCapabilityExecutor.java`
- Create: `gateway-jco/src/main/java/com/sapnexus/gateway/jco/InventoryAvailabilityExecutor.java`
- Create: `gateway-jco/src/main/java/com/sapnexus/gateway/result/ExecutionResult.java`
- Create: `gateway-jco/src/main/java/com/sapnexus/gateway/result/SapReturnMessage.java`
- Create: `gateway-jco/src/main/java/com/sapnexus/gateway/result/SapReturnNormalizer.java`
- Create: `gateway-jco/src/test/java/com/sapnexus/gateway/api/CapabilityExecutionApiTest.java`
- Create: `gateway-jco/src/test/java/com/sapnexus/gateway/result/SapReturnNormalizerTest.java`

- [x] **Step 5.1: Add destination environment reader without logging secrets**

Read these env vars:

```text
SAP_ASHOST
SAP_SYSNR
SAP_CLIENT
SAP_USER
SAP_PASSWORD
SAP_LANG
SAP_SAPROUTER
SAP_JCO_LIB_PATH
```

Expose only readiness booleans and non-sensitive missing-key names. Never serialize `SAP_PASSWORD` or full connection string.

- [x] **Step 5.2: Define executor interface**

Use a capability-level interface:

```java
public interface JcoCapabilityExecutor {
    ExecutionResult execute(CapabilityDefinition capability, Map<String, Object> parameters, String traceId);
}
```

Implementation must read `capability.executor.rfcName` from Registry. It must not accept caller-provided `rfcName`.

- [x] **Step 5.3: Implement inventory executor mapping**

For `MM.Inventory.GetAvailability`, map Registry inputs to BAPI params:

```text
material -> MATERIAL
plant    -> PLANT
unit     -> UNIT
```

Target RFC:

```text
BAPI_MATERIAL_AVAILABILITY
```

If JCo Java dependency is not available yet, keep SAP invocation behind an adapter and use fake executor in tests; document live JCo completion boundary in README. Do not expose arbitrary RFC fallback.

- [x] **Step 5.4: Normalize SAP RETURN**

Map SAP `RETURN.TYPE`:
- `S` / `I` / `W` -> success unless no business data is available and contract requires it
- `E` / `A` -> `SAP_BUSINESS_ERROR`

Normalized message fields:

```json
{
  "type": "E",
  "id": "M3",
  "number": "001",
  "message": "Material not found",
  "field": "MATERIAL"
}
```

- [x] **Step 5.5: Ensure READ execution does not commit or rollback**

Add a source-level and test-level guard:

```bash
rg -n "BAPI_TRANSACTION_COMMIT|BAPI_TRANSACTION_ROLLBACK" gateway-jco/src || true
```

Expected: no matches in Gateway source.

- [x] **Step 5.6: Verify execute API**

Run:

```bash
cd gateway-jco
./gradlew test --tests '*CapabilityExecutionApiTest' --tests '*SapReturnNormalizerTest'
rg -n "POST /rfc|rfcName.*Request|BAPI_TRANSACTION_COMMIT|BAPI_TRANSACTION_ROLLBACK" src || true
```

Expected:
- Valid execute request validates before fake execution.
- Unknown/missing/invalid execute requests do not invoke executor.
- No arbitrary RFC route exists.
- No commit/rollback calls exist for READ Function.

archived-with: 2026-06-19-sap-nexus-capability-registry-gateway
---

## Task 6: JSONL Trace Emission

**OpenSpec coverage:** 6.1, 6.2

**Files:**
- Create: `gateway-jco/src/main/java/com/sapnexus/gateway/trace/TraceRecord.java`
- Create: `gateway-jco/src/main/java/com/sapnexus/gateway/trace/TraceWriter.java`
- Create: `gateway-jco/src/test/java/com/sapnexus/gateway/trace/TraceWriterTest.java`
- Modify: validate and execute services/controllers to call `TraceWriter`

- [x] **Step 6.1: Define trace record fields**

Trace record must include:

```json
{
  "traceId": "<uuid>",
  "timestamp": "<iso-8601>",
  "operation": "validate|execute",
  "capabilityId": "MM.Inventory.GetAvailability",
  "parameterSummary": {"material":"***","plant":"1000","unit":"EA"},
  "success": true,
  "durationMs": 12,
  "errorType": "NONE"
}
```

Parameter summary must avoid secrets and should mask or summarize business identifiers when appropriate.

- [x] **Step 6.2: Implement append-only JSONL writer**

Behavior:
- Creates parent directory under configured `runtime/` path.
- Appends one JSON object per line.
- Does not write `.env`, SAP destination properties, passwords, tokens, or raw environment dumps.

- [x] **Step 6.3: Add trace tests**

Tests:

```java
validateWritesTraceRecordWithRequiredFields()
executeWritesTraceRecordForSuccessAndFailure()
traceDoesNotContainPasswordOrSapDestinationDetails()
```

- [x] **Step 6.4: Verify trace behavior**

Run:

```bash
cd gateway-jco
./gradlew test --tests '*TraceWriterTest'
rg -n "SAP_PASSWORD|password|\.env|SAP_ASHOST" ../runtime gateway-jco/build || true
```

Expected:
- Trace tests pass.
- Generated trace fixtures do not contain secrets.

archived-with: 2026-06-19-sap-nexus-capability-registry-gateway
---

## Task 7: Documentation, Smoke Commands, And OpenSpec Task Sync

**OpenSpec coverage:** 6.3, 6.4, 6.5 and all task checkboxes

**Files:**
- Modify: `gateway-jco/README.md`
- Modify: `docs/runbooks/01-capability-registry-gateway.md` or create a new numbered workstream runbook if state has materially changed
- Modify: `openspec/changes/sap-nexus-capability-registry-gateway/tasks.md`

- [x] **Step 7.1: Document fast verification**

README must include:

```bash
cd gateway-jco
./gradlew test
```

And explain: fast tests do not require SAP connectivity.

- [x] **Step 7.2: Document live SAP smoke separately**

README must include prerequisites and commands:

```bash
export SAP_ASHOST=...
export SAP_SYSNR=...
export SAP_CLIENT=...
export SAP_USER=...
export SAP_PASSWORD=...
export SAP_LANG=ZH
export SAP_JCO_LIB_PATH=/path/to/libsapjco3.so
./gradlew bootRun
curl -s http://localhost:8080/health
curl -s http://localhost:8080/capabilities
curl -s -X POST http://localhost:8080/capabilities/MM.Inventory.GetAvailability/validate \
  -H 'Content-Type: application/json' \
  -d '{"parameters":{"material":"MAT-001","plant":"1000","unit":"EA"}}'
```

Use placeholders only; never write real credentials.

- [x] **Step 7.3: Run full fast verification**

Run:

```bash
python3 -m json.tool schemas/capability.schema.json >/tmp/capability.schema.check.json
python3 -m json.tool schemas/execution-result.schema.json >/tmp/execution-result.schema.check.json
cd gateway-jco
./gradlew test
```

Expected:
- JSON schemas parse.
- Gateway unit tests pass.

- [x] **Step 7.4: Check safety invariants**

Run from repo root:

```bash
rg -n "POST /rfc|/rfc/|request.*rfcName|BAPI_TRANSACTION_COMMIT|BAPI_TRANSACTION_ROLLBACK|SAP_PASSWORD=.*|BEGIN RSA|BEGIN OPENSSH|password:" . --glob '!node_modules/**' --glob '!runtime/**'
```

Expected:
- No arbitrary RFC route.
- No commit/rollback for READ Function.
- No real credentials or private keys.
- `password:` may appear only in documentation as placeholder guidance, not real values.

- [x] **Step 7.5: Mark OpenSpec tasks only after evidence exists**

For each OpenSpec checkbox in `openspec/changes/sap-nexus-capability-registry-gateway/tasks.md`, mark complete only when its implementation exists and the nearest verification command has passed. Do not mark 6.5 complete until full fast verification has been run and result is recorded in the final response or runbook.

- [x] **Step 7.6: Prepare for review and Comet build guard**

Before running Comet build guard:
- Use `requesting-code-review` skill if `build_mode: executing-plans`.
- Ask user before any git commit if commits are required by Comet guard.
- Then run:

```bash
COMET_ENV="${COMET_ENV:-$(find . "$HOME"/.*/skills "$HOME/.config" "$HOME/.gemini" -path '*/comet/scripts/comet-env.sh' -type f -print -quit 2>/dev/null)}"
. "$COMET_ENV"
"$COMET_BASH" "$COMET_GUARD" sap-nexus-capability-registry-gateway build --apply
"$COMET_BASH" "$COMET_STATE" next sap-nexus-capability-registry-gateway
```

Expected:
- Build guard advances `.comet.yaml` to `phase: verify` only after all required tasks and verification evidence are present.

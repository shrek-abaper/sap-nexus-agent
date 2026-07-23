# Comet Design Handoff

- Change: sap-nexus-capability-registry-gateway
- Phase: design
- Mode: compact
- Context hash: 0017e63bf3cba355b88dab1662697a8513b907521821969a8deb5aacf83f2095

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/sap-nexus-capability-registry-gateway/proposal.md

- Source: openspec/changes/sap-nexus-capability-registry-gateway/proposal.md
- Lines: 1-33
- SHA256: 899e50f13ba5449b0f29fdfcaa738887d173137b399d9111dc193f8672116d03

```md
## Why

SAP Nexus Agent 已确认 JCo/SAP 连通不是首要风险；当前需要把已验证的 JCo 访问能力封装为受控、可审计、可复用的 SAP capability execution boundary。该变更建立第一层工程骨架：轻量 Capability Registry、跨语言契约、Java JCo Gateway Harness、validate/execute API 和 JSONL trace，为后续 Inventory Read Function、Python Agent、ReasoningFact 和 Action Governance 提供稳定基础。

## What Changes

- 新增轻量 Capability Registry，使用 `registry/capabilities.yaml` 注册首个 read Function：`MM.Inventory.GetAvailability`。
- 新增 capability contract/schema，要求 capability 定义包含 `capabilityId`、`ontologyIri`、`kind`、input/output、executor、governance、side effect 和 approval policy。
- 新增 Java JCo Gateway 工程骨架，默认技术路线为 Spring Boot + Gradle Wrapper，作为长期 Gateway 框架。
- 新增 capability-level Gateway API：`GET /health`、`GET /capabilities`、`POST /capabilities/{capabilityId}/validate`、`POST /capabilities/{capabilityId}/execute`。
- Gateway 必须只接受注册 `capabilityId`，不得暴露任意 `rfcName` 执行入口。
- validate 必须在 SAP 执行前拦截未知 capability、disabled capability、缺参和非法参数。
- execute 必须通过 Registry 将 `capabilityId` 映射到 BAPI/RFC executor，并返回标准 `ExecutionResult` 形态。
- 新增 JSONL trace 输出约定，用于记录 capability execution 的 `traceId`、capability、参数摘要、结果状态、duration 和 errorType。
- 明确本 change 不实现完整 Python Agent、RecommendationPlan、ML 推理、SAP Write Action、Knowledge Graph runtime 或 UI。

## Capabilities

### New Capabilities

- `capability-registry-gateway`: Defines the lightweight capability registry and Java Gateway behavior for registered SAP capability validation, execution, and trace emission.

### Modified Capabilities

- None.

## Impact

- 新增工程目录：`gateway-jco/`、`registry/`、`schemas/`、`runtime/`。
- 新增 OpenSpec capability spec：`openspec/changes/sap-nexus-capability-registry-gateway/specs/capability-registry-gateway/spec.md`。
- Gateway 技术栈采用 Spring Boot + Gradle Wrapper，目标 Java 17 LTS；当前本机 Java 11 需要在实施前配置 JDK 17 或记录临时兼容策略。
- 首次构建可能需要下载 Gradle/Spring 依赖；受限网络下需使用审批网络或内部镜像。
- 不改变现有 docs/wiki 架构基线，只按该基线进入首个 implementation change。
```

## openspec/changes/sap-nexus-capability-registry-gateway/design.md

- Source: openspec/changes/sap-nexus-capability-registry-gateway/design.md
- Lines: 1-134
- SHA256: e24a9f183ab59edc40a7d51e7ee3d0dd839332fbe1e9fd4bef9a964c49f5046e

[TRUNCATED]

```md
## Context

SAP Nexus Agent has a product architecture baseline and technology selection baseline. The next implementation slice is not proving whether JCo can connect to SAP; that integration path is treated as validated. The objective is to wrap JCo access in a governed capability execution boundary that future Python Agent, reasoning, approval, and replay layers can reuse.

Current repository state is documentation-first. There is no Gateway source tree, Registry, schema directory, or runtime trace structure yet. The first implementation change must establish those boundaries without pulling in the full Python Agent, RecommendationPlan, SAP Write Action, ML reasoning, or knowledge graph runtime.

Key constraints:

- Work on the current branch; do not create branches or worktrees.
- Gateway exposes `capabilityId`, not arbitrary `rfcName`.
- MVP uses YAML/JSON Registry as the lightweight runtime capability ontology.
- The first read Function is `MM.Inventory.GetAvailability`, backed by `BAPI_MATERIAL_AVAILABILITY`.
- Target technology is Spring Boot + Gradle Wrapper + Java 17 LTS, while the current local Java check showed Java 11.
- Runtime output must stay out of git unless intentionally added as fixtures.

## Goals / Non-Goals

**Goals:**

- Create the first lightweight Capability Registry and schema contract.
- Scaffold a Java JCo Gateway service using Spring Boot and Gradle Wrapper.
- Provide capability-level APIs for health, capability listing, validation, and execution.
- Enforce Registry allowlist semantics and reject unknown capability IDs.
- Validate required parameters before any SAP JCo execution.
- Normalize SAP execution output into an `ExecutionResult` shape.
- Emit JSONL trace records for validation/execution outcomes without secrets.
- Document local verification commands and live SAP smoke prerequisites.

**Non-Goals:**

- Do not implement the complete Python Agent orchestration.
- Do not implement RecommendationPlan, deterministic reasoning, or ML reasoning.
- Do not implement SAP Write Action or Human Approval execution.
- Do not add knowledge graph, Jena, Neo4j, Ontop, or GraphDB runtime dependencies.
- Do not expose arbitrary RFC execution.
- Do not introduce a production database for trace storage.

## Decisions

### Use Spring Boot for `gateway-jco/`

Use Spring Boot as the Gateway framework, with Gradle Wrapper as the build entrypoint.

Rationale:

- Gateway is a long-running production service boundary, not a throwaway demo endpoint.
- Spring Boot gives mature HTTP controller, validation, JSON serialization, profile, testing, health check, and future observability patterns.
- Gradle Wrapper avoids reliance on a global Gradle installation.

Alternatives considered:

- Javalin: lighter and easier under Java 11, but weaker for long-term production governance and observability.
- Quarkus/Micronaut: strong cloud-native options, but not necessary for this SAP On-Prem Gateway slice and require additional JCo compatibility confidence.

Implementation note:

- Default target is Java 17 and Spring Boot 3.x.
- If JDK 17 cannot be configured during build, any temporary Java 11 / Spring Boot 2.7 compatibility decision must be recorded in the change before implementation proceeds.

### Use YAML Registry as early lightweight ontology

Use `registry/capabilities.yaml` as the Gateway allowlist and capability metadata source.

Rationale:

- Matches the architecture decision to avoid knowledge graph runtime in MVP.
- Keeps capability metadata reviewable and versioned.
- Provides a future migration path to OWL / Graph Registry through `ontologyIri` and semantic field metadata.

The Registry entry for `MM.Inventory.GetAvailability` must include identity, status, `kind`, semantic metadata, inputs, outputs, executor mapping, and governance metadata.

### Use schemas for contracts

Use `schemas/` for shared JSON Schema contracts where practical, starting with capability and execution result contracts.

Rationale:

- Prevents Java, Python, prompts, docs, and evals from drifting into separate JSON shapes.
- Makes Agent-facing behavior testable before the full Agent exists.

```

Full source: openspec/changes/sap-nexus-capability-registry-gateway/design.md

## openspec/changes/sap-nexus-capability-registry-gateway/tasks.md

- Source: openspec/changes/sap-nexus-capability-registry-gateway/tasks.md
- Lines: 1-43
- SHA256: 9a14f882ff1434674aaa1e140b7675aaaee4466ec8e29b466d232310c18e6848

```md
## 1. Registry And Contracts

- [ ] 1.1 Create `registry/capabilities.yaml` with `MM.Inventory.GetAvailability` as an active `Function` mapped to `BAPI_MATERIAL_AVAILABILITY`.
- [ ] 1.2 Add `schemas/capability.schema.json` covering identity, kind, status, semantic metadata, inputs, outputs, executor, governance, side effects, and approval policy.
- [ ] 1.3 Add `schemas/execution-result.schema.json` for normalized Gateway responses including traceId, capabilityId, executor metadata, return messages, data, duration, success state, and error type.
- [ ] 1.4 Add generated runtime output ignore rules for traces, callplans, facts, eval results, and local Gateway runtime files.

## 2. Java Gateway Skeleton

- [ ] 2.1 Create `gateway-jco/` Spring Boot + Gradle Wrapper project structure targeting Java 17, or document a temporary Java 11 compatibility decision before implementation.
- [ ] 2.2 Add Gateway README with build/test commands, local SAP/JCo prerequisites, and live smoke test prerequisites.
- [ ] 2.3 Add application package structure for API, capability registry, validation, JCo adapter, result normalization, and trace emission.
- [ ] 2.4 Implement `GET /health` returning Gateway/JCo readiness fields without exposing SAP credentials or sensitive destination details.

## 3. Capability Registry Loading And Validation

- [ ] 3.1 Implement Registry loader that reads `registry/capabilities.yaml` and exposes enabled capabilities in memory.
- [ ] 3.2 Implement registry validation for required fields, duplicate capability IDs, valid kind, Function side-effect constraints, and Action approval constraints.
- [ ] 3.3 Implement `GET /capabilities` returning enabled registered capabilities from the Registry rather than hardcoded controller data.
- [ ] 3.4 Add tests for valid registry load, malformed registry rejection, duplicate capability IDs, and disabled capability exclusion.

## 4. Validate And Execute APIs

- [ ] 4.1 Implement `POST /capabilities/{capabilityId}/validate` with unknown capability, disabled capability, missing required parameter, and invalid parameter handling.
- [ ] 4.2 Ensure validation failures return structured error types and never invoke SAP JCo.
- [ ] 4.3 Implement `POST /capabilities/{capabilityId}/execute` for registered READ Functions, including validate-before-execute behavior.
- [ ] 4.4 Ensure the Gateway has no arbitrary RFC execution endpoint and does not allow request payloads to override `executor.rfcName`.

## 5. JCo Execution And Result Normalization

- [ ] 5.1 Implement JCo destination configuration using SAP environment variable conventions and `SAP_JCO_LIB_PATH` support.
- [ ] 5.2 Implement `MM.Inventory.GetAvailability` executor path that maps Registry inputs to `BAPI_MATERIAL_AVAILABILITY` parameters.
- [ ] 5.3 Normalize SAP `RETURN` messages and map SAP business, auth, and communication failures to structured error types.
- [ ] 5.4 Return normalized `ExecutionResult` without SAP credentials, full destination details, or sensitive environment values.
- [ ] 5.5 Ensure READ Function execution does not call `BAPI_TRANSACTION_COMMIT` or `BAPI_TRANSACTION_ROLLBACK`.

## 6. Trace And Verification

- [ ] 6.1 Implement JSONL trace emission for validate and execute operations under an ignored runtime path.
- [ ] 6.2 Add tests or checks confirming trace records include traceId, operation, capabilityId, parameter summary, success, duration, and errorType while excluding secrets.
- [ ] 6.3 Add fast verification commands for schema/registry validation and Gateway unit tests.
- [ ] 6.4 Add documented live SAP smoke commands for `/health`, `/capabilities`, validate, and execute, separated from fast tests.
- [ ] 6.5 Run the relevant verification commands and record results before marking this change ready for verify.
```

## openspec/changes/sap-nexus-capability-registry-gateway/specs/capability-registry-gateway/spec.md

- Source: openspec/changes/sap-nexus-capability-registry-gateway/specs/capability-registry-gateway/spec.md
- Lines: 1-79
- SHA256: 8efb23eea70f94e70a9c29af05f1fa490ab909229ca2baabd11611766e5ca704

```md
## ADDED Requirements

### Requirement: Capability registry source of truth
The system SHALL provide a lightweight capability registry as the runtime source of truth for executable SAP capabilities.

#### Scenario: Load active capability from registry
- **WHEN** the Gateway starts with a valid `registry/capabilities.yaml` containing an active `MM.Inventory.GetAvailability` Function
- **THEN** the Gateway capability catalog includes `MM.Inventory.GetAvailability` with its kind, domain, business object, executor type, and governance metadata

#### Scenario: Reject malformed registry entry
- **WHEN** a capability registry entry is missing required identity, executor, input, output, or governance fields
- **THEN** registry validation fails with a structured validation error and the malformed capability is not exposed for execution

### Requirement: Capability-level Gateway API
The system SHALL expose SAP execution through capability-level Gateway APIs and MUST NOT expose arbitrary RFC execution.

#### Scenario: List registered capabilities
- **WHEN** a client calls `GET /capabilities`
- **THEN** the Gateway returns only enabled registered capabilities and does not require or expose raw SAP RFC names as callable endpoints

#### Scenario: Reject unknown capability
- **WHEN** a client calls validate or execute for an unregistered `capabilityId`
- **THEN** the Gateway returns `CAPABILITY_NOT_FOUND` and does not invoke SAP JCo

#### Scenario: No arbitrary RFC endpoint
- **WHEN** the Gateway API surface is inspected
- **THEN** there is no endpoint that allows a caller to submit an arbitrary `rfcName` for execution

### Requirement: Validate before execute
The system SHALL validate capability identity, status, required parameters, parameter constraints, and governance rules before SAP execution.

#### Scenario: Missing required parameter is blocked
- **WHEN** a client validates `MM.Inventory.GetAvailability` without required `material` or `plant`
- **THEN** the Gateway returns `MISSING_PARAMETER` and does not invoke SAP JCo

#### Scenario: Invalid parameter is blocked
- **WHEN** a client validates `MM.Inventory.GetAvailability` with a parameter that violates the registry constraints
- **THEN** the Gateway returns `INVALID_PARAMETER` and does not invoke SAP JCo

#### Scenario: Valid read capability passes validation
- **WHEN** a client validates `MM.Inventory.GetAvailability` with valid `material`, `plant`, and optional `unit`
- **THEN** the Gateway returns a successful validation result that includes the `traceId` and selected `capabilityId`

### Requirement: Execute registered SAP read capability
The system SHALL execute registered READ Functions through SAP JCo and return a normalized `ExecutionResult`.

#### Scenario: Execute inventory availability capability
- **WHEN** a client executes `MM.Inventory.GetAvailability` with valid parameters
- **THEN** the Gateway maps the registered `capabilityId` to `BAPI_MATERIAL_AVAILABILITY`, invokes SAP through JCo, and returns an `ExecutionResult` containing `traceId`, `capabilityId`, executor metadata, normalized return messages, data, duration, and success state

#### Scenario: READ capability does not commit
- **WHEN** the Gateway executes a READ Function
- **THEN** it does not call `BAPI_TRANSACTION_COMMIT` or `BAPI_TRANSACTION_ROLLBACK`

#### Scenario: SAP business error is normalized
- **WHEN** SAP returns an error or abort message for a registered capability execution
- **THEN** the Gateway returns a failed `ExecutionResult` with `SAP_BUSINESS_ERROR` and normalized SAP return messages

### Requirement: Trace capability validation and execution
The system SHALL emit replayable JSONL trace records for capability validation and execution without leaking sensitive SAP configuration.

#### Scenario: Execute writes trace record
- **WHEN** a capability execute call completes successfully or unsuccessfully
- **THEN** the Gateway appends a JSONL trace record containing `traceId`, timestamp, capabilityId, operation, parameter summary, success flag, duration, and errorType

#### Scenario: Trace excludes secrets
- **WHEN** trace records are written
- **THEN** they do not include SAP passwords, full sensitive destination configuration, tokens, or `.env` contents

### Requirement: Engineering skeleton and verification commands
The system SHALL provide an engineering skeleton with documented verification commands for Gateway development.

#### Scenario: Gateway project skeleton is present
- **WHEN** the change is built
- **THEN** the repository contains `gateway-jco/`, `registry/`, `schemas/`, and runtime output ignore rules needed for the capability registry gateway slice

#### Scenario: Fast verification is documented
- **WHEN** a developer reads the Gateway README or runbook
- **THEN** they can find commands for local build/test, health check, capabilities check, and any live SAP smoke test prerequisites
```


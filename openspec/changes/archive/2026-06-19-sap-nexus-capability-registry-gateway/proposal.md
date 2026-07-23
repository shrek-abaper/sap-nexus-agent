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

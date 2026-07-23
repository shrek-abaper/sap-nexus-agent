# Brainstorm Summary

- Change: sap-nexus-capability-registry-gateway
- Date: 2026-06-19

## 确认的技术方案

采用 Spring Boot Gateway + YAML Registry + JSON Schema + JSONL Trace。当前 change 严格限制在 Gateway/Registry 骨架，不扩展到 Python Agent、推理、Action 或知识图谱 runtime。

核心数据流：

```text
registry/capabilities.yaml
  -> Gateway Registry Loader
  -> validate capabilityId + params + governance
  -> execute registered READ Function
  -> SAP JCo / BAPI_MATERIAL_AVAILABILITY
  -> ExecutionResult
  -> JSONL Trace
```

实施边界：

- `gateway-jco/`：Spring Boot + Gradle Wrapper，目标 Java 17。
- `registry/`：YAML 作为轻量 capability ontology 和 Gateway allowlist。
- `schemas/`：先定义 `capability.schema.json`、`execution-result.schema.json`。
- `runtime/`：JSONL trace 输出，默认 git ignored。
- API 只开放 `GET /health`、`GET /capabilities`、`POST /capabilities/{capabilityId}/validate`、`POST /capabilities/{capabilityId}/execute`。
- 不提供任意 RFC 执行接口。

## 关键取舍与风险

| 取舍/风险 | 决策 |
|---|---|
| 本机 Java 11 vs 目标 Java 17 | 目标仍是 Java 17 + Spring Boot 3；若实施时 JDK 17 不可用，需记录临时 Java 11 兼容决策 |
| Spring Boot 相对重 | 接受，换取长期 Gateway 量产治理、测试、配置和 observability 能力 |
| YAML Registry 不是最终形态 | 接受，作为 MVP runtime；通过 `ontologyIri` / `semanticType` 预留 OWL / Graph Registry 迁移 |
| Live SAP smoke 可能受环境影响 | fast tests 与 live smoke 分离；live smoke 不阻塞普通单测 |
| trace 泄密风险 | 只记录参数摘要和 execution metadata，不序列化 raw env/destination |

## 测试策略

- Registry/schema tests：合法配置、缺字段、重复 capability、disabled capability、Function side-effect 约束。
- Gateway unit tests：unknown capability、missing/invalid parameter、no raw RFC endpoint。
- Execute path tests：READ Function validate-before-execute、ExecutionResult shape、RETURN normalization。
- Trace tests：trace 字段完整、不包含 secrets。
- Live smoke：单独文档化 `/health`、`/capabilities`、validate、execute 的 SAP 环境前提。

## Spec Patch

无。当前 OpenSpec delta spec 已覆盖需求。

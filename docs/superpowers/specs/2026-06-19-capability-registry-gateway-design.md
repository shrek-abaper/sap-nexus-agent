---
comet_change: sap-nexus-capability-registry-gateway
role: technical-design
canonical_spec: openspec
archived-with: 2026-06-19-sap-nexus-capability-registry-gateway
status: final
---

# Capability Registry Gateway Technical Design

## Summary

This design implements the first SAP Nexus Agent execution boundary: a Java JCo Gateway that exposes only registered SAP capabilities. It uses a YAML Capability Registry as the early lightweight ontology, JSON Schema as cross-language contracts, Spring Boot as the long-running Gateway framework, and JSONL traces for replayable execution diagnostics.

This change intentionally does not implement the full Python Agent, RecommendationPlan, ML reasoning, SAP Write Action, UI, or knowledge graph runtime.

## Architecture

```text
registry/capabilities.yaml
  -> Capability Registry Loader
  -> Capability Validator
  -> Gateway API
      GET /health
      GET /capabilities
      POST /capabilities/{capabilityId}/validate
      POST /capabilities/{capabilityId}/execute
  -> JCo Capability Executor
  -> SAP BAPI/RFC
  -> ExecutionResult
  -> JSONL Trace
```

The Gateway accepts `capabilityId`, not arbitrary `rfcName`. `executor.rfcName` is read from the Registry and cannot be overridden by request payloads.

## Components

| Component | Responsibility |
|---|---|
| `registry/capabilities.yaml` | Runtime allowlist and lightweight capability ontology. |
| `schemas/capability.schema.json` | Validates capability identity, semantics, executor mapping, and governance metadata. |
| `schemas/execution-result.schema.json` | Defines normalized Gateway response shape. |
| `gateway-jco/` | Spring Boot service for capability-level SAP access. |
| Registry loader | Reads and validates enabled capabilities. |
| Capability validator | Blocks unknown, disabled, missing-parameter, invalid-parameter, and governance-invalid requests before SAP execution. |
| JCo adapter | Owns SAP JCo destination and native library interaction. |
| Result normalizer | Converts SAP output and RETURN messages into `ExecutionResult`. |
| Trace emitter | Writes replayable JSONL records without secrets. |

## Data Flow

1. Client calls `validate` or `execute` with `capabilityId` and parameters.
2. Gateway loads capability metadata from Registry.
3. Gateway rejects unknown or disabled capability IDs.
4. Gateway validates required inputs and constraints.
5. Execute path maps Registry inputs to BAPI/RFC parameters.
6. JCo adapter invokes registered SAP function.
7. Result normalizer returns `ExecutionResult`.
8. Trace emitter writes JSONL execution metadata.

## Key Decisions

### Spring Boot + Gradle Wrapper

Use Spring Boot for the long-running Java Gateway and Gradle Wrapper for reproducible builds. The target is Java 17 LTS and Spring Boot 3.x.

If JDK 17 is unavailable during implementation, record a temporary Java 11 compatibility decision before downgrading framework choices.

### YAML Registry First

Use `registry/capabilities.yaml` as the early runtime source of truth. It is not a throwaway config file; it is the first lightweight capability ontology and should include `ontologyIri`, semantic fields, executor mapping, side-effect policy, and approval policy.

### JSON Schema Contracts

Use JSON Schema files in `schemas/` to keep Java, Python, prompts, docs, and evals aligned. Prompt-only enforcement is not acceptable for capability safety.

### JSONL Trace First

Use ignored JSONL files under `runtime/` for early replay diagnostics. Trace fields should include `traceId`, operation, capabilityId, parameter summary, success, duration, and errorType. Traces must not contain SAP passwords, full destination config, tokens, or raw environment dumps.

## API Boundary

Allowed API surface:

```text
GET /health
GET /capabilities
POST /capabilities/{capabilityId}/validate
POST /capabilities/{capabilityId}/execute
```

Explicitly forbidden:

```text
POST /rfc/{rfcName}/execute
POST /execute with request-provided rfcName
```

## Error Handling

The Gateway should return structured errors, including at least:

| Error Type | Trigger |
|---|---|
| `CAPABILITY_NOT_FOUND` | Capability ID is not registered. |
| `CAPABILITY_DISABLED` | Capability exists but is disabled. |
| `MISSING_PARAMETER` | Required input is absent. |
| `INVALID_PARAMETER` | Input violates registry constraints. |
| `SAP_BUSINESS_ERROR` | SAP RETURN contains business error or abort. |
| `SAP_AUTH_ERROR` | SAP authentication or authorization failure. |
| `SAP_COMMUNICATION_ERROR` | JCo destination, network, or timeout failure. |
| `NORMALIZATION_ERROR` | SAP response cannot be mapped to the contract. |

Validation errors must not invoke SAP JCo.

## Testing Strategy

| Test Layer | Coverage |
|---|---|
| Registry/schema tests | Valid config, missing fields, duplicate IDs, disabled capabilities, side-effect constraints. |
| Gateway unit tests | Unknown capability, missing parameters, invalid parameters, no arbitrary RFC route. |
| Execute path tests | Validate-before-execute, ExecutionResult shape, RETURN normalization. |
| Trace tests | Required trace fields present and secrets absent. |
| Live smoke | `/health`, `/capabilities`, validate, execute with SAP env and JCo library available. |

Fast tests must not require SAP connectivity. Live smoke tests must be documented separately and gated by local SAP/JCo prerequisites.

## Risks And Mitigations

| Risk | Mitigation |
|---|---|
| Local Java is 11 while target is 17 | Configure JDK 17 before build or explicitly record a temporary compatibility decision. |
| Dependency download blocked | Use approved network access or internal mirror; do not vendor arbitrary dependency jars. |
| Gateway scope expands into Agent/reasoning | Keep this change limited to Registry, Gateway API, validation, execute shape, and trace. |
| Trace leaks SAP config | Serialize only summaries; never write raw env or destination properties. |
| Live SAP environment unavailable | Keep fast tests separate from live smoke. |

## Implementation Sequence

1. Add Registry and schemas.
2. Add Spring Boot + Gradle Wrapper skeleton.
3. Add Registry loader and capability validation.
4. Add `/health` and `/capabilities`.
5. Add validate API.
6. Add execute API for READ Function.
7. Add JCo destination adapter and result normalization.
8. Add JSONL trace emission and ignore rules.
9. Add tests and documentation.
10. Run fast verification and document live smoke prerequisites.

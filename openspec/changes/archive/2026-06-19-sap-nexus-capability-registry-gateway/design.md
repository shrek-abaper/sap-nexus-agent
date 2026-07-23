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

### Keep execution API capability-level only

The Gateway API surface is:

```text
GET /health
GET /capabilities
POST /capabilities/{capabilityId}/validate
POST /capabilities/{capabilityId}/execute
```

No endpoint accepts arbitrary `rfcName`. The request path uses a registered `capabilityId`; the Gateway reads `executor.rfcName` from Registry.

### Use JSONL trace first

Use JSONL files under `runtime/` for early trace output.

Rationale:

- Simple to inspect, grep, and replay.
- No database migration or service dependency is needed for the first Gateway slice.
- Future SQLite/PostgreSQL/Trace Service migration can preserve the trace fields.

Trace records must include enough to diagnose behavior but must not include credentials or full sensitive destination details.

## Risks / Trade-offs

- Java 17 target vs current Java 11 local environment → Configure JDK 17 before building, or explicitly record a temporary Java 11 compatibility decision.
- Dependency downloads may fail in restricted network → Use approved network access or internal mirror; do not vendor random dependency jars into the repo.
- Spring Boot skeleton could expand scope → Keep the first slice limited to Registry, health, capabilities, validate, execute shape, and trace.
- Live SAP smoke could block on environment variables or native JCo library path → Separate fast tests from live smoke prerequisites.
- Registry and Java model drift → Add schema validation and tests for the first capability.
- Trace could leak sensitive SAP config → Use explicit parameter summaries and destination summaries; never serialize raw environment or destination properties.

## Migration Plan

1. Add Registry and schema contracts.
2. Add `gateway-jco/` Spring Boot + Gradle Wrapper skeleton.
3. Implement Registry loading and capability listing.
4. Implement validation without SAP execution.
5. Implement execute path for the registered READ Function.
6. Add JSONL trace output and `.gitignore` rules for generated runtime files.
7. Add README/runbook verification commands.

Rollback strategy:

- This change is additive. If Gateway implementation blocks, keep Registry and schema artifacts and mark Gateway tasks incomplete rather than weakening capability-level safety boundaries.
- Do not replace the capability-level API with arbitrary RFC execution as a shortcut.

## Open Questions

- Is JDK 17 available locally before build, or must the first implementation temporarily target Java 11?
- Where are `sapjco3.jar` and platform native libraries expected to live for local development?
- Should schema validation run from Java tests only in the first slice, or also through a standalone script?

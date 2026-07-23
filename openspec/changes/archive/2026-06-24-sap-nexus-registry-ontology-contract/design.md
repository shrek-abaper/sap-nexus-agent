## Context

SAP Nexus Agent already has a completed `JCO_RFC` inventory vertical slice: `registry/capabilities.yaml`, Java JCo Gateway validation/execution, Python Agent CallPlan / ReasoningFact flow, hybrid LLM intent adapter, Workbench Console, and MD04 stock/requirements implementation are complete and archived. The current next roadmap step is contract hardening, not runtime expansion.

The existing Registry schema validates a single `executor.type=JCO_RFC` shape and keeps technical fields such as `rfcName` in the capability entry. The architecture and runbook now require a clearer split:

```text
Capability Registry = business semantics, governance, evidence contract
Executor Binding Catalog = technical allowlist and protocol constraints
Gateway family = protocol execution only
```

This change creates the release gate for that split while preserving current runtime compatibility.

## Goals / Non-Goals

**Goals:**

- Validate the current Registry as a semantic capability contract.
- Introduce schema-ready executor binding shapes for `JCO_RFC`, `ODATA`, `CDS_ADT`, `CDS_ODATA`, and `REST_JSON`.
- Add deterministic contract checks for identity, ontology IRI, governance, side effects, approval policy, technical binding ownership, and eval linkage.
- Add offline OWL skeleton identity for SAP Nexus core terms and `MM.Inventory.GetAvailability`.
- Keep the current inventory runtime path and Agent / Gateway regressions passing.

**Non-Goals:**

- No Knowledge Graph runtime, Graph Registry backend, Jena, Neo4j, GraphDB, or runtime OWL loading.
- No new SAP capability and no change to business behavior of `MM.Inventory.GetAvailability`.
- No OData Gateway, CDS / ADT Gateway, REST JSON Gateway, runtime dispatcher, arbitrary HTTP client, arbitrary URL execution, arbitrary ADT SQL, or LLM-generated JSON payload execution.
- No SAP write Action, STO creation, RecommendationPlan, ML uncertainty reasoning, or UI work.

## Decisions

### Decision 1: Use a staged compatibility split

Keep existing runtime-compatible Registry data available while introducing a contract-level `executorBinding` / binding-catalog model. The validator can accept the current `JCO_RFC` capability and enforce that future technical details are represented as allowlisted binding metadata rather than request-owned payload.

Alternative considered: immediately remove the existing `executor` shape. This is too risky because Java Gateway and Agent regressions already depend on current files, and the roadmap asks for contract hardening rather than runtime refactor.

### Decision 2: Put contract validation in deterministic local tooling

Implement a local validator command under `scripts/` with tests under a registry-focused test location. It should validate schema and semantic consistency without network access, SAP credentials, live LLM credentials, generated traces, or runtime Gateway startup.

Alternative considered: relying only on JSON Schema or only on Java loader tests. JSON Schema alone cannot easily prove eval linkage or OWL identity consistency; Java loader tests should remain runtime compatibility tests, not the whole contract gate.

### Decision 3: Treat OWL as offline identity scaffold

Add `ontology/` skeleton files that define stable concepts and individuals, then validate that Registry `ontologyIri` values map to those identities. The Agent and Gateway should not load OWL at runtime in this change.

Alternative considered: introduce an RDF/OWL runtime or graph backend now. That violates the current scope and would distract from the release-gate contract.

### Decision 4: Model `REST_JSON` as controlled binding readiness only

Represent `REST_JSON` as fixed allowlisted method/path/mapping metadata with `credentialRef` placeholders and side-effect guard. It must not become a generic HTTP client or a way for Agent/LLM/user input to provide URL, method, headers, token, or JSON payload.

Alternative considered: build a REST Gateway pilot now. The roadmap explicitly defers `sap-nexus-rest-json-gateway-read-pilot` to a later change.

### Decision 5: Make eval linkage part of the contract

Active executable capabilities should point to matching regression evidence, starting with the existing inventory eval and `scripts/verify-agent-callplan-evidence.sh`. The validator should fail missing linkage so future Registry edits cannot silently bypass Agent/Gateway evidence.

Alternative considered: document eval linkage only in runbooks. Documentation is useful but insufficient as a release gate.

## Risks / Trade-offs

- Registry compatibility risk -> Mitigate by preserving current Agent/Gateway regressions and validating current `MM.Inventory.GetAvailability` first.
- Schema overreach risk -> Mitigate by requiring only `JCO_RFC` runtime validity and using fixture/schema tests for future executor shapes.
- OWL scope creep risk -> Mitigate by keeping OWL skeleton small, identity-focused, and offline.
- REST security drift risk -> Mitigate by making request-owned REST technical details invalid and keeping secrets out of Registry, trace, logs, and responses.
- Eval linkage brittleness -> Mitigate by starting with stable existing eval IDs and documenting the contract in `registry/README.md` or nearest runbook.

## Migration Plan

1. Add contract schemas and validator around the existing inventory capability without changing runtime behavior.
2. Add OWL skeleton identities and validation checks.
3. Add positive and negative tests for governance, binding ownership, future executor shapes, and eval linkage.
4. Update docs/runbook/roadmap with validation commands and scope boundaries.
5. Run registry validation, existing Agent regression, and strict OpenSpec validation.

Rollback strategy: revert the new contract artifacts and validator while leaving existing Gateway / Agent runtime files unchanged.

## Open Questions

- Whether the compatibility bridge should keep both `executor` and `executorBinding` in `registry/capabilities.yaml` for one release or move technical details into a separate binding catalog immediately.
- Whether `schemas/capability.schema.json` should remain the compatibility schema and a new `schemas/registry-contract.schema.json` should become the hardened release gate, or whether the existing schema should be evolved in place.

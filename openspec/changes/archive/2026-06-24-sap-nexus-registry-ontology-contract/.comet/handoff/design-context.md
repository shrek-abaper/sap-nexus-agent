# Comet Design Handoff

- Change: sap-nexus-registry-ontology-contract
- Phase: design
- Mode: compact
- Context hash: 84e5f42be87b99d010277d439c57469bae3efb768b5b6fddf5c4582f6efe9a73

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/sap-nexus-registry-ontology-contract/proposal.md

- Source: openspec/changes/sap-nexus-registry-ontology-contract/proposal.md
- Lines: 1-26
- SHA256: 4db0eebe02d7b215a7cf63b16ff0cfde58e00dca5176a2728c1dc1d405a7ce04

```md
## Why

The current SAP Nexus Registry is sufficient for the completed `JCO_RFC` inventory vertical slice, but it still mixes semantic capability metadata with technical executor details and only validates the existing single executor shape. The next roadmap step needs a traceable contract layer that hardens Registry schema, OWL identity, governance checks, eval linkage, and future executor binding readiness without reopening runtime Gateway or Agent work.

## What Changes

- Add a Registry / OWL contract hardening capability for validating `registry/capabilities.yaml` as the semantic capability source of truth.
- Define a controlled multi-executor binding contract for `JCO_RFC`, `ODATA`, `CDS_ADT`, `CDS_ODATA`, and `REST_JSON` as schema/validator-ready shapes.
- Add contract validation for stable capability identity, `ontologyIri`, `kind`, governance, side effects, approval policy, technical binding ownership, and eval linkage.
- Add OWL skeleton coverage for SAP Nexus core concepts, MM inventory identity, executor bindings, external systems, credential references, and REST JSON mapping terms.
- Preserve existing Gateway, Python Agent CallPlan, LLM intent adapter, Workbench Console, and MD04 inventory runtime behavior.
- Do not implement OData Gateway, CDS / ADT Gateway, REST JSON Gateway, Knowledge Graph runtime, new SAP capability, SAP write action, arbitrary HTTP client, arbitrary URL execution, or LLM-generated JSON payload execution.

## Capabilities

### New Capabilities
- `registry-ontology-contract`: Defines Registry schema hardening, OWL skeleton identity, governance consistency validation, eval linkage, and multi-executor binding contract readiness including controlled `REST_JSON` readiness.

### Modified Capabilities

## Impact

- Affected areas: `registry/`, `schemas/`, `ontology/`, `scripts/`, registry tests, eval linkage, OpenSpec artifacts, and current runbook / roadmap closeout notes.
- Existing `gateway-jco/`, Python Agent orchestration, LLM adapter, Workbench Console runtime, and SAP JCo execution behavior must remain compatible and should only be touched if contract validation exposes a concrete compatibility gap.
- Verification should include registry contract validation, negative contract cases, existing Agent CallPlan/eval regression, and strict OpenSpec validation.
- No `.env`, SAP password, destination config, token, LLM API key, raw live LLM response, or generated runtime trace may be committed.
```

## openspec/changes/sap-nexus-registry-ontology-contract/design.md

- Source: openspec/changes/sap-nexus-registry-ontology-contract/design.md
- Lines: 1-85
- SHA256: 1ed016da50f891af14697bf35e9f12a6802315086b5ea27dd49fbb964e0f656c

[TRUNCATED]

```md
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
```

Full source: openspec/changes/sap-nexus-registry-ontology-contract/design.md

## openspec/changes/sap-nexus-registry-ontology-contract/tasks.md

- Source: openspec/changes/sap-nexus-registry-ontology-contract/tasks.md
- Lines: 1-30
- SHA256: 4b22cbdcee8637e6f3636121a21c65ebf96a0de80cbacc0b9eea42c193d9b4a0

```md
## 1. Contract Shape And Compatibility

- [ ] 1.1 Inspect current Registry, schema, Gateway loader, Agent selector, and eval references for fields that must remain runtime-compatible.
- [ ] 1.2 Define the staged semantic capability / technical binding split, including current `JCO_RFC` compatibility and future `ODATA`, `CDS_ADT`, `CDS_ODATA`, and `REST_JSON` shapes.
- [ ] 1.3 Update or add schema artifacts for Registry capability metadata, executor binding metadata, governance fields, and eval linkage.

## 2. Validator And Tests

- [ ] 2.1 Add deterministic Registry contract validator command for schema, identity, governance, binding ownership, OWL identity, and eval linkage checks.
- [ ] 2.2 Add positive tests proving `MM.Inventory.GetAvailability` passes the contract.
- [ ] 2.3 Add negative tests for malformed identity, invalid governance, request-owned technical details, missing eval linkage, and unsafe `REST_JSON` binding shapes.

## 3. OWL Skeleton

- [ ] 3.1 Add SAP Nexus core OWL skeleton terms for capabilities, governance, facts, executor bindings, external systems, credential references, and JSON mappings.
- [ ] 3.2 Add MM inventory OWL skeleton identity for `sapnexus:MM_Inventory_GetAvailability` and related inventory terms.
- [ ] 3.3 Document that OWL is offline scaffolding and not a runtime dependency in this change.

## 4. Documentation And Traceability

- [ ] 4.1 Document the Registry contract validation command and contract boundary in the nearest Registry or ontology README.
- [ ] 4.2 Update `docs/runbooks/04-registry-ontology-contract.md` and `docs/runbooks/README.md` with progress, verification commands, and next-session guidance.
- [ ] 4.3 Update roadmap/wiki progress with the implemented contract boundary and confirm deferred runtime pilots remain out of scope.

## 5. Verification

- [ ] 5.1 Run the registry contract validator and registry-focused tests.
- [ ] 5.2 Run `scripts/verify-agent-callplan-evidence.sh`.
- [ ] 5.3 Run `openspec validate --all --strict`.
- [ ] 5.4 Run `git status --short` and confirm no secrets, credentials, destination config, tokens, LLM API keys, raw live LLM responses, or runtime traces are included.
```

## openspec/changes/sap-nexus-registry-ontology-contract/specs/registry-ontology-contract/spec.md

- Source: openspec/changes/sap-nexus-registry-ontology-contract/specs/registry-ontology-contract/spec.md
- Lines: 1-90
- SHA256: 6f2fbdfc8460ec247a6e3e4f94557097c561f84936dc2945a28b6c4f33a517f7

[TRUNCATED]

```md
## ADDED Requirements

### Requirement: Registry schema validates semantic capability contract
The system SHALL validate `registry/capabilities.yaml` against a deterministic Registry contract that covers capability identity, semantic metadata, inputs, outputs, governance, and executor binding references.

#### Scenario: Active inventory capability passes Registry contract
- **WHEN** the contract validator checks the active `MM.Inventory.GetAvailability` entry
- **THEN** validation succeeds for its `capabilityId`, `ontologyIri`, `kind`, `domain`, `businessObject`, semantic inputs, semantic outputs, governance metadata, and executor binding reference
- **AND** the capability remains available to existing Agent and Gateway flows by `capabilityId`

#### Scenario: Malformed capability is rejected before runtime execution
- **WHEN** a Registry entry is missing required identity, semantic fields, governance fields, input/output metadata, or executor binding reference
- **THEN** contract validation fails with a deterministic error
- **AND** the invalid entry is not treated as an executable SAP or external-system capability

### Requirement: Semantic capability and technical binding are separated
The system SHALL distinguish business semantic capability metadata from technical executor binding metadata. Agent, Workbench, LLM, and eval flows MUST use registered `capabilityId`; technical execution details MUST come from an allowlisted binding owned by Registry / binding catalog artifacts, not from external requests.

#### Scenario: Capability references allowlisted technical binding
- **WHEN** `MM.Inventory.GetAvailability` declares its technical execution mapping
- **THEN** the semantic capability identifies the business capability and evidence contract
- **AND** the technical binding identifies an allowlisted `bindingId` and executor type for the current `JCO_RFC` implementation
- **AND** callers cannot override `bindingId`, `rfcName`, OData service, CDS object, ADT path, REST endpoint, HTTP method, headers, credential reference, or JSON mapping

#### Scenario: Request-provided technical details are rejected
- **WHEN** a caller, Agent output, LLM output, eval case, or Workbench request attempts to provide raw technical execution details such as `rfcName`, `bindingId`, REST URL, HTTP method, headers, token, or JSON payload mapping
- **THEN** the request is rejected or ignored before runtime execution
- **AND** no SAP, OData, CDS / ADT, or REST runtime call is triggered from those request-provided technical details

### Requirement: Multi-executor binding contract is expressible without runtime pilots
The system SHALL define schema-valid executor binding shapes for `JCO_RFC`, `ODATA`, `CDS_ADT`, `CDS_ODATA`, and `REST_JSON` while only requiring the existing `JCO_RFC` inventory binding to execute in this change.

#### Scenario: Current JCO RFC binding remains valid
- **WHEN** the validator checks the current inventory binding for `MM.Inventory.GetAvailability`
- **THEN** the binding is accepted as `JCO_RFC`
- **AND** it maps to the existing allowlisted MD04 stock/requirements implementation without exposing arbitrary RFC execution

#### Scenario: Future executor binding shapes validate as contracts only
- **WHEN** schema examples or invalid-fixture tests cover `ODATA`, `CDS_ADT`, `CDS_ODATA`, and `REST_JSON`
- **THEN** the schema can express their allowlisted binding metadata
- **AND** no OData Gateway, CDS / ADT Gateway, REST JSON Gateway, arbitrary HTTP client, arbitrary ADT SQL path, or runtime dispatcher is implemented by this change

### Requirement: REST JSON binding is controlled read-only contract readiness
The system SHALL model `REST_JSON` as a controlled executor binding for SAP-context external system facts, not as an open HTTP client.

#### Scenario: REST JSON contract stores only non-secret allowlist metadata
- **WHEN** a `REST_JSON` binding is represented by schema or fixture
- **THEN** it can express `systemRef`, fixed HTTP method, path template, request mapping, response mapping, credential reference, timeout, retry, and side-effect guard
- **AND** it does not store API keys, tokens, base URLs with secrets, tenant secrets, connection strings, raw headers with credentials, or arbitrary caller-provided payloads

#### Scenario: REST JSON Function cannot declare write side effects
- **WHEN** a `REST_JSON` binding is associated with a `Function`
- **THEN** the contract requires read-only side effect semantics
- **AND** any write-like REST operation or side-effecting business action must be modeled later as an `Action` with human approval outside this change

### Requirement: Governance consistency is enforced by contract validation
The system SHALL enforce governance consistency for capability kind, side effects, approval policy, data classification, and audit requirement before a capability can be treated as active.

#### Scenario: Function must be read-only and approval-free
- **WHEN** a capability has `kind=Function`
- **THEN** validation requires `sideEffect=none`, `requiresApproval=false`, and `approvalPolicy=not_required`

#### Scenario: Action must require human approval
- **WHEN** a capability has `kind=Action`
- **THEN** validation requires `requiresApproval=true` and `approvalPolicy=human_required`
- **AND** this change does not add or execute any SAP write Action

### Requirement: OWL skeleton provides stable capability identity
The system SHALL provide offline OWL skeleton files that define stable SAP Nexus core concepts and the MM inventory capability identity for future ontology governance without becoming a runtime dependency.

#### Scenario: Inventory capability maps to OWL identity
- **WHEN** the validator checks `MM.Inventory.GetAvailability`
- **THEN** the capability maps to stable ontology identity `sapnexus:MM_Inventory_GetAvailability`
- **AND** the referenced OWL skeleton contains the relevant SAP Nexus core and MM inventory terms needed for future migration

#### Scenario: OWL remains offline scaffolding
- **WHEN** the Agent, Workbench, Gateway, or eval regression runs
- **THEN** it does not require GraphDB, Jena, Neo4j, OWL runtime loading, or Graph Registry backend availability

### Requirement: Eval linkage is traceable for active capabilities
```

Full source: openspec/changes/sap-nexus-registry-ontology-contract/specs/registry-ontology-contract/spec.md


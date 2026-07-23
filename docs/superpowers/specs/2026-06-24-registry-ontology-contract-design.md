---
comet_change: sap-nexus-registry-ontology-contract
role: technical-design
canonical_spec: openspec
archived-with: 2026-06-24-sap-nexus-registry-ontology-contract
status: final
---

# Registry Ontology Contract Technical Design

## Context

SAP Nexus Agent already has a completed read-only inventory vertical slice:

```text
Chinese query
-> hybrid intent adapter with rule fallback
-> closed-set capability selection
-> CallPlan
-> Java Gateway validate / execute
-> BAPI_MATERIAL_STOCK_REQ_LIST
-> ExecutionResult
-> ReasoningFact
-> Chinese narrative
-> Workbench observation
```

The next change is not a runtime expansion. It hardens the contract around the Registry and ontology so future executor families can be added without moving business semantics into Gateway runtime or allowing callers / LLMs to submit raw technical execution details.

Current constraints:

- Existing `MM.Inventory.GetAvailability` must stay runtime-compatible.
- Existing Gateway, Agent, LLM adapter, Workbench Console, and MD04 inventory behavior must not be reimplemented.
- `JCO_RFC` is the only executor that must execute now.
- `ODATA`, `CDS_ADT`, `CDS_ODATA`, and `REST_JSON` are contract-ready shapes only.
- OWL is offline identity scaffolding only; it is not a runtime dependency.

## Confirmed Architecture

Use a staged compatibility split:

```text
registry/capabilities.yaml
  current runtime-compatible capability entry
  existing executor metadata for Gateway compatibility

contract gate
  semantic capability validation
  executor binding validation
  OWL identity validation
  governance consistency validation
  eval linkage validation

future runtime cutover
  Gateway reads allowlisted bindingId / technical request
  semantic mapping stays outside Gateway
```

The contract model separates responsibilities:

| Layer | Owns | Does Not Own |
|---|---|---|
| Capability Registry | `capabilityId`, `ontologyIri`, `kind`, semantic IO, evidence roles, governance, eval linkage | Raw caller-provided technical endpoints |
| Executor Binding Contract | `bindingId`, executor type, protocol allowlist, mapping, timeout, retry, side-effect guard | Business intent, natural language, cross-capability reasoning |
| Gateway Family | Allowlisted protocol execution, technical errors, trace, redaction | Capability selection, semantic mapping, arbitrary RFC/OData/CDS/REST proxying |
| Agent / Workbench / LLM | Registered `capabilityId` and redacted artifacts | `rfcName`, `bindingId`, REST URL, method, headers, token, JSON mapping override |

## Key Decisions

### 1. Keep runtime compatibility while adding a release gate

The implementation should not perform a hard cutover away from the current Registry shape. Instead, it should add contract-level schema and validation around the current capability, then introduce binding catalog readiness in a way that does not break existing Gateway / Agent tests.

Rationale:

- Existing archived work is already verified and should not be reopened.
- The roadmap asks for Registry / OWL contract hardening, not Gateway execution refactoring.
- Future `sap-nexus-gateway-execution-contract` can handle runtime dispatcher changes after this contract exists.

### 2. Prefer deterministic local tooling with no new dependency by default

The validator should run locally without network access, SAP credentials, LLM credentials, Gateway startup, runtime traces, or dependency installation. The current virtual environment does not have `yaml` or `jsonschema`, so the first implementation should use Python stdlib and a project-limited parser/checker.

Acceptable implementation boundary:

- Support the YAML subset used by current `registry/capabilities.yaml` and test fixtures.
- Validate semantic consistency in Python code where JSON Schema would be awkward.
- Keep tests explicit so future dependency introduction remains a conscious choice.

If this becomes too brittle, a later change can introduce PyYAML / jsonschema with explicit approval.

### 3. Treat OWL as offline identity scaffold

Add `ontology/` skeleton files that define stable terms and individuals, then validate that Registry `ontologyIri` values map to those identities. Do not load OWL in Agent or Gateway runtime.

Minimum OWL coverage:

- Core: `Skill`, `Function`, `Action`, `Capability`, `BusinessObject`, `ReasoningFact`, `RecommendationPlan`, `ApprovalRecord`, `ActionResult`.
- Binding: `ExecutorBinding`, `TechnicalAdapter`, `JcoRfcBinding`, `ODataBinding`, `CdsAdtBinding`, `CdsODataBinding`, `RestJsonBinding`.
- REST JSON readiness: `ExternalSystem`, `CredentialReference`, `JsonRequestSchema`, `JsonResponseSchema`, `ResponseMapping`.
- MM inventory: `Material`, `Plant`, `InventoryStock`, `AvailableQuantity`, `MM_Inventory_GetAvailability`.

### 4. Keep `REST_JSON` closed and read-only in this change

`REST_JSON` is a controlled executor binding for SAP-context external system facts. It is not a generic HTTP client.

Contract should allow:

```text
systemRef
fixed method
pathTemplate
request mapping
response mapping
credentialRef
timeout / retry
sideEffect guard
```

Contract must reject or avoid:

```text
raw URL from caller or LLM
method override
headers with credential values
token / API key / base URL secret in git
caller-provided JSON payload mapping
write side effect for Function
runtime REST execution
```

### 5. Make eval linkage part of active capability readiness

An active capability should not be release-ready unless it links to regression coverage. For the current inventory capability, the validator should connect Registry readiness to the existing Agent/Gateway eval and verification flow.

Minimum evidence linkage:

- `evals/inventory_availability_cases.yaml` includes `MM.Inventory.GetAvailability` happy path and guard cases.
- `scripts/verify-agent-callplan-evidence.sh` continues to pass.
- OpenSpec strict validation continues to pass.

## Implementation Shape

Recommended artifact layout:

```text
registry/
  capabilities.yaml
  executor-bindings.yaml              # optional if needed for contract fixtures
  README.md

schemas/
  capability.schema.json              # existing compatibility schema may evolve
  executor-binding.schema.json        # new contract schema
  registry-contract.schema.json       # optional wrapper if cleaner than in-place schema

ontology/
  sapnexus-core.owl
  mm-inventory.owl
  README.md

scripts/
  validate-registry-contract.py

tests/registry/ or agent/tests/
  test_registry_contract.py
  fixtures/
    invalid-*.yaml
```

If adding a top-level `tests/registry` creates more harness friction than value, registry tests may live under `agent/tests/` and invoke the script/module through `.venv/bin/python`. The verification command must be documented where maintainers will find it.

## Validation Rules

The validator should check at least:

- `capabilityId` is stable and unique.
- `ontologyIri` is present and maps to the OWL skeleton identity.
- `kind` is valid.
- `Function` requires `sideEffect=none`, `requiresApproval=false`, and `approvalPolicy=not_required`.
- `Action` requires `requiresApproval=true` and `approvalPolicy=human_required`.
- Active capability has semantic inputs / outputs and at least one evidence role.
- Active capability has executor binding metadata owned by registry/binding artifacts.
- Request-owned or unsafe technical override fields are invalid in contract fixtures.
- `REST_JSON` contract metadata uses references and mappings, not secrets or raw credential values.
- Active executable capability has eval linkage.

## Test Strategy

Add registry-focused tests for:

- Positive case: current `MM.Inventory.GetAvailability` passes.
- Negative case: malformed identity fails.
- Negative case: Function with write side effect fails.
- Negative case: Action without human approval fails.
- Negative case: request-owned technical details or unsafe binding override fails.
- Negative case: unsafe `REST_JSON` shape fails.
- Negative case: missing eval linkage fails.

Regression verification:

```bash
.venv/bin/python -m pytest <registry-test-path>
.venv/bin/python scripts/validate-registry-contract.py registry/capabilities.yaml
scripts/verify-agent-callplan-evidence.sh
openspec validate --all --strict
```

Adjust `<registry-test-path>` to the final test placement.

## Risks And Mitigations

| Risk | Mitigation |
|---|---|
| Compatibility drift breaks Gateway / Agent | Preserve existing verification and avoid runtime cutover in this change |
| Custom parser is too narrow | Restrict supported YAML subset and cover fixtures; revisit dependency only if needed |
| Binding split becomes runtime refactor | Keep runtime dispatcher work for `sap-nexus-gateway-execution-contract` |
| OWL grows into KG runtime | Keep OWL files small, identity-focused, and documented as offline scaffolding |
| REST JSON becomes open HTTP proxy | Reject caller-owned URL/method/header/token/payload/mapping and avoid runtime client code |
| Eval linkage becomes documentation-only | Make missing linkage a validator failure |

## Spec Patch

No OpenSpec delta spec patch is required. The current delta spec already covers schema validation, semantic/binding split, multi-executor readiness, REST JSON safety, governance consistency, OWL identity, and eval linkage.

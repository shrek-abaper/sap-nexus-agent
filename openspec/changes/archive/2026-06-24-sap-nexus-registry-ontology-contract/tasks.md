## 1. Contract Shape And Compatibility

- [x] 1.1 Inspect current Registry, schema, Gateway loader, Agent selector, and eval references for fields that must remain runtime-compatible.
- [x] 1.2 Define the staged semantic capability / technical binding split, including current `JCO_RFC` compatibility and future `ODATA`, `CDS_ADT`, `CDS_ODATA`, and `REST_JSON` shapes.
- [x] 1.3 Update or add schema artifacts for Registry capability metadata, executor binding metadata, governance fields, and eval linkage.

## 2. Validator And Tests

- [x] 2.1 Add deterministic Registry contract validator command for schema, identity, governance, binding ownership, OWL identity, and eval linkage checks.
- [x] 2.2 Add positive tests proving `MM.Inventory.GetAvailability` passes the contract.
- [x] 2.3 Add negative tests for malformed identity, invalid governance, request-owned technical details, missing eval linkage, and unsafe `REST_JSON` binding shapes.

## 3. OWL Skeleton

- [x] 3.1 Add SAP Nexus core OWL skeleton terms for capabilities, governance, facts, executor bindings, external systems, credential references, and JSON mappings.
- [x] 3.2 Add MM inventory OWL skeleton identity for `sapnexus:MM_Inventory_GetAvailability` and related inventory terms.
- [x] 3.3 Document that OWL is offline scaffolding and not a runtime dependency in this change.

## 4. Documentation And Traceability

- [x] 4.1 Document the Registry contract validation command and contract boundary in the nearest Registry or ontology README.
- [x] 4.2 Update `docs/runbooks/04-registry-ontology-contract.md` and `docs/runbooks/README.md` with progress, verification commands, and next-session guidance.
- [x] 4.3 Update roadmap/wiki progress with the implemented contract boundary and confirm deferred runtime pilots remain out of scope.

## 5. Verification

- [x] 5.1 Run the registry contract validator and registry-focused tests.
- [x] 5.2 Run `scripts/verify-agent-callplan-evidence.sh`.
- [x] 5.3 Run `openspec validate --all --strict`.
- [x] 5.4 Run `git status --short` and confirm no secrets, credentials, destination config, tokens, LLM API keys, raw live LLM responses, or runtime traces are included.

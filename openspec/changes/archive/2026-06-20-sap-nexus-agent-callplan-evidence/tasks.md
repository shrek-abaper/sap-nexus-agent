## 1. Agent Skeleton And Contracts

- [x] 1.1 Create `agent/` Python package structure with CLI, intent parser, capability selector, CallPlan, Gateway client, ExecutionResult adapter, ReasoningFact builder, narrator, and eval runner modules.
- [x] 1.2 Add `schemas/call-plan.schema.json` and `schemas/reasoning-fact.schema.json` aligned with the architecture docs.
- [x] 1.3 Add fast test harness under `agent/tests/` with fake Gateway client support and no live SAP dependency.

## 2. Intent Harness And Capability Selection

- [x] 2.1 Implement Chinese inventory availability parser for `material`, `plant`, and optional `unit`.
- [x] 2.2 Implement missing-parameter clarification that returns Chinese prompts and prevents Gateway validate / execute calls.
- [x] 2.3 Implement closed-set capability selector that only allows `MM.Inventory.GetAvailability` and rejects unsupported read-only MVP intents.
- [x] 2.4 Add tests for complete inventory query, optional unit, missing `material`, missing `plant`, unknown intent, and user-supplied `rfcName`.

## 3. CallPlan And Gateway Orchestration

- [x] 3.1 Implement CallPlan creation before Gateway validate with `traceId`, capability identity, kind, parameters, validation policy, creator, and approval requirement.
- [x] 3.2 Implement Gateway client for `POST /capabilities/{capabilityId}/validate` and `POST /capabilities/{capabilityId}/execute`.
- [x] 3.3 Implement orchestration that calls validate before execute and stops execute on validation failure.
- [x] 3.4 Add tests for validate-before-execute ordering, validation failure, execution failure, trace correlation, and no raw RFC execution.

## 4. Evidence And Narrative

- [x] 4.1 Implement `ExecutionResult` parsing from Gateway responses using the existing execution-result contract.
- [x] 4.2 Implement ReasoningFact creation for successful inventory availability results.
- [x] 4.3 Implement Chinese narrator that consumes ReasoningFact only and refuses unsupported quantity claims.
- [x] 4.4 Add tests for successful fact creation, failed execution without success fact, Chinese fact narration, and narrative guard failure.

## 5. Eval, Safety, And Verification

- [x] 5.1 Add `evals/inventory_availability_cases.yaml` for happy path, missing params, invalid params, unknown intent, Gateway failure, and sensitive-data guard.
- [x] 5.2 Implement eval runner assertions for selected capability, missing parameters, Gateway call counts, narrative guard, and sensitive-data redaction.
- [x] 5.3 Document Agent verification commands in the nearest README or runbook.
- [x] 5.4 Run `python -m pytest agent/tests`, `python -m sap_nexus_agent.eval evals/inventory_availability_cases.yaml`, and `openspec validate --all --strict`.

<!-- build note: user confirmed current-branch execution per project rule; Comet isolation is recorded as branch for state-machine compatibility, but no new branch was created. Standard review found Critical/Important issues; fixes added real Gateway-shaped ExecutionResult coverage, broader redaction, and rfcName precedence before build verification. -->

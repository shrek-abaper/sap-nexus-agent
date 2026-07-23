# Comet Design Handoff

- Change: sap-nexus-agent-callplan-evidence
- Phase: design
- Mode: compact
- Context hash: d751ff8585fd72d60b09b10608a6f39ff064b4d8f2bbbdecf7cdeba7a834d60f

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/sap-nexus-agent-callplan-evidence/proposal.md

- Source: openspec/changes/sap-nexus-agent-callplan-evidence/proposal.md
- Lines: 1-32
- SHA256: 8dc5e8e871cf0e815ad2598cae922c9ac95ecff93de743556fbcf1830b246943

```md
## Why

The Gateway and Registry baseline is complete, but SAP Nexus Agent still lacks the read-only Python Agent slice that turns Chinese inventory intent into an auditable CallPlan, Gateway execution, ReasoningFact, and Chinese narrative. This change establishes that Agent evidence chain now, while the scope is still limited to the single registered `MM.Inventory.GetAvailability` capability.

## What Changes

- Add a read-only Python Agent MVP for Chinese inventory availability queries.
- Parse `material`, `plant`, and optional `unit` from Chinese user intent.
- Select only the registered `MM.Inventory.GetAvailability` capability from the Registry closed set.
- Block missing `material` or `plant` with clarification before any Gateway call.
- Generate a structured CallPlan before Gateway validate / execute.
- Add a Gateway client for capability-level validate / execute APIs without exposing or accepting arbitrary `rfcName`.
- Convert Gateway `ExecutionResult` into `ReasoningFact` evidence.
- Render Chinese narrative only from fields present in `ReasoningFact`.
- Add eval cases and tests for happy path, missing params, invalid params, unknown intent, Gateway failure, and sensitive-data guard.

## Capabilities

### New Capabilities

- `agent-callplan-evidence`: Covers the read-only Python Agent path from Chinese intent through closed-set capability selection, CallPlan generation, Gateway execution, ReasoningFact creation, guarded Chinese narration, and eval evidence.

### Modified Capabilities

- None. Existing `capability-registry-gateway` requirements remain the source-of-truth Gateway contract and are consumed without changing Gateway behavior.

## Impact

- Affected code: new `agent/` Python package, Agent tests, eval runner, and eval cases.
- Affected contracts: new CallPlan and ReasoningFact schemas under `schemas/`; existing `schemas/execution-result.schema.json` is consumed.
- Affected systems: Java Gateway must already be running for live smoke, but fast tests and evals must support fixture or fake-client execution without live SAP.
- Safety: no SAP write actions, no arbitrary RFC execution, no `.env`, SAP password, destination config, token, or runtime trace committed.
```

## openspec/changes/sap-nexus-agent-callplan-evidence/design.md

- Source: openspec/changes/sap-nexus-agent-callplan-evidence/design.md
- Lines: 1-122
- SHA256: fa016a573990b4f6e71b04692756930b962bbb0d473b7e09031b9b87e15e96dc

[TRUNCATED]

```md
## Context

`sap-nexus-capability-registry-gateway` is complete and archived. The current Gateway contract exposes only capability-level APIs and the active `MM.Inventory.GetAvailability` Function through Registry-backed validation and execution. The next risk is not JCo connectivity; it is proving that the Python Agent can plan, validate, execute, evidence, narrate, and evaluate a read-only SAP capability without becoming a generic LLM tool-calling wrapper.

This change builds the first Python Agent vertical slice:

```text
Chinese user intent
-> Intent Harness
-> closed-set Capability Selection
-> CallPlan
-> Java Gateway validate / execute
-> ExecutionResult
-> ReasoningFact
-> Chinese Narrator
-> Eval / Trace evidence
```

The Agent consumes the existing Registry and Gateway behavior. It does not change Gateway endpoints, Registry executor mappings, or SAP JCo connectivity.

## Goals / Non-Goals

**Goals:**

- Parse Chinese inventory availability queries into `material`, `plant`, and optional `unit`.
- Select only `MM.Inventory.GetAvailability` from the Registry closed set for inventory availability intent.
- Clarify missing `material` or `plant` before Gateway validate or execute.
- Generate a structured CallPlan before any executable Gateway call.
- Call the Java Gateway validate / execute APIs by `capabilityId`.
- Parse Gateway `ExecutionResult` and convert it into `ReasoningFact`.
- Render Chinese narrative only from `ReasoningFact` fields.
- Provide fast tests and eval cases that do not require live SAP by default.
- Keep live Gateway smoke optional and explicitly separated from fast verification.

**Non-Goals:**

- No SAP Write Action.
- No `RecommendationPlan`.
- No ML uncertainty reasoning.
- No Knowledge Graph runtime.
- No UI.
- No multi-domain orchestration.
- No raw RFC execution or Agent-provided `rfcName`.
- No changes to the completed Gateway / Registry implementation except consuming its public contract.

## Decisions

### Decision 1: Start with deterministic parser and closed-set selector

The MVP Agent will use deterministic intent parsing and closed-set selection instead of an LLM-first router. The selector may only return `MM.Inventory.GetAvailability` when inventory availability intent is recognized and required parameters are present.

Alternatives considered:

- **LLM-first selection**: more flexible, but increases prompt and hallucination risk before the deterministic harness exists.
- **Gateway-only validation**: simpler, but would allow preventable missing-parameter calls to cross the Agent boundary.

Rationale: deterministic parsing proves the harness and evidence chain first. Future LLM support can be added behind the same closed-set selector contract.

### Decision 2: CallPlan is created before Gateway validate

The Agent will create a CallPlan once intent, capability, and parameters are sufficient to attempt execution. The same `traceId` is then used for Gateway validate and execute when the Gateway contract supports trace propagation or correlation.

Alternatives considered:

- **Create CallPlan after validate**: loses evidence that the Agent planned the call before crossing the Gateway boundary.
- **Only rely on Gateway trace**: omits Agent-side intent, parameter-source, and selection evidence.

Rationale: the project rule is that every action must be planned, validated, executed, normalized, evidenced, audited, and replayable.

### Decision 3: Fast tests use fake Gateway client, live smoke is optional

Unit tests and evals will use a fake Gateway client or fixtures by default. A live smoke can run against `http://localhost:8080` when the Gateway and SAP environment are available.

Alternatives considered:

- **Require live Gateway for all evals**: closer to production, but brittle and blocks local iteration without SAP credentials and JCo native library.
- **Only fixtures forever**: fast, but misses integration regressions.

Rationale: fast verification must be deterministic and safe, while live smoke remains available as extra evidence.

```

Full source: openspec/changes/sap-nexus-agent-callplan-evidence/design.md

## openspec/changes/sap-nexus-agent-callplan-evidence/tasks.md

- Source: openspec/changes/sap-nexus-agent-callplan-evidence/tasks.md
- Lines: 1-33
- SHA256: 483388a228654346fb38dde542f57aaa98a55f88749463292cffec46f1bb0589

```md
## 1. Agent Skeleton And Contracts

- [ ] 1.1 Create `agent/` Python package structure with CLI, intent parser, capability selector, CallPlan, Gateway client, ExecutionResult adapter, ReasoningFact builder, narrator, and eval runner modules.
- [ ] 1.2 Add `schemas/call-plan.schema.json` and `schemas/reasoning-fact.schema.json` aligned with the architecture docs.
- [ ] 1.3 Add fast test harness under `agent/tests/` with fake Gateway client support and no live SAP dependency.

## 2. Intent Harness And Capability Selection

- [ ] 2.1 Implement Chinese inventory availability parser for `material`, `plant`, and optional `unit`.
- [ ] 2.2 Implement missing-parameter clarification that returns Chinese prompts and prevents Gateway validate / execute calls.
- [ ] 2.3 Implement closed-set capability selector that only allows `MM.Inventory.GetAvailability` and rejects unsupported read-only MVP intents.
- [ ] 2.4 Add tests for complete inventory query, optional unit, missing `material`, missing `plant`, unknown intent, and user-supplied `rfcName`.

## 3. CallPlan And Gateway Orchestration

- [ ] 3.1 Implement CallPlan creation before Gateway validate with `traceId`, capability identity, kind, parameters, validation policy, creator, and approval requirement.
- [ ] 3.2 Implement Gateway client for `POST /capabilities/{capabilityId}/validate` and `POST /capabilities/{capabilityId}/execute`.
- [ ] 3.3 Implement orchestration that calls validate before execute and stops execute on validation failure.
- [ ] 3.4 Add tests for validate-before-execute ordering, validation failure, execution failure, trace correlation, and no raw RFC execution.

## 4. Evidence And Narrative

- [ ] 4.1 Implement `ExecutionResult` parsing from Gateway responses using the existing execution-result contract.
- [ ] 4.2 Implement ReasoningFact creation for successful inventory availability results.
- [ ] 4.3 Implement Chinese narrator that consumes ReasoningFact only and refuses unsupported quantity claims.
- [ ] 4.4 Add tests for successful fact creation, failed execution without success fact, Chinese fact narration, and narrative guard failure.

## 5. Eval, Safety, And Verification

- [ ] 5.1 Add `evals/inventory_availability_cases.yaml` for happy path, missing params, invalid params, unknown intent, Gateway failure, and sensitive-data guard.
- [ ] 5.2 Implement eval runner assertions for selected capability, missing parameters, Gateway call counts, narrative guard, and sensitive-data redaction.
- [ ] 5.3 Document Agent verification commands in the nearest README or runbook.
- [ ] 5.4 Run `python -m pytest agent/tests`, `python -m sap_nexus_agent.eval evals/inventory_availability_cases.yaml`, and `openspec validate --all --strict`.
```

## openspec/changes/sap-nexus-agent-callplan-evidence/specs/agent-callplan-evidence/spec.md

- Source: openspec/changes/sap-nexus-agent-callplan-evidence/specs/agent-callplan-evidence/spec.md
- Lines: 1-101
- SHA256: f49ae65aa83b027a211cd9deb7d04907eac2a6ab2dc0555b30c2e7d9da1fb5a3

[TRUNCATED]

```md
## ADDED Requirements

### Requirement: Chinese inventory intent parsing
The system SHALL parse Chinese inventory availability queries for `MM.Inventory.GetAvailability` into normalized intent parameters without using free-form RFC names.

#### Scenario: Parse complete inventory availability query
- **WHEN** the user asks `DEMOA1 在 1000 还有多少可用库存？`
- **THEN** the Agent identifies inventory availability intent and extracts `material=DEMOA1` and `plant=1000`

#### Scenario: Parse optional unit when present
- **WHEN** the user asks `查一下 DEMOA1 在 1000 的 EA 可用量`
- **THEN** the Agent extracts `material=DEMOA1`, `plant=1000`, and `unit=EA`

### Requirement: Missing parameter clarification
The system MUST clarify missing required inventory parameters before any Gateway validate or execute call.

#### Scenario: Missing plant is clarified before Gateway call
- **WHEN** the user asks `查一下 DEMOA1 的可用量`
- **THEN** the Agent returns a Chinese clarification asking for `plant` and does not call Gateway validate or execute

#### Scenario: Missing material is clarified before Gateway call
- **WHEN** the user asks `查一下 1000 工厂还有多少可用库存`
- **THEN** the Agent returns a Chinese clarification asking for `material` and does not call Gateway validate or execute

### Requirement: Closed-set capability selection
The system SHALL select capabilities only from the Registry closed set and MUST reject unsupported intent before Gateway execution.

#### Scenario: Inventory availability selects registered capability
- **WHEN** a complete inventory availability query includes valid `material` and `plant`
- **THEN** the Agent selects `MM.Inventory.GetAvailability` from the Registry closed set

#### Scenario: Unknown intent is rejected
- **WHEN** the user asks for a non-inventory task such as creating a purchase requisition
- **THEN** the Agent rejects the request as unsupported for this read-only MVP and does not call Gateway validate or execute

#### Scenario: Agent cannot override RFC name
- **WHEN** a user query or internal request includes an `rfcName` value
- **THEN** the Agent ignores or rejects the supplied `rfcName` and uses only the Registry-selected `capabilityId`

### Requirement: CallPlan before Gateway execution
The system SHALL create a structured CallPlan before Gateway validation or execution for every executable request.

#### Scenario: Complete request creates CallPlan before validate
- **WHEN** a complete inventory availability request is executable
- **THEN** the Agent creates a CallPlan containing `traceId`, `capabilityId=MM.Inventory.GetAvailability`, `kind=Function`, normalized parameters, validation policy, creator, and approval requirement before Gateway validate

#### Scenario: CallPlan is read-only
- **WHEN** the Agent creates a CallPlan for `MM.Inventory.GetAvailability`
- **THEN** the CallPlan records `requiresApproval=false` and contains no SAP write action fields

### Requirement: Gateway validate and execute orchestration
The system SHALL call the Java Gateway capability APIs by `capabilityId` and handle validation or execution failure as structured Agent outcomes.

#### Scenario: Valid request calls Gateway validate then execute
- **WHEN** Gateway validate succeeds for a complete CallPlan
- **THEN** the Agent calls Gateway execute for `MM.Inventory.GetAvailability` and parses the returned `ExecutionResult`

#### Scenario: Gateway validation failure stops execution
- **WHEN** Gateway validate returns `INVALID_PARAMETER` or `MISSING_PARAMETER`
- **THEN** the Agent returns a structured Chinese failure response and does not call Gateway execute

#### Scenario: Gateway execution failure is reported without secrets
- **WHEN** Gateway execute returns a failed `ExecutionResult`
- **THEN** the Agent reports the failure using `errorType` and safe return messages without exposing SAP passwords, destination config, tokens, or `.env` contents

### Requirement: ExecutionResult to ReasoningFact conversion
The system SHALL convert successful inventory `ExecutionResult` data into deterministic `ReasoningFact` evidence before narration.

#### Scenario: Successful execution creates availability fact
- **WHEN** Gateway execute returns success with `data.availableQuantity`, `data.material`, `data.plant`, and `data.unit`
- **THEN** the Agent creates a `ReasoningFact` with `predicate=availableQuantity`, `deterministic=true`, `confidence=1.0`, source capability metadata, and evidence fields for the returned quantity and unit

#### Scenario: Failed execution does not create success fact
- **WHEN** Gateway execute returns `success=false`
- **THEN** the Agent does not create a deterministic availability fact that claims a successful quantity

### Requirement: Chinese narration from facts only
The system SHALL render Chinese narrative only from fields present in `ReasoningFact` or structured failure outcomes.

#### Scenario: Narrate available quantity from fact
```

Full source: openspec/changes/sap-nexus-agent-callplan-evidence/specs/agent-callplan-evidence/spec.md


# Comet Design Handoff

- Change: sap-nexus-agent-workbench-console
- Phase: design
- Mode: compact
- Context hash: 70fc54e661b70178a22032e98fcdaa74d3ce36e6dac8a0b9177b68f38e7c44f0

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/sap-nexus-agent-workbench-console/proposal.md

- Source: openspec/changes/sap-nexus-agent-workbench-console/proposal.md
- Lines: 1-33
- SHA256: cc0f5f6f568580a179db034a631c24bfedb200b58976a7bba51912d735eaf3e0

```md
## Why

SAP Nexus Agent now has a verified read-only Agent path, but developers still need a safe internal console to observe the harness chain end to end without inspecting scattered CLI output, Gateway logs, or runtime traces. This change adds a local-first Agent Workbench Console shaped for future production hardening so Agent runs can be visualized, audited, and prepared for human-in-the-loop workflows.

## What Changes

- Add a React + Next.js + TypeScript Workbench skeleton for the existing read-only `MM.Inventory.GetAvailability` Agent flow.
- Add an Agent Runtime Adapter boundary so the frontend starts and observes Agent runs without calling SAP, Java Gateway, or raw RFC endpoints directly.
- Add an SSE-first runtime event stream for ordered Agent run stages.
- Add a run state machine and timeline visualization for intent parsing, capability selection, CallPlan, Gateway validation/execution, fact creation, narration, trace, and completion/error states.
- Add artifact panels for redacted `CallPlan`, `ExecutionResult`, `ReasoningFact`, Chinese narrative, and trace metadata.
- Add a human-in-the-loop state skeleton where read-only inventory queries show `approval_not_required`.
- Add secret redaction rules so the console does not display or persist `.env`, SAP password, destination config, tokens, LLM API keys, raw live LLM responses, or runtime trace contents.
- No SAP write actions, real approval writes, RecommendationPlan, KG runtime, RBAC, multi-tenancy, or production deployment are introduced in this change.

## Capabilities

### New Capabilities

- `agent-workbench-console`: Internal Agent console behavior for local-first Agent run submission, SSE runtime visualization, redacted artifact panels, trace/audit viewing, and human-in-the-loop state skeleton.

### Modified Capabilities

- None. Existing `capability-registry-gateway` and `agent-callplan-evidence` requirements are consumed as the backend baseline and are not changed by this proposal.

## Impact

- Adds a new `frontend/` subsystem with Next.js, React, TypeScript, Modular Monolith module boundaries, API routes, runtime adapter, run event schema, state machine, redaction guard, shared UI/types, tests, and documentation.
- May add frontend package metadata and verification commands without changing existing Python Agent or Java Gateway execution contracts.
- Existing verification must continue to pass:
  - `scripts/verify-agent-callplan-evidence.sh`
  - `openspec validate --all --strict`
- Frontend verification will be added by this change and must not require live SAP credentials, live LLM credentials, committed runtime traces, or sensitive local configuration.
```

## openspec/changes/sap-nexus-agent-workbench-console/design.md

- Source: openspec/changes/sap-nexus-agent-workbench-console/design.md
- Lines: 1-166
- SHA256: 924a869a0943344f51b6ba88da54a40ee3d2469249046d7b631c21d699b74c56

[TRUNCATED]

```md
## Context

The repository already has a verified read-only Agent MVP for `MM.Inventory.GetAvailability`: Chinese intent parsing, closed-set capability selection, CallPlan creation, Java Gateway validate/execute, `ExecutionResult`, `ReasoningFact`, Chinese narration, eval coverage, and trace evidence. The next need is not another SAP/JCo path; it is a controlled internal console that lets developers and future operators see the Agent harness chain as a timeline with auditable artifacts.

The console is part of the User Interaction Layer, but it must preserve the existing Harness Engineering boundary. It must not become a generic SAP tool page, raw RFC console, or bypass around the Python Agent and Java Gateway contracts. The first delivery can be local-only, but the architecture should keep production hardening possible.

## Goals / Non-Goals

**Goals:**

- Add a local-first `frontend/` Workbench using React, Next.js, and TypeScript.
- Keep a Modular Monolith shape with clear module boundaries for console input, runtime timeline, artifacts, trace audit, and human-in-the-loop state.
- Introduce an Agent Runtime Adapter as the only frontend boundary to Agent execution.
- Stream ordered Agent run events over SSE for the current read-only inventory flow.
- Render timeline states and redacted artifact panels for intent, capability selection, CallPlan, validation/execution, `ExecutionResult`, `ReasoningFact`, Chinese narrative, and trace metadata.
- Represent human-in-the-loop state with `approval_not_required` for read-only queries and reserved states for future Actions.
- Keep existing Agent and OpenSpec verification passing.

**Non-Goals:**

- No SAP Write Action execution.
- No real approval-driven write flow.
- No `RecommendationPlan` implementation.
- No Knowledge Graph runtime.
- No RBAC, multi-tenancy, or production deployment.
- No frontend endpoint that accepts or overrides `rfcName`.
- No direct frontend calls to Java Gateway, SAP, or arbitrary RFC execution.
- No committed `.env`, SAP credentials, destination config, LLM API keys, raw live LLM responses, or generated runtime traces.

## Decisions

### Decision 1: Use Next.js as a local-first internal console shell

Use `frontend/` with Next.js App Router, React, and TypeScript. The first version will run locally, but API routes and modular source boundaries should resemble an internal production console rather than a disposable demo.

Alternatives considered:

- Plain Vite SPA: simpler, but it would require a separate backend adapter process or direct browser calls that weaken the production-shaped boundary.
- Server-rendered backend templates: less frontend complexity, but weaker fit for interactive timelines and artifact panels.

### Decision 2: Use Modular Monolith boundaries

Keep the frontend in one deployable app while separating modules under `frontend/src/modules/` and runtime contracts under `frontend/src/runtime/`.

Target shape:

```text
frontend/
  app/
    workbench/
      page.tsx
    api/
      agent-runs/
        route.ts
      agent-runs/[runId]/stream/
        route.ts
      traces/[traceId]/
        route.ts
  src/
    modules/
      agent-console/
      runtime-timeline/
      capability-catalog/
      call-plan/
      execution-result/
      reasoning-fact/
      human-approval/
      trace-audit/
      eval-lab/
    runtime/
      agent-runtime-adapter.ts
      run-event-schema.ts
      run-state-machine.ts
      redaction.ts
    shared/
      ui/
      types/
      contracts/
```

```

Full source: openspec/changes/sap-nexus-agent-workbench-console/design.md

## openspec/changes/sap-nexus-agent-workbench-console/tasks.md

- Source: openspec/changes/sap-nexus-agent-workbench-console/tasks.md
- Lines: 1-36
- SHA256: fa5119d38db7a9136bf5a2dfcb0042e626fdfb1734b643f4eca23e3b1c400c09

```md
## 1. Frontend Skeleton And Contracts

- [ ] 1.1 Create `frontend/` Next.js + React + TypeScript skeleton with documented local dev and verification commands.
- [ ] 1.2 Add Modular Monolith directories for agent console, runtime timeline, artifact panels, trace audit, human approval, runtime contracts, and shared UI/types.
- [ ] 1.3 Define `AgentRunEvent` TypeScript contract with event type, run ID, sequence, timestamp, state, trace IDs, safe artifact payload, and error metadata.
- [ ] 1.4 Define the Agent run state machine and human-in-the-loop state skeleton, including `approval_not_required` for read-only queries.

## 2. Runtime Adapter And Streaming

- [ ] 2.1 Implement an Agent Runtime Adapter boundary that accepts natural language input and blocks or removes raw `rfcName` overrides.
- [ ] 2.2 Add local API route to create an Agent run through the adapter.
- [ ] 2.3 Add SSE route for ordered run events using the `AgentRunEvent` contract.
- [ ] 2.4 Add deterministic fake/local adapter path for tests and development without live SAP or live LLM credentials.

## 3. Workbench User Interface

- [ ] 3.1 Build the Workbench page with Chinese natural language input for the existing inventory availability flow.
- [ ] 3.2 Render a timeline for intent parsing, capability selection, CallPlan creation, approval state, Gateway validation, Gateway execution, ReasoningFact creation, narration, trace linkage, and completion/failure.
- [ ] 3.3 Add redacted artifact panels for CallPlan, ExecutionResult, ReasoningFact, Chinese narrative, and trace metadata.
- [ ] 3.4 Add human-in-the-loop panel that shows `approval_not_required` for `MM.Inventory.GetAvailability` and can represent reserved future approval states.

## 4. Safety And Redaction

- [ ] 4.1 Implement redaction guard for `.env`, SAP password, destination config, tokens, LLM API keys, raw live LLM responses, and suspicious secret-like fields.
- [ ] 4.2 Ensure UI components only render redacted artifacts received from the adapter.
- [ ] 4.3 Ensure frontend routes do not expose direct Java Gateway, SAP, or arbitrary RFC execution surfaces.
- [ ] 4.4 Confirm generated runtime traces and local live outputs remain ignored and are not committed.

## 5. Verification And Documentation

- [ ] 5.1 Add frontend unit tests for event schema, run state transitions, HITL states, and redaction behavior.
- [ ] 5.2 Add a frontend build or typecheck command and document it near the `frontend/` subsystem.
- [ ] 5.3 Run frontend verification without live SAP credentials, live LLM credentials, raw live LLM responses, or generated runtime traces.
- [ ] 5.4 Run `scripts/verify-agent-callplan-evidence.sh`.
- [ ] 5.5 Run `openspec validate --all --strict`.
- [ ] 5.6 Update `docs/runbooks/03-agent-workbench-console.md` with what changed, what was verified, blockers, and the exact next action.
```

## openspec/changes/sap-nexus-agent-workbench-console/specs/agent-workbench-console/spec.md

- Source: openspec/changes/sap-nexus-agent-workbench-console/specs/agent-workbench-console/spec.md
- Lines: 1-85
- SHA256: 2590beed692553261c46715b90d84b4ecc816173b1de6c4df594e9c19f5a30ed

[TRUNCATED]

```md
## ADDED Requirements

### Requirement: Workbench run submission through Agent Runtime Adapter
The system SHALL provide a local Workbench UI that submits natural language Agent queries through an Agent Runtime Adapter and MUST NOT call SAP, Java Gateway, or arbitrary RFC execution directly from UI components.

#### Scenario: Submit Chinese inventory query
- **WHEN** a user submits `DEMOA1 在 1000 还有多少可用库存？` from the Workbench page
- **THEN** the UI creates an Agent run through the Agent Runtime Adapter
- **AND** the UI does not submit or expose a raw `rfcName`

#### Scenario: Reject direct RFC override
- **WHEN** a Workbench request includes an attempted `rfcName` override
- **THEN** the Agent Runtime Adapter rejects or removes the override before execution
- **AND** no frontend route forwards that `rfcName` to the Java Gateway or SAP

### Requirement: SSE Agent run event stream
The system SHALL expose an SSE-first stream of ordered Agent run events for the local Workbench.

#### Scenario: Stream ordered run events
- **WHEN** a Workbench Agent run starts
- **THEN** the stream emits ordered events with stable run ID, sequence number, timestamp, event type, and run state
- **AND** the event sequence covers the major stages from run start through completion or failure

#### Scenario: Stream uses SSE rather than WebSocket
- **WHEN** the first Workbench implementation observes an Agent run
- **THEN** the browser consumes a server-sent event stream
- **AND** no WebSocket protocol is required for the read-only inventory flow

### Requirement: Agent run state machine and timeline visualization
The system SHALL model Agent run progress with a deterministic state machine and render it as a timeline.

#### Scenario: Successful read-only timeline
- **WHEN** the Agent run completes successfully for `MM.Inventory.GetAvailability`
- **THEN** the timeline shows intent parsing, capability selection, CallPlan creation, approval state, Gateway validation, Gateway execution, ReasoningFact creation, narrative creation, trace linkage, and completion

#### Scenario: Failed run timeline
- **WHEN** an Agent run fails during parsing, validation, Gateway execution, or narration
- **THEN** the timeline shows the failed stage, structured error type, safe message, and terminal failed state

### Requirement: Redacted artifact panels
The system SHALL display redacted Agent artifacts for CallPlan, ExecutionResult, ReasoningFact, Chinese narrative, and trace metadata.

#### Scenario: Display successful run artifacts
- **WHEN** a successful inventory availability run produces artifacts
- **THEN** the Workbench displays redacted panels for CallPlan, ExecutionResult, ReasoningFact, Chinese narrative, agent trace ID, and gateway trace ID

#### Scenario: Artifact panels preserve harness boundaries
- **WHEN** artifact panels render CallPlan or ExecutionResult data
- **THEN** they display the registered `capabilityId` and safe executor metadata from normalized artifacts
- **AND** they do not provide controls for arbitrary RFC execution

### Requirement: Secret and runtime redaction guard
The system SHALL redact secrets and sensitive runtime details before any Agent run artifact is displayed in the Workbench.

#### Scenario: Redact known sensitive keys
- **WHEN** an artifact contains keys or values resembling `.env`, SAP password, destination config, token, LLM API key, or raw live LLM response data
- **THEN** the Agent Runtime Adapter redacts those fields before the UI receives the artifact

#### Scenario: Runtime trace content is not committed or displayed raw
- **WHEN** the Workbench links trace metadata
- **THEN** it displays safe trace IDs and status fields only
- **AND** it does not require committing generated runtime trace files or displaying raw live trace contents

### Requirement: Human-in-the-loop state skeleton
The system SHALL include a human-in-the-loop state model without implementing SAP Write Action execution.

#### Scenario: Read-only query requires no approval
- **WHEN** the Workbench runs `MM.Inventory.GetAvailability`
- **THEN** the human-in-the-loop panel displays `approval_not_required`
- **AND** no approval record or SAP write action is created

#### Scenario: Future approval states are representable
- **WHEN** the state machine receives a future approval state such as `approval_required`, `awaiting_human_approval`, `approved`, `rejected`, or `expired`
- **THEN** the Workbench can represent that state without executing a SAP write action

### Requirement: Local verification and regression safety
The system SHALL add repeatable verification for Workbench contracts and preserve existing Agent and OpenSpec regression checks.

#### Scenario: Frontend verification does not require live credentials
- **WHEN** frontend tests or build checks run
```

Full source: openspec/changes/sap-nexus-agent-workbench-console/specs/agent-workbench-console/spec.md


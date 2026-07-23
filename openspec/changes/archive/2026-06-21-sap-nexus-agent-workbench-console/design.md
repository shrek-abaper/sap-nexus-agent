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

Alternatives considered:

- Flat frontend structure: faster initially, but hard to keep artifact, trace, and HITL responsibilities clear.
- Micro-frontends: unnecessary for the first local tool and too heavy for the current scope.

### Decision 3: Put Agent Runtime Adapter between UI and existing Agent

The Workbench will call local Next.js API routes that delegate to an Agent Runtime Adapter. The adapter owns run creation, event emission, redaction, and artifact normalization. It may shell out to the existing Python Agent CLI or call a future Agent HTTP API, but that implementation detail must stay behind the adapter.

The UI must not know Java Gateway URLs, SAP destination details, or RFC names. The adapter must pass only natural language input and controlled runtime options that are safe for the current read-only flow.

Alternatives considered:

- Browser directly calls Python Agent or Java Gateway: rejected because it exposes internal execution shape and risks bypassing CallPlan and capability governance.
- Build a new backend Agent service now: rejected because it expands scope beyond the first local console.

### Decision 4: Use SSE first for run observation

Use server-sent events for the first runtime stream. The stream is one-way from the Agent Runtime Adapter to the browser, matching the current need: observe run progress and artifacts.

WebSocket remains out of scope until the product needs bidirectional approval, cancellation, multi-turn human input, or collaborative review.

Alternatives considered:

- Polling: simpler, but poor fit for ordered timeline UX and state transitions.
- WebSocket now: more flexible, but adds unnecessary protocol and lifecycle complexity.

### Decision 5: Define `AgentRunEvent` before UI panels

The event schema is the integration contract for the Workbench. Events should include stable identifiers, run state, sequence number, timestamp, optional capability ID, optional trace IDs, redacted artifact payloads, and structured error metadata.

Expected event categories:

```text
run_started
intent_parsed
capability_selected
callplan_created
approval_state_changed
gateway_validate_started
gateway_validate_completed
gateway_execute_started
gateway_execute_completed
reasoning_fact_created
narrative_created
trace_linked
run_completed
run_failed
```

### Decision 6: Treat HITL as state now, not write behavior

The Workbench should display a human-in-the-loop state machine skeleton, but the current read-only capability must resolve to `approval_not_required`. States like `approval_required`, `awaiting_human_approval`, `approved`, `rejected`, and `expired` can exist as UI/contract states without any SAP write implementation.

This keeps the console ready for future Action Governance while preventing scope drift into write execution.

### Decision 7: Redaction is mandatory at the adapter boundary

Redaction should run before any artifact reaches UI components. It must remove or mask known sensitive keys and suspicious values, including `.env`, password-like keys, SAP destination config, tokens, LLM API keys, raw live LLM response payloads, and runtime trace file content.

The UI should render redacted artifacts only. Tests should cover redaction directly.

## Risks / Trade-offs

- Local Next.js API routes may blur frontend/backend boundaries -> Keep all execution behind `agent-runtime-adapter.ts` and prohibit direct Gateway/SAP calls in UI modules.
- SSE streams can be awkward to test -> Add deterministic fake run events and unit tests for schema/state transitions; reserve live Agent streaming for optional manual smoke.
- Calling the Python Agent from Next.js can be environment-sensitive -> Make the first adapter implementation local and explicit, with clear errors when the Agent command or Gateway is unavailable.
- Artifact panels may accidentally reveal sensitive data -> Redact at the adapter boundary and test password/token/destination key patterns.
- A rich Workbench can invite scope creep into recommendations or write approvals -> Keep `RecommendationPlan` and real write approval out of this change; only show HITL state skeleton.
- Adding frontend dependencies requires network or package availability -> Prefer existing package manager conventions in the repo and document commands; if dependency installation is unavailable, stop and report rather than vendoring dependencies.

## Migration Plan

1. Add the `frontend/` subsystem without modifying existing Python Agent or Java Gateway contracts.
2. Add deterministic fake adapter/test fixtures for frontend verification before wiring local Agent execution.
3. Wire the adapter to the existing read-only Agent path through a safe local boundary.
4. Add frontend verification commands and include them in the runbook or README.
5. Keep generated runtime traces ignored; do not commit live SAP or live LLM artifacts.

Rollback is straightforward: remove `frontend/` and associated package metadata added by this change. Existing Gateway and Python Agent behavior should remain unchanged.

## Open Questions

- Should the first adapter invoke the existing Python CLI directly, or should it introduce a thin local Python HTTP endpoint in a later change?
- Should frontend verification use only TypeScript unit tests initially, or also include a build check in the first change?
- Should trace viewer read only adapter-produced redacted summaries in the first version, or also provide a guarded local trace lookup endpoint for ignored runtime JSONL files?

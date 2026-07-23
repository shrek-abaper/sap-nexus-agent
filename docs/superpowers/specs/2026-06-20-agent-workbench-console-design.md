---
comet_change: sap-nexus-agent-workbench-console
role: technical-design
canonical_spec: openspec
archived-with: 2026-06-21-sap-nexus-agent-workbench-console
status: final
---

# Agent Workbench Console Technical Design

## 1. Context

`sap-nexus-agent-workbench-console` builds the first internal Agent console for SAP Nexus Agent. The backend baseline already exists:

- Python Agent parses Chinese inventory queries and selects only registered capabilities.
- Python Agent creates `CallPlan` before Gateway validation/execution.
- Java Gateway executes by `capabilityId`, not raw `rfcName`.
- `ExecutionResult` is converted to `ReasoningFact`.
- Chinese narration is generated from facts only.
- Current read-only slice is `MM.Inventory.GetAvailability`.

This change must not rebuild Gateway, Registry execution, JCo connectivity, Python Agent CallPlan, or the LLM intent adapter. It adds a local-first but production-shaped frontend control surface for observing the existing harness chain.

## 2. Confirmed Technical Approach

Use **Next.js App Router + React + TypeScript** under `frontend/` as a local-first internal Agent Workbench Console.

Use a **Modular Monolith** structure:

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

The Workbench submits natural language input to a local API route, which delegates to `Agent Runtime Adapter`. The UI must not call Java Gateway, SAP, or arbitrary RFC execution directly.

## 3. Runtime Boundary

`Agent Runtime Adapter` is the anti-corruption boundary between frontend UI and Agent execution.

Responsibilities:

- Accept natural language input and safe runtime options.
- Reject or remove `rfcName` override attempts.
- Create a local Agent run ID.
- Emit ordered `AgentRunEvent` objects.
- Normalize artifact payloads before UI rendering.
- Redact sensitive keys and values before artifacts leave the adapter.
- Link safe trace metadata such as agent trace ID and gateway trace ID.

The adapter may use a deterministic fake/local event source for tests and development. A later implementation step may wire the adapter to the existing Python Agent path, but the UI must remain unchanged.

## 4. Streaming Protocol

Use **SSE first**.

API shape:

```text
POST /api/agent-runs
GET  /api/agent-runs/[runId]/stream
GET  /api/traces/[traceId]
```

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

WebSocket is intentionally out of scope. It should only be considered later for bidirectional approval, cancellation, multi-turn human input, or collaborative review.

## 5. AgentRunEvent Contract

The TypeScript contract should be stable enough for timeline, artifact panels, tests, and future adapter implementations.

Minimum fields:

```ts
type AgentRunEvent = {
  runId: string;
  sequence: number;
  timestamp: string;
  type: AgentRunEventType;
  state: AgentRunState;
  capabilityId?: string;
  agentTraceId?: string;
  gatewayTraceId?: string;
  artifact?: RedactedArtifact;
  error?: {
    errorType: string;
    message: string;
    stage: AgentRunState;
  };
};
```

The contract should prefer explicit event types over free-form strings. UI modules should consume this contract rather than infer state from artifact shapes.

## 6. Run State Machine And HITL Skeleton

The run state machine should model the read-only harness path:

```text
idle
-> submitting
-> running
-> intent_parsed
-> capability_selected
-> callplan_created
-> approval_checked
-> validating
-> executing
-> fact_created
-> narrated
-> trace_linked
-> completed
```

Failure can occur at parsing, validation, execution, fact creation, narration, or trace linkage:

```text
... -> failed
```

Human-in-the-loop states:

```text
approval_not_required
approval_required
awaiting_human_approval
approved
rejected
expired
```

For `MM.Inventory.GetAvailability`, the state must be `approval_not_required`. The Workbench may display future states, but it must not create approvals or execute SAP writes in this change.

## 7. UI Composition

The Workbench page should contain:

- Natural language input panel for Chinese inventory availability queries.
- Run status header with run ID and terminal state.
- Timeline visualization for each harness stage.
- Artifact panels:
  - Intent parse result.
  - Capability selection.
  - `CallPlan`.
  - Gateway validation / execution status.
  - `ExecutionResult`.
  - `ReasoningFact`.
  - Chinese narrative.
  - Trace metadata.
- HITL panel showing `approval_not_required` for read-only inventory queries.

The visual style should feel like an internal mission-control workbench rather than a generic chat page: timeline-first, artifact-first, and trace-first.

## 8. Redaction And Safety

Redaction happens before UI components receive artifacts.

The redaction guard must mask or remove:

- `.env` content and env-like keys.
- SAP password or password-like fields.
- SAP destination config and router/host-sensitive details.
- Tokens and API keys.
- LLM API keys.
- Raw live LLM response payloads.
- Generated runtime trace file contents.

The UI may display safe identifiers such as `capabilityId`, run ID, agent trace ID, gateway trace ID, `errorType`, and redacted artifact JSON.

The Workbench must not expose any control that allows arbitrary RFC execution or `rfcName` override.

## 9. Testing Strategy

Frontend tests should be deterministic and not require live SAP or live LLM credentials.

Required coverage:

- `AgentRunEvent` contract shape and event ordering.
- Run state transitions for success and failure.
- HITL states, especially `approval_not_required`.
- Redaction guard for password, token, destination, `.env`, and raw LLM response patterns.
- Fake adapter path emits the expected ordered event sequence.

Verification chain:

```bash
# frontend command chosen during implementation
npm --prefix frontend test
npm --prefix frontend run typecheck

scripts/verify-agent-callplan-evidence.sh
openspec validate --all --strict
```

If the exact frontend package scripts differ, the implementation must document the chosen commands in `frontend/README.md` or the nearest equivalent.

## 10. Spec Patch

No delta spec patch is required after design review. The existing `agent-workbench-console` delta spec already covers:

- Workbench run submission through Agent Runtime Adapter.
- SSE Agent run event stream.
- Agent run state machine and timeline visualization.
- Redacted artifact panels.
- Secret and runtime redaction guard.
- Human-in-the-loop state skeleton.
- Local verification and regression safety.

## 11. Implementation Notes

The first build should prioritize contract correctness over live integration:

1. Create frontend skeleton and contracts.
2. Implement state machine, redaction, and fake adapter with tests.
3. Add API routes and SSE stream around fake/local events.
4. Build the Workbench page and artifact panels.
5. Wire safe local Agent execution only after contracts and redaction are covered.

Do not add SAP Write Action, RecommendationPlan, RBAC, multi-tenancy, KG runtime, production deployment, or direct Gateway execution from the frontend.

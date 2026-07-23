---
change: sap-nexus-agent-workbench-console
design-doc: docs/superpowers/specs/2026-06-20-agent-workbench-console-design.md
base-ref: 65968d53fe329e70283295c1253178d6ead6cbd5
archived-with: 2026-06-21-sap-nexus-agent-workbench-console
---

# Agent Workbench Console Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local-first internal Agent Workbench Console that submits Chinese inventory queries, observes ordered Agent run events over SSE, renders timeline/artifact/HITL panels, and preserves SAP Nexus Harness boundaries.

**Architecture:** Add a `frontend/` Next.js App Router app with TypeScript and React. Keep execution behind `Agent Runtime Adapter`; UI modules consume `AgentRunEvent` contracts and redacted artifacts only. Start with deterministic fake/local adapter events so verification does not require SAP or LLM credentials, then leave a safe adapter seam for the existing Python Agent path.

**Tech Stack:** Next.js, React, TypeScript, CSS Modules or app-level CSS, Node test runner or Vitest, existing Python Agent and Java Gateway as backend baseline only.

archived-with: 2026-06-21-sap-nexus-agent-workbench-console
---

## File Structure

Create:

- `frontend/package.json` - frontend scripts and dependencies.
- `frontend/tsconfig.json` - TypeScript config.
- `frontend/next.config.mjs` - Next.js config.
- `frontend/app/layout.tsx` - app shell metadata.
- `frontend/app/globals.css` - Workbench visual system.
- `frontend/app/workbench/page.tsx` - Workbench page route.
- `frontend/app/api/agent-runs/route.ts` - creates local Agent runs.
- `frontend/app/api/agent-runs/[runId]/stream/route.ts` - SSE stream endpoint.
- `frontend/app/api/traces/[traceId]/route.ts` - safe trace metadata endpoint.
- `frontend/src/runtime/run-event-schema.ts` - `AgentRunEvent` and related types.
- `frontend/src/runtime/run-state-machine.ts` - deterministic state transitions.
- `frontend/src/runtime/redaction.ts` - redaction guard.
- `frontend/src/runtime/agent-runtime-adapter.ts` - adapter with fake/local run event store.
- `frontend/src/modules/agent-console/AgentConsole.tsx` - input and run shell.
- `frontend/src/modules/runtime-timeline/RuntimeTimeline.tsx` - timeline renderer.
- `frontend/src/modules/call-plan/CallPlanPanel.tsx` - CallPlan artifact panel.
- `frontend/src/modules/execution-result/ExecutionResultPanel.tsx` - ExecutionResult artifact panel.
- `frontend/src/modules/reasoning-fact/ReasoningFactPanel.tsx` - ReasoningFact panel.
- `frontend/src/modules/human-approval/HumanApprovalPanel.tsx` - HITL panel.
- `frontend/src/modules/trace-audit/TraceAuditPanel.tsx` - trace metadata panel.
- `frontend/src/shared/ui/ArtifactJson.tsx` - safe JSON renderer.
- `frontend/src/shared/types/artifacts.ts` - shared artifact types.
- `frontend/tests/runtime/redaction.test.ts` - redaction tests.
- `frontend/tests/runtime/run-state-machine.test.ts` - state machine tests.
- `frontend/tests/runtime/agent-runtime-adapter.test.ts` - fake adapter event-order tests.
- `frontend/README.md` - local dev and verification commands.

Modify:

- `openspec/changes/sap-nexus-agent-workbench-console/tasks.md` - check off tasks only after implementation and verification.
- `docs/runbooks/03-agent-workbench-console.md` - append session closeout after verification.

Do not modify:

- `gateway-jco/` execution behavior.
- `agent/sap_nexus_agent/call_plan.py`.
- `agent/sap_nexus_agent/gateway_client.py`.
- `agent/sap_nexus_agent/orchestrator.py`.
- `.env` or runtime trace files.

## Task 1: Frontend Project Skeleton

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/tsconfig.json`
- Create: `frontend/next.config.mjs`
- Create: `frontend/app/layout.tsx`
- Create: `frontend/app/globals.css`
- Create: `frontend/app/workbench/page.tsx`
- Create: `frontend/README.md`

- [x] **Step 1: Create package metadata**

Create `frontend/package.json`:

```json
{
  "name": "sap-nexus-agent-workbench",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "next dev",
    "build": "next build",
    "typecheck": "tsc --noEmit",
    "test": "vitest run"
  },
  "dependencies": {
    "next": "^15.3.0",
    "react": "^19.0.0",
    "react-dom": "^19.0.0"
  },
  "devDependencies": {
    "@types/node": "^22.0.0",
    "@types/react": "^19.0.0",
    "@types/react-dom": "^19.0.0",
    "typescript": "^5.8.0",
    "vitest": "^3.0.0"
  }
}
```

- [x] **Step 2: Add TypeScript and Next config**

Create `frontend/tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["dom", "dom.iterable", "es2022"],
    "allowJs": false,
    "skipLibCheck": true,
    "strict": true,
    "noEmit": true,
    "esModuleInterop": true,
    "module": "esnext",
    "moduleResolution": "bundler",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "jsx": "preserve",
    "incremental": true,
    "baseUrl": ".",
    "paths": {
      "@/*": ["./src/*"]
    }
  },
  "include": ["next-env.d.ts", "**/*.ts", "**/*.tsx"],
  "exclude": ["node_modules"]
}
```

Create `frontend/next.config.mjs`:

```js
/** @type {import('next').NextConfig} */
const nextConfig = {
  poweredByHeader: false
};

export default nextConfig;
```

- [x] **Step 3: Add initial app shell**

Create `frontend/app/layout.tsx`:

```tsx
import "./globals.css";

export const metadata = {
  title: "SAP Nexus Agent Workbench",
  description: "Internal console for Agent run timeline, evidence, trace, and HITL state."
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
```

Create `frontend/app/workbench/page.tsx`:

```tsx
export default function WorkbenchPage() {
  return (
    <main>
      <h1>SAP Nexus Agent Workbench</h1>
      <p>Agent runtime timeline and redacted artifacts will render here.</p>
    </main>
  );
}
```

- [x] **Step 4: Add visual foundation**

Create `frontend/app/globals.css` with CSS variables and a console-oriented layout:

```css
:root {
  --ink: #17201b;
  --paper: #f4efe3;
  --panel: rgba(255, 252, 242, 0.88);
  --line: #23352c;
  --accent: #d66f2f;
  --ok: #3b7f5b;
  --warn: #bd8b2f;
  --bad: #a64034;
}

* {
  box-sizing: border-box;
}

body {
  margin: 0;
  min-height: 100vh;
  color: var(--ink);
  background:
    radial-gradient(circle at 20% 12%, rgba(214, 111, 47, 0.22), transparent 28rem),
    linear-gradient(135deg, #f4efe3 0%, #d8d0bd 100%);
  font-family: ui-serif, Georgia, "Times New Roman", serif;
}

button,
input,
textarea {
  font: inherit;
}
```

- [x] **Step 5: Document install and verification**

Create `frontend/README.md`:

```md
# SAP Nexus Agent Workbench

Local-first internal console for observing SAP Nexus Agent runs.

## Commands

```bash
npm install
npm run dev
npm run typecheck
npm run test
npm run build
```

Verification must not require SAP credentials, LLM credentials, raw live LLM responses, or generated runtime traces.
```

- [x] **Step 6: Verify dependency availability**

Run:

```bash
npm --prefix frontend install
```

Expected: dependencies install and `frontend/package-lock.json` is created.

If network is blocked, request approval for `npm --prefix frontend install`; do not vendor dependencies manually.

- [x] **Step 7: Run skeleton checks**

Run:

```bash
npm --prefix frontend run typecheck
```

Expected: TypeScript succeeds after dependencies are installed.

- [x] **Step 8: Check status**

Run:

```bash
git status --short -- sap-nexus-agent
```

Expected: only intentional `frontend/`, OpenSpec, and design/plan files are modified or untracked.

Do not commit unless the user explicitly asks.

## Task 2: Runtime Contracts And State Machine

**Files:**
- Create: `frontend/src/runtime/run-event-schema.ts`
- Create: `frontend/src/runtime/run-state-machine.ts`
- Create: `frontend/src/shared/types/artifacts.ts`
- Create: `frontend/tests/runtime/run-state-machine.test.ts`

- [x] **Step 1: Write state machine test first**

Create `frontend/tests/runtime/run-state-machine.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { applyRunEvent } from "../../src/runtime/run-state-machine";
import type { AgentRunSnapshot } from "../../src/runtime/run-event-schema";

const initial: AgentRunSnapshot = {
  runId: "run-1",
  state: "idle",
  events: [],
  hitlState: "approval_not_required"
};

describe("applyRunEvent", () => {
  it("advances a successful read-only run", () => {
    const next = applyRunEvent(initial, {
      runId: "run-1",
      sequence: 1,
      timestamp: "2026-06-20T00:00:00.000Z",
      type: "run_started",
      state: "running"
    });

    expect(next.state).toBe("running");
    expect(next.events).toHaveLength(1);
    expect(next.hitlState).toBe("approval_not_required");
  });

  it("enters failed state when an error event arrives", () => {
    const next = applyRunEvent(initial, {
      runId: "run-1",
      sequence: 1,
      timestamp: "2026-06-20T00:00:00.000Z",
      type: "run_failed",
      state: "failed",
      error: {
        errorType: "INVALID_PARAMETER",
        message: "参数不合法",
        stage: "validating"
      }
    });

    expect(next.state).toBe("failed");
    expect(next.error?.errorType).toBe("INVALID_PARAMETER");
  });
});
```

- [x] **Step 2: Add runtime types**

Create `frontend/src/shared/types/artifacts.ts`:

```ts
export type JsonPrimitive = string | number | boolean | null;
export type JsonValue = JsonPrimitive | JsonValue[] | { [key: string]: JsonValue };

export type RedactedArtifact = {
  label: string;
  kind:
    | "intent"
    | "capability"
    | "callplan"
    | "validation"
    | "execution-result"
    | "reasoning-fact"
    | "narrative"
    | "trace";
  payload: JsonValue;
};
```

Create `frontend/src/runtime/run-event-schema.ts`:

```ts
import type { RedactedArtifact } from "../shared/types/artifacts";

export type AgentRunEventType =
  | "run_started"
  | "intent_parsed"
  | "capability_selected"
  | "callplan_created"
  | "approval_state_changed"
  | "gateway_validate_started"
  | "gateway_validate_completed"
  | "gateway_execute_started"
  | "gateway_execute_completed"
  | "reasoning_fact_created"
  | "narrative_created"
  | "trace_linked"
  | "run_completed"
  | "run_failed";

export type AgentRunState =
  | "idle"
  | "submitting"
  | "running"
  | "intent_parsed"
  | "capability_selected"
  | "callplan_created"
  | "approval_checked"
  | "validating"
  | "executing"
  | "fact_created"
  | "narrated"
  | "trace_linked"
  | "completed"
  | "failed";

export type HumanInTheLoopState =
  | "approval_not_required"
  | "approval_required"
  | "awaiting_human_approval"
  | "approved"
  | "rejected"
  | "expired";

export type AgentRunEvent = {
  runId: string;
  sequence: number;
  timestamp: string;
  type: AgentRunEventType;
  state: AgentRunState;
  capabilityId?: string;
  agentTraceId?: string;
  gatewayTraceId?: string;
  hitlState?: HumanInTheLoopState;
  artifact?: RedactedArtifact;
  error?: {
    errorType: string;
    message: string;
    stage: AgentRunState;
  };
};

export type AgentRunSnapshot = {
  runId: string;
  state: AgentRunState;
  hitlState: HumanInTheLoopState;
  events: AgentRunEvent[];
  latestArtifact?: RedactedArtifact;
  error?: AgentRunEvent["error"];
};
```

- [x] **Step 3: Implement state machine**

Create `frontend/src/runtime/run-state-machine.ts`:

```ts
import type { AgentRunEvent, AgentRunSnapshot } from "./run-event-schema";

export function applyRunEvent(snapshot: AgentRunSnapshot, event: AgentRunEvent): AgentRunSnapshot {
  if (snapshot.runId !== event.runId) {
    return snapshot;
  }

  return {
    runId: snapshot.runId,
    state: event.state,
    hitlState: event.hitlState ?? snapshot.hitlState,
    events: [...snapshot.events, event].sort((left, right) => left.sequence - right.sequence),
    latestArtifact: event.artifact ?? snapshot.latestArtifact,
    error: event.error ?? snapshot.error
  };
}

export function createInitialSnapshot(runId: string): AgentRunSnapshot {
  return {
    runId,
    state: "idle",
    hitlState: "approval_not_required",
    events: []
  };
}
```

- [x] **Step 4: Run failing/passing test**

Run:

```bash
npm --prefix frontend run test -- tests/runtime/run-state-machine.test.ts
```

Expected: tests pass after implementation.

## Task 3: Redaction Guard

**Files:**
- Create: `frontend/src/runtime/redaction.ts`
- Create: `frontend/tests/runtime/redaction.test.ts`

- [x] **Step 1: Write redaction tests first**

Create `frontend/tests/runtime/redaction.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { redactArtifact } from "../../src/runtime/redaction";

describe("redactArtifact", () => {
  it("masks sensitive keys recursively", () => {
    const redacted = redactArtifact({
      label: "execution",
      kind: "execution-result",
      payload: {
        SAP_PASSWORD: "secret",
        nested: {
          token: "abc",
          destinationConfig: "ashost=internal password=secret"
        }
      }
    });

    expect(JSON.stringify(redacted)).not.toContain("secret");
    expect(JSON.stringify(redacted)).not.toContain("abc");
    expect(JSON.stringify(redacted)).toContain("[REDACTED]");
  });

  it("keeps safe trace identifiers", () => {
    const redacted = redactArtifact({
      label: "trace",
      kind: "trace",
      payload: {
        agentTraceId: "agent-123",
        gatewayTraceId: "gw-456",
        capabilityId: "MM.Inventory.GetAvailability"
      }
    });

    expect(JSON.stringify(redacted)).toContain("agent-123");
    expect(JSON.stringify(redacted)).toContain("MM.Inventory.GetAvailability");
  });
});
```

- [x] **Step 2: Implement redaction**

Create `frontend/src/runtime/redaction.ts`:

```ts
import type { JsonValue, RedactedArtifact } from "../shared/types/artifacts";

const SENSITIVE_KEY = /(password|passwd|secret|token|api[_-]?key|llm[_-]?api|destination|saprouter|\.env|raw.*llm)/i;
const SENSITIVE_VALUE = /(password\s*=|passwd\s*=|api[_-]?key\s*=|bearer\s+|sk-[a-z0-9])/i;

export function redactArtifact(artifact: RedactedArtifact): RedactedArtifact {
  return {
    ...artifact,
    payload: redactJson(artifact.payload, "")
  };
}

function redactJson(value: JsonValue, key: string): JsonValue {
  if (SENSITIVE_KEY.test(key)) {
    return "[REDACTED]";
  }
  if (typeof value === "string") {
    return SENSITIVE_VALUE.test(value) ? "[REDACTED]" : value;
  }
  if (Array.isArray(value)) {
    return value.map((entry) => redactJson(entry, key));
  }
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value).map(([entryKey, entryValue]) => [entryKey, redactJson(entryValue, entryKey)])
    );
  }
  return value;
}
```

- [x] **Step 3: Run redaction tests**

Run:

```bash
npm --prefix frontend run test -- tests/runtime/redaction.test.ts
```

Expected: tests pass and sensitive literals do not appear in serialized redacted artifacts.

## Task 4: Agent Runtime Adapter And API Routes

**Files:**
- Create: `frontend/src/runtime/agent-runtime-adapter.ts`
- Create: `frontend/tests/runtime/agent-runtime-adapter.test.ts`
- Create: `frontend/app/api/agent-runs/route.ts`
- Create: `frontend/app/api/agent-runs/[runId]/stream/route.ts`
- Create: `frontend/app/api/traces/[traceId]/route.ts`

- [x] **Step 1: Write adapter event-order test first**

Create `frontend/tests/runtime/agent-runtime-adapter.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { createAgentRun, getAgentRunEvents } from "../../src/runtime/agent-runtime-adapter";

describe("agent runtime adapter", () => {
  it("creates a read-only run and emits ordered events", async () => {
    const run = createAgentRun({ query: "DEMOA1 在 1000 还有多少可用库存？" });
    const events = await getAgentRunEvents(run.runId);

    expect(events.map((event) => event.sequence)).toEqual(events.map((_, index) => index + 1));
    expect(events.some((event) => event.type === "callplan_created")).toBe(true);
    expect(events.some((event) => event.hitlState === "approval_not_required")).toBe(true);
    expect(JSON.stringify(events)).not.toContain("SAP_PASSWORD");
  });

  it("rejects raw RFC override attempts", () => {
    expect(() =>
      createAgentRun({
        query: "查库存",
        rfcName: "BAPI_MATERIAL_AVAILABILITY"
      })
    ).toThrow("Raw RFC execution is not allowed");
  });
});
```

- [x] **Step 2: Implement fake/local adapter**

Create `frontend/src/runtime/agent-runtime-adapter.ts` with an in-memory run store:

```ts
import type { AgentRunEvent } from "./run-event-schema";
import { redactArtifact } from "./redaction";

type CreateAgentRunInput = {
  query: string;
  rfcName?: string;
};

type AgentRunRecord = {
  runId: string;
  query: string;
  events: AgentRunEvent[];
};

const runs = new Map<string, AgentRunRecord>();

export function createAgentRun(input: CreateAgentRunInput): { runId: string } {
  if (input.rfcName) {
    throw new Error("Raw RFC execution is not allowed");
  }
  const runId = `run-${crypto.randomUUID()}`;
  const events = buildFakeEvents(runId, input.query);
  runs.set(runId, { runId, query: input.query, events });
  return { runId };
}

export async function getAgentRunEvents(runId: string): Promise<AgentRunEvent[]> {
  const run = runs.get(runId);
  if (!run) {
    return [];
  }
  return run.events;
}

export function getTraceMetadata(traceId: string) {
  return {
    traceId,
    status: "available",
    redacted: true
  };
}

function buildFakeEvents(runId: string, query: string): AgentRunEvent[] {
  const timestamp = "2026-06-20T00:00:00.000Z";
  const agentTraceId = "agent-demo-trace";
  const gatewayTraceId = "gateway-demo-trace";

  return [
    { runId, sequence: 1, timestamp, type: "run_started", state: "running" },
    {
      runId,
      sequence: 2,
      timestamp,
      type: "intent_parsed",
      state: "intent_parsed",
      capabilityId: "MM.Inventory.GetAvailability",
      artifact: redactArtifact({
        label: "IntentParseResult",
        kind: "intent",
        payload: { query, material: "DEMOA1", plant: "1000", unit: "EA" }
      })
    },
    {
      runId,
      sequence: 3,
      timestamp,
      type: "capability_selected",
      state: "capability_selected",
      capabilityId: "MM.Inventory.GetAvailability",
      artifact: redactArtifact({
        label: "Capability Selection",
        kind: "capability",
        payload: { capabilityId: "MM.Inventory.GetAvailability", kind: "Function" }
      })
    },
    {
      runId,
      sequence: 4,
      timestamp,
      type: "callplan_created",
      state: "callplan_created",
      capabilityId: "MM.Inventory.GetAvailability",
      agentTraceId,
      artifact: redactArtifact({
        label: "CallPlan",
        kind: "callplan",
        payload: {
          agentTraceId,
          capabilityId: "MM.Inventory.GetAvailability",
          parameters: { material: "DEMOA1", plant: "1000", unit: "EA" },
          requiresApproval: false
        }
      })
    },
    {
      runId,
      sequence: 5,
      timestamp,
      type: "approval_state_changed",
      state: "approval_checked",
      hitlState: "approval_not_required"
    },
    {
      runId,
      sequence: 6,
      timestamp,
      type: "gateway_validate_completed",
      state: "validating",
      capabilityId: "MM.Inventory.GetAvailability",
      agentTraceId,
      gatewayTraceId,
      artifact: redactArtifact({
        label: "Gateway Validation",
        kind: "validation",
        payload: { success: true, errorType: "NONE" }
      })
    },
    {
      runId,
      sequence: 7,
      timestamp,
      type: "gateway_execute_completed",
      state: "executing",
      capabilityId: "MM.Inventory.GetAvailability",
      agentTraceId,
      gatewayTraceId,
      artifact: redactArtifact({
        label: "ExecutionResult",
        kind: "execution-result",
        payload: {
          success: true,
          traceId: gatewayTraceId,
          capabilityId: "MM.Inventory.GetAvailability",
          data: { material: "DEMOA1", plant: "1000", availableQuantity: 12, unit: "EA" }
        }
      })
    },
    {
      runId,
      sequence: 8,
      timestamp,
      type: "reasoning_fact_created",
      state: "fact_created",
      capabilityId: "MM.Inventory.GetAvailability",
      agentTraceId,
      gatewayTraceId,
      artifact: redactArtifact({
        label: "ReasoningFact",
        kind: "reasoning-fact",
        payload: {
          predicate: "availableQuantity",
          value: 12,
          unit: "EA",
          deterministic: true,
          confidence: 1
        }
      })
    },
    {
      runId,
      sequence: 9,
      timestamp,
      type: "narrative_created",
      state: "narrated",
      artifact: redactArtifact({
        label: "Chinese Narrative",
        kind: "narrative",
        payload: { text: "物料 DEMOA1 在工厂 1000 的可用库存为 12 EA。" }
      })
    },
    {
      runId,
      sequence: 10,
      timestamp,
      type: "trace_linked",
      state: "trace_linked",
      agentTraceId,
      gatewayTraceId,
      artifact: redactArtifact({
        label: "Trace Metadata",
        kind: "trace",
        payload: { agentTraceId, gatewayTraceId, status: "linked" }
      })
    },
    { runId, sequence: 11, timestamp, type: "run_completed", state: "completed" }
  ];
}
```

- [x] **Step 3: Add create-run API route**

Create `frontend/app/api/agent-runs/route.ts`:

```ts
import { NextResponse } from "next/server";
import { createAgentRun } from "@/runtime/agent-runtime-adapter";

export async function POST(request: Request) {
  const payload = await request.json();
  try {
    const result = createAgentRun({
      query: String(payload.query ?? ""),
      rfcName: payload.rfcName ? String(payload.rfcName) : undefined
    });
    return NextResponse.json(result);
  } catch (error) {
    return NextResponse.json(
      { errorType: "INVALID_REQUEST", message: error instanceof Error ? error.message : "Invalid request" },
      { status: 400 }
    );
  }
}
```

- [x] **Step 4: Add SSE route**

Create `frontend/app/api/agent-runs/[runId]/stream/route.ts`:

```ts
import { getAgentRunEvents } from "@/runtime/agent-runtime-adapter";

export async function GET(_request: Request, { params }: { params: Promise<{ runId: string }> }) {
  const { runId } = await params;
  const events = await getAgentRunEvents(runId);
  const body = events.map((event) => `event: ${event.type}\ndata: ${JSON.stringify(event)}\n\n`).join("");

  return new Response(body, {
    headers: {
      "Content-Type": "text/event-stream; charset=utf-8",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive"
    }
  });
}
```

- [x] **Step 5: Add trace metadata route**

Create `frontend/app/api/traces/[traceId]/route.ts`:

```ts
import { NextResponse } from "next/server";
import { getTraceMetadata } from "@/runtime/agent-runtime-adapter";

export async function GET(_request: Request, { params }: { params: Promise<{ traceId: string }> }) {
  const { traceId } = await params;
  return NextResponse.json(getTraceMetadata(traceId));
}
```

- [x] **Step 6: Run adapter tests**

Run:

```bash
npm --prefix frontend run test -- tests/runtime/agent-runtime-adapter.test.ts
```

Expected: adapter emits ordered events and rejects `rfcName`.

## Task 5: Workbench UI Modules

**Files:**
- Create: `frontend/src/shared/ui/ArtifactJson.tsx`
- Create: `frontend/src/modules/runtime-timeline/RuntimeTimeline.tsx`
- Create: `frontend/src/modules/call-plan/CallPlanPanel.tsx`
- Create: `frontend/src/modules/execution-result/ExecutionResultPanel.tsx`
- Create: `frontend/src/modules/reasoning-fact/ReasoningFactPanel.tsx`
- Create: `frontend/src/modules/human-approval/HumanApprovalPanel.tsx`
- Create: `frontend/src/modules/trace-audit/TraceAuditPanel.tsx`
- Create: `frontend/src/modules/agent-console/AgentConsole.tsx`
- Modify: `frontend/app/workbench/page.tsx`

- [x] **Step 1: Add safe JSON renderer**

Create `frontend/src/shared/ui/ArtifactJson.tsx`:

```tsx
import type { RedactedArtifact } from "../types/artifacts";

export function ArtifactJson({ artifact }: { artifact?: RedactedArtifact }) {
  if (!artifact) {
    return <p className="muted">等待运行产物。</p>;
  }

  return (
    <section className="artifact-card">
      <h3>{artifact.label}</h3>
      <pre>{JSON.stringify(artifact.payload, null, 2)}</pre>
    </section>
  );
}
```

- [x] **Step 2: Add timeline component**

Create `frontend/src/modules/runtime-timeline/RuntimeTimeline.tsx`:

```tsx
import type { AgentRunEvent } from "@/runtime/run-event-schema";

export function RuntimeTimeline({ events }: { events: AgentRunEvent[] }) {
  return (
    <ol className="timeline">
      {events.map((event) => (
        <li key={`${event.runId}-${event.sequence}`}>
          <span className="sequence">{event.sequence.toString().padStart(2, "0")}</span>
          <strong>{event.type}</strong>
          <span>{event.state}</span>
          {event.error ? <em>{event.error.errorType}</em> : null}
        </li>
      ))}
    </ol>
  );
}
```

- [x] **Step 3: Add artifact panel components**

Create `frontend/src/modules/call-plan/CallPlanPanel.tsx`:

```tsx
import type { RedactedArtifact } from "@/shared/types/artifacts";
import { ArtifactJson } from "@/shared/ui/ArtifactJson";

export function CallPlanPanel({ artifact }: { artifact?: RedactedArtifact }) {
  return <ArtifactJson artifact={artifact} />;
}
```

Create `frontend/src/modules/execution-result/ExecutionResultPanel.tsx`:

```tsx
import type { RedactedArtifact } from "@/shared/types/artifacts";
import { ArtifactJson } from "@/shared/ui/ArtifactJson";

export function ExecutionResultPanel({ artifact }: { artifact?: RedactedArtifact }) {
  return <ArtifactJson artifact={artifact} />;
}
```

Create `frontend/src/modules/reasoning-fact/ReasoningFactPanel.tsx`:

```tsx
import type { RedactedArtifact } from "@/shared/types/artifacts";
import { ArtifactJson } from "@/shared/ui/ArtifactJson";

export function ReasoningFactPanel({ artifact }: { artifact?: RedactedArtifact }) {
  return <ArtifactJson artifact={artifact} />;
}
```

- [x] **Step 4: Add HITL and trace panels**

Create `frontend/src/modules/human-approval/HumanApprovalPanel.tsx`:

```tsx
import type { HumanInTheLoopState } from "@/runtime/run-event-schema";

export function HumanApprovalPanel({ state }: { state: HumanInTheLoopState }) {
  return (
    <section className="panel">
      <h2>Human-in-the-loop</h2>
      <p>{state}</p>
      {state === "approval_not_required" ? <small>Read-only Function，不需要人工审批。</small> : null}
    </section>
  );
}
```

Create `frontend/src/modules/trace-audit/TraceAuditPanel.tsx`:

```tsx
export function TraceAuditPanel({
  agentTraceId,
  gatewayTraceId
}: {
  agentTraceId?: string;
  gatewayTraceId?: string;
}) {
  return (
    <section className="panel">
      <h2>Trace / Audit</h2>
      <p>Agent trace: {agentTraceId ?? "等待 trace"}</p>
      <p>Gateway trace: {gatewayTraceId ?? "等待 Gateway trace"}</p>
    </section>
  );
}
```

- [x] **Step 5: Add Agent console client component**

Create `frontend/src/modules/agent-console/AgentConsole.tsx`:

```tsx
"use client";

import { useMemo, useState } from "react";
import type { AgentRunEvent, AgentRunSnapshot } from "@/runtime/run-event-schema";
import { applyRunEvent, createInitialSnapshot } from "@/runtime/run-state-machine";
import { RuntimeTimeline } from "@/modules/runtime-timeline/RuntimeTimeline";
import { CallPlanPanel } from "@/modules/call-plan/CallPlanPanel";
import { ExecutionResultPanel } from "@/modules/execution-result/ExecutionResultPanel";
import { ReasoningFactPanel } from "@/modules/reasoning-fact/ReasoningFactPanel";
import { HumanApprovalPanel } from "@/modules/human-approval/HumanApprovalPanel";
import { TraceAuditPanel } from "@/modules/trace-audit/TraceAuditPanel";

export function AgentConsole() {
  const [query, setQuery] = useState("DEMOA1 在 1000 还有多少可用库存？");
  const [snapshot, setSnapshot] = useState<AgentRunSnapshot | null>(null);

  async function runAgent() {
    const response = await fetch("/api/agent-runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query })
    });
    const { runId } = await response.json();
    let nextSnapshot = createInitialSnapshot(runId);
    setSnapshot(nextSnapshot);

    const stream = new EventSource(`/api/agent-runs/${runId}/stream`);
    stream.onmessage = (message) => {
      const event = JSON.parse(message.data) as AgentRunEvent;
      nextSnapshot = applyRunEvent(nextSnapshot, event);
      setSnapshot(nextSnapshot);
      if (event.state === "completed" || event.state === "failed") {
        stream.close();
      }
    };
    stream.onerror = () => stream.close();
  }

  const artifacts = useMemo(() => {
    const events = snapshot?.events ?? [];
    return {
      callPlan: events.find((event) => event.artifact?.kind === "callplan")?.artifact,
      executionResult: events.find((event) => event.artifact?.kind === "execution-result")?.artifact,
      reasoningFact: events.find((event) => event.artifact?.kind === "reasoning-fact")?.artifact,
      agentTraceId: events.find((event) => event.agentTraceId)?.agentTraceId,
      gatewayTraceId: events.find((event) => event.gatewayTraceId)?.gatewayTraceId
    };
  }, [snapshot]);

  return (
    <div className="workbench-grid">
      <section className="hero-panel">
        <p className="eyebrow">Harness Engineering Console</p>
        <h1>SAP Nexus Agent Workbench</h1>
        <textarea value={query} onChange={(event) => setQuery(event.target.value)} />
        <button onClick={runAgent}>启动 Agent Run</button>
      </section>

      <section className="panel">
        <h2>Runtime Timeline</h2>
        <RuntimeTimeline events={snapshot?.events ?? []} />
      </section>

      <HumanApprovalPanel state={snapshot?.hitlState ?? "approval_not_required"} />
      <TraceAuditPanel agentTraceId={artifacts.agentTraceId} gatewayTraceId={artifacts.gatewayTraceId} />
      <CallPlanPanel artifact={artifacts.callPlan} />
      <ExecutionResultPanel artifact={artifacts.executionResult} />
      <ReasoningFactPanel artifact={artifacts.reasoningFact} />
    </div>
  );
}
```

- [x] **Step 6: Wire page to console**

Modify `frontend/app/workbench/page.tsx`:

```tsx
import { AgentConsole } from "@/modules/agent-console/AgentConsole";

export default function WorkbenchPage() {
  return <AgentConsole />;
}
```

- [x] **Step 7: Add CSS for modules**

Extend `frontend/app/globals.css`:

```css
.workbench-grid {
  display: grid;
  grid-template-columns: minmax(18rem, 0.95fr) minmax(22rem, 1.4fr);
  gap: 1rem;
  padding: 2rem;
}

.hero-panel,
.panel,
.artifact-card {
  border: 1px solid rgba(35, 53, 44, 0.26);
  border-radius: 24px;
  background: var(--panel);
  box-shadow: 0 24px 70px rgba(23, 32, 27, 0.14);
  padding: 1.25rem;
}

.eyebrow {
  color: var(--accent);
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

textarea {
  width: 100%;
  min-height: 8rem;
  border: 1px solid var(--line);
  border-radius: 18px;
  padding: 1rem;
  background: rgba(255, 255, 255, 0.54);
}

button {
  margin-top: 1rem;
  border: 0;
  border-radius: 999px;
  background: var(--line);
  color: var(--paper);
  padding: 0.8rem 1.2rem;
}

.timeline {
  list-style: none;
  margin: 0;
  padding: 0;
}

.timeline li {
  display: grid;
  grid-template-columns: 3rem 1fr 1fr;
  gap: 0.75rem;
  border-bottom: 1px solid rgba(35, 53, 44, 0.12);
  padding: 0.7rem 0;
}

.sequence {
  color: var(--accent);
}

pre {
  overflow: auto;
  max-height: 20rem;
}

.muted {
  color: rgba(23, 32, 27, 0.58);
}

@media (max-width: 900px) {
  .workbench-grid {
    grid-template-columns: 1fr;
    padding: 1rem;
  }
}
```

- [x] **Step 8: Run frontend checks**

Run:

```bash
npm --prefix frontend run typecheck
npm --prefix frontend run test
npm --prefix frontend run build
```

Expected: all commands pass.

## Task 6: OpenSpec Tasks, Runbook, And Regression Verification

**Files:**
- Modify: `openspec/changes/sap-nexus-agent-workbench-console/tasks.md`
- Modify: `docs/runbooks/03-agent-workbench-console.md`

- [x] **Step 1: Mark completed OpenSpec tasks**

After Tasks 1-5 pass verification, update `openspec/changes/sap-nexus-agent-workbench-console/tasks.md` by changing completed items from `- [ ]` to `- [x]`.

Do not mark task `5.4`, `5.5`, or `5.6` complete until the exact commands and runbook update below are done.

- [x] **Step 2: Run Agent regression**

Run:

```bash
scripts/verify-agent-callplan-evidence.sh
```

Expected:

```text
38 passed, 1 skipped
Eval passed: 7/7
Totals: 3 passed, 0 failed (3 items)
```

The OpenSpec total may be `3 passed` while this change is active.

- [x] **Step 3: Run OpenSpec strict validation**

Run:

```bash
openspec validate --all --strict
```

Expected:

```text
✓ spec/agent-callplan-evidence
✓ spec/capability-registry-gateway
✓ change/sap-nexus-agent-workbench-console
Totals: 3 passed, 0 failed (3 items)
```

PostHog network flush errors are non-blocking if the command exits 0 and validation passes.

- [x] **Step 4: Append runbook closeout**

Append to `docs/runbooks/03-agent-workbench-console.md`:

```md
## Session Closeout - 2026-06-20

### Completed

- Created and implemented OpenSpec / Comet change `sap-nexus-agent-workbench-console`.
- Added local-first `frontend/` Agent Workbench Console with SSE runtime visualization, redacted artifact panels, trace metadata, and HITL state skeleton.

### Verified

- Command: `npm --prefix frontend run typecheck`
- Result: passed
- Command: `npm --prefix frontend run test`
- Result: passed
- Command: `npm --prefix frontend run build`
- Result: passed
- Command: `scripts/verify-agent-callplan-evidence.sh`
- Result: passed
- Command: `openspec validate --all --strict`
- Result: passed

### Blockers

- None, unless frontend dependency installation or local runtime verification was blocked by network or environment constraints.

### Next Start Here

1. Review `frontend/README.md` and run the frontend verification commands.
2. Continue Comet verify for `sap-nexus-agent-workbench-console`.
3. Keep `sap-nexus-registry-ontology-contract` as the next recommended workstream after this change is verified and archived.
```

If any command fails or was skipped, write the actual result instead of the passing text.

- [x] **Step 5: Final status check**

Run:

```bash
git status --short -- sap-nexus-agent
```

Expected: changes are limited to Workbench frontend, OpenSpec/Comet artifacts, Design Doc, plan, and runbook.

Do not commit unless the user explicitly asks.

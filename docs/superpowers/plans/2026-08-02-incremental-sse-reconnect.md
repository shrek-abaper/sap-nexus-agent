---
change: sap-nexus-incremental-sse-reconnect
design-doc: docs/superpowers/specs/2026-08-02-incremental-sse-reconnect-design.md
base-ref: a7ac4d1ca69cc05f1bec1c3bc48efc7e323d039d
archived-with: 2026-08-02-sap-nexus-incremental-sse-reconnect
---

# Incremental SSE with Cursor Reconnect Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 SSE 传输从 buffered 一次性返回改造为增量发布 + cursor 重连，使客户端在 runner 执行期间即可收到事件，断线后可从最后收到事件的 sequence 续传。

**Architecture:** `createAgentRun` 改为立即返回 `runId` + 后台 fire-and-forget 执行 runner；事件构建从 array-return 改为 emitter-callback 模式，每事件立即 `appendEvent` 落盘；stream route 改为 `ReadableStream` 轮询 `load()` + `?cursor=N` 内存过滤；客户端 `AgentConsole.tsx` 记录 `lastSequence` 并在 `onerror` 时带 cursor 重连。

**Tech Stack:** Next.js 15.3.6 (App Router route handlers)、TypeScript、vitest (node environment)、Web `ReadableStream` API、`EventSource` (浏览器)。

**Design Doc:** `docs/superpowers/specs/2026-08-02-incremental-sse-reconnect-design.md` §1-§7

## Global Constraints

- 复用项1 的 `DurableRunStore.appendEvent`（per-event fsync）、`load`（全量重放 + sequence 排序）、`AgentRunEvent.sequence`，不向 `DurableRunStore` 添加任何新接口。
- 不触 Gateway / trusted principal / durable approval store / WebSocket 双向。
- terminal 事件为 `run_completed` 和 `run_failed`（`AgentRunEventType`），其他事件不是 terminal。
- `POLL_INTERVAL` = 50ms（stream route 轮询间隔）；`RECONNECT_DELAY` = 500ms（客户端重连间隔）。
- 测试用 vitest（`environment: "node"`，`include: ["src/**/*.test.ts"]`）；`npm --prefix frontend run verify` = typecheck + test + build。
- `sequence` 是单调递增整数，由 emitter 内部计数器分配，语义为事件在 run 内的序号。

archived-with: 2026-08-02-sap-nexus-incremental-sse-reconnect
---

## File Structure

| 文件 | 职责 | 动作 |
|------|------|------|
| `frontend/src/runtime/agent-runtime-adapter.ts` | 事件构建 emitter + createAgentRun/decideAgentRunApproval/confirmAgentRunBatch 后台执行 | Modify |
| `frontend/src/runtime/agent-runtime-adapter.test.ts` | adapter 单元测试 | Modify |
| `frontend/app/api/agent-runs/[runId]/stream/route.ts` | SSE stream route（轮询 + cursor + terminal 收敛 + 背压） | Modify |
| `frontend/src/runtime/stream-route.test.ts` | stream route 单元测试 | Create |
| `frontend/src/modules/agent-console/stream-helpers.ts` | `buildStreamUrl` / `lastEventSequence` / `RECONNECT_DELAY` 纯函数 | Create |
| `frontend/src/modules/agent-console/stream-helpers.test.ts` | stream helpers 单元测试 | Create |
| `frontend/src/modules/agent-console/AgentConsole.tsx` | 客户端 `streamAgentRun` reconnect + `decideApproval` cursor 传递 | Modify |

archived-with: 2026-08-02-sap-nexus-incremental-sse-reconnect
---

## Task 1: Emitter 转换 + rejection terminal 修复
- [x] Task 1: Emitter 转换 + rejection terminal 修复

**Design Doc:** §1.2（emitter 模式）、§4.4（rejection 追加 `run_failed`）、§7（早退分支事件发射）

**目标：** 将 `buildEventsFromOutcome` / `buildApprovalEvents` / `buildBatchEvents` 从返回 `AgentRunEvent[]` 改为接受 `emit` 回调的 async emitter；同步修复 `buildApprovalEvents` rejection 路径缺失 `run_failed` terminal 事件的问题。此 task 是纯重构（行为不变），唯一行为变更是 rejection 路径多一个 `run_failed` 事件。

**Files:**
- Modify: `frontend/src/runtime/agent-runtime-adapter.ts`
- Modify: `frontend/src/runtime/agent-runtime-adapter.test.ts`

**Interfaces:**
- Produces: `emitEventsFromOutcome(runId, query, outcome, timestamp, emit, nextSequence)` — async，从 `nextSequence` 开始递增分配 sequence，不 emit `run_started`（已由 `createAgentRun.save` 落盘）
- Produces: `emitApprovalEvents(record, outcome, timestamp, emit)` — async，从 `record.events.length + 1` 开始分配 sequence
- Produces: `emitBatchEvents(record, outcome, timestamp, emit)` — async，同上
- Produces: `AsyncPush = (event: Omit<AgentRunEvent, "runId" | "sequence" | "timestamp">) => Promise<void>` — 内部类型

- [x] **Step 1: Write the failing test — rejection emits run_failed terminal event**

在 `frontend/src/runtime/agent-runtime-adapter.test.ts` 的 `describe` 块末尾追加：

```typescript
it("rejection emits run_failed terminal event after approval_state_changed", async () => {
  const runner = vi.fn(async (input: any) => {
    if (input.continuation) {
      return {
        status: "rejected",
        callPlan: { capabilityId: "cap-1", kind: "Action", agentTraceId: "t" },
        validationResult: { success: true, capabilityId: "cap-1", traceId: "g" },
        approvalRecord: { id: "apr-1", status: "rejected" },
        responseText: "审批已拒绝"
      } as WorkbenchOutcome;
    }
    return {
      status: "awaiting_approval",
      callPlan: { capabilityId: "cap-1", kind: "Action", agentTraceId: "t" },
      validationResult: { success: true, capabilityId: "cap-1", traceId: "g" },
      approvalRecord: { id: "apr-1", status: "pending" },
      responseText: "待审批"
    } as WorkbenchOutcome;
  });
  setAgentRunnerForTests(runner);
  const { runId } = await createAgentRun({ query: "创建采购申请", conversationId: "c-reject" });
  await decideAgentRunApproval(runId, "reject");
  const events = await getAgentRunEvents(runId);
  const lastEvent = events[events.length - 1];
  expect(lastEvent.type).toBe("run_failed");
  expect(lastEvent.error?.errorType).toBe("APPROVAL_REJECTED");
});
```

- [x] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/runtime/agent-runtime-adapter.test.ts -t "rejection emits run_failed"`
Expected: FAIL — last event type is `approval_state_changed` (not `run_failed`)

- [x] **Step 3: Replace event builder functions with emitter versions**

在 `frontend/src/runtime/agent-runtime-adapter.ts` 中：

1. 在文件顶部类型区（`type AgentRunner` 之后）添加内部类型：

```typescript
type AsyncPush = (event: Omit<AgentRunEvent, "runId" | "sequence" | "timestamp">) => Promise<void>;
```

2. 将 `buildEventsFromOutcome` 函数（约 304-494 行）整体替换为 `emitEventsFromOutcome`：

```typescript
async function emitEventsFromOutcome(
  runId: string,
  query: string,
  outcome: WorkbenchOutcome,
  timestamp: string,
  emit: (event: AgentRunEvent) => Promise<void>,
  nextSequence: number
): Promise<void> {
  let seq = nextSequence;
  const push: AsyncPush = async (event) => {
    await emit({ runId, sequence: seq, timestamp, ...event });
    seq++;
  };

  const callPlan = objectOrNull(outcome.callPlan);
  const validation = objectOrNull(outcome.validationResult);
  const execution = objectOrNull(outcome.executionResult);
  const fact = objectOrNull(outcome.fact);
  const capabilityId = textValue(callPlan?.capabilityId) ?? textValue(validation?.capabilityId) ?? textValue(execution?.capabilityId);
  const agentTraceId = textValue(callPlan?.agentTraceId) ?? textValue(fact?.agentTraceId);
  const gatewayTraceId =
    textValue(outcome.gatewayTraceId) ?? textValue(execution?.traceId) ?? textValue(validation?.traceId);

  await push({
    type: "intent_parsed",
    state: "intent_parsed",
    capabilityId,
    artifact: redactArtifact({
      label: "IntentParseResult",
      kind: "intent",
      payload: toJsonValue({
        query,
        status: outcome.status,
        parameters: objectOrNull(callPlan?.parameters) ?? {},
        missingParameters: outcome.missingParameters ?? []
      })
    })
  });

  if (!callPlan) {
    await emitTerminalOutcome(push, outcome, agentTraceId, gatewayTraceId);
    return;
  }

  await push({
    type: "capability_selected",
    state: "capability_selected",
    capabilityId,
    artifact: redactArtifact({
      label: "Capability Selection",
      kind: "capability",
      payload: toJsonValue({ capabilityId, kind: callPlan.kind ?? "Function" })
    })
  });
  await push({
    type: "callplan_created",
    state: "callplan_created",
    capabilityId,
    agentTraceId,
    artifact: redactArtifact({ label: "CallPlan", kind: "callplan", payload: toJsonValue(callPlan) })
  });
  const isAction = callPlan.kind === "Action";
  if (!isAction) {
    await push({
      type: "approval_state_changed",
      state: "approval_checked",
      hitlState: "approval_not_required"
    });
  }

  if (validation) {
    await push({
      type: "gateway_validate_started",
      state: "validating",
      capabilityId,
      agentTraceId,
      gatewayTraceId: textValue(validation.traceId) ?? gatewayTraceId
    });
    await push({
      type: "gateway_validate_completed",
      state: "validating",
      capabilityId,
      agentTraceId,
      gatewayTraceId: textValue(validation.traceId) ?? gatewayTraceId,
      artifact: redactArtifact({ label: "Gateway Validation", kind: "validation", payload: toJsonValue(validation) })
    });
    if (validation.success === false) {
      await emitFailure(push, "validating", outcome);
      return;
    }
  }

  if (isAction && outcome.status === "awaiting_approval") {
    const approvalRecord = objectOrNull(outcome.approvalRecord);
    await push({
      type: "approval_state_changed",
      state: "awaiting_approval",
      hitlState: "approval_required"
    });
    await push({
      type: "approval_state_changed",
      state: "awaiting_approval",
      hitlState: "awaiting_human_approval",
      artifact: approvalRecord
        ? redactArtifact({
            label: "ApprovalRecord",
            kind: "approval",
            payload: toJsonValue(approvalRecord)
          })
        : undefined
    });
    return;
  }

  if (outcome.status === "awaiting_batch_confirm") {
    const combinations = outcome.combinations ?? null;
    await push({
      type: "batch_confirm_requested",
      state: "awaiting_batch_confirm",
      capabilityId,
      agentTraceId,
      artifact: combinations
        ? redactArtifact({
            label: "BatchCombinations",
            kind: "callplan",
            payload: toJsonValue({ combinations, callPlan })
          })
        : undefined
    });
    return;
  }

  if (execution) {
    await push({
      type: "gateway_execute_started",
      state: "executing",
      capabilityId,
      agentTraceId,
      gatewayTraceId: textValue(execution.traceId) ?? gatewayTraceId
    });
    await push({
      type: "gateway_execute_completed",
      state: "executing",
      capabilityId,
      agentTraceId,
      gatewayTraceId: textValue(execution.traceId) ?? gatewayTraceId,
      artifact: redactArtifact({ label: "ExecutionResult", kind: "execution-result", payload: toJsonValue(execution) })
    });
    if (execution.success === false) {
      await emitFailure(push, "executing", outcome);
      return;
    }
  }

  if (fact) {
    await push({
      type: "reasoning_fact_created",
      state: "fact_created",
      capabilityId,
      agentTraceId,
      gatewayTraceId,
      artifact: redactArtifact({ label: "ReasoningFact", kind: "reasoning-fact", payload: toJsonValue(fact) })
    });
  }

  if (outcome.responseText) {
    await push({
      type: "narrative_created",
      state: "narrated",
      artifact: redactArtifact({
        label: "Chinese Narrative",
        kind: "narrative",
        payload: toJsonValue({ text: outcome.responseText })
      })
    });
  }

  if (agentTraceId || gatewayTraceId) {
    await push({
      type: "trace_linked",
      state: "trace_linked",
      agentTraceId,
      gatewayTraceId,
      artifact: redactArtifact({
        label: "Trace Metadata",
        kind: "trace",
        payload: toJsonValue({ agentTraceId, gatewayTraceId, status: "linked" })
      })
    });
  }

  if (outcome.status === "success" || outcome.status === "clarification") {
    await push({ type: "run_completed", state: "completed" });
  } else {
    await emitFailure(push, "failed", outcome);
  }
}
```

3. 将 `pushTerminalOutcome` 替换为 `emitTerminalOutcome`：

```typescript
async function emitTerminalOutcome(
  push: AsyncPush,
  outcome: WorkbenchOutcome,
  agentTraceId?: string,
  gatewayTraceId?: string
): Promise<void> {
  await emitMatchDecisionEventIfPresent(push, outcome);

  if (outcome.responseText) {
    await push({
      type: "narrative_created",
      state: "narrated",
      artifact: redactArtifact({
        label: "Chinese Narrative",
        kind: "narrative",
        payload: toJsonValue({ text: outcome.responseText })
      })
    });
  }
  if (agentTraceId || gatewayTraceId) {
    await push({
      type: "trace_linked",
      state: "trace_linked",
      agentTraceId,
      gatewayTraceId,
      artifact: redactArtifact({
        label: "Trace Metadata",
        kind: "trace",
        payload: toJsonValue({ agentTraceId, gatewayTraceId })
      })
    });
  }
  if (outcome.status === "clarification") {
    await push({ type: "run_completed", state: "completed" });
  } else {
    await emitFailure(push, "intent_parsed", outcome);
  }
}
```

4. 将 `pushMatchDecisionEventIfPresent` 替换为 `emitMatchDecisionEventIfPresent`：

```typescript
async function emitMatchDecisionEventIfPresent(
  push: AsyncPush,
  outcome: WorkbenchOutcome
): Promise<void> {
  const matchDecision = objectOrNull(outcome.matchDecision);
  if (!matchDecision) {
    return;
  }
  const decisionType = textValue(matchDecision.decisionType);
  if (decisionType !== "SHOW_OPTIONS" && decisionType !== "ESCALATE_TO_PLANNER") {
    return;
  }
  const candidates = matchDecision.candidates ?? null;
  const handoff = matchDecision.handoff ?? null;
  const rationale = textValue(matchDecision.rationale) ?? "";
  const dryRun = objectOrNull(outcome.dryRun);
  await push({
    type: "match_decision_created",
    state: "match_decided",
    artifact: redactArtifact({
      label: "MatchDecision",
      kind: "match-decision",
      payload: toJsonValue({
        decisionType,
        candidates,
        handoff,
        rationale,
        dryRun
      })
    })
  });
}
```

5. 将 `pushFailure` 和 `pushFailureAll` 合并为 `emitFailure`：

```typescript
async function emitFailure(
  push: AsyncPush,
  stage: AgentRunState,
  outcome: WorkbenchOutcome
): Promise<void> {
  await push({
    type: "run_failed",
    state: "failed",
    error: {
      errorType: outcome.errorType || "AGENT_RUN_FAILED",
      message: outcome.responseText || outcome.message || "Agent run failed",
      stage
    }
  });
}
```

6. 将 `buildApprovalEvents` 替换为 `emitApprovalEvents`（含 §4.4 rejection 修复）：

```typescript
async function emitApprovalEvents(
  record: AgentRunRecord,
  outcome: WorkbenchOutcome,
  timestamp: string,
  emit: (event: AgentRunEvent) => Promise<void>
): Promise<void> {
  let seq = record.events.length + 1;
  const push: AsyncPush = async (event) => {
    await emit({ runId: record.runId, sequence: seq, timestamp, ...event });
    seq++;
  };
  const callPlan = objectOrNull(outcome.callPlan) ?? objectOrNull(record.pendingOutcome?.callPlan);
  const execution = objectOrNull(outcome.executionResult);
  const approvalRecord = objectOrNull(outcome.approvalRecord);
  const capabilityId = textValue(callPlan?.capabilityId);
  const agentTraceId = textValue(callPlan?.agentTraceId);
  const gatewayTraceId = textValue(outcome.gatewayTraceId) ?? textValue(execution?.traceId);

  if (outcome.status === "rejected") {
    await push({ type: "approval_state_changed", state: "rejected", hitlState: "rejected", capabilityId, agentTraceId,
      artifact: approvalRecord ? redactArtifact({ label: "ApprovalRecord", kind: "approval", payload: toJsonValue(approvalRecord) }) : undefined });
    // §4.4: append run_failed terminal so the stream can close on rejection
    await push({ type: "run_failed", state: "failed",
      error: { errorType: "APPROVAL_REJECTED", message: outcome.responseText || outcome.message || "Approval rejected", stage: "approval_checked" } });
    return;
  }
  const approvalStatus = textValue(approvalRecord?.status);
  if (approvalStatus !== "approved" && approvalStatus !== "executed") {
    await emitFailure(push, "approval_checked", outcome);
    return;
  }
  await push({ type: "approval_state_changed", state: "approval_checked", hitlState: "approved", capabilityId, agentTraceId,
    artifact: approvalRecord ? redactArtifact({ label: "ApprovalRecord", kind: "approval", payload: toJsonValue(approvalRecord) }) : undefined });
  if (execution) {
    await push({ type: "gateway_execute_started", state: "executing", capabilityId, agentTraceId, gatewayTraceId });
    await push({ type: "gateway_execute_completed", state: "executing", capabilityId, agentTraceId, gatewayTraceId,
      artifact: redactArtifact({ label: "ActionResult", kind: "execution-result", payload: toJsonValue(execution) }) });
  }
  if (outcome.responseText) {
    await push({ type: "narrative_created", state: "narrated",
      artifact: redactArtifact({ label: "Chinese Narrative", kind: "narrative", payload: toJsonValue({ text: outcome.responseText }) }) });
  }
  if (outcome.status === "success") {
    await push({ type: "run_completed", state: "completed", capabilityId, agentTraceId, gatewayTraceId });
  } else {
    await emitFailure(push, "executing", outcome);
  }
}
```

7. 将 `buildBatchEvents` 替换为 `emitBatchEvents`：

```typescript
async function emitBatchEvents(
  record: AgentRunRecord,
  outcome: WorkbenchOutcome,
  timestamp: string,
  emit: (event: AgentRunEvent) => Promise<void>
): Promise<void> {
  let seq = record.events.length + 1;
  const push: AsyncPush = async (event) => {
    await emit({ runId: record.runId, sequence: seq, timestamp, ...event });
    seq++;
  };
  const callPlan = objectOrNull(outcome.callPlan) ?? objectOrNull(record.pendingOutcome?.callPlan);
  const capabilityId = textValue(callPlan?.capabilityId);
  const agentTraceId = textValue(callPlan?.agentTraceId);
  const gatewayTraceId = textValue(outcome.gatewayTraceId);

  if (outcome.responseText) {
    await push({ type: "narrative_created", state: "narrated",
      artifact: redactArtifact({ label: "Chinese Narrative", kind: "narrative", payload: toJsonValue({ text: outcome.responseText }) }) });
  }
  if (outcome.status === "success") {
    await push({ type: "run_completed", state: "completed", capabilityId, agentTraceId, gatewayTraceId });
  } else {
    await emitFailure(push, "executing", outcome);
  }
}
```

8. 删除旧的 `push` 函数（同步 array-push 辅助）：

```typescript
// DELETE this function entirely:
// function push(events: AgentRunEvent[], runId: string, timestamp: string, event: Omit<AgentRunEvent, "runId" | "sequence" | "timestamp">) { ... }
```

- [x] **Step 4: Update callers to use emitter functions**

在 `createAgentRun` 的 `try` 块中，将：

```typescript
    const events = buildEventsFromOutcome(runId, query, outcome, timestamp);
    for (const event of events.slice(1)) {
      await runStore.appendEvent(runId, event);
    }
    record.events = events;
```

替换为：

```typescript
    await emitEventsFromOutcome(runId, query, outcome, timestamp,
      (event) => runStore.appendEvent(runId, event), 2);
```

在 `decideAgentRunApproval` 的 `try` 块中，将：

```typescript
    const newEvents = buildApprovalEvents(record, outcome, new Date().toISOString());
    for (const event of newEvents) {
      await runStore.appendEvent(runId, event);
    }
```

替换为：

```typescript
    await emitApprovalEvents(record, outcome, new Date().toISOString(),
      (event) => runStore.appendEvent(runId, event));
```

在 `confirmAgentRunBatch` 的 `try` 块中，将：

```typescript
    const newEvents = buildBatchEvents(record, outcome, new Date().toISOString());
    for (const event of newEvents) {
      await runStore.appendEvent(runId, event);
    }
```

替换为：

```typescript
    await emitBatchEvents(record, outcome, new Date().toISOString(),
      (event) => runStore.appendEvent(runId, event));
```

- [x] **Step 5: Run rejection test to verify it passes**

Run: `cd frontend && npx vitest run src/runtime/agent-runtime-adapter.test.ts -t "rejection emits run_failed"`
Expected: PASS

- [x] **Step 6: Run all adapter tests to verify no regression**

Run: `cd frontend && npx vitest run src/runtime/agent-runtime-adapter.test.ts`
Expected: PASS — all existing tests pass (行为不变，rejection 多一个事件但不影响现有断言)

- [x] **Step 7: Commit**

```bash
git add frontend/src/runtime/agent-runtime-adapter.ts frontend/src/runtime/agent-runtime-adapter.test.ts
git commit -m "refactor: convert event builders to emitter pattern + add run_failed on rejection

- buildEventsFromOutcome/buildApprovalEvents/buildBatchEvents -> emit* versions
- emit callback replaces array-return; each event emitted via async push
- §4.4: rejection path now appends run_failed terminal event
Co-Authored-By: Claude <noreply@anthropic.com>"
```

archived-with: 2026-08-02-sap-nexus-incremental-sse-reconnect
---

## Task 2: createAgentRun 后台执行
- [x] Task 2: createAgentRun 后台执行

**Design Doc:** §1.1（createAgentRun 立即返回 runId + 后台执行 runner）

**目标：** `createAgentRun` 在 `save(run_started)` + `claim` 之后立即返回 `{ runId }`，runner 在后台 fire-and-forget 执行。客户端打开 stream 时即可收到 `run_started`（sequence=1），runner 执行期间增量收到后续事件。

**Files:**
- Modify: `frontend/src/runtime/agent-runtime-adapter.ts`
- Modify: `frontend/src/runtime/agent-runtime-adapter.test.ts`

**Interfaces:**
- Consumes: `emitEventsFromOutcome` from Task 1
- Produces: `executeRunnerInBackground(runId, query, conversationId, timestamp)` — async，fire-and-forget；调用方用 `void` 启动

- [x] **Step 1: Add waitForRunSettled test helper**

在 `frontend/src/runtime/agent-runtime-adapter.test.ts` 的 `describe` 块之前添加：

```typescript
async function waitForRunSettled(runId: string, timeoutMs = 5000): Promise<AgentRunEvent[]> {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const events = await getAgentRunEvents(runId);
    if (events.length > 0) {
      const last = events[events.length - 1];
      if (last.type === "run_completed" || last.type === "run_failed" ||
          last.state === "awaiting_approval" || last.state === "awaiting_batch_confirm" ||
          last.state === "rejected") {
        return events;
      }
    }
    await new Promise((resolve) => setTimeout(resolve, 10));
  }
  throw new Error(`Run ${runId} did not settle within ${timeoutMs}ms`);
}
```

在 import 块中添加 `AgentRunEvent` 类型导入：

```typescript
import type { AgentRunEvent } from "./run-event-schema";
```

- [x] **Step 2: Write failing test — createAgentRun returns before runner completes**

在 `describe` 块末尾追加：

```typescript
it("createAgentRun returns runId before runner produces non-started events", async () => {
  let runnerResolved = false;
  setAgentRunnerForTests(async () => {
    await new Promise((resolve) => setTimeout(resolve, 100));
    runnerResolved = true;
    return { status: "success", responseText: "完成" } as WorkbenchOutcome;
  });
  const { runId } = await createAgentRun({ query: "查询库存" });
  // run_started (sequence=1) is already persisted before return
  const events = await getAgentRunEvents(runId);
  expect(events.length).toBe(1);
  expect(events[0].type).toBe("run_started");
  expect(runnerResolved).toBe(false);
  // after waiting, more events appear
  const settled = await waitForRunSettled(runId);
  expect(settled.some((e) => e.type === "run_completed")).toBe(true);
});
```

- [x] **Step 3: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/runtime/agent-runtime-adapter.test.ts -t "returns runId before runner"`
Expected: FAIL — `createAgentRun` currently awaits runner; `events.length` is > 1 and `runnerResolved` is true

- [x] **Step 4: Extract executeRunnerInBackground and make createAgentRun return immediately**

在 `frontend/src/runtime/agent-runtime-adapter.ts` 中：

1. 添加 `executeRunnerInBackground` 函数（在 `createAgentRun` 之后）：

```typescript
async function executeRunnerInBackground(
  runId: string,
  query: string,
  conversationId: string | undefined,
  timestamp: string
): Promise<void> {
  try {
    const runner = runnerForTests ?? runLocalPythonAgent;
    const context = conversationId ? buildContext(await getSession(conversationId)) : undefined;
    const outcome = await runner({ query, gatewayUrl: gatewayUrl(), intentMode: intentMode(), context });
    await emitEventsFromOutcome(runId, query, outcome, timestamp,
      (event) => runStore.appendEvent(runId, event), 2);

    if (outcome.status === "awaiting_approval" || outcome.status === "awaiting_batch_confirm") {
      await runStore.appendPendingOutcome(runId, outcome);
    }

    if (conversationId) {
      const session = await getSession(conversationId);
      session.lastRunId = runId;
      session.history.push({ role: "user", content: query });
      if (outcome.responseText) {
        session.history.push({ role: "assistant", content: outcome.responseText });
      }
      session.lastContext = outcome.lastContext ?? null;
      await conversationStore.save(conversationId, session);
    }

    await runStore.release(runId, workerId);
  } catch (error) {
    const currentRecord = await runStore.load(runId);
    const baseSeq = currentRecord?.events.length ?? 1;
    const failEvents = buildRuntimeFailureEventsTail(runId, baseSeq, new Date().toISOString(), error);
    for (const event of failEvents) {
      await runStore.appendEvent(runId, event);
    }
    await runStore.release(runId, workerId);
  }
}
```

2. 将 `createAgentRun` 的 `try { ... } catch { ... }` 块（约 129-163 行）替换为：

```typescript
  // §1.1: fire-and-forget background execution; return runId immediately
  void executeRunnerInBackground(runId, query, input.conversationId, timestamp);

  return { runId };
```

3. 删除 `buildRuntimeFailureEvents` 函数（已无调用方）：

```typescript
// DELETE this function:
// function buildRuntimeFailureEvents(runId: string, timestamp: string, error: unknown): AgentRunEvent[] { ... }
```

- [x] **Step 5: Run the new test to verify it passes**

Run: `cd frontend && npx vitest run src/runtime/agent-runtime-adapter.test.ts -t "returns runId before runner"`
Expected: PASS

- [x] **Step 6: Adapt existing tests for async background**

在 `frontend/src/runtime/agent-runtime-adapter.test.ts` 中，修改以下测试：

1. `"pending approval run recovers across store reset"` — 在 `createAgentRun` 之后、`reopenedRun` 之前加 `await waitForRunSettled(runId);`

2. `"Q2 gate rejects new query while prior approval pending"` — 在第一个 `createAgentRun` 之后加 `await waitForRunSettled(runId);`（需要捕获 runId）

3. `"decideAgentRunApproval loads from store and appends decision events"` — 在 `decideAgentRunApproval` 之后加 `await waitForRunSettled(target.runId);`

4. `"resetAgentRunsForTests clears durable runs"` — 在 `createAgentRun` 之后、`resetAgentRunsForTests()` 之前加 `await waitForRunSettled(runId);`

5. `"resetAgentSessionsForTests clears durable sessions"` — 在 `createAgentRun` 之后加 `await waitForRunSettled(runId);`（需要捕获 runId）

6. `"duplicate approve continuation is idempotent (executes once)"` — 在 `decideAgentRunApproval` 之后加 `await waitForRunSettled(runId);`

7. `"duplicate batch confirm continuation is idempotent (executes once)"` — 在 `confirmAgentRunBatch` 之后加 `await waitForRunSettled(runId);`

- [x] **Step 7: Run all adapter tests**

Run: `cd frontend && npx vitest run src/runtime/agent-runtime-adapter.test.ts`
Expected: PASS — all tests pass

- [x] **Step 8: Commit**

```bash
git add frontend/src/runtime/agent-runtime-adapter.ts frontend/src/runtime/agent-runtime-adapter.test.ts
git commit -m "feat: createAgentRun returns runId immediately with background runner execution

- extract executeRunnerInBackground; fire-and-forget via void
- run_started (seq=1) persisted before return; client can open stream immediately
- add waitForRunSettled test helper; adapt existing tests for async
- remove unused buildRuntimeFailureEvents
Co-Authored-By: Claude <noreply@anthropic.com>"
```

archived-with: 2026-08-02-sap-nexus-incremental-sse-reconnect
---

## Task 3: Continuation 路径后台执行
- [x] Task 3: Continuation 路径后台执行

**Design Doc:** §1.3（decideAgentRunApproval / confirmAgentRunBatch 后台执行）

**目标：** `decideAgentRunApproval` 和 `confirmAgentRunBatch` 在校验 + claim + appendDecision 后立即返回，runner 在后台执行。客户端用 `?cursor=N` 重连获取 continuation 事件。

**Files:**
- Modify: `frontend/src/runtime/agent-runtime-adapter.ts`
- Modify: `frontend/src/runtime/agent-runtime-adapter.test.ts`

**Interfaces:**
- Consumes: `emitApprovalEvents` / `emitBatchEvents` from Task 1
- Produces: `executeApprovalInBackground(runId, record, decision, callPlan, validationResult, approvalRecord, idemKey)` — async fire-and-forget
- Produces: `executeBatchInBackground(runId, record, callPlan, combinations, idemKey)` — async fire-and-forget

- [x] **Step 1: Write failing test — decideAgentRunApproval returns before runner completes**

在 `frontend/src/runtime/agent-runtime-adapter.test.ts` 的 `describe` 块末尾追加：

```typescript
it("decideAgentRunApproval returns before continuation runner completes", async () => {
  let continuationResolved = false;
  setAgentRunnerForTests(async (input: any) => {
    if (input.continuation) {
      await new Promise((resolve) => setTimeout(resolve, 100));
      continuationResolved = true;
      return { status: "success", responseText: "已执行", approvalRecord: { id: "apr-1", status: "executed" } } as WorkbenchOutcome;
    }
    return awaitingOutcome("run-1");
  });
  const { runId } = await createAgentRun({ query: "查询库存", conversationId: "c-async-approval" });
  await waitForRunSettled(runId);
  expect(continuationResolved).toBe(false);
  await decideAgentRunApproval(runId, "approve");
  // decideAgentRunApproval returns immediately; continuation not yet done
  expect(continuationResolved).toBe(false);
  const settled = await waitForRunSettled(runId);
  expect(settled.some((e) => e.type === "run_completed")).toBe(true);
});
```

- [x] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/runtime/agent-runtime-adapter.test.ts -t "returns before continuation runner"`
Expected: FAIL — `decideAgentRunApproval` currently awaits runner; `continuationResolved` is true

- [x] **Step 3: Extract background functions and make continuation paths return immediately**

在 `frontend/src/runtime/agent-runtime-adapter.ts` 中：

1. 添加 `executeApprovalInBackground` 函数（在 `decideAgentRunApproval` 之后）：

```typescript
async function executeApprovalInBackground(
  runId: string,
  record: AgentRunRecord,
  decision: ApprovalDecision,
  callPlan: Record<string, unknown>,
  validationResult: Record<string, unknown>,
  approvalRecord: Record<string, unknown>,
  idemKey: string
): Promise<void> {
  try {
    const runner = runnerForTests ?? runLocalPythonAgent;
    const outcome = await runner({
      query: record.query,
      gatewayUrl: gatewayUrl(),
      intentMode: intentMode(),
      continuation: { decision, callPlan, validationResult, approvalRecord }
    });
    await emitApprovalEvents(record, outcome, new Date().toISOString(),
      (event) => runStore.appendEvent(runId, event));
    await runStore.markExecuted(idemKey, outcome);
    if (outcome.status === "awaiting_approval" || outcome.status === "awaiting_batch_confirm") {
      await runStore.release(runId, workerId);
    }
  } catch (error) {
    const currentRecord = await runStore.load(runId);
    const baseSeq = currentRecord?.events.length ?? record.events.length;
    const failEvents = buildRuntimeFailureEventsTail(runId, baseSeq, new Date().toISOString(), error);
    for (const event of failEvents) {
      await runStore.appendEvent(runId, event);
    }
    await runStore.release(runId, workerId);
  }
}
```

2. 添加 `executeBatchInBackground` 函数（在 `confirmAgentRunBatch` 之后）：

```typescript
async function executeBatchInBackground(
  runId: string,
  record: AgentRunRecord,
  callPlan: Record<string, unknown>,
  combinations: Record<string, string>[],
  idemKey: string
): Promise<void> {
  try {
    const runner = runnerForTests ?? runLocalPythonAgent;
    const outcome = await runner({
      query: record.query,
      gatewayUrl: gatewayUrl(),
      intentMode: intentMode(),
      continuation: { type: "batch", callPlan, combinations }
    });
    await emitBatchEvents(record, outcome, new Date().toISOString(),
      (event) => runStore.appendEvent(runId, event));
    await runStore.markExecuted(idemKey, outcome);
    if (outcome.status === "awaiting_approval" || outcome.status === "awaiting_batch_confirm") {
      await runStore.release(runId, workerId);
    }
  } catch (error) {
    const currentRecord = await runStore.load(runId);
    const baseSeq = currentRecord?.events.length ?? record.events.length;
    const failEvents = buildRuntimeFailureEventsTail(runId, baseSeq, new Date().toISOString(), error);
    for (const event of failEvents) {
      await runStore.appendEvent(runId, event);
    }
    await runStore.release(runId, workerId);
  }
}
```

3. 将 `decideAgentRunApproval` 的 `try { ... } catch { ... }` 块（约 211-233 行）替换为：

```typescript
  // §1.3: fire-and-forget background execution; return immediately
  void executeApprovalInBackground(runId, record, decision, callPlan, validationResult, approvalRecord, idemKey);
```

4. 将 `confirmAgentRunBatch` 的 `try { ... } catch { ... }` 块（约 271-293 行）替换为：

```typescript
  // §1.3: fire-and-forget background execution; return immediately
  void executeBatchInBackground(runId, record, callPlan, combinations, idemKey);
```

- [x] **Step 4: Run the new test to verify it passes**

Run: `cd frontend && npx vitest run src/runtime/agent-runtime-adapter.test.ts -t "returns before continuation runner"`
Expected: PASS

- [x] **Step 5: Run all adapter tests**

Run: `cd frontend && npx vitest run src/runtime/agent-runtime-adapter.test.ts`
Expected: PASS

- [x] **Step 6: Commit**

```bash
git add frontend/src/runtime/agent-runtime-adapter.ts frontend/src/runtime/agent-runtime-adapter.test.ts
git commit -m "feat: decideAgentRunApproval/confirmAgentRunBatch return immediately with background runner

- extract executeApprovalInBackground / executeBatchInBackground
- continuation paths fire-and-forget after claim + appendDecision
- client reconnects with ?cursor=N to receive continuation events
Co-Authored-By: Claude <noreply@anthropic.com>"
```

archived-with: 2026-08-02-sap-nexus-incremental-sse-reconnect
---

## Task 4: Stream route cursor + 轮询 + terminal 收敛 + 背压
- [x] Task 4: Stream route cursor + 轮询 + terminal 收敛 + 背压

**Design Doc:** §1.4（stream route 轮询 live stream）、§2（cursor = sequence）、§3（reconnect replay）、§4.1-§4.3（terminal 收敛）、§5（背压策略）

**目标：** 将 stream route 从一次性返回改为 `ReadableStream` 轮询模式：解析 `?cursor=N`，轮询 `getAgentRunEvents` 发现新事件即推送，terminal 事件后关闭 stream，`controller.desiredSize <= 0` 时暂停推送实现背压。

**Files:**
- Modify: `frontend/app/api/agent-runs/[runId]/stream/route.ts`
- Create: `frontend/src/runtime/stream-route.test.ts`

**Interfaces:**
- Consumes: `getAgentRunEvents(runId)` from `agent-runtime-adapter`（返回 `AgentRunEvent[]`，按 sequence 升序）
- Produces: `GET(request, { params })` — 返回 `Response` with `ReadableStream` body；`?cursor=N` 过滤 `sequence > N`

- [x] **Step 1: Create stream route test file with terminal replay test**

创建 `frontend/src/runtime/stream-route.test.ts`：

```typescript
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { GET } from "../../app/api/agent-runs/[runId]/stream/route";
import {
  createAgentRun,
  getAgentRunEvents,
  resetAgentRunsForTests,
  resetAgentSessionsForTests,
  setAgentRunnerForTests,
  setDurableStoresForTests
} from "./agent-runtime-adapter";
import { JsonlConversationStore } from "./durable/jsonl-conversation-store";
import { JsonlRunStore } from "./durable/jsonl-run-store";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import type { AgentRunEvent } from "./run-event-schema";
import type { WorkbenchOutcome } from "./durable/types";

async function waitForRunSettled(runId: string, timeoutMs = 5000): Promise<AgentRunEvent[]> {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const events = await getAgentRunEvents(runId);
    if (events.length > 0) {
      const last = events[events.length - 1];
      if (last.type === "run_completed" || last.type === "run_failed" ||
          last.state === "awaiting_approval" || last.state === "awaiting_batch_confirm" ||
          last.state === "rejected") {
        return events;
      }
    }
    await new Promise((resolve) => setTimeout(resolve, 10));
  }
  throw new Error(`Run ${runId} did not settle within ${timeoutMs}ms`);
}

function parseSseChunks(text: string): AgentRunEvent[] {
  return text
    .split("\n\n")
    .filter((chunk) => chunk.trim())
    .map((chunk) => {
      const dataLine = chunk.split("\n").find((line) => line.startsWith("data: "));
      return JSON.parse(dataLine!.slice(6)) as AgentRunEvent;
    });
}

async function readStream(response: Response): Promise<string> {
  const reader = response.body!.getReader();
  const decoder = new TextDecoder();
  let text = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    text += decoder.decode(value, { stream: true });
  }
  return text;
}

function request(runId: string, cursor?: number): Request {
  const url = cursor !== undefined
    ? `http://localhost/api/agent-runs/${runId}/stream?cursor=${cursor}`
    : `http://localhost/api/agent-runs/${runId}/stream`;
  return new Request(url);
}

describe("stream route", () => {
  let dir: string;
  let runStore: JsonlRunStore;
  let convStore: JsonlConversationStore;

  beforeEach(() => {
    dir = mkdtempSync(path.join(tmpdir(), "stream-"));
    runStore = new JsonlRunStore(dir);
    convStore = new JsonlConversationStore(dir);
    setDurableStoresForTests(runStore, convStore);
  });
  afterEach(() => {
    setAgentRunnerForTests(null);
    setDurableStoresForTests(
      new JsonlRunStore(mkdtempSync(path.join(tmpdir(), "teardown-"))),
      new JsonlConversationStore(mkdtempSync(path.join(tmpdir(), "teardown-")))
    );
    rmSync(dir, { recursive: true, force: true });
  });

  it("replays all events for a terminal run and closes stream", async () => {
    setAgentRunnerForTests(async () =>
      ({ status: "success", responseText: "完成" } as WorkbenchOutcome));
    const { runId } = await createAgentRun({ query: "查询库存" });
    await waitForRunSettled(runId);

    const response = await GET(request(runId), { params: Promise.resolve({ runId }) });
    expect(response.status).toBe(200);
    expect(response.headers.get("Content-Type")).toBe("text/event-stream; charset=utf-8");

    const text = await readStream(response);
    const events = parseSseChunks(text);
    expect(events.length).toBeGreaterThan(0);
    expect(events[0].type).toBe("run_started");
    expect(events[events.length - 1].type).toBe("run_completed");
  });

  it("filters events by cursor (sequence > cursor)", async () => {
    setAgentRunnerForTests(async () =>
      ({ status: "success", responseText: "完成" } as WorkbenchOutcome));
    const { runId } = await createAgentRun({ query: "查询库存" });
    const settled = await waitForRunSettled(runId);
    // cursor = 2: only events with sequence > 2
    const response = await GET(request(runId, 2), { params: Promise.resolve({ runId }) });
    const text = await readStream(response);
    const events = parseSseChunks(text);
    expect(events.every((e) => e.sequence > 2)).toBe(true);
    expect(events[events.length - 1].type).toBe("run_completed");
  });

  it("returns 404 for unknown run", async () => {
    const response = await GET(request("run-missing"), { params: Promise.resolve({ runId: "run-missing" }) });
    expect(response.status).toBe(404);
  });

  it("returns 400 for invalid cursor", async () => {
    const response = await GET(request("run-x", -1 as unknown as number), {
      params: Promise.resolve({ runId: "run-x" })
    });
    expect(response.status).toBe(400);
    const negativeResponse = await GET(
      new Request("http://localhost/api/agent-runs/run-x/stream?cursor=abc"),
      { params: Promise.resolve({ runId: "run-x" }) }
    );
    expect(negativeResponse.status).toBe(400);
  });

  it("closes stream immediately when cursor >= terminal sequence", async () => {
    setAgentRunnerForTests(async () =>
      ({ status: "success", responseText: "完成" } as WorkbenchOutcome));
    const { runId } = await createAgentRun({ query: "查询库存" });
    const settled = await waitForRunSettled(runId);
    const terminalSeq = settled[settled.length - 1].sequence;
    const response = await GET(request(runId, terminalSeq), { params: Promise.resolve({ runId }) });
    const text = await readStream(response);
    // no new events; stream closes immediately
    expect(text).toBe("");
  });
});
```

- [x] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/runtime/stream-route.test.ts`
Expected: FAIL — current route returns buffered string, not a stream; no cursor parsing

- [x] **Step 3: Rewrite stream route as polling ReadableStream**

将 `frontend/app/api/agent-runs/[runId]/stream/route.ts` 全文替换为：

```typescript
import { getAgentRunEvents } from "@/runtime/agent-runtime-adapter";
import type { AgentRunEvent } from "@/runtime/run-event-schema";

const POLL_INTERVAL = 50;
const encoder = new TextEncoder();

function isTerminal(event: AgentRunEvent): boolean {
  return event.type === "run_completed" || event.type === "run_failed";
}

export async function GET(request: Request, { params }: { params: Promise<{ runId: string }> }) {
  const { runId } = await params;

  // §3.1: cursor query parameter parsing and validation
  const url = new URL(request.url);
  const cursorParam = url.searchParams.get("cursor");
  let cursor = 0;
  if (cursorParam !== null) {
    const parsed = Number(cursorParam);
    if (!Number.isInteger(parsed) || parsed < 0) {
      return new Response("Invalid cursor", { status: 400 });
    }
    cursor = parsed;
  }

  // Initial existence check (run must have at least run_started)
  const initialEvents = await getAgentRunEvents(runId);
  if (initialEvents.length === 0) {
    return new Response("Run not found", { status: 404 });
  }

  let lastCursor = cursor;
  let cancelled = false;
  let timeoutId: ReturnType<typeof setTimeout> | undefined;

  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      const poll = async () => {
        if (cancelled) return;
        try {
          const events = await getAgentRunEvents(runId);
          if (events.length === 0) {
            controller.close();
            return;
          }
          // §3.2: replay filtered by sequence > cursor
          const newEvents = events.filter((e) => e.sequence > lastCursor);
          for (const event of newEvents) {
            // §5.1: backpressure - stop enqueuing if internal buffer is full
            if (controller.desiredSize !== null && controller.desiredSize <= 0) {
              break;
            }
            const chunk = `event: ${event.type}\ndata: ${JSON.stringify(event)}\n\n`;
            controller.enqueue(encoder.encode(chunk));
            lastCursor = event.sequence;
          }
          // §4.2: close stream after terminal event is sent
          const lastEvent = events[events.length - 1];
          if (isTerminal(lastEvent)) {
            controller.close();
            return;
          }
          // §1.4: poll for new events
          timeoutId = setTimeout(() => { void poll(); }, POLL_INTERVAL);
        } catch {
          controller.close();
        }
      };
      void poll();
    },
    cancel() {
      cancelled = true;
      if (timeoutId) clearTimeout(timeoutId);
    }
  });

  return new Response(stream, {
    headers: {
      "Content-Type": "text/event-stream; charset=utf-8",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive"
    }
  });
}
```

- [x] **Step 4: Run stream route tests to verify they pass**

Run: `cd frontend && npx vitest run src/runtime/stream-route.test.ts`
Expected: PASS

- [x] **Step 5: Commit**

```bash
git add frontend/app/api/agent-runs/[runId]/stream/route.ts frontend/src/runtime/stream-route.test.ts
git commit -m "feat: stream route with polling, cursor replay, terminal close, backpressure

- ReadableStream polls getAgentRunEvents every 50ms
- ?cursor=N filters sequence > cursor for reconnect replay
- terminal event (run_completed/run_failed) closes stream
- desiredSize check provides backpressure; cursor reconnect is safety net
- 404 for unknown run, 400 for invalid cursor
Co-Authored-By: Claude <noreply@anthropic.com>"
```

archived-with: 2026-08-02-sap-nexus-incremental-sse-reconnect
---

## Task 5: 客户端 reconnect
- [x] Task 5: 客户端 reconnect

**Design Doc:** §6（客户端 reconnect — last sequence + onerror ?cursor=N 重连）

**目标：** `AgentConsole.tsx` 的 `streamAgentRun` 记录 `lastSequence`，`onerror` 时用 `?cursor=lastSequence` 重连；`decideApproval` 传递 cursor 获取 continuation 事件。

**Files:**
- Create: `frontend/src/modules/agent-console/stream-helpers.ts`
- Create: `frontend/src/modules/agent-console/stream-helpers.test.ts`
- Modify: `frontend/src/modules/agent-console/AgentConsole.tsx`

**Interfaces:**
- Produces: `buildStreamUrl(serverRunId, cursor)` — 返回 `/api/agent-runs/${serverRunId}/stream?cursor=${cursor}`
- Produces: `lastEventSequence(events)` — 返回 events 中最大 sequence，空数组返回 0
- Produces: `RECONNECT_DELAY` = 500

- [x] **Step 1: Create stream-helpers test file**

创建 `frontend/src/modules/agent-console/stream-helpers.test.ts`：

```typescript
import { describe, expect, it } from "vitest";
import { buildStreamUrl, lastEventSequence, RECONNECT_DELAY } from "./stream-helpers";
import type { AgentRunEvent } from "@/runtime/run-event-schema";

describe("stream helpers", () => {
  it("buildStreamUrl includes cursor parameter", () => {
    expect(buildStreamUrl("run-123", 0)).toBe("/api/agent-runs/run-123/stream?cursor=0");
    expect(buildStreamUrl("run-123", 5)).toBe("/api/agent-runs/run-123/stream?cursor=5");
  });

  it("lastEventSequence returns max sequence from unsorted events", () => {
    const events: AgentRunEvent[] = [
      { runId: "r1", sequence: 1, timestamp: "t", type: "run_started", state: "running" },
      { runId: "r1", sequence: 3, timestamp: "t", type: "run_completed", state: "completed" },
      { runId: "r1", sequence: 2, timestamp: "t", type: "intent_parsed", state: "intent_parsed" }
    ];
    expect(lastEventSequence(events)).toBe(3);
  });

  it("lastEventSequence returns 0 for empty events", () => {
    expect(lastEventSequence([])).toBe(0);
  });

  it("RECONNECT_DELAY is 500ms", () => {
    expect(RECONNECT_DELAY).toBe(500);
  });
});
```

- [x] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/modules/agent-console/stream-helpers.test.ts`
Expected: FAIL — module not found

- [x] **Step 3: Create stream-helpers module**

创建 `frontend/src/modules/agent-console/stream-helpers.ts`：

```typescript
import type { AgentRunEvent } from "@/runtime/run-event-schema";

export const RECONNECT_DELAY = 500;

export function buildStreamUrl(serverRunId: string, cursor: number): string {
  return `/api/agent-runs/${serverRunId}/stream?cursor=${cursor}`;
}

export function lastEventSequence(events: AgentRunEvent[]): number {
  return events.length > 0 ? Math.max(...events.map((e) => e.sequence)) : 0;
}
```

- [x] **Step 4: Run helper tests to verify they pass**

Run: `cd frontend && npx vitest run src/modules/agent-console/stream-helpers.test.ts`
Expected: PASS

- [x] **Step 5: Update AgentConsole.tsx streamAgentRun with cursor and reconnect**

在 `frontend/src/modules/agent-console/AgentConsole.tsx` 中：

1. 在 import 区块添加：

```typescript
import { buildStreamUrl, lastEventSequence, RECONNECT_DELAY } from "./stream-helpers";
```

2. 将 `streamAgentRun` 函数（约 60-102 行）替换为：

```typescript
  function streamAgentRun(
    localRunId: string,
    serverRunId: string,
    initialSnapshot: AgentRunSnapshot,
    cursor = 0
  ) {
    let nextSnapshot = initialSnapshot;
    let lastSequence = cursor;
    let intentionallyClosed = false;
    const stream = new EventSource(buildStreamUrl(serverRunId, cursor));
    const handleRunEvent = (message: MessageEvent<string>) => {
      const event = JSON.parse(message.data) as AgentRunEvent;
      if (nextSnapshot.events.some((existing) => existing.sequence === event.sequence)) {
        return;
      }
      lastSequence = event.sequence;
      nextSnapshot = applyRunEvent(nextSnapshot, event);
      setTurns((prev) =>
        prev.map((turn) => (turn.runId === localRunId ? { ...turn, snapshot: nextSnapshot } : turn))
      );
      const pausedForApproval = event.state === "awaiting_approval";
      const terminal = event.state === "completed" || event.state === "failed" || event.state === "rejected";
      if (pausedForApproval || terminal) {
        intentionallyClosed = true;
        stream.close();
        setTurns((prev) =>
          prev.map((turn) => (turn.runId === localRunId ? { ...turn, isRunning: false } : turn))
        );
      }
    };
    stream.onmessage = handleRunEvent;
    agentRunEventTypes.forEach((eventType) => stream.addEventListener(eventType, handleRunEvent));
    stream.onerror = () => {
      stream.close();
      if (intentionallyClosed) {
        return;
      }
      // §6.1: reconnect with cursor to resume from last received event
      setTimeout(() => {
        streamAgentRun(localRunId, serverRunId, nextSnapshot, lastSequence);
      }, RECONNECT_DELAY);
    };
  }
```

3. 在 `decideApproval` 函数中，将 `streamAgentRun(target.runId, serverRunId, target.snapshot)`（约 124 行）替换为：

```typescript
      const cursor = lastEventSequence(target.snapshot.events);
      streamAgentRun(target.runId, serverRunId, target.snapshot, cursor);
```

- [x] **Step 6: Run all tests + typecheck**

Run: `cd frontend && npx vitest run && npm run typecheck`
Expected: PASS — all tests pass, typecheck succeeds

- [x] **Step 7: Commit**

```bash
git add frontend/src/modules/agent-console/stream-helpers.ts \
  frontend/src/modules/agent-console/stream-helpers.test.ts \
  frontend/src/modules/agent-console/AgentConsole.tsx
git commit -m "feat: client reconnect with cursor in AgentConsole

- streamAgentRun tracks lastSequence; onerror reconnects with ?cursor=N
- decideApproval passes cursor for continuation events
- extract buildStreamUrl / lastEventSequence / RECONNECT_DELAY to stream-helpers
Co-Authored-By: Claude <noreply@anthropic.com>"
```

archived-with: 2026-08-02-sap-nexus-incremental-sse-reconnect
---

## Task 6: 回归验证 + openspec validate
- [x] Task 6: 回归验证 + openspec validate

**Design Doc:** §6 测试验证

**目标：** 全量回归验证，确保 typecheck + test + build 通过，openspec validate 通过。

**Files:** 无修改

- [x] **Step 1: Run full verify**

Run: `cd frontend && npm run verify`
Expected: typecheck PASS, test PASS, build PASS

- [x] **Step 2: Run openspec validate**

Run: `openspec validate --all --strict`
Expected: PASS

- [x] **Step 3: Run openspec list**

Run: `cd . && openspec list --json`
Expected: JSON output without errors

- [x] **Step 4: Run callplan evidence script**

Run: `cd . && scripts/verify-agent-callplan-evidence.sh`
Expected: PASS

- [x] **Step 5: Commit if any test fixtures were adjusted**

```bash
git status --short
# If any files changed during verification:
git add -A && git commit -m "test: adapt fixtures for incremental SSE regression

Co-Authored-By: Claude <noreply@anthropic.com>"
```

archived-with: 2026-08-02-sap-nexus-incremental-sse-reconnect
---

## Self-Review Checklist

**Spec coverage (§1-§7):**
- §1 增量发布 -> Task 1 (emitter) + Task 2 (createAgentRun background) + Task 3 (continuation background) + Task 4 (stream polling)
- §2 event cursor -> Task 4 (cursor = sequence，SSE payload 已包含 sequence via JSON.stringify)
- §3 reconnect replay -> Task 4 (?cursor=N + load() 全量重放 + 过滤 sequence > cursor)
- §4 terminal 收敛 -> Task 1 (§4.4 rejection run_failed fix) + Task 4 (§4.1-§4.3 stream close on terminal)
- §5 背压策略 -> Task 4 (desiredSize check + cursor reconnect 兜底)
- §6 客户端 reconnect -> Task 5 (lastSequence + onerror ?cursor=N 重连)
- §7 早退分支处理 -> Task 1 (emitter 早退分支 emit 正确事件) + Task 4 (stream 对各分支的行为)

**项1 依赖：** appendEvent + load + sequence，不向 DurableRunStore 添加新接口 -> 确认，所有 task 仅消费现有接口

**不触边界：** Gateway / trusted principal / durable approval store / WebSocket -> 确认，无相关修改


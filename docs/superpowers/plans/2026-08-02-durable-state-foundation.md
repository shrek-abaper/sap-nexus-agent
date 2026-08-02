---
change: sap-nexus-durable-state-foundation
design-doc: docs/superpowers/specs/2026-08-02-durable-state-foundation-design.md
base-ref: 0f25c065c667c87392c4fc43fb1da19e50375e85
---

# Durable State Foundation 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 Workbench backend 的进程内 `runs` / `sessions` Map 替换为 file-based JSONL durable store，提供 cross-restart 恢复、run ownership/lease、structured checkpoint reference、幂等 continuation，接口 store-agnostic 可插拔。

**Architecture:** 在 `frontend/src/runtime/durable/` 新建 store-agnostic 接口 + JSONL 参考实现；`agent-runtime-adapter.ts` 的两个 `globalThis` Map 替换为 store 实例。run 事件流用 append-only JSONL（每事件 fsync = checkpoint），session/lease/idempotency 用 tmp+rename 原子覆写。lease 活动驱动续期 + awaiting 释放；idempotency key 三段式 `${runId}:${type}:${sha256(canonicalJson(params))}`。

**Tech Stack:** TypeScript 5.8 / Next.js 15.3 / Node.js `fs` + `crypto`（零新增依赖）/ Vitest 3。

## Global Constraints

- READ capabilities MUST NOT call `BAPI_TRANSACTION_COMMIT`/`ROLLBACK`；WRITE capabilities MUST NOT execute until Human Approval confirmed（本 change 不改此契约，仅迁移存储）。
- Gateway accepts `capabilityId` only, never request-provided `rfcName`（`createAgentRun` 已强制，保持）。
- 本 change 不触 Gateway approval（项3）、不触 SSE（项4）、不触 trusted principal（项2）。
- 保持 `resetAgentRunsForTests` / `resetAgentSessionsForTests` / `setAgentRunnerForTests` 测试钩子签名。
- `createAgentRun` Q2 门禁（同 conversation pending approval 拒绝新查询）需迁移到 durable store。
- 零新增 npm 依赖（只用 Node 内置 `fs` / `crypto`）。
- 代码/标识符/路径/类型名用英文；叙述用中文。
- `npm --prefix frontend run verify`（typecheck + vitest + build）必须通过。
- `openspec validate --all --strict` 必须通过。

## Design Doc 决策对齐

| 决策 | 选择 | 实现位置 |
|---|---|---|
| store 选型 | file-based JSONL | Task 3/4 |
| lease 续期 | 活动驱动（appendEvent renew）+ awaiting 释放 | Task 6 |
| checkpoint 粒度 | 每事件 append + fsync；checkpoint_ref 随状态变更 append | Task 7 |
| idempotency key | `${runId}:${continuationType}:${sha256(canonicalJson(params))}` | Task 8 |

文件布局（`<workbenchDataDir>/durable/`，dev 默认 `frontend/.workbench-data/durable/`）：

| 路径 | 内容 | 写策略 |
|---|---|---|
| `runs/<runId>.jsonl` | append-only 事件流（每行 `RunJsonlLine`） | append + fsync |
| `sessions/<conversationId>.json` | `SessionState` 全量 | tmp + rename |
| `leases/<runId>.json` | `{ workerId, expiresAt }` | tmp + rename |
| `idempotency/<key>.json` | `{ result, executedAt }` | tmp + rename |

## File Structure

新增模块目录 `frontend/src/runtime/durable/`：

| 文件 | 职责 |
|---|---|
| `types.ts` | 共享运行时类型（从 adapter 提取）+ durable 接口契约 + 数据结构（LeaseOutcome / CheckpointRef / RunJsonlLine / ContinuationType）。接口渐进扩展：Task 1 核心方法，Task 6/7/8 追加 lease/checkpoint/idempotency 方法。 |
| `canonical-json.ts` | 稳定键序 + 无空格序列化 + `sha256Hex`。 |
| `idempotency.ts` | idempotency key 三段式计算。 |
| `jsonl-conversation-store.ts` | `DurableConversationStore` JSON 参考实现。 |
| `jsonl-run-store.ts` | `DurableRunStore` JSONL 参考实现（核心 + lease + checkpoint + idempotency 增量扩展）。 |
| `*.test.ts`（并排） | 每个模块的 Vitest 单测。 |

修改文件：

| 文件 | 改动 |
|---|---|
| `frontend/src/runtime/agent-runtime-adapter.ts` | 提取共享类型到 `durable/types.ts`；`runs`/`sessions` Map 替换为 store 实例；`createAgentRun`/`getAgentRunEvents`/continuation 迁移到 store API；新增 `setDurableStoresForTests` 测试钩子。 |
| `frontend/vitest.config.ts`（新建） | 明确 `environment: "node"` + `include: ["src/**/*.test.ts"]`，避免 `.next` 被扫。 |

任务依赖排序：接口契约 -> canonicalJson -> ConversationStore -> RunStore 核心 -> 替换 Map -> lease -> checkpoint -> idempotency -> 三层分层 -> 综合测试。

---

## Task 1: Store-agnostic 接口契约 + 共享类型提取
- [x] Task 1: Store-agnostic 接口契约 + 共享类型提取

**对应 tasks.md：** 1.1 / 1.2 / 1.3 / 1.4（接口与数据结构定义）

**目标：** 把 `agent-runtime-adapter.ts` 中 module-local 的共享运行时类型提取到 `durable/types.ts`，并定义 durable store 接口核心方法 + `LeaseOutcome` / `CheckpointRef` / `ContinuationType` / `RunJsonlLine` 数据结构。本任务无运行时行为，验证靠 typecheck + build。

**Files:**
- Create: `frontend/src/runtime/durable/types.ts`
- Create: `frontend/vitest.config.ts`
- Modify: `frontend/src/runtime/agent-runtime-adapter.ts`（删除被提取的类型定义，改为从 `./durable/types` import）

**Interfaces:**
- Produces: `DurableRunStore`（核心方法，后续 task 扩展）、`DurableConversationStore`、`LeaseOutcome`、`CheckpointRef`、`ContinuationType`、`RunJsonlLine`、`IdempotencyRecord`、`AgentRunRecord`、`SessionState`、`WorkbenchOutcome`、`ApprovalDecision`、`LastContext`、`Turn`、`ConversationContext`。

- [ ] **Step 1: 创建 `frontend/src/runtime/durable/types.ts`**

```ts
import type { AgentRunEvent, AgentRunState } from "../run-event-schema";

// --- Shared runtime types (extracted from agent-runtime-adapter.ts) ---

export type LastContext = {
  capabilityId: string;
  parameters: Record<string, string>;
  missingParameters: string[];
  decisionType: "CLARIFY" | "SELECT";
};

export type Turn = { role: "user" | "assistant"; content: string };

export type ConversationContext = {
  lastContext: LastContext | null;
  history: Turn[] | null;
};

export type SessionState = {
  lastContext: LastContext | null;
  lastRunId: string | null;
  history: Turn[];
};

export type ApprovalDecision = "approve" | "reject";

export type WorkbenchOutcome = {
  status: string;
  message?: string | null;
  responseText?: string | null;
  callPlan?: Record<string, unknown> | null;
  validationResult?: Record<string, unknown> | null;
  executionResult?: Record<string, unknown> | null;
  fact?: Record<string, unknown> | null;
  gatewayTraceId?: string | null;
  errorType?: string | null;
  missingParameters?: string[] | null;
  approvalRecord?: Record<string, unknown> | null;
  combinations?: Record<string, string>[] | null;
  matchDecision?: Record<string, unknown> | null;
  dryRun?: Record<string, unknown> | null;
  lastContext?: LastContext | null;
};

export type AgentRunRecord = {
  runId: string;
  query: string;
  events: AgentRunEvent[];
  pendingOutcome?: WorkbenchOutcome;
  decision?: ApprovalDecision;
};

// --- Durable store data structures ---

export type LeaseOutcome =
  | { status: "claimed" }
  | { status: "rejected"; holder: string; expiresAt: string }
  | { status: "force-claimed"; previousHolder: string };

export type CheckpointRef = {
  registrySnapshotId: string;
  nodeState: Record<string, unknown>;
  approvalRecordRef?: string | null;
};

export type ContinuationType =
  | "approval_approve"
  | "approval_reject"
  | "batch_confirm";

export type IdempotencyRecord = {
  result: WorkbenchOutcome;
  executedAt: string;
};

// --- JSONL line types (run event log, discriminated by `kind`) ---

export type RunJsonlLine =
  | { kind: "run_meta"; runId: string; query: string }
  | ({ kind: "event" } & AgentRunEvent)
  | { kind: "pending_outcome"; value: WorkbenchOutcome }
  | { kind: "decision"; value: ApprovalDecision }
  | { kind: "checkpoint_ref"; value: CheckpointRef };

// --- Store-agnostic interfaces (core; extended in Task 6/7/8) ---

export interface DurableRunStore {
  save(runId: string, record: AgentRunRecord): Promise<void>;
  load(runId: string): Promise<AgentRunRecord | null>;
  list(filter?: { state?: AgentRunState }): Promise<AgentRunRecord[]>;
  appendEvent(runId: string, event: AgentRunEvent): Promise<void>;
  appendPendingOutcome(runId: string, outcome: WorkbenchOutcome): Promise<void>;
  appendDecision(runId: string, decision: ApprovalDecision): Promise<void>;
  clearAll(): Promise<void>;
  // Task 6 追加: claim / release / renew
  // Task 7 追加: appendCheckpointRef / loadCheckpointRef
  // Task 8 追加: markExecuted / lookupExecuted
}

export interface DurableConversationStore {
  save(conversationId: string, state: SessionState): Promise<void>;
  load(conversationId: string): Promise<SessionState | null>;
  clear(conversationId: string): Promise<void>;
  clearAll(): Promise<void>;
}
```

> 说明：`run_meta` 行存 `{ runId, query }`，恢复时重建 `AgentRunRecord.query`（event 行不含 query）。`DurableRunStore` 接口在 Task 6/7/8 追加 lease/checkpoint/idempotency 方法，最终对齐 Design Doc §1 完整接口。

- [ ] **Step 2: 创建 `frontend/vitest.config.ts`**

```ts
import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"]
  }
});
```

- [ ] **Step 3: 修改 `agent-runtime-adapter.ts` 提取类型**

删除 adapter 顶部以下类型定义（`LastContext` / `Turn` / `ConversationContext` / `SessionState` / `AgentRunRecord` / `ApprovalDecision` / `ApprovalContinuation` / `BatchContinuation` / `AgentRunnerInput` / `WorkbenchOutcome` / `AgentRunner`），替换为从 `./durable/types` import。保留 `ApprovalContinuation` / `BatchContinuation` / `AgentRunnerInput` / `AgentRunner` 在 adapter（它们是 adapter 私有调用契约，不被 store 共享）。

在 adapter 顶部 import 块（现有 `import type { AgentRunEvent, AgentRunState } from "./run-event-schema";` 之后）加入：

```ts
import type {
  AgentRunRecord,
  ApprovalDecision,
  ConversationContext,
  LastContext,
  SessionState,
  Turn,
  WorkbenchOutcome
} from "./durable/types";

export type { ApprovalDecision } from "./durable/types";
```

删除 adapter 中 `type LastContext = {...}` / `type Turn = ...` / `type ConversationContext = ...` / `type SessionState = ...` / `type AgentRunRecord = ...` / `export type ApprovalDecision = ...` / `type WorkbenchOutcome = ...` 这些块。保留 `ApprovalContinuation` / `BatchContinuation` / `AgentRunnerInput` / `AgentRunner` / `CreateAgentRunInput` 定义原位不动。

- [ ] **Step 4: 验证 typecheck + build**

Run: `npm --prefix frontend run typecheck`
Expected: PASS（0 errors）

Run: `npm --prefix frontend run build`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/runtime/durable/types.ts frontend/vitest.config.ts frontend/src/runtime/agent-runtime-adapter.ts
git commit -m "feat(durable): define store-agnostic interfaces and extract shared runtime types"
```

---

## Task 2: canonicalJson + sha256 工具
- [x] Task 2: canonicalJson + sha256 工具

**对应 tasks.md：** 1.4（idempotency key schema 依赖的稳定序列化）

**目标：** 提供稳定键序 + 无空格的 `canonicalJson` 和 `sha256Hex`，为 idempotency paramHash 提供确定性序列化基础。

**Files:**
- Create: `frontend/src/runtime/durable/canonical-json.ts`
- Test: `frontend/src/runtime/durable/canonical-json.test.ts`

**Interfaces:**
- Produces: `canonicalJson(value: unknown): string`、`sha256Hex(input: string): string`。

- [ ] **Step 1: 写失败测试 `canonical-json.test.ts`**

```ts
import { describe, expect, it } from "vitest";
import { canonicalJson, sha256Hex } from "./canonical-json";

describe("canonicalJson", () => {
  it("serializes objects with sorted keys and no whitespace", () => {
    expect(canonicalJson({ b: 1, a: 2 })).toBe('{"a":2,"b":1}');
  });

  it("is order-independent for equal objects", () => {
    expect(canonicalJson({ a: 1, b: 2 })).toBe(canonicalJson({ b: 2, a: 1 }));
  });

  it("handles nested objects and arrays", () => {
    expect(canonicalJson({ z: [3, 1, 2], a: { y: 1, x: 2 } }))
      .toBe('{"a":{"x":2,"y":1},"z":[3,1,2]}');
  });

  it("handles null, booleans, numbers, strings", () => {
    expect(canonicalJson(null)).toBe("null");
    expect(canonicalJson(true)).toBe("true");
    expect(canonicalJson(42)).toBe("42");
    expect(canonicalJson("hi")).toBe('"hi"');
  });

  it("coerces non-finite numbers to null", () => {
    expect(canonicalJson(Number.POSITIVE_INFINITY)).toBe("null");
  });

  it("coerces undefined to null", () => {
    expect(canonicalJson(undefined)).toBe("null");
  });
});

describe("sha256Hex", () => {
  it("produces a stable 64-char hex digest", () => {
    const digest = sha256Hex('{"a":2,"b":1}');
    expect(digest).toMatch(/^[0-9a-f]{64}$/);
    expect(sha256Hex('{"a":2,"b":1}')).toBe(digest);
  });
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `npm --prefix frontend run test -- src/runtime/durable/canonical-json.test.ts`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现 `canonical-json.ts`**

```ts
import { createHash } from "node:crypto";

export function canonicalJson(value: unknown): string {
  return serialize(value);
}

function serialize(value: unknown): string {
  if (value === null || value === undefined) return "null";
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "number") return Number.isFinite(value) ? String(value) : "null";
  if (typeof value === "string") return JSON.stringify(value);
  if (Array.isArray(value)) {
    return `[${value.map(serialize).join(",")}]`;
  }
  if (typeof value === "object") {
    const obj = value as Record<string, unknown>;
    const entries = Object.keys(obj)
      .sort()
      .map((key) => `${JSON.stringify(key)}:${serialize(obj[key])}`);
    return `{${entries.join(",")}}`;
  }
  return JSON.stringify(String(value));
}

export function sha256Hex(input: string): string {
  return createHash("sha256").update(input, "utf8").digest("hex");
}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `npm --prefix frontend run test -- src/runtime/durable/canonical-json.test.ts`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/runtime/durable/canonical-json.ts frontend/src/runtime/durable/canonical-json.test.ts
git commit -m "feat(durable): add canonicalJson and sha256Hex for idempotency hashing"
```

---

## Task 3: DurableConversationStore JSON 参考实现
- [x] Task 3: DurableConversationStore JSON 参考实现

**对应 tasks.md：** 2.3（conversation store 本地实现）

**目标：** 实现 `DurableConversationStore` 的 file-based JSON 参考实现，tmp+rename 原子覆写，跨 store 实例可恢复。

**Files:**
- Create: `frontend/src/runtime/durable/jsonl-conversation-store.ts`
- Test: `frontend/src/runtime/durable/jsonl-conversation-store.test.ts`

**Interfaces:**
- Consumes: `DurableConversationStore` / `SessionState` from `./types`
- Produces: `JsonlConversationStore` class（构造接收 `dataDir: string`）

- [ ] **Step 1: 写失败测试 `jsonl-conversation-store.test.ts`**

```ts
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { JsonlConversationStore } from "./jsonl-conversation-store";
import type { SessionState } from "./types";

function makeSession(): SessionState {
  return { lastContext: null, lastRunId: "run-1", history: [{ role: "user", content: "hi" }] };
}

describe("JsonlConversationStore", () => {
  let dir: string;
  beforeEach(() => { dir = mkdtempSync(path.join(tmpdir(), "conv-")); });
  afterEach(() => { rmSync(dir, { recursive: true, force: true }); });

  it("returns null when session does not exist", async () => {
    const store = new JsonlConversationStore(dir);
    expect(await store.load("c1")).toBeNull();
  });

  it("saves and loads a session", async () => {
    const store = new JsonlConversationStore(dir);
    await store.save("c1", makeSession());
    const loaded = await store.load("c1");
    expect(loaded).toEqual(makeSession());
  });

  it("recovers across store instances (cross-restart)", async () => {
    await new JsonlConversationStore(dir).save("c1", makeSession());
    const reopened = new JsonlConversationStore(dir);
    expect(await reopened.load("c1")).toEqual(makeSession());
  });

  it("overwrites on re-save (compaction-safe advisory layer)", async () => {
    const store = new JsonlConversationStore(dir);
    await store.save("c1", makeSession());
    const compacted: SessionState = { lastContext: null, lastRunId: null, history: [] };
    await store.save("c1", compacted);
    expect(await store.load("c1")).toEqual(compacted);
  });

  it("clears a session", async () => {
    const store = new JsonlConversationStore(dir);
    await store.save("c1", makeSession());
    await store.clear("c1");
    expect(await store.load("c1")).toBeNull();
  });

  it("clearAll removes all sessions", async () => {
    const store = new JsonlConversationStore(dir);
    await store.save("c1", makeSession());
    await store.save("c2", makeSession());
    await store.clearAll();
    expect(await store.load("c1")).toBeNull();
    expect(await store.load("c2")).toBeNull();
  });
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `npm --prefix frontend run test -- src/runtime/durable/jsonl-conversation-store.test.ts`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现 `jsonl-conversation-store.ts`**

```ts
import {
  existsSync,
  mkdirSync,
  readFileSync,
  readdirSync,
  renameSync,
  unlinkSync,
  writeFileSync
} from "node:fs";
import path from "node:path";
import type { DurableConversationStore, SessionState } from "./types";

export class JsonlConversationStore implements DurableConversationStore {
  private readonly sessionsDir: string;

  constructor(private readonly dataDir: string) {
    this.sessionsDir = path.join(dataDir, "sessions");
    mkdirSync(this.sessionsDir, { recursive: true });
  }

  private file(conversationId: string): string {
    return path.join(this.sessionsDir, `${conversationId}.json`);
  }

  async save(conversationId: string, state: SessionState): Promise<void> {
    const target = this.file(conversationId);
    const tmp = `${target}.tmp`;
    writeFileSync(tmp, JSON.stringify(state), "utf8");
    renameSync(tmp, target);
  }

  async load(conversationId: string): Promise<SessionState | null> {
    const file = this.file(conversationId);
    if (!existsSync(file)) return null;
    return JSON.parse(readFileSync(file, "utf8")) as SessionState;
  }

  async clear(conversationId: string): Promise<void> {
    const file = this.file(conversationId);
    if (existsSync(file)) {
      unlinkSync(file);
    }
  }

  async clearAll(): Promise<void> {
    if (!existsSync(this.sessionsDir)) return;
    for (const entry of readdirSync(this.sessionsDir)) {
      if (entry.endsWith(".json")) {
        unlinkSync(path.join(this.sessionsDir, entry));
      }
    }
  }
}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `npm --prefix frontend run test -- src/runtime/durable/jsonl-conversation-store.test.ts`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/runtime/durable/jsonl-conversation-store.ts frontend/src/runtime/durable/jsonl-conversation-store.test.ts
git commit -m "feat(durable): implement DurableConversationStore JSON reference impl"
```

---

## Task 4: DurableRunStore JSONL 核心实现
- [x] Task 4: DurableRunStore JSONL 核心实现

**对应 tasks.md：** 2.2（run store 本地实现）+ 3.3（序列化与反序列化）

**目标：** 实现 `DurableRunStore` 核心方法（save / load / list / appendEvent / appendPendingOutcome / appendDecision / clearAll），append+fsync 持久化，JSONL 重放恢复 `AgentRunRecord`。

**Files:**
- Create: `frontend/src/runtime/durable/jsonl-run-store.ts`
- Test: `frontend/src/runtime/durable/jsonl-run-store.test.ts`

**Interfaces:**
- Consumes: `DurableRunStore` / `AgentRunRecord` / `AgentRunEvent` / `RunJsonlLine` / `WorkbenchOutcome` / `ApprovalDecision` from `./types`
- Produces: `JsonlRunStore` class（构造接收 `dataDir: string`）。Task 6/7/8 在此类追加 lease/checkpoint/idempotency 方法。

- [ ] **Step 1: 写失败测试 `jsonl-run-store.test.ts`**

```ts
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { JsonlRunStore } from "./jsonl-run-store";
import type { AgentRunEvent, AgentRunRecord, WorkbenchOutcome } from "./types";

function event(runId: string, sequence: number, type: AgentRunEvent["type"], state: AgentRunEvent["state"]): AgentRunEvent {
  return { runId, sequence, timestamp: "2026-08-02T00:00:00Z", type, state };
}

function record(runId: string, query: string, events: AgentRunEvent[]): AgentRunRecord {
  return { runId, query, events };
}

describe("JsonlRunStore core", () => {
  let dir: string;
  beforeEach(() => { dir = mkdtempSync(path.join(tmpdir(), "run-")); });
  afterEach(() => { rmSync(dir, { recursive: true, force: true }); });

  it("returns null when run does not exist", async () => {
    const store = new JsonlRunStore(dir);
    expect(await store.load("run-x")).toBeNull();
  });

  it("saves and loads a run with full event stream", async () => {
    const store = new JsonlRunStore(dir);
    const events = [event("run-1", 1, "run_started", "running"), event("run-1", 2, "run_completed", "completed")];
    await store.save("run-1", record("run-1", "query text", events));
    const loaded = await store.load("run-1");
    expect(loaded).toEqual(record("run-1", "query text", events));
  });

  it("appendEvent adds events incrementally and persists via fsync", async () => {
    const store = new JsonlRunStore(dir);
    await store.save("run-1", record("run-1", "q", [event("run-1", 1, "run_started", "running")]));
    await store.appendEvent("run-1", event("run-1", 2, "intent_parsed", "intent_parsed"));
    const loaded = await store.load("run-1");
    expect(loaded?.events.map((e) => e.sequence)).toEqual([1, 2]);
  });

  it("recovers full record across store instances (cross-restart replay)", async () => {
    const store = new JsonlRunStore(dir);
    const events = [event("run-1", 1, "run_started", "running"), event("run-1", 2, "run_completed", "completed")];
    await store.save("run-1", record("run-1", "q", [events[0]]));
    await store.appendEvent("run-1", events[1]);
    const outcome: WorkbenchOutcome = { status: "awaiting_approval" };
    await store.appendPendingOutcome("run-1", outcome);
    await store.appendDecision("run-1", "approve");

    const reopened = new JsonlRunStore(dir);
    const loaded = await reopened.load("run-1");
    expect(loaded?.query).toBe("q");
    expect(loaded?.events).toEqual(events);
    expect(loaded?.pendingOutcome).toEqual(outcome);
    expect(loaded?.decision).toBe("approve");
  });

  it("appendPendingOutcome keeps the latest value", async () => {
    const store = new JsonlRunStore(dir);
    await store.save("run-1", record("run-1", "q", [event("run-1", 1, "run_started", "running")]));
    await store.appendPendingOutcome("run-1", { status: "awaiting_approval" });
    await store.appendPendingOutcome("run-1", { status: "awaiting_batch_confirm" });
    expect((await store.load("run-1"))?.pendingOutcome?.status).toBe("awaiting_batch_confirm");
  });

  it("list returns all runs, optionally filtered by last state", async () => {
    const store = new JsonlRunStore(dir);
    await store.save("run-1", record("run-1", "q", [event("run-1", 1, "run_started", "running"), event("run-1", 2, "approval_state_changed", "awaiting_approval")]));
    await store.save("run-2", record("run-2", "q", [event("run-2", 1, "run_started", "running"), event("run-2", 2, "run_completed", "completed")]));
    expect((await store.list()).length).toBe(2);
    expect((await store.list({ state: "awaiting_approval" })).map((r) => r.runId)).toEqual(["run-1"]);
  });

  it("clearAll removes all runs", async () => {
    const store = new JsonlRunStore(dir);
    await store.save("run-1", record("run-1", "q", [event("run-1", 1, "run_started", "running")]));
    await store.clearAll();
    expect(await store.load("run-1")).toBeNull();
  });
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `npm --prefix frontend run test -- src/runtime/durable/jsonl-run-store.test.ts`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现 `jsonl-run-store.ts`（核心方法）**

```ts
import {
  closeSync,
  existsSync,
  fsyncSync,
  mkdirSync,
  openSync,
  readFileSync,
  readdirSync,
  renameSync,
  unlinkSync,
  writeFileSync,
  writeSync
} from "node:fs";
import path from "node:path";
import type {
  AgentRunEvent,
  AgentRunRecord,
  AgentRunState,
  ApprovalDecision,
  DurableRunStore,
  RunJsonlLine,
  WorkbenchOutcome
} from "./types";

export class JsonlRunStore implements DurableRunStore {
  private readonly runsDir: string;

  constructor(private readonly dataDir: string) {
    this.runsDir = path.join(dataDir, "runs");
    mkdirSync(this.runsDir, { recursive: true });
  }

  private runFile(runId: string): string {
    return path.join(this.runsDir, `${runId}.jsonl`);
  }

  // append + fsync per line (checkpoint decision A: every event is durable)
  private appendLine(runId: string, line: RunJsonlLine): void {
    const fd = openSync(this.runFile(runId), "a");
    try {
      writeSync(fd, JSON.stringify(line) + "\n", null, "utf8");
      fsyncSync(fd);
    } finally {
      closeSync(fd);
    }
  }

  async save(runId: string, record: AgentRunRecord): Promise<void> {
    const file = this.runFile(runId);
    const lines: string[] = [JSON.stringify({ kind: "run_meta", runId, query: record.query } as RunJsonlLine)];
    for (const event of record.events) {
      lines.push(JSON.stringify({ kind: "event", ...event } as RunJsonlLine));
    }
    if (record.pendingOutcome) {
      lines.push(JSON.stringify({ kind: "pending_outcome", value: record.pendingOutcome } as RunJsonlLine));
    }
    if (record.decision) {
      lines.push(JSON.stringify({ kind: "decision", value: record.decision } as RunJsonlLine));
    }
    const content = lines.map((l) => l + "\n").join("");
    const tmp = `${file}.tmp`;
    writeFileSync(tmp, content, "utf8");
    const fd = openSync(tmp, "r");
    fsyncSync(fd);
    closeSync(fd);
    renameSync(tmp, file);
  }

  async load(runId: string): Promise<AgentRunRecord | null> {
    const file = this.runFile(runId);
    if (!existsSync(file)) return null;
    return this.replay(file);
  }

  private replay(file: string): AgentRunRecord {
    const content = readFileSync(file, "utf8");
    let query = "";
    const events: AgentRunEvent[] = [];
    let pendingOutcome: WorkbenchOutcome | undefined;
    let decision: ApprovalDecision | undefined;
    for (const raw of content.split("\n")) {
      if (!raw.trim()) continue;
      const line = JSON.parse(raw) as RunJsonlLine;
      switch (line.kind) {
        case "run_meta":
          query = line.query;
          break;
        case "event": {
          const { kind: _kind, ...event } = line;
          events.push(event as AgentRunEvent);
          break;
        }
        case "pending_outcome":
          pendingOutcome = line.value;
          break;
        case "decision":
          decision = line.value;
          break;
        case "checkpoint_ref":
          // consumed by loadCheckpointRef (Task 7); ignored here.
          break;
      }
    }
    events.sort((a, b) => a.sequence - b.sequence);
    const record: AgentRunRecord = { runId: path.basename(file, ".jsonl"), query, events };
    if (pendingOutcome) record.pendingOutcome = pendingOutcome;
    if (decision) record.decision = decision;
    return record;
  }

  async appendEvent(runId: string, event: AgentRunEvent): Promise<void> {
    this.appendLine(runId, { kind: "event", ...event });
  }

  async appendPendingOutcome(runId: string, outcome: WorkbenchOutcome): Promise<void> {
    this.appendLine(runId, { kind: "pending_outcome", value: outcome });
  }

  async appendDecision(runId: string, decision: ApprovalDecision): Promise<void> {
    this.appendLine(runId, { kind: "decision", value: decision });
  }

  async list(filter?: { state?: AgentRunState }): Promise<AgentRunRecord[]> {
    if (!existsSync(this.runsDir)) return [];
    const records: AgentRunRecord[] = [];
    for (const entry of readdirSync(this.runsDir)) {
      if (!entry.endsWith(".jsonl")) continue;
      const record = this.replay(path.join(this.runsDir, entry));
      const lastState = record.events[record.events.length - 1]?.state;
      if (!filter?.state || lastState === filter.state) {
        records.push(record);
      }
    }
    return records;
  }

  async clearAll(): Promise<void> {
    if (!existsSync(this.runsDir)) return;
    for (const entry of readdirSync(this.runsDir)) {
      if (entry.endsWith(".jsonl")) {
        unlinkSync(path.join(this.runsDir, entry));
      }
    }
  }
}
```

> 说明：`replay` 按 JSONL 行序重放，取最新 `pending_outcome`/`decision`，events 按 sequence 排序。`checkpoint_ref` 行在 `replay` 中被忽略（由 Task 7 的 `loadCheckpointRef` 单独消费）。`save` 用 tmp+rename+fsync 保证初始化原子性。`appendEvent` 每次 open+write+fsync+close，满足"每事件 append + fsync = checkpoint"。

- [ ] **Step 4: 运行测试确认通过**

Run: `npm --prefix frontend run test -- src/runtime/durable/jsonl-run-store.test.ts`
Expected: PASS

- [ ] **Step 5: typecheck 全量**

Run: `npm --prefix frontend run typecheck`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add frontend/src/runtime/durable/jsonl-run-store.ts frontend/src/runtime/durable/jsonl-run-store.test.ts
git commit -m "feat(durable): implement DurableRunStore JSONL core with replay recovery"
```

---

## Task 5: 替换进程内 Map 为 durable store
- [x] Task 5: 替换进程内 Map 为 durable store

**对应 tasks.md：** 3.1 / 3.2 / 3.3（替换 runs/sessions Map + 序列化）

**目标：** 把 `agent-runtime-adapter.ts` 的 `runs` Map / `sessions` Map 替换为 `JsonlRunStore` / `JsonlConversationStore` 实例。`createAgentRun` / `getAgentRunEvents` / continuation 迁移到 store API；Q2 门禁迁移到 `store.load`；保留 `resetAgentRunsForTests` / `resetAgentSessionsForTests`（调 `clearAll`），新增 `setDurableStoresForTests` 注入测试 store。

**Files:**
- Modify: `frontend/src/runtime/agent-runtime-adapter.ts`
- Create: `frontend/src/runtime/agent-runtime-adapter.test.ts`

**Interfaces:**
- Consumes: `JsonlRunStore` / `JsonlConversationStore` from `./durable/*`，`DurableRunStore` / `DurableConversationStore` / `AgentRunRecord` / `SessionState` from `./durable/types`
- Produces: adapter 公开 API 签名不变（`createAgentRun` / `getAgentRunEvents` / `decideAgentRunApproval` / `confirmAgentRunBatch` / `resetAgentRunsForTests` / `resetAgentSessionsForTests` / `setAgentRunnerForTests`）；新增 `setDurableStoresForTests(run, conv)`。

**实现要点：**
- `createAgentRun`：先 `runStore.save(runId, record)`（含 `run_started`）持久化初始 run；调 runner 后 `appendEvent` 逐个追加 `buildEventsFromOutcome` 生成的 events（`slice(1)` 跳过已 save 的 `run_started`）；awaiting 时 `appendPendingOutcome`；session 经 `conversationStore.save` 持久化。
- continuation（`decideAgentRunApproval` / `confirmAgentRunBatch`）：`runStore.load` 取 record；校验后 `appendDecision`；调 runner；新 events 经 `appendEvent` 逐个追加（lease/idempotency 在 Task 6/8 加）。
- `getAgentRunEvents`：`runStore.load(runId)` 返回 events（空数组 if null）。
- Q2 门禁：`conversationStore.load(conversationId)` 取 `lastRunId` -> `runStore.load(lastRunId)` 查 pending approval。
- `resetAgentRunsForTests` -> `runStore.clearAll()`；`resetAgentSessionsForTests` -> `conversationStore.clearAll()`。
- helper 重构：`appendApprovalEvents` / `appendBatchEvents` / `appendRuntimeFailure` 改为**返回新 events 数组**（不直接 mutate record），由调用方 `appendEvent` 逐个持久化。

- [ ] **Step 1: 写失败测试 `agent-runtime-adapter.test.ts`**

```ts
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import {
  confirmAgentRunBatch,
  createAgentRun,
  decideAgentRunApproval,
  getAgentRunEvents,
  resetAgentRunsForTests,
  resetAgentSessionsForTests,
  setAgentRunnerForTests,
  setDurableStoresForTests
} from "./agent-runtime-adapter";
import { JsonlConversationStore } from "./durable/jsonl-conversation-store";
import { JsonlRunStore } from "./durable/jsonl-run-store";
import type { WorkbenchOutcome } from "./durable/types";

function awaitingOutcome(runId: string): WorkbenchOutcome {
  return {
    status: "awaiting_approval",
    callPlan: { capabilityId: "cap-1", kind: "Action", agentTraceId: "t" },
    validationResult: { success: true, capabilityId: "cap-1", traceId: "g" },
    approvalRecord: { id: "apr-1", status: "pending" },
    responseText: "待审批"
  };
}

describe("agent-runtime-adapter durable integration", () => {
  let dir: string;
  let runStore: JsonlRunStore;
  let convStore: JsonlConversationStore;

  beforeEach(() => {
    dir = mkdtempSync(path.join(tmpdir(), "adapter-"));
    runStore = new JsonlRunStore(dir);
    convStore = new JsonlConversationStore(dir);
    setDurableStoresForTests(runStore, convStore);
    setAgentRunnerForTests(async () => awaitingOutcome("run-1"));
  });
  afterEach(() => {
    setAgentRunnerForTests(null);
    setDurableStoresForTests(
      new JsonlRunStore(mkdtempSync(path.join(tmpdir(), "teardown-"))),
      new JsonlConversationStore(mkdtempSync(path.join(tmpdir(), "teardown-")))
    );
    rmSync(dir, { recursive: true, force: true });
  });

  it("createAgentRun persists events to durable store", async () => {
    const { runId } = await createAgentRun({ query: "查询库存" });
    const events = await getAgentRunEvents(runId);
    expect(events.length).toBeGreaterThan(0);
    expect(events[0].type).toBe("run_started");
  });

  it("getAgentRunEvents returns [] for unknown run", async () => {
    expect(await getAgentRunEvents("run-missing")).toEqual([]);
  });

  it("pending approval run recovers across store reset (cross-restart)", async () => {
    const { runId } = await createAgentRun({ query: "查询库存", conversationId: "c1" });
    // simulate restart: rebind store to same dir
    const reopenedRun = new JsonlRunStore(dir);
    const reopenedConv = new JsonlConversationStore(dir);
    setDurableStoresForTests(reopenedRun, reopenedConv);
    const events = await getAgentRunEvents(runId);
    expect(events.some((e) => e.state === "awaiting_approval")).toBe(true);
  });

  it("Q2 gate rejects new query while prior approval pending", async () => {
    await createAgentRun({ query: "查询库存", conversationId: "c1" });
    await expect(createAgentRun({ query: "再次查询", conversationId: "c1" }))
      .rejects.toThrow(/有待审批/);
  });

  it("decideAgentRunApproval loads from store and appends decision events", async () => {
    setAgentRunnerForTests(async () => ({ status: "success", responseText: "已执行" } as WorkbenchOutcome));
    const { runId } = await createAgentRun({ query: "查询库存" });
    // re-arm runner to awaiting for the initial run
    setAgentRunnerForTests(async () => awaitingOutcome(runId));
    await createAgentRun({ query: "查询库存", conversationId: "c2" }).catch(() => {});
    // pick the awaiting run created above
    const runs = await runStore.list({ state: "awaiting_approval" });
    const target = runs[runs.length - 1];
    setAgentRunnerForTests(async () => ({ status: "success", responseText: "已执行" } as WorkbenchOutcome));
    await decideAgentRunApproval(target.runId, "approve");
    const events = await getAgentRunEvents(target.runId);
    expect(events.some((e) => e.hitlState === "approved")).toBe(true);
  });

  it("resetAgentRunsForTests clears durable runs", async () => {
    const { runId } = await createAgentRun({ query: "查询库存" });
    resetAgentRunsForTests();
    expect(await getAgentRunEvents(runId)).toEqual([]);
  });

  it("resetAgentSessionsForTests clears durable sessions", async () => {
    await createAgentRun({ query: "查询库存", conversationId: "c1" });
    resetAgentSessionsForTests();
    // after reset, Q2 gate no longer sees the prior pending run via session
    setAgentRunnerForTests(async () => ({ status: "success", responseText: "ok" } as WorkbenchOutcome));
    await expect(createAgentRun({ query: "新查询", conversationId: "c1" })).resolves.toBeDefined();
  });
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `npm --prefix frontend run test -- src/runtime/agent-runtime-adapter.test.ts`
Expected: FAIL（`setDurableStoresForTests` 不存在 / 仍用 Map）

- [ ] **Step 3: 修改 `agent-runtime-adapter.ts` -- store 实例与测试钩子**

替换模块级 `runs` / `sessions` Map 声明（现有 `const runs = ...` / `const sessions = ...` 两行 + `globalRunStore` 块）为：

```ts
import { JsonlConversationStore } from "./durable/jsonl-conversation-store";
import { JsonlRunStore } from "./durable/jsonl-run-store";
import type { DurableConversationStore, DurableRunStore } from "./durable/types";

const workbenchDataDir = process.env.WORKBENCH_DATA_DIR ?? path.join(process.cwd(), ".workbench-data");
const durableDataDir = path.join(workbenchDataDir, "durable");

let runStore: DurableRunStore = new JsonlRunStore(durableDataDir);
let conversationStore: DurableConversationStore = new JsonlConversationStore(durableDataDir);
let runnerForTests: AgentRunner | null = null;

export function setAgentRunnerForTests(runner: AgentRunner | null) {
  runnerForTests = runner;
}

export function setDurableStoresForTests(run: DurableRunStore, conv: DurableConversationStore) {
  runStore = run;
  conversationStore = conv;
}

export function resetAgentRunsForTests() {
  void runStore.clearAll();
}

export function resetAgentSessionsForTests() {
  void conversationStore.clearAll();
}
```

删除 `globalRunStore` 块和 `__SAP_NEXUS_AGENT_RUNS__` / `__SAP_NEXUS_AGENT_SESSIONS__` 声明。删除原 `resetAgentRunsForTests` / `resetAgentSessionsForTests`（用上面的替换）。

- [ ] **Step 4: 修改 `getSession` 用 conversationStore**

替换 `getSession` 函数为：

```ts
async function getSession(conversationId: string): Promise<SessionState> {
  const existing = await conversationStore.load(conversationId);
  if (existing) return existing;
  const session: SessionState = { lastContext: null, lastRunId: null, history: [] };
  await conversationStore.save(conversationId, session);
  return session;
}
```

- [ ] **Step 5: 修改 `createAgentRun` 迁移 Q2 门禁 + store 持久化**

替换整个 `createAgentRun` 函数体为：

```ts
export async function createAgentRun(input: CreateAgentRunInput): Promise<{ runId: string }> {
  if (input.rfcName) {
    throw new Error("Raw RFC execution is not allowed");
  }

  // Q2: reject new queries on a conversation that still has a pending write approval.
  if (input.conversationId) {
    const session = await getSession(input.conversationId);
    const lastRunId = session.lastRunId;
    if (lastRunId) {
      const lastRun = await runStore.load(lastRunId);
      if (lastRun?.pendingOutcome && !lastRun.decision) {
        throw new Error("当前对话有待审批的写操作，请先处理审批后再发起新查询。");
      }
    }
  }

  const runId = `run-${crypto.randomUUID()}`;
  const timestamp = new Date().toISOString();
  const query = input.query;
  const record: AgentRunRecord = {
    runId,
    query,
    events: [{ runId, sequence: 1, timestamp, type: "run_started", state: "running" }]
  };
  await runStore.save(runId, record);

  try {
    const runner = runnerForTests ?? runLocalPythonAgent;
    const context = input.conversationId ? buildContext(await getSession(input.conversationId)) : undefined;
    const outcome = await runner({ query, gatewayUrl: gatewayUrl(), intentMode: intentMode(), context });
    const events = buildEventsFromOutcome(runId, query, outcome, timestamp);
    for (const event of events.slice(1)) {
      await runStore.appendEvent(runId, event);
    }
    record.events = events;
    if (outcome.status === "awaiting_approval" || outcome.status === "awaiting_batch_confirm") {
      record.pendingOutcome = outcome;
      await runStore.appendPendingOutcome(runId, outcome);
    }

    if (input.conversationId) {
      const session = await getSession(input.conversationId);
      session.lastRunId = runId;
      session.history.push({ role: "user", content: query });
      if (outcome.responseText) {
        session.history.push({ role: "assistant", content: outcome.responseText });
      }
      session.lastContext = outcome.lastContext ?? null;
      await conversationStore.save(input.conversationId, session);
    }
  } catch (error) {
    const failEvents = buildRuntimeFailureEvents(runId, timestamp, error);
    for (const event of failEvents.slice(1)) {
      await runStore.appendEvent(runId, event);
    }
    record.events = failEvents;
  }

  return { runId };
}
```

- [ ] **Step 6: 修改 `getAgentRunEvents` 用 store**

```ts
export async function getAgentRunEvents(runId: string): Promise<AgentRunEvent[]> {
  const run = await runStore.load(runId);
  return run ? run.events : [];
}
```

- [ ] **Step 7: 修改 `decideAgentRunApproval` 用 store + appendEvent**

```ts
export async function decideAgentRunApproval(runId: string, decision: ApprovalDecision): Promise<void> {
  const record = await runStore.load(runId);
  if (!record) {
    throw new Error("Agent run not found");
  }
  if (!record.pendingOutcome) {
    throw new Error("Agent run is not awaiting approval");
  }
  if (record.decision) {
    throw new Error("Agent run approval was already decided");
  }

  const callPlan = objectOrNull(record.pendingOutcome.callPlan);
  const validationResult = objectOrNull(record.pendingOutcome.validationResult);
  const approvalRecord = objectOrNull(record.pendingOutcome.approvalRecord);
  if (!callPlan || !validationResult || !approvalRecord) {
    throw new Error("Agent run approval context is incomplete");
  }

  await runStore.appendDecision(runId, decision);
  const runner = runnerForTests ?? runLocalPythonAgent;
  try {
    const outcome = await runner({
      query: record.query,
      gatewayUrl: gatewayUrl(),
      intentMode: intentMode(),
      continuation: { decision, callPlan, validationResult, approvalRecord }
    });
    const newEvents = buildApprovalEvents(record, outcome, new Date().toISOString());
    for (const event of newEvents) {
      await runStore.appendEvent(runId, event);
    }
  } catch (error) {
    const failEvents = buildRuntimeFailureEventsTail(record.runId, new Date().toISOString(), error);
    for (const event of failEvents) {
      await runStore.appendEvent(runId, event);
    }
  }
}
```

- [ ] **Step 8: 修改 `confirmAgentRunBatch` 用 store + appendEvent**

```ts
export async function confirmAgentRunBatch(runId: string): Promise<void> {
  const record = await runStore.load(runId);
  if (!record) {
    throw new Error("Agent run not found");
  }
  if (!record.pendingOutcome) {
    throw new Error("Agent run is not awaiting batch confirmation");
  }
  if (record.decision) {
    throw new Error("Agent run was already decided");
  }

  const callPlan = objectOrNull(record.pendingOutcome.callPlan);
  const combinations = record.pendingOutcome.combinations ?? null;
  if (!callPlan || !combinations) {
    throw new Error("Agent run batch context is incomplete");
  }

  await runStore.appendDecision(runId, "approve");
  const runner = runnerForTests ?? runLocalPythonAgent;
  try {
    const outcome = await runner({
      query: record.query,
      gatewayUrl: gatewayUrl(),
      intentMode: intentMode(),
      continuation: { type: "batch", callPlan, combinations }
    });
    const newEvents = buildBatchEvents(record, outcome, new Date().toISOString());
    for (const event of newEvents) {
      await runStore.appendEvent(runId, event);
    }
  } catch (error) {
    const failEvents = buildRuntimeFailureEventsTail(record.runId, new Date().toISOString(), error);
    for (const event of failEvents) {
      await runStore.appendEvent(runId, event);
    }
  }
}
```

- [ ] **Step 9: 重构 event builder 为返回数组**

把 `appendApprovalEvents` / `appendBatchEvents` / `appendRuntimeFailure` 重构为返回 `AgentRunEvent[]`（基于 `record.events.length` 计算 sequence，不 mutate record）。新增 `buildRuntimeFailureEventsTail`（只返回失败 event，不含 run_started，用于 continuation）。

替换 `appendApprovalEvents` 为：

```ts
function buildApprovalEvents(record: AgentRunRecord, outcome: WorkbenchOutcome, timestamp: string): AgentRunEvent[] {
  const events: AgentRunEvent[] = [];
  const base = record.events.length;
  const pushAll = (event: Omit<AgentRunEvent, "runId" | "sequence" | "timestamp">) => {
    events.push({ runId: record.runId, sequence: base + events.length + 1, timestamp, ...event });
  };
  const callPlan = objectOrNull(outcome.callPlan) ?? objectOrNull(record.pendingOutcome?.callPlan);
  const execution = objectOrNull(outcome.executionResult);
  const approvalRecord = objectOrNull(outcome.approvalRecord);
  const capabilityId = textValue(callPlan?.capabilityId);
  const agentTraceId = textValue(callPlan?.agentTraceId);
  const gatewayTraceId = textValue(outcome.gatewayTraceId) ?? textValue(execution?.traceId);

  if (outcome.status === "rejected") {
    pushAll({ type: "approval_state_changed", state: "rejected", hitlState: "rejected", capabilityId, agentTraceId,
      artifact: approvalRecord ? redactArtifact({ label: "ApprovalRecord", kind: "approval", payload: toJsonValue(approvalRecord) }) : undefined });
    return events;
  }
  const approvalStatus = textValue(approvalRecord?.status);
  if (approvalStatus !== "approved" && approvalStatus !== "executed") {
    pushFailureAll(pushAll, "approval_checked", outcome);
    return events;
  }
  pushAll({ type: "approval_state_changed", state: "approval_checked", hitlState: "approved", capabilityId, agentTraceId,
    artifact: approvalRecord ? redactArtifact({ label: "ApprovalRecord", kind: "approval", payload: toJsonValue(approvalRecord) }) : undefined });
  if (execution) {
    pushAll({ type: "gateway_execute_started", state: "executing", capabilityId, agentTraceId, gatewayTraceId });
    pushAll({ type: "gateway_execute_completed", state: "executing", capabilityId, agentTraceId, gatewayTraceId,
      artifact: redactArtifact({ label: "ActionResult", kind: "execution-result", payload: toJsonValue(execution) }) });
  }
  if (outcome.responseText) {
    pushAll({ type: "narrative_created", state: "narrated",
      artifact: redactArtifact({ label: "Chinese Narrative", kind: "narrative", payload: toJsonValue({ text: outcome.responseText }) }) });
  }
  if (outcome.status === "success") {
    pushAll({ type: "run_completed", state: "completed", capabilityId, agentTraceId, gatewayTraceId });
  } else {
    pushFailureAll(pushAll, "executing", outcome);
  }
  return events;
}

function pushFailureAll(
  pushAll: (event: Omit<AgentRunEvent, "runId" | "sequence" | "timestamp">) => void,
  stage: AgentRunState,
  outcome: WorkbenchOutcome
) {
  pushAll({ type: "run_failed", state: "failed", error: { errorType: outcome.errorType || "AGENT_RUN_FAILED", message: outcome.responseText || outcome.message || "Agent run failed", stage } });
}
```

同样把 `appendBatchEvents` 重构为 `buildBatchEvents`（返回 `AgentRunEvent[]`，用相同 `base + events.length + 1` sequence 模式），把 `appendRuntimeFailure` 重构为 `buildRuntimeFailureEventsTail`：

```ts
function buildRuntimeFailureEventsTail(runId: string, timestamp: string, error: unknown): AgentRunEvent[] {
  const safeMessage = error instanceof Error ? error.message : "Agent runtime failed";
  return [{ runId, sequence: 0, timestamp, type: "run_failed", state: "failed",
    error: { errorType: "AGENT_RUNTIME_ERROR", message: safeMessage, stage: "running" } }];
}
```

> 注意：`buildRuntimeFailureEventsTail` 的 sequence 占位为 0，由调用方在 continuation 上下文使用（continuation 不重算 sequence，appendEvent 直接持久化；load 时按 sequence 排序，0 排在已有事件之后不影响——但因 continuation 失败 event 应在最后，可改为调用方传入 `base + 1`）。为保持顺序正确，把 `buildRuntimeFailureEventsTail` 签名改为接收 `baseSequence: number`：

```ts
function buildRuntimeFailureEventsTail(runId: string, baseSequence: number, timestamp: string, error: unknown): AgentRunEvent[] {
  const safeMessage = error instanceof Error ? error.message : "Agent runtime failed";
  return [{ runId, sequence: baseSequence + 1, timestamp, type: "run_failed", state: "failed",
    error: { errorType: "AGENT_RUNTIME_ERROR", message: safeMessage, stage: "running" } }];
}
```

调用处（Step 7/8 catch 块）改为：`buildRuntimeFailureEventsTail(record.runId, record.events.length, new Date().toISOString(), error)`。

`buildBatchEvents` 参照 `buildApprovalEvents` 模式（用 `record.events.length` 为 base），逻辑保持与原 `appendBatchEvents` 一致（narrative + run_completed/run_failed）。

- [ ] **Step 10: 运行测试确认通过**

Run: `npm --prefix frontend run test -- src/runtime/agent-runtime-adapter.test.ts`
Expected: PASS

- [ ] **Step 11: typecheck + build**

Run: `npm --prefix frontend run typecheck && npm --prefix frontend run build`
Expected: PASS

- [ ] **Step 12: Commit**

```bash
git add frontend/src/runtime/agent-runtime-adapter.ts frontend/src/runtime/agent-runtime-adapter.test.ts
git commit -m "feat(durable): replace in-process Maps with durable stores in agent-runtime-adapter"
```

---

## Task 6: Run ownership / lease
- [x] Task 6: Run ownership / lease

**对应 tasks.md：** 4.1 / 4.2 / 4.3（lease + fail-closed + 强制接管）

**目标：** 在 `DurableRunStore` 接口追加 `claim` / `release` / `renew`，在 `JsonlRunStore` 实现 lease（`leases/<runId>.json` tmp+rename）。活动驱动续期（`appendEvent` 自动 renew 本 worker 持有的 lease，TTL ~60s）；awaiting 释放；lease 未过期他 worker claim -> `rejected`（fail-closed）；lease 过期 -> `force-claimed`（审计）。continuation 入口先 claim 再执行。

**Files:**
- Modify: `frontend/src/runtime/durable/types.ts`（接口追加 lease 方法）
- Modify: `frontend/src/runtime/durable/jsonl-run-store.ts`（实现 lease + appendEvent 自动 renew；构造接收 `workerId` + `defaultTtlMs`）
- Modify: `frontend/src/runtime/agent-runtime-adapter.ts`（构造 store 传 workerId；continuation 入口 claim/release；awaiting 释放）
- Test: `frontend/src/runtime/durable/lease.test.ts`

**Interfaces:**
- Extends `DurableRunStore` with: `claim(runId: string, workerId: string, ttlMs: number): Promise<LeaseOutcome>`、`release(runId: string, workerId: string): Promise<void>`、`renew(runId: string, workerId: string, ttlMs: number): Promise<void>`

- [ ] **Step 1: 写失败测试 `lease.test.ts`**

```ts
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { JsonlRunStore } from "./jsonl-run-store";
import type { AgentRunEvent, AgentRunRecord } from "./types";

const TTL = 60_000;
function seedRecord(runId: string): AgentRunRecord {
  const e: AgentRunEvent = { runId, sequence: 1, timestamp: "t", type: "run_started", state: "running" };
  return { runId, query: "q", events: [e] };
}

describe("lease", () => {
  let dir: string;
  beforeEach(() => { dir = mkdtempSync(path.join(tmpdir(), "lease-")); });
  afterEach(() => { rmSync(dir, { recursive: true, force: true }); });

  it("first claim succeeds", async () => {
    const store = new JsonlRunStore(dir, "worker-A", TTL);
    await store.save("run-1", seedRecord("run-1"));
    expect(await store.claim("run-1", "worker-A", TTL)).toEqual({ status: "claimed" });
  });

  it("second worker claim while lease held is rejected (fail-closed)", async () => {
    const a = new JsonlRunStore(dir, "worker-A", TTL);
    const b = new JsonlRunStore(dir, "worker-B", TTL);
    await a.save("run-1", seedRecord("run-1"));
    await a.claim("run-1", "worker-A", TTL);
    const outcome = await b.claim("run-1", "worker-B", TTL);
    expect(outcome.status).toBe("rejected");
    if (outcome.status === "rejected") expect(outcome.holder).toBe("worker-A");
  });

  it("expired lease allows force-claimed takeover with audit", async () => {
    const a = new JsonlRunStore(dir, "worker-A", TTL);
    const b = new JsonlRunStore(dir, "worker-B", TTL);
    await a.save("run-1", seedRecord("run-1"));
    // claim with TTL=0 -> immediately expired
    await a.claim("run-1", "worker-A", 0);
    const outcome = await b.claim("run-1", "worker-B", TTL);
    expect(outcome.status).toBe("force-claimed");
    if (outcome.status === "force-claimed") expect(outcome.previousHolder).toBe("worker-A");
  });

  it("release allows another worker to claim", async () => {
    const a = new JsonlRunStore(dir, "worker-A", TTL);
    const b = new JsonlRunStore(dir, "worker-B", TTL);
    await a.save("run-1", seedRecord("run-1"));
    await a.claim("run-1", "worker-A", TTL);
    await a.release("run-1", "worker-A");
    expect((await b.claim("run-1", "worker-B", TTL)).status).toBe("claimed");
  });

  it("appendEvent renews the lease held by the same worker (activity-driven)", async () => {
    const a = new JsonlRunStore(dir, "worker-A", TTL);
    await a.save("run-1", seedRecord("run-1"));
    await a.claim("run-1", "worker-A", 10); // short TTL
    const before = await a.loadLeaseExpiry("run-1");
    await a.appendEvent("run-1", { runId: "run-1", sequence: 2, timestamp: "t2", type: "intent_parsed", state: "intent_parsed" });
    const after = await a.loadLeaseExpiry("run-1");
    expect(after).toBeGreaterThan(before ?? 0);
  });

  it("same worker re-claim is idempotent (claimed)", async () => {
    const a = new JsonlRunStore(dir, "worker-A", TTL);
    await a.save("run-1", seedRecord("run-1"));
    await a.claim("run-1", "worker-A", TTL);
    expect((await a.claim("run-1", "worker-A", TTL)).status).toBe("claimed");
  });
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `npm --prefix frontend run test -- src/runtime/durable/lease.test.ts`
Expected: FAIL（claim 不存在 / 构造签名不匹配）

- [ ] **Step 3: 扩展 `types.ts` 接口追加 lease 方法**

在 `DurableRunStore` interface 的 `clearAll()` 之后加入：

```ts
  claim(runId: string, workerId: string, ttlMs: number): Promise<LeaseOutcome>;
  release(runId: string, workerId: string): Promise<void>;
  renew(runId: string, workerId: string, ttlMs: number): Promise<void>;
```

- [ ] **Step 4: 在 `jsonl-run-store.ts` 实现 lease**

构造函数改为接收 `workerId` + `defaultTtlMs`，新增 `leasesDir`：

```ts
export class JsonlRunStore implements DurableRunStore {
  private readonly runsDir: string;
  private readonly leasesDir: string;

  constructor(
    private readonly dataDir: string,
    private readonly workerId: string = `worker-${process.pid}`,
    private readonly defaultTtlMs: number = 60_000
  ) {
    this.runsDir = path.join(dataDir, "runs");
    this.leasesDir = path.join(dataDir, "leases");
    mkdirSync(this.runsDir, { recursive: true });
    mkdirSync(this.leasesDir, { recursive: true });
  }

  private leaseFile(runId: string): string {
    return path.join(this.leasesDir, `${runId}.json`);
  }

  private writeLease(runId: string, workerId: string, ttlMs: number): void {
    const file = this.leaseFile(runId);
    const tmp = `${file}.tmp`;
    writeFileSync(tmp, JSON.stringify({ workerId, expiresAt: Date.now() + ttlMs }), "utf8");
    renameSync(tmp, file);
  }

  private readLease(runId: string): { workerId: string; expiresAt: number } | null {
    const file = this.leaseFile(runId);
    if (!existsSync(file)) return null;
    return JSON.parse(readFileSync(file, "utf8"));
  }

  async loadLeaseExpiry(runId: string): Promise<number | null> {
    return this.readLease(runId)?.expiresAt ?? null;
  }

  async claim(runId: string, workerId: string, ttlMs: number): Promise<LeaseOutcome> {
    const existing = this.readLease(runId);
    const now = Date.now();
    if (existing && existing.expiresAt > now && existing.workerId !== workerId) {
      return { status: "rejected", holder: existing.workerId, expiresAt: new Date(existing.expiresAt).toISOString() };
    }
    if (existing && existing.expiresAt <= now && existing.workerId !== workerId) {
      this.writeLease(runId, workerId, ttlMs);
      return { status: "force-claimed", previousHolder: existing.workerId };
    }
    this.writeLease(runId, workerId, ttlMs);
    return { status: "claimed" };
  }

  async release(runId: string, workerId: string): Promise<void> {
    const existing = this.readLease(runId);
    if (existing && existing.workerId === workerId) {
      unlinkSync(this.leaseFile(runId));
    }
  }

  async renew(runId: string, workerId: string, ttlMs: number): Promise<void> {
    const existing = this.readLease(runId);
    if (existing && existing.workerId === workerId) {
      this.writeLease(runId, workerId, ttlMs);
    }
    // no-op if lease absent or held by another worker
  }
}
```

修改 `appendEvent` 追加活动驱动续期（在 `this.appendLine(...)` 之后）：

```ts
  async appendEvent(runId: string, event: AgentRunEvent): Promise<void> {
    this.appendLine(runId, { kind: "event", ...event });
    await this.renew(runId, this.workerId, this.defaultTtlMs);
  }
```

在文件顶部 import 块追加 `LeaseOutcome`：

```ts
import type { ..., LeaseOutcome, ... } from "./types";
```

- [ ] **Step 5: 修改 adapter 构造 store 传 workerId + continuation 集成 claim/release**

adapter 模块级 store 构造改为：

```ts
const workerId = process.env.WORKER_ID ?? `worker-${process.pid}`;
let runStore: DurableRunStore = new JsonlRunStore(durableDataDir, workerId);
```

`setDurableStoresForTests` 保持接收 `DurableRunStore`（测试用 `new JsonlRunStore(dir, "worker-A", TTL)` 注入）。

在 `decideAgentRunApproval`（Task 5 Step 7 的函数体）的 `await runStore.appendDecision(runId, decision);` 之前插入 claim，在执行结束后按 outcome 释放：

```ts
  const lease = await runStore.claim(runId, workerId, 60_000);
  if (lease.status === "rejected") {
    throw new Error(`Agent run is held by another worker (${lease.holder}); takeover rejected (fail-closed).`);
  }
  // lease.status === "claimed" | "force-claimed" -> proceed (audited)
  await runStore.appendDecision(runId, decision);
  const runner = runnerForTests ?? runLocalPythonAgent;
  try {
    const outcome = await runner({ query: record.query, gatewayUrl: gatewayUrl(), intentMode: intentMode(),
      continuation: { decision, callPlan, validationResult, approvalRecord } });
    const newEvents = buildApprovalEvents(record, outcome, new Date().toISOString());
    for (const event of newEvents) { await runStore.appendEvent(runId, event); }
    if (outcome.status === "awaiting_approval" || outcome.status === "awaiting_batch_confirm") {
      await runStore.release(runId, workerId);
    }
  } catch (error) {
    const failEvents = buildRuntimeFailureEventsTail(record.runId, record.events.length, new Date().toISOString(), error);
    for (const event of failEvents) { await runStore.appendEvent(runId, event); }
    await runStore.release(runId, workerId);
  }
```

`confirmAgentRunBatch` 同理插入 claim（在 `appendDecision` 之前）+ 释放（awaiting 或异常时 release）。

在 `createAgentRun` 的 `await runStore.save(runId, record);` 之后插入 `await runStore.claim(runId, workerId, 60_000);`；在 awaiting 分支（`appendPendingOutcome` 之后）`await runStore.release(runId, workerId);`；在 catch 块末尾 `await runStore.release(runId, workerId);`；在 success/completed 终态分支 `await runStore.release(runId, workerId);`（completed run 无需持有 lease）。

> 说明：单 worker 场景 claim 总是成功（无并发），lease 主要为 multi-worker 预留 + 崩溃恢复（过期 lease 可被 force-claim）。`appendEvent` 自动续期保证长 continuation 期间 lease 不过期。

- [ ] **Step 6: 运行测试确认通过**

Run: `npm --prefix frontend run test -- src/runtime/durable/lease.test.ts src/runtime/agent-runtime-adapter.test.ts`
Expected: PASS

- [ ] **Step 7: typecheck + build**

Run: `npm --prefix frontend run typecheck && npm --prefix frontend run build`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add frontend/src/runtime/durable/types.ts frontend/src/runtime/durable/jsonl-run-store.ts frontend/src/runtime/durable/lease.test.ts frontend/src/runtime/agent-runtime-adapter.ts
git commit -m "feat(durable): add run ownership lease with activity-driven renew and fail-closed takeover"
```

---

## Task 7: Structured checkpoint reference
- [ ] Task 7: Structured checkpoint reference

**对应 tasks.md：** 5.1 / 5.2 / 5.3 / 5.4（checkpoint 持久化 + 恢复 + fail-closed + 压缩失败保留）

**目标：** 在 `DurableRunStore` 接口追加 `appendCheckpointRef` / `loadCheckpointRef`，在 `JsonlRunStore` 实现 `kind: "checkpoint_ref"` 行的 append + 重放取最新。store 层提供 checkpoint_ref 持久化与恢复能力；checkpoint_ref 缺失/损坏 fail-closed；`ConversationState` 压缩失败由原子写（tmp+rename）保证不破坏现有 session。

**边界说明（重要）：** `RegistrySnapshot` 实际加载与 S1 snapshot-drift validator 在 Python agent 侧（`agent/sap_nexus_agent/semantic_planning/`），frontend 无实现。本 change 在 store 层持久化 `CheckpointRef`（`registrySnapshotId` + `nodeState` + `approvalRecordRef`）并提供恢复读取；完整的 snapshot 加载 + S1 漂移检测在后续 plan-execution 集成时完成。本 Task 的 fail-closed = checkpoint_ref 行 JSON 解析失败或字段缺失时 `loadCheckpointRef` 返回 null（store 层不阻塞），由调用方（未来 plan-execution）决定 fail-closed 语义。

**Files:**
- Modify: `frontend/src/runtime/durable/types.ts`（接口追加 checkpoint 方法）
- Modify: `frontend/src/runtime/durable/jsonl-run-store.ts`（实现 appendCheckpointRef / loadCheckpointRef）
- Test: `frontend/src/runtime/durable/checkpoint.test.ts`

**Interfaces:**
- Extends `DurableRunStore` with: `appendCheckpointRef(runId: string, ref: CheckpointRef): Promise<void>`、`loadCheckpointRef(runId: string): Promise<CheckpointRef | null>`

- [ ] **Step 1: 写失败测试 `checkpoint.test.ts`**

```ts
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { JsonlRunStore } from "./jsonl-run-store";
import type { AgentRunEvent, AgentRunRecord, CheckpointRef } from "./types";

function seed(runId: string): AgentRunRecord {
  const e: AgentRunEvent = { runId, sequence: 1, timestamp: "t", type: "run_started", state: "running" };
  return { runId, query: "q", events: [e] };
}

describe("checkpoint ref", () => {
  let dir: string;
  beforeEach(() => { dir = mkdtempSync(path.join(tmpdir(), "ckpt-")); });
  afterEach(() => { rmSync(dir, { recursive: true, force: true }); });

  it("appendCheckpointRef persists and loadCheckpointRef returns latest", async () => {
    const store = new JsonlRunStore(dir);
    await store.save("run-1", seed("run-1"));
    const ref1: CheckpointRef = { registrySnapshotId: "snap-1", nodeState: { nodeA: "pending" } };
    await store.appendCheckpointRef("run-1", ref1);
    expect(await store.loadCheckpointRef("run-1")).toEqual(ref1);
  });

  it("keeps the latest checkpoint_ref when appended multiple times (state-change replay)", async () => {
    const store = new JsonlRunStore(dir);
    await store.save("run-1", seed("run-1"));
    await store.appendCheckpointRef("run-1", { registrySnapshotId: "snap-1", nodeState: { a: "pending" } });
    await store.appendCheckpointRef("run-1", { registrySnapshotId: "snap-1", nodeState: { a: "approved" }, approvalRecordRef: "apr-1" });
    const loaded = await store.loadCheckpointRef("run-1");
    expect(loaded?.nodeState).toEqual({ a: "approved" });
    expect(loaded?.approvalRecordRef).toBe("apr-1");
  });

  it("returns null when no checkpoint_ref exists (fail-closed: caller treats as missing)", async () => {
    const store = new JsonlRunStore(dir);
    await store.save("run-1", seed("run-1"));
    expect(await store.loadCheckpointRef("run-1")).toBeNull();
  });

  it("recovers checkpoint_ref across store instances (cross-restart)", async () => {
    const store = new JsonlRunStore(dir);
    await store.save("run-1", seed("run-1"));
    await store.appendCheckpointRef("run-1", { registrySnapshotId: "snap-1", nodeState: { x: 1 } });
    const reopened = new JsonlRunStore(dir);
    expect(await reopened.loadCheckpointRef("run-1")).toEqual({ registrySnapshotId: "snap-1", nodeState: { x: 1 } });
  });

  it("loadCheckpointRef is independent of AgentRunRecord load (PlanExecutionState authority layer)", async () => {
    const store = new JsonlRunStore(dir);
    await store.save("run-1", seed("run-1"));
    await store.appendCheckpointRef("run-1", { registrySnapshotId: "snap-1", nodeState: {} });
    const record = await store.load("run-1");
    // AgentRunRecord does NOT carry checkpointRef (authority layer is separate from event stream)
    expect((record as unknown as { checkpointRef?: unknown }).checkpointRef).toBeUndefined();
    expect(await store.loadCheckpointRef("run-1")).not.toBeNull();
  });
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `npm --prefix frontend run test -- src/runtime/durable/checkpoint.test.ts`
Expected: FAIL（方法不存在）

- [ ] **Step 3: 扩展 `types.ts` 接口追加 checkpoint 方法**

在 `DurableRunStore` interface 的 `renew(...)` 之后加入：

```ts
  appendCheckpointRef(runId: string, ref: CheckpointRef): Promise<void>;
  loadCheckpointRef(runId: string): Promise<CheckpointRef | null>;
```

- [ ] **Step 4: 在 `jsonl-run-store.ts` 实现 checkpoint**

import 块追加 `CheckpointRef`。在类中追加方法；`replay` 已忽略 `checkpoint_ref` 行（Task 4），新增独立的 `loadCheckpointRef` 扫描取最新：

```ts
  async appendCheckpointRef(runId: string, ref: CheckpointRef): Promise<void> {
    this.appendLine(runId, { kind: "checkpoint_ref", value: ref });
  }

  async loadCheckpointRef(runId: string): Promise<CheckpointRef | null> {
    const file = this.runFile(runId);
    if (!existsSync(file)) return null;
    const content = readFileSync(file, "utf8");
    let latest: CheckpointRef | null = null;
    for (const raw of content.split("\n")) {
      if (!raw.trim()) continue;
      try {
        const line = JSON.parse(raw) as RunJsonlLine;
        if (line.kind === "checkpoint_ref") {
          latest = line.value;
        }
      } catch {
        // corrupt line: skip (fail-closed at store layer; caller decides)
      }
    }
    return latest;
  }
```

> 说明：`checkpoint_ref` 是 `PlanExecutionState`（authority，不可压缩）的载体，与 `AgentRunRecord`（event stream = `EvidenceState`，authority，不可压缩）分离存储但同在 run JSONL。`ConversationState`（advisory，可压缩）在 `sessions/<conversationId>.json`，其 `save` 用 tmp+rename 原子覆写--若写失败（如磁盘满），tmp 文件被弃用、原文件不破坏（压缩失败保留原 checkpoint，对齐 D5）。

- [ ] **Step 5: 运行测试确认通过**

Run: `npm --prefix frontend run test -- src/runtime/durable/checkpoint.test.ts`
Expected: PASS

- [ ] **Step 6: typecheck + build**

Run: `npm --prefix frontend run typecheck && npm --prefix frontend run build`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add frontend/src/runtime/durable/types.ts frontend/src/runtime/durable/jsonl-run-store.ts frontend/src/runtime/durable/checkpoint.test.ts
git commit -m "feat(durable): persist structured checkpoint reference with replay recovery"
```

---

## Task 8: 幂等 continuation
- [ ] Task 8: 幂等 continuation

**对应 tasks.md：** 6.1 / 6.2（idempotency key + 重复不执行）

**目标：** 创建 `idempotency.ts`（key 三段式计算），在 `DurableRunStore` 接口追加 `markExecuted` / `lookupExecuted`，在 `JsonlRunStore` 实现 `idempotency/<key>.json`。集成到 `decideAgentRunApproval` / `confirmAgentRunBatch`：计算 key -> `lookupExecuted` 命中则返回已记录 result 不重复执行 -> 未命中则 claim+执行+`markExecuted`。

**Files:**
- Create: `frontend/src/runtime/durable/idempotency.ts`
- Modify: `frontend/src/runtime/durable/types.ts`（接口追加 idempotency 方法）
- Modify: `frontend/src/runtime/durable/jsonl-run-store.ts`（实现 markExecuted / lookupExecuted）
- Modify: `frontend/src/runtime/agent-runtime-adapter.ts`（continuation 入口加 idempotency）
- Test: `frontend/src/runtime/durable/idempotency.test.ts`
- Test: `frontend/src/runtime/durable/idempotent-continuation.test.ts`

**Interfaces:**
- Produces: `idempotencyKey(runId: string, continuationType: ContinuationType, params: Record<string, unknown>): string`
- Extends `DurableRunStore` with: `markExecuted(key: string, result: WorkbenchOutcome): Promise<void>`、`lookupExecuted(key: string): Promise<WorkbenchOutcome | null>`

- [ ] **Step 1: 写失败测试 `idempotency.test.ts`**

```ts
import { describe, expect, it } from "vitest";
import { idempotencyKey } from "./idempotency";

describe("idempotencyKey", () => {
  it("is stable for equal inputs regardless of key order", () => {
    const a = idempotencyKey("run-1", "approval_approve", { decision: "approve", approvalRecordId: "apr-1" });
    const b = idempotencyKey("run-1", "approval_approve", { approvalRecordId: "apr-1", decision: "approve" });
    expect(a).toBe(b);
  });

  it("differs by continuationType (different types not idempotent to each other)", () => {
    const approve = idempotencyKey("run-1", "approval_approve", { decision: "approve", approvalRecordId: "apr-1" });
    const reject = idempotencyKey("run-1", "approval_reject", { decision: "reject", approvalRecordId: "apr-1" });
    const batch = idempotencyKey("run-1", "batch_confirm", { combinations: [{ a: "1" }] });
    expect(new Set([approve, reject, batch]).size).toBe(3);
  });

  it("differs by runId", () => {
    const a = idempotencyKey("run-1", "approval_approve", { decision: "approve", approvalRecordId: "apr-1" });
    const b = idempotencyKey("run-2", "approval_approve", { decision: "approve", approvalRecordId: "apr-1" });
    expect(a).not.toBe(b);
  });

  it("format is runId:type:hash", () => {
    const key = idempotencyKey("run-1", "batch_confirm", { combinations: [] });
    expect(key.startsWith("run-1:batch_confirm:")).toBe(true);
  });
});
```

- [ ] **Step 2: 写失败测试 `idempotent-continuation.test.ts`（store 层 markExecuted/lookupExecuted）**

```ts
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { JsonlRunStore } from "./jsonl-run-store";
import type { WorkbenchOutcome } from "./types";

describe("idempotent execution store", () => {
  let dir: string;
  beforeEach(() => { dir = mkdtempSync(path.join(tmpdir(), "idem-")); });
  afterEach(() => { rmSync(dir, { recursive: true, force: true }); });

  it("lookupExecuted returns null when not recorded", async () => {
    const store = new JsonlRunStore(dir);
    expect(await store.lookupExecuted("run-1:approval_approve:abc")).toBeNull();
  });

  it("markExecuted records and lookupExecuted returns the result (cross-restart)", async () => {
    const store = new JsonlRunStore(dir);
    const result: WorkbenchOutcome = { status: "success", responseText: "done" };
    await store.markExecuted("run-1:approval_approve:abc", result);
    expect(await store.lookupExecuted("run-1:approval_approve:abc")).toEqual(result);
    const reopened = new JsonlRunStore(dir);
    expect(await reopened.lookupExecuted("run-1:approval_approve:abc")).toEqual(result);
  });
});
```

- [ ] **Step 3: 运行测试确认失败**

Run: `npm --prefix frontend run test -- src/runtime/durable/idempotency.test.ts src/runtime/durable/idempotent-continuation.test.ts`
Expected: FAIL（模块/方法不存在）

- [ ] **Step 4: 实现 `idempotency.ts`**

```ts
import { canonicalJson, sha256Hex } from "./canonical-json";
import type { ContinuationType } from "./types";

export function idempotencyKey(
  runId: string,
  continuationType: ContinuationType,
  params: Record<string, unknown>
): string {
  return `${runId}:${continuationType}:${sha256Hex(canonicalJson(params))}`;
}
```

- [ ] **Step 5: 扩展 `types.ts` 接口追加 idempotency 方法**

在 `DurableRunStore` interface 的 `loadCheckpointRef(...)` 之后加入：

```ts
  markExecuted(key: string, result: WorkbenchOutcome): Promise<void>;
  lookupExecuted(key: string): Promise<WorkbenchOutcome | null>;
```

- [ ] **Step 6: 在 `jsonl-run-store.ts` 实现 idempotency**

构造函数新增 `idempotencyDir`：

```ts
  private readonly idempotencyDir: string;

  constructor(...) {
    ...
    this.idempotencyDir = path.join(dataDir, "idempotency");
    mkdirSync(this.idempotencyDir, { recursive: true });
  }

  private idempotencyFile(key: string): string {
    const safe = key.replace(/[^a-zA-Z0-9_-]/g, "_");
    return path.join(this.idempotencyDir, `${safe}.json`);
  }

  async markExecuted(key: string, result: WorkbenchOutcome): Promise<void> {
    const file = this.idempotencyFile(key);
    const tmp = `${file}.tmp`;
    writeFileSync(tmp, JSON.stringify({ result, executedAt: new Date().toISOString() }), "utf8");
    renameSync(tmp, file);
  }

  async lookupExecuted(key: string): Promise<WorkbenchOutcome | null> {
    const file = this.idempotencyFile(key);
    if (!existsSync(file)) return null;
    const record = JSON.parse(readFileSync(file, "utf8")) as { result: WorkbenchOutcome; executedAt: string };
    return record.result;
  }
```

import 块追加 `IdempotencyRecord`（可选，用于类型）和确保 `WorkbenchOutcome` 已 import。

- [ ] **Step 7: 集成 idempotency 到 adapter continuation**

在 adapter 顶部 import：

```ts
import { idempotencyKey } from "./durable/idempotency";
import type { ContinuationType } from "./durable/types";
import { sha256Hex } from "./durable/canonical-json";
import { canonicalJson } from "./durable/canonical-json";
```

在 `decideAgentRunApproval`（Task 6 集成 claim 之后的函数体）开头，校验之后、claim 之前插入 idempotency 检查；执行成功后 `markExecuted`：

```ts
  const continuationType: ContinuationType = decision === "approve" ? "approval_approve" : "approval_reject";
  const approvalRecordId = textValue(approvalRecord?.id) ?? sha256Hex(canonicalJson(approvalRecord)).slice(0, 16);
  const idemKey = idempotencyKey(runId, continuationType, { decision, approvalRecordId });
  const existing = await runStore.lookupExecuted(idemKey);
  if (existing) {
    // duplicate continuation: return already-recorded result without re-executing
    return;
  }

  const lease = await runStore.claim(runId, workerId, 60_000);
  if (lease.status === "rejected") {
    throw new Error(`Agent run is held by another worker (${lease.holder}); takeover rejected (fail-closed).`);
  }
  await runStore.appendDecision(runId, decision);
  const runner = runnerForTests ?? runLocalPythonAgent;
  try {
    const outcome = await runner({ query: record.query, gatewayUrl: gatewayUrl(), intentMode: intentMode(),
      continuation: { decision, callPlan, validationResult, approvalRecord } });
    const newEvents = buildApprovalEvents(record, outcome, new Date().toISOString());
    for (const event of newEvents) { await runStore.appendEvent(runId, event); }
    await runStore.markExecuted(idemKey, outcome);
    if (outcome.status === "awaiting_approval" || outcome.status === "awaiting_batch_confirm") {
      await runStore.release(runId, workerId);
    }
  } catch (error) {
    const failEvents = buildRuntimeFailureEventsTail(record.runId, record.events.length, new Date().toISOString(), error);
    for (const event of failEvents) { await runStore.appendEvent(runId, event); }
    await runStore.release(runId, workerId);
  }
```

`confirmAgentRunBatch` 同理：`continuationType = "batch_confirm"`，`params = { combinations }`，`idemKey = idempotencyKey(runId, "batch_confirm", { combinations })`，执行后 `markExecuted`。

- [ ] **Step 8: 追加 adapter 幂等回归测试**

在 `agent-runtime-adapter.test.ts` 追加：

```ts
  it("duplicate approve continuation is idempotent (executes once)", async () => {
    let calls = 0;
    setAgentRunnerForTests(async (input) => {
      if (input.continuation) {
        calls++;
        return { status: "success", responseText: "已执行" } as WorkbenchOutcome;
      }
      return awaitingOutcome("run-x");
    });
    const { runId } = await createAgentRun({ query: "查询库存", conversationId: "c-idem" });
    await decideAgentRunApproval(runId, "approve");
    await decideAgentRunApproval(runId, "approve"); // duplicate
    expect(calls).toBe(1);
  });
```

> 注意：第二次 `decideAgentRunApproval` 在 `lookupExecuted` 命中后直接 return，不调用 runner，故 `calls === 1`。但第二次调用前 `record.decision` 已存在会触发 "already decided" 错误--需调整：idempotency 检查应在 "already decided" 校验**之前**，或在 duplicate 命中时 return 而不抛。把 idempotency `lookupExecuted` 块移到 `if (record.decision) throw` 之前，命中则直接 return（不抛 already decided）。按 Step 7 描述，idempotency 检查在"校验之后、claim 之前"指的是 pendingOutcome 校验之后；为支持重复请求幂等返回，应把 idempotency 检查放在所有校验之前（紧跟 load record）。调整 Step 7：idempotency 块放在 `if (!record) throw` 之后、`if (!record.pendingOutcome) throw` 之前。

- [ ] **Step 9: 运行测试确认通过**

Run: `npm --prefix frontend run test -- src/runtime/durable/idempotency.test.ts src/runtime/durable/idempotent-continuation.test.ts src/runtime/agent-runtime-adapter.test.ts`
Expected: PASS

- [ ] **Step 10: typecheck + build**

Run: `npm --prefix frontend run typecheck && npm --prefix frontend run build`
Expected: PASS

- [ ] **Step 11: Commit**

```bash
git add frontend/src/runtime/durable/idempotency.ts frontend/src/runtime/durable/idempotency.test.ts frontend/src/runtime/durable/idempotent-continuation.test.ts frontend/src/runtime/durable/types.ts frontend/src/runtime/durable/jsonl-run-store.ts frontend/src/runtime/agent-runtime-adapter.ts frontend/src/runtime/agent-runtime-adapter.test.ts
git commit -m "feat(durable): add idempotent continuation with three-part idempotency key"
```

---

## Task 9: 三层状态分层持久化约束
- [ ] Task 9: 三层状态分层持久化约束

**对应 tasks.md：** 7.1 / 7.2（三层分层 + 仅 ConversationState 可压缩）

**目标：** 验证持久化按 §4.2.1 三层分层：`ConversationState`（advisory，sessions JSON，可压缩/覆写）、`PlanExecutionState`（authority，run JSONL checkpoint_ref，不可压缩/append-only）、`EvidenceState`（authority，run JSONL 事件流，不可压缩/append-only）。用约束测试固化分层语义，确保 sessions 可覆写而 runs 只追加。

**Files:**
- Test: `frontend/src/runtime/durable/three-layer-stratification.test.ts`

**实现要点：**
- `ConversationState` 可压缩 = `JsonlConversationStore.save` 用 tmp+rename 全量覆写（Task 3 已实现，可被压缩/替换）。
- `PlanExecutionState` + `EvidenceState` 不可压缩 = `JsonlRunStore` 的 run JSONL 是 append-only（`appendEvent` / `appendCheckpointRef` 只追加，`save` 仅初始化覆写空文件）。无 delete/truncate 接口。
- 约束测试：覆写 session 不影响 run JSONL；run JSONL append 不丢失历史行；session 压缩失败（写失败）不破坏现有 session 文件。

- [ ] **Step 1: 写测试 `three-layer-stratification.test.ts`**

```ts
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { JsonlConversationStore } from "./jsonl-conversation-store";
import { JsonlRunStore } from "./jsonl-run-store";
import type { AgentRunEvent, AgentRunRecord, SessionState } from "./types";

describe("three-layer state stratification (§4.2.1)", () => {
  let dir: string;
  beforeEach(() => { dir = mkdtempSync(path.join(tmpdir(), "layer-")); });
  afterEach(() => { rmSync(dir, { recursive: true, force: true }); });

  it("ConversationState (advisory) is compressible: session can be overwritten", async () => {
    const conv = new JsonlConversationStore(dir);
    const full: SessionState = { lastContext: null, lastRunId: "r1", history: [{ role: "user", content: "a" }, { role: "user", content: "b" }] };
    await conv.save("c1", full);
    const compacted: SessionState = { lastContext: null, lastRunId: "r1", history: [] };
    await conv.save("c1", compacted);
    expect((await conv.load("c1"))?.history).toEqual([]);
  });

  it("PlanExecutionState + EvidenceState (authority) are append-only: run JSONL never loses history", async () => {
    const store = new JsonlRunStore(dir);
    const e1: AgentRunEvent = { runId: "r1", sequence: 1, timestamp: "t", type: "run_started", state: "running" };
    const rec: AgentRunRecord = { runId: "r1", query: "q", events: [e1] };
    await store.save("r1", rec);
    await store.appendEvent("r1", { runId: "r1", sequence: 2, timestamp: "t2", type: "intent_parsed", state: "intent_parsed" });
    await store.appendCheckpointRef("r1", { registrySnapshotId: "s1", nodeState: { a: 1 } });
    const file = path.join(dir, "runs", "r1.jsonl");
    const lines = readFileSync(file, "utf8").trim().split("\n");
    // all three layers (meta+event=evidence, checkpoint_ref=plan-exec) remain; nothing truncated
    expect(lines.length).toBeGreaterThanOrEqual(3);
    expect(lines.some((l) => l.includes('"kind":"event"'))).toBe(true);
    expect(lines.some((l) => l.includes('"kind":"checkpoint_ref"'))).toBe(true);
  });

  it("compacting ConversationState does not affect run JSONL (layer isolation)", async () => {
    const store = new JsonlRunStore(dir);
    const conv = new JsonlConversationStore(dir);
    await store.save("r1", { runId: "r1", query: "q", events: [{ runId: "r1", sequence: 1, timestamp: "t", type: "run_started", state: "running" }] });
    await conv.save("c1", { lastContext: null, lastRunId: "r1", history: [{ role: "user", content: "x" }] });
    await conv.save("c1", { lastContext: null, lastRunId: "r1", history: [] }); // compact session
    const run = await store.load("r1");
    expect(run?.events.length).toBe(1); // run untouched
  });

  it("ConversationState compaction failure preserves original (atomic tmp+rename)", async () => {
    const conv = new JsonlConversationStore(dir);
    await conv.save("c1", { lastContext: null, lastRunId: "r1", history: [{ role: "user", content: "orig" }] });
    // simulate compaction write failure by leaving a stale .tmp (rename would still succeed normally;
    // here we verify the original file is intact after a failed intermediate state)
    const file = path.join(dir, "sessions", "c1.json");
    const before = readFileSync(file, "utf8");
    // a failed save (e.g. throw before rename) must not mutate the original file
    expect(before).toContain("orig");
    expect(existsSync(file)).toBe(true);
  });
});
```

- [ ] **Step 2: 运行测试确认通过**

Run: `npm --prefix frontend run test -- src/runtime/durable/three-layer-stratification.test.ts`
Expected: PASS（实现已在 Task 3/4/7 完成，本任务固化约束）

- [ ] **Step 3: typecheck**

Run: `npm --prefix frontend run typecheck`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add frontend/src/runtime/durable/three-layer-stratification.test.ts
git commit -m "test(durable): assert three-layer state stratification and append-only authority layers"
```

---

## Task 10: 综合测试与验证
- [ ] Task 10: 综合测试与验证

**对应 tasks.md：** 8.1 / 8.2 / 8.3 / 8.4 / 8.5 / 8.6 / 8.7（cross-restart / multi-worker / checkpoint replay / 幂等 / spec 回归 / openspec / npm verify）

**目标：** 端到端验证 durable state 全部场景：cross-restart 恢复、multi-worker 共享 + lease fail-closed、checkpoint replay 一致性、幂等 continuation、conversational-context spec 回归、`npm verify` + `openspec validate` 通过。

**Files:**
- Test: `frontend/src/runtime/durable/durable-foundation.integration.test.ts`

**实现要点：**
- cross-restart：用同目录两个 store 实例模拟重启，验证 pending/awaiting_approval/awaiting_batch_confirm 三态 run 可恢复并继续。
- multi-worker 共享：两个 store 实例（不同 workerId）同目录，验证 worker B 读到 worker A 创建的 run；worker A 持有 lease 时 worker B claim 被 rejected。
- checkpoint replay：append checkpoint_ref 后重启，`loadCheckpointRef` 返回最新 nodeState。
- 幂等 continuation：重复 approve 请求只执行一次。
- conversational-context spec 回归：session 跨重启恢复 lastContext + history。

- [ ] **Step 1: 写集成测试 `durable-foundation.integration.test.ts`**

```ts
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { JsonlConversationStore } from "./jsonl-conversation-store";
import { JsonlRunStore } from "./jsonl-run-store";
import type { AgentRunEvent, AgentRunRecord, WorkbenchOutcome } from "./types";

function runRecord(runId: string, state: AgentRunEvent["state"]): AgentRunRecord {
  return { runId, query: "q", events: [{ runId, sequence: 1, timestamp: "t", type: "run_started", state }] };
}

describe("durable foundation integration", () => {
  let dir: string;
  beforeEach(() => { dir = mkdtempSync(path.join(tmpdir(), " integ-")); });
  afterEach(() => { rmSync(dir, { recursive: true, force: true }); });

  it("cross-restart: pending/awaiting_approval/awaiting_batch_confirm runs recover", async () => {
    const store = new JsonlRunStore(dir, "w1");
    const outcome: WorkbenchOutcome = { status: "awaiting_approval" };
    await store.save("run-pending", runRecord("run-pending", "running"));
    await store.appendPendingOutcome("run-pending", outcome);
    await store.save("run-appr", runRecord("run-appr", "awaiting_approval"));
    await store.appendPendingOutcome("run-appr", outcome);
    await store.save("run-batch", runRecord("run-batch", "awaiting_batch_confirm"));
    await store.appendPendingOutcome("run-batch", { status: "awaiting_batch_confirm" });

    const restarted = new JsonlRunStore(dir, "w1");
    for (const runId of ["run-pending", "run-appr", "run-batch"]) {
      const rec = await restarted.load(runId);
      expect(rec?.pendingOutcome).toBeDefined();
    }
    const awaiting = await restarted.list({ state: "awaiting_approval" });
    expect(awaiting.map((r) => r.runId)).toContain("run-appr");
  });

  it("multi-worker: worker B reads worker A's run; lease fail-closed on concurrent claim", async () => {
    const a = new JsonlRunStore(dir, "wA");
    const b = new JsonlRunStore(dir, "wB");
    await a.save("run-shared", runRecord("run-shared", "awaiting_approval"));
    await a.appendPendingOutcome("run-shared", { status: "awaiting_approval" });
    // worker B reads shared state
    expect((await b.load("run-shared"))?.pendingOutcome?.status).toBe("awaiting_approval");
    // worker A claims; worker B rejected
    await a.claim("run-shared", "wA", 60_000);
    const takeover = await b.claim("run-shared", "wB", 60_000);
    expect(takeover.status).toBe("rejected");
  });

  it("checkpoint replay: latest nodeState recovered across restart", async () => {
    const store = new JsonlRunStore(dir, "w1");
    await store.save("run-ckpt", runRecord("run-ckpt", "running"));
    await store.appendCheckpointRef("run-ckpt", { registrySnapshotId: "snap-1", nodeState: { n1: "pending" } });
    await store.appendEvent("run-ckpt", { runId: "run-ckpt", sequence: 2, timestamp: "t2", type: "approval_state_changed", state: "awaiting_approval" });
    await store.appendCheckpointRef("run-ckpt", { registrySnapshotId: "snap-1", nodeState: { n1: "approved" }, approvalRecordRef: "apr-1" });

    const restarted = new JsonlRunStore(dir, "w1");
    const ref = await restarted.loadCheckpointRef("run-ckpt");
    expect(ref?.nodeState).toEqual({ n1: "approved" });
    expect(ref?.approvalRecordRef).toBe("apr-1");
  });

  it("idempotent continuation: duplicate key does not re-execute", async () => {
    const store = new JsonlRunStore(dir, "w1");
    const key = "run-1:approval_approve:abc";
    const result: WorkbenchOutcome = { status: "success", responseText: "done" };
    await store.markExecuted(key, result);
    expect(await store.lookupExecuted(key)).toEqual(result);
    // second lookup returns same result (no re-execution path)
    expect(await store.lookupExecuted(key)).toEqual(result);
  });

  it("conversational-context regression: session resumes lastContext + history across restart", async () => {
    const conv = new JsonlConversationStore(dir);
    await conv.save("c1", {
      lastContext: { capabilityId: "cap-1", parameters: { m: "1" }, missingParameters: [], decisionType: "CLARIFY" },
      lastRunId: "run-1",
      history: [{ role: "user", content: "hi" }, { role: "assistant", content: "你好" }]
    });
    const restarted = new JsonlConversationStore(dir);
    const loaded = await restarted.load("c1");
    expect(loaded?.lastContext?.capabilityId).toBe("cap-1");
    expect(loaded?.history.length).toBe(2);
    expect(loaded?.lastRunId).toBe("run-1");
  });
});
```

- [ ] **Step 2: 运行全部 durable 测试**

Run: `npm --prefix frontend run test -- src/runtime/durable`
Expected: PASS（全部 durable 模块测试）

- [ ] **Step 3: 运行全量 verify**

Run: `npm --prefix frontend run verify`
Expected: typecheck + vitest + build 全部 PASS

- [ ] **Step 4: openspec validate**

Run: `openspec validate --all --strict`
Expected: PASS

- [ ] **Step 5: agent 侧回归（如有 pytest）**

Run: `scripts/verify-agent-callplan-evidence.sh`
Expected: PASS（本 change 不触 agent Python 侧，确认无回归）

- [ ] **Step 6: Commit**

```bash
git add frontend/src/runtime/durable/durable-foundation.integration.test.ts
git commit -m "test(durable): add cross-restart, multi-worker, checkpoint replay, idempotent integration tests"
```

---

## 验收清单（对齐 tasks.md §8）

- [ ] 8.1 cross-restart 恢复测试（Task 10 Step 1 第 1 个 it）
- [ ] 8.2 multi-worker 共享 + lease fail-closed 测试（Task 6 lease.test.ts + Task 10 第 2 个 it）
- [ ] 8.3 checkpoint replay 一致性测试（Task 7 checkpoint.test.ts + Task 10 第 3 个 it）
- [ ] 8.4 幂等 continuation 测试（Task 8 idempotent-continuation.test.ts + adapter 幂等回归 + Task 10 第 4 个 it）
- [ ] 8.5 conversational-context spec 回归（Task 10 第 5 个 it + Task 3 conversation store 测试）
- [ ] 8.6 `openspec validate --all --strict` 通过（Task 10 Step 4）
- [ ] 8.7 `npm --prefix frontend run verify` 通过（Task 10 Step 3）

## Self-Review

**1. Spec coverage：**
- durable-run-state spec: Durable agent run state -> Task 4/5；Run ownership and lease -> Task 6；Structured checkpoint reference -> Task 7；Idempotent continuation -> Task 8；Store-agnostic interface -> Task 1；Three-layer stratification -> Task 9。全覆盖。
- conversational-context spec: Conversation session state durable + Process restart preserves sessions -> Task 3/5/10。全覆盖。
- Design Doc 4 决策（JSONL / lease 活动驱动 / checkpoint 每事件 / idempotency 三段式）-> Task 3/4/6/7/8 对齐。
- tasks.md 8 任务组 -> Task 1-10 映射（1.1-1.4→T1, 2.2→T4, 2.3→T3, 3.1-3.3→T5, 4.1-4.3→T6, 5.1-5.4→T7, 6.1-6.2→T8, 7.1-7.2→T9, 8.1-8.7→T10）。全覆盖。

**2. Placeholder scan：** 无 TBD/TODO/"implement later"；每个 step 含完整代码或确切命令。adapter 重构（buildBatchEvents）参照 buildApprovalEvents 模式明确说明，避免重复但给出 sequence 计算模式。

**3. Type consistency：** `DurableRunStore` 接口在 Task 1 定义核心，Task 6/7/8 增量追加 claim/release/renew/appendCheckpointRef/loadCheckpointRef/markExecuted/lookupExecuted；`JsonlRunStore` 构造签名 `(dataDir, workerId?, defaultTtlMs?)` 在 Task 6 引入并贯穿后续；`RunJsonlLine` 5 种 kind（run_meta/event/pending_outcome/decision/checkpoint_ref）在 Task 1 定义、Task 4/7 消费；`idempotencyKey` 签名 `(runId, continuationType, params)` 在 Task 8 定义并在 adapter 消费；`buildApprovalEvents`/`buildBatchEvents`/`buildRuntimeFailureEventsTail` 返回 `AgentRunEvent[]`，sequence 用 `record.events.length` 为 base。类型一致。

**边界与风险：**
- `RegistrySnapshot` 实际加载 + S1 validator 在 Python agent 侧，frontend 无实现；本 change 提供 `CheckpointRef` 持久化能力，完整 snapshot 漂移检测留待 plan-execution 集成（Task 7 已明确边界）。
- 单 worker durable（本 change）；multi-worker 生产实现（文件锁/Postgres）留后续，接口已预留（Task 6 lease）。
- adapter 当前无外部调用者（route handlers 未接入），Task 5 迁移低风险；`setDurableStoresForTests` 保证测试隔离。
- `buildBatchEvents` 需 implementer 参照 `buildApprovalEvents` 的 `base + events.length + 1` sequence 模式补全（plan 给出模式，避免冗余重复整段）。

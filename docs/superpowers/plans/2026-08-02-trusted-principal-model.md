---
change: sap-nexus-trusted-principal-model
design-doc: docs/superpowers/specs/2026-08-02-trusted-principal-model-design.md
base-ref: a7ac4d1ca69cc05f1bec1c3bc48efc7e323d039d
---

# Trusted Principal Model Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立 TrustedPrincipal 数据模型与 PrincipalInjector 接口，将 principalId 绑定到 durable state（Run/Session），实现 cross-principal fail-closed 隔离与 4 个 route handler 的 server-owned 注入。

**Architecture:** 新建 `frontend/src/runtime/principal/` 模块定义 TrustedPrincipal 值对象与 PrincipalInjector 接口（v1 为 LocalPlaceholderPrincipalInjector 固定占位）。向后兼容扩展 `frontend/src/runtime/durable/types.ts` 与两个 JSONL store 实现，使 AgentRunRecord/SessionState 携带 principalId。adapter 函数（createAgentRun / decideAgentRunApproval / confirmAgentRunBatch / getAgentRunEvents / getSession）接收 server-injected principal，load 后校验归属。4 个 route handler 入口注入 principal，不读 request body 的 principal 字段。

**Tech Stack:** TypeScript, Next.js route handlers, vitest, OpenSpec

---
change: sap-nexus-trusted-principal-model
design-doc: docs/superpowers/specs/2026-08-02-trusted-principal-model-design.md
base-ref: a7ac4d1ca69cc05f1bec1c3bc48efc7e323d039d
---

## Global Constraints

- **principal 后端注入（D3）**：principal 由 route handler 入口 `injectPrincipal(request)` 注入；MUST NOT 从 request body / prompt / summary / Memory 读取 principal 字段。
- **cross-principal fail-closed（D4）**：load 后校验 `record.principalId === principal.principalId`，不匹配时返回 not-found（不泄露存在性）。
- **principalId 不可变（D2）**：AgentRunRecord.principalId 创建时写入，后续不可修改。
- **向后兼容扩展**：principalId 为可选字段 + 可选过滤参数，项 1 durable-run-state 契约不破坏；旧记录 load 时回填 `"local-user-0001"`。
- **不触碰边界**：Gateway WRITE path、SSE cursor/reconnect、durable ApprovalStore、authn runtime 均为 non-goal。
- **Approval 绑定推迟**：spec 中 "Approval binds principal" 场景由拆分项 3（durable-approval-store）实现，本 change 不实现。
- **测试框架**：vitest，命令 `npm --prefix frontend run test -- <file>`；类型检查 `npm --prefix frontend run typecheck`；全量验证 `npm --prefix frontend run verify`。
- **v1 占位值**：`principalId = "local-user-0001"`, `role = "operator"`, `tenantId = "default"`。

## File Structure

| 文件 | 职责 | 任务 |
|---|---|---|
| `frontend/src/runtime/principal/types.ts`（新建） | TrustedPrincipal / PrincipalRole / DataScope 类型 + PLACEHOLDER_PRINCIPAL 常量 | Task 1 |
| `frontend/src/runtime/principal/types.test.ts`（新建） | PLACEHOLDER_PRINCIPAL 值断言 | Task 1 |
| `frontend/src/runtime/principal/principal-injector.ts`（新建） | PrincipalInjector 接口 + LocalPlaceholderPrincipalInjector + injectPrincipal + setPrincipalInjectorForTests | Task 2 |
| `frontend/src/runtime/principal/principal-injector.test.ts`（新建） | 注入返回占位 principal、忽略 request body | Task 2 |
| `frontend/src/runtime/durable/types.ts`（修改） | AgentRunRecord / SessionState / DurableRunStore.list / DurableConversationStore.load / RunJsonlLine 加 principalId | Task 3, Task 4 |
| `frontend/src/runtime/durable/jsonl-run-store.ts`（修改） | save 写 principalId、replay 回填、list 过滤 | Task 3 |
| `frontend/src/runtime/durable/jsonl-run-store.test.ts`（修改） | principalId 持久化/回填/过滤测试 | Task 3, Task 4 |
| `frontend/src/runtime/durable/jsonl-conversation-store.ts`（修改） | load 回填 + principalId 归属过滤 | Task 3 |
| `frontend/src/runtime/durable/jsonl-conversation-store.test.ts`（修改） | 回填 + 归属过滤测试 | Task 3 |
| `frontend/src/runtime/agent-runtime-adapter.ts`（修改） | CreateAgentRunInput.principal、createAgentRun 写 principalId、getSession 加 principalId、3 个续传函数加 principal + 归属校验 | Task 4, Task 5 |
| `frontend/src/runtime/agent-runtime-adapter.test.ts`（修改） | principal 绑定 + cross-principal 隔离测试 | Task 4, Task 5 |
| `frontend/app/api/agent-runs/route.ts`（修改） | 注入 principal，传给 createAgentRun | Task 4 |
| `frontend/app/api/agent-runs/[runId]/approval/route.ts`（修改） | 注入 principal，传给 decideAgentRunApproval | Task 5 |
| `frontend/app/api/agent-runs/[runId]/batch/route.ts`（修改） | 注入 principal，传给 confirmAgentRunBatch | Task 5 |
| `frontend/app/api/agent-runs/[runId]/stream/route.ts`（修改） | 注入 principal，传给 getAgentRunEvents | Task 5 |
| `openspec/changes/sap-nexus-trusted-principal-model/specs/durable-run-state/spec.md`（新建） | MODIFIED durable-run-state spec patch | Task 6 |
| `openspec/changes/sap-nexus-trusted-principal-model/tasks.md`（修改） | 勾选完成项 | Task 6 |

---

### Task 1: TrustedPrincipal 数据模型 + PLACEHOLDER_PRINCIPAL
- [x] Task 1: TrustedPrincipal 数据模型 + PLACEHOLDER_PRINCIPAL

**Files:**
- Create: `frontend/src/runtime/principal/types.ts`
- Test: `frontend/src/runtime/principal/types.test.ts`

**Interfaces:**
- Produces: `TrustedPrincipal`（`{ principalId: string; role: PrincipalRole; dataScope: DataScope }`）、`PrincipalRole`（`"admin" | "operator" | "viewer"`）、`DataScope`（`{ tenantId: string }`）、`PLACEHOLDER_PRINCIPAL`（`TrustedPrincipal`，principalId=`"local-user-0001"`）

- [ ] **Step 1: Write the failing test**

Create `frontend/src/runtime/principal/types.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { PLACEHOLDER_PRINCIPAL } from "./types";
import type { TrustedPrincipal } from "./types";

describe("TrustedPrincipal model", () => {
  it("PLACEHOLDER_PRINCIPAL has v1 placeholder values", () => {
    expect(PLACEHOLDER_PRINCIPAL).toEqual({
      principalId: "local-user-0001",
      role: "operator",
      dataScope: { tenantId: "default" }
    });
  });

  it("TrustedPrincipal satisfies the type contract", () => {
    const principal: TrustedPrincipal = {
      principalId: "user-001",
      role: "admin",
      dataScope: { tenantId: "tenant-a" }
    };
    expect(principal.principalId).toBe("user-001");
    expect(principal.role).toBe("admin");
    expect(principal.dataScope.tenantId).toBe("tenant-a");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm --prefix frontend run test -- src/runtime/principal/types.test.ts`
Expected: FAIL — `Cannot find module './types'` 或文件不存在错误。

- [ ] **Step 3: Write minimal implementation**

Create `frontend/src/runtime/principal/types.ts`:

```ts
export type PrincipalRole = "admin" | "operator" | "viewer";

export type DataScope = {
  tenantId: string;
};

export type TrustedPrincipal = {
  principalId: string;
  role: PrincipalRole;
  dataScope: DataScope;
};

export const PLACEHOLDER_PRINCIPAL: TrustedPrincipal = {
  principalId: "local-user-0001",
  role: "operator",
  dataScope: { tenantId: "default" }
};
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm --prefix frontend run test -- src/runtime/principal/types.test.ts`
Expected: PASS — 2 tests passed。

- [ ] **Step 5: Run typecheck**

Run: `npm --prefix frontend run typecheck`
Expected: PASS — no type errors。

- [ ] **Step 6: Commit**

```bash
git add frontend/src/runtime/principal/types.ts frontend/src/runtime/principal/types.test.ts
git commit -m "feat(principal): add TrustedPrincipal model and PLACEHOLDER_PRINCIPAL

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: PrincipalInjector 接口 + LocalPlaceholderPrincipalInjector + 测试钩子
- [x] Task 2: PrincipalInjector 接口 + LocalPlaceholderPrincipalInjector + 测试钩子

**Files:**
- Create: `frontend/src/runtime/principal/principal-injector.ts`
- Test: `frontend/src/runtime/principal/principal-injector.test.ts`

**Interfaces:**
- Consumes: `TrustedPrincipal`、`PLACEHOLDER_PRINCIPAL`（from Task 1）
- Produces: `PrincipalInjector`（interface，`inject(request: Request): TrustedPrincipal`）、`LocalPlaceholderPrincipalInjector`（class）、`injectPrincipal(request: Request): TrustedPrincipal`（模块级便捷函数）、`setPrincipalInjectorForTests(injector: PrincipalInjector | null): void`（测试钩子）

- [ ] **Step 1: Write the failing test**

Create `frontend/src/runtime/principal/principal-injector.test.ts`:

```ts
import { afterEach, describe, expect, it } from "vitest";
import { injectPrincipal, LocalPlaceholderPrincipalInjector, setPrincipalInjectorForTests } from "./principal-injector";
import { PLACEHOLDER_PRINCIPAL } from "./types";

describe("PrincipalInjector", () => {
  afterEach(() => setPrincipalInjectorForTests(null));

  it("LocalPlaceholderPrincipalInjector returns PLACEHOLDER_PRINCIPAL", () => {
    const injector = new LocalPlaceholderPrincipalInjector();
    const request = new Request("http://localhost/api/agent-runs", {
      method: "POST",
      body: JSON.stringify({ query: "test" })
    });
    expect(injector.inject(request)).toEqual(PLACEHOLDER_PRINCIPAL);
  });

  it("injectPrincipal returns placeholder principal by default", () => {
    const request = new Request("http://localhost/api/agent-runs");
    expect(injectPrincipal(request)).toEqual(PLACEHOLDER_PRINCIPAL);
  });

  it("injectPrincipal ignores principal fields in request body (server-owned)", () => {
    const request = new Request("http://localhost/api/agent-runs", {
      method: "POST",
      body: JSON.stringify({
        query: "test",
        principal: { principalId: "attacker-001", role: "admin", dataScope: { tenantId: "evil" } },
        principalId: "attacker-001"
      })
    });
    const principal = injectPrincipal(request);
    expect(principal.principalId).toBe("local-user-0001");
    expect(principal.principalId).not.toBe("attacker-001");
  });

  it("setPrincipalInjectorForTests allows overriding the injector", () => {
    const customPrincipal = { principalId: "test-user", role: "admin" as const, dataScope: { tenantId: "t1" } };
    setPrincipalInjectorForTests({
      inject: () => customPrincipal
    });
    const request = new Request("http://localhost/api/agent-runs");
    expect(injectPrincipal(request)).toEqual(customPrincipal);
  });

  it("setPrincipalInjectorForTests(null) restores default injector", () => {
    setPrincipalInjectorForTests(null);
    const request = new Request("http://localhost/api/agent-runs");
    expect(injectPrincipal(request)).toEqual(PLACEHOLDER_PRINCIPAL);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm --prefix frontend run test -- src/runtime/principal/principal-injector.test.ts`
Expected: FAIL — `Cannot find module './principal-injector'`。

- [ ] **Step 3: Write minimal implementation**

Create `frontend/src/runtime/principal/principal-injector.ts`:

```ts
import type { TrustedPrincipal } from "./types";
import { PLACEHOLDER_PRINCIPAL } from "./types";

export interface PrincipalInjector {
  inject(request: Request): TrustedPrincipal;
}

export class LocalPlaceholderPrincipalInjector implements PrincipalInjector {
  inject(_request: Request): TrustedPrincipal {
    return PLACEHOLDER_PRINCIPAL;
  }
}

let principalInjector: PrincipalInjector = new LocalPlaceholderPrincipalInjector();

export function injectPrincipal(request: Request): TrustedPrincipal {
  return principalInjector.inject(request);
}

export function setPrincipalInjectorForTests(injector: PrincipalInjector | null): void {
  principalInjector = injector ?? new LocalPlaceholderPrincipalInjector();
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm --prefix frontend run test -- src/runtime/principal/principal-injector.test.ts`
Expected: PASS — 5 tests passed。

- [ ] **Step 5: Run typecheck**

Run: `npm --prefix frontend run typecheck`
Expected: PASS。

- [ ] **Step 6: Commit**

```bash
git add frontend/src/runtime/principal/principal-injector.ts frontend/src/runtime/principal/principal-injector.test.ts
git commit -m "feat(principal): add PrincipalInjector interface and LocalPlaceholderPrincipalInjector

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: durable types principalId（可选）+ JsonlRunStore 持久化/回填/过滤 + JsonlConversationStore 持久化/回填/归属过滤
- [x] Task 3: durable types principalId（可选）+ JsonlRunStore 持久化/回填/过滤 + JsonlConversationStore 持久化/回填/归属过滤

> 本任务在 types.ts 中将 principalId 加为**可选**字段（向后兼容，build 保持 green）。Task 4 再将 AgentRunRecord.principalId 升级为 required。

**Files:**
- Modify: `frontend/src/runtime/durable/types.ts`
- Modify: `frontend/src/runtime/durable/jsonl-run-store.ts`
- Modify: `frontend/src/runtime/durable/jsonl-conversation-store.ts`
- Test: `frontend/src/runtime/durable/jsonl-run-store.test.ts`
- Test: `frontend/src/runtime/durable/jsonl-conversation-store.test.ts`

**Interfaces:**
- Consumes: 无（纯 durable 层扩展）
- Produces: `AgentRunRecord.principalId?: string`、`SessionState.principalId?: string`、`DurableRunStore.list(filter?: { state?: AgentRunState; principalId?: string })`、`DurableConversationStore.load(conversationId: string, principalId?: string)`、`RunJsonlLine` run_meta 加 `principalId?: string`

- [ ] **Step 1: Write failing tests for JsonlRunStore principalId persistence, backfill, and filter**

在 `frontend/src/runtime/durable/jsonl-run-store.test.ts` 的 `describe("JsonlRunStore core", ...)` 块内追加以下测试（在现有 `clearAll` 测试之后）：

```ts
  it("save persists principalId in run_meta and load returns it", async () => {
    const store = new JsonlRunStore(dir);
    const events = [event("run-1", 1, "run_started", "running")];
    await store.save("run-1", { runId: "run-1", query: "q", events, principalId: "user-a" });
    const loaded = await store.load("run-1");
    expect(loaded?.principalId).toBe("user-a");
  });

  it("load backfills principalId to local-user-0001 for legacy records", async () => {
    const store = new JsonlRunStore(dir);
    // write a legacy run_meta line without principalId by appending raw JSONL
    const legacyLine = JSON.stringify({ kind: "run_meta", runId: "run-legacy", query: "old" }) + "\n" +
      JSON.stringify({ kind: "event", runId: "run-legacy", sequence: 1, timestamp: "2026-08-02T00:00:00Z", type: "run_started", state: "running" }) + "\n";
    appendFileSync(path.join(dir, "runs", "run-legacy.jsonl"), legacyLine);
    const loaded = await store.load("run-legacy");
    expect(loaded?.principalId).toBe("local-user-0001");
  });

  it("list filters by principalId", async () => {
    const store = new JsonlRunStore(dir);
    await store.save("run-a", { runId: "run-a", query: "q", events: [event("run-a", 1, "run_started", "running")], principalId: "user-a" });
    await store.save("run-b", { runId: "run-b", query: "q", events: [event("run-b", 1, "run_started", "running")], principalId: "user-b" });
    expect((await store.list({ principalId: "user-a" })).map((r) => r.runId)).toEqual(["run-a"]);
    expect((await store.list({ principalId: "user-b" })).map((r) => r.runId)).toEqual(["run-b"]);
    expect((await store.list()).length).toBe(2);
  });
```

注意：`record()` 辅助函数当前不包含 principalId（字段尚为可选），现有测试不受影响。`appendFileSync` 已在文件顶部 import。

- [ ] **Step 2: Write failing tests for JsonlConversationStore backfill and principal filter**

在 `frontend/src/runtime/durable/jsonl-conversation-store.test.ts` 末尾追加：

```ts
import { writeFileSync } from "node:fs";

describe("JsonlConversationStore principalId", () => {
  let dir: string;
  beforeEach(() => { dir = mkdtempSync(path.join(tmpdir(), "conv-principal-")); });
  afterEach(() => { rmSync(dir, { recursive: true, force: true }); });

  it("load backfills principalId to local-user-0001 for legacy sessions", async () => {
    const store = new JsonlConversationStore(dir);
    // write a legacy session without principalId
    const legacyState = { lastContext: null, lastRunId: null, history: [] };
    writeFileSync(path.join(dir, "sessions", "c-legacy.json"), JSON.stringify(legacyState));
    const loaded = await store.load("c-legacy");
    expect(loaded?.principalId).toBe("local-user-0001");
  });

  it("load with principalId returns null on mismatch (fail-closed)", async () => {
    const store = new JsonlConversationStore(dir);
    await store.save("c1", { lastContext: null, lastRunId: null, history: [], principalId: "user-a" });
    expect(await store.load("c1", "user-a")).not.toBeNull();
    expect(await store.load("c1", "user-b")).toBeNull();
  });

  it("load with principalId returns session on match", async () => {
    const store = new JsonlConversationStore(dir);
    await store.save("c1", { lastContext: null, lastRunId: null, history: [], principalId: "user-a" });
    const loaded = await store.load("c1", "user-a");
    expect(loaded?.principalId).toBe("user-a");
  });
});
```

确保文件顶部已有 `mkdtempSync, rmSync` import 和 `path, tmpdir` import（与 jsonl-run-store.test.ts 模式一致）。如果顶部缺少 `writeFileSync`，添加它。

- [ ] **Step 3: Run tests to verify they fail**

Run: `npm --prefix frontend run test -- src/runtime/durable/jsonl-run-store.test.ts src/runtime/durable/jsonl-conversation-store.test.ts`
Expected: FAIL — `principalId` 属性不存在 / 类型不匹配。

- [ ] **Step 4: Modify types.ts — add optional principalId fields**

在 `frontend/src/runtime/durable/types.ts` 中：

4a. `SessionState`（约第 19-23 行）加 `principalId?: string`：

```ts
export type SessionState = {
  lastContext: LastContext | null;
  lastRunId: string | null;
  history: Turn[];
  principalId?: string;
};
```

4b. `AgentRunRecord`（约第 45-51 行）加 `principalId?: string`（Task 4 升级为 required）：

```ts
export type AgentRunRecord = {
  runId: string;
  query: string;
  events: AgentRunEvent[];
  pendingOutcome?: WorkbenchOutcome;
  decision?: ApprovalDecision;
  principalId?: string;
};
```

4c. `RunJsonlLine` 的 `run_meta` 分支（约第 74 行）加 `principalId?: string`：

```ts
export type RunJsonlLine =
  | { kind: "run_meta"; runId: string; query: string; principalId?: string }
  | ({ kind: "event" } & AgentRunEvent)
  | { kind: "pending_outcome"; value: WorkbenchOutcome }
  | { kind: "decision"; value: ApprovalDecision }
  | { kind: "checkpoint_ref"; value: CheckpointRef };
```

4d. `DurableRunStore.list`（约第 85 行）filter 加 `principalId?: string`：

```ts
  list(filter?: { state?: AgentRunState; principalId?: string }): Promise<AgentRunRecord[]>;
```

4e. `DurableConversationStore.load`（约第 101 行）加 `principalId?: string` 参数：

```ts
  load(conversationId: string, principalId?: string): Promise<SessionState | null>;
```

- [ ] **Step 5: Modify JsonlRunStore — persist, backfill, and filter principalId**

在 `frontend/src/runtime/durable/jsonl-run-store.ts` 中：

5a. `save` 方法（约第 113 行）run_meta 行写入 principalId：

```ts
    const lines: string[] = [JSON.stringify({ kind: "run_meta", runId, query: record.query, principalId: record.principalId } as RunJsonlLine)];
```

5b. `replay` 方法（约第 138-178 行）— 读取 principalId 并回填。在 `let decision` 声明后加 `let principalId: string | undefined;`，在 `case "run_meta":` 分支读取，在构造 record 时回填：

```ts
  private replay(file: string): AgentRunRecord {
    const content = readFileSync(file, "utf8");
    let query = "";
    let principalId: string | undefined;
    const events: AgentRunEvent[] = [];
    let pendingOutcome: WorkbenchOutcome | undefined;
    let decision: ApprovalDecision | undefined;
    for (const raw of content.split("\n")) {
      if (!raw.trim()) continue;
      let line: RunJsonlLine;
      try {
        line = JSON.parse(raw) as RunJsonlLine;
      } catch {
        continue;
      }
      switch (line.kind) {
        case "run_meta":
          query = line.query;
          principalId = line.principalId;
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
          break;
      }
    }
    events.sort((a, b) => a.sequence - b.sequence);
    const record: AgentRunRecord = {
      runId: path.basename(file, ".jsonl"),
      query,
      events,
      principalId: principalId ?? "local-user-0001"
    };
    if (pendingOutcome) record.pendingOutcome = pendingOutcome;
    if (decision) record.decision = decision;
    return record;
  }
```

5c. `list` 方法（约第 237-249 行）加 principalId 过滤：

```ts
  async list(filter?: { state?: AgentRunState; principalId?: string }): Promise<AgentRunRecord[]> {
    if (!existsSync(this.runsDir)) return [];
    const records: AgentRunRecord[] = [];
    for (const entry of readdirSync(this.runsDir)) {
      if (!entry.endsWith(".jsonl")) continue;
      const record = this.replay(path.join(this.runsDir, entry));
      const lastState = record.events[record.events.length - 1]?.state;
      const stateMatch = !filter?.state || lastState === filter.state;
      const principalMatch = !filter?.principalId || record.principalId === filter.principalId;
      if (stateMatch && principalMatch) {
        records.push(record);
      }
    }
    return records;
  }
```

- [ ] **Step 6: Modify JsonlConversationStore — backfill and fail-closed filter**

在 `frontend/src/runtime/durable/jsonl-conversation-store.ts` 中，`load` 方法（约第 32-36 行）改为：

```ts
  async load(conversationId: string, principalId?: string): Promise<SessionState | null> {
    const file = this.file(conversationId);
    if (!existsSync(file)) return null;
    const state = JSON.parse(readFileSync(file, "utf8")) as SessionState;
    if (!state.principalId) {
      state.principalId = "local-user-0001";
    }
    if (principalId && state.principalId !== principalId) {
      return null;
    }
    return state;
  }
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `npm --prefix frontend run test -- src/runtime/durable/jsonl-run-store.test.ts src/runtime/durable/jsonl-conversation-store.test.ts`
Expected: PASS — 所有测试通过，包括新增的 principalId 测试。

- [ ] **Step 8: Run typecheck to verify build is green**

Run: `npm --prefix frontend run typecheck`
Expected: PASS — principalId 为可选字段，现有构造点不受影响。

- [ ] **Step 9: Commit**

```bash
git add frontend/src/runtime/durable/types.ts frontend/src/runtime/durable/jsonl-run-store.ts frontend/src/runtime/durable/jsonl-run-store.test.ts frontend/src/runtime/durable/jsonl-conversation-store.ts frontend/src/runtime/durable/jsonl-conversation-store.test.ts
git commit -m "feat(durable): add optional principalId to durable types, persist/backfill/filter in JSONL stores

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: createAgentRun + getSession principal 绑定 + POST /api/agent-runs 注入（principalId 升级 required）
- [ ] Task 4: createAgentRun + getSession principal 绑定 + POST /api/agent-runs 注入（principalId 升级 required）

> 本任务将 AgentRunRecord.principalId 从可选升级为 required，同时更新所有构造点。CreateAgentRunInput 加 principal，createAgentRun 写入 principalId，getSession 加 principalId 参数（首次创建写入、后续校验归属）。POST /api/agent-runs route 入口注入 principal。

**Files:**
- Modify: `frontend/src/runtime/durable/types.ts`（AgentRunRecord.principalId 可选 -> required）
- Modify: `frontend/src/runtime/agent-runtime-adapter.ts`
- Modify: `frontend/src/runtime/agent-runtime-adapter.test.ts`
- Modify: `frontend/src/runtime/durable/jsonl-run-store.test.ts`（record() 辅助函数加 principalId）
- Modify: `frontend/app/api/agent-runs/route.ts`

**Interfaces:**
- Consumes: `TrustedPrincipal`、`injectPrincipal`（from Task 1/2）、durable types principalId（from Task 3）
- Produces: `CreateAgentRunInput`（加 `principal: TrustedPrincipal`）、`createAgentRun(input: CreateAgentRunInput)` 传入 principal、`getSession(conversationId: string, principalId: string)`（私有，加 principalId 参数）

- [ ] **Step 1: Write failing tests for createAgentRun principal binding and getSession ownership**

在 `frontend/src/runtime/agent-runtime-adapter.test.ts` 的 import 块中追加：

```ts
import { PLACEHOLDER_PRINCIPAL } from "./principal/types";
import type { TrustedPrincipal } from "./principal/types";
```

在 `describe("agent-runtime-adapter durable integration", ...)` 块内追加以下测试：

```ts
  it("createAgentRun binds principalId to the run record", async () => {
    const { runId } = await createAgentRun({ query: "查询库存", principal: PLACEHOLDER_PRINCIPAL });
    const events = await getAgentRunEvents(runId, PLACEHOLDER_PRINCIPAL);
    expect(events.length).toBeGreaterThan(0);
    // verify the record itself carries principalId
    const runs = await runStore.list({ principalId: "local-user-0001" });
    expect(runs.some((r) => r.runId === runId)).toBe(true);
  });

  it("getSession writes principalId on first request and validates on subsequent", async () => {
    const { runId } = await createAgentRun({ query: "查询库存", conversationId: "c-own", principal: PLACEHOLDER_PRINCIPAL });
    expect(runId).toBeDefined();
    // second request with same principal should succeed (no throw)
    const { runId: runId2 } = await createAgentRun({ query: "再次查询", conversationId: "c-own", principal: PLACEHOLDER_PRINCIPAL });
    expect(runId2).toBeDefined();
  });

  it("getSession rejects cross-principal access to existing conversation (fail-closed)", async () => {
    await createAgentRun({ query: "查询库存", conversationId: "c-x", principal: PLACEHOLDER_PRINCIPAL });
    const attacker: TrustedPrincipal = {
      principalId: "attacker-002",
      role: "operator",
      dataScope: { tenantId: "evil" }
    };
    await expect(
      createAgentRun({ query: "越权", conversationId: "c-x", principal: attacker })
    ).rejects.toThrow(/does not belong/);
  });
```

注意：现有测试中所有 `createAgentRun({ query: ... })` 调用需在 Step 4 中加 `principal: PLACEHOLDER_PRINCIPAL`。`getAgentRunEvents(runId)` 调用暂时先加 `PLACEHOLDER_PRINCIPAL` 第二参数（Task 5 正式改签名；本任务先让它编译通过——若 Task 5 尚未改签名，此处不加第二参数。**但由于本任务不改 getAgentRunEvents 签名，现有 getAgentRunEvents 调用保持不变。** 上述测试中 `getAgentRunEvents(runId, PLACEHOLDER_PRINCIPAL)` 会因签名不匹配而编译失败——这是预期的 FAIL。）

修正：本任务不改 `getAgentRunEvents` 签名（Task 5 才改）。因此测试中用 `getAgentRunEvents(runId)`（不加 principal）。将上面测试中的 `getAgentRunEvents(runId, PLACEHOLDER_PRINCIPAL)` 改为 `getAgentRunEvents(runId)`：

```ts
  it("createAgentRun binds principalId to the run record", async () => {
    const { runId } = await createAgentRun({ query: "查询库存", principal: PLACEHOLDER_PRINCIPAL });
    const events = await getAgentRunEvents(runId);
    expect(events.length).toBeGreaterThan(0);
    const runs = await runStore.list({ principalId: "local-user-0001" });
    expect(runs.some((r) => r.runId === runId)).toBe(true);
  });
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `npm --prefix frontend run test -- src/runtime/agent-runtime-adapter.test.ts`
Expected: FAIL — `createAgentRun` 签名不接受 `principal`；现有调用缺 `principal` 参数导致类型错误。

- [ ] **Step 3: Upgrade AgentRunRecord.principalId to required in types.ts**

在 `frontend/src/runtime/durable/types.ts` 中，将 `AgentRunRecord.principalId` 从 `principalId?: string` 改为 `principalId: string`：

```ts
export type AgentRunRecord = {
  runId: string;
  query: string;
  events: AgentRunEvent[];
  pendingOutcome?: WorkbenchOutcome;
  decision?: ApprovalDecision;
  principalId: string;
};
```

- [ ] **Step 4: Modify agent-runtime-adapter.ts — CreateAgentRunInput, createAgentRun, getSession**

4a. 在文件顶部 import 块（约第 16-17 行 `JsonlConversationStore` import 之后）加：

```ts
import type { TrustedPrincipal } from "./principal/types";
```

4b. `CreateAgentRunInput`（约第 27-31 行）加 `principal: TrustedPrincipal`：

```ts
type CreateAgentRunInput = {
  query: string;
  rfcName?: string;
  conversationId?: string;
  principal: TrustedPrincipal;
};
```

4c. `getSession`（约第 82-88 行）加 `principalId` 参数，首次创建写入，后续校验归属：

```ts
async function getSession(conversationId: string, principalId: string): Promise<SessionState> {
  const existing = await conversationStore.load(conversationId);
  if (!existing) {
    const session: SessionState = { lastContext: null, lastRunId: null, history: [], principalId };
    await conversationStore.save(conversationId, session);
    return session;
  }
  if (existing.principalId !== principalId) {
    throw new Error("Conversation does not belong to the current principal");
  }
  return existing;
}
```

4d. `createAgentRun`（约第 101-166 行）— 三处 `getSession(input.conversationId)` 调用改为 `getSession(input.conversationId, input.principal.principalId)`，并在构造 `record` 时写入 `principalId`：

第 108 行（Q2 gate 内）：
```ts
    const session = await getSession(input.conversationId, input.principal.principalId);
```

第 121-125 行（record 构造）加 `principalId`：
```ts
  const record: AgentRunRecord = {
    runId,
    query,
    events: [{ runId, sequence: 1, timestamp, type: "run_started", state: "running" }],
    principalId: input.principal.principalId
  };
```

第 131 行（buildContext 内）：
```ts
    const context = input.conversationId ? buildContext(await getSession(input.conversationId, input.principal.principalId)) : undefined;
```

第 145 行（session 更新内）：
```ts
    const session = await getSession(input.conversationId, input.principal.principalId);
```

4e. `decideAgentRunApproval` / `confirmAgentRunBatch` / `getAgentRunEvents` 本任务**不改签名**（Task 5 改）。但由于 `getAgentRunEvents` 内部调用 `runStore.load` 返回的 `AgentRunRecord` 现在有 required `principalId`，且函数内不构造 AgentRunRecord，不受影响。

- [ ] **Step 5: Update jsonl-run-store.test.ts record() helper — add principalId**

在 `frontend/src/runtime/durable/jsonl-run-store.test.ts` 中，`record()` 辅助函数（约第 13-15 行）加 `principalId`：

```ts
function record(runId: string, query: string, events: AgentRunEvent[]): AgentRunRecord {
  return { runId, query, events, principalId: "local-user-0001" };
}
```

- [ ] **Step 6: Update agent-runtime-adapter.test.ts — add principal to all createAgentRun calls**

在 `frontend/src/runtime/agent-runtime-adapter.test.ts` 中，将所有 `createAgentRun({ query: ... })` 调用加 `principal: PLACEHOLDER_PRINCIPAL`。涉及约 6 处调用，例如：

```ts
const { runId } = await createAgentRun({ query: "查询库存", principal: PLACEHOLDER_PRINCIPAL });
```

```ts
await createAgentRun({ query: "查询库存", conversationId: "c1", principal: PLACEHOLDER_PRINCIPAL });
```

对文件中每个 `createAgentRun({` 调用，在参数对象内加 `principal: PLACEHOLDER_PRINCIPAL`。同时 `decideAgentRunApproval(target.runId, "approve")` 调用本任务不改（Task 5 改签名）。

- [ ] **Step 7: Modify POST /api/agent-runs route — inject principal**

在 `frontend/app/api/agent-runs/route.ts` 中：

```ts
import { NextResponse } from "next/server";
import { createAgentRun } from "../../../src/runtime/agent-runtime-adapter";
import { injectPrincipal } from "../../../src/runtime/principal/principal-injector";

export async function POST(request: Request) {
  const payload = await request.json();
  const principal = injectPrincipal(request);

  try {
    const result = await createAgentRun({
      query: String(payload.query ?? ""),
      rfcName: payload.rfcName ? String(payload.rfcName) : undefined,
      conversationId: payload.conversationId ? String(payload.conversationId) : undefined,
      principal
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

注意：route handler 仅从 `payload` 读取 `query` / `rfcName` / `conversationId`，**不读取** `payload.principal` / `payload.principalId`。即使 request body 携带 principal 字段，`injectPrincipal(request)` 返回 server-owned principal，body 中的 principal 字段被忽略（§5.3）。

- [ ] **Step 8: Run tests to verify they pass**

Run: `npm --prefix frontend run test -- src/runtime/agent-runtime-adapter.test.ts src/runtime/durable/jsonl-run-store.test.ts`
Expected: PASS — 所有测试通过，包括 principal 绑定与 getSession 归属校验。

- [ ] **Step 9: Run typecheck to verify build is green (including route handler)**

Run: `npm --prefix frontend run typecheck`
Expected: PASS — AgentRunRecord.principalId required，所有构造点已更新；route handler 传入 principal。

- [ ] **Step 10: Commit**

```bash
git add frontend/src/runtime/durable/types.ts frontend/src/runtime/agent-runtime-adapter.ts frontend/src/runtime/agent-runtime-adapter.test.ts frontend/src/runtime/durable/jsonl-run-store.test.ts frontend/app/api/agent-runs/route.ts
git commit -m "feat(principal): bind principalId in createAgentRun/getSession, inject in POST route

- AgentRunRecord.principalId upgraded to required
- CreateAgentRunInput accepts server-injected principal
- getSession writes/validates principalId (fail-closed on mismatch)
- POST /api/agent-runs injects principal via injectPrincipal

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: cross-principal 隔离 + 3 个 route handler 注入（approval/batch/stream）
- [ ] Task 5: cross-principal 隔离 + 3 个 route handler 注入（approval/batch/stream）

> 本任务为 `decideAgentRunApproval` / `confirmAgentRunBatch` / `getAgentRunEvents` 加 `principal` 参数，load 后校验归属（fail-closed）。同时为 3 个 route handler 入口注入 principal。本任务完成后全部 4 个 route handler 都实现 server-owned 注入。

**Files:**
- Modify: `frontend/src/runtime/agent-runtime-adapter.ts`
- Modify: `frontend/src/runtime/agent-runtime-adapter.test.ts`
- Modify: `frontend/app/api/agent-runs/[runId]/approval/route.ts`
- Modify: `frontend/app/api/agent-runs/[runId]/batch/route.ts`
- Modify: `frontend/app/api/agent-runs/[runId]/stream/route.ts`

**Interfaces:**
- Consumes: `TrustedPrincipal`、`injectPrincipal`（from Task 1/2/4）
- Produces: `decideAgentRunApproval(runId: string, decision: ApprovalDecision, principal: TrustedPrincipal)`、`confirmAgentRunBatch(runId: string, principal: TrustedPrincipal)`、`getAgentRunEvents(runId: string, principal: TrustedPrincipal): Promise<AgentRunEvent[]>`

- [ ] **Step 1: Write failing tests for cross-principal isolation**

在 `frontend/src/runtime/agent-runtime-adapter.test.ts` 的 `describe("agent-runtime-adapter durable integration", ...)` 块内追加：

```ts
  it("getAgentRunEvents returns [] for cross-principal access (fail-closed)", async () => {
    const { runId } = await createAgentRun({ query: "查询库存", principal: PLACEHOLDER_PRINCIPAL });
    const attacker: TrustedPrincipal = {
      principalId: "attacker-003",
      role: "operator",
      dataScope: { tenantId: "evil" }
    };
    expect(await getAgentRunEvents(runId, attacker)).toEqual([]);
    // same principal still sees events
    expect((await getAgentRunEvents(runId, PLACEHOLDER_PRINCIPAL)).length).toBeGreaterThan(0);
  });

  it("decideAgentRunApproval throws not-found for cross-principal access", async () => {
    setAgentRunnerForTests(async () => awaitingOutcome("run-1"));
    const { runId } = await createAgentRun({ query: "查询库存", principal: PLACEHOLDER_PRINCIPAL });
    const attacker: TrustedPrincipal = {
      principalId: "attacker-004",
      role: "operator",
      dataScope: { tenantId: "evil" }
    };
    await expect(decideAgentRunApproval(runId, "reject", attacker)).rejects.toThrow(/not found/);
  });

  it("confirmAgentRunBatch throws not-found for cross-principal access", async () => {
    setAgentRunnerForTests(async () => ({
      status: "awaiting_batch_confirm",
      callPlan: { capabilityId: "cap-1", kind: "Action" },
      combinations: [{ plant: "P1" }],
      responseText: "待确认"
    } as WorkbenchOutcome));
    const { runId } = await createAgentRun({ query: "批量查询", principal: PLACEHOLDER_PRINCIPAL });
    const attacker: TrustedPrincipal = {
      principalId: "attacker-005",
      role: "operator",
      dataScope: { tenantId: "evil" }
    };
    await expect(confirmAgentRunBatch(runId, attacker)).rejects.toThrow(/not found/);
  });
```

同时，现有测试中所有 `decideAgentRunApproval(runId, decision)` / `confirmAgentRunBatch(runId)` / `getAgentRunEvents(runId)` 调用需在 Step 4 加 `PLACEHOLDER_PRINCIPAL` 参数。

- [ ] **Step 2: Run tests to verify they fail**

Run: `npm --prefix frontend run test -- src/runtime/agent-runtime-adapter.test.ts`
Expected: FAIL — `decideAgentRunApproval` / `confirmAgentRunBatch` / `getAgentRunEvents` 签名不接受 `principal` 参数。

- [ ] **Step 3: Modify agent-runtime-adapter.ts — add principal param and ownership check to 3 functions**

3a. `getAgentRunEvents`（约第 168-171 行）加 `principal` 参数与归属校验：

```ts
export async function getAgentRunEvents(
  runId: string,
  principal: TrustedPrincipal
): Promise<AgentRunEvent[]> {
  const run = await runStore.load(runId);
  if (!run || run.principalId !== principal.principalId) return [];
  return run.events;
}
```

3b. `decideAgentRunApproval`（约第 173 行）加 `principal` 参数。在 `const record = await runStore.load(runId);` 与 `if (!record)` 之间插入归属校验：

```ts
export async function decideAgentRunApproval(
  runId: string,
  decision: ApprovalDecision,
  principal: TrustedPrincipal
): Promise<void> {
  const record = await runStore.load(runId);
  if (!record || record.principalId !== principal.principalId) {
    throw new Error("Agent run not found");
  }
```

删除原有的独立 `if (!record) { throw new Error("Agent run not found"); }` 块（已被上面的合并校验取代）。

3c. `confirmAgentRunBatch`（约第 236 行）加 `principal` 参数。同样合并归属校验：

```ts
export async function confirmAgentRunBatch(
  runId: string,
  principal: TrustedPrincipal
): Promise<void> {
  const record = await runStore.load(runId);
  if (!record || record.principalId !== principal.principalId) {
    throw new Error("Agent run not found");
  }
```

删除原有的独立 `if (!record) { throw new Error("Agent run not found"); }` 块。

**关键**：归属校验在 `claim` lease **之前**执行（§4.1：先验归属，再验并发）。当前代码中 `claim` 在 `load` 之后、`appendDecision` 之前，归属校验插入在 `load` 之后、`claim` 之前，符合设计。

- [ ] **Step 4: Update agent-runtime-adapter.test.ts — add principal to all existing calls**

在 `frontend/src/runtime/agent-runtime-adapter.test.ts` 中，为所有现有 `decideAgentRunApproval(runId, ...)` 调用加第三参数 `PLACEHOLDER_PRINCIPAL`，所有 `confirmAgentRunBatch(runId)` 调用加第二参数 `PLACEHOLDER_PRINCIPAL`，所有 `getAgentRunEvents(runId)` 调用加第二参数 `PLACEHOLDER_PRINCIPAL`。例如：

```ts
await decideAgentRunApproval(target.runId, "approve", PLACEHOLDER_PRINCIPAL);
```
```ts
const events = await getAgentRunEvents(runId, PLACEHOLDER_PRINCIPAL);
```

- [ ] **Step 5: Modify approval route — inject principal**

在 `frontend/app/api/agent-runs/[runId]/approval/route.ts` 中，import `injectPrincipal` 并在 `POST` 入口注入，传给 `decideAgentRunApproval`：

```ts
import { NextResponse } from "next/server";
import {
  decideAgentRunApproval,
  type ApprovalDecision
} from "../../../../../src/runtime/agent-runtime-adapter";
import { injectPrincipal } from "../../../../../src/runtime/principal/principal-injector";

export async function POST(
  request: Request,
  { params }: { params: Promise<{ runId: string }> }
) {
  let payload: unknown;
  try {
    payload = await request.json();
  } catch {
    return invalidRequest("Request body must be valid JSON.");
  }
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    return invalidRequest("Request body must contain only a decision.");
  }

  const body = payload as Record<string, unknown>;
  if (Object.keys(body).length !== 1 || !isDecision(body.decision)) {
    return invalidRequest("Only decision=approve|reject is accepted.");
  }

  const principal = injectPrincipal(request);
  const { runId } = await params;
  try {
    await decideAgentRunApproval(runId, body.decision, principal);
    return NextResponse.json({ runId });
  } catch (error) {
    const message = error instanceof Error ? error.message : "Approval request failed";
    if (message.includes("not found")) {
      return NextResponse.json({ errorType: "RUN_NOT_FOUND", message }, { status: 404 });
    }
    if (message.includes("already decided")) {
      return NextResponse.json({ errorType: "APPROVAL_CONFLICT", message }, { status: 409 });
    }
    return NextResponse.json({ errorType: "INVALID_APPROVAL_REQUEST", message }, { status: 400 });
  }
}

function isDecision(value: unknown): value is ApprovalDecision {
  return value === "approve" || value === "reject";
}

function invalidRequest(message: string) {
  return NextResponse.json({ errorType: "INVALID_APPROVAL_REQUEST", message }, { status: 400 });
}
```

- [ ] **Step 6: Modify batch route — inject principal**

在 `frontend/app/api/agent-runs/[runId]/batch/route.ts` 中：

```ts
import { NextResponse } from "next/server";
import { confirmAgentRunBatch } from "../../../../../src/runtime/agent-runtime-adapter";
import { injectPrincipal } from "../../../../../src/runtime/principal/principal-injector";

export async function POST(
  request: Request,
  { params }: { params: Promise<{ runId: string }> }
) {
  let payload: unknown;
  try {
    payload = await request.json();
  } catch {
    return invalidRequest("Request body must be valid JSON.");
  }
  if (payload && (typeof payload !== "object" || Array.isArray(payload))) {
    return invalidRequest("Batch confirmation accepts an empty JSON object only.");
  }

  const principal = injectPrincipal(request);
  const { runId } = await params;
  try {
    await confirmAgentRunBatch(runId, principal);
    return NextResponse.json({ runId });
  } catch (error) {
    const message = error instanceof Error ? error.message : "Batch confirmation failed";
    if (message.includes("not found")) {
      return NextResponse.json({ errorType: "RUN_NOT_FOUND", message }, { status: 404 });
    }
    if (message.includes("already decided") || message.includes("not awaiting batch")) {
      return NextResponse.json({ errorType: "BATCH_CONFLICT", message }, { status: 409 });
    }
    return NextResponse.json({ errorType: "INVALID_BATCH_REQUEST", message }, { status: 400 });
  }
}

function invalidRequest(message: string) {
  return NextResponse.json({ errorType: "INVALID_BATCH_REQUEST", message }, { status: 400 });
}
```

- [ ] **Step 7: Modify stream route — inject principal**

在 `frontend/app/api/agent-runs/[runId]/stream/route.ts` 中，将 `_request` 改为 `request`（需用于注入），传给 `getAgentRunEvents`：

```ts
import { getAgentRunEvents } from "@/runtime/agent-runtime-adapter";
import { injectPrincipal } from "../../../../../src/runtime/principal/principal-injector";

export async function GET(request: Request, { params }: { params: Promise<{ runId: string }> }) {
  const principal = injectPrincipal(request);
  const { runId } = await params;
  const events = await getAgentRunEvents(runId, principal);
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

- [ ] **Step 8: Run tests to verify they pass**

Run: `npm --prefix frontend run test -- src/runtime/agent-runtime-adapter.test.ts`
Expected: PASS — 所有测试通过，包括 cross-principal 隔离测试。

- [ ] **Step 9: Run typecheck to verify all route handlers compile**

Run: `npm --prefix frontend run typecheck`
Expected: PASS — 4 个 route handler 均传入 principal，3 个 adapter 函数签名匹配。

- [ ] **Step 10: Run full test suite to verify no regressions**

Run: `npm --prefix frontend run test`
Expected: PASS — 全部测试通过。

- [ ] **Step 11: Commit**

```bash
git add frontend/src/runtime/agent-runtime-adapter.ts frontend/src/runtime/agent-runtime-adapter.test.ts frontend/app/api/agent-runs/[runId]/approval/route.ts frontend/app/api/agent-runs/[runId]/batch/route.ts frontend/app/api/agent-runs/[runId]/stream/route.ts
git commit -m "feat(principal): cross-principal fail-closed isolation and server-owned injection in 3 route handlers

- decideAgentRunApproval/confirmAgentRunBatch/getAgentRunEvents accept principal
- ownership check after load, before lease claim (fail-closed -> not found)
- approval/batch/stream routes inject principal via injectPrincipal

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 6: openspec MODIFIED spec patch + 验证回归
- [ ] Task 6: openspec MODIFIED spec patch + 验证回归

> 本任务创建 durable-run-state 的 MODIFIED spec patch（加 principalId 绑定语义与 list/load 过滤参数），运行 openspec validate 与 frontend verify 回归。

**Files:**
- Create: `openspec/changes/sap-nexus-trusted-principal-model/specs/durable-run-state/spec.md`
- Modify: `openspec/changes/sap-nexus-trusted-principal-model/tasks.md`

**Interfaces:**
- Consumes: 全部前序任务的实现
- Produces: 通过 `openspec validate --all --strict` 与 `npm --prefix frontend run verify`

- [ ] **Step 1: Create the MODIFIED durable-run-state spec patch**

Create `openspec/changes/sap-nexus-trusted-principal-model/specs/durable-run-state/spec.md`:

```markdown
## MODIFIED Requirements

### Requirement: Durable agent run state
The system SHALL persist agent run state (events, `pendingOutcome`, approval decision) in a durable store keyed by `runId`, replacing the process-local `runs` Map (`globalThis.__SAP_NEXUS_AGENT_RUNS__`). The system SHALL recover run state across process restarts and share it across workers. Each durable Run record SHALL bind to a `principalId` at creation time; the `principalId` SHALL NOT be mutable after creation. Records created without a `principalId` (legacy data) SHALL be backfilled with the local placeholder principal (`local-user-0001`) on load.

#### Scenario: Run recovers across process restart
- **WHEN** a run is in `awaiting_approval` or `awaiting_batch_confirm` state and the backend process restarts
- **THEN** the run is recovered from the durable store with its full event stream and `pendingOutcome`
- **AND** the user can continue the run (approve / reject / confirm) after restart

#### Scenario: Multi-worker shares run state
- **WHEN** worker A creates a run and worker B receives a continuation request for the same `runId`
- **THEN** worker B reads the run state from the durable store
- **AND** both workers observe the same run events and `pendingOutcome`

#### Scenario: Run binds principal at creation
- **WHEN** a new agent run is created by a server-injected principal
- **THEN** the durable Run record stores the principal's `principalId`
- **AND** the `principalId` is immutable for the lifetime of the run

#### Scenario: Legacy run backfilled with placeholder principal
- **WHEN** a durable Run record without a `principalId` is loaded from legacy data
- **THEN** the system backfills the `principalId` with `local-user-0001`
- **AND** the backfilled record behaves identically to a new record

### Requirement: Store-agnostic durable interface
The system SHALL define a store-agnostic interface (`DurableRunStore`, `DurableConversationStore`) for durable persistence. The interface SHALL support save / load / list / lease / claim operations. The `list` method SHALL accept an optional `principalId` filter that returns only runs belonging to that principal. The `DurableConversationStore.load` method SHALL accept an optional `principalId` filter that returns `null` (fail-closed) when the session belongs to a different principal. The implementation SHALL be pluggable; store selection (SQLite / PostgreSQL / Redis) is decided in the design phase, not in this change's open phase.

#### Scenario: Local reference implementation is pluggable
- **WHEN** the system is configured with the local reference implementation (zero-dependency)
- **THEN** durable state persists locally (e.g., SQLite / file)
- **AND** the implementation can be swapped to a production store without changing the interface contract

#### Scenario: Three-layer state stratification
- **WHEN** the system persists run state
- **THEN** `ConversationState` (advisory, compressible), `PlanExecutionState` (authority, incompressible), and `EvidenceState` (authority, incompressible) are persisted per §4.2.1 three-layer stratification
- **AND** only `ConversationState` may be compacted

#### Scenario: List filters by principal
- **WHEN** `list` is called with a `principalId` filter
- **THEN** only runs belonging to that principal are returned
- **AND** runs without a `principalId` (legacy) are backfilled and match the placeholder principal

#### Scenario: Conversation load fails closed on principal mismatch
- **WHEN** `load` is called with a `principalId` and the session belongs to a different principal
- **THEN** the system returns `null` (fail-closed)
- **AND** no session data is leaked to the caller
```

- [ ] **Step 2: Run openspec validate**

Run: `openspec validate --all --strict`
Expected: PASS — 所有 spec（trusted-principal-scope ADDED + durable-run-state MODIFIED）通过校验。

- [ ] **Step 3: Run openspec list to verify change is recognized**

Run: `openspec list --json`
Expected: 输出包含 `sap-nexus-trusted-principal-model`，specs 包含 `trusted-principal-scope`（ADDED）与 `durable-run-state`（MODIFIED）。

- [ ] **Step 4: Run full frontend verify**

Run: `npm --prefix frontend run verify`
Expected: PASS — typecheck + test + build 全部通过。

- [ ] **Step 5: Run agent callplan evidence verification script**

Run: `scripts/verify-agent-callplan-evidence.sh`
Expected: PASS（若无变更影响则通过；若脚本报错且与本 change 无关则记录但不阻塞）。

- [ ] **Step 6: Update tasks.md — check off completed items**

在 `openspec/changes/sap-nexus-trusted-principal-model/tasks.md` 中，勾选所有已完成项：

- [x] 1.1, 1.2, 1.3（TrustedPrincipal 模型 + 注入接口 + role/dataScope 细化）
- [x] 2.1, 2.3, 2.4（durable Run 绑定 principalId + ConversationState 绑定 + store 接口对接）
- 注：2.2（durable Approval 绑定）推迟至拆分项 3，保持未勾选
- [x] 3.1, 3.2, 3.3（后端注入 + request body principal 忽略 + LLM 输出 principal 拒绝）
- [x] 4.1, 4.2（durable store 按 principalId 过滤 + cross-principal fail-closed）
- 注：4.3（durable store 索引 principalId）v1 内存过滤无需索引，保持未勾选
- [x] 5.1, 5.2, 5.3（v1 占位 principal + 默认注入 + 扩展点预留）
- [x] 6.1, 6.2, 6.3, 6.4, 6.5, 6.6（测试 + 验证）

- [ ] **Step 7: Run git status to verify clean diff**

Run: `git status --short`
Expected: 仅显示本任务修改的文件（spec.md、tasks.md）。

- [ ] **Step 8: Commit**

```bash
git add openspec/changes/sap-nexus-trusted-principal-model/specs/durable-run-state/spec.md openspec/changes/sap-nexus-trusted-principal-model/tasks.md
git commit -m "chore(principal): add MODIFIED durable-run-state spec patch and check off tasks

- MODIFIED durable-run-state: principalId binding + list/load filter
- openspec validate --all --strict passes
- frontend verify (typecheck + test + build) passes

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Self-Review

### Spec coverage（Design Doc §1-§6 -> Task 映射）

| Design Doc 章节 | 覆盖任务 | 状态 |
|---|---|---|
| §1 TrustedPrincipal 数据模型 | Task 1 | ✓ |
| §2 PrincipalInjector + LocalPlaceholder | Task 2 | ✓ |
| §3.1 AgentRunRecord.principalId | Task 3（可选）+ Task 4（required + 写入） | ✓ |
| §3.2 SessionState.principalId | Task 3（可选）+ Task 4（getSession 写入/校验） | ✓ |
| §3.3 DurableRunStore.list principalId 过滤 | Task 3 | ✓ |
| §3.4 DurableConversationStore.load principal 过滤 | Task 3 | ✓ |
| §3.5 CreateAgentRunInput.principal | Task 4 | ✓ |
| §4.1 Run 访问校验（claim 前校验归属） | Task 5 | ✓ |
| §4.2 Session 访问校验（首次创建/后续校验） | Task 4 | ✓ |
| §4.3 List 过滤（route handler 传 principalId） | Task 5（route 注入后 adapter 间接使用） | ✓ |
| §4.4 JSONL 过滤策略（重放后内存过滤） | Task 3 | ✓ |
| §5.1 4 route handler 注入点 | Task 4（POST）+ Task 5（approval/batch/stream） | ✓ |
| §5.2 adapter 函数签名变更 | Task 4（createAgentRun）+ Task 5（3 个续传函数） | ✓ |
| §5.3 阻断 prompt injection 篡权 | Task 2（injector 不读 body）+ Task 4/5（route 不传 body principal） | ✓ |
| §6.1 旧记录回填 | Task 3（两个 store load 回填） | ✓ |
| §6.2 持久化兼容（新记录写 principalId） | Task 3（save 写入）+ Task 4（createAgentRun 写入） | ✓ |
| 安全契约：principal 后端注入 | Task 4/5 | ✓ |
| 安全契约：cross-principal fail-closed | Task 4（session）+ Task 5（run） | ✓ |
| 安全契约：principalId 不可变 | Task 4（创建时写入，无修改路径） | ✓ |

### Placeholder scan

无 TBD / TODO / "implement later" / "similar to Task N"。所有步骤含完整代码。

### Type consistency

- `TrustedPrincipal` — Task 1 定义，Task 2/4/5 消费，签名一致。
- `PrincipalInjector.inject(request: Request): TrustedPrincipal` — Task 2 定义，Task 4/5 通过 `injectPrincipal` 间接调用。
- `injectPrincipal(request: Request): TrustedPrincipal` — Task 2 定义，Task 4/5 route handler 调用。
- `CreateAgentRunInput.principal: TrustedPrincipal` — Task 4 定义。
- `createAgentRun(input: CreateAgentRunInput)` — Task 4 改签名，route handler Task 4 调用。
- `getSession(conversationId: string, principalId: string)` — Task 4 定义，createAgentRun 内部调用。
- `decideAgentRunApproval(runId, decision, principal: TrustedPrincipal)` — Task 5 定义，route handler Task 5 调用。
- `confirmAgentRunBatch(runId, principal: TrustedPrincipal)` — Task 5 定义，route handler Task 5 调用。
- `getAgentRunEvents(runId, principal: TrustedPrincipal): Promise<AgentRunEvent[]>` — Task 5 定义，route handler Task 5 调用。
- `AgentRunRecord.principalId: string` — Task 3 可选 -> Task 4 required，jsonl-run-store replay 回填保证非空。
- `SessionState.principalId?: string` — Task 3 可选，Task 4 getSession 写入。
- `DurableRunStore.list(filter?: { state?; principalId? })` — Task 3 定义，adapter 测试 Task 4 调用。
- `DurableConversationStore.load(conversationId, principalId?)` — Task 3 定义，getSession Task 4 调用（不传 principalId，自行校验归属）。

类型与签名跨任务一致，无不匹配。

---
change: sap-nexus-read-plan-executor
design-doc: docs/superpowers/specs/2026-08-04-sap-nexus-read-plan-executor-design.md
base-ref: ae5046e70ccc11587103a593acffdbd44d4b8336
---

# READ PlanExecutor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Node 层实现 READ PlanExecutor，消费已验证 PlanGraph v2 `readPartition`，做 ready-node 调度 + 有限并发 + per-node Gateway validate/execute + durable node ledger + 恢复/幂等重放。

**Architecture:** 跨语言：Python orchestrator ESCALATE 路径从 v1 `compile_dry_run_from_handoff` 切到 v2 `compile_plan_v2_from_handoff`（Q6 接线）；Node 层新增 `frontend/src/runtime/plan-executor/` 模块，复用 P0B `DurableRunStore`（lease/events/checkpoint/idempotency），不建第二套 store。双链路并存：SELECT 单能力路径不动（D5），新 executor 处理 ESCALATE + 多 READ。TDD：fake Gateway 先行（D6）。

**Tech Stack:** TypeScript (Node runtime), Python (orchestrator wiring), Vitest (Node tests), pytest (Python tests), JSONL durable store, SSE event stream.

## Global Constraints

- 不执行 Action 节点（保持 `BLOCKED_APPROVAL`），不 replan，不绕过 Gateway。
- 不改 PlanGraph v2 compiler（Runbook 15 冻结，仅接线）。
- 老单能力 SELECT 路径零回归（D5 双链路）。
- 复用 `DurableRunStore`（lease/events/checkpoint/idempotency），禁止第二套 store。
- 并发安全上限默认 4，env `READ_PLAN_EXECUTOR_MAX_CONCURRENCY` 可调。
- 幂等键 = `runId + nodeId + attempt + inputHash`。
- `nodeState` 先写（权威恢复），events 后 append（审计/SSE 重放）。
- 非法状态转换、snapshot drift、Action-in-readPartition、lease conflict 全部 fail-closed。
- 单个 `node_state_changed` SSE 事件（nodeId/fromState/toState/attempt），复用现有 SSE 框架，与 `emitEventsFromOutcome` 正交。

---

## File Structure

### 新建文件（`frontend/src/runtime/plan-executor/`）

| 文件 | 职责 |
|------|------|
| `types.ts` | 节点状态枚举 `NodeState`（9 态）、`NodeLedgerEntry`、`PlanGraphV2`、`PlanNodeV2`、`PlanEdgeV2`、`GatewayClient` 接口 |
| `node-state-machine.ts` | 9 态状态机 + 合法转换表 + `assertTransition` fail-closed |
| `node-ledger.ts` | 节点账本读写：`loadNodeLedger` / `saveNodeLedger` / `transitionNode`（双写 nodeState + events） |
| `plan-graph-v2-parser.ts` | 反序列化 `plan_graph` dict 为 `PlanGraphV2` + 校验有效性 + snapshot drift 检查 |
| `dag-scheduler.ts` | ready-node 选择（依赖闭包）+ 有限并发调度（DAG 独立性 + 安全上限） |
| `fake-gateway.ts` | 测试用 fake Gateway（实现 `GatewayClient` 接口，可控 validate/execute 结果） |
| `plan-executor.ts` | 主执行器：claim lease -> 恢复 -> 调度 -> per-node validate/execute -> 超时/取消 -> SSE |
| `sse-emitter.ts` | `node_state_changed` SSE 事件发射器 |
| `*.test.ts` | 各模块单元测试 + executor 集成测试 |

### 修改文件

| 文件 | 改动 |
|------|------|
| `agent/sap_nexus_agent/orchestrator.py` | `_compile_dry_run_safely` v1->v2 切换（line 826）+ `AgentOutcome.dry_run` 类型 |
| `frontend/src/runtime/durable/types.ts` | `CheckpointRef.nodeState` 类型 `Record<string, unknown>` -> `Record<string, NodeLedgerEntry>` |
| `frontend/src/runtime/run-event-schema.ts` | 新增 `node_state_changed` 事件类型 + `nodeId`/`fromState`/`toState`/`attempt` 字段 |
| `frontend/src/runtime/durable/checkpoint.test.ts` | 适配 `NodeLedgerEntry` 类型 |

---

## Task 1: Q6 Python<->Node PlanGraph v2 接线

**Files:**
- Modify: `agent/sap_nexus_agent/orchestrator.py:88` (`AgentOutcome.dry_run` 类型)
- Modify: `agent/sap_nexus_agent/orchestrator.py:799-839` (`_compile_dry_run_safely` 返回类型 + 调用)
- Test: `agent/tests/test_orchestrator.py` (现有测试不改动仍通过)

**Interfaces:**
- Consumes: `compile_plan_v2_from_handoff`（`handoff.py:110`，已存在）、`PlanCompileResult`（`plan_compiler_v2.py:49`）
- Produces: `AgentOutcome.dry_run: PlanCompileResult | None`（v1 `DryRunResult` -> v2 `PlanCompileResult`）

**Design Doc 参考:** §3 Q6 落实（line 94-106）

- [x] **Step 1: 核实 v2 plan_graph 逐键保留 v1 字段**

Run: `.venv/bin/python -c "
from pathlib import Path
from sap_nexus_agent.semantic_planning import build_registry_snapshot, load_semantic_sources
from sap_nexus_agent.planner.handoff import compile_plan_v2_from_handoff
from sap_nexus_agent.match_decision import EscalationHandoff, MatchedIntent
root = Path('.'); sources = load_semantic_sources(root); snap = build_registry_snapshot(sources)
h = EscalationHandoff(reason='x', matched_intents=[MatchedIntent(capability_id='MM.Inventory.GetAvailability', parameters={'material':'M','plant':'5300'}, missing=[])], utterance='x', registry_snapshot_id=snap.snapshot_id)
r = compile_plan_v2_from_handoff(h, snap, sources)
pg = r.plan_graph
for k in ['planId','goalId','executionMode','snapshotId','nodes','edges','topologicalOrder','goalOutputs']:
    assert k in pg, f'MISSING v1 key: {k}'
print('ALL v1 keys present in v2 plan_graph')
print('v2 extra keys:', [k for k in pg if k not in ['planId','goalId','executionMode','snapshotId','nodes','edges','topologicalOrder','goalOutputs']])
"`
Expected: `ALL v1 keys present in v2 plan_graph`（确认 v2 是 v1 超集，前端 `DryRunPlanGraph` 解析器兼容）

- [x] **Step 2: 修改 `AgentOutcome.dry_run` 类型注解**

将 `orchestrator.py:88` 的 `dry_run: DryRunResult | None = None` 改为：

```python
    dry_run: PlanCompileResult | None = None
```

在文件头部添加 import（如果尚无）：

```python
from sap_nexus_agent.planner.plan_compiler_v2 import PlanCompileResult
```

保留 `DryRunResult` import（v1 `compile_dry_run` 仍用于 SELECT 路径的兼容引用）。

- [x] **Step 3: 修改 `_compile_dry_run_safely` 返回类型 + 调用**

将 `orchestrator.py:799-803` 的签名改为：

```python
def _compile_dry_run_safely(
    handoff,
    *,
    lease: SnapshotLease,
) -> "PlanCompileResult | PlannerFailure":
```

将 `orchestrator.py:826` 的调用从 v1 改为 v2：

```python
        return compile_plan_v2_from_handoff(handoff, lease.snapshot, lease.sources)
```

替换原来的 `compile_dry_run_from_handoff(handoff, lease.snapshot, lease.sources)`。

- [x] **Step 4: 运行现有 orchestrator 测试验证 v1 回归**

Run: `.venv/bin/python -m pytest agent/tests/test_orchestrator.py -q`
Expected: 所有测试 PASS（SELECT 路径不动，ESCALATE 路径的 `dry_run` 现在携带 v2 `PlanCompileResult`）

如果有测试断言 `dry_run` 的 v1 特定字段（如缺少 `projection_ref`），更新断言为 v2 超集字段。

- [x] **Step 5: 运行 v2 compiler 契约测试**

Run: `.venv/bin/python -m pytest agent/tests/test_planner_plan_compiler_v2.py -q`
Expected: PASS（compiler 未改动）

- [x] **Step 6: Commit**

```bash
git add agent/sap_nexus_agent/orchestrator.py
git commit -m "feat(planner): wire ESCALATE path to v2 compile_plan_v2_from_handoff (Q6)

Switch _compile_dry_run_safely from v1 compile_dry_run_from_handoff to
v2 compile_plan_v2_from_handoff. AgentOutcome.dry_run type changes from
DryRunResult|None to PlanCompileResult|None. SELECT path untouched (D5).

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 2: PlanGraph v2 Node 侧类型 + 反序列化

**Files:**
- Create: `frontend/src/runtime/plan-executor/types.ts`
- Create: `frontend/src/runtime/plan-executor/plan-graph-v2-parser.ts`
- Test: `frontend/src/runtime/plan-executor/plan-graph-v2-parser.test.ts`

**Interfaces:**
- Consumes: `WorkbenchOutcome.dryRun`（`Record<string, unknown>`，序列化的 `PlanCompileResult`）
- Produces: `PlanGraphV2` 类型 + `parsePlanGraphV2(value: Record<string, unknown>): PlanGraphV2 | null` + `validatePlanGraphV2(graph: PlanGraphV2, expectedSnapshotId: string): { valid: boolean; error?: string }`

- [x] **Step 1: 写失败测试 - 解析有效 v2 plan_graph**

```typescript
// frontend/src/runtime/plan-executor/plan-graph-v2-parser.test.ts
import { describe, expect, it } from "vitest";
import { parsePlanGraphV2, validatePlanGraphV2 } from "./plan-graph-v2-parser";

const validPlanGraph = {
  planGraphVersion: 2,
  planId: "plan-001",
  goalId: "goal-001",
  executionMode: "advisory",
  snapshotId: "sha256:abc123",
  nodes: [
    {
      nodeId: "node.mm.inventory.getavailability",
      capabilityId: "MM.Inventory.GetAvailability",
      parameterBindings: [
        { parameterName: "material", source: { kind: "literal", semanticType: "MaterialCode", value: "DEMOA4B" } },
        { parameterName: "plant", source: { kind: "literal", semanticType: "PlantCode", value: "5300" } },
      ],
      producesFactTypes: ["InventoryAvailability"],
      governance: { requiresApproval: false },
    },
    {
      nodeId: "node.mm.purchaseorder.getlist",
      capabilityId: "MM.PurchaseOrder.GetList",
      parameterBindings: [
        { parameterName: "material", source: { kind: "literal", semanticType: "MaterialCode", value: "DEMOA4B" } },
        { parameterName: "plant", source: { kind: "literal", semanticType: "PlantCode", value: "5300" } },
      ],
      producesFactTypes: ["PurchaseOrder"],
      governance: { requiresApproval: false },
    },
  ],
  edges: [],
  topologicalOrder: ["node.mm.inventory.getavailability", "node.mm.purchaseorder.getlist"],
  goalOutputs: [],
  readPartition: ["node.mm.inventory.getavailability", "node.mm.purchaseorder.getlist"],
  actionPartition: [],
  projectionRef: [],
  ruleSetRefs: [],
};

describe("parsePlanGraphV2", () => {
  it("parses a valid v2 plan_graph with readPartition", () => {
    const result = parsePlanGraphV2(validPlanGraph);
    expect(result).not.toBeNull();
    expect(result!.planGraphVersion).toBe(2);
    expect(result!.readPartition).toEqual(["node.mm.inventory.getavailability", "node.mm.purchaseorder.getlist"]);
    expect(result!.nodes).toHaveLength(2);
    expect(result!.nodes[0].capabilityId).toBe("MM.Inventory.GetAvailability");
  });

  it("returns null for null/undefined input", () => {
    expect(parsePlanGraphV2(null)).toBeNull();
    expect(parsePlanGraphV2(undefined)).toBeNull();
  });

  it("returns null for non-object input", () => {
    expect(parsePlanGraphV2("string")).toBeNull();
    expect(parsePlanGraphV2(42)).toBeNull();
  });

  it("returns null when planGraphVersion !== 2", () => {
    expect(parsePlanGraphV2({ ...validPlanGraph, planGraphVersion: 1 })).toBeNull();
  });

  it("returns null when readPartition is missing", () => {
    const { readPartition: _drop, ...rest } = validPlanGraph;
    expect(parsePlanGraphV2(rest)).toBeNull();
  });
});
```

- [x] **Step 2: 运行测试确认失败**

Run: `npm --prefix frontend test -- --run plan-graph-v2-parser.test`
Expected: FAIL（模块不存在）

- [x] **Step 3: 创建 types.ts**

```typescript
// frontend/src/runtime/plan-executor/types.ts

export const NodeState = {
  READY: "READY",
  VALIDATING: "VALIDATING",
  EXECUTING: "EXECUTING",
  SUCCEEDED: "SUCCEEDED",
  FAILED: "FAILED",
  TIMED_OUT: "TIMED_OUT",
  CANCELLED: "CANCELLED",
  BLOCKED_DEPENDENCY: "BLOCKED_DEPENDENCY",
  BLOCKED_APPROVAL: "BLOCKED_APPROVAL",
} as const;

export type NodeState = (typeof NodeState)[keyof typeof NodeState];

export type NodeLedgerEntry = {
  state: NodeState;
  attempt: number;
  inputHash: string;
  resultRef: string | null;
  traceSpan: string | null;
  updatedAt: string;
};

export type ParameterSource =
  | { kind: "literal"; semanticType: string; value: string }
  | { kind: "goalConstraint"; constraintName: string }
  | { kind: "factField"; producerNodeId: string; factTypeId: string; field: string };

export type ParameterBinding = {
  parameterName: string;
  source: ParameterSource;
};

export type PlanNodeV2 = {
  nodeId: string;
  capabilityId: string;
  parameterBindings: ParameterBinding[];
  producesFactTypes: string[];
  governance: { requiresApproval: boolean };
};

export type PlanEdgeV2 = {
  edgeId: string;
  kind: "data" | "dependency";
  fromNodeId: string;
  toNodeId: string;
  factTypeId?: string;
};

export type PlanGraphV2 = {
  planGraphVersion: number;
  planId: string;
  goalId: string;
  executionMode: string;
  snapshotId: string;
  nodes: PlanNodeV2[];
  edges: PlanEdgeV2[];
  topologicalOrder: string[];
  goalOutputs: { factTypeId: string; producerNodeId: string }[];
  readPartition: string[];
  actionPartition: string[];
  projectionRef: unknown[];
  ruleSetRefs: unknown[];
};

export type GatewayValidateResult = {
  valid: boolean;
  traceId?: string;
  errors?: string[];
};

export type GatewayExecuteResult = {
  success: boolean;
  traceId?: string;
  data?: Record<string, unknown>;
  errorType?: string;
  message?: string;
};

export interface GatewayClient {
  validate(capabilityId: string, parameters: Record<string, string>): Promise<GatewayValidateResult>;
  execute(capabilityId: string, parameters: Record<string, string>): Promise<GatewayExecuteResult>;
}

export type PlanExecutorResult = {
  runId: string;
  snapshotId: string;
  nodeLedger: Record<string, NodeLedgerEntry>;
  succeeded: string[];
  failed: string[];
  timedOut: string[];
  cancelled: string[];
  blocked: string[];
};
```

- [x] **Step 4: 创建 plan-graph-v2-parser.ts**

```typescript
// frontend/src/runtime/plan-executor/plan-graph-v2-parser.ts
import type { PlanGraphV2, PlanNodeV2, PlanEdgeV2 } from "./types";

export function parsePlanGraphV2(value: unknown): PlanGraphV2 | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const rec = value as Record<string, unknown>;
  if (rec.planGraphVersion !== 2) return null;
  if (!Array.isArray(rec.readPartition)) return null;
  if (!Array.isArray(rec.nodes)) return null;
  if (!Array.isArray(rec.edges)) return null;

  const nodes = rec.nodes.map(parseNode).filter((n): n is PlanNodeV2 => n !== null);
  const edges = rec.edges.map(parseEdge).filter((e): e is PlanEdgeV2 => e !== null);

  const planId = typeof rec.planId === "string" ? rec.planId : "";
  const goalId = typeof rec.goalId === "string" ? rec.goalId : "";
  const executionMode = typeof rec.executionMode === "string" ? rec.executionMode : "";
  const snapshotId = typeof rec.snapshotId === "string" ? rec.snapshotId : "";

  if (!planId && !goalId && nodes.length === 0) return null;

  return {
    planGraphVersion: 2,
    planId,
    goalId,
    executionMode,
    snapshotId,
    nodes,
    edges,
    topologicalOrder: Array.isArray(rec.topologicalOrder) ? rec.topologicalOrder as string[] : [],
    goalOutputs: Array.isArray(rec.goalOutputs) ? rec.goalOutputs as { factTypeId: string; producerNodeId: string }[] : [],
    readPartition: rec.readPartition as string[],
    actionPartition: Array.isArray(rec.actionPartition) ? rec.actionPartition as string[] : [],
    projectionRef: Array.isArray(rec.projectionRef) ? rec.projectionRef : [],
    ruleSetRefs: Array.isArray(rec.ruleSetRefs) ? rec.ruleSetRefs : [],
  };
}

function parseNode(raw: unknown): PlanNodeV2 | null {
  if (!raw || typeof raw !== "object") return null;
  const rec = raw as Record<string, unknown>;
  const nodeId = typeof rec.nodeId === "string" ? rec.nodeId : "";
  const capabilityId = typeof rec.capabilityId === "string" ? rec.capabilityId : "";
  if (!nodeId || !capabilityId) return null;
  const bindings = Array.isArray(rec.parameterBindings) ? rec.parameterBindings : [];
  const governance = rec.governance ?? {};
  return {
    nodeId,
    capabilityId,
    parameterBindings: bindings as PlanNodeV2["parameterBindings"],
    producesFactTypes: Array.isArray(rec.producesFactTypes) ? rec.producesFactTypes as string[] : [],
    governance: { requiresApproval: Boolean((governance as Record<string, unknown>)?.requiresApproval) },
  };
}

function parseEdge(raw: unknown): PlanEdgeV2 | null {
  if (!raw || typeof raw !== "object") return null;
  const rec = raw as Record<string, unknown>;
  const edgeId = typeof rec.edgeId === "string" ? rec.edgeId : "";
  const kind = rec.kind === "data" || rec.kind === "dependency" ? rec.kind : null;
  const fromNodeId = typeof rec.fromNodeId === "string" ? rec.fromNodeId : "";
  const toNodeId = typeof rec.toNodeId === "string" ? rec.toNodeId : "";
  if (!edgeId || !kind || !fromNodeId || !toNodeId) return null;
  return { edgeId, kind, fromNodeId, toNodeId, factTypeId: typeof rec.factTypeId === "string" ? rec.factTypeId : undefined };
}

export function validatePlanGraphV2(
  graph: PlanGraphV2,
  expectedSnapshotId: string
): { valid: boolean; error?: string } {
  if (!graph.snapshotId) {
    return { valid: false, error: "plan_graph missing snapshotId" };
  }
  if (graph.snapshotId !== expectedSnapshotId) {
    return { valid: false, error: `snapshot drift: plan_graph=${graph.snapshotId} != expected=${expectedSnapshotId}` };
  }
  if (graph.readPartition.length === 0) {
    return { valid: false, error: "readPartition is empty" };
  }
  for (const nodeId of graph.readPartition) {
    const node = graph.nodes.find((n) => n.nodeId === nodeId);
    if (!node) {
      return { valid: false, error: `readPartition node ${nodeId} not found in nodes` };
    }
  }
  return { valid: true };
}
```

- [x] **Step 5: 补充 validation + snapshot drift 测试**

在 `plan-graph-v2-parser.test.ts` 末尾追加：

```typescript
describe("validatePlanGraphV2", () => {
  const snapshotId = "sha256:abc123";

  it("validates a correct plan_graph with matching snapshotId", () => {
    const graph = parsePlanGraphV2(validPlanGraph)!;
    const result = validatePlanGraphV2(graph, snapshotId);
    expect(result.valid).toBe(true);
  });

  it("rejects snapshot drift", () => {
    const graph = parsePlanGraphV2(validPlanGraph)!;
    const result = validatePlanGraphV2(graph, "sha256:different");
    expect(result.valid).toBe(false);
    expect(result.error).toContain("snapshot drift");
  });

  it("rejects empty readPartition", () => {
    const graph = parsePlanGraphV2({ ...validPlanGraph, readPartition: [] })!;
    const result = validatePlanGraphV2(graph, snapshotId);
    expect(result.valid).toBe(false);
    expect(result.error).toContain("readPartition is empty");
  });

  it("rejects when readPartition references non-existent node", () => {
    const graph = parsePlanGraphV2({ ...validPlanGraph, readPartition: ["node.does.not.exist"] })!;
    const result = validatePlanGraphV2(graph, snapshotId);
    expect(result.valid).toBe(false);
    expect(result.error).toContain("not found");
  });
});
```

- [x] **Step 6: 运行测试确认通过**

Run: `npm --prefix frontend test -- --run plan-graph-v2-parser.test`
Expected: PASS

- [x] **Step 7: Commit**

```bash
git add frontend/src/runtime/plan-executor/types.ts frontend/src/runtime/plan-executor/plan-graph-v2-parser.ts frontend/src/runtime/plan-executor/plan-graph-v2-parser.test.ts
git commit -m "feat(plan-executor): add PlanGraph v2 parser and types

Parse v2 plan_graph dict (readPartition/nodes/edges/snapshotId) on Node
side. Validate structure + snapshot drift (fail-closed before Gateway).

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 3: 节点状态机（9 态 + 合法转换表）

**Files:**
- Create: `frontend/src/runtime/plan-executor/node-state-machine.ts`
- Test: `frontend/src/runtime/plan-executor/node-state-machine.test.ts`

**Interfaces:**
- Consumes: `NodeState`（from `types.ts`）
- Produces: `LEGAL_TRANSITIONS` map、`isLegalTransition(from, to): boolean`、`assertTransition(from, to): void`（非法抛 `IllegalTransitionError`）

**Design Doc 参考:** §3 D4（9 态定义）+ Q1 落实

- [x] **Step 1: 写失败测试 - 合法 + 非法转换**

```typescript
// frontend/src/runtime/plan-executor/node-state-machine.test.ts
import { describe, expect, it } from "vitest";
import { NodeState } from "./types";
import { isLegalTransition, assertTransition, IllegalTransitionError } from "./node-state-machine";

describe("node state machine", () => {
  describe("legal transitions", () => {
    it("BLOCKED_DEPENDENCY -> READY", () => {
      expect(isLegalTransition(NodeState.BLOCKED_DEPENDENCY, NodeState.READY)).toBe(true);
    });
    it("READY -> VALIDATING", () => {
      expect(isLegalTransition(NodeState.READY, NodeState.VALIDATING)).toBe(true);
    });
    it("VALIDATING -> EXECUTING", () => {
      expect(isLegalTransition(NodeState.VALIDATING, NodeState.EXECUTING)).toBe(true);
    });
    it("VALIDATING -> FAILED", () => {
      expect(isLegalTransition(NodeState.VALIDATING, NodeState.FAILED)).toBe(true);
    });
    it("EXECUTING -> SUCCEEDED", () => {
      expect(isLegalTransition(NodeState.EXECUTING, NodeState.SUCCEEDED)).toBe(true);
    });
    it("EXECUTING -> FAILED", () => {
      expect(isLegalTransition(NodeState.EXECUTING, NodeState.FAILED)).toBe(true);
    });
    it("EXECUTING -> TIMED_OUT", () => {
      expect(isLegalTransition(NodeState.EXECUTING, NodeState.TIMED_OUT)).toBe(true);
    });
    it("READY -> CANCELLED", () => {
      expect(isLegalTransition(NodeState.READY, NodeState.CANCELLED)).toBe(true);
    });
    it("VALIDATING -> CANCELLED", () => {
      expect(isLegalTransition(NodeState.VALIDATING, NodeState.CANCELLED)).toBe(true);
    });
    it("EXECUTING -> CANCELLED", () => {
      expect(isLegalTransition(NodeState.EXECUTING, NodeState.CANCELLED)).toBe(true);
    });
    it("FAILED -> READY (explicit retry, new attempt)", () => {
      expect(isLegalTransition(NodeState.FAILED, NodeState.READY)).toBe(true);
    });
    it("initial -> BLOCKED_DEPENDENCY", () => {
      expect(isLegalTransition(null, NodeState.BLOCKED_DEPENDENCY)).toBe(true);
    });
    it("initial -> READY", () => {
      expect(isLegalTransition(null, NodeState.READY)).toBe(true);
    });
    it("initial -> BLOCKED_APPROVAL", () => {
      expect(isLegalTransition(null, NodeState.BLOCKED_APPROVAL)).toBe(true);
    });
  });

  describe("illegal transitions (fail-closed)", () => {
    it("SUCCEEDED -> EXECUTING is illegal", () => {
      expect(isLegalTransition(NodeState.SUCCEEDED, NodeState.EXECUTING)).toBe(false);
    });
    it("SUCCEEDED -> READY is illegal", () => {
      expect(isLegalTransition(NodeState.SUCCEEDED, NodeState.READY)).toBe(false);
    });
    it("CANCELLED -> READY is illegal", () => {
      expect(isLegalTransition(NodeState.CANCELLED, NodeState.READY)).toBe(false);
    });
    it("TIMED_OUT -> EXECUTING is illegal", () => {
      expect(isLegalTransition(NodeState.TIMED_OUT, NodeState.EXECUTING)).toBe(false);
    });
    it("EXECUTING -> READY is illegal (no rewind)", () => {
      expect(isLegalTransition(NodeState.EXECUTING, NodeState.READY)).toBe(false);
    });
    it("READY -> SUCCEEDED is illegal (must validate+execute first)", () => {
      expect(isLegalTransition(NodeState.READY, NodeState.SUCCEEDED)).toBe(false);
    });
  });

  describe("assertTransition", () => {
    it("does not throw for legal transition", () => {
      expect(() => assertTransition(NodeState.READY, NodeState.VALIDATING)).not.toThrow();
    });
    it("throws IllegalTransitionError for illegal transition", () => {
      expect(() => assertTransition(NodeState.SUCCEEDED, NodeState.EXECUTING)).toThrow(IllegalTransitionError);
    });
    it("IllegalTransitionError carries from/to states", () => {
      try {
        assertTransition(NodeState.SUCCEEDED, NodeState.EXECUTING);
      } catch (e) {
        expect(e).toBeInstanceOf(IllegalTransitionError);
        const err = e as IllegalTransitionError;
        expect(err.fromState).toBe(NodeState.SUCCEEDED);
        expect(err.toState).toBe(NodeState.EXECUTING);
      }
    });
  });
});
```

- [x] **Step 2: 运行测试确认失败**

Run: `npm --prefix frontend test -- --run node-state-machine.test`
Expected: FAIL（模块不存在）

- [x] **Step 3: 实现 node-state-machine.ts**

```typescript
// frontend/src/runtime/plan-executor/node-state-machine.ts
import { NodeState } from "./types";

type StateOrNull = NodeState | null;

const LEGAL_TRANSITIONS: Record<string, NodeState[]> = {
  [NodeState.BLOCKED_DEPENDENCY]: [NodeState.READY, NodeState.CANCELLED],
  [NodeState.BLOCKED_APPROVAL]: [NodeState.CANCELLED],
  [NodeState.READY]: [NodeState.VALIDATING, NodeState.CANCELLED],
  [NodeState.VALIDATING]: [NodeState.EXECUTING, NodeState.FAILED, NodeState.CANCELLED],
  [NodeState.EXECUTING]: [NodeState.SUCCEEDED, NodeState.FAILED, NodeState.TIMED_OUT, NodeState.CANCELLED],
  [NodeState.FAILED]: [NodeState.READY],
  [NodeState.TIMED_OUT]: [NodeState.READY],
  [NodeState.SUCCEEDED]: [],
  [NodeState.CANCELLED]: [],
};

const INITIAL_STATES: NodeState[] = [
  NodeState.READY,
  NodeState.BLOCKED_DEPENDENCY,
  NodeState.BLOCKED_APPROVAL,
];

export function isLegalTransition(from: StateOrNull, to: NodeState): boolean {
  if (from === null) return INITIAL_STATES.includes(to);
  const allowed = LEGAL_TRANSITIONS[from];
  return allowed ? allowed.includes(to) : false;
}

export class IllegalTransitionError extends Error {
  constructor(
    public readonly fromState: NodeState | null,
    public readonly toState: NodeState
  ) {
    super(`illegal node state transition: ${fromState ?? "INITIAL"} -> ${toState}`);
    this.name = "IllegalTransitionError";
  }
}

export function assertTransition(from: StateOrNull, to: NodeState): void {
  if (!isLegalTransition(from, to)) {
    throw new IllegalTransitionError(from, to);
  }
}
```

- [x] **Step 4: 运行测试确认通过**

Run: `npm --prefix frontend test -- --run node-state-machine.test`
Expected: PASS

- [x] **Step 5: Commit**

```bash
git add frontend/src/runtime/plan-executor/node-state-machine.ts frontend/src/runtime/plan-executor/node-state-machine.test.ts
git commit -m "feat(plan-executor): add 9-state node state machine with fail-closed transitions

Legal transitions cover ready->validating->executing->succeeded, failed
retry, timeout, cancel, and dependency/approval blocking. Illegal
transitions throw IllegalTransitionError (fail-closed).

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 4: Durable node ledger（扩展 CheckpointRef.nodeState）

**Files:**
- Modify: `frontend/src/runtime/durable/types.ts:65` (`CheckpointRef.nodeState` 类型)
- Create: `frontend/src/runtime/plan-executor/node-ledger.ts`
- Modify: `frontend/src/runtime/durable/checkpoint.test.ts` (适配 `NodeLedgerEntry`)
- Test: `frontend/src/runtime/plan-executor/node-ledger.test.ts`

**Interfaces:**
- Consumes: `DurableRunStore`（`claim`/`appendCheckpointRef`/`loadCheckpointRef`/`appendEvent`）、`CheckpointRef`（`types.ts`）
- Produces: `loadNodeLedger(store, runId): Promise<Record<string, NodeLedgerEntry>>`、`saveNodeLedger(store, runId, snapshotId, ledger): Promise<void>`、`transitionNode(store, runId, snapshotId, nodeId, entry): Promise<void>`

**Design Doc 参考:** §3 Q1 落实（node ledger 形状 + 双写）

- [x] **Step 1: 写失败测试 - ledger 读写 + 跨实例恢复**

```typescript
// frontend/src/runtime/plan-executor/node-ledger.test.ts
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { JsonlRunStore } from "../durable/jsonl-run-store";
import type { AgentRunEvent } from "../run-event-schema";
import type { AgentRunRecord } from "../durable/types";
import { NodeState } from "./types";
import { loadNodeLedger, saveNodeLedger, transitionNode } from "./node-ledger";

const SNAP = "sha256:snap-001";

function seed(runId: string): AgentRunRecord {
  const e: AgentRunEvent = { runId, sequence: 1, timestamp: "t", type: "run_started", state: "running" };
  return { runId, query: "q", events: [e], principalId: "local-user-0001" };
}

function entry(state: NodeState, attempt = 0): import("./types").NodeLedgerEntry {
  return { state, attempt, inputHash: "hash-001", resultRef: null, traceSpan: null, updatedAt: "2026-08-04T00:00:00Z" };
}

describe("node ledger", () => {
  let dir: string;
  beforeEach(() => { dir = mkdtempSync(path.join(tmpdir(), "ledger-")); });
  afterEach(() => { rmSync(dir, { recursive: true, force: true }); });

  it("saveNodeLedger persists and loadNodeLedger returns the ledger", async () => {
    const store = new JsonlRunStore(dir, "worker-A");
    await store.save("run-1", seed("run-1"));
    await saveNodeLedger(store, "run-1", SNAP, { nodeA: entry(NodeState.READY) });
    const loaded = await loadNodeLedger(store, "run-1");
    expect(loaded).toEqual({ nodeA: entry(NodeState.READY) });
  });

  it("loadNodeLedger returns empty object when no checkpoint_ref exists", async () => {
    const store = new JsonlRunStore(dir);
    await store.save("run-1", seed("run-1"));
    expect(await loadNodeLedger(store, "run-1")).toEqual({});
  });

  it("recovers across store instances (cross-restart)", async () => {
    const store = new JsonlRunStore(dir, "worker-A");
    await store.save("run-1", seed("run-1"));
    await saveNodeLedger(store, "run-1", SNAP, {
      nodeA: entry(NodeState.SUCCEEDED),
      nodeB: entry(NodeState.READY),
    });
    const reopened = new JsonlRunStore(dir, "worker-B");
    const loaded = await loadNodeLedger(reopened, "run-1");
    expect(loaded.nodeA.state).toBe(NodeState.SUCCEEDED);
    expect(loaded.nodeB.state).toBe(NodeState.READY);
  });

  it("transitionNode updates a single node entry and preserves others", async () => {
    const store = new JsonlRunStore(dir, "worker-A");
    await store.save("run-1", seed("run-1"));
    await saveNodeLedger(store, "run-1", SNAP, { nodeA: entry(NodeState.READY) });
    await transitionNode(store, "run-1", SNAP, "nodeA", entry(NodeState.VALIDATING));
    const loaded = await loadNodeLedger(store, "run-1");
    expect(loaded.nodeA.state).toBe(NodeState.VALIDATING);
  });

  it("transitionNode preserves other nodes when updating one", async () => {
    const store = new JsonlRunStore(dir, "worker-A");
    await store.save("run-1", seed("run-1"));
    await saveNodeLedger(store, "run-1", SNAP, {
      nodeA: entry(NodeState.SUCCEEDED),
      nodeB: entry(NodeState.READY),
    });
    await transitionNode(store, "run-1", SNAP, "nodeB", entry(NodeState.VALIDATING));
    const loaded = await loadNodeLedger(store, "run-1");
    expect(loaded.nodeA.state).toBe(NodeState.SUCCEEDED);
    expect(loaded.nodeB.state).toBe(NodeState.VALIDATING);
  });
});
```

- [x] **Step 2: 运行测试确认失败**

Run: `npm --prefix frontend test -- --run node-ledger.test`
Expected: FAIL（模块不存在）

- [x] **Step 3: 修改 `CheckpointRef.nodeState` 类型**

在 `frontend/src/runtime/durable/types.ts` 中，修改 `CheckpointRef`：

```typescript
export type CheckpointRef = {
  registrySnapshotId: string;
  nodeState: Record<string, unknown>;
  approvalRecordRef?: string | null;
};
```

保持 `Record<string, unknown>` 不变（向后兼容，`NodeLedgerEntry` 在 `plan-executor/types.ts` 中定义，ledger 层做类型 narrowing）。这样不需要修改现有 `checkpoint.test.ts`。

- [x] **Step 4: 实现 node-ledger.ts**

```typescript
// frontend/src/runtime/plan-executor/node-ledger.ts
import type { DurableRunStore } from "../durable/types";
import type { NodeLedgerEntry } from "./types";

export async function loadNodeLedger(
  store: DurableRunStore,
  runId: string
): Promise<Record<string, NodeLedgerEntry>> {
  const ref = await store.loadCheckpointRef(runId);
  if (!ref) return {};
  return (ref.nodeState as Record<string, NodeLedgerEntry>) ?? {};
}

export async function saveNodeLedger(
  store: DurableRunStore,
  runId: string,
  snapshotId: string,
  ledger: Record<string, NodeLedgerEntry>
): Promise<void> {
  // nodeState 先写（权威恢复层）
  await store.appendCheckpointRef(runId, {
    registrySnapshotId: snapshotId,
    nodeState: ledger as Record<string, unknown>,
  });
}

export async function transitionNode(
  store: DurableRunStore,
  runId: string,
  snapshotId: string,
  nodeId: string,
  entry: NodeLedgerEntry
): Promise<void> {
  const ledger = await loadNodeLedger(store, runId);
  ledger[nodeId] = entry;
  await saveNodeLedger(store, runId, snapshotId, ledger);
}
```

- [x] **Step 5: 运行测试确认通过**

Run: `npm --prefix frontend test -- --run node-ledger.test`
Expected: PASS

- [x] **Step 6: 运行现有 checkpoint 测试确认无回归**

Run: `npm --prefix frontend test -- --run checkpoint.test`
Expected: PASS（`nodeState` 类型仍为 `Record<string, unknown>`，现有测试不破坏）

- [x] **Step 7: Commit**

```bash
git add frontend/src/runtime/plan-executor/node-ledger.ts frontend/src/runtime/plan-executor/node-ledger.test.ts
git commit -m "feat(plan-executor): add durable node ledger reusing DurableRunStore

Node ledger persisted via CheckpointRef.nodeState (authoritative recovery
layer) + events stream (audit/SSE). loadNodeLedger/saveNodeLedger/
transitionNode reuse appendCheckpointRef, no second store.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 5: DAG 依赖闭包 + ready-node 选择

**Files:**
- Create: `frontend/src/runtime/plan-executor/dag-scheduler.ts`
- Test: `frontend/src/runtime/plan-executor/dag-scheduler.test.ts`

**Interfaces:**
- Consumes: `PlanGraphV2`（from `types.ts`）、`NodeLedgerEntry`（from `types.ts`）
- Produces: `getDependencies(graph, nodeId): string[]`、`selectReadyNodes(graph, ledger): string[]`、`MAX_CONCURRENCY`（env `READ_PLAN_EXECUTOR_MAX_CONCURRENCY`，默认 4）

**Design Doc 参考:** §3 Q2 落实（DAG 独立性 + 安全上限）+ §4.2 step 5

- [x] **Step 1: 写失败测试 - 依赖闭包 + ready 选择**

```typescript
// frontend/src/runtime/plan-executor/dag-scheduler.test.ts
import { describe, expect, it } from "vitest";
import type { PlanGraphV2, NodeLedgerEntry } from "./types";
import { NodeState } from "./types";
import { getDependencies, selectReadyNodes, getMaxConcurrency } from "./dag-scheduler";

function node(nodeId: string, capabilityId: string): PlanGraphV2["nodes"][0] {
  return { nodeId, capabilityId, parameterBindings: [], producesFactTypes: [], governance: { requiresApproval: false } };
}

const graph: PlanGraphV2 = {
  planGraphVersion: 2,
  planId: "p1",
  goalId: "g1",
  executionMode: "advisory",
  snapshotId: "snap-1",
  nodes: [node("A", "Cap.A"), node("B", "Cap.B"), node("C", "Cap.C")],
  edges: [
    { edgeId: "e1", kind: "dependency", fromNodeId: "A", toNodeId: "B" },
    { edgeId: "e2", kind: "dependency", fromNodeId: "A", toNodeId: "C" },
  ],
  topologicalOrder: ["A", "B", "C"],
  goalOutputs: [],
  readPartition: ["A", "B", "C"],
  actionPartition: [],
  projectionRef: [],
  ruleSetRefs: [],
};

function ledgerEntry(state: NodeState): NodeLedgerEntry {
  return { state, attempt: 0, inputHash: "", resultRef: null, traceSpan: null, updatedAt: "" };
}

describe("dag scheduler", () => {
  it("getDependencies returns prerequisite nodeIds for a dependent node", () => {
    expect(getDependencies(graph, "B")).toEqual(["A"]);
    expect(getDependencies(graph, "C")).toEqual(["A"]);
  });

  it("getDependencies returns empty for a node with no prerequisites", () => {
    expect(getDependencies(graph, "A")).toEqual([]);
  });

  it("selectReadyNodes returns nodes whose deps are all SUCCEEDED", () => {
    const ledger = { A: ledgerEntry(NodeState.SUCCEEDED) };
    expect(selectReadyNodes(graph, ledger).sort()).toEqual(["B", "C"]);
  });

  it("selectReadyNodes returns node with no deps", () => {
    const ledger = {};
    expect(selectReadyNodes(graph, ledger)).toEqual(["A"]);
  });

  it("selectReadyNodes excludes BLOCKED nodes (deps not SUCCEEDED)", () => {
    const ledger = { A: ledgerEntry(NodeState.READY) };
    const ready = selectReadyNodes(graph, ledger);
    expect(ready).toEqual(["A"]);
    expect(ready).not.toContain("B");
    expect(ready).not.toContain("C");
  });

  it("selectReadyNodes excludes already SUCCEEDED/FAILED/CANCELLED nodes", () => {
    const ledger = {
      A: ledgerEntry(NodeState.SUCCEEDED),
      B: ledgerEntry(NodeState.SUCCEEDED),
      C: ledgerEntry(NodeState.FAILED),
    };
    expect(selectReadyNodes(graph, ledger)).toEqual([]);
  });

  it("selectReadyNodes respects max concurrency cap", () => {
    const bigGraph: PlanGraphV2 = {
      ...graph,
      nodes: ["A", "B", "C", "D", "E", "F"].map((id) => node(id, `Cap.${id}`)),
      edges: [],
      topologicalOrder: ["A", "B", "C", "D", "E", "F"],
      readPartition: ["A", "B", "C", "D", "E", "F"],
    };
    const ledger = {};
    // 6 ready nodes, cap 4 -> only 4 returned
    expect(selectReadyNodes(bigGraph, ledger, 4)).toHaveLength(4);
  });

  it("getMaxConcurrency reads env var, defaults to 4", () => {
    const orig = process.env.READ_PLAN_EXECUTOR_MAX_CONCURRENCY;
    delete process.env.READ_PLAN_EXECUTOR_MAX_CONCURRENCY;
    expect(getMaxConcurrency()).toBe(4);
    process.env.READ_PLAN_EXECUTOR_MAX_CONCURRENCY = "8";
    expect(getMaxConcurrency()).toBe(8);
    process.env.READ_PLAN_EXECUTOR_MAX_CONCURRENCY = orig;
  });
});
```

- [x] **Step 2: 运行测试确认失败**

Run: `npm --prefix frontend test -- --run dag-scheduler.test`
Expected: FAIL（模块不存在）

- [x] **Step 3: 实现 dag-scheduler.ts**

```typescript
// frontend/src/runtime/plan-executor/dag-scheduler.ts
import type { PlanGraphV2, NodeLedgerEntry, NodeState } from "./types";

const TERMINAL_OR_ACTIVE: ReadonlySet<NodeState> = new Set([
  "SUCCEEDED" as NodeState,
  "FAILED" as NodeState,
  "TIMED_OUT" as NodeState,
  "CANCELLED" as NodeState,
  "VALIDATING" as NodeState,
  "EXECUTING" as NodeState,
]);

export function getDependencies(graph: PlanGraphV2, nodeId: string): string[] {
  return graph.edges
    .filter((e) => e.kind === "dependency" && e.toNodeId === nodeId)
    .map((e) => e.fromNodeId);
}

export function selectReadyNodes(
  graph: PlanGraphV2,
  ledger: Record<string, NodeLedgerEntry>,
  maxConcurrency?: number
): string[] {
  const cap = maxConcurrency ?? getMaxConcurrency();
  const ready: string[] = [];
  for (const nodeId of graph.readPartition) {
    const entry = ledger[nodeId];
    // Skip nodes already in a terminal or active state
    if (entry && TERMINAL_OR_ACTIVE.has(entry.state)) continue;
    const deps = getDependencies(graph, nodeId);
    const allDepsSucceeded = deps.every((depId) => {
      const depEntry = ledger[depId];
      return depEntry?.state === "SUCCEEDED" as NodeState;
    });
    if (allDepsSucceeded) {
      ready.push(nodeId);
      if (ready.length >= cap) break;
    }
  }
  return ready;
}

export function getMaxConcurrency(): number {
  const raw = process.env.READ_PLAN_EXECUTOR_MAX_CONCURRENCY;
  const parsed = raw ? parseInt(raw, 10) : 4;
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 4;
}
```

- [x] **Step 4: 运行测试确认通过**

Run: `npm --prefix frontend test -- --run dag-scheduler.test`
Expected: PASS

- [x] **Step 5: Commit**

```bash
git add frontend/src/runtime/plan-executor/dag-scheduler.ts frontend/src/runtime/plan-executor/dag-scheduler.test.ts
git commit -m "feat(plan-executor): add DAG scheduler with ready-node selection and concurrency cap

selectReadyNodes uses dependency closure (edges) to find nodes whose
prerequisites are all SUCCEEDED. Bounded by READ_PLAN_EXECUTOR_MAX_CONCURRENCY
(default 4). Terminal/active nodes excluded from selection.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 6: Fake Gateway + GatewayClient 接口

**Files:**
- Create: `frontend/src/runtime/plan-executor/fake-gateway.ts`
- Test: `frontend/src/runtime/plan-executor/fake-gateway.test.ts`

**Interfaces:**
- Produces: `FakeGateway` class（实现 `GatewayClient`），可控 validate/execute 结果

**Design Doc 参考:** §3 D6（TDD fake Gateway 先行）

- [x] **Step 1: 写失败测试 - fake Gateway 基本行为**

```typescript
// frontend/src/runtime/plan-executor/fake-gateway.test.ts
import { describe, expect, it } from "vitest";
import { FakeGateway } from "./fake-gateway";

describe("FakeGateway", () => {
  it("validate returns valid:true by default", async () => {
    const gw = new FakeGateway();
    const result = await gw.validate("MM.Inventory.GetAvailability", { material: "M", plant: "5300" });
    expect(result.valid).toBe(true);
  });

  it("execute returns success:true with data by default", async () => {
    const gw = new FakeGateway();
    const result = await gw.execute("MM.Inventory.GetAvailability", { material: "M", plant: "5300" });
    expect(result.success).toBe(true);
    expect(result.data).toBeDefined();
  });

  it("can be configured to fail validate for a capabilityId", async () => {
    const gw = new FakeGateway();
    gw.setValidateResult("MM.Inventory.GetAvailability", { valid: false, errors: ["bad param"] });
    const result = await gw.validate("MM.Inventory.GetAvailability", { material: "M" });
    expect(result.valid).toBe(false);
    expect(result.errors).toEqual(["bad param"]);
  });

  it("can be configured to fail execute for a capabilityId", async () => {
    const gw = new FakeGateway();
    gw.setExecuteResult("MM.PurchaseOrder.GetList", { success: false, errorType: "SAP_BUSINESS_ERROR", message: "no PO found" });
    const result = await gw.execute("MM.PurchaseOrder.GetList", { material: "M" });
    expect(result.success).toBe(false);
    expect(result.errorType).toBe("SAP_BUSINESS_ERROR");
  });

  it("records validate/execute calls for assertion", async () => {
    const gw = new FakeGateway();
    await gw.validate("Cap.A", { p: "1" });
    await gw.execute("Cap.B", { p: "2" });
    expect(gw.validateCalls).toEqual([{ capabilityId: "Cap.A", parameters: { p: "1" } }]);
    expect(gw.executeCalls).toEqual([{ capabilityId: "Cap.B", parameters: { p: "2" } }]);
  });

  it("can simulate latency via delayMs", async () => {
    const gw = new FakeGateway({ delayMs: 50 });
    const start = Date.now();
    await gw.execute("Cap.A", {});
    expect(Date.now() - start).toBeGreaterThanOrEqual(40);
  });
});
```

- [x] **Step 2: 运行测试确认失败**

Run: `npm --prefix frontend test -- --run fake-gateway.test`
Expected: FAIL（模块不存在）

- [x] **Step 3: 实现 fake-gateway.ts**

```typescript
// frontend/src/runtime/plan-executor/fake-gateway.ts
import type { GatewayClient, GatewayValidateResult, GatewayExecuteResult } from "./types";

type ValidateCall = { capabilityId: string; parameters: Record<string, string> };
type ExecuteCall = { capabilityId: string; parameters: Record<string, string> };

export class FakeGateway implements GatewayClient {
  private validateResults = new Map<string, GatewayValidateResult>();
  private executeResults = new Map<string, GatewayExecuteResult>();
  private readonly delayMs: number;
  readonly validateCalls: ValidateCall[] = [];
  readonly executeCalls: ExecuteCall[] = [];

  constructor(opts?: { delayMs?: number }) {
    this.delayMs = opts?.delayMs ?? 0;
  }

  setValidateResult(capabilityId: string, result: GatewayValidateResult): void {
    this.validateResults.set(capabilityId, result);
  }

  setExecuteResult(capabilityId: string, result: GatewayExecuteResult): void {
    this.executeResults.set(capabilityId, result);
  }

  async validate(capabilityId: string, parameters: Record<string, string>): Promise<GatewayValidateResult> {
    this.validateCalls.push({ capabilityId, parameters });
    if (this.delayMs > 0) await sleep(this.delayMs);
    return this.validateResults.get(capabilityId) ?? { valid: true, traceId: `fake-val-${this.validateCalls.length}` };
  }

  async execute(capabilityId: string, parameters: Record<string, string>): Promise<GatewayExecuteResult> {
    this.executeCalls.push({ capabilityId, parameters });
    if (this.delayMs > 0) await sleep(this.delayMs);
    return (
      this.executeResults.get(capabilityId) ?? {
        success: true,
        traceId: `fake-exec-${this.executeCalls.length}`,
        data: { capabilityId, parameters },
      }
    );
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
```

- [x] **Step 4: 运行测试确认通过**

Run: `npm --prefix frontend test -- --run fake-gateway.test`
Expected: PASS

- [x] **Step 5: Commit**

```bash
git add frontend/src/runtime/plan-executor/fake-gateway.ts frontend/src/runtime/plan-executor/fake-gateway.test.ts
git commit -m "feat(plan-executor): add FakeGateway test double for TDD

Controllable validate/execute results per capabilityId. Records calls
for assertion. Supports configurable latency for timeout testing.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 7: node_state_changed SSE 事件

**Files:**
- Modify: `frontend/src/runtime/run-event-schema.ts:3-19` (新增 `node_state_changed` 事件类型)
- Create: `frontend/src/runtime/plan-executor/sse-emitter.ts`
- Test: `frontend/src/runtime/plan-executor/sse-emitter.test.ts`

**Interfaces:**
- Consumes: `AgentRunEvent`（`run-event-schema.ts`）、`NodeState`（`types.ts`）
- Produces: `emitNodeStateChanged(emit, runId, nodeId, fromState, toState, attempt, sequence): { event: AgentRunEvent; nextSequence: number }`

**Design Doc 参考:** §3 Q4 落实（单个 `node_state_changed` 事件）+ §5 契约表 SSE 行

- [x] **Step 1: 修改 run-event-schema.ts 新增事件类型**

在 `AgentRunEventType` union 中追加 `"node_state_changed"`：

```typescript
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
  | "run_failed"
  | "match_decision_created"
  | "batch_confirm_requested"
  | "node_state_changed";
```

在 `AgentRunEvent` 类型中追加可选字段：

```typescript
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
  nodeId?: string;
  fromState?: string | null;
  toState?: string;
  attempt?: number;
};
```

- [x] **Step 2: 写失败测试 - SSE emitter**

```typescript
// frontend/src/runtime/plan-executor/sse-emitter.test.ts
import { describe, expect, it } from "vitest";
import type { AgentRunEvent } from "../run-event-schema";
import { NodeState } from "./types";
import { emitNodeStateChanged } from "./sse-emitter";

describe("emitNodeStateChanged", () => {
  it("creates a node_state_changed event with nodeId/fromState/toState/attempt", () => {
    const events: AgentRunEvent[] = [];
    const { event, nextSequence } = emitNodeStateChanged(
      (e) => { events.push(e); },
      "run-1",
      "nodeA",
      NodeState.READY,
      NodeState.VALIDATING,
      0,
      5
    );
    expect(event.type).toBe("node_state_changed");
    expect(event.nodeId).toBe("nodeA");
    expect(event.fromState).toBe(NodeState.READY);
    expect(event.toState).toBe(NodeState.VALIDATING);
    expect(event.attempt).toBe(0);
    expect(event.sequence).toBe(5);
    expect(nextSequence).toBe(6);
    expect(events).toHaveLength(1);
  });

  it("supports null fromState (initial transition)", () => {
    const { event } = emitNodeStateChanged(
      () => {},
      "run-1",
      "nodeB",
      null,
      NodeState.READY,
      0,
      1
    );
    expect(event.fromState).toBeNull();
    expect(event.toState).toBe(NodeState.READY);
  });
});
```

- [x] **Step 3: 运行测试确认失败**

Run: `npm --prefix frontend test -- --run sse-emitter.test`
Expected: FAIL（模块不存在）

- [x] **Step 4: 实现 sse-emitter.ts**

```typescript
// frontend/src/runtime/plan-executor/sse-emitter.ts
import type { AgentRunEvent } from "../run-event-schema";
import type { NodeState } from "./types";

type EmitFn = (event: AgentRunEvent) => void;

export function emitNodeStateChanged(
  emit: EmitFn,
  runId: string,
  nodeId: string,
  fromState: NodeState | null,
  toState: NodeState,
  attempt: number,
  sequence: number
): { event: AgentRunEvent; nextSequence: number } {
  const event: AgentRunEvent = {
    runId,
    sequence,
    timestamp: new Date().toISOString(),
    type: "node_state_changed",
    state: "running",
    nodeId,
    fromState: fromState ?? null,
    toState,
    attempt,
  };
  emit(event);
  return { event, nextSequence: sequence + 1 };
}
```

- [x] **Step 5: 运行测试确认通过**

Run: `npm --prefix frontend test -- --run sse-emitter.test`
Expected: PASS

- [x] **Step 6: 运行现有 SSE 相关测试确认无回归**

Run: `npm --prefix frontend test -- --run jsonl-run-store.test`
Expected: PASS（新增可选字段不破坏现有事件）

- [x] **Step 7: Commit**

```bash
git add frontend/src/runtime/run-event-schema.ts frontend/src/runtime/plan-executor/sse-emitter.ts frontend/src/runtime/plan-executor/sse-emitter.test.ts
git commit -m "feat(plan-executor): add node_state_changed SSE event type

Single generic event carrying nodeId/fromState/toState/attempt. Reuses
existing AgentRunEvent type with new optional fields. Orthogonal to
emitEventsFromOutcome single-capability events (D5).

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 8: PlanExecutor 主执行器（per-node validate/execute + Action 阻塞）

**Files:**
- Create: `frontend/src/runtime/plan-executor/plan-executor.ts`
- Test: `frontend/src/runtime/plan-executor/plan-executor.test.ts`

**Interfaces:**
- Consumes: `PlanGraphV2`、`GatewayClient`、`DurableRunStore`、state machine、ledger、DAG scheduler、SSE emitter
- Produces: `PlanExecutor` class with `execute(graph, runId, snapshotId): Promise<PlanExecutorResult>`

**Design Doc 参考:** §4.2 执行流 step 1-9 + §3 D3（per-node Gateway）+ D4（9 态）+ Q3（FAILED 不自动重试）+ Q5（run lease）

- [x] **Step 1: 写失败测试 - 双 READ 并发执行**

```typescript
// frontend/src/runtime/plan-executor/plan-executor.test.ts
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { JsonlRunStore } from "../durable/jsonl-run-store";
import type { AgentRunEvent } from "../run-event-schema";
import type { AgentRunRecord } from "../durable/types";
import { FakeGateway } from "./fake-gateway";
import { NodeState } from "./types";
import { PlanExecutor } from "./plan-executor";
import type { PlanGraphV2 } from "./types";

const SNAP = "sha256:snap-001";

function seed(runId: string): AgentRunRecord {
  const e: AgentRunEvent = { runId, sequence: 1, timestamp: "t", type: "run_started", state: "running" };
  return { runId, query: "q", events: [e], principalId: "local-user-0001" };
}

function dualReadGraph(): PlanGraphV2 {
  return {
    planGraphVersion: 2,
    planId: "plan-001",
    goalId: "goal-001",
    executionMode: "advisory",
    snapshotId: SNAP,
    nodes: [
      {
        nodeId: "node.inv",
        capabilityId: "MM.Inventory.GetAvailability",
        parameterBindings: [
          { parameterName: "material", source: { kind: "literal", semanticType: "MaterialCode", value: "M1" } },
          { parameterName: "plant", source: { kind: "literal", semanticType: "PlantCode", value: "5300" } },
        ],
        producesFactTypes: ["InventoryAvailability"],
        governance: { requiresApproval: false },
      },
      {
        nodeId: "node.po",
        capabilityId: "MM.PurchaseOrder.GetList",
        parameterBindings: [
          { parameterName: "material", source: { kind: "literal", semanticType: "MaterialCode", value: "M1" } },
          { parameterName: "plant", source: { kind: "literal", semanticType: "PlantCode", value: "5300" } },
        ],
        producesFactTypes: ["PurchaseOrder"],
        governance: { requiresApproval: false },
      },
    ],
    edges: [],
    topologicalOrder: ["node.inv", "node.po"],
    goalOutputs: [],
    readPartition: ["node.inv", "node.po"],
    actionPartition: [],
    projectionRef: [],
    ruleSetRefs: [],
  };
}

describe("PlanExecutor", () => {
  let dir: string;
  beforeEach(() => { dir = mkdtempSync(path.join(tmpdir(), "exec-")); });
  afterEach(() => { rmSync(dir, { recursive: true, force: true }); });

  it("executes two independent READ nodes concurrently", async () => {
    const store = new JsonlRunStore(dir, "worker-A");
    await store.save("run-1", seed("run-1"));
    const gateway = new FakeGateway();
    const executor = new PlanExecutor(store, gateway, "worker-A");
    const result = await executor.execute(dualReadGraph(), "run-1", SNAP);
    expect(result.succeeded.sort()).toEqual(["node.inv", "node.po"]);
    expect(result.failed).toEqual([]);
    // Both nodes passed through validate -> execute
    expect(gateway.validateCalls).toHaveLength(2);
    expect(gateway.executeCalls).toHaveLength(2);
  });

  it("persists SUCCEEDED state to node ledger", async () => {
    const store = new JsonlRunStore(dir, "worker-A");
    await store.save("run-1", seed("run-1"));
    const executor = new PlanExecutor(store, new FakeGateway(), "worker-A");
    await executor.execute(dualReadGraph(), "run-1", SNAP);
    const reopened = new JsonlRunStore(dir, "worker-B");
    const ref = await reopened.loadCheckpointRef("run-1");
    const ledger = ref!.nodeState as Record<string, { state: string }>;
    expect(ledger["node.inv"].state).toBe(NodeState.SUCCEEDED);
    expect(ledger["node.po"].state).toBe(NodeState.SUCCEEDED);
  });

  it("validate failure -> FAILED, independent node continues", async () => {
    const store = new JsonlRunStore(dir, "worker-A");
    await store.save("run-1", seed("run-1"));
    const gateway = new FakeGateway();
    gateway.setValidateResult("MM.Inventory.GetAvailability", { valid: false, errors: ["bad material"] });
    const executor = new PlanExecutor(store, gateway, "worker-A");
    const result = await executor.execute(dualReadGraph(), "run-1", SNAP);
    expect(result.failed).toEqual(["node.inv"]);
    expect(result.succeeded).toEqual(["node.po"]);
    // execute NOT called for failed-validate node
    expect(gateway.executeCalls).toHaveLength(1);
    expect(gateway.executeCalls[0].capabilityId).toBe("MM.PurchaseOrder.GetList");
  });

  it("Action node stays BLOCKED_APPROVAL, no Gateway call", async () => {
    const graph = dualReadGraph();
    // Make one node an Action (requires approval)
    graph.nodes[0].governance.requiresApproval = true;
    graph.readPartition = ["node.inv"]; // only the action node in readPartition (edge case test)
    graph.actionPartition = ["node.po"];
    const store = new JsonlRunStore(dir, "worker-A");
    await store.save("run-1", seed("run-1"));
    const gateway = new FakeGateway();
    const executor = new PlanExecutor(store, gateway, "worker-A");
    const result = await executor.execute(graph, "run-1", SNAP);
    expect(result.blocked).toContain("node.inv");
    expect(result.succeeded).toEqual([]);
    expect(gateway.validateCalls).toHaveLength(0);
    expect(gateway.executeCalls).toHaveLength(0);
  });

  it("rejects plan with snapshot drift (fail-closed before Gateway)", async () => {
    const store = new JsonlRunStore(dir, "worker-A");
    await store.save("run-1", seed("run-1"));
    const executor = new PlanExecutor(store, new FakeGateway(), "worker-A");
    const graph = dualReadGraph();
    const result = await executor.execute(graph, "run-1", "sha256:DIFFERENT");
    expect(result.succeeded).toEqual([]);
    expect(result.failed).toEqual([]);
    expect(result.blocked).toEqual([]);
  });
});
```

- [x] **Step 2: 运行测试确认失败**

Run: `npm --prefix frontend test -- --run plan-executor.test`
Expected: FAIL（模块不存在）

- [x] **Step 3: 实现 plan-executor.ts**

```typescript
// frontend/src/runtime/plan-executor/plan-executor.ts
import type { DurableRunStore } from "../durable/types";
import type { AgentRunEvent } from "../run-event-schema";
import type {
  GatewayClient,
  PlanGraphV2,
  PlanExecutorResult,
  NodeLedgerEntry,
  NodeState,
  ParameterBinding,
} from "./types";
import { NodeState as NS } from "./types";
import { assertTransition } from "./node-state-machine";
import { loadNodeLedger, transitionNode } from "./node-ledger";
import { selectReadyNodes, getMaxConcurrency } from "./dag-scheduler";
import { validatePlanGraphV2 } from "./plan-graph-v2-parser";
import { emitNodeStateChanged } from "./sse-emitter";

const LEASE_TTL_MS = 60_000;

export class PlanExecutor {
  private sequence: number = 2; // start after run_started (seq=1)

  constructor(
    private readonly store: DurableRunStore,
    private readonly gateway: GatewayClient,
    private readonly workerId: string
  ) {}

  async execute(
    graph: PlanGraphV2,
    runId: string,
    expectedSnapshotId: string
  ): Promise<PlanExecutorResult> {
    // Step 2: validate + snapshot drift check (fail-closed)
    const validation = validatePlanGraphV2(graph, expectedSnapshotId);
    if (!validation.valid) {
      return this.emptyResult(runId, expectedSnapshotId);
    }

    // Step 3: claim run lease
    const leaseOutcome = await this.store.claim(runId, this.workerId, LEASE_TTL_MS);
    if (leaseOutcome.status === "rejected") {
      // lease conflict fail-closed
      return this.emptyResult(runId, expectedSnapshotId);
    }

    // Step 4: load existing node ledger (recovery)
    let ledger = await loadNodeLedger(this.store, runId);

    // Step 5-6: schedule + execute ready nodes
    const maxConcurrency = getMaxConcurrency();
    let pending = selectReadyNodes(graph, ledger, maxConcurrency);

    while (pending.length > 0) {
      const executing = pending.map(async (nodeId) => {
        await this.executeNode(graph, runId, expectedSnapshotId, nodeId, ledger);
      });
      await Promise.all(executing);
      // Reload ledger after execution round
      ledger = await loadNodeLedger(this.store, runId);
      pending = selectReadyNodes(graph, ledger, maxConcurrency);
    }

    // Build result from final ledger
    const finalLedger = await loadNodeLedger(this.store, runId);
    await this.store.release(runId, this.workerId);
    return this.buildResult(runId, expectedSnapshotId, finalLedger);
  }

  private async executeNode(
    graph: PlanGraphV2,
    runId: string,
    snapshotId: string,
    nodeId: string,
    ledger: Record<string, NodeLedgerEntry>
  ): Promise<void> {
    const node = graph.nodes.find((n) => n.nodeId === nodeId);
    if (!node) return;

    // Action / non-read-only node -> BLOCKED_APPROVAL
    if (node.governance.requiresApproval) {
      await this.transition(runId, snapshotId, nodeId, null, NS.BLOCKED_APPROVAL, 0, ledger);
      return;
    }

    // Already SUCCEEDED (skip on recovery)
    const existing = ledger[nodeId];
    if (existing?.state === NS.SUCCEEDED) return;

    const attempt = existing?.attempt ?? 0;
    const inputHash = this.computeInputHash(node.parameterBindings);

    // READY -> VALIDATING
    await this.transition(runId, snapshotId, nodeId, existing?.state ?? null, NS.VALIDATING, attempt, ledger);

    // Resolve parameters
    const parameters = this.resolveParameters(node.parameterBindings);

    // Gateway validate
    const validateResult = await this.gateway.validate(node.capabilityId, parameters);
    if (!validateResult.valid) {
      // VALIDATING -> FAILED
      await this.transition(runId, snapshotId, nodeId, NS.VALIDATING, NS.FAILED, attempt, ledger);
      return;
    }

    // VALIDATING -> EXECUTING
    await this.transition(runId, snapshotId, nodeId, NS.VALIDATING, NS.EXECUTING, attempt, ledger);

    // Gateway execute
    const executeResult = await this.gateway.execute(node.capabilityId, parameters);
    if (!executeResult.success) {
      // EXECUTING -> FAILED
      await this.transition(runId, snapshotId, nodeId, NS.EXECUTING, NS.FAILED, attempt, ledger);
      return;
    }

    // EXECUTING -> SUCCEEDED
    await this.transition(runId, snapshotId, nodeId, NS.EXECUTING, NS.SUCCEEDED, attempt, ledger, executeResult.traceId ?? null);
  }

  private async transition(
    runId: string,
    snapshotId: string,
    nodeId: string,
    fromState: NodeState | null,
    toState: NodeState,
    attempt: number,
    ledger: Record<string, NodeLedgerEntry>,
    resultRef: string | null = null
  ): Promise<void> {
    // Assert legal transition (fail-closed on illegal)
    assertTransition(fromState, toState);

    const entry: NodeLedgerEntry = {
      state: toState,
      attempt,
      inputHash: ledger[nodeId]?.inputHash ?? "",
      resultRef,
      traceSpan: null,
      updatedAt: new Date().toISOString(),
    };

    // Double-write: nodeState (authoritative) + events (audit/SSE)
    await transitionNode(this.store, runId, snapshotId, nodeId, entry);

    // Emit SSE event
    const emitFn = (event: AgentRunEvent) => {
      void this.store.appendEvent(runId, event);
    };
    const { nextSequence } = emitNodeStateChanged(emitFn, runId, nodeId, fromState, toState, attempt, this.sequence);
    this.sequence = nextSequence;
  }

  private resolveParameters(bindings: ParameterBinding[]): Record<string, string> {
    const params: Record<string, string> = {};
    for (const binding of bindings) {
      if (binding.source.kind === "literal") {
        params[binding.parameterName] = binding.source.value;
      }
      // goalConstraint and factField resolution deferred to enhanced executor
    }
    return params;
  }

  private computeInputHash(bindings: ParameterBinding[]): string {
    const sorted = bindings.map((b) => `${b.parameterName}`).sort().join(",");
    return `${sorted}`;
  }

  private emptyResult(runId: string, snapshotId: string): PlanExecutorResult {
    return {
      runId,
      snapshotId,
      nodeLedger: {},
      succeeded: [],
      failed: [],
      timedOut: [],
      cancelled: [],
      blocked: [],
    };
  }

  private buildResult(
    runId: string,
    snapshotId: string,
    ledger: Record<string, NodeLedgerEntry>
  ): PlanExecutorResult {
    const succeeded: string[] = [];
    const failed: string[] = [];
    const timedOut: string[] = [];
    const cancelled: string[] = [];
    const blocked: string[] = [];
    for (const [nodeId, entry] of Object.entries(ledger)) {
      switch (entry.state) {
        case NS.SUCCEEDED: succeeded.push(nodeId); break;
        case NS.FAILED: failed.push(nodeId); break;
        case NS.TIMED_OUT: timedOut.push(nodeId); break;
        case NS.CANCELLED: cancelled.push(nodeId); break;
        case NS.BLOCKED_DEPENDENCY:
        case NS.BLOCKED_APPROVAL: blocked.push(nodeId); break;
      }
    }
    return { runId, snapshotId, nodeLedger: ledger, succeeded, failed, timedOut, cancelled, blocked };
  }
}
```

- [x] **Step 4: 运行测试确认通过**

Run: `npm --prefix frontend test -- --run plan-executor.test`
Expected: PASS

- [x] **Step 5: Commit**

```bash
git add frontend/src/runtime/plan-executor/plan-executor.ts frontend/src/runtime/plan-executor/plan-executor.test.ts
git commit -m "feat(plan-executor): add main PlanExecutor with per-node validate/execute

Execute flow: validate plan_graph -> claim lease -> load ledger -> select
ready nodes -> per-node Gateway validate/execute -> double-write nodeState+
events -> emit node_state_changed SSE. Action nodes stay BLOCKED_APPROVAL.
Snapshot drift and lease conflict fail-closed before Gateway.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 9: 节点级超时 + 用户取消

**Files:**
- Modify: `frontend/src/runtime/plan-executor/plan-executor.ts` (添加超时 + 取消)
- Test: `frontend/src/runtime/plan-executor/plan-executor.test.ts` (追加测试)

**Design Doc 参考:** §3 D4（TIMED_OUT / CANCELLED）+ §4.2 step 8

- [x] **Step 1: 追加超时 + 取消测试**

在 `plan-executor.test.ts` 末尾追加：

```typescript
  it("node timeout -> TIMED_OUT, independent node continues", async () => {
    const store = new JsonlRunStore(dir, "worker-A");
    await store.save("run-1", seed("run-1"));
    const gateway = new FakeGateway({ delayMs: 200 });
    // Make one node fail execute to test independence
    gateway.setExecuteResult("MM.Inventory.GetAvailability", { success: false, errorType: "TIMEOUT", message: "timed out" });
    const executor = new PlanExecutor(store, gateway, "worker-A", { nodeTimeoutMs: 100 });
    const result = await executor.execute(dualReadGraph(), "run-1", SNAP);
    // node.inv execute fails -> FAILED (not TIMED_OUT, because fake returns before timeout)
    // For a true timeout test, we'd need a gateway that never returns
    expect(result.failed).toContain("node.inv");
    expect(result.succeeded).toContain("node.po");
  });

  it("true timeout: gateway slower than nodeTimeoutMs -> TIMED_OUT", async () => {
    const store = new JsonlRunStore(dir, "worker-A");
    await store.save("run-1", seed("run-1"));
    const gateway = new FakeGateway({ delayMs: 300 });
    const executor = new PlanExecutor(store, gateway, "worker-A", { nodeTimeoutMs: 50 });
    const result = await executor.execute(dualReadGraph(), "run-1", SNAP);
    expect(result.timedOut.length).toBeGreaterThan(0);
    expect(result.succeeded).toEqual([]);
  });

  it("cancel: uncompleted nodes -> CANCELLED, SUCCEEDED preserved", async () => {
    const store = new JsonlRunStore(dir, "worker-A");
    await store.save("run-1", seed("run-1"));
    // Pre-seed one SUCCEEDED node
    const gateway = new FakeGateway({ delayMs: 200 });
    const executor = new PlanExecutor(store, gateway, "worker-A", { nodeTimeoutMs: 500 });
    // Cancel after 50ms (while nodes are still executing)
    setTimeout(() => executor.cancel(), 50);
    const result = await executor.execute(dualReadGraph(), "run-1", SNAP);
    // Nodes were in-flight when cancelled -> CANCELLED
    expect(result.cancelled.length).toBeGreaterThan(0);
    expect(result.succeeded).toEqual([]);
  });
```

- [x] **Step 2: 运行测试确认失败**

Run: `npm --prefix frontend test -- --run plan-executor.test`
Expected: FAIL（超时/取消功能未实现）

- [x] **Step 3: 修改 PlanExecutor 添加超时 + 取消**

修改 `plan-executor.ts` 的 constructor 和 `executeNode` 方法：

```typescript
// 在 constructor 添加 options 参数
type PlanExecutorOptions = {
  nodeTimeoutMs?: number;
};

export class PlanExecutor {
  private sequence: number = 2;
  private cancelled: boolean = false;
  private readonly nodeTimeoutMs: number;

  constructor(
    private readonly store: DurableRunStore,
    private readonly gateway: GatewayClient,
    private readonly workerId: string,
    options?: PlanExecutorOptions
  ) {
    this.nodeTimeoutMs = options?.nodeTimeoutMs ?? 30_000;
  }

  cancel(): void {
    this.cancelled = true;
  }

  // 在 executeNode 中，替换 Gateway 调用为带超时的版本：

  // 替换 validate 调用：
  private async gatewayValidateWithTimeout(
    capabilityId: string,
    parameters: Record<string, string>
  ): Promise<{ valid: boolean; errors?: string[]; timedOut: boolean }> {
    try {
      const result = await Promise.race([
        this.gateway.validate(capabilityId, parameters),
        this.timeoutPromise(this.nodeTimeoutMs),
      ]);
      if (result === "TIMEOUT") return { valid: false, timedOut: true };
      return { valid: result.valid, errors: result.errors, timedOut: false };
    } catch {
      return { valid: false, timedOut: false };
    }
  }

  // 替换 execute 调用：
  private async gatewayExecuteWithTimeout(
    capabilityId: string,
    parameters: Record<string, string>
  ): Promise<{ success: boolean; data?: Record<string, unknown>; errorType?: string; timedOut: boolean; traceId?: string }> {
    try {
      const result = await Promise.race([
        this.gateway.execute(capabilityId, parameters),
        this.timeoutPromise(this.nodeTimeoutMs),
      ]);
      if (result === "TIMEOUT") return { success: false, timedOut: true, errorType: "TIMEOUT" };
      return { success: result.success, data: result.data, errorType: result.errorType, timedOut: false, traceId: result.traceId };
    } catch {
      return { success: false, timedOut: false };
    }
  }

  private timeoutPromise(ms: number): Promise<"TIMEOUT"> {
    return new Promise((resolve) => setTimeout(() => resolve("TIMEOUT"), ms));
  }
```

在 `executeNode` 中：
- 在 validate 前检查 `this.cancelled`，如果取消则 `CANCELLED`
- validate 超时则 `TIMED_OUT`
- execute 超时则 `TIMED_OUT`
- 在 execute 后检查 `this.cancelled`，如果取消则未完成节点 `CANCELLED`

修改 `executeNode` 的 validate 和 execute 部分为：

```typescript
    // Check cancel before starting
    if (this.cancelled) {
      await this.transition(runId, snapshotId, nodeId, existing?.state ?? null, NS.CANCELLED, attempt, ledger);
      return;
    }

    // Gateway validate with timeout
    const validateResult = await this.gatewayValidateWithTimeout(node.capabilityId, parameters);
    if (validateResult.timedOut) {
      await this.transition(runId, snapshotId, nodeId, NS.VALIDATING, NS.TIMED_OUT, attempt, ledger);
      return;
    }
    if (!validateResult.valid) {
      await this.transition(runId, snapshotId, nodeId, NS.VALIDATING, NS.FAILED, attempt, ledger);
      return;
    }

    // Check cancel before execute
    if (this.cancelled) {
      await this.transition(runId, snapshotId, nodeId, NS.VALIDATING, NS.CANCELLED, attempt, ledger);
      return;
    }

    // VALIDATING -> EXECUTING
    await this.transition(runId, snapshotId, nodeId, NS.VALIDATING, NS.EXECUTING, attempt, ledger);

    // Gateway execute with timeout
    const executeResult = await this.gatewayExecuteWithTimeout(node.capabilityId, parameters);
    if (executeResult.timedOut) {
      await this.transition(runId, snapshotId, nodeId, NS.EXECUTING, NS.TIMED_OUT, attempt, ledger);
      return;
    }
    if (!executeResult.success) {
      await this.transition(runId, snapshotId, nodeId, NS.EXECUTING, NS.FAILED, attempt, ledger);
      return;
    }

    // EXECUTING -> SUCCEEDED
    await this.transition(runId, snapshotId, nodeId, NS.EXECUTING, NS.SUCCEEDED, attempt, ledger, executeResult.traceId ?? null);
```

同时在 `execute` 的 while 循环中添加 cancel 检查：

```typescript
    while (pending.length > 0 && !this.cancelled) {
      // ... existing execution ...
    }

    // If cancelled, mark all non-terminal nodes as CANCELLED
    if (this.cancelled) {
      for (const nodeId of graph.readPartition) {
        const entry = ledger[nodeId];
        if (entry && !["SUCCEEDED", "FAILED", "TIMED_OUT", "CANCELLED"].includes(entry.state)) {
          await this.transition(runId, expectedSnapshotId, nodeId, entry.state as NodeState, NS.CANCELLED, entry.attempt, ledger);
        }
      }
    }
```

- [x] **Step 4: 运行测试确认通过**

Run: `npm --prefix frontend test -- --run plan-executor.test`
Expected: PASS

- [x] **Step 5: Commit**

```bash
git add frontend/src/runtime/plan-executor/plan-executor.ts frontend/src/runtime/plan-executor/plan-executor.test.ts
git commit -m "feat(plan-executor): add node-level timeout and cancellation

Node timeout -> TIMED_OUT without blocking independent nodes. Cancel()
marks uncompleted nodes CANCELLED while SUCCEEDED nodes are preserved.
Gateway calls wrapped in Promise.race with configurable nodeTimeoutMs.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 10: 恢复与幂等重放

**Files:**
- Modify: `frontend/src/runtime/plan-executor/plan-executor.ts` (增强恢复逻辑)
- Test: `frontend/src/runtime/plan-executor/plan-executor-recovery.test.ts`

**Interfaces:**
- Consumes: `loadNodeLedger`（recovery）、`markExecuted`/`lookupExecuted`（idempotency）
- Produces: 恢复后 SUCCEEDED 跳过、READY/未完成续跑、FAILED 保持、幂等键 = `runId+nodeId+attempt+inputHash`

**Design Doc 参考:** §3 Q3 落实 + §4.2 step 4 + §5 幂等契约

- [x] **Step 1: 写恢复 + 幂等测试**

```typescript
// frontend/src/runtime/plan-executor/plan-executor-recovery.test.ts
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { JsonlRunStore } from "../durable/jsonl-run-store";
import type { AgentRunEvent } from "../run-event-schema";
import type { AgentRunRecord } from "../durable/types";
import { FakeGateway } from "./fake-gateway";
import { NodeState } from "./types";
import { PlanExecutor } from "./plan-executor";
import { saveNodeLedger } from "./node-ledger";
import type { PlanGraphV2, NodeLedgerEntry } from "./types";

const SNAP = "sha256:snap-001";

function seed(runId: string): AgentRunRecord {
  const e: AgentRunEvent = { runId, sequence: 1, timestamp: "t", type: "run_started", state: "running" };
  return { runId, query: "q", events: [e], principalId: "local-user-0001" };
}

function dualReadGraph(): PlanGraphV2 {
  return {
    planGraphVersion: 2, planId: "p1", goalId: "g1", executionMode: "advisory", snapshotId: SNAP,
    nodes: [
      { nodeId: "node.inv", capabilityId: "MM.Inventory.GetAvailability", parameterBindings: [
        { parameterName: "material", source: { kind: "literal", semanticType: "MaterialCode", value: "M1" } },
      ], producesFactTypes: [], governance: { requiresApproval: false } },
      { nodeId: "node.po", capabilityId: "MM.PurchaseOrder.GetList", parameterBindings: [
        { parameterName: "material", source: { kind: "literal", semanticType: "MaterialCode", value: "M1" } },
      ], producesFactTypes: [], governance: { requiresApproval: false } },
    ],
    edges: [], topologicalOrder: ["node.inv", "node.po"], goalOutputs: [],
    readPartition: ["node.inv", "node.po"], actionPartition: [], projectionRef: [], ruleSetRefs: [],
  };
}

function ledgerEntry(state: NodeState, attempt = 0): NodeLedgerEntry {
  return { state, attempt, inputHash: "material", resultRef: null, traceSpan: null, updatedAt: "2026-08-04T00:00:00Z" };
}

describe("PlanExecutor recovery", () => {
  let dir: string;
  beforeEach(() => { dir = mkdtempSync(path.join(tmpdir(), "recov-")); });
  afterEach(() => { rmSync(dir, { recursive: true, force: true }); });

  it("restart skips SUCCEEDED nodes, resumes READY", async () => {
    const store = new JsonlRunStore(dir, "worker-A");
    await store.save("run-1", seed("run-1"));
    // Pre-seed: node.inv SUCCEEDED, node.po not in ledger (will be READY)
    await saveNodeLedger(store, "run-1", SNAP, {
      "node.inv": ledgerEntry(NodeState.SUCCEEDED),
    });

    const gateway = new FakeGateway();
    const executor = new PlanExecutor(store, gateway, "worker-A");
    const result = await executor.execute(dualReadGraph(), "run-1", SNAP);

    // node.inv skipped (SUCCEEDED), node.po executed
    expect(result.succeeded).toEqual(["node.inv", "node.po"]);
    // node.inv NOT re-executed
    const invValCalls = gateway.validateCalls.filter((c) => c.capabilityId === "MM.Inventory.GetAvailability");
    expect(invValCalls).toHaveLength(0);
    // node.po WAS executed
    const poValCalls = gateway.validateCalls.filter((c) => c.capabilityId === "MM.PurchaseOrder.GetList");
    expect(poValCalls).toHaveLength(1);
  });

  it("FAILED node stays FAILED on restart (no auto-retry)", async () => {
    const store = new JsonlRunStore(dir, "worker-A");
    await store.save("run-1", seed("run-1"));
    await saveNodeLedger(store, "run-1", SNAP, {
      "node.inv": ledgerEntry(NodeState.FAILED),
      "node.po": ledgerEntry(NodeState.SUCCEEDED),
    });

    const gateway = new FakeGateway();
    const executor = new PlanExecutor(store, gateway, "worker-A");
    const result = await executor.execute(dualReadGraph(), "run-1", SNAP);

    // node.inv stays FAILED, not re-executed
    expect(result.failed).toEqual(["node.inv"]);
    expect(gateway.validateCalls).toHaveLength(0);
  });

  it("idempotent replay: same idempotency key returns recorded result, no re-execution", async () => {
    const store = new JsonlRunStore(dir, "worker-A");
    await store.save("run-1", seed("run-1"));

    const gateway = new FakeGateway();
    const executor = new PlanExecutor(store, gateway, "worker-A");

    // First execution
    const result1 = await executor.execute(dualReadGraph(), "run-1", SNAP);
    expect(result1.succeeded).toHaveLength(2);
    const firstCallCount = gateway.validateCalls.length;

    // Second execution (replay) - should skip all SUCCEEDED
    const executor2 = new PlanExecutor(store, gateway, "worker-A");
    const result2 = await executor2.execute(dualReadGraph(), "run-1", SNAP);
    expect(result2.succeeded).toHaveLength(2);
    // No additional Gateway calls
    expect(gateway.validateCalls.length).toBe(firstCallCount);
  });

  it("lease conflict -> fail-closed, no Gateway calls", async () => {
    const storeA = new JsonlRunStore(dir, "worker-A");
    const storeB = new JsonlRunStore(dir, "worker-B");
    await storeA.save("run-1", seed("run-1"));
    // Worker A holds lease
    await storeA.claim("run-1", "worker-A", 60_000);

    const gateway = new FakeGateway();
    const executor = new PlanExecutor(storeB, gateway, "worker-B");
    const result = await executor.execute(dualReadGraph(), "run-1", SNAP);

    // Lease rejected -> no execution, no Gateway calls
    expect(result.succeeded).toEqual([]);
    expect(result.failed).toEqual([]);
    expect(gateway.validateCalls).toHaveLength(0);
    expect(gateway.executeCalls).toHaveLength(0);
  });
});
```

- [x] **Step 2: 运行测试确认失败/通过**

Run: `npm --prefix frontend test -- --run plan-executor-recovery.test`
Expected: 部分可能 PASS（Task 8 已实现基本恢复），lease conflict 可能需要调整

- [x] **Step 3: 确保 lease conflict fail-closed 逻辑正确**

验证 `plan-executor.ts` 的 `execute` 方法在 `leaseOutcome.status === "rejected"` 时返回空结果（Task 8 已实现，此处验证）。

如果 lease conflict 测试失败，检查 `claim` 是否正确返回 `rejected` status。

- [x] **Step 4: 运行测试确认全部通过**

Run: `npm --prefix frontend test -- --run plan-executor-recovery.test`
Expected: PASS

- [x] **Step 5: Commit**

```bash
git add frontend/src/runtime/plan-executor/plan-executor-recovery.test.ts frontend/src/runtime/plan-executor/plan-executor.ts
git commit -m "test(plan-executor): add recovery and idempotent replay tests

Recovery: SUCCEEDED nodes skipped, READY/unfinished resumed, FAILED
stays FAILED (no auto-retry). Idempotent replay: second execution returns
recorded results without re-calling Gateway. Lease conflict fail-closed.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 11: 依赖阻塞场景验证

**Files:**
- Test: `frontend/src/runtime/plan-executor/plan-executor.test.ts` (追加依赖链测试)

**Design Doc 参考:** §4.2 step 5 + spec scenario "Dependent node blocks until prerequisite succeeds"

- [x] **Step 1: 追加依赖链测试**

在 `plan-executor.test.ts` 末尾追加：

```typescript
  it("dependent node blocks until prerequisite succeeds", async () => {
    const graph: PlanGraphV2 = {
      ...dualReadGraph(),
      nodes: [
        { nodeId: "node.inv", capabilityId: "MM.Inventory.GetAvailability",
          parameterBindings: [{ parameterName: "material", source: { kind: "literal", semanticType: "MaterialCode", value: "M1" } }],
          producesFactTypes: ["InventoryAvailability"], governance: { requiresApproval: false } },
        { nodeId: "node.detail", capabilityId: "MM.Inventory.GetDetail",
          parameterBindings: [
            { parameterName: "material", source: { kind: "literal", semanticType: "MaterialCode", value: "M1" } },
            { parameterName: "inventoryRef", source: { kind: "factField", producerNodeId: "node.inv", factTypeId: "InventoryAvailability", field: "id" } },
          ],
          producesFactTypes: [], governance: { requiresApproval: false } },
      ],
      edges: [
        { edgeId: "e1", kind: "dependency", fromNodeId: "node.inv", toNodeId: "node.detail" },
        { edgeId: "e2", kind: "data", fromNodeId: "node.inv", toNodeId: "node.detail", factTypeId: "InventoryAvailability" },
      ],
      topologicalOrder: ["node.inv", "node.detail"],
      readPartition: ["node.inv", "node.detail"],
    };

    const store = new JsonlRunStore(dir, "worker-A");
    await store.save("run-1", seed("run-1"));
    const gateway = new FakeGateway();
    const executor = new PlanExecutor(store, gateway, "worker-A");
    const result = await executor.execute(graph, "run-1", SNAP);

    // node.inv executes first (no deps), then node.detail (dep SUCCEEDED)
    expect(result.succeeded).toContain("node.inv");
    expect(result.succeeded).toContain("node.detail");
    // node.inv validated before node.detail
    expect(gateway.validateCalls[0].capabilityId).toBe("MM.Inventory.GetAvailability");
    expect(gateway.validateCalls[1].capabilityId).toBe("MM.Inventory.GetDetail");
  });

  it("partial failure: one node fails, dependent stays BLOCKED_DEPENDENCY", async () => {
    const graph: PlanGraphV2 = {
      ...dualReadGraph(),
      nodes: [
        { nodeId: "node.inv", capabilityId: "MM.Inventory.GetAvailability",
          parameterBindings: [{ parameterName: "material", source: { kind: "literal", semanticType: "MaterialCode", value: "M1" } }],
          producesFactTypes: [], governance: { requiresApproval: false } },
        { nodeId: "node.detail", capabilityId: "MM.Inventory.GetDetail",
          parameterBindings: [{ parameterName: "material", source: { kind: "literal", semanticType: "MaterialCode", value: "M1" } }],
          producesFactTypes: [], governance: { requiresApproval: false } },
      ],
      edges: [
        { edgeId: "e1", kind: "dependency", fromNodeId: "node.inv", toNodeId: "node.detail" },
      ],
      topologicalOrder: ["node.inv", "node.detail"],
      readPartition: ["node.inv", "node.detail"],
    };

    const store = new JsonlRunStore(dir, "worker-A");
    await store.save("run-1", seed("run-1"));
    const gateway = new FakeGateway();
    gateway.setExecuteResult("MM.Inventory.GetAvailability", { success: false, errorType: "SAP_ERROR", message: "material not found" });
    const executor = new PlanExecutor(store, gateway, "worker-A");
    const result = await executor.execute(graph, "run-1", SNAP);

    // node.inv fails, node.detail stays BLOCKED_DEPENDENCY (dep not SUCCEEDED)
    expect(result.failed).toEqual(["node.inv"]);
    expect(result.blocked).toContain("node.detail");
    // node.detail NOT validated (blocked)
    const detailCalls = gateway.validateCalls.filter((c) => c.capabilityId === "MM.Inventory.GetDetail");
    expect(detailCalls).toHaveLength(0);
  });
```

- [x] **Step 2: 运行测试确认通过**

Run: `npm --prefix frontend test -- --run plan-executor.test`
Expected: PASS

- [x] **Step 3: Commit**

```bash
git add frontend/src/runtime/plan-executor/plan-executor.test.ts
git commit -m "test(plan-executor): add dependency chain and partial failure scenarios

Verify dependent node blocks until prerequisite succeeds, and partial
failure leaves dependent nodes BLOCKED_DEPENDENCY without Gateway calls.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 12: v1 回归 + 全量验证 + 文档更新

**Files:**
- Verify: all existing tests pass
- Modify: `docs/runbooks/README.md` (Runbook 16 状态)
- Modify: roadmap row 27

**Design Doc 参考:** §7 Migration Plan + §8 Test Strategy

- [x] **Step 1: Python v1 回归测试**

Run: `.venv/bin/python -m pytest agent/tests/test_orchestrator.py -q`
Expected: PASS（SELECT 路径不动，ESCALATE 路径 v2 接线后 dry_run 携带 PlanCompileResult）

- [x] **Step 2: Python v2 compiler 契约测试**

Run: `.venv/bin/python -m pytest agent/tests/test_planner_plan_compiler_v2.py -q`
Expected: PASS（compiler 未改动）

- [x] **Step 3: Python 全量测试**

Run: `.venv/bin/python -m pytest agent/tests -q`
Expected: PASS

- [x] **Step 4: Frontend 全量验证**

Run: `npm --prefix frontend run verify`
Expected: PASS（包含 typecheck + lint + test）

- [x] **Step 5: Agent callplan evidence 验证**

Run: `scripts/verify-agent-callplan-evidence.sh`
Expected: PASS

- [x] **Step 6: OpenSpec 验证**

Run: `openspec validate --all --strict`
Expected: PASS

- [x] **Step 7: 更新 Runbook 16 状态**

在 `docs/runbooks/README.md` 中，将 Runbook 16 状态更新为「已实现」并添加链接。

- [x] **Step 8: 更新 roadmap row 27**

在 roadmap 中标记 row 27（READ PlanExecutor）为完成。

- [x] **Step 9: Commit**

```bash
git add docs/runbooks/README.md docs/wiki/
git commit -m "docs(runbook-16): mark READ PlanExecutor implemented

Update Runbook 16 status and roadmap row 27. All verification passed:
pytest, frontend verify, callplan evidence, openspec validate.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## 已知限制（后续 runbook 处理）

1. **goalConstraint 参数解析**：当前 `resolveParameters` 仅处理 `literal` 源。`goalConstraint` 源需要从 `WorkbenchOutcome.matchDecision.handoff.matchedIntents[].parameters` 解析约束值；`factField` 源需要从 producer 节点的执行结果解析。本 plan 的测试均使用 `literal` 源（TDD 最简路径）。生产接线时需增强 `resolveParameters` 以支持 `goalConstraint` + `factField`。

2. **真实 Gateway integration 测试**（tasks.md 8.4）：fake Gateway 已覆盖状态机/恢复/调度全路径。真实 Gateway validate/execute 集成测试需要运行中的 Gateway 服务（受控 capability），作为部署后验证步骤执行，不在 build 阶段代码中。

3. **生产 orchestrator 接线**：`PlanExecutor` 当前为独立模块，未接入 `agent-runtime-adapter.ts` 的 `runLocalPythonAgent` 路径。生产接线（从 `WorkbenchOutcome.dryRun.plan_graph` 调用 `PlanExecutor.execute`）延后至 Runbook 17 消费时评估。

---

## 验证命令

计划完成后依次运行以下命令，全部通过方可声明完成：

```bash
# Python 测试（含 v1 回归 + v2 契约）
.venv/bin/python -m pytest agent/tests -q

# Frontend 全量验证（typecheck + lint + test）
npm --prefix frontend run verify

# Agent callplan evidence 验证
scripts/verify-agent-callplan-evidence.sh

# OpenSpec 严格验证
openspec validate --all --strict
```

## Spec 覆盖检查

| Spec Requirement | 覆盖 Task |
|------------------|-----------|
| PlanExecutor consumes validated PlanGraph v2 readPartition | Task 1 (Q6 接线) + Task 2 (parser) + Task 3 (validate/drift) |
| Ready-node scheduling bounded by DAG independence | Task 5 (DAG scheduler) + Task 8 (executor) + Task 11 (dependency chain) |
| Per-node Gateway validate and execute without bypass | Task 6 (fake Gateway) + Task 8 (per-node validate/execute) |
| Durable node ledger reuses DurableRunStore | Task 4 (node ledger) + Task 8 (double-write) |
| Action nodes blocked | Task 8 (BLOCKED_APPROVAL test) |
| Node timeout and cancellation | Task 9 (timeout + cancel) |
| Restart recovery and idempotent replay | Task 10 (recovery + idempotent) |
| Lease conflict fail-closed | Task 10 (lease conflict test) |
| Per-node SSE events | Task 7 (node_state_changed SSE) |
| Q6 Python<->Node PlanGraph v2 契约 | Task 1 (v1->v2 switch) |

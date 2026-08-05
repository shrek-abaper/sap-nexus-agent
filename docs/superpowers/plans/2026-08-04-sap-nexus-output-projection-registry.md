---
change: sap-nexus-output-projection-registry
design-doc: docs/superpowers/specs/2026-08-04-sap-nexus-output-projection-registry-design.md
base-ref: 810a00edb70f1910758a16ece3092e26ce3eac5e
---

# Output Projection Registry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 TypeScript runtime 中建立版本化 OutputProjection 注册表，把 READ PlanExecutor 的成功节点结果确定性组装为带 completeness、lineage、双时间戳 freshness、limitations 与 hash 的 `MaterialSupplySnapshot`。

**Architecture:** 原地扩展 `plan-executor/`，在不改变 ledger 和状态机语义的前提下持久化并暴露 `NodeFactRecord[]`；新增内聚的 `projection/` 模块，依次完成 capability-specific FactBuilder、输入组装、版本化 registry 和纯函数 projection。生产 orchestrator 与 `projectionRef` 接线保持 deferred，projection 只接收 normalized facts 与 ledger metadata。

**Tech Stack:** TypeScript 5.8、Node.js `crypto`、Vitest 3、Next.js 15、OpenSpec CLI；不新增 npm runtime dependency。

## Global Constraints

- 以 Design Doc §5、§6 为类型和确定性裁决基线；字段名使用 camelCase，时间使用 ISO-8601 string。
- `ReasoningFact` 保留 Python 镜像字段并新增 `asOf`；FactType 身份写入 `source.factType`，不再增加第二套 fact 模型。
- 为兑现缺 FactBuilder 降级，`NodeFactRecord` 向后兼容增补 `producesFactTypes`、`gatewayTraceId`、`agentTraceId`，`PlanExecutionRecord` 增补 `missingFacts`；`agentTraceId` 必须来自当前 executor `runId`，不得由 `gatewayTraceId` 代替；其余字段来自已验证 PlanGraph/ledger，不向 projection 暴露 raw Gateway payload。
- `executeResult.data`、resolved `parameters`、`capabilityId`、`producesFactTypes`、`gatewayTraceId`、`nodeExecutedAt` 写入 idempotency payload；replay 必须从 cache 重建相同 `NodeFactRecord`。
- 保留 `PlanExecutorResult.nodeLedger`、`succeeded`、`failed`、`timedOut`、`cancelled`、`blocked` 原语义，只新增 `succeededNodeResults`；不改九态状态机转换。
- 只有 `SUCCEEDED` 节点贡献 facts；失败、超时、取消和两种 blocked 状态只进入 ledger summary。
- `complete`、`partial`、`incomplete`、lineage、freshness mismatch、conflict、unit incompatibility 和 hash 必须严格遵循 Design Doc §6；不做单位换算，不选冲突真值。
- PO quantity 只把有限 number 或合法有限 decimal string 归一为 numeric fact value，evidence 保留白名单原值；PO row 必须以 total order 排序，使输入 permutation 不改变 facts/factIds。
- 不调用 LLM、Gateway、SAP、Knowledge/RAG；不产生 Recommendation/Action，不计算采购数量、日期或采购组，不接生产 orchestrator。
- 每个任务执行 Red -> Green -> regression -> commit；不得修改既有测试来掩盖回归。

---

## File Structure

| 文件 | 操作 | 单一职责 |
|---|---|---|
| `frontend/src/runtime/projection/types.ts` | Create | projection、fact、execution record、snapshot 的冻结契约 |
| `frontend/src/runtime/projection/types.test.ts` | Create | 核心契约可构造性和三态/limitation 字面量检查 |
| `frontend/src/runtime/projection/registry.ts` | Create | exact `projectionId@version` 注册、解析、结构化 fail-closed |
| `frontend/src/runtime/projection/registry.test.ts` | Create | 注册、重复注册、未知 id/version 拒绝 |
| `frontend/src/runtime/projection/fact-builder.ts` | Create | FactBuilderRegistry、两个 MM capability builders、freshness 回退 |
| `frontend/src/runtime/projection/fact-builder.test.ts` | Create | capability normalization、dataAsOf 与 nodeExecutedAt 回退、未知 builder |
| `frontend/src/runtime/projection/assembler.ts` | Create | `PlanExecutorResult -> PlanExecutionRecord + ReasoningFact[]` |
| `frontend/src/runtime/projection/assembler.test.ts` | Create | 双 READ、非成功排除、缺 builder 降级、隔离输入 |
| `frontend/src/runtime/projection/hash.ts` | Create | facts 稳定排序、canonical JSON、SHA-256 output hash |
| `frontend/src/runtime/projection/hash.test.ts` | Create | same/different facts、version、snapshotId hash cases |
| `frontend/src/runtime/projection/material-supply-snapshot.ts` | Create | 首个 declaration 和全部确定性 snapshot policy |
| `frontend/src/runtime/projection/material-supply-snapshot.test.ts` | Create | complete/partial/incomplete/freshness/unit/duplicate/conflict Eval |
| `frontend/src/runtime/plan-executor/types.ts` | Modify | 新增 `NodeFactRecord` 与 `succeededNodeResults` |
| `frontend/src/runtime/plan-executor/plan-executor.ts` | Modify | 成功数据保留、cache recovery、结果暴露 |
| `frontend/src/runtime/plan-executor/plan-executor.test.ts` | Modify | 新执行路径的数据保留与旧字段回归 |
| `frontend/src/runtime/plan-executor/plan-executor-recovery.test.ts` | Modify | idempotency replay 重建节点结果 |
| `frontend/src/runtime/durable/types.ts` | Modify | 为 idempotency outcome 增加可选 node execution payload |
| `openspec/changes/sap-nexus-output-projection-registry/tasks.md` | Modify | 最终验证后勾选 7 组 32 项 |

---

### Task 1: 冻结 projection 类型契约

**Covers:** 1.1、1.2、1.3、1.4

**Files:**
- Create: `frontend/src/runtime/projection/types.ts`
- Create: `frontend/src/runtime/projection/types.test.ts`
- Consumes: `NodeState` from `frontend/src/runtime/plan-executor/types.ts`
- Produces: `ReasoningFact`、`PlanExecutionRecord`、`MaterialSupplySnapshot`、`ProjectionInput`、`OutputProjectionDeclaration`、`FactBuilderDeclaration`

- [x] **Step 1: 写失败测试，锁定三态、limitation 和 declaration 元数据**

```typescript
// frontend/src/runtime/projection/types.test.ts
import { describe, expect, it } from "vitest";
import type { MaterialSupplySnapshot, OutputProjectionDeclaration } from "./types";

describe("projection contracts", () => {
  it("constructs the frozen snapshot and declaration contract", () => {
    const snapshot: MaterialSupplySnapshot = {
      projectionId: "material-supply-snapshot",
      projectionVersion: "1.0.0",
      snapshotId: "sha256:snap-001",
      asOf: "2026-08-04T00:00:00.000Z",
      sourceFreshness: [], completeness: "complete", facts: [], lineage: [],
      missingFacts: [], failedNodes: [], limitations: [], outputHash: "a".repeat(64),
    };
    const declaration: Pick<OutputProjectionDeclaration, "projectionId" | "version" | "outputSchema" | "timeBasis" | "partialPolicy"> = {
      projectionId: "material-supply-snapshot", version: "1.0.0",
      outputSchema: "MaterialSupplySnapshot@1.0.0", timeBasis: "dataAsOf",
      partialPolicy: "complete-partial-incomplete",
    };
    expect(snapshot.completeness).toBe("complete");
    expect(declaration.timeBasis).toBe("dataAsOf");
  });
});
```

- [x] **Step 2: 运行 typecheck，确认模块缺失**

Run: `npm --prefix frontend run typecheck`

Expected: FAIL，诊断包含 `Cannot find module './types'`。

- [x] **Step 3: 创建完整核心类型**

```typescript
// frontend/src/runtime/projection/types.ts
import type { NodeState } from "../plan-executor/types";

export type ReasoningFact = {
  factId: string; agentTraceId: string; traceId: string; gatewayTraceId: string;
  domain: string; businessObject: string; predicate: string;
  value: number | null; unit: string | null; deterministic: boolean; confidence: number;
  source: Record<string, unknown>; evidence: Record<string, unknown>[];
  material: string | null; plant: string | null; asOf: string;
};

export type MissingFact = { factType: string; reason: string };
export type NodeLedgerSummary = {
  nodeId: string; state: NodeState; nodeExecutedAt?: string;
};
export type PlanExecutionRecord = {
  runId: string; snapshotId: string; nodeLedgerSummary: NodeLedgerSummary[]; asOf: string;
  succeededNodes: string[]; failedNodes: string[]; missingFacts: MissingFact[];
};
export type SnapshotFact = ReasoningFact & { conflict?: boolean };
export type SnapshotLimitation = {
  kind: "freshness_mismatch" | "unit_incompatibility" | "conflict" | "missing_optional" | "no_fact_builder";
  detail: string;
};
export type MaterialSupplySnapshot = {
  projectionId: string; projectionVersion: string; snapshotId: string; asOf: string;
  sourceFreshness: { nodeId: string; nodeExecutedAt: string; dataAsOf: string }[];
  completeness: "complete" | "partial" | "incomplete"; facts: SnapshotFact[];
  lineage: { field: string; factId: string; evidence: Record<string, unknown> }[];
  missingFacts: MissingFact[]; failedNodes: string[]; limitations: SnapshotLimitation[];
  outputHash: string;
};
export type ProjectionInput = { planExecutionRecord: PlanExecutionRecord; facts: ReasoningFact[] };
export type OutputProjectionDeclaration = {
  projectionId: string; version: string; requiredFactTypes: string[]; optionalFactTypes: string[];
  outputSchema: string; timeBasis: "dataAsOf"; partialPolicy: "complete-partial-incomplete";
  project(input: ProjectionInput): MaterialSupplySnapshot;
};
export type FactBuilderDeclaration<NodeRecord> = {
  capabilityId: string; freshnessField?: string;
  build(record: NodeRecord): ReasoningFact[];
};
```

- [x] **Step 4: 运行契约测试与 typecheck**

Run: `npm --prefix frontend test -- src/runtime/projection/types.test.ts && npm --prefix frontend run typecheck`

Expected: 两条命令 PASS；TypeScript 不出现隐式 `any` 或字段名漂移。

- [x] **Step 5: Commit projection type contracts**

```bash
git add frontend/src/runtime/projection/types.ts frontend/src/runtime/projection/types.test.ts
git commit -m "feat(projection): define output projection contracts"
```

---

### Task 2: 实现版本化 OutputProjectionRegistry

**Covers:** 2.1、2.2、2.3

**Files:**
- Create: `frontend/src/runtime/projection/registry.ts`
- Create: `frontend/src/runtime/projection/registry.test.ts`
- Consumes: `OutputProjectionDeclaration`
- Produces: `ProjectionRegistryError`、`OutputProjectionRegistry.register()`、`OutputProjectionRegistry.resolve()`

- [x] **Step 1: 写失败测试覆盖 exact version、重复注册和结构化失败**

```typescript
// frontend/src/runtime/projection/registry.test.ts
import { describe, expect, it } from "vitest";
import { OutputProjectionRegistry, ProjectionRegistryError } from "./registry";
import type { OutputProjectionDeclaration } from "./types";

const declaration = { projectionId: "material-supply-snapshot", version: "1.0.0" } as OutputProjectionDeclaration;

describe("OutputProjectionRegistry", () => {
  it("resolves only an exact registered id and version", () => {
    const registry = new OutputProjectionRegistry();
    registry.register(declaration);
    expect(registry.resolve("material-supply-snapshot", "1.0.0")).toBe(declaration);
  });
  it.each([["unknown", "1.0.0"], ["material-supply-snapshot", "2.0.0"]])("fails closed for %s@%s", (id, version) => {
    const registry = new OutputProjectionRegistry(); registry.register(declaration);
    expect(() => registry.resolve(id, version)).toThrowError(ProjectionRegistryError);
    try { registry.resolve(id, version); } catch (error) {
      expect(error).toMatchObject({ code: "PROJECTION_NOT_REGISTERED", projectionId: id, version });
    }
  });
  it("rejects duplicate registration", () => {
    const registry = new OutputProjectionRegistry(); registry.register(declaration);
    expect(() => registry.register(declaration)).toThrowError(/already registered/);
  });
});
```

- [x] **Step 2: 运行 registry 测试确认失败**

Run: `npm --prefix frontend test -- src/runtime/projection/registry.test.ts`

Expected: FAIL，诊断包含 `Cannot find module './registry'`。

- [x] **Step 3: 实现 fail-closed registry**

```typescript
// frontend/src/runtime/projection/registry.ts
import type { OutputProjectionDeclaration } from "./types";

export class ProjectionRegistryError extends Error {
  readonly code = "PROJECTION_NOT_REGISTERED";
  constructor(readonly projectionId: string, readonly version: string) {
    super(`projection not registered: ${projectionId}@${version}`);
    this.name = "ProjectionRegistryError";
  }
}

export class OutputProjectionRegistry {
  private readonly declarations = new Map<string, OutputProjectionDeclaration>();
  register(declaration: OutputProjectionDeclaration): void {
    const key = this.key(declaration.projectionId, declaration.version);
    if (this.declarations.has(key)) throw new Error(`projection already registered: ${key}`);
    this.declarations.set(key, declaration);
  }
  resolve(projectionId: string, version: string): OutputProjectionDeclaration {
    const declaration = this.declarations.get(this.key(projectionId, version));
    if (!declaration) throw new ProjectionRegistryError(projectionId, version);
    return declaration;
  }
  private key(projectionId: string, version: string): string { return `${projectionId}@${version}`; }
}
```

- [x] **Step 4: 运行 registry 测试**

Run: `npm --prefix frontend test -- src/runtime/projection/registry.test.ts`

Expected: PASS，4 个 case 全部通过。

- [x] **Step 5: Commit versioned projection registry**

```bash
git add frontend/src/runtime/projection/registry.ts frontend/src/runtime/projection/registry.test.ts
git commit -m "feat(projection): add versioned projection registry"
```

---

### Task 3: 扩展 PlanExecutor 保留并恢复成功节点数据

**Covers:** 3.1、3.2

**Files:**
- Modify: `frontend/src/runtime/plan-executor/types.ts`
- Modify: `frontend/src/runtime/plan-executor/plan-executor.ts`
- Modify: `frontend/src/runtime/durable/types.ts`
- Modify: `frontend/src/runtime/plan-executor/plan-executor.test.ts`
- Modify: `frontend/src/runtime/plan-executor/plan-executor-recovery.test.ts`
- Produces: `NodeFactRecord`、`PlanExecutorResult.succeededNodeResults`

- [x] **Step 1: 写失败测试，要求新执行保留 data/parameters/time 且旧结果字段不变**

```typescript
it("exposes succeeded node data without changing legacy result semantics", async () => {
  const store = new JsonlRunStore(dir, "worker-A"); await store.save("run-1", seed("run-1"));
  const gateway = new FakeGateway();
  gateway.setExecuteResult("MM.Inventory.GetAvailability", {
    success: true, traceId: "gw-inv", data: { availableQuantity: 7, dataAsOf: "2026-08-04T00:00:00Z" },
  });
  const result = await new PlanExecutor(store, gateway, "worker-A").execute(singleReadNodeGraph(), "run-1", SNAP);
  expect(result.succeeded).toEqual(["node.inv"]);
  expect(result.succeededNodeResults).toEqual([expect.objectContaining({
    nodeId: "node.inv", capabilityId: "MM.Inventory.GetAvailability",
    parameters: { material: "M1", plant: "5300" }, producesFactTypes: ["InventoryAvailability"],
    gatewayTraceId: "gw-inv", executeData: { availableQuantity: 7, dataAsOf: "2026-08-04T00:00:00Z" },
    nodeExecutedAt: expect.any(String),
  })]);
  expect(result.nodeLedger["node.inv"].resultRef).toBe("gw-inv");
  expect(result.failed).toEqual([]); expect(result.timedOut).toEqual([]);
});
```

在 recovery test 增加：首次执行后新建 executor 再执行，第二次 `succeededNodeResults` 与第一次深相等，且 Gateway 调用数不增加。

- [x] **Step 2: 运行两个 executor 测试文件确认失败**

Run: `npm --prefix frontend test -- src/runtime/plan-executor/plan-executor.test.ts src/runtime/plan-executor/plan-executor-recovery.test.ts`

Expected: FAIL，`succeededNodeResults` 为 `undefined`。

- [x] **Step 3: 扩展类型和 idempotency payload**

```typescript
// add to plan-executor/types.ts
export type NodeFactRecord = {
  nodeId: string; agentTraceId: string; capabilityId: string; parameters: Record<string, string>;
  producesFactTypes: string[]; gatewayTraceId: string;
  executeData: Record<string, unknown>; nodeExecutedAt: string;
};
// add to PlanExecutorResult
succeededNodeResults: NodeFactRecord[];

// add optional fields to WorkbenchOutcome in durable/types.ts
data?: Record<string, unknown>;
parameters?: Record<string, string>;
capabilityId?: string;
producesFactTypes?: string[];
nodeExecutedAt?: string;
```

- [x] **Step 4: 修改 executor，使 transition 返回 entry，并在 fresh/cache/old-cache 路径构造同形记录**

在 `execute()` 内创建局部 `const nodeResults = new Map<string, NodeFactRecord>()`，传给 `executeNode()`；成功 transition 返回的 `entry.updatedAt` 是唯一 `nodeExecutedAt`。`markExecuted` payload 写入：

```typescript
const record: NodeFactRecord = {
  nodeId, agentTraceId: runId, capabilityId: node.capabilityId, parameters,
  producesFactTypes: [...node.producesFactTypes], gatewayTraceId: executeResult.traceId ?? "",
  executeData: executeResult.data ?? {}, nodeExecutedAt: succeededEntry.updatedAt,
};
nodeResults.set(nodeId, record);
await this.store.markExecuted(idempotencyKey, {
  status: "succeeded", gatewayTraceId: record.gatewayTraceId, data: record.executeData,
  parameters: record.parameters, capabilityId: record.capabilityId,
  producesFactTypes: record.producesFactTypes, nodeExecutedAt: record.nodeExecutedAt,
});
```

把 `existing?.state === SUCCEEDED` 检查移到 idempotency lookup 之后，并明确分支顺序：若 ledger 已是 `SUCCEEDED`，则只在 cache 字段完整时重建 map，随后立即 return（不得再走 `SUCCEEDED -> READY`）；若 ledger 尚未成功但 cache 命中，则维持既有 `VALIDATING -> EXECUTING -> SUCCEEDED` replay 转换，并用 cache 中原始 `nodeExecutedAt` 重建 map；仅无 cache 时调用 Gateway。当 cache 同时具备 `data`、`parameters`、`capabilityId`、`producesFactTypes`、`nodeExecutedAt` 时才填入 map，旧格式 cache 或仅有 ledger 的历史 run 保持 succeeded 但不伪造数据。`emptyResult()` 返回空数组；`buildResult()` 接收 map，并按 `nodeId` 排序输出：

```typescript
succeededNodeResults: [...nodeResults.values()].sort((a, b) => a.nodeId.localeCompare(b.nodeId)),
```

- [x] **Step 5: 运行 executor 定向回归和完整 frontend typecheck**

Run: `npm --prefix frontend test -- src/runtime/plan-executor/plan-executor.test.ts src/runtime/plan-executor/plan-executor-recovery.test.ts && npm --prefix frontend run typecheck`

Expected: PASS；原有状态、取消、超时、依赖、lease 测试不改断言仍通过，新 recovery case 证明不重呼 Gateway。

- [x] **Step 6: Commit executor projection data retention**

```bash
git add frontend/src/runtime/durable/types.ts frontend/src/runtime/plan-executor/types.ts frontend/src/runtime/plan-executor/plan-executor.ts frontend/src/runtime/plan-executor/plan-executor.test.ts frontend/src/runtime/plan-executor/plan-executor-recovery.test.ts
git commit -m "feat(plan-executor): retain succeeded node projection data"
```

---

### Task 4: 实现 FactBuilderRegistry 与 ProjectionInputAssembler

**Covers:** 4.1、4.2、4.3、4.4，以及缺 FactBuilder graceful degradation

**Files:**
- Create: `frontend/src/runtime/projection/fact-builder.ts`
- Create: `frontend/src/runtime/projection/fact-builder.test.ts`
- Create: `frontend/src/runtime/projection/assembler.ts`
- Create: `frontend/src/runtime/projection/assembler.test.ts`
- Modify: `frontend/src/runtime/projection/types.ts`（`FactBuilderDeclaration<NodeFactRecord>` 改为唯一具体类型）
- Review fix modify: `frontend/src/runtime/plan-executor/types.ts`
- Review fix modify: `frontend/src/runtime/plan-executor/plan-executor.ts`
- Review fix modify: `frontend/src/runtime/plan-executor/plan-executor.test.ts`
- Review fix modify: `frontend/src/runtime/plan-executor/plan-executor-recovery.test.ts`
- Consumes: `PlanExecutorResult.succeededNodeResults`
- Produces: `FactBuilderRegistry.resolve()`、`createMaterialSupplyFactBuilderRegistry()`、`ProjectionInputAssembler.assemble(result, registry): ProjectionInput`

- [x] **Step 1: 写失败测试覆盖双 READ、freshness 回退、非成功排除和 missing builder**

测试 fixture 固定两个 `NodeFactRecord`：inventory data 为 `{ availableQuantity: 7, unit: "EA", dataAsOf: "2026-08-04T00:00:00Z" }`，PO data 为 `{ purchaseOrders: [{ purchaseOrder: "4500001", orderQuantity: 2, purchaseOrderUnit: "EA" }], dataAsOf: "2026-08-04T00:00:00Z" }`。断言：

```typescript
const input = new ProjectionInputAssembler().assemble(result, createMaterialSupplyFactBuilderRegistry());
expect(input.facts.map((fact) => fact.source.factType)).toEqual(["InventoryAvailability", "PurchaseOrder"]);
expect(input.facts.every((fact) => fact.asOf === "2026-08-04T00:00:00Z")).toBe(true);
expect(input.planExecutionRecord.nodeLedgerSummary).toContainEqual({ nodeId: "node.failed", state: "FAILED" });
expect(input.facts.some((fact) => fact.source.nodeId === "node.failed")).toBe(false);
```

另建 unknown capability 的 succeeded record，断言无 fact，且 `missingFacts` 为 `[{ factType: "InventoryAvailability", reason: "no_fact_builder" }]`；删除 `dataAsOf` 后断言 fact `asOf === nodeExecutedAt`。

- [x] **Step 2: 运行 builder/assembler 测试确认失败**

Run: `npm --prefix frontend test -- src/runtime/projection/fact-builder.test.ts src/runtime/projection/assembler.test.ts`

Expected: FAIL，两个模块均不存在。

- [x] **Step 3: 实现 registry 和两个 capability-specific builder**

`FactBuilderRegistry.register()` 拒绝重复 capability；`resolve()` 对未知 capability 返回 `null`。builder 统一用 `freshness(record, "dataAsOf")`，只读取白名单字段并产生稳定 factId `${nodeId}:${predicate}:${index}`；`source` 固定包含 `{ nodeId, capabilityId, factType }`，`gatewayTraceId` 来自 record。inventory builder 仅在 numeric `availableQuantity` 时产一条 `availableQuantity` fact；PO builder 遍历 `purchaseOrders`（含 header `items[]` 与 flat shape），稳定按 `purchaseOrder/material/plant` 排序后产 `purchaseOrderItem` facts。

```typescript
// replace Task 1's generic declaration in projection/types.ts
import type { NodeFactRecord } from "../plan-executor/types";
export type FactBuilderDeclaration = {
  capabilityId: string; freshnessField?: string;
  build(record: NodeFactRecord): ReasoningFact[];
};

export class FactBuilderRegistry {
  private readonly builders = new Map<string, FactBuilderDeclaration>();
  register(builder: FactBuilderDeclaration): void {
    if (this.builders.has(builder.capabilityId)) throw new Error(`fact builder already registered: ${builder.capabilityId}`);
    this.builders.set(builder.capabilityId, builder);
  }
  resolve(capabilityId: string): FactBuilderDeclaration | null { return this.builders.get(capabilityId) ?? null; }
}

function dataAsOf(record: NodeFactRecord, field = "dataAsOf"): string {
  const value = record.executeData[field];
  return typeof value === "string" && value.length > 0 ? value : record.nodeExecutedAt;
}
```

`createMaterialSupplyFactBuilderRegistry()` 注册 `MM.Inventory.GetAvailability` 和 `MM.PurchaseOrder.GetList`，两项均显式声明 `freshnessField: "dataAsOf"`。

- [x] **Step 4: 实现 assembler，输入签名不允许 conversation/model/raw payload 参数**

```typescript
export class ProjectionInputAssembler {
  assemble(result: PlanExecutorResult, builders: FactBuilderRegistry): ProjectionInput {
    const facts: ReasoningFact[] = [];
    const missingFacts: MissingFact[] = [];
    for (const record of [...result.succeededNodeResults].sort((a, b) => a.nodeId.localeCompare(b.nodeId))) {
      const builder = builders.resolve(record.capabilityId);
      if (!builder) {
        for (const factType of record.producesFactTypes) missingFacts.push({ factType, reason: "no_fact_builder" });
        continue;
      }
      facts.push(...builder.build(record));
    }
    const failedNodes = [...result.failed, ...result.timedOut, ...result.cancelled].sort();
    const asOf = facts.map((fact) => fact.asOf).sort()[0] ?? "";
    return { facts, planExecutionRecord: {
      runId: result.runId, snapshotId: result.snapshotId, asOf,
      succeededNodes: [...result.succeeded].sort(), failedNodes, missingFacts,
      nodeLedgerSummary: Object.entries(result.nodeLedger).sort(([a], [b]) => a.localeCompare(b)).map(([nodeId, entry]) => ({
        nodeId, state: entry.state, ...(entry.state === "SUCCEEDED" ? { nodeExecutedAt: entry.updatedAt } : {}),
      })),
    } };
  }
}
```

- [x] **Step 5: 运行 builder/assembler tests 与 typecheck**

Run: `npm --prefix frontend test -- src/runtime/projection/fact-builder.test.ts src/runtime/projection/assembler.test.ts && npm --prefix frontend run typecheck`

Expected: PASS；测试证明 only-succeeded、双时间戳回退、missing builder 和隔离签名。

- [x] **Step 6: Commit fact builders and assembler**

```bash
git add frontend/src/runtime/projection/types.ts frontend/src/runtime/projection/fact-builder.ts frontend/src/runtime/projection/fact-builder.test.ts frontend/src/runtime/projection/assembler.ts frontend/src/runtime/projection/assembler.test.ts
git commit -m "feat(projection): assemble normalized facts from executor results"
```

- [x] **Step 7: 写 reviewer-fix RED tests**

在 executor fresh/restart tests 断言 `NodeFactRecord.agentTraceId === runId` 且不等于 `gatewayTraceId`；在 builder tests 增加 decimal string、`NaN`、`Infinity`、非法 string，以及相同 `purchaseOrder/material/plant` 不同 item/quantity 的 reversed-input permutation：

```typescript
expect(replayed.succeededNodeResults[0]).toMatchObject({ agentTraceId: "run-1" });
expect(decimalFact.value).toBe(1);
expect(decimalFact.evidence[0].orderQuantity).toBe("1.000");
expect(buildFacts([...rows].reverse())).toEqual(buildFacts(rows));
expect(facts.every((fact) => fact.agentTraceId === "run-1" && fact.traceId === "run-1")).toBe(true);
```

- [x] **Step 8: 运行 reviewer-fix tests 确认失败**

Run: `npm --prefix frontend test -- src/runtime/plan-executor/plan-executor.test.ts src/runtime/plan-executor/plan-executor-recovery.test.ts src/runtime/projection/fact-builder.test.ts src/runtime/projection/assembler.test.ts`

Expected: FAIL；缺 `agentTraceId`、空 fact traces、decimal string value 为 `null` 或 reversed permutation 不一致，且失败均对应 reviewer finding。

- [x] **Step 9: 实现 run correlation 与确定性 PO normalization**

`NodeFactRecord.agentTraceId` 在 fresh、cache replay、existing-`SUCCEEDED` hydration 中统一使用当前 `execute(..., runId, ...)` 的 `runId`；无需新增 cache 字段。FactBuilder 将 `agentTraceId`/`traceId` 设为 record 的 agent trace。PO quantity 用显式 finite-decimal parser 归一，evidence 保留原始白名单 scalar；排序 key 包含 item、normalized quantity、unit 和 canonical whitelisted row，形成 total order。

- [x] **Step 10: 运行 reviewer-fix GREEN 与完整 frontend verify**

Run: `npm --prefix frontend test -- src/runtime/plan-executor/plan-executor.test.ts src/runtime/plan-executor/plan-executor-recovery.test.ts src/runtime/projection/fact-builder.test.ts src/runtime/projection/assembler.test.ts && npm --prefix frontend run verify`

Expected: focused tests PASS；frontend typecheck、全部 Vitest 和 production build PASS；无空 agent trace、raw payload leak 或 Runbook 16 回归。

- [x] **Step 11: Commit Task 4 review fixes**

```bash
git add frontend/src/runtime/plan-executor/types.ts frontend/src/runtime/plan-executor/plan-executor.ts frontend/src/runtime/plan-executor/plan-executor.test.ts frontend/src/runtime/plan-executor/plan-executor-recovery.test.ts frontend/src/runtime/projection/fact-builder.ts frontend/src/runtime/projection/fact-builder.test.ts frontend/src/runtime/projection/assembler.test.ts
git commit -m "fix(projection): preserve fact correlation and ordering"
```

- [x] **Step 12: 写第三轮 reviewer-fix RED tests，锁定显式降级、PO precedence 与 freshness epoch**

在 executor fresh/cache/existing-`SUCCEEDED` tests 中分别覆盖 missing 与 blank Gateway trace，断言成功节点仍保留 nullable record、cache 路径不重调 Gateway；在 assembler/builder tests 中覆盖 `missing_gateway_trace`、item 字段存在优先、非法 freshness 回退及跨 offset epoch 排序：

```typescript
expect(result.succeeded).toEqual(["node.inv"]);
expect(result.succeededNodeResults).toEqual([
  expect.objectContaining({ nodeId: "node.inv", gatewayTraceId: null }),
]);
expect(gateway.executeCalls).toHaveLength(0);

expect(input.facts).toEqual([]);
expect(input.planExecutionRecord.missingFacts).toEqual([
  { factType: "InventoryAvailability", reason: "missing_gateway_trace" },
]);

expect(itemQuantityFact.value).toBeNull();
expect(itemQuantityFact.evidence[0].orderQuantity).toBe("");
expect(itemQuantityFact.evidence[0].orderQuantity).not.toBe("12");

expect(malformedFreshnessFact.asOf).toBe(nodeExecutedAt);
expect(offsetInput.planExecutionRecord.asOf).toBe("2026-08-03T23:30:00.000Z");
expect(equivalentInstantInput.planExecutionRecord.asOf).toBe("2026-08-04T00:00:00.000Z");
```

- [x] **Step 13: 运行第三轮 reviewer-fix tests 确认目标行为失败**

Run: `npm --prefix frontend test -- src/runtime/plan-executor/plan-executor.test.ts src/runtime/plan-executor/plan-executor-recovery.test.ts src/runtime/projection/fact-builder.test.ts src/runtime/projection/assembler.test.ts`

Expected: FAIL；旧实现会丢弃 missing/blank Gateway trace 的成功 record、允许 item 非法 quantity 回退 header、接受无时区或 malformed `dataAsOf`，或按字符串而非 epoch 选择 aggregate `asOf`。RED 报告必须逐项记录命令和失败摘要。

- [x] **Step 14: 实现 nullable Gateway trace、field-presence precedence 与 ISO-8601 epoch aggregation**

将 `NodeFactRecord.gatewayTraceId` 改为 `string | null`。fresh、cache replay 与 existing-`SUCCEEDED` hydration 对缺失/纯空白 trace 统一写 `null`，但仍保留完整 record，且不改变 `SUCCEEDED`、不重调 Gateway、不用 `runId` 替代。assembler 在 trace 为 `null` 时跳过 builder，并对每个 `producesFactTypes` 写入 `{ reason: "missing_gateway_trace" }`；通过类型收窄使 builder 继续只接收非空 trace record，`ReasoningFact.gatewayTraceId` 保持 `string`。

PO builder 使用 `Object.prototype.hasOwnProperty.call(item, "orderQuantity")` 先选择 item/header 原值，再只归一一次；item 值非法或为空时保留 item evidence、`value = null`，不得回退 header。freshness helper 只接受带 `Z` 或 `+/-HH:mm` 显式时区且 `Date.parse()` 为有限 epoch 的 ISO-8601 string，否则回退 `nodeExecutedAt`；fact 保留选中来源字符串，assembler 按 epoch 取最早 instant，并用 `new Date(minEpoch).toISOString()` 输出 aggregate `asOf`。

- [x] **Step 15: 运行第三轮 GREEN、完整 frontend 与严格 OpenSpec 验证**

Run: `npm --prefix frontend test -- src/runtime/plan-executor/plan-executor.test.ts src/runtime/plan-executor/plan-executor-recovery.test.ts src/runtime/projection/fact-builder.test.ts src/runtime/projection/assembler.test.ts && npm --prefix frontend run verify && git diff --check && comet classic openspec -- validate --all --strict`

Expected: focused tests PASS；frontend typecheck、全部 Vitest 与 production build PASS；diff check PASS；OpenSpec strict validation 20/20 PASS。报告必须包含 RED/GREEN 命令、测试数量、完整验证结果和风险信号。

- [x] **Step 16: Commit Task 4 explicit degradation fixes**

```bash
git add frontend/src/runtime/plan-executor/types.ts frontend/src/runtime/plan-executor/plan-executor.ts frontend/src/runtime/plan-executor/plan-executor.test.ts frontend/src/runtime/plan-executor/plan-executor-recovery.test.ts frontend/src/runtime/projection/types.ts frontend/src/runtime/projection/fact-builder.ts frontend/src/runtime/projection/fact-builder.test.ts frontend/src/runtime/projection/assembler.ts frontend/src/runtime/projection/assembler.test.ts
git commit -m "fix(projection): preserve succeeded-node degradation"
```

- [x] **Step 17: 写第四轮 reviewer-fix RED tests，锁定 calendar validity 与 PO item identity**

在 `frontend/src/runtime/projection/fact-builder.test.ts` 增加非法日历日期回退和 item identity evidence 两组回归：

```typescript
it.each([
  "2026-02-30T00:00:00Z",
  "2025-02-29T00:00:00+08:00",
  "2026-13-01T00:00:00Z",
])("falls back for invalid ISO-8601 calendar freshness: %s", (dataAsOf) => {
  const builder = createMaterialSupplyFactBuilderRegistry().resolve(
    "MM.Inventory.GetAvailability",
  );
  const facts = builder?.build(record({
    executeData: { availableQuantity: 7, dataAsOf },
  }));
  expect(facts?.[0]?.asOf).toBe("2026-08-04T00:00:01Z");
});

it("preserves purchase-order item identity in fact evidence", () => {
  const builder = createMaterialSupplyFactBuilderRegistry().resolve("MM.PurchaseOrder.GetList");
  const build = (purchaseOrderItem: string) => builder?.build(record({
    nodeId: "node.po",
    capabilityId: "MM.PurchaseOrder.GetList",
    producesFactTypes: ["PurchaseOrder"],
    executeData: { purchaseOrders: [{
      purchaseOrder: "4500001", purchaseOrderItem,
      material: "MAT-1", plant: "P1", orderQuantity: 1, purchaseOrderUnit: "EA",
    }] },
  }));
  expect(build("10")?.[0]?.evidence[0]?.purchaseOrderItem).toBe("10");
  expect(build("10")).not.toEqual(build("20"));
});
```

- [x] **Step 18: 运行第四轮 reviewer-fix tests 确认两个 finding 均失败**

Run: `npm --prefix frontend test -- src/runtime/projection/fact-builder.test.ts`

Expected: FAIL；非法日期被旧 freshness helper 接受而未回退，且 PO evidence 缺 `purchaseOrderItem`，两组失败均直接对应 `.superpowers/sdd/task-4-rereview-3.md` 的 Important finding。

- [x] **Step 19: 实现严格 calendar validation 并保留 PO item evidence**

把 freshness regex 改为捕获 year/month/day/hour/minute/second/timezone 的形式；新增纯函数检查 month `1..12`、day 不超过该月天数（闰年规则：`year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0)`）、hour `0..23`、minute/second `0..59`、offset hour `0..23`、offset minute `0..59`，之后才允许 `Date.parse()` 的 finite epoch。不得把 parsed/canonical UTC 替换进 fact `asOf`；合法 source string 仍原样保留，非法值回退 `nodeExecutedAt`。

```typescript
function isLeapYear(year: number): boolean {
  return year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
}

function daysInMonth(year: number, month: number): number {
  const days = [31, isLeapYear(year) ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  return days[month - 1] ?? 0;
}
```

在 PO fact 的白名单 evidence 中加入 `purchaseOrderItem: row.purchaseOrderItem`；不 spread raw row，不改变既有 total-order、quantity precedence 或 factId 规则。

- [x] **Step 20: 运行第四轮 GREEN 与完整验证**

Run: `npm --prefix frontend test -- src/runtime/projection/fact-builder.test.ts && npm --prefix frontend run verify && git diff --check && comet classic openspec -- validate --all --strict`

Expected: focused fact-builder tests PASS；frontend typecheck、全部 Vitest 与 production build PASS；diff check PASS；OpenSpec strict validation 20/20 PASS。报告必须包含第四轮 RED/GREEN 命令和数量，并确认合法 leap-day/offset freshness 仍保留 source string。

- [x] **Step 21: Commit Task 4 strict freshness and item identity fixes**

```bash
git add frontend/src/runtime/projection/fact-builder.ts frontend/src/runtime/projection/fact-builder.test.ts
git commit -m "fix(projection): validate fact source identity"
```

---

### Task 5: 实现确定性 hash 与 MaterialSupplySnapshot projection

**Covers:** 5.1、5.2、5.3、5.4、5.5、5.6、5.7、5.8、5.9

**Files:**
- Create: `frontend/src/runtime/projection/hash.ts`
- Create: `frontend/src/runtime/projection/hash.test.ts`
- Create: `frontend/src/runtime/projection/material-supply-snapshot.ts`
- Create: `frontend/src/runtime/projection/material-supply-snapshot.test.ts`
- Consumes: `ProjectionInput`、`canonicalJson`/`sha256Hex` from `../durable/canonical-json`
- Produces: `computeOutputHash()`、`materialSupplySnapshotProjection`、`createOutputProjectionRegistry()`

- [x] **Step 1: 写 hash 失败测试**

构造两条 facts，分别交换数组顺序、改变 `value`、`version`、`snapshotId`：

```typescript
expect(computeOutputHash([factB, factA], "1.0.0", "snap-1"))
  .toBe(computeOutputHash([factA, factB], "1.0.0", "snap-1"));
expect(computeOutputHash([factA], "1.0.0", "snap-1"))
  .not.toBe(computeOutputHash([{ ...factA, value: 8 }], "1.0.0", "snap-1"));
expect(computeOutputHash([factA], "1.0.0", "snap-1"))
  .not.toBe(computeOutputHash([factA], "1.0.1", "snap-1"));
expect(computeOutputHash([factA], "1.0.0", "snap-1"))
  .not.toBe(computeOutputHash([factA], "1.0.0", "snap-2"));
```

- [x] **Step 2: 运行 hash 测试确认失败，再实现稳定排序和精确拼接规则**

Run: `npm --prefix frontend test -- src/runtime/projection/hash.test.ts`

Expected: FAIL，模块不存在。

```typescript
// frontend/src/runtime/projection/hash.ts
import { canonicalJson, sha256Hex } from "../durable/canonical-json";
import type { ReasoningFact } from "./types";
export function normalizeFacts(facts: ReasoningFact[]): ReasoningFact[] {
  return [...facts].sort((a, b) => {
    const left = [a.businessObject, a.predicate, a.material ?? "", a.plant ?? "", a.factId].join("\u0000");
    const right = [b.businessObject, b.predicate, b.material ?? "", b.plant ?? "", b.factId].join("\u0000");
    return left < right ? -1 : left > right ? 1 : 0;
  });
}
export function computeOutputHash(facts: ReasoningFact[], version: string, snapshotId: string): string {
  return sha256Hex(canonicalJson(normalizeFacts(facts)) + version + snapshotId);
}
```

Run: `npm --prefix frontend test -- src/runtime/projection/hash.test.ts`

Expected: PASS，same case 相同，三类 different case 均不同。

- [x] **Step 3: 写 projection 失败测试覆盖核心裁决**

在 `material-supply-snapshot.test.ts` 使用纯 `ProjectionInput` fixtures，先写以下断言：

- required inventory 与 optional PO facts 均存在、相同 `dataAsOf`、无失败：`complete`、无 limitations；每个输出 fact 的全部字段均有 lineage。
- optional fact 缺失：`partial` + `missing_optional`。
- required fact 缺失或 record 有 FAILED/TIMED_OUT/CANCELLED：`incomplete` + `missingFacts`/`failedNodes`。
- 两节点 `dataAsOf` 不同：保留两条 `sourceFreshness` + `freshness_mismatch`。
- 同逻辑字段不同 unit：`unit_incompatibility`；required 时 `incomplete`。
- 同分组同值：按 `factId` 留一条且无限制；异值：两条均 `conflict: true`、稳定排序、`conflict` limitation；required 时 `incomplete`。
- assembler 的 `no_fact_builder` missing fact：`incomplete` + 同类 limitation。

- [x] **Step 4: 运行 projection 测试确认失败**

Run: `npm --prefix frontend test -- src/runtime/projection/material-supply-snapshot.test.ts`

Expected: FAIL，模块不存在。

- [x] **Step 5: 实现 declaration 和确定性 project pipeline**

`materialSupplySnapshotProjection` 固定：`projectionId="material-supply-snapshot"`、`version="1.0.0"`、`requiredFactTypes=["InventoryAvailability"]`、`optionalFactTypes=["PurchaseOrder"]`、`outputSchema="MaterialSupplySnapshot@1.0.0"`、`timeBasis="dataAsOf"`、`partialPolicy="complete-partial-incomplete"`。这样双 READ 可达 `complete`，inventory-only 可验证 optional 缺失的 `partial`，任一节点失败仍按 §6.1 降为 `incomplete`。`project()` 按此顺序处理：

1. 从 `source.factType` 计算 required/optional 缺失，并合并 `planExecutionRecord.missingFacts`（按 `factType|reason` 去重排序）；required 缺失 reason 固定为 `missing_required`，optional 缺失产生 `missing_optional` limitation，reason 为 `no_fact_builder` 的条目产生同类 limitation。
2. 按 `(businessObject,predicate,material,plant)` 分组；同值同 unit 仅保留 `factId` 最小者；异值保留全部并标 conflict；同值不同 unit 产生 unit incompatibility。若组内任一 fact 的 `source.factType` 属 required，则该 conflict/unit incompatibility 是阻塞项，否则是非阻塞 limitation。
3. `sourceFreshness` 从去重前 input facts 的 `source.nodeId`、对应 ledger `nodeExecutedAt`、fact `asOf` 生成（同 node 去重后按 nodeId 排序），确保 duplicate fact 不会抹掉节点时间；仅 distinct `dataAsOf` 数量大于 1 时产生 freshness mismatch。
4. lineage 为每条输出 fact 的 `factId`、`agentTraceId`、`traceId`、`gatewayTraceId`、`domain`、`businessObject`、`predicate`、`value`、`unit`、`deterministic`、`confidence`、`source`、`evidence`、`material`、`plant`、`asOf` 逐字段生成条目；conflicting fact 另覆盖派生的 `conflict` 字段。`evidence` 使用 `fact.evidence[0] ?? {}`，complete snapshot 的 `lineage.length === facts.length * 16`。
5. failedNodes 只取 FAILED/TIMED_OUT/CANCELLED；blocked 不产 fact但不单独触发 failedNodes。
6. required 缺失、failedNodes 非空、required conflict/unit incompatibility -> incomplete；否则 limitations 非空 -> partial；否则 complete。
7. snapshot 的 `asOf` 直接使用 assembler 已按 epoch 取最早并规范化 UTC 的 `planExecutionRecord.asOf`，不得再次按 fact source string 排序；`outputHash` 严格调用 `computeOutputHash(normalizedInputFacts, version, snapshotId)`。

注册 factory 的完整接口：

```typescript
export function createOutputProjectionRegistry(): OutputProjectionRegistry {
  const registry = new OutputProjectionRegistry();
  registry.register(materialSupplySnapshotProjection);
  return registry;
}
```

- [x] **Step 6: 运行 projection/hash/registry tests**

Run: `npm --prefix frontend test -- src/runtime/projection/hash.test.ts src/runtime/projection/material-supply-snapshot.test.ts src/runtime/projection/registry.test.ts`

Expected: PASS；所有输出数组在输入倒序时仍深相等，且 registry exact resolve 返回首个 projection。

- [x] **Step 7: Commit**

```bash
git add frontend/src/runtime/projection/hash.ts frontend/src/runtime/projection/hash.test.ts frontend/src/runtime/projection/material-supply-snapshot.ts frontend/src/runtime/projection/material-supply-snapshot.test.ts
git commit -m "feat(projection): add deterministic material supply snapshot"
```

---

### Task 6: 完成端到端 Projection Eval 与隔离证明

**Covers:** 6.1、6.2、6.3、6.4、6.5、6.6、6.7、6.8

**Files:**
- Modify: `frontend/src/runtime/projection/assembler.test.ts`
- Modify: `frontend/src/runtime/projection/material-supply-snapshot.test.ts`
- Modify: `frontend/src/runtime/plan-executor/plan-executor.test.ts`
- Produces: component-level executor -> assembler -> registry -> projection evidence

- [x] **Step 1: 写一个双 READ component Eval**

使用真实 `PlanExecutor` + `JsonlRunStore`、可控 `FakeGateway`、真实 builder registry/assembler/output registry。Gateway 返回同一 `dataAsOf` 的 availability 与 purchase orders；执行：

```typescript
const result = await executor.execute(dualReadGraph(), "run-projection-eval", SNAP);
const input = new ProjectionInputAssembler().assemble(result, createMaterialSupplyFactBuilderRegistry());
const projection = createOutputProjectionRegistry().resolve("material-supply-snapshot", "1.0.0");
const snapshot = projection.project(input);
expect(snapshot.completeness).toBe("complete");
expect(snapshot.limitations).toEqual([]);
expect(new Set(snapshot.lineage.map((item) => item.factId)))
  .toEqual(new Set(snapshot.facts.map((fact) => fact.factId)));
```

- [x] **Step 2: 增加 bad-case Eval table 和 projection 隔离编译契约**

用 `it.each` 输入明确 fixtures 覆盖 incomplete、partial、freshness mismatch、unit incompatibility、duplicate/conflict；hash same/different 已由 Task 5 的 dedicated test 覆盖。隔离测试只向 `project({ planExecutionRecord, facts })` 传值，并用 `@ts-expect-error` 证明 `rawGatewayPayload`、`conversationText`、`modelOutput` 不是 `ProjectionInput` 字段：

```typescript
// @ts-expect-error raw payload is outside the projection boundary
projection.project({ planExecutionRecord, facts, rawGatewayPayload: {} });
```

该调用放在 `if (false)` 内，避免测试运行时执行，只由 `tsc --noEmit` 验证 excess-property error 确实存在。

- [x] **Step 3: 运行全部 projection Eval 与 executor 回归**

Run: `npm --prefix frontend test -- src/runtime/projection src/runtime/plan-executor`

Expected: PASS；projection 全场景与 Runbook 16 executor 全部通过。

- [x] **Step 4: 运行 typecheck 证明隔离断言有效**

Run: `npm --prefix frontend run typecheck`

Expected: PASS；若 `@ts-expect-error` 变成 unused directive，则 FAIL，说明 projection 边界被意外放宽。

- [x] **Step 5: Commit projection Eval coverage**

```bash
git add frontend/src/runtime/projection/assembler.test.ts frontend/src/runtime/projection/material-supply-snapshot.test.ts frontend/src/runtime/plan-executor/plan-executor.test.ts
git commit -m "test(projection): cover output projection evaluation matrix"
```

---

### Task 7: 全量相关验证与 OpenSpec 任务收口

**Covers:** 7.1、7.2；并复核 1.1-6.8 共 32 项

**Files:**
- Modify: `openspec/changes/sap-nexus-output-projection-registry/tasks.md`

- [ ] **Step 1: 运行项目规定的 frontend verify**

Run: `npm --prefix frontend run verify`

Expected: `tsc --noEmit`、全部 Vitest、Next.js production build 均 PASS；输出不得有 failed test 或 build error。

- [ ] **Step 2: 运行严格 OpenSpec 验证**

Run: `openspec validate --all --strict`

Expected: exit code 0，authoritative validation summary 无 error；非阻塞 telemetry DNS/flush 信息不算 spec failure。

- [ ] **Step 3: 检查 diff 与边界**

Run: `git diff --check && git status --short && git diff --name-only`

Expected: `git diff --check` 无输出；改动仅包含本计划列出的 projection、plan-executor、durable type、test 与当前 change 文件，不含 `.env`、runtime trace、生产 orchestrator 或 `projectionRef` 接线。

- [ ] **Step 4: 在 tasks.md 勾选已由命令和测试证明的全部 32 项**

把 `openspec/changes/sap-nexus-output-projection-registry/tasks.md` 中 1.1-7.2 的 `- [ ]` 全部改为 `- [x]`；若任一项没有对应 PASS evidence，保留未勾选并回到对应任务修复。

- [ ] **Step 5: Commit OpenSpec task closeout**

```bash
git add openspec/changes/sap-nexus-output-projection-registry/tasks.md
git commit -m "chore(openspec): complete output projection registry change"
```

---

## Coverage Matrix

| OpenSpec tasks | 实现/验证位置 |
|---|---|
| 1.1-1.4 | Task 1：`types.ts` 与 typecheck |
| 2.1-2.3 | Task 2：registry exact resolve / structured fail-closed tests |
| 3.1-3.2 | Task 3：executor data retention、cache recovery、Runbook 16 regression |
| 4.1-4.4 | Task 4：FactBuilder + assembler tests |
| 5.1-5.9 | Task 5：hash、snapshot deterministic policy、registry registration |
| 6.1-6.8 | Task 6：component Eval matrix 与 compile-time isolation |
| 7.1-7.2 | Task 7：frontend verify 与 strict OpenSpec validation |

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-08-04-sap-nexus-output-projection-registry.md`. Two execution options:

1. **Subagent-Driven (recommended)** - 使用 `superpowers:subagent-driven-development`，每个 task 分派 fresh subagent，并在 task 间做 spec/compliance 与 code-quality 两阶段 review。
2. **Inline Execution** - 使用 `superpowers:executing-plans`，在当前 session 分批执行并设置 review checkpoints。

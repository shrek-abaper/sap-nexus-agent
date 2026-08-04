---
comet_change: sap-nexus-output-projection-registry
role: technical-design
canonical_spec: openspec
---

# Output Projection Registry 技术设计（sap-nexus-output-projection-registry）

## Document Version

| Field | Value |
|---|---|
| Change | `sap-nexus-output-projection-registry` |
| Runbook | 17 - Composite Fact and Output Projection |
| Date | 2026-08-04 |
| Depends On | Runbook 16 (READ PlanExecutor) |
| Unblocks | Runbook 18 (Recommendation) |
| Status | draft |

## 1. Context

Runbook 16 在 TS 侧（`frontend/src/runtime/plan-executor/`）实现了 READ-only PlanExecutor：消费 PlanGraph v2 `readPartition`，按 ready-node 调度，产出 `PlanExecutorResult`（节点账本 + `succeeded/failed/timedOut/cancelled/blocked` 列表）。`PlanGraphV2.projectionRef: unknown[]` 是预留空占位符。

**核心缺口（深度勘察发现）**：`executeNode` 成功后仅把 `executeResult.traceId` 存为 `resultRef`，并经 `store.markExecuted(idempotencyKey, { status, gatewayTraceId })` 持久化--`GatewayExecuteResult.data`（业务数据如 `availableQuantity`）被丢弃。因此投影无法仅从 ledger 重建 `ReasoningFact[]`。Python 侧 `build_availability_fact` 是能力专属构建器（知道取 `availableQuantity` 字段），TS 侧无等价物。

本轮补齐 `ReasoningFact[] -> MaterialSupplySnapshot` 投影链路。生产 orchestrator 接线仍 deferred（与 Runbook 16 边界一致），本轮在 component + Eval 层验证。open 阶段 `design.md` 给出高层框架；本 Design Doc 是深度技术细化。

## 2. Goals / Non-Goals

**Goals**
- 版本化 `OutputProjection` 注册表 + 校验（projection 声明 required/optional FactType、output schema、time basis、partial policy）。
- `MaterialSupplySnapshot` 首个注册 projection（组合事实束）。
- 投影输入组装：`PlanExecutorResult` + 节点级 Gateway 结果 -> `PlanExecutionRecord + successful ReasoningFact[]`。
- partial/incomplete/lineage/freshness/limitations 确定性 policy。
- 确定性输出 hash。
- projection Eval（frontend 测试）。

**Non-Goals**
- 不接入生产 orchestrator；`projectionRef` 生产绑定随 orchestrator deferred。
- 不形成 Action / Recommendation（Runbook 18）；不计算采购数量/日期/采购组；不调用 LLM；不接 Knowledge/RAG。
- 不做多 WRITE / Saga / 自动补偿；不做单位换算。

## 3. 模块结构（方案 1：聚合 projection/ 模块）

```
frontend/src/runtime/
├── plan-executor/                    ◀── 原地扩展（read-plan-executor 修改）
│   ├── types.ts                      + NodeFactRecord; PlanExecutorResult.succeededNodeResults
│   ├── plan-executor.ts              + 成功节点保留 executeData + nodeExecutedAt
│   └── (node-ledger/dag-scheduler/...) 不改
└── projection/                       ◀── 新模块（output-projection 能力）
    ├── types.ts                      ReasoningFact / PlanExecutionRecord / MaterialSupplySnapshot
    │                                 OutputProjectionDeclaration / NodeFactRecord / FactBuilderDeclaration
    ├── fact-builder.ts               FactBuilderRegistry（per-capability builder + freshnessField）
    ├── assembler.ts                  ProjectionInputAssembler
    ├── registry.ts                   OutputProjectionRegistry（register/resolve @version，fail-closed）
    ├── material-supply-snapshot.ts   首个 projection
    ├── hash.ts                       确定性 hash
    └── *.test.ts                     Eval
```

理由：整条 pipeline（data -> facts -> PlanExecutionRecord -> projection -> snapshot）是一个内聚数据流，co-locate 镜像 `plan-executor/` 模式；FactBuilder 属投影输入非执行关注点；change 边界最小。

## 4. 数据流

```
PlanExecutor.execute()
  └─ SUCCEEDED node ─> 保留 NodeFactRecord { nodeId, capabilityId, parameters, executeData, nodeExecutedAt }
                        （idempotency cache 扩展持久化 + succeededNodeResults 暴露；向后兼容）
                                        │
                                        ▼
ProjectionInputAssembler.assemble(planExecutorResult, factBuilderRegistry)
  ├─ SUCCEEDED 节点 ─> FactBuilder.build(nodeFactRecord) ─> ReasoningFact[]
  │     └─ asOf = executeData[freshnessField] ?? nodeExecutedAt
  ├─ FAILED/TIMED_OUT/CANCELLED ─> 记入 nodeLedgerSummary，不产 fact
  └─ 产出 { planExecutionRecord, facts }
                                        │
                                        ▼
OutputProjectionRegistry.resolve("material-supply-snapshot", "1.0.0")
  └─ MaterialSupplySnapshot.project({ planExecutionRecord, facts })
       ├─ completeness 三态裁决
       ├─ lineage：每输出字段 -> source fact/evidence
       ├─ sourceFreshness：per-node { nodeId, nodeExecutedAt, dataAsOf }
       ├─ conflicts：同 predicate 异值 -> 保留双方 + conflict 标记 + limitation
       ├─ missingFacts / failedNodes / limitations 填充
       └─ outputHash = hash(normalized facts, version, snapshotId)
                                        │
                                        ▼
                              MaterialSupplySnapshot
```

## 5. 核心类型（TS）

```ts
// 镜像 Python reasoning_fact.py，新增 asOf
type ReasoningFact = {
  factId: string; agentTraceId: string; traceId: string; gatewayTraceId: string;
  domain: string; businessObject: string; predicate: string;
  value: number | null; unit: string | null;
  deterministic: boolean; confidence: number;
  source: Record<string, unknown>; evidence: Record<string, unknown>[];
  material: string | null; plant: string | null;
  asOf: string;            // dataAsOf（能力专属新鲜度字段，缺失回退 nodeExecutedAt）
};

type NodeFactRecord = {           // executor 扩展保留
  nodeId: string; capabilityId: string;
  parameters: Record<string, string>;
  executeData: Record<string, unknown>;  // 保留的 GatewayExecuteResult.data
  nodeExecutedAt: string;                 // ledger updatedAt
};

type PlanExecutionRecord = {
  runId: string; snapshotId: string;
  nodeLedgerSummary: { nodeId: string; state: NodeState; nodeExecutedAt?: string }[];
  asOf: string;                   // snapshot 级 asOf（min dataAsOf across facts）
};

type SnapshotFact = ReasoningFact & { conflict?: boolean };

type MaterialSupplySnapshot = {
  projectionId: string; projectionVersion: string; snapshotId: string;
  asOf: string;
  sourceFreshness: { nodeId: string; nodeExecutedAt: string; dataAsOf: string }[];
  completeness: "complete" | "partial" | "incomplete";
  facts: SnapshotFact[];
  lineage: { field: string; factId: string; evidence: Record<string, unknown> }[];
  missingFacts: { factType: string; reason: string }[];
  failedNodes: string[];
  limitations: { kind: "freshness_mismatch" | "unit_incompatibility" | "conflict" | "missing_optional" | "no_fact_builder"; detail: string }[];
  outputHash: string;
};

type OutputProjectionDeclaration = {
  projectionId: string; version: string;
  requiredFactTypes: string[]; optionalFactTypes: string[];
  timeBasis: "dataAsOf";
  project: (input: { planExecutionRecord: PlanExecutionRecord; facts: ReasoningFact[] }) => MaterialSupplySnapshot;
};

type FactBuilderDeclaration = {
  capabilityId: string;
  build: (record: NodeFactRecord) => ReasoningFact[];
  freshnessField?: string;        // executeData 中的新鲜度字段路径，缺失回退 nodeExecutedAt
};
```

## 6. 确定性规则

### 6.1 Completeness 三态

| 态 | 条件 |
|---|---|
| `complete` | 所有 required FactType 有干净 fact + 无 failedNodes + 无 limitation |
| `partial` | 非 incomplete，且（optional 缺失 OR 存在非阻塞 limitation：freshness_mismatch / optional 冲突 / optional 单位不兼容 / missing_optional） |
| `incomplete` | 任一 required FactType 缺失 OR 任一节点 FAILED/TIMED_OUT/CANCELLED OR required fact 命中 conflict/单位不兼容 |

`freshness_mismatch` limitation **仅当 ≥2 节点 `dataAsOf` 不同**时产生。双 READ 若 `dataAsOf` 相同（如同一业务日期）-> 无 limitation -> 可达 `complete`（测试可控）。

### 6.2 Lineage

每个输出 fact 字段在 `lineage` 中有 `{ field, factId, evidence }` 条目，追溯到 source `ReasoningFact` 及其 evidence。`complete` snapshot 的 lineage 覆盖率 = 100%。

### 6.3 Freshness（双时间戳）

- `sourceFreshness` 恒携带 per-node `{ nodeId, nodeExecutedAt, dataAsOf }`。
- `dataAsOf = executeData[freshnessField]`（FactBuilder 声明，存在时）?? `nodeExecutedAt`（回退）。
- `freshness_mismatch` limitation IFF ≥2 节点 `dataAsOf` 值不同；保留各自时间，不合并。

### 6.4 Conflict（保留双方）

- 按 `(businessObject, predicate, material, plant)` 分组。
- 同 predicate + 同值 -> 去重保留一份（按 `factId` 稳定排序），无 limitation。
- 同 predicate + 异值 -> 两者都保留进 `facts`（按 `factId` 稳定排序），标 `conflict: true`，产 `conflict` limitation；若该 predicate 属 required -> `incomplete`。投影不选真值，透明呈现供 narrator 叙述。

### 6.5 Unit incompatibility

同逻辑字段不同单位且无版本化转换规则 -> 记 `unit_incompatibility` limitation，该字段排除出 `complete` 计量；required -> `incomplete`，optional -> `partial`。投影不做单位换算（non-goal）。

### 6.6 Determinism hash

- `normalize`：facts 按 `(businessObject, predicate, material, plant, factId)` 排序 -> canonical JSON。
- `outputHash = sha256(canonical(normalized facts) + projectionVersion + snapshotId)`。
- 相同输入 -> 相同 hash；fact 值 / version / snapshotId 任一不同 -> 不同 hash。

## 7. 错误处理 / fail-closed

- 未知 `projectionId@version` -> fail-closed，结构化失败，不产 snapshot。
- 缺 FactBuilder（capabilityId 未注册）-> 该节点不贡献 fact，其 required FactType 进 `missingFacts`（reason: `no_fact_builder`）-> 降级 `incomplete`，不崩溃（graceful degradation）。
- 投影隔离：`project()` 签名只接收 `{ planExecutionRecord, facts }`，类型层面无法访问 raw Gateway payload / conversation / model output。
- executor 扩展向后兼容：新增 `succeededNodeResults` 字段，不改 `nodeLedger` / `succeeded` / `failed` 等已有字段语义与状态机。

## 8. executor 扩展细节

`executeNode` 成功分支当前：
```ts
await this.transition(..., NS.SUCCEEDED, attempt, inputHash, executeResult.traceId ?? null);
await this.store.markExecuted(idempotencyKey, { status: "succeeded", gatewayTraceId: executeResult.traceId ?? null });
```

扩展为保留 `executeData` + `nodeExecutedAt`：
- `markExecuted` payload 增补 `{ data: executeResult.data, parameters, capabilityId, nodeExecutedAt }`（idempotency cache 持久化，recovery 时可重建）。
- executor 维护 `nodeResults: Map<nodeId, NodeFactRecord>`，成功时填入，最终汇入 `PlanExecutorResult.succeededNodeResults`。
- idempotent replay 分支（`cachedResult` 命中）从 cache 重建 `NodeFactRecord`，保证 recovery 一致。
- `NodeLedgerEntry` 不改（仍存 `resultRef=traceId`）；data 保留是并行的旁路结构，不污染状态机。

## 9. 测试策略（Eval）

1. complete：双 READ 成功 + 同 dataAsOf + lineage 100% + hash 确定性
2. incomplete：单节点 FAILED -> missingFacts + failedNodes
3. partial：optional 缺失 -> limitation
4. freshness mismatch：异 dataAsOf -> sourceFreshness 保留双方 + limitation
5. unit incompatibility：limitation + 排除 complete
6. conflict：同 predicate 异值 -> 保留双方 + conflict 标记 + limitation + required 则 incomplete
7. 确定性 hash：same->same / different->different
8. 隔离：projection 仅收 normalized facts + ledger metadata
9. fail-closed：未知 projectionId@version
10. executor 回归：Runbook 16 套件不改动通过

验证命令：`npm --prefix frontend run verify` + `openspec validate --all --strict`。

## 10. Spec Patch（回写 delta spec）

回写 `specs/output-projection/spec.md`：
1. conflict 场景细化：当前 "applies a deterministic resolution" 模糊 -> "保留双方 + conflict 标记 + limitation，required 则 incomplete"。
2. complete 场景补充前提：无 freshness mismatch（dataAsOf 一致）。
3. 新增 "缺 FactBuilder 降级" 场景：missingFacts reason=`no_fact_builder` + incomplete。

## 11. Risks / Trade-offs

- [executor 丢弃 data] -> 扩展 idempotency cache payload + 旁路 nodeResults，向后兼容。
- [TS ReasoningFact 镜像漂移] -> 镜像最小契约 + asOf；Python 侧运行时不变。
- [complete 可达性] -> freshness_mismatch 仅 dataAsOf 不同才触发；测试设同 dataAsOf 验证 complete。
- [生产 orchestrator deferred] -> component/Eval 层验证；生产接线后续 runbook。
- [FactBuilder 注册缺口] -> 降级 missingFacts + incomplete，不崩溃。

## 12. Open Questions（已解决，记录裁决）

- MaterialSupplySnapshot 字段集：第 5 节定稿。
- 冲突裁决规则：第 6.4 节（保留双方 + conflict 标记）。
- 单位不兼容处理：第 6.5 节（limitation + 排除 complete，不换算）。
- executor 扩展形态：第 8 节（idempotency cache 增补 + 旁路 nodeResults）。

---
comet_change: sap-nexus-output-projection-registry
role: technical-design
canonical_spec: openspec
archived-with: 2026-08-05-sap-nexus-output-projection-registry
status: final
---

# Output Projection Registry 技术设计（sap-nexus-output-projection-registry）

## Document Version

| Field | Value |
|---|---|
| Change | `sap-nexus-output-projection-registry` |
| Runbook | 17 - Composite Fact and Output Projection |
| Date | 2026-08-04 |
| Last Updated | 2026-08-05 (final review fixes) |
| Depends On | Runbook 16 (READ PlanExecutor) |
| Unblocks | Runbook 18 (Recommendation) |
| Status | final |

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
  └─ SUCCEEDED node ─> 保留 NodeFactRecord { nodeId, agentTraceId=runId, capabilityId, parameters, executeData, nodeExecutedAt }
                        （完整 payload 先落 idempotency cache，再落 SUCCEEDED；succeededNodeResults 暴露）
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
       └─ outputHash = sha256(canonicalJson({ facts: normalized facts, version, snapshotId }))
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
  nodeId: string; agentTraceId: string; capabilityId: string;
  parameters: Record<string, string>;
  producesFactTypes: string[];
  gatewayTraceId: string | null;
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
  build: (record: NodeFactRecord & { gatewayTraceId: string }) => ReasoningFact[];
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

`freshness_mismatch` limitation **仅当 ≥2 节点 `dataAsOf` 的 parsed epoch 不同**时产生。原始字符串不同但 instant 等价（例如 `Z` 与 `+08:00`）-> 无 limitation -> 可达 `complete`；`sourceFreshness` 仍保留原始字符串。

### 6.2 Lineage

每个输出 fact 字段在 `lineage` 中有 `{ field, factId, evidence }` 条目，追溯到 source `ReasoningFact` 及其 evidence。`complete` snapshot 的 lineage 覆盖率 = 100%。

### 6.3 Freshness（双时间戳）

- `sourceFreshness` 恒携带 per-node `{ nodeId, nodeExecutedAt, dataAsOf }`。
- `dataAsOf = executeData[freshnessField]`（FactBuilder 声明，存在时）?? `nodeExecutedAt`（回退）。
- `freshness_mismatch` limitation IFF ≥2 节点 `dataAsOf` 的 parsed epoch 不同；判断按 instant，`sourceFreshness` 保留各自原始字符串，不合并。

### 6.4 Conflict（保留双方）

- 按 `(businessObject, predicate, material, plant)` 分组。
- 同 predicate + 同值 -> 去重保留一份（按 `factId` 稳定排序），无 limitation。
- 同 predicate + 异值 -> 两者都保留进 `facts`（按 `factId` 稳定排序），标 `conflict: true`，产 `conflict` limitation；若该 predicate 属 required -> `incomplete`。投影不选真值，透明呈现供 narrator 叙述。

### 6.5 Unit incompatibility

同逻辑字段不同单位且无版本化转换规则 -> 记 `unit_incompatibility` limitation，该字段排除出 `complete` 计量；required -> `incomplete`，optional -> `partial`。投影不做单位换算（non-goal）。

### 6.6 Determinism hash

- `normalize`：facts 按 `(businessObject, predicate, material, plant, factId)` 排序 -> canonical JSON。
- `envelope = { facts: normalizeFacts(facts), version: projectionVersion, snapshotId }`。
- `outputHash = sha256(canonicalJson(envelope))`；canonical object envelope 明确划分三个字段，不做可变长度字符串拼接。
- 相同输入 -> 相同 hash；fact 值 / version / snapshotId 任一不同 -> 不同 hash。

### 6.7 FactBuilder normalization and correlation

- `NodeFactRecord.agentTraceId` 使用当前 `PlanExecutor.execute(..., runId, ...)` 的 `runId`。fresh、cache replay 和 existing-`SUCCEEDED` hydration 均从当前 run context 注入；该字段不从 Gateway trace 推导，也无需重复持久化到 idempotency payload。
- 新成功路径的每个 `SUCCEEDED` 节点均保留完整 `NodeFactRecord`；唯一例外是 documented historical pre-change success 缺 payload，不能伪造 record。`gatewayTraceId` 是 `string | null`：非空 Gateway trace 保持原值，缺失或纯空白 trace 规范化为 `null`；不得用 `runId` 代替，也不得通过省略新路径 record 隐藏该节点。
- assembler 遇到 `gatewayTraceId = null` 时不调用 FactBuilder、不产 fact，并对 record 声明的每个 `producesFactTypes` 写入 `missingFacts`，固定 reason 为 `missing_gateway_trace`。FactBuilder 只接收已收窄为非空 Gateway trace 的 record，因此 `ReasoningFact.gatewayTraceId` 继续是非空 string。
- FactBuilder 将 `ReasoningFact.agentTraceId` 与 `traceId` 均设置为 `record.agentTraceId`，与 Python builder 的 agent-level correlation 语义一致；`gatewayTraceId` 仅承载 Gateway correlation。
- PO `orderQuantity` 先按字段存在性选择原始值：item 自身存在该字段时必须选择 item（即使值非法或为空），仅字段不存在时才回退 header；随后对所选值执行一次归一。有限 JS number 或合法有限 decimal string 进入 `ReasoningFact.value`，evidence 保留所选白名单原值；`NaN`、`Infinity` 和非法字符串不得进入 value，也不得触发 header 值替代。
- PO rows 使用 total order：`purchaseOrder/material/plant/purchaseOrderItem/normalizedQuantity/unit/canonicalWhitelistedRow`。完全相同的重复行可互换；任何非相同行不得依赖 Gateway 输入顺序决定 index-based `factId`。

### 6.8 ISO-8601 freshness 与 aggregate `asOf`

- `dataAsOf` 只有在它是带显式 `Z` 或 `±HH:mm` 时区、且可解析为有限 epoch 的 ISO-8601 string 时才有效；否则回退到 executor 生成的可信 `nodeExecutedAt`。
- 每条 `ReasoningFact.asOf` 保留所选来源的原始合法 ISO-8601 string，供 `sourceFreshness` 和 lineage 追溯。
- `PlanExecutionRecord.asOf` 不按字符串排序；assembler 单次扫描 facts，按 epoch 取最早 instant，并统一输出 UTC `new Date(minEpoch).toISOString()`。不同时区但等价的 instant 必须得到相同 aggregate `asOf`；实现不得用全量 argument spread，因此无隐含 fact cardinality ceiling。
- assembler fact/missing-fact/ledger-summary 与 executor `succeededNodeResults` 的新增 observable ordering 使用显式 UTF-16 code-unit comparator，不依赖 locale/ICU。既有 `computeInputHash()` ordering 不属于本 change。

## 7. 错误处理 / fail-closed

- 未知 `projectionId@version` -> fail-closed，结构化失败，不产 snapshot。
- 缺 FactBuilder（capabilityId 未注册）-> 该节点不贡献 fact，其 required FactType 进 `missingFacts`（reason: `no_fact_builder`）-> 降级 `incomplete`，不崩溃（graceful degradation）。
- 缺 Gateway correlation（`gatewayTraceId = null`）-> 保留 `SUCCEEDED` 节点和 `NodeFactRecord`，不调用 FactBuilder；声明 FactType 进 `missingFacts`（reason: `missing_gateway_trace`）-> required fact 缺失时降级 `incomplete`。
- restart 遇到新路径遗留 `EXECUTING`：完整 matching payload -> 合法 `EXECUTING -> SUCCEEDED` 并恢复 `NodeFactRecord`；缺失/不完整 payload -> `EXECUTING -> FAILED`。两条路径都不重复 Gateway/SAP READ。
- 历史 pre-change `SUCCEEDED` 缺完整 payload：保留 `SUCCEEDED`，不伪造 `NodeFactRecord`，不重复 Gateway/SAP READ；projection 只能按现有 facts 做 documented degradation。
- 投影隔离：`project()` 签名只接收 `{ planExecutionRecord, facts }`，类型层面无法访问 raw Gateway payload / conversation / model output。
- executor 扩展向后兼容：新增 `succeededNodeResults` 字段，不改 `nodeLedger` / `succeeded` / `failed` 等已有字段语义与状态机。

## 8. executor 扩展细节

新成功路径使用明确的 cache-first ordering：
```ts
const nodeExecutedAt = new Date().toISOString();
await this.store.markExecuted(idempotencyKey, {
  status: "succeeded",
  gatewayTraceId: executeResult.traceId,
  data: executeResult.data ?? {},
  parameters,
  capabilityId: node.capabilityId,
  producesFactTypes: [...node.producesFactTypes],
  nodeExecutedAt,
});
await this.transition(
  ..., NS.EXECUTING, NS.SUCCEEDED, ..., executeResult.traceId ?? null, nodeExecutedAt,
);
```

该 ordering 不承诺 idempotency cache 与 ledger 跨存储原子提交。它通过九态内的可恢复中间态消除 “ledger 已 `SUCCEEDED`、payload 尚未落盘” 窗口：

| Restart state | Matching payload | Recovery |
|---|---|---|
| `EXECUTING` | 完整 | `EXECUTING -> SUCCEEDED`，hydrate record，不重调 Gateway |
| `EXECUTING` | 缺失/不完整 | `EXECUTING -> FAILED`，不重调 Gateway |
| `SUCCEEDED` | 完整 | 保持终态，hydrate record |
| historical `SUCCEEDED` | 缺失/不完整 | 保持终态，record 缺失降级，不重调 Gateway |

- `markExecuted` payload 含 `{ data, parameters, capabilityId, producesFactTypes, nodeExecutedAt }`，在 ledger success 之前持久化；cache 与 success ledger 共用生成好的 `nodeExecutedAt`。
- `NodeFactRecord.agentTraceId` 由当前 `runId` 注入；fresh 和所有 replay/hydration 路径使用同一 run correlation，不把 `gatewayTraceId` 冒充 agent trace。
- executor 维护 `nodeResults: Map<nodeId, NodeFactRecord>`，每个拥有完整 fact-building data 的成功节点均填入并汇入 `PlanExecutorResult.succeededNodeResults`；Gateway trace 缺失或纯空白时 record 的 `gatewayTraceId` 为 `null`，而不是空 string 或省略 record。
- idempotent replay 与 recovered `EXECUTING` 分支从完整 cache 重建 `NodeFactRecord`；不完整 cache 不被当作可恢复 projection payload。
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
11. trace correlation：fresh/restart/builder facts 的 `agentTraceId` / `traceId` 等于 runId，且区别于 `gatewayTraceId`
12. PO normalization：decimal string 保留 evidence 并归一为有限 number；相同业务键的输入 permutation 产生稳定 facts/factIds
13. projection-missing：fresh/cache/existing-`SUCCEEDED` 缺 Gateway trace 时仍保留 nullable record；assembler 产生 `missing_gateway_trace`，不产空 trace fact、不重调 Gateway
14. PO precedence：nested item quantity 字段存在但非法时保留 item evidence、value 为 null，不回退合法 header quantity
15. freshness validation：malformed `dataAsOf` 回退 `nodeExecutedAt`；offset ordering 按 epoch，等价 instant 产生相同 UTC aggregate `asOf`
16. freshness classification：`Z` / `+08:00` 等价 instant 保留原字符串但不产 mismatch
17. hash framing：`(version="1", snapshotId="23")` 与 `(version="12", snapshotId="3")` 不碰撞
18. registry tuple：accepted `@` 跨边界 tuple exact resolve / coexist / duplicate reject
19. durable recovery：cache 写前失败与写后 interruption/restart 均不重复 Gateway READ；完整 payload 恢复、缺 payload fail-closed
20. ordering：mixed-case/non-ASCII node ids 在 assembler/executor 使用固定 code-unit order
21. high cardinality：150,000 facts aggregate `asOf` 无 argument-limit failure

验证命令：`npm --prefix frontend run verify` + `comet classic openspec -- validate --all --strict`。

## 10. Spec Patch（回写 delta spec）

回写 `specs/output-projection/spec.md`：
1. conflict 场景细化：当前 "applies a deterministic resolution" 模糊 -> "保留双方 + conflict 标记 + limitation，required 则 incomplete"。
2. complete 场景补充前提：无 freshness mismatch（dataAsOf 一致）。
3. 新增 "缺 FactBuilder 降级" 场景：missingFacts reason=`no_fact_builder` + incomplete。
4. freshness mismatch 改为 parsed epoch 语义，并补 offset-equivalent 场景。
5. hash 明确 canonical object envelope，并补 variable-boundary collision 场景。
6. registry 明确 logical tuple boundary，并补 accepted `@` 场景。
7. executor 明确 cache-first success ordering、`EXECUTING` recovery 与 historical degradation。
8. observable ordering 固定 code-unit；aggregate `asOf` 明确无 cardinality-dependent spread。

## 11. Risks / Trade-offs

- [executor 丢弃 data / success-payload 双写窗口] -> cache-first 完整 payload + 旁路 nodeResults；restart 仅走合法 `EXECUTING` exits，不做跨存储伪原子承诺。
- [TS ReasoningFact 镜像漂移] -> 镜像最小契约 + asOf；Python 侧运行时不变。
- [complete 可达性] -> freshness_mismatch 仅 parsed epoch 不同才触发；测试覆盖同字符串与 offset-equivalent instant。
- [生产 orchestrator deferred] -> component/Eval 层验证；生产接线后续 runbook。
- [FactBuilder 注册缺口] -> 降级 missingFacts + incomplete，不崩溃。

## 12. Resolved Decisions

- MaterialSupplySnapshot 字段集：第 5 节定稿。
- 冲突裁决规则：第 6.4 节（保留双方 + conflict 标记）。
- 单位不兼容处理：第 6.5 节（limitation + 排除 complete，不换算）。
- executor 扩展形态：第 8 节（cache-first idempotency payload + 旁路 nodeResults + `EXECUTING` recovery）。

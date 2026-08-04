# Brainstorm Summary

- Change: sap-nexus-output-projection-registry
- Date: 2026-08-04

## 确认的技术方案

**模块结构（方案 1，聚合 projection/ 模块）**：`frontend/src/runtime/projection/` 内含 types/fact-builder/assembler/registry/material-supply-snapshot/hash；`plan-executor/` 原地扩展保留成功节点 data。镜像 `plan-executor/` 模式。

**数据流**：PlanExecutor 成功节点保留 `{ nodeId, capabilityId, parameters, executeData, nodeExecutedAt }`（idempotency cache 持久化 + `succeededNodeResults` 暴露）-> ProjectionInputAssembler 编排，对每个 SUCCEEDED 节点调用 FactBuilder.build -> ReasoningFact[] + PlanExecutionRecord -> OutputProjectionRegistry.resolve(projectionId@version) -> MaterialSupplySnapshot.project -> snapshot。

**Q1 Fact 构建 = 独立 FactBuilder 组件 + assembler 编排**：executor 仅保留 data，FactBuilder 持 per-capability 构建器 + freshnessField 声明，assembler 编排。executor 不了解 fact 语义。

**Q2 asOf = 双时间戳**：sourceFreshness per-node `{ nodeId, nodeExecutedAt, dataAsOf }`；dataAsOf = executeData[freshnessField] ?? nodeExecutedAt；freshness_mismatch limitation IFF ≥2 节点 dataAsOf 不同。

**Q3 conflict = 保留双方 + conflict 标记**：同 predicate 同值去重无 limitation；同 predicate 异值保留双方（factId 稳定排序）+ conflict 标记 + limitation，required 则 incomplete。投影不选真值。

## 核心类型

- `ReasoningFact`：镜像 Python dataclass + `asOf`
- `NodeFactRecord`：executor 扩展保留（nodeId/capabilityId/parameters/executeData/nodeExecutedAt）
- `PlanExecutionRecord`：runId/snapshotId/nodeLedgerSummary/asOf
- `MaterialSupplySnapshot`：projectionId/projectionVersion/snapshotId/asOf/sourceFreshness/completeness/facts/lineage/missingFacts/failedNodes/limitations/outputHash
- `OutputProjectionDeclaration`：projectionId@version + required/optional FactTypes + timeBasis + project()
- `FactBuilderDeclaration`：capabilityId + build() + freshnessField?

## 关键取舍与风险

- **[executor 丢弃 data]** executeNode 成功后只存 traceId，丢弃 GatewayExecuteResult.data。Mitigation: 扩展 idempotency cache payload 携带 data + nodeExecutedAt，向后兼容新增 succeededNodeResults 字段；不改状态机与已有字段语义。
- **[TS ReasoningFact 镜像漂移]** Mitigation: 镜像 Python dataclass 最小契约 + asOf；Python 侧运行时行为不变。
- **[complete 可达性]** freshness_mismatch 仅当 dataAsOf 不同才产 limitation；双 READ 同 dataAsOf 可达 complete（测试可控）。
- **[生产 orchestrator deferred]** projection 在 component/Eval 层验证，不经生产调用链；projectionRef 生产绑定随 orchestrator deferred。
- **[FactBuilder 注册缺口]** 缺 builder 时降级 missingFacts(no_fact_builder) + incomplete，不崩溃。

## 测试策略

10 类 Eval 场景：complete / incomplete / partial / freshness mismatch / unit incompatibility / conflict / 确定性 hash / 隔离 / fail-closed(未知 projectionId@version) / executor 回归。验证命令 `npm --prefix frontend run verify` + `openspec validate --all --strict`。

## Spec Patch

回写 `specs/output-projection/spec.md`：
1. conflict 场景细化：当前"applies a deterministic resolution"模糊 -> "保留双方 + conflict 标记 + limitation，required 则 incomplete"。
2. complete 场景补充前提：无 freshness mismatch（dataAsOf 一致）。
3. 新增"缺 FactBuilder 降级"场景：missingFacts reason=no_fact_builder + incomplete。

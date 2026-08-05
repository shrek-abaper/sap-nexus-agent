## Context

Runbook 16 在 TS 侧（`frontend/src/runtime/plan-executor/`）实现了 READ-only PlanExecutor：消费 PlanGraph v2 `readPartition`，按 ready-node 调度，产出 `PlanExecutorResult`（节点账本 + `succeeded/failed/timedOut/cancelled/blocked` 列表）。`PlanGraphV2.projectionRef: unknown[]` 是为投影预留的空占位符。

当前缺口：executor 不产出 `ReasoningFact[]` 或 `PlanExecutionRecord`，多 READ 结果无确定性组合投影，freshness / 完整性 / lineage / partial 失败无结构化口径。Runbook 17 补齐这条 `ReasoningFact[] -> MaterialSupplySnapshot` 投影链路。生产 orchestrator 接线仍 deferred（与 Runbook 16 边界一致），本轮在 component + Eval 层验证。

## Goals / Non-Goals

**Goals:**
- 版本化 `OutputProjection` 注册表 + 校验：projection 声明 required/optional input FactType、output schema、时间口径、partial policy。
- `MaterialSupplySnapshot` 作为首个注册 projection（组合事实束）。
- 投影输入组装：`PlanExecutorResult` + 节点级 Gateway 结果 -> `PlanExecutionRecord + successful ReasoningFact[]`。
- partial/incomplete/lineage/freshness/limitations 确定性 policy。
- 确定性输出 hash（相同输入 + projection version + snapshotId -> 相同 hash）。
- projection Eval（frontend 测试）覆盖核心与边界场景。

**Non-Goals:**
- 不接入生产 orchestrator（仍 deferred）。
- 不形成 Action / Recommendation（Runbook 18）。
- 不计算采购数量 / 日期 / 采购组；不调用 LLM；不接 Knowledge/RAG。
- 不做多 WRITE / Saga / 自动补偿。
- 深度技术细节由 `docs/superpowers/specs/2026-08-04-sap-nexus-output-projection-registry-design.md` 定稿；本文只保留高层裁决。

## Decisions

### D1. 实现侧 = TS（`frontend/src/runtime/projection/`）
executor 与节点级 Gateway 结果均在 TS 运行时；projection 与 executor 同侧避免跨语言序列化往返。Python 侧 `semantic_planning` 契约不变，TS 侧镜像 `ReasoningFact` 最小契约。
- 备选：Python 侧实现（需把 executor 结果序列化回 Python，跨语言开销大，已否决）。

### D2. 通用版本化注册表，MaterialSupplySnapshot 为首项
`OutputProjectionRegistry` 按逻辑 tuple `(projectionId, version)` 查找已注册 projection，并用 nested map 保留 tuple 边界；`@` 只是 accepted identifier 内容，不是存储分隔符。projection 注册时声明 required/optional FactType、output schema、partial policy。本轮 projection 通过显式 `projectionId@version` 在 component/Eval 层调用；`projectionRef` 生产绑定随 orchestrator deferred。为 Runbook 18 RuleSet 留同构接口。
- 备选：仅硬编码 MaterialSupplySnapshot（已否决，违背 runbook「registered OutputProjection@version」且不利 Runbook 18 扩展）。

### D3. 投影输入组装 = 新增 assembler，executor 扩展产出携带节点 facts
新增 `ProjectionInputAssembler`：消费 `PlanExecutorResult` + 节点级 Gateway execute 结果，组装 `PlanExecutionRecord`（含 snapshotId / node ledger 摘要 / asOf）+ `successful ReasoningFact[]`。executor 扩展产出以暴露成功节点的 fact 数据（向后兼容新增字段，不改已有字段语义）。新成功节点先持久化完整 fact-building payload，再落权威 `SUCCEEDED`；restart 遇到 `EXECUTING` 时，完整 cache 走合法 `EXECUTING -> SUCCEEDED`，缺失/不完整 cache 则走 `EXECUTING -> FAILED`，两者都不重复 Gateway/SAP READ。历史 `SUCCEEDED` 缺 payload 保留其终态但不伪造 `NodeFactRecord`。`NodeFactRecord.agentTraceId` 由当前 executor `runId` 注入，FactBuilder 用它填充 `ReasoningFact.agentTraceId/traceId`，并与 `gatewayTraceId` 保持语义分离。每个拥有完整 payload 的 `SUCCEEDED` 节点均保留 `NodeFactRecord`；Gateway trace 缺失或纯空白时 `gatewayTraceId = null`，assembler 不产 fact，并按声明 FactType 写入 `missingFacts(reason="missing_gateway_trace")`。PO 数量先按字段存在性选择 item/header 原值，再按版本化规则接受有限 number/decimal string；evidence 保留所选白名单原值，PO row 排序使用完整 deterministic tie-breaker，不依赖 Gateway 输入顺序。Fact freshness 只接受带时区且可解析的 ISO-8601，非法 `dataAsOf` 回退 `nodeExecutedAt`；aggregate `asOf` 按 epoch 单次扫描取最早值并规范化为 UTC `toISOString()`。所有新 observable node/fact ordering 使用显式 code-unit comparator，不依赖 process locale。
- 备选：在 executor 内直接产出 projection（耦合 executor 与 projection，已否决）。

### D4. MaterialSupplySnapshot = 组合事实束（非派生业务指标）
snapshot = facts + lineage + freshness + completeness + limitations 元数据包裹，不做采购数量计算（runbook non-goal）。`completeness` 三态：`complete`（required fact 齐全 + 无失败节点）/ `partial`（有可选 fact 缺失或 limitation）/ `incomplete`（缺 required fact 或节点失败/超时/取消）。

### D5. 确定性 hash
对 canonical envelope 计算确定性 hash：`sha256(canonicalJson({ facts: normalizeFacts(facts), version: projectionVersion, snapshotId }))`。对象字段的 canonical JSON 提供无歧义 framing，不拼接可变长度字符串。跨节点 parsed epoch 不一致时保留各自原始时间字符串并产生 limitation；offset 表达不同但 epoch 相同不产生 mismatch。

## Risks / Trade-offs

- [executor 产出契约扩展可能影响 Runbook 16 已有测试] -> Mitigation: 向后兼容扩展（新增字段，不改已有字段语义与状态机）；回归 `frontend run verify`。
- [payload cache 与 ledger 属两个 durable record，无法跨存储原子提交] -> Mitigation: 明确 cache-first ordering；restart 只沿九态合法边恢复，缺 payload fail-closed 且不重复 READ。
- [TS `ReasoningFact` 镜像与 Python dataclass 漂移] -> Mitigation: 镜像最小契约 + 共享 schema 校验；Python 侧运行时行为不变。
- [生产 orchestrator 仍 deferred，projection 未经生产链路验证] -> Mitigation: 本轮在 component + Eval 层充分验证；生产接线和 `projectionRef` 绑定在后续 runbook 完成。

## Resolved Decisions

- `MaterialSupplySnapshot` 字段集与 TS contract：technical design 第 5 节。
- 重复 / 冲突 fact 裁决：technical design 第 6.4 节（保留双方 + conflict marker）。
- 单位不兼容：technical design 第 6.5 节（limitation + 排除 complete，不换算）。
- executor 输出与 durable recovery：technical design 第 8 节（cache-first payload + 旁路 `nodeResults` + fail-closed restart）。

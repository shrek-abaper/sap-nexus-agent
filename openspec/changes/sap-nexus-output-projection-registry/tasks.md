## 1. 类型与契约冻结

- [x] 1.1 定义 TS `ReasoningFact` 最小镜像契约（与 Python `reasoning_fact.py` dataclass 对齐：factId / domain / businessObject / predicate / value / unit / deterministic / confidence / source / evidence / material / plant / asOf）
- [x] 1.2 定义 `PlanExecutionRecord` 类型（`snapshotId` / node ledger 摘要 / `asOf` / succeeded/failed 节点列表）
- [x] 1.3 定义 `MaterialSupplySnapshot` 类型（`asOf` / `sourceFreshness` / `completeness` / `facts` / `lineage` / `missingFacts` / `failedNodes` / `limitations`）
- [x] 1.4 定义 `OutputProjection` 注册声明类型（`projectionId` / `version` / required FactTypes / optional FactTypes / output schema / time basis / partial policy）

## 2. OutputProjection 注册表 + 校验

- [x] 2.1 实现 `OutputProjectionRegistry`：`register(declaration)` + `resolve(projectionId, version)`
- [x] 2.2 未知 `projectionId` 或未注册 `version` fail-closed 并记录结构化失败
- [x] 2.3 注册表单测（注册 + 解析 + 未知拒绝）

## 3. Executor 扩展产出（read-plan-executor 修改）

- [x] 3.1 扩展 executor 产出，使 `SUCCEEDED` 节点暴露构建 `ReasoningFact` 所需的 per-node 数据（向后兼容新增字段，不改已有字段语义与状态机）
- [x] 3.2 回归 Runbook 16 executor 测试（`frontend run verify` 中 executor 套件）不改动通过
- [x] 3.3 为 `NodeFactRecord` 增加由当前 `runId` 注入的 `agentTraceId`，覆盖 fresh / cache replay / existing-SUCCEEDED hydration，且不混用 `gatewayTraceId`
- [x] 3.4 fresh / cache replay / existing-SUCCEEDED 缺 Gateway trace 时仍保留 `NodeFactRecord(gatewayTraceId=null)`，不改变成功状态、不重调 Gateway

## 4. 投影输入组装

- [x] 4.1 实现 `ProjectionInputAssembler`：消费 `PlanExecutorResult` + 节点级 Gateway 结果 -> `PlanExecutionRecord` + successful `ReasoningFact[]`
- [x] 4.2 仅 `SUCCEEDED` 节点贡献 facts；`FAILED`/`TIMED_OUT`/`CANCELLED`/`BLOCKED_*` 节点排除并记入 ledger 摘要
- [x] 4.3 assembler 不读 raw Gateway payload 之外内容、不读 conversation text / model output
- [x] 4.4 assembler 单测（双 READ 成功组装、非成功节点排除）
- [x] 4.5 PO decimal-string quantity 确定性归一并保留白名单 evidence，拒绝非有限或非法数值
- [x] 4.6 PO rows 使用 total-order tie-breaker，输入 permutation 产生稳定 facts / factIds
- [x] 4.7 FactBuilder 使用 `NodeFactRecord.agentTraceId` 填充非空 `ReasoningFact.agentTraceId/traceId`
- [x] 4.8 assembler 对 nullable Gateway trace 产生 `missingFacts(reason="missing_gateway_trace")`，且不调用 builder、不产空 trace fact
- [x] 4.9 PO item quantity 按字段存在性优先；item 非法/空值保留 evidence 且不得回退合法 header quantity
- [x] 4.10 freshness 校验带时区 ISO-8601，非法 `dataAsOf` 回退 `nodeExecutedAt`，aggregate `asOf` 按 epoch 取最早并规范化 UTC

## 5. MaterialSupplySnapshot 投影

- [x] 5.1 实现 `material-supply-snapshot` projection：产出组合事实束（facts + lineage + 元数据），不计算采购数量/日期/采购组
- [x] 5.2 实现 `completeness` 三态：`complete`（required 齐全 + 无失败节点）/ `partial`（可选缺失或 limitation）/ `incomplete`（缺 required 或节点失败/超时/取消）
- [x] 5.3 实现 `missingFacts` / `failedNodes` / `limitations` 填充
- [x] 5.4 实现 `lineage`：每个输出 fact 字段可追溯到 source fact / evidence
- [x] 5.5 实现 freshness mismatch：跨节点 `asOf` 不一致时保留各自时间到 `sourceFreshness` + 产生 limitation
- [x] 5.6 实现 unit incompatibility 确定性处理 + limitation（不计入 `complete`）
- [x] 5.7 实现 duplicate / conflicting fact（同 predicate 异值）确定性裁决 + limitation
- [x] 5.8 实现确定性 hash：normalized facts（排序）+ projection `version` + `snapshotId`
- [x] 5.9 注册 `material-supply-snapshot` 到 `OutputProjectionRegistry`

## 6. Projection Eval（frontend 测试）

- [x] 6.1 complete snapshot 场景（双 READ 成功，lineage 完整率 100%）
- [x] 6.2 incomplete 场景（单节点失败 -> missingFacts + failedNodes + limitation）
- [x] 6.3 partial 场景（可选 fact 缺失 -> limitation）
- [x] 6.4 freshness mismatch bad case
- [x] 6.5 unit incompatibility bad case
- [x] 6.6 duplicate / conflict fact bad case
- [x] 6.7 确定性 hash（same input -> same hash；different input -> different hash）
- [x] 6.8 projection 隔离测试（仅读 normalized facts + ledger metadata，不读 raw payload / model output）

## 7. 验证

- [ ] 7.1 `npm --prefix frontend run verify` 通过（含 projection Eval + executor 回归）
- [ ] 7.2 `openspec validate --all --strict` 通过

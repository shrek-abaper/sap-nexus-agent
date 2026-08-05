## Why

Runbook 16 的 READ PlanExecutor 已能在 TS 侧调度执行 READ 节点并产出节点账本（`PlanExecutorResult`），但多 READ 结果仍以裸节点级形式存在，缺少确定性的组合投影：跨节点事实无法形成可追溯的 `MaterialSupplySnapshot`，freshness / 完整性 / lineage 无结构化口径，partial 失败无契约。LLM 因此被迫在 prompt 中拼接业务事实，违背"事实由版本化确定性规则投影、LLM 仅叙述"的边界。Runbook 17 是 Runbook 16 的直接后继，补上这条投影链路，为 Runbook 18 的 Recommendation 提供可追溯快照输入。

## What Changes

- 新增版本化 `OutputProjection` 注册表与校验机制：projection 声明 required/optional input FactType、output schema、时间口径、partial policy；`@version` 确定性绑定，相同输入 + projection version + snapshotId 产出相同输出 hash。
- 新增 `MaterialSupplySnapshot` 作为首个注册 projection：`{ asOf, sourceFreshness, completeness, facts, lineage, missingFacts, failedNodes, limitations }`，作为组合事实束（非派生业务指标）。
- 新增投影输入组装：从 `PlanExecutorResult` + 节点级 Gateway 结果组装 `PlanExecutionRecord + successful ReasoningFact[]` 作为 projection 输入（executor 现仅产出节点账本，不携带 facts，本轮补齐输入契约）。
- 实现 partial/incomplete policy：缺 required fact / 节点失败 / 超时 / 取消时不得标记 `complete`，产出 `missingFacts` + `failedNodes` + `limitation`。
- 实现 lineage / freshness / 单位与冲突的确定性处理：每个输出字段可追溯到 fact/evidence；跨节点 `asOf` 不一致时保留各自时间并产生 limitation。
- 新增 projection Eval（frontend 测试）：覆盖 complete / partial / freshness mismatch / 单位不兼容 / 重复冲突 / 确定性 hash bad case。
- **不接入生产 orchestrator**（仍 deferred，与 Runbook 16 边界一致）；projection 通过显式 `projectionId@version` 在 component/Eval 层调用，`projectionRef` 生产绑定随 orchestrator deferred；不形成 Action / Recommendation（Runbook 18）；不计算采购数量 / 日期 / 采购组；不调用 LLM；不接 Knowledge/RAG。

## Capabilities

### New Capabilities

- `output-projection`: 版本化 OutputProjection 注册表 + 校验、MaterialSupplySnapshot 首项、投影输入组装（PlanExecutionRecord + ReasoningFact[]）、partial/incomplete/lineage/freshness/limitations policy、确定性 hash、projection Eval。

### Modified Capabilities

- `read-plan-executor`: 扩展 executor 产出契约，使其在节点账本之外提供 projection 输入（`PlanExecutionRecord + successful ReasoningFact[]`），供 projection 消费。

## Impact

- 代码：`frontend/src/runtime/` 新增 projection 模块（registry + validator + assembler + MaterialSupplySnapshot + Eval）；`frontend/src/runtime/plan-executor/` 扩展产出以携带节点级 facts。
- 契约：新增 `output-projection` spec；修改 `read-plan-executor` spec 的 delta（ADDED requirement）。
- 依赖：复用现有 `PlanExecutorResult`、`RegistrySnapshot`、`ReasoningFact`（TS 侧需镜像最小契约）；不引入新运行时依赖。
- 验证：`npm --prefix frontend run verify`（projection Eval）；`openspec validate --all --strict`。
- 不影响：生产 orchestrator 接线、`projectionRef` 生产绑定、Action 路径、Python 侧 planner / semantic_planning 运行时行为。

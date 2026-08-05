# Outcome

交付 Runbook 22 的完整 Agent 生产组合编排与离线发布门禁：在不改变 LLM-first 语义入口和 Gateway 权威边界的前提下，把已归档的 PlanGraph v2、READ PlanExecutor、OutputProjection、Recommendation、grounded Narrative、Workbench evidence 与单 Action Human Approval 串成可回放的 L1/L2/L3 端到端运行，并用不可被平均分抵消的 hard gates 产生真实成熟度发布决定。

# Scope

- 保留现有 Python Agent 作为 intent、closed-set recall、五态 MatchDecision 与 PlanGraph v2 authoring 入口；新增服务端 TypeScript composition coordinator，只消费已验证且绑定同一 run/principal/snapshot 的计划。
- L1 继续验证现有单 capability 主链不回退；L2 串联 multi-READ executor、fact builders、`MaterialSupplySnapshot`、Recommendation、Narrative、durable events 与 Workbench replay；L3 在 L2 证据之上形成最多一个 Action proposal，并复用 Runbook 21 的 plan-aware Human Approval 与 exactly-once continuation。
- 建立版本化的 L1/L2/L3 release profiles、deterministic fixtures、recorded LLM fixtures、端到端 scenarios、指标聚合、hard-gate evaluator、机器可读/人可读证据报告和离线统一命令。
- 覆盖未知/不可见 capability、prompt injection、缺参、snapshot drift、timeout/cancel/recovery、partial facts、freshness、规则输入、unsupported claim、approval bypass/hash drift、重复 continuation、cross-principal、SSE reconnect/replay 等 Runbook 22 风险矩阵。
- 更新 Runbook 22、runbook index、README/roadmap/wiki 的实际成熟度；只把已通过的最高等级标为实现，不把 fixture、UI 标签、fake Gateway 或未执行的 live smoke 描述为 live SAP 证据。

# Non-goals

- 不引入 Knowledge/RAG、embedding/vector store、自由 LLM tool calling、任意 RFC/URL/SQL、通用 dynamic replanning、多 WRITE、Saga 或自动补偿。
- 不重写 Runbooks 13-21 已归档组件，也不建立第二套 approval、ledger、event 或 Gateway 权威。
- 不在本变更中执行 live SAP WRITE；任何 live WRITE smoke 仍需针对精确 capability、不可变参数 snapshot 与执行窗口另行取得明确 Human Approval。
- 不要求离线 maturity gate 依赖网络、真实 LLM、真实 SAP 或不可提交的 runtime trace；live smoke 状态单独记录，未运行时不得形成 live release claim。

# Acceptance examples

- L1 recorded intent case 经过 LLM-first recorded response、五态决策、CallPlan、fake Gateway、Fact 与 Narrative 后通过；未知/不可见 capability 或缺参在 Gateway 前停止，既有单能力结果不回退。
- L2 material-supply case 从同一 snapshot 的两项 READ PlanGraph 执行到完整 projection、recommendation、grounded narrative、durable event/replay 与 Workbench view；每个 claim 和 projection 字段均可追溯到 fact/node/Gateway evidence。
- L2 节点 timeout/cancel/failure 只能产生 partial/incomplete projection 和显式 limitations；如果 profile 要求完整业务结论，则 L2 hard gate 失败且最高可发布等级降为 L1。
- L3 case 在完整 fresh L2 证据与齐备规则输入上只形成一个 `MM.PR.CreateDraft` proposal；没有服务端记录的人审时 WRITE execute 为 0，精确批准后 fake/sandbox Action 最多执行一次，重复/reconnect/restart 返回同一结果。
- 任一 visibility leakage、approval bypass、unsupported narrative claim、缺失 lineage、cross-principal access、hash/snapshot drift 或 replay side effect 使对应等级 hard-fail；较高等级失败不影响已独立通过的较低等级决定。
- 每次离线回归输出 schema/profile version、registry snapshot、fixture/model-recording versions、case totals、失败 case/hard gate、trace/evidence refs、live-smoke status 与 `L1_ONLY`/`L2_READ_COMPOSITION`/`L3_ACTION_GOVERNED`/`NO_RELEASE` 决定。

# Constraints and invariants

- LLM 只能在服务端提供的 visible CapabilityCard closed set 内做语义候选；Registry、PlanGraph validator、RuleSet、Approval 与 Gateway 始终是确定性权威。
- 所有组合对象必须绑定同一非空 `runId`、`traceId`、`snapshotId` 和 trusted principal；任一跨 run/snapshot/principal 引用 fail closed。
- Gateway 只接收 `capabilityId`；请求、fixture 与模型不得提供或覆盖 RFC name、binding、URL、SQL、credential 或不可见 capability。
- READ 不得 commit/rollback；WRITE 未经可核验 Human Approval 不得执行；proposal、UI label、chat sentence、fixture 和 event 都不是 approval evidence。
- `visibilityLeakageRate=0`、`writeApprovalBypassRate=0`、unsupported narrative claim rate `0`、fact lineage completeness `100%` 是不可加权抵消的 hard gates。
- 离线 suite 必须 deterministic、可重复且无 live side effects；recorded LLM fixture 保存经审查的模型响应与版本信息，不在回归时访问模型网络。

# Decisions

- 采用薄 TypeScript composition coordinator：Python 保持语义/规划入口，TypeScript 复用 Runbooks 16-21 已实现的执行、投影、建议、叙事、事件与 Action 治理组件；不跨语言复制权威逻辑。
- release evaluator 消费真实 coordinator 产物和 durable replay，而不是把 Runbook 20 的静态 UI fixtures 当成执行证据。
- L1/L2/L3 分级独立判定并选择最高连续通过等级；L2 失败最多发布 L1，L3 失败最多发布 L2，安全 hard gate 失败使受影响等级及其以上等级不可发布。
- offline release decision 与 live smoke authorization/report 分离；未授权或未运行的 live smoke 记录为 `not_run`，不能升级 live claim，也不伪造为离线失败。
- 本变更不执行 live SAP WRITE；如后续用户提供精确批准，live smoke 作为独立授权步骤和证据记录处理。
- 2026-08-05 用户已确认本 brief 与两份完整目标规格，允许按上述边界进入 Build。

# Open questions

无。

# Verification expectations

- 按 TDD 为 coordinator、profiles、fixtures、metrics、hard gates、report 与 CLI 先写失败测试，再写最小实现；focused tests 覆盖每个安全失败和等级降级行为。
- 运行 `npm --prefix frontend run verify`、`.venv/bin/python -m pytest agent/tests -q`、`scripts/verify-agent-callplan-evidence.sh`、相关 eval commands、`openspec list --json`、`openspec validate --all --strict`、离线 release-gate command 与 `git diff --check`。
- Native Verify 报告必须绑定全部 acceptance item 的当前 receipts；未运行、失败、stale 或 live-only 检查不得记录为 passed。

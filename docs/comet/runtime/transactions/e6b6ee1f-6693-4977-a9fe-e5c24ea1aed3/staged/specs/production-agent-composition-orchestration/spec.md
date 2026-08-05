# Production Agent Composition Orchestration Specification

## Purpose

定义 Runbook 22 完成后的生产组合编排行为：保留 Python Agent 的 LLM-first 语义与 PlanGraph authoring，由服务端 TypeScript coordinator 只消费已验证的 PlanGraph v2，并串联 READ execution、事实投影、建议、grounded narrative、durable evidence、Workbench replay 与受人审的单 Action continuation。

## Requirements

### Requirement: Semantic front door and composition coordinator have one governed handoff

系统 SHALL 保留现有 Python Agent 负责 `IntentEnvelope`、visible closed-set recall、五态 `MatchDecision` 与 deterministic PlanGraph v2 authoring。只有 `ESCALATE_TO_PLANNER` 且 dry-run 含 schema-valid PlanGraph v2、无 blocking gaps、非空 snapshot、可见已注册 capabilities 和完整 required parameter bindings 时，服务端 coordinator 才可接管组合执行。coordinator MUST NOT 接受模型或请求提供的 RFC、binding、URL、SQL、credential 或任意 capability。L1 `SELECT`、`CLARIFY`、`SHOW_OPTIONS` 与 `REJECT` SHALL 保持现有行为。

#### Scenario: Valid multi-intent handoff enters composition

- **WHEN** Python Agent 返回同一 governed snapshot 下的 `ESCALATE_TO_PLANNER` 与有效双 READ PlanGraph v2
- **THEN** coordinator 以当前 server-owned run/principal/trace 和该 snapshot 创建 composition execution
- **AND** 只执行图中 visible、registered、READ partition 的 capability

#### Scenario: Invalid or unsafe handoff stops before Gateway

- **WHEN** handoff 缺 plan/snapshot/parameters、含 blocking gaps、未知或不可见 capability、cross-snapshot ref 或 technical binding
- **THEN** coordinator 返回结构化 fail-closed outcome 与 durable failure evidence
- **AND** Gateway validate/execute、projection、recommendation 与 Action 调用数均为 0

### Requirement: Multi-READ execution produces one traceable composition bundle

coordinator SHALL 使用现有 `PlanExecutor` 执行已验证的 READ partition，使用 capability-specific FactBuilder 生成 `ReasoningFact[]`，再通过 snapshot-bound registered `OutputProjection` 生成 `MaterialSupplySnapshot`。node ledger、Gateway safe result、facts、projection freshness/completeness/lineage/limitations MUST 绑定同一 run/trace/snapshot。失败、timeout、cancel、dependency block、lease/recovery conflict 或 missing fact MUST 保持结构化状态，不得被投影或叙事隐藏。

#### Scenario: Complete plan produces a complete snapshot

- **WHEN** inventory 与 purchase-order READ nodes 成功且返回可归一化、fresh、单位兼容的 facts
- **THEN** coordinator 产生 complete `MaterialSupplySnapshot` 与 100% fact lineage
- **AND** 每个 projection 字段可导航到 node、Gateway safe evidence 与 `ReasoningFact`

#### Scenario: Partial execution remains partial

- **WHEN** 任一 READ node failed、timed out、cancelled 或 recovery 后仍无结果
- **THEN** projection 按注册 policy 返回 partial/incomplete、missing facts、failed nodes 与 limitations
- **AND** 不允许需要完整 fresh input 的 Action proposal

### Requirement: Recommendation and narrative consume only deterministic governed outputs

coordinator SHALL 从精确 snapshot/version 的 `RuleSetRegistry` 解析规则，以 projection、facts 与显式用户 constraints 生成 `RecommendationPlan`。缺少 required quantity、target date、purchasing group、freshness 或声明输入时 MUST 返回 `CLARIFY`/`INSUFFICIENT_INPUT`，不得猜值。`NarrativeEnvelope` SHALL 只消费治理对象；所有 claims MUST 有可解析 evidence refs，模型失败或输出 unsupported claim 时使用既有 template fallback。

#### Scenario: Complete inputs produce one grounded recommendation narrative

- **WHEN** complete fresh projection 与 RuleSet required constraints 全部有效
- **THEN** coordinator 产生 replayable RecommendationPlan 与 NarrativeEnvelope
- **AND** unsupported narrative claim 数为 0，每个 claim ref 均解析到同 run/snapshot

#### Scenario: Missing decision input cannot be invented

- **WHEN** required constraint、RuleSet 或 projection version 缺失或漂移
- **THEN** recommendation 返回 clarification/insufficient status 与 limitations
- **AND** 不生成可审批 Action proposal，不调用 WRITE Gateway

### Requirement: Durable event and replay are the Workbench evidence source

coordinator SHALL 将 intent、recall、plan、node、fact、projection、recommendation、narrative、proposal、approval 与 action 的 allowlisted/redacted events 按严格递增 sequence 追加到现有 durable run store。Workbench 与 SSE reconnect SHALL 只投影这些 durable objects。refresh、cursor replay、重复 delivery 与 UI interaction MUST NOT 触发 PlanExecutor、Gateway、approval decision 或 Action continuation。

#### Scenario: Reconnect returns evidence without side effects

- **WHEN** 客户端从 cursor N 重连或重复读取已完成 L2/L3 run
- **THEN** 只返回 sequence 大于 N 的持久事件并保持 object identity/ref 不变
- **AND** READ/WRITE execute 调用数不增加

#### Scenario: Evidence corruption is visible and fail closed

- **WHEN** durable chain 出现 gap、冲突 sequence、unknown ref、cross-snapshot object 或 unsafe payload
- **THEN** replay/Workbench 显示结构化 limited/error 状态
- **AND** 不重排为成功、不创建缺失证据、不触发执行

### Requirement: One Action remains proposal-only until exact Human Approval

L3 composition SHALL 复用 Runbook 21 的 `PlanApprovalRecord` 与 `PlanActionContinuation`。完整 fresh L2 evidence 最多生成一个注册 `MM.PR.CreateDraft` proposal；pending proposal、chat sentence、fixture、event、button 或 label MUST NOT 构成授权。只有 server-owned run owner 对当前 immutable subject 的显式 approval 被 durable 记录，并在 continuation 时通过全部绑定重校验后，Action 才可最多执行一次。

#### Scenario: Proposal without recorded approval never executes

- **WHEN** composition 产生 pending Action proposal 但没有匹配的服务端 Human Approval record
- **THEN** Workbench 显示 proposal 与来源
- **AND** WRITE Gateway execute 调用数为 0

#### Scenario: Exact approved subject executes at most once

- **WHEN** run owner 显式批准未过期、未撤销且所有绑定未漂移的唯一 proposal
- **THEN** continuation 通过现有 Gateway atomic claim 执行一次并持久化 ActionResult/evidence
- **AND** retry、SSE reconnect、并发 worker 或 restart 返回相同 durable result，WRITE execute 调用数保持为 1

#### Scenario: Drift or another principal blocks continuation

- **WHEN** principal、snapshot、plan、parameters、facts、projection、RuleSet、proposal/hash 任一变化，或非 run owner 尝试决定或继续
- **THEN** continuation fail closed 且不泄露其他 principal 数据
- **AND** WRITE Gateway execute 调用数为 0

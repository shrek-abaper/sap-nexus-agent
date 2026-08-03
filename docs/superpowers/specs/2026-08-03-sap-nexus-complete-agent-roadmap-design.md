# SAP Nexus Complete Agent Roadmap Design

## Document Version

| Field | Value |
|---|---|
| Version | `v0.1.0` |
| Status | `Approved Design / Implementation Planned` |
| Created | `2026-08-03` |
| Scope | 完整意图识别、已注册能力召回、多能力编排、事实投影、建议、grounded narrative、Workbench 展示和受审批的单 Action proposal |
| Non-goal | 本轮不改代码；Knowledge/RAG、跨会话相似问题检索、自由 Tool Calling、多 WRITE/Saga 均不进入 MVP |

## 1. 结论

当前 Agent 设计方向合理，但实现成熟度只到“LLM-first 意图识别 + 受治理五态匹配 + 多能力 PlanGraph dry-run”。完整 Agent 还缺少可信上下文与同快照交接、可执行 PlanGraph、确定性组合事实、规则化建议、证据约束叙事、Workbench 全链路展示，以及 READ-to-WRITE 的组合审批闭环。

目标架构不是让 LLM 自由调用工具，而是让 LLM 负责语义理解和表达，让 Registry、deterministic compiler/validator、PlanExecutor、RuleSet、Approval 与 Gateway 掌握执行权。建议按 10 个可独立验证的 Runbook 顺序实施，避免把“召回、规划、执行、计算、叙事、审批”混成一个大 change。

## 2. 代码事实基线

| 能力 | 当前事实 | 目标差距 |
|---|---|---|
| 意图识别 | `hybrid` 默认以 LLM 为主，仅 `LlmUnavailable` 回退规则；LLM 结果受 capability closed set 和参数白名单约束 | 模型候选上下文尚未统一经过真实 principal/visibility pre-filter |
| 能力决策 | 五态 `MatchDecision` 已实现，支持 `ESCALATE_TO_PLANNER`，multi-intent false `SELECT` 回归已关闭 | 决策、handoff、planner 未严格证明使用同一 `RegistrySnapshot` |
| 规划 | `CapabilityCard`、`GoalSpec`、`PlanDraft`/handoff、deterministic `PlanCompiler` 和 `PlanGraph` dry-run 已实现 | dry-run 不等于执行；handoff snapshot id 可能为空，failure 仍可能退化为 `dry_run=None` |
| 组合执行 | 无通用 `PlanExecutor` | 缺 ready-node 调度、durable node ledger、超时/取消、幂等与逐节点 Gateway 调用 |
| 组合输出 | 原子 `ReasoningFact` 已存在 | 缺 `ReasoningFact[] -> MaterialSupplySnapshot` 的确定性 `OutputProjection` |
| 建议 | `RecommendationPlan` 有架构契约，sandbox Action 纵切已验证 | 缺已注册 RuleSet、缺输入澄清以及由组合事实形成 Action proposal 的闭环 |
| 叙事 | 单能力 narrator 已受事实约束 | 缺跨节点 claims/evidence/limitations 契约和模板 fallback |
| 状态与流式 | durable Run/Session、trusted principal、durable approval、incremental SSE/reconnect 已归档 | 尚未承载 PlanExecution、Projection、Recommendation、Narrative、Action proposal 的完整事件模型 |

## 3. 核心领域模型

| 实体 | 责任 | 权威来源 |
|---|---|---|
| `TrustedPrincipal` | principal、role、tenant/data scope | 受信服务端注入 |
| `RegistrySnapshot` | 某次决策可见的 capability、fact type、relation、rule/projection 版本集合 | Registry publisher |
| `IntentEnvelope` | 用户目标、约束、参数、歧义和证据位置 | LLM candidate + deterministic normalization |
| `MatchDecision` | `SELECT` / `CLARIFY` / `SHOW_OPTIONS` / `REJECT` / `ESCALATE_TO_PLANNER` | deterministic matcher |
| `GoalSpec` / `PlanDraft` | 自然语言目标的 advisory 规划候选 | LLM 或 deterministic builder |
| `PlanGraph` | 可验证的多能力执行权威 | deterministic `PlanCompiler` |
| `PlanExecutionRecord` | 节点状态、输入绑定、重试、结果、lineage | durable `PlanExecutor` ledger |
| `ReasoningFact` | 标准化业务事实 | Gateway result normalizer |
| `OutputProjection` | 多事实到业务快照的确定性转换 | 注册 projection |
| `RecommendationPlan` | facts + RuleSet + user constraints 产生的建议 | deterministic rule engine |
| `ActionProposal` | 一个待审批的 WRITE capability 与完整参数快照 | recommendation layer |
| `NarrativeEnvelope` | claims、evidence refs、limitations 和状态叙事 | grounded narrator |
| `PlanApprovalRecord` | 对 plan/snapshot/action/parameters/facts/rules 的人审授权 | approval service |

关系约束：`IntentEnvelope` 只能引用同一 snapshot 可见的能力；`PlanGraph` 节点只能引用该 snapshot 中的已注册 capability；`OutputProjection` 只消费成功节点产生的 `ReasoningFact`；`RecommendationPlan` 只消费 projection、已注册 RuleSet 和用户显式约束；`ActionProposal` 不等于执行；`PlanApprovalRecord` 必须精确绑定 proposal，审批后 Gateway 仍做最终校验。

## 4. 目标数据流

```text
User utterance + durable conversation context
-> TrustedPrincipal + RegistrySnapshot
-> LLM-first IntentEnvelope candidate
-> visibility-filtered CapabilityCard recall
-> deterministic MatchDecision
   -> SELECT: existing single-capability CallPlan path
   -> CLARIFY / SHOW_OPTIONS / REJECT: no execution
   -> ESCALATE_TO_PLANNER:
      GoalSpec / PlanDraft candidate
      -> deterministic PlanCompiler + validation
      -> executable READ partition of PlanGraph
      -> PlanExecutor -> Gateway validate/execute per node
      -> ExecutionResult[] -> ReasoningFact[]
      -> deterministic OutputProjection
      -> registered RuleSet -> RecommendationPlan
      -> grounded NarrativeEnvelope
      -> optional single ActionProposal
      -> Human Approval
      -> exactly-once Action CallPlan -> Gateway -> SAP
```

任一阶段失败都以结构化状态停止，不允许 LLM 修补 capabilityId、参数、事实、关系、计算结果、审批或 execution identity。

## 5. 意图识别与能力召回

MVP 继续采用 **LLM-first hybrid**：LLM 负责理解自然语言、多目标、指代、省略和参数候选；规则路径只在 LLM 不可用时兜底。LLM 不是最终路由权威。`MatchDecision` 仍由 Registry/schema/governance/parameter-fit 的确定性校验产生。

候选召回顺序固定为：

```text
TrustedPrincipal
-> snapshot-bound visibility pre-filter
-> safe CapabilityCard projection
-> lexical/alias/example recall
-> bounded LLM rerank or clarification
-> deterministic MatchDecision
```

当前 capability 数量小，MVP 不引入 embedding、vector store 或 Knowledge/RAG。未来能力数量和 Eval bad case 达到阈值后，可在 safe cards 上增加 hybrid retrieval，但不得把 executor binding、凭据或不可见能力暴露给模型。

## 6. 多能力编排与执行

`GoalSpec` 和 `PlanDraft` 是建议，只有绑定 `RegistrySnapshot` 且通过 schema、关系、参数来源、拓扑与 governance 校验的 `PlanGraph` 才能进入执行。第一阶段仅执行 READ 节点；WRITE 节点在产生 proposal 前始终 `BLOCKED_APPROVAL`。

`PlanExecutor` 只做以下确定性工作：

- 从已验证 DAG 选取 ready nodes。
- 仅对无依赖且 `sideEffect=none` 的节点并发。
- 每个节点生成独立 `CallPlan` 并调用现有 Gateway `validate -> execute`。
- 将状态、重试、超时、取消、结果引用和 lineage 写入 durable ledger。
- snapshot 漂移、未知能力、缺参、越权、节点失败或恢复冲突一律 fail-closed。

MVP 首个场景固定为：

```text
MM.Inventory.GetAvailability
+ MM.PurchaseOrder.GetList
-> MaterialSupplySnapshot
-> RecommendationPlan
-> optional MM.PR.CreateDraft ActionProposal
```

第一版最多一个终点 Action。多 WRITE、Saga、自动补偿、自由 replan 和动态新增节点均为 Reserved。

## 7. 组合事实、建议与叙事

`MaterialSupplySnapshot` 不是 LLM 摘要，而是注册 `OutputProjection` 的确定性产物，至少包含：`asOf`、各来源 freshness、`completeness`、facts、lineage、missingFacts 和 limitations。必需节点失败、超时或取消时只能输出 `partial` / `incomplete`，不能伪装成完整供给结论。

库存和采购订单事实本身不足以推导 PR 数量、交付日期或采购组。建议层必须通过已注册 `RuleSet` 显式声明所需事实和用户约束；缺少需求量、目标日期、采购组或规则输入时返回 `CLARIFY` / `INSUFFICIENT_INPUT`，LLM 不得猜值。

`NarrativeEnvelope` 只组织语言，每个 claim 必须引用 fact/projection/rule/proposal id；limitations、partial 状态和 approval 状态必须可见。LLM 不可用时使用模板 narrator，保证事实和状态仍可展示。

## 8. Workbench 体验

Workbench 按同一 `runId` 展示：Intent、候选能力、`MatchDecision`、`PlanGraph`、节点状态、Facts、Projection、Recommendation、Narrative、Action proposal、Approval、Trace/Replay。UI 标签只说明展示状态，不能作为执行证明；执行证明来自 ledger、Gateway result、approval binding 和 trace。

SSE 在现有 cursor/reconnect 基础上增加 plan/node/fact/projection/recommendation/narrative/proposal/approval 事件。重连后必须按 sequence 重放且不得重复触发节点或 Action。

## 9. Knowledge/RAG 预留边界

Knowledge/RAG 作为未来 `EvidenceProvider` 保留接口，但 MVP：

- 不连接文档库、向量库或外部知识源。
- 不做跨会话相似问题检索。
- 不让 RAG 内容成为 capability、参数、权限、Fact、RuleSet 或审批权威。
- 若未来接入，只能产生带来源和 freshness 的补充 evidence，并通过独立 runbook、Eval 和治理门禁。

## 10. Runbook 拆分与依赖

| Runbook | 交付 | 状态 |
|---|---|---|
| 13 | governed context、visibility 与统一 RegistrySnapshot | `Planned` |
| 14 | LLM-first IntentEnvelope 与受治理能力召回 | `Planned` |
| 15 | advisory plan 到 deterministic PlanGraph v2 | `Planned` |
| 16 | READ PlanExecutor 与 durable node ledger | `Planned` |
| 17 | Composite Fact / OutputProjection | `Planned` |
| 18 | RuleSet、RecommendationPlan 与 ActionProposal | `Planned` |
| 19 | grounded narrative orchestration | `Planned` |
| 20 | Workbench plan/evidence experience | `Planned` |
| 21 | READ-to-WRITE approval 与 exactly-once Action | `Planned` |
| 22 | 端到端 Eval 与 release gate | `Planned` |

主依赖链：

```text
13 -> 14 -> 15 -> 16 -> 17 -> 18 -> 19 -> 20 -> 21 -> 22
```

Runbook 20 可提前做静态 UI contract spike，但正式集成必须等待 16-19 输出契约稳定。每个 Runbook 都应形成独立 OpenSpec/Comet change、测试、验证报告和归档记录，不能一次实施全部 10 项。

## 11. 全局验收边界

- 单能力路径不回退：现有 READ 与 sandbox Action contract 保持通过。
- 多目标请求不 false `SELECT`，候选不可见能力泄漏率为 0。
- planner、executor、projection、recommendation、narrative 全部绑定同一 snapshot/run/trace。
- 多 READ 可并发但只由 PlanGraph DAG 决定；失败节点不可被叙事隐藏。
- 每个业务结论可追溯到 `ReasoningFact` 和原始 execution evidence。
- 建议所需输入不足时澄清，不猜参数。
- WRITE 只形成一个 proposal；未经 Human Approval 不调用 Gateway execute。
- 批准后 Action 按已批准 hash exactly-once；snapshot/参数/fact/rule 漂移使审批失效。
- Knowledge/RAG 未接入时系统功能完整，不存在隐式依赖。

## 12. 实施决策

本文件只固化设计和未来实施顺序。当前不创建 OpenSpec change、不修改 runtime、不执行 SAP、不提交 git。下一次实施从 Runbook 13 开始，并在每个 Runbook 完成后重新评估后续契约，而不是预先锁死全部代码结构。

# Grounded Narrative Orchestration Specification

## Purpose

定义 Runbook 19 的 component/Eval 完整目标契约：从已归档 Runbooks 17-18 的 facts、`MaterialSupplySnapshot`、`RecommendationPlan` 与只读 proposal state 构建 grounded `NarrativeEnvelope`。该组件只组织和校验表达，不新增事实、不改变 recommendation/proposal、不创建审批、不接生产 orchestrator，也不执行 SAP WRITE。

## Domain model

- `NarrativeSourceInput` 聚合 `ReasoningFact[]`、`MaterialSupplySnapshot`、`RecommendationPlan` 和 `NarrativeProposalState`，这些对象构成唯一内容边界。
- `NarrativeContentItem` 是 deterministic input projection 产生的最小可改写单元，包含稳定 `claimId`、source kind/ref、source-provided content 与非空 evidence refs。
- `NarrativeCandidate` 是 model adapter 返回的 JSON，只能为每个既有 content item 提供一条改写，并保持 claim/source/evidence identity。
- `NarrativeEnvelope` 是 validator 接受 candidate 或 template fallback 后的完整输出，包含 summary、claims、evidence refs、limitations、recommendation/proposal refs、approval state 和 fallback 标记。
- `NarrativeProposalState` 仅表达外部提供的只读展示状态；它不等于 `ApprovalRecord`、Gateway result 或 SAP execution authority。

## Requirements

### Requirement: Narrative input projection has a closed source boundary

系统 SHALL 仅从显式传入的 `ReasoningFact[]`、`MaterialSupplySnapshot`、`RecommendationPlan` 和 `NarrativeProposalState` 构建 narrative input。builder SHALL 为 fact、projection、rule/recommendation、limitation 和 proposal state 内容生成稳定 typed item、source ref 与 evidence refs，并使用确定性排序。builder MUST NOT 读取 raw Gateway payload、conversation text、model output、外部检索内容、凭据或生产 orchestrator state。

#### Scenario: Complete governed inputs produce a closed content projection

- **WHEN** 输入包含 complete snapshot、可追溯 facts、RecommendationPlan 和 pending proposal state
- **THEN** builder 输出的每个 content item 都只引用这些输入对象
- **AND** 每个业务 content item 具有稳定 claim identity 和至少一个 evidence ref
- **AND** 相同语义输入即使 facts 顺序不同也产生相同 projection

#### Scenario: Untraceable input is rejected

- **WHEN** recommendation/proposal refs 与输入对象不一致，或业务 content 无可用 source/evidence ref
- **THEN** builder fail closed
- **AND** 不调用 model、不生成无依据 claim

### Requirement: NarrativeEnvelope preserves claims, evidence and state

系统 SHALL 输出 `NarrativeEnvelope`，至少包含 `summary`、`claims[]`、`evidenceRefs[]`、`limitations[]`、`recommendationRef`、`proposalRef`、`approvalState` 和 `templateFallbackUsed`。每个业务 claim MUST 引用一个或多个来自 input projection 的 evidence refs；顶层 evidence refs SHALL 是所有 claim refs 的稳定去重并集。limitations、recommendation ref、proposal ref 和 approval state MUST 直接来自 deterministic input projection，不能由 model 创建或修改。

#### Scenario: Every claim is traceable

- **WHEN** envelope 通过 validation
- **THEN** 每个 claim 的 source ref 和全部 evidence refs 都存在于 input projection
- **AND** claim grounding rate 为 100%
- **AND** unsupported claim rate 为 0

#### Scenario: Partial and limitation state remain visible

- **WHEN** projection completeness 为 `partial` 或 `incomplete`，或包含 freshness/missing-fact/limitation 信息
- **THEN** envelope 显式保留 completeness 和 limitations
- **AND** summary/claims 不得将该输入表述为 complete

### Requirement: LLM may only rewrite provided content through strict JSON

组件 SHALL 将 deterministic content projection 作为 model prompt 的完整内容边界，并要求 model 返回严格 JSON。candidate SHALL 与 content items 一一对应：claim IDs、source refs 和 evidence refs 必须完全相同且各出现一次；model 只能提供 localized rewritten text。未知、缺失、重复或改绑的 claim/source/evidence、额外状态/limitation 字段、空文本、invalid JSON 或错误 schema MUST 使整个 candidate 无效。candidate 文本 MUST NOT 成为 facts、projection、`RecommendationPlan`、`ActionProposal`、Approval 或 execution 的输入。

#### Scenario: Valid one-to-one rewrite is accepted

- **WHEN** model 返回有效 JSON，且每条 rewrite 的 identity/reference 与 input projection 完全一致
- **THEN** envelope 使用 model text
- **AND** `templateFallbackUsed=false`
- **AND** refs、limitations 和状态仍由 deterministic builder 提供

#### Scenario: Unsupported claim is rejected

- **WHEN** model 新增 claim、使用未知 evidence ref、删除既有 claim、重复 claim 或改变 source binding
- **THEN** candidate 整体无效
- **AND** 不部分接受 model 输出
- **AND** 最终 envelope 使用 deterministic template fallback

### Requirement: Deterministic template fallback is mandatory

model adapter 缺失、不可用、抛错、超时、返回空响应、invalid JSON 或 candidate validation 失败时，组件 SHALL 使用 deterministic template 生成完整 envelope。fallback SHALL 保留相同 claim/source/evidence identity、limitations、recommendation/proposal refs 和状态，并设置 `templateFallbackUsed=true`。相同 input projection 与 locale MUST 产生完全相同的 fallback envelope。

#### Scenario: Model failure preserves all governed content

- **WHEN** model unavailable 或抛错
- **THEN** facts、recommendation、limitations 和 proposal state 仍通过 template envelope 展示
- **AND** 不新增事实或状态
- **AND** fallback 结果可重放

#### Scenario: Invalid JSON falls back deterministically

- **WHEN** model 返回非 JSON、错误 schema 或无效 references
- **THEN** 最终结果等于同输入不调用 model 时的 template envelope
- **AND** 不泄漏或保留部分无效 model text

### Requirement: Localized state wording is explicit and non-authoritative

组件 SHALL 为中文和英文提供确定性状态文案，区分 projection `complete`/`partial`/`incomplete`、recommendation `RECOMMEND`/`NO_ACTION`/`CLARIFY`/`INSUFFICIENT_INPUT`，以及 proposal state `none`/`pending_approval`/`approved`/`executed`/`failed`。pending MUST NOT 表述为 approved，approved MUST NOT 表述为 executed；所有状态都必须绑定只读 state evidence ref。展示标签 MUST NOT 被当作审批或执行证据。

#### Scenario: Pending proposal is not approval

- **WHEN** proposal state 为 `pending_approval`
- **THEN** 中文显示“待审批”，英文显示 `pending approval`
- **AND** envelope 不包含“已批准”或“已执行”的含义
- **AND** 不创建 Human Approval

#### Scenario: Terminal state fixtures preserve supplied status

- **WHEN** fixture 提供 `approved`、`executed` 或 `failed` 的只读 proposal state 与 evidence ref
- **THEN** envelope 仅渲染该显式状态并保留 ref
- **AND** component 不执行状态转换、不生成 ApprovalRecord、不调用 Gateway/SAP

### Requirement: RecommendationPlan and ActionProposal remain immutable inputs

narrative component SHALL 把 `RecommendationPlan`、其 optional `ActionProposal` 以及 proposal state 视为只读输入。组件 MUST NOT 修改 recommendation status/hash、facts、rules、limitations、proposal parameters/hash/status，MUST NOT 根据 model text 生成或补齐 Action 参数，也 MUST NOT 提供 approval/execution API。

#### Scenario: Narrative generation has no business-state mutation

- **WHEN** 对含 `pending_approval` proposal 的 plan 生成 envelope
- **THEN** 输入 plan/proposal 深度不变
- **AND** 没有 ApprovalRecord、Gateway request、commit/rollback 或 SAP WRITE side effect

### Requirement: Eval proves grounding, fallback and status coverage

项目 SHALL 提供 versioned、可审查的 narrative Eval fixtures 与自动化测试，至少覆盖 complete、partial、clarify、proposal pending、approved、executed、failed、LLM unavailable、invalid JSON、unsupported/unknown reference 和 deterministic replay。Eval SHALL 计算业务 claims 的 grounding/unsupported 指标；完整 Eval matrix 的 claim grounding rate MUST 为 100%，unsupported claim rate MUST 为 0%。

#### Scenario: Narrative Eval matrix passes

- **WHEN** 运行 narrative focused tests 和 frontend verification
- **THEN** 所有成功、fallback、bad-case 和状态 fixtures 通过
- **AND** grounding rate 为 100%、unsupported claim rate 为 0%
- **AND** 既有 projection、recommendation 和 runtime tests 无回归

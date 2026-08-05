# Recommendation Decision Plan Specification

## Purpose

定义 Runbook 18 的 component/Eval 完整目标契约：确定性地将同一 RegistrySnapshot 下的 `MaterialSupplySnapshot`、已注册 versioned `RuleSet` 与用户显式约束转换为可解释、可重放的 `RecommendationPlan`，并在输入充分时最多形成一个尚未审批、不可执行的 `ActionProposal`。

## Requirements

### Requirement: Versioned RuleSet registry is snapshot-bound and fail-closed

系统 SHALL 提供按精确 `ruleSetId@version` 注册和解析的 `RuleSetRegistry`。每个 RuleSet SHALL 声明非空 `registrySnapshotId`、输入 `projectionId@version`、必需用户约束、最大 projection age、允许的 Action capability 和确定性策略。未知 id/version、相同 tuple 重复注册或冲突定义 MUST fail closed。Registry 和 RuleSet MUST NOT 调用 LLM、Gateway 或 SAP。

#### Scenario: Exact registered RuleSet resolves

- **WHEN** 调用方在绑定 snapshot 的 registry 中解析已注册的精确 `ruleSetId@version`
- **THEN** 返回包含 input、freshness、constraints、Action allowlist 和 strategy 的完整 declaration

#### Scenario: Unknown or conflicting RuleSet is rejected

- **WHEN** id/version 未注册，或相同 tuple 被重复/冲突注册
- **THEN** 返回结构化 registry failure
- **AND** 不产生 RecommendationPlan proposal

### Requirement: Decision input sufficiency is explicit

decision engine SHALL 在计算前验证 request、RuleSet、projection 与 proposal capability 属于同一个非空 RegistrySnapshot，并验证 projection 精确版本、`completeness=complete`、RuleSet freshness 上限、事实唯一性/单位以及 RuleSet 声明的 required constraints。缺少用户可补齐的 `requiredQuantity`、`targetDate` 或 `purchasingGroup` SHALL 输出 `CLARIFY` 和明确缺项。partial/incomplete/stale projection、snapshot/version 不一致、冲突事实或不支持的 Action SHALL 输出 `INSUFFICIENT_INPUT`。任一门禁失败均 MUST NOT 产生 proposal。

#### Scenario: Missing user constraints requests clarification

- **WHEN** projection 可用但缺 `requiredQuantity`、`targetDate` 或 `purchasingGroup`
- **THEN** plan status 为 `CLARIFY`
- **AND** `limitations` 明确列出缺失字段
- **AND** 系统不猜任何 Action 参数且不产生 proposal

#### Scenario: Partial or incomplete projection is blocked

- **WHEN** `MaterialSupplySnapshot.completeness` 为 `partial` 或 `incomplete`
- **THEN** plan status 为 `INSUFFICIENT_INPUT`
- **AND** projection limitations/missing facts 被保留为证据
- **AND** 不产生 proposal

#### Scenario: Stale projection is blocked by governed rule policy

- **WHEN** projection age 超过 RuleSet 显式声明的最大 age，或时间字段不可验证
- **THEN** plan status 为 `INSUFFICIENT_INPUT`
- **AND** engine 不使用隐藏 freshness 默认值
- **AND** 不产生 proposal

#### Scenario: Snapshot or Action registry mismatch is blocked

- **WHEN** request、projection、RuleSet 或 `MM.PR.CreateDraft` capability 不属于同一 snapshot，或 Action 未注册/不受 RuleSet 支持
- **THEN** plan status 为 `INSUFFICIENT_INPUT`
- **AND** 不产生 proposal、ApprovalRecord 或执行调用

### Requirement: RecommendationPlan is deterministic and explainable

engine SHALL 输出单个 `RecommendationPlan`，状态仅为 `RECOMMEND`、`NO_ACTION`、`CLARIFY` 或 `INSUFFICIENT_INPUT`。plan SHALL 列出 `facts`、`rules`、`assumptions`、`limitations` 和 `rejectedAlternatives`，并绑定 projection、snapshot 和 RuleSet refs。相同语义输入（包括 facts 顺序变化）MUST 产生相同 recommendation id/hash 和内容。

#### Scenario: Reordered facts replay identically

- **WHEN** 两次输入仅 facts 顺序不同，其他 projection、RuleSet、constraints 和 evaluation time 相同
- **THEN** 两次 RecommendationPlan 深度相等
- **AND** recommendation id/hash 相同

#### Scenario: Sufficient stock yields no action

- **WHEN** 唯一 `availableQuantity` 大于或等于用户 `requiredQuantity`
- **THEN** status 为 `NO_ACTION`
- **AND** plan 保留 facts、rules 和 rejected alternatives
- **AND** 不产生 ActionProposal

### Requirement: Shortage rule may form at most one pending ActionProposal

当精确注册的 material-shortage RuleSet 命中、所有 input sufficiency 门禁通过且 `availableQuantity < requiredQuantity` 时，engine SHALL 形成一个且仅一个 `MM.PR.CreateDraft` proposal。quantity SHALL 等于 `requiredQuantity - availableQuantity`；`material`、`plant` 和 `unit` SHALL 来自唯一受治理 availability fact；`delivery_date` 和 `purchasing_group` SHALL 来自用户显式约束。proposal status MUST 为 `pending_approval`，并包含完整 `parameterSources`、`factsUsed`、`ruleSetRefs` 与 deterministic `proposalHash`。

#### Scenario: Shortage produces replayable proposal

- **WHEN** complete/fresh projection 中唯一 availability fact 为 7 EA，用户约束为需要 10 EA、目标日期和采购组均明确，且 Action 在同 snapshot 注册
- **THEN** plan status 为 `RECOMMEND`
- **AND** 唯一 proposal 的 quantity 为 3、status 为 `pending_approval`
- **AND** 六个 Action 参数均有来源，proposal 引用使用的 fact 和 RuleSet

#### Scenario: PO ordered quantity is not guessed as available supply

- **WHEN** snapshot 同时包含 PO `orderQuantity` facts，但缺少交付日期、未清量或收货状态语义
- **THEN** shortage quantity 不自动扣减 PO 数量
- **AND** plan 将该候选计算记录为 rejected alternative

### Requirement: Component has no execution authority

recommendation component SHALL 只返回数据，不创建 ApprovalRecord，不调用 orchestrator、Gateway、JCo、OData 或 SAP，也不提供执行 `ActionProposal` 的 API。ActionProposal MUST NOT 被当作 Human Approval 或 SAP WRITE 证据。

#### Scenario: Proposal creation has no side effect

- **WHEN** engine 形成 `pending_approval` proposal
- **THEN** 仅返回 RecommendationPlan 数据
- **AND** 没有 Gateway/SAP 调用、commit/rollback、审批记录或 durable execution side effect

### Requirement: Eval covers success, clarification, no-action and fail-closed cases

项目 SHALL 提供可审查的 recommendation Eval cases 和自动化测试，至少覆盖：shortage proposal、sufficient-stock no action、缺三类用户约束、partial/incomplete、stale projection、unknown RuleSet、conflicting RuleSet、snapshot mismatch、unsupported Action、fact conflict/unit mismatch、deterministic replay、最多一个 proposal和无执行 side effect。

#### Scenario: Eval matrix passes

- **WHEN** 运行 recommendation focused tests 和 frontend verification
- **THEN** 所有 success/bad cases 通过
- **AND** 既有 projection、executor、Workbench/runtime 测试无回归

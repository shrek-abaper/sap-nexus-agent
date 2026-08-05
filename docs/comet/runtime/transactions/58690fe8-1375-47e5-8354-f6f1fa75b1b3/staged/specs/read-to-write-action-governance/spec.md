# Read-to-Write Action Governance Specification

## Purpose

定义 Runbook 21 的完整目标行为：把同一受治理 run 中的 READ PlanGraph、执行事实、确定性 projection/recommendation 与唯一 `ActionProposal` 绑定为可核验的 Human Approval subject，并在批准后通过完整重校验、durable idempotency 与 Gateway atomic claim 最多执行一次已注册的 `MM.PR.CreateDraft` Action。

## Requirements

### Requirement: PlanApprovalRecord binds the complete immutable action subject

系统 SHALL 为唯一、已注册的 ActionProposal 创建不可变 `PlanApprovalRecord`。记录 MUST 绑定 `runId`、`planId` 与 plan hash、非空 `snapshotId`、`actionNodeId`、`capabilityId@version`、canonical parameter hash、fact-set hash、projection id/version/output hash、精确 RuleSet refs、proposal id/hash、run-owner principal、confirming principal、decision/expiry timestamps、revocation data、status 与 separation-of-duty result。所有引用 MUST 属于同一 run/snapshot，且 plan MUST 只有一个终点 Action node。创建 pending record MUST NOT 调用 Gateway execute。本 MVP 的 confirming principal MUST 等于 run owner，`separationOfDutyResult` SHALL 为 `not_applicable`。

`PlanApprovalRecord` SHALL 扩展或封套既有原子 `ApprovalRecord`，共用 approval identity、durable lifecycle 与 parameter snapshot；系统 MUST NOT 建立第二套独立审批权威。

#### Scenario: Complete proposal creates one pending approval subject

- **WHEN** 同一 snapshot 的 READ plan 已完成，projection 为 complete/fresh，RecommendationPlan 含唯一受支持的 `MM.PR.CreateDraft` proposal，且所有 subject refs/hash 可验证
- **THEN** 系统持久化一个 status 为 `pending` 的 PlanApprovalRecord
- **AND** 记录包含完整 plan/fact/projection/rule/proposal/parameter 与 actor 绑定
- **AND** Gateway WRITE execute 调用数为 0

#### Scenario: Incomplete or inconsistent subject cannot become approvable

- **WHEN** plan 含零个或多个 Action node，或任一 required ref/hash 缺失、跨 run、跨 snapshot、不可解析或不一致
- **THEN** 系统返回结构化 `APPROVAL_SUBJECT_INVALID`/等价错误
- **AND** 不创建可批准记录、不调用 Gateway WRITE

### Requirement: Human decision is server-authoritative and policy-governed

系统 SHALL 向 run owner 展示本次 Action 的 capability、不可变 canonical parameters、parameter sources、关键 facts/rules/projection/proposal refs、expiry 与 limitations，并要求用户显式选择 approve 或 reject。请求 SHALL 仅携带 approval identity 与 decision；confirming principal、tenant、role、data scope 和授权结果 MUST 来自 trusted server context。confirming principal MUST 是 run owner；其他 principal MUST 按既有 cross-principal isolation fail closed。

系统 SHALL 只允许 `pending` 记录被决定一次，记录真实 actor、时间、Human-in-the-loop policy、subject hash 与 `separationOfDutyResult=not_applicable`，并支持 rejected、expired 与 revoked 终态。UI 展示本身、chat sentence、ActionProposal、event、fixture 或模型输出 MUST NOT 充当审批证据或提供 approval token；只有服务端收到并验证 run owner 针对当前 approval identity 的显式 decision 才构成 Human Approval。

#### Scenario: Authorized human approves the exact subject

- **WHEN** 授权审批主体对仍为 pending、未过期且未撤销的 PlanApprovalRecord 提交 approve
- **THEN** 系统原子记录 approved actor/time/policy result
- **AND** 该记录只授权其绑定的一个 capability/version 与 canonical parameters

#### Scenario: Run owner explicitly confirms the displayed Action

- **WHEN** run owner 查看当前 PlanApprovalRecord 绑定的精确参数和依据后提交 approve
- **THEN** 系统记录该 trusted principal、decision time、subject hash 与 `separationOfDutyResult=not_applicable`
- **AND** 只有全部重校验通过后才允许 continuation

#### Scenario: Another principal cannot approve the run owner's Action

- **WHEN** 任一非 run-owner principal 尝试读取或决定该 PlanApprovalRecord
- **THEN** 系统按 cross-principal isolation fail closed
- **AND** 不返回 approval/run 数据、不改变状态且 Gateway WRITE execute 调用数为 0

#### Scenario: Unauthorized or repeated decision fails closed

- **WHEN** confirming principal 不是 run owner、tenant/role/data-scope 不允许、identity provider 不可用，或记录已被决定、过期或撤销
- **THEN** 系统拒绝该 decision 并返回不泄密的结构化原因
- **AND** 不改变 approval subject、不调用 Gateway WRITE

### Requirement: Continuation revalidates every governed binding

approved continuation 在构造 Action CallPlan 或调用 Gateway 前 MUST 从 durable authoritative state 重新加载并验证：principal/tenant/role/data-scope、approval status/expiry/revocation、run ownership、snapshot、plan/action node、capability status/version/governance、canonical parameters/hash、facts/fact-set hash、projection id/version/output hash、RuleSet refs/versions、proposal id/hash 与 approval subject hash。任一对象缺失、变更、stale、被撤销或不一致 MUST fail closed，且不得用当前值静默更新已批准 subject。

#### Scenario: Unchanged approved subject may continue

- **WHEN** approved record 的全部 actor、lifecycle、snapshot、plan、Action、parameter、fact、projection、RuleSet 与 proposal 绑定仍精确匹配
- **THEN** 系统可构造唯一 `MM.PR.CreateDraft` Action CallPlan
- **AND** CallPlan 只含 Registry 允许的 `capabilityId` 与已批准 parameters，不含 request-provided RFC/binding

#### Scenario: Any drift blocks before Gateway execute

- **WHEN** snapshot、plan、action node、capability/version/status、parameters、facts、projection、RuleSet 或 proposal 任一值/hash 与 approval subject 不同，或证据已 stale/revoked
- **THEN** continuation 返回对应的结构化 stale/mismatch/revoked 错误
- **AND** Gateway WRITE execute 调用数为 0
- **AND** 旧 approval 不可通过重新计算 hash 被复活

### Requirement: Single Action continuation is exactly-once across retries and recovery

系统 SHALL 从 approval identity、proposal hash 与 canonical parameter hash 派生稳定的 continuation idempotency identity。执行顺序 MUST 至少包含 durable completed-result lookup、run/continuation lease 或等价原子占用、Gateway approval atomic claim、单次 execute 和 durable ActionResult 记录。并发、重复提交、SSE reconnect、进程重启或客户端 retry MUST NOT 产生第二次 Gateway WRITE execute。

#### Scenario: First approved continuation executes once

- **WHEN** 首次 continuation 通过全部重校验并成功取得 durable lease 与 Gateway approval claim
- **THEN** 系统调用 Gateway validate/execute 一次并持久化 ActionResult、execution hash 与 trace refs
- **AND** approval 进入 executed 终态

#### Scenario: Completed retry returns the same result

- **WHEN** 相同 approval/subject 的 continuation 在执行完成后再次提交或跨重启恢复
- **THEN** 系统从 durable result lookup 返回同一个 ActionResult/identity
- **AND** Gateway WRITE execute 调用数保持为 1

#### Scenario: Concurrent or conflicting retry cannot double execute

- **WHEN** 两个 worker 并发处理同一 approval，或 retry 使用不同 proposal/parameter subject
- **THEN** 只有一个 worker 可取得执行权
- **AND** 其他请求返回已完成结果、明确的 in-progress 或 subject-conflict 状态
- **AND** 不进行第二次 Gateway WRITE execute

### Requirement: Gateway remains the final atomic WRITE guard

Gateway SHALL 继续只接受已注册 `capabilityId`，从 Registry 解析 binding，并在 dispatcher/SAP 前校验 approved record、expiry、capability/version、registry snapshot、canonical parameters/hash 与 duplicate/executing/executed 状态。Gateway SHALL 先原子 claim approval 再 dispatch，成功后持久化 executed；Action 失败 SHALL 产生结构化 ActionResult 并遵循既有 stateful JCo commit/rollback 契约。READ capability MUST NOT 因本能力调用 commit/rollback。

#### Scenario: Missing or mismatched approval never reaches dispatcher

- **WHEN** Gateway 收到无 approval、未批准/过期 approval、snapshot/capability/version/parameter hash 不匹配或已 claim/executed 的 WRITE request
- **THEN** Gateway 返回既有或扩展的结构化 approval error
- **AND** dispatcher/JCo/SAP 调用数为 0

#### Scenario: Registered approved Action uses the existing binding authority

- **WHEN** 唯一有效 approval request 通过 Gateway guard
- **THEN** Gateway 根据 `capabilityId` 解析受信 binding 并最多 dispatch 一次
- **AND** request/LLM 不能提供或覆盖 RFC name、bindingId 或 credentials

### Requirement: Approval lifecycle supports expiry, revocation and re-proposal

pending/approved record SHALL 在 expiry 后不可执行；授权撤销动作 SHALL 将尚未 executed 的 record 原子置为 revoked 或等价不可执行终态，并记录 actor、time、reason code。rejected、expired、revoked 或 stale record MUST NOT 恢复为 approved。业务仍需执行时 SHALL 基于当前 snapshot/facts/rules/parameters 生成新 proposal 与新 approval identity。

#### Scenario: Revocation wins before execution claim

- **WHEN** approval 在 Gateway atomic execution claim 之前被授权主体撤销
- **THEN** continuation 返回 revoked 状态且 Gateway WRITE execute 调用数为 0
- **AND** replay 显示撤销 actor/time/reason 的安全摘要

#### Scenario: Expired or stale action requires a new approval

- **WHEN** approval 已过期或任一受治理输入漂移
- **THEN** 系统不允许延长、改写或复用旧 approval
- **AND** 新执行意图必须形成新的 proposal/PlanApprovalRecord

### Requirement: Governed events and Workbench preserve approval/action evidence boundaries

系统 SHALL 在同一 `runId`/`traceId`/`snapshotId` 下追加 allowlisted、redacted 的 proposal-created、approval-pending/approved/rejected/expired/revoked、action-executing/executed/failed 事件，并关联 plan/node/fact/projection/recommendation/proposal/approval/ActionResult refs。Workbench SHALL 明确区分 proposal、Human Approval 与 execution evidence。refresh/reconnect/replay SHALL 只读取 durable events/results，不触发 decision、continuation 或 Gateway execute。

#### Scenario: Full trace is replayable without side effects

- **WHEN** 审计方按 trace/run 回放一个完成或拒绝的 READ-to-WRITE run
- **THEN** 可串联 intent、plan、READ nodes、facts、projection、recommendation、proposal、approval 与 ActionResult/SAP RETURN 安全摘要
- **AND** replay 不新增 decision、claim、Gateway 或 SAP 调用

#### Scenario: UI state is not execution authority

- **WHEN** Workbench 显示 pending/approved/executed label 或收到重复 SSE event
- **THEN** 状态只来自服务端 durable evidence
- **AND** label、button、fixture 或 event 本身不能授权或重放 Action

### Requirement: Verification proves fail-closed and exactly-once behavior without live SAP WRITE

项目 SHALL 提供自动化测试，至少覆盖 run-owner explicit approve/reject、UI 展示不自动批准、cross-principal/cross-tenant denial、expire、revoke、duplicate、unauthorized role/data-scope、stale snapshot、changed plan/action/capability/version/parameters/facts/projection/rules/proposal、concurrent workers、cross-restart recovery、Gateway guard、event replay 与 redaction。测试 MUST 断言所有未批准/漂移路径 Gateway WRITE execute 为 0，唯一批准路径最大为 1，并使用 fake/sandbox boundary。

#### Scenario: Governance verification matrix passes

- **WHEN** 运行 focused tests、frontend verify、Agent/PR Eval、Gateway tests、call-plan evidence 与 OpenSpec strict validation
- **THEN** 全部 acceptance/bad cases 通过且既有 READ、sandbox Action、durable runtime、PlanExecutor、projection/recommendation/narrative/Workbench 无回归
- **AND** 验证报告明确没有执行新的真实 SAP WRITE

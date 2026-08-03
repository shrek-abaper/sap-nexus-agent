## MODIFIED Requirements

### Requirement: ApprovalRecord 契约

系统 SHALL 定义 `ApprovalRecord`，记录审批对象（PR 参数快照 hash）、审批人、审批时间、过期时间、执行状态，以及 `registry_snapshot_id`（绑定生成该 approval 时 `GovernedContext` 的非空 `snapshotId`）。Agent 审计状态为 pending/approved/executed/rejected；Gateway 可使用内部 executing 状态表示已原子占用、不可重放。薄纵切下审批对象为用户确认的 PR 参数快照（material/plant/quantity/unit/delivery date/purchasing group），而非 RecommendationPlan 建议版本。`registry_snapshot_id` SHALL 在 pending 生成时从 `GovernedContext` 填入，使 approval 记录与同一 run 的 matcher/planner 共享同一 snapshot 标识；跨语言 approval store 的「漂移使审批失效」执行校验留 Runbook 21。

#### Scenario: 审批记录参数快照

- **WHEN** 用户确认 PR 参数并审批
- **THEN** 系统生成 `ApprovalRecord`，记录参数快照 hash、审批人、审批时间、过期时间、`registry_snapshot_id`，状态置为 `approved`

#### Scenario: ApprovalRecord 携带同快照标识

- **WHEN** orchestrator 生成 pending `ApprovalRecord`
- **THEN** `ApprovalRecord.registry_snapshot_id` 非空且等于 `GovernedContext.snapshotId`
- **AND** 与同一 run 的 matcher/planner 使用同一 `snapshotId`

#### Scenario: 审批过期

- **WHEN** execute 时 `ApprovalRecord` 已超过过期时间
- **THEN** 系统返回 `APPROVAL_EXPIRED`，不触发 SAP

#### Scenario: 审批参数版本不匹配

- **WHEN** execute 时当前 PR 参数与 `ApprovalRecord` 记录的参数快照 hash 不一致
- **THEN** 系统返回 `APPROVAL_VERSION_MISMATCH`，不触发 SAP

#### Scenario: Gateway 重算实际参数快照

- **GIVEN** ApprovalRecord 保存原参数与其 canonical SHA-256
- **WHEN** execute 请求沿用原 hash 但修改 quantity、plant 或其他实际参数
- **THEN** Gateway 重算 actual parameters hash 并返回 `APPROVAL_VERSION_MISMATCH`
- **AND** 不触发 SAP dispatch

#### Scenario: 伪造 approval 注册被拒绝

- **WHEN** `/approve` 缺少有效服务令牌，或 record 非 approved、capability 不匹配、TTL 超过 600 秒、stored parameters 与 hash 不一致
- **THEN** Gateway 拒绝注册且 ApprovalStore 不保存该记录

#### Scenario: 已消费 approval 不可重新注册

- **GIVEN** approvalId 已处于 executing 或 executed
- **WHEN** 受信调用方再次向 `/approve` 提交同一 approvalId
- **THEN** Gateway 返回冲突且不得把状态覆盖回 approved

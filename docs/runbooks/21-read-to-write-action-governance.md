# Read-to-Write Action Governance Runbook

## Document Version

| Field | Value |
|---|---|
| Runbook | `21-read-to-write-action-governance` |
| Version | `v0.1.0` |
| Status | `Planned` |
| Created / Updated | `2026-08-03` |
| Depends On | Runbooks 13, 15-20; archived sandbox write and durable approval foundations |
| Unblocks | Runbook 22 |

## 1. Goal

在多个 READ capability 形成事实和建议后，允许生成一个已注册 WRITE `ActionProposal`，经 Human Approval 后按批准快照 exactly-once 执行。

## 2. Current Baseline

- `MM.PR.CreateDraft` sandbox Action 已具备 approval、参数 snapshot hash、anti-replay、atomic claim、commit/rollback 和 trace。
- durable approval store、trusted principal 和 SSE continuation 已实现。
- 当前审批只覆盖原子 Action，尚未绑定多 READ plan、projection、facts 和 RuleSet。

## 3. Contracts and Data Flow

```text
PlanGraph + PlanExecutionRecord + MaterialSupplySnapshot
+ RecommendationPlan + ActionProposal
-> PlanApprovalRecord
-> human approve/reject
-> revalidate principal/snapshot/plan/proposal/facts/rules/hash
-> exactly-once Action CallPlan
-> Gateway validate -> execute -> ActionResult
```

`PlanApprovalRecord` 必须绑定 `planId`、`snapshotId`、`actionNodeId`、`capabilityId/version`、parameter hash、facts/projection hash、RuleSet versions、proposal hash、approver、expiry 和 separation-of-duty result。

## 4. Scope and Non-goals

- Scope：单终点 Action proposal、plan-aware approval、staleness/revocation、exactly-once continuation、审计回放。
- Non-goal：不支持多 WRITE、Saga、自动补偿、自动审批、生产 client 自动提交或 approval token 由模型携带。

## 5. Safety Boundaries

- 未审批、过期、主体不符、hash/snapshot/fact/rule 漂移时不调用 Gateway execute。
- READ 计划成功不等于 Action 获批；建议也不等于动作。
- approval 只授权一个 capability 和一份不可变参数快照。
- Gateway 保持最终 `capabilityId -> bindingId`、approval 与参数 hash 校验权威。

## 6. Acceptance Criteria

- approve/reject/expire/revoke/duplicate/cross-principal/stale snapshot/changed parameter/fact/rule 全部有测试。
- 未批准路径的 Gateway WRITE 调用数为 0。
- 批准后 Action 最多执行一次，重复 continuation 返回已有结果或冲突状态。
- trace 可串起 intent、plan、read nodes、facts、projection、recommendation、proposal、approval、Action 和 SAP RETURN。

## 7. Verification

```bash
.venv/bin/python -m pytest agent/tests -q
npm --prefix frontend run verify
.venv/bin/python -m sap_nexus_agent.eval evals/pr_create_cases.json
scripts/verify-agent-callplan-evidence.sh
openspec validate --all --strict
```

本 runbook 的实现与测试默认使用 fake/sandbox boundary；任何新的真实 SAP WRITE 都需要用户另行明确确认。

## 8. Next Start Here

复用现有 sandbox Action contract，不新建第二套 approval/Gateway。完成后由 Runbook 22 做三等级端到端 release gate。

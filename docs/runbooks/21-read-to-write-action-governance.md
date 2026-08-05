# Read-to-Write Action Governance Runbook

## Document Version

| Field | Value |
|---|---|
| Runbook | `21-read-to-write-action-governance` |
| Version | `v0.2.0` |
| Status | `Completed / Archived` |
| Created / Updated | `2026-08-03 / 2026-08-05` |
| Depends On | Runbooks 13, 15-20; archived sandbox write and durable approval foundations |
| Unblocks | Runbook 22 |
| Archive | `docs/comet/archive/2026-08-05-sap-nexus-read-to-write-action-governance/` |

## 1. Goal

在多个 READ capability 形成事实和建议后，允许生成一个已注册 WRITE `ActionProposal`，经 Human Approval 后按批准快照 exactly-once 执行。

## 2. Delivered Baseline

- `MM.PR.CreateDraft` sandbox Action 已具备 approval、参数 snapshot hash、anti-replay、atomic claim、commit/rollback 和 trace。
- `PlanApprovalRecord` 已将同一 run 的 plan、snapshot、Action node、capability/version、canonical parameters、facts、projection、RuleSets、proposal、owner、expiry/revocation 与 subject hash 绑定到既有 durable approval authority。
- Human Approval 是 run owner 对所展示不可变 Action subject 的单用户 Human-in-the-loop confirmation，不是多人协同审批流；`confirmingPrincipal == runOwner`，`separationOfDutyResult=not_applicable`。
- approved continuation 会从 durable authoritative state 重新加载并校验全部受治理绑定，再通过 continuation lease、Gateway atomic claim 与 durable result lookup 保证跨重试/重启 exactly-once。
- Workbench 只在服务端 durable pending evidence 存在时显示确认操作；浏览器只提交 `approvalId` 和 decision，身份与授权上下文来自 trusted server context。

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

归档验证结果：frontend 42 files / 405 tests 与 production build 通过；Agent 959 passed / 1 skipped；PR Eval 9/9；Gateway `BUILD SUCCESSFUL`；call-plan evidence 通过；OpenSpec 20 passed / 0 failed；Native acceptance 35/35 passed。

本 runbook 的实现与测试仅使用 fake/sandbox boundary，没有执行新的真实 SAP WRITE；任何 live SAP WRITE 仍需要用户针对精确 capability 与不可变参数快照另行明确确认。

## 8. Next Start Here

从 `22-end-to-end-agent-eval-release-gate.md` 开始建立 L1/L2/L3 三等级端到端 release gate。Runbook 21 的归档不能替代 Runbook 22 的 production orchestration、live smoke 或发布成熟度证明。

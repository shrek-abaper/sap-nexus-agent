# Workbench Plan and Evidence Experience Runbook

## Document Version

| Field | Value |
|---|---|
| Runbook | `20-workbench-plan-evidence-experience` |
| Version | `v0.2.0` |
| Status | `Implemented / Archived` |
| Created / Updated | `2026-08-03 / 2026-08-05` |
| Depends On | Runbooks 16-19 |
| Unblocks | Runbooks 21-22 |

## 1. Goal

让 Workbench 以同一 run/trace 展示完整 Agent 决策链：能力召回、PlanGraph、节点执行、Facts、Projection、Recommendation、Narrative、Action proposal、Approval 与 Replay。

## 2. Current Baseline

- Workbench 保持单能力 timeline、artifacts、MatchDecision、dry-run preview、legacy approval、batch 和 cursor SSE reconnect。
- 新增的 governed event projector、durable replay reducer 和八分区 plan/evidence workspace 已在 fixture/component integration 范围落地；生产 multi-capability orchestrator 仍未接线。

## 3. Contracts and Data Flow

新增 SSE 事件族：`intent_recognized`、`capability_recalled`、`plan_compiled`、`plan_node_state`、`fact_emitted`、`projection_completed`、`recommendation_completed`、`narrative_completed`、`action_proposed`、`approval_updated`、`action_executed`。所有事件包含 `runId`、`traceId`、`sequence`、`snapshotId` 和对象引用。

Workbench 分区：Conversation、Intent/Recall、Plan、Execution、Evidence、Recommendation/Narrative、Action/Approval、Trace/Replay。移动端以顺序卡片呈现，桌面端可并排查看 plan 与 evidence。

## 4. Scope and Non-goals

- Scope：事件 schema、allowlist/redaction event projection、durable replay、PlanGraph/ledger/evidence 展示、proposal/approval 状态分离、无障碍与移动端。
- Non-goal：UI 不做 plan 编译、事实计算、参数补全、审批推断或执行授权；本 Runbook 不创建 ApprovalRecord、不调用 Gateway/SAP、不执行 WRITE。

## 5. Safety Boundaries

- 前端不接收 technical binding、credential、raw SAP payload 或不可见 capability。
- reconnect 只重放事件，不重复触发节点或 Action。
- approval 按钮提交 proposal/approval id；服务端重新校验 principal、hash 和状态。
- UI 标签不可被记录为 execution evidence。

## 6. Acceptance Criteria

- 单能力、多 READ、partial failure 和 READ-to-WRITE proposal 四类 run 可完整展示。
- 刷新/断线重连后事件顺序、节点状态和 approval 状态一致。
- 每个 narrative claim 可跳转到 evidence；每个节点可查看 CallPlan/result/trace 的安全摘要。
- desktop/mobile、loading/empty/error/replay 状态通过组件和端到端测试。

## 7. Verification

```bash
npm --prefix frontend run verify
.venv/bin/python -m pytest agent/tests -q
scripts/verify-agent-callplan-evidence.sh
openspec validate --all --strict
```

## 8. Next Start Here

Runbook 20 已通过 Native change `sap-nexus-workbench-plan-evidence-experience` 完成并归档。下一实施入口为 Runbook 21：建立 proposal-to-ApprovalRecord 与 exactly-once single Action 闭环；必须重新取得并校验 Human Approval，不得把本 Runbook 的 `pending_approval` fixture、event 或 UI 标签当成授权。

## Session Closeout - 2026-08-05

### Completed

- 新增 11 个 snapshot-bound governed event types、稳定阶段排序、typed object refs、顶层字段 allowlist、递归 technical-field rejection 与敏感值 redaction。
- JSONL store 在 save/append 前拒绝 run mismatch、duplicate 和 sequence gap；replay reducer 对 identical duplicate 幂等，并显式暴露 conflict/gap/corrupt reference。
- Workbench 新增 Conversation、Intent/Recall、Plan、Execution、Evidence、Recommendation/Narrative、Action/Approval、Trace/Replay 八分区，支持 plan/node/fact 引用导航、结构化 limitations、claim grounding 和 safe node summaries。
- 四类 fixtures 覆盖 legacy single-capability、multi-READ、partial failure 与 READ-to-WRITE proposal；proposal-only 保持只读，不产生 ApprovalRecord、approval control、Gateway request 或 SAP WRITE。
- 修复 fire-and-forget runner 在测试清除 in-flight run 后写出 orphan terminal event 的生命周期缺陷；已删除的 run 被视为取消，存在的 run 仍记录真实 `run_failed`。

### Verified

- `npm --prefix frontend run verify`：37/37 Vitest files、380/380 tests、TypeScript 与 Next.js production build 通过。
- Playwright fixture replay：desktop/mobile 八分区可访问；390px viewport 无水平溢出、语义顺序不变、console 0 errors；proposal-only 完整消费 terminal event 且无 approve/reject control。
- 其余 Agent、CallPlan 与 OpenSpec 回归结果记录在 Native archive verification report；全部验证均未调用 Gateway、JCo、OData 或 SAP WRITE。

### Boundaries / Next

- 本次交付是 event contract + durable replay + component/UI integration，不是 production multi-capability orchestration 或 live E2E composition 证明。
- `ActionProposal.pending_approval` 不是 Human Approval；proposal-to-approval、exactly-once Action 与 SAP WRITE 仍由 `docs/runbooks/21-read-to-write-action-governance.md` 独立治理。

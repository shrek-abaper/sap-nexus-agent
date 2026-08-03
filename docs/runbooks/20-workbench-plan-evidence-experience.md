# Workbench Plan and Evidence Experience Runbook

## Document Version

| Field | Value |
|---|---|
| Runbook | `20-workbench-plan-evidence-experience` |
| Version | `v0.1.0` |
| Status | `Planned` |
| Created / Updated | `2026-08-03` |
| Depends On | Runbooks 16-19 |
| Unblocks | Runbooks 21-22 |

## 1. Goal

让 Workbench 以同一 run/trace 展示完整 Agent 决策链：能力召回、PlanGraph、节点执行、Facts、Projection、Recommendation、Narrative、Action proposal、Approval 与 Replay。

## 2. Current Baseline

- Workbench 已展示单能力 timeline、artifacts、MatchDecision、dry-run preview、approval、batch 和 cursor SSE reconnect。
- 当前没有真实多节点 ledger、组合 facts/projection/recommendation/narrative/proposal 的统一视图。

## 3. Contracts and Data Flow

新增 SSE 事件族：`intent_recognized`、`capability_recalled`、`plan_compiled`、`plan_node_state`、`fact_emitted`、`projection_completed`、`recommendation_completed`、`narrative_completed`、`action_proposed`、`approval_updated`、`action_executed`。所有事件包含 `runId`、`traceId`、`sequence`、`snapshotId` 和对象引用。

Workbench 分区：Conversation、Intent/Recall、Plan、Execution、Evidence、Recommendation/Narrative、Action/Approval、Trace/Replay。移动端以顺序卡片呈现，桌面端可并排查看 plan 与 evidence。

## 4. Scope and Non-goals

- Scope：事件 schema、durable replay、PlanGraph/ledger/evidence 展示、approval control、无障碍与移动端。
- Non-goal：UI 不做 plan 编译、事实计算、参数补全、审批推断或执行授权。

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

可以先做静态契约 fixture，但正式集成必须等 Runbooks 16-19 稳定。完成后进入 Runbook 21 的真实 proposal/approval continuation。

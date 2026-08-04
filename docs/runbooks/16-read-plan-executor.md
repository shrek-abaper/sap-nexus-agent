# Read Plan Executor Runbook

## Document Version

| Field | Value |
|---|---|
| Runbook | `16-read-plan-executor` |
| Version | `v0.1.0` |
| Status | `Implemented / Archived` |
| Created / Updated | `2026-08-04` |
| Depends On | Runbook 15; P0B durable runtime foundation |
| Unblocks | Runbook 17 |

## 1. Goal

实现只消费已验证 `PlanGraph` 的 READ `PlanExecutor`，通过 durable node ledger 完成 ready-node 调度、并发、超时、取消、恢复和幂等重放。

## 2. Current Baseline

- 单能力 `CallPlan -> Gateway validate -> execute -> ExecutionResult -> ReasoningFact` 已稳定。
- durable Run/Session、ownership/lease 和 incremental SSE 已存在。
- 当前没有多能力节点执行器；planner 只产 dry-run。

## 3. Contracts and Data Flow

节点状态固定为：`READY`、`VALIDATING`、`EXECUTING`、`SUCCEEDED`、`FAILED`、`TIMED_OUT`、`CANCELLED`、`BLOCKED_DEPENDENCY`、`BLOCKED_APPROVAL`。每次状态转换记录 sequence、attempt、input hash、result ref 和 trace span。

```text
validated PlanGraph readPartition
-> claim plan lease
-> select dependency-free READY nodes
-> per-node CallPlan
-> Gateway validate -> execute
-> ExecutionResult -> ReasoningFact
-> durable ledger + SSE
```

## 4. Scope and Non-goals

- Scope：READ nodes、有限并发、timeout/cancel、durable ledger、restart recovery、idempotent continuation、node-level trace。
- Non-goal：不执行 Action、不自动 replan、不做 Saga/补偿、不绕过现有 Gateway。

## 5. Safety Boundaries

- executor 只接受 validator 签名/状态有效且 snapshot 未漂移的 PlanGraph。
- `sideEffect != none` 或 `requiresApproval=true` 节点保持 `BLOCKED_APPROVAL`。
- 并发只由 DAG 独立性决定；模型并行 tool calls 没有调度权。
- retry 必须复用幂等键；恢复不能重复调用已成功节点。

## 6. Acceptance Criteria

- 两个独立 READ 节点可并发并各自经过 Gateway validate/execute。
- dependency、timeout、cancel、partial failure、restart 和 lease conflict 有确定性测试。
- ledger 与 SSE 重放一致；相同 continuation 不重复执行节点。
- Action 节点、snapshot drift 和非法状态转换全部在 Gateway 前阻断。

## 7. Verification

```bash
.venv/bin/python -m pytest agent/tests -q
npm --prefix frontend run verify
scripts/verify-agent-callplan-evidence.sh
openspec validate --all --strict
```

如需 live READ smoke，必须沿用现有受控 capability 和环境配置；本 runbook 不授权任何 SAP WRITE。

## 8. Next Start Here

先用 fake Gateway 完成状态机和恢复测试，再运行现有 READ integration。成功后进入 Runbook 17，仍不生成业务建议。

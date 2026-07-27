## Context

`continue_action` 审批流有完整服务层接续：`run_query` -> `awaiting_approval`（approval_record）-> `outcome_to_workbench_dict` 序列化 approvalRecord -> 前端 `pendingOutcome` 持有 -> 用户 approve -> `ApprovalContinuation` 回传（callPlan+validationResult+approvalRecord）-> runner 调 `continue_action`。`continue_batch` 缺这套接续：`combinations` 未序列化、无 continuation 类型、无 CLI 入口、零调用方。

## Goals / Non-Goals

**Goals**:
- `awaiting_batch_confirm` outcome 序列化 `combinations` + `callPlan` 到 workbench dict。
- 前端 `pendingOutcome` 持有 combinations；用户确认 -> `BatchContinuation` 回传 -> 调 `continue_batch`。
- CLI `--continue-batch` 入口。
- API route / SSE 支持 batch continuation。
- 端到端：Turn N 多值 -> awaiting_batch_confirm；Turn N+1 确认 -> continue_batch -> 批量聚合结果。

**Non-Goals**:
- 不改 orchestrator/selector/narrator 核心逻辑（已实现）。
- 不实现 WRITE 批量（continue_batch 仅 READ，Action 落到 awaiting_approval）。
- 不改 capability 契约。
- 不改 Action 审批流。
- 不做服务端 BatchRecord（reads 无状态，前端持有回传，类比 approval）。

## Decisions

### D1: combinations 前端持有回传（类比 approvalRecord）
`outcome_to_workbench_dict` 序列化 `combinations` + `callPlan`。前端 `AgentRunRecord.pendingOutcome` 持有（与 approval 相同机制）。用户确认 -> `BatchContinuation`（callPlan + combinations）回传。无服务端状态（reads 无状态，与 approval 审批流的 pendingOutcome 持有一致）。

### D2: 显式 continuation（类比 approve）
不自动检测"确认"文本。前端检测 `status="awaiting_batch_confirm"` + 用户点确认按钮 -> 发 `BatchContinuation`。CLI `--continue-batch` 标志（类比 `--continue-action`）。可靠且与 approval 一致。

### D3: continue_batch READ-only 不变
`continue_batch` 已有 READ-only 守卫（ValueError on Action）。batch continuation 仅对 READ capability（inventory）。Action + multi_parameters 仍走 awaiting_approval（run_query 守卫已保证）。

### D4: API route / SSE
batch continuation 复用 approval continuation 的端点模式（或并行新端点，design 阶段细化）。SSE 增加 `awaiting_batch_confirm` 状态事件（类比 `awaiting_approval`）。

## Risks / Trade-offs

- 前端持有 combinations：与 approval 一致，但 combinations 可能较大（≤20 组合，每组合小 dict）。可接受。
- API route 设计（复用 vs 新端点）需 design 阶段细化。
- SSE 状态扩展：`AgentRunState` 增加 `awaiting_batch_confirm`（类比 `awaiting_approval`）。
- 跨轮 combinations 完整性：前端持有，无服务端校验（类比 approval 的 approvalRecord 前端持有）。READ 操作无安全风险。

## Migration Plan

1. `workbench_output.py`：序列化 combinations。
2. `agent-runtime-adapter.ts`：WorkbenchOutcome.combinations + BatchContinuation + 路由。
3. `cli.py`：--continue-batch。
4. API route / SSE：batch continuation 端点 + awaiting_batch_confirm 状态。
5. 测试 + e2e。

## Open Questions

1. API route：复用 approval continuation 端点 vs 新增 batch continuation 端点？（design 阶段细化）
2. SSE `awaiting_batch_confirm` 状态事件设计？（design 阶段细化）

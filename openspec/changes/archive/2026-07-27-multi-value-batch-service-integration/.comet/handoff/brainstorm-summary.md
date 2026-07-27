# Brainstorm Summary

- Change: multi-value-batch-service-integration
- Date: 2026-07-27

## 确认的技术方案

A+A 全类比 `continue_action` 审批流：
- **workbench_output.py**：`outcome_to_workbench_dict` 序列化 `combinations`（类比 approvalRecord）。
- **agent-runtime-adapter.ts**：`WorkbenchOutcome.combinations` + `BatchContinuation`（callPlan + combinations）+ pendingOutcome 持有 + runner 按 continuation type 分派（approval -> continue_action；batch -> continue_batch）。
- **cli.py**：`--continue-batch`（类比 `--continue-action`）。
- **API route / SSE**：同一 agent-runs 端点 + continuation 类型判别；`AgentRunState` 增加 `awaiting_batch_confirm`（类比 `awaiting_approval`）+ 状态事件。
- **continue_batch**：已实现，接上调用方。

## 关键取舍与风险

- combinations 前端持有回传（≤20 组合，小 dict），与 approval pendingOutcome 一致；reads 无状态，无服务端 BatchRecord。
- continuation 类型判别：runner 按 type 字段分派（`approval` vs `batch`）。
- READ-only：continue_batch 守卫已保证（ValueError on Action）；batch continuation 仅 READ。
- 风险：前端 combinations 完整性由前端持有保证（无服务端校验，类比 approval approvalRecord）；READ 操作无安全风险。

## 测试策略

- Python：`test_workbench_output`（combinations 序列化）+ `test_orchestrator`（continue_batch 接续）+ `test_conversation_context`（awaiting_batch_confirm lastContext=None，已 hotfix）。
- Frontend：`agent-runtime-adapter` 测试（BatchContinuation 路由）+ API route 测试。
- e2e：Turn N 多值 -> awaiting_batch_confirm + combinations；Turn N+1 --continue-batch -> 批量聚合结果。
- `npm --prefix frontend run verify` + `scripts/verify-agent-callplan-evidence.sh`。

## Spec Patch

delta spec MODIFIED "Multi-value query split"：
- `Scenario: awaiting_batch_confirm serializes combinations to workbench`
- `Scenario: continue_batch service entry executes confirmed batch`（端到端）

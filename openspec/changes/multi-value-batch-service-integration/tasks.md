## 1. workbench 序列化 combinations

- [x] 1.1 `outcome_to_workbench_dict` 序列化 `combinations`（类比 approvalRecord，line 44）
- [x] 1.2 测试：awaiting_batch_confirm outcome -> workbench dict 含 combinations + callPlan
- [x] 1.3 测试：非 awaiting_batch_confirm outcome -> combinations=None

## 2. 前端 agent-runtime-adapter BatchContinuation

- [ ] 2.1 `WorkbenchOutcome` 增加 `combinations` 字段
- [ ] 2.2 新增 `BatchContinuation` 类型（callPlan + combinations）
- [ ] 2.3 `awaiting_batch_confirm` -> pendingOutcome 持有 combinations
- [ ] 2.4 用户确认 -> BatchContinuation 回传 -> 调用 continue_batch（类比 ApprovalContinuation -> continue_action）
- [ ] 2.5 测试：awaiting_batch_confirm pendingOutcome 持有；确认 -> continue_batch 调用

## 3. CLI --continue-batch

- [ ] 3.1 `cli.py` 新增 `--continue-batch` 标志（类比 `--continue-action`）
- [ ] 3.2 解析 callPlan + combinations JSON -> 调 `continue_batch(call_plan, combinations, gateway)`
- [ ] 3.3 测试：--continue-batch 调 continue_batch 返回批量结果

## 4. API route / SSE batch continuation

- [ ] 4.1 API route：batch continuation 端点（类比 approval continuation，design 阶段定复用 vs 新端点）
- [ ] 4.2 SSE：`awaiting_batch_confirm` 状态事件（AgentRunState + 事件类型，类比 awaiting_approval）
- [ ] 4.3 测试：API batch continuation 端到端

## 5. 验证

- [ ] 5.1 `openspec validate --all --strict` 通过
- [ ] 5.2 pytest 回归（workbench_output + cli + orchestrator）
- [ ] 5.3 `npm --prefix frontend run verify`（frontend 改动）
- [ ] 5.4 `scripts/verify-agent-callplan-evidence.sh` 通过
- [ ] 5.5 e2e：Turn N 多值 -> awaiting_batch_confirm + combinations 序列化；Turn N+1 确认 -> continue_batch -> 批量聚合结果

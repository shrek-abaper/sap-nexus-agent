---
comet_change: multi-value-batch-service-integration
role: technical-design
canonical_spec: openspec
archived-with: 2026-07-27-multi-value-batch-service-integration
status: final
---

# 多值批量确认服务层集成 Design Doc

> Canonical capability spec: `openspec/changes/multi-value-batch-service-integration/specs/agent-callplan-evidence/spec.md`。本文件是技术设计细化，不重复需求 spec。

## 1. Context

`continue_batch` 在生产代码零调用方；`combinations` 不跨轮携带；`awaiting_batch_confirm` 端到端不可用。hotfix 已止住"确认"死循环（last_context=None），但功能仍不可用。本 change 补服务层集成，全类比 `continue_action` 审批流。

## 2. Goals / Non-Goals

**Goals**：`awaiting_batch_confirm` -> 用户确认 -> `continue_batch` 端到端可用（CLI + workbench/SSE）。

**Non-Goals**：不改 orchestrator/selector/narrator 核心逻辑；不实现 WRITE 批量；不改 capability 契约；不改 Action 审批流；不做服务端 BatchRecord。

## 3. Architecture & Data Flow

```
Turn N: run_query -> awaiting_batch_confirm (combinations + call_plan)
  -> outcome_to_workbench_dict: 序列化 combinations + callPlan
  -> agent-runtime-adapter: WorkbenchOutcome.combinations -> pendingOutcome 持有
  -> SSE: 发 awaiting_batch_confirm 状态事件
Turn N+1: 用户确认（前端按钮 / CLI --continue-batch）
  -> BatchContinuation（callPlan + combinations）回传
  -> runner 按 continuation type 分派 -> continue_batch(call_plan, combinations, gateway)
  -> 逐组合 execute + narrate_inventory_facts 聚合（已实现）
  -> 返回批量结果
```

## 4. Component Changes

### 4.1 `workbench_output.py`
- `outcome_to_workbench_dict` 序列化 `combinations`：`"combinations": [dict(c) for c in outcome.combinations] if outcome.combinations else None`（类比 `approvalRecord` line 44）。

### 4.2 `agent-runtime-adapter.ts`
- `WorkbenchOutcome` 增加 `combinations?: Record<string,string>[] | null`。
- 新增 `BatchContinuation` 类型：`{ callPlan: Record<string,unknown>; combinations: Record<string,string>[] }`。
- `AgentRunnerInput.continuation` 联合类型：`ApprovalContinuation | BatchContinuation`（type 判别字段）。
- `awaiting_batch_confirm` -> `pendingOutcome` 持有 combinations（与 approval 相同机制）。
- runner 按 continuation type 分派：`approval` -> `continue_action`；`batch` -> `continue_batch`（调用 Python runner 的 batch continuation 路径）。

### 4.3 `cli.py`
- 新增 `--continue-batch` 标志（类比 `--continue-action`）：解析 callPlan + combinations JSON -> 调 `continue_batch(call_plan, combinations, gateway)`。

### 4.4 API route / SSE
- API：同一 agent-runs 端点，`continuation` 字段按 type 判别（`approval` vs `batch`）。runner 分派。
- SSE：`AgentRunState` 增加 `"awaiting_batch_confirm"`（类比 `"awaiting_approval"`）；发状态事件携带 combinations artifact。

### 4.5 `continue_batch`
- 已实现（orchestrator.py:276），READ-only 守卫已保证。本 change 仅接上调用方。

## 5. Error Handling

| 场景 | 处理 |
|------|------|
| combinations 缺失/空 | continue_batch 空 combinations -> 无 facts -> failure "全部组合查询失败" 或无匹配 |
| callPlan 与 combinations 不匹配 | runner 校验 callPlan.capability_id 与 combinations 一致性（defense-in-depth）|
| Action capability 误入 batch | continue_batch ValueError（已有守卫）|
| 前端 combinations 丢失 | 用户重新发起查询（无服务端状态，类比 approval approvalRecord 丢失）|

## 6. Testing Strategy

- `test_workbench_output.py`：awaiting_batch_confirm outcome -> dict 含 combinations；非 batch -> combinations=None。
- `test_orchestrator.py`：continue_batch 接续（已覆盖，补 service-entry 场景）。
- `test_conversation_context.py`：awaiting_batch_confirm lastContext=None（已 hotfix 覆盖）。
- Frontend：`agent-runtime-adapter` BatchContinuation 路由测试 + API route 测试。
- e2e：Turn N 多值 -> awaiting_batch_confirm + combinations 序列化；Turn N+1 --continue-batch -> 批量聚合结果。
- `npm --prefix frontend run verify` + `scripts/verify-agent-callplan-evidence.sh`。

## 7. Spec Patch

delta spec MODIFIED "Multi-value query split"：
- 补充：workbench SHALL serialize `combinations` for `awaiting_batch_confirm`；service layer SHALL route confirmed batch to `continue_batch`。
- 新增场景：`awaiting_batch_confirm serializes combinations to workbench`、`continue_batch service entry executes confirmed batch`。

## 8. Risks & Trade-offs

- 前端持有 combinations（≤20 组合，小 dict）：与 approval 一致，可接受。
- continuation 类型判别：runner 按 type 分派，需明确 type 字段。
- READ-only：continue_batch 守卫已保证。

## 9. Future Extension Points

- 服务端 BatchRecord（若未来需服务端状态/审计）。
- WRITE 批量审批语义（若未来扩展）。
- combinations 分页（若组合数大）。


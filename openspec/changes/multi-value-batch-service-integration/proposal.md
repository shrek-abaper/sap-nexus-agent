## Why

`awaiting_batch_confirm` 端到端不可用：`continue_batch` 在生产代码零调用方（无 CLI/workbench/SSE 入口），`combinations` 不跨轮携带。上一个 change 实现了 orchestrator 层（run_query 多值检测 + continue_batch + narrate_inventory_facts），hotfix 止住了"确认"死循环（`_last_context_from_outcome` 对 awaiting_batch_confirm 返回 None），但功能仍不可用：用户"确认"后得到 CLARIFY/REJECT 而非批量结果。

根因：服务层集成缺失。`continue_batch` 类比 `continue_action`（Action 审批流），但后者有完整的服务层接续（workbench 序列化 approvalRecord + 前端 pendingOutcome 持有 + ApprovalContinuation 回传 + CLI `--continue-action` + runner 调用 continue_action），batch 路径缺这套接续。

## What Changes

全类比 `continue_action` 审批流（A+A 设计：前端持有 combinations 回传 + 显式 continuation）：

- **`workbench_output.py`**：`outcome_to_workbench_dict` 序列化 `combinations`（类比 `approvalRecord`）。
- **`agent-runtime-adapter.ts`**：`WorkbenchOutcome` 增加 `combinations` 字段；新增 `BatchContinuation` 类型（callPlan + combinations）；`awaiting_batch_confirm` -> pendingOutcome 持有；用户确认 -> BatchContinuation 回传 -> 调用 `continue_batch`。
- **`cli.py`**：新增 `--continue-batch` 标志（类比 `--continue-action`），解析 callPlan + combinations 调 `continue_batch`。
- **API route / SSE**：batch continuation 端点（类比 approval continuation），SSE `awaiting_batch_confirm` 状态。
- **`continue_batch`**：已有实现，接上调用方。

## Capabilities

### New Capabilities
（无新 capability，集成现有 continue_batch 到服务层）

### Modified Capabilities
- `agent-callplan-evidence`：`awaiting_batch_confirm` outcome 序列化 combinations + continue_batch 服务入口 + batch continuation 流。

## Impact

- **Python Agent**：`agent/sap_nexus_agent/workbench_output.py`（序列化 combinations）、`agent/sap_nexus_agent/cli.py`（--continue-batch）。
- **Frontend**：`frontend/src/runtime/agent-runtime-adapter.ts`（WorkbenchOutcome.combinations + BatchContinuation + 路由）、API route（batch continuation 端点）、SSE 事件（awaiting_batch_confirm）。
- **测试**：`agent/tests/test_{workbench_output,orchestrator,conversation_context}.py` + frontend tests + e2e（awaiting_batch_confirm -> 确认 -> 批量结果）。
- **非影响**：orchestrator/selector/narrator 核心逻辑不变（已实现）；capability 契约不变；Action 审批流不变；WRITE 批量不做（continue_batch 仅 READ）。

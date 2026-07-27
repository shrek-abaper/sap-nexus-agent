## Why

`awaiting_batch_confirm` 状态触发死循环：用户回复"确认"后，`_last_context_from_outcome`（`workbench_output.py:66`）因 `match_decision.decision_type == "SELECT"` 返回 `LastContext(SELECT, {material, unit})`，导致下一轮 LLM 拿"确认"+last_context(material) 重新发出 `multi_parameters={plant:[5200,1000]}`，`run_query` 又返回 `awaiting_batch_confirm`，无限循环。

根因：`_last_context_from_outcome` 未对 `status="awaiting_batch_confirm"` 特殊处理，落到 SELECT 分支，使 LLM 误以为上一轮是成功的 SELECT 查询而重新发起多值查询。

## What Changes

- `_last_context_from_outcome` 对 `status="awaiting_batch_confirm"` 返回 `None`（类比 `awaiting_approval` 的处理，line 73-74），清空 session last_context，阻止 LLM 基于过时的 material 上下文重新发出多值查询。

## Impact

- `agent/sap_nexus_agent/workbench_output.py`：`_last_context_from_outcome` 增加 `awaiting_batch_confirm` 早返回 None。
- 测试：`agent/tests/test_conversation_context.py` 或 `test_orchestrator.py` 增加回归用例（awaiting_batch_confirm outcome -> lastContext=None）。
- 非影响：orchestrator、selector、narrator、capability 契约均不变。
- 已知限制：本修复仅止住死循环；`continue_batch` 的服务层集成（CLI/workbench 入口 + combinations 跨轮携带）仍缺失，批量查询功能端到端不可用，留作后续完整 change。

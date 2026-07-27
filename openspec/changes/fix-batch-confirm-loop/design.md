## Context

`_last_context_from_outcome`（`agent/sap_nexus_agent/workbench_output.py:66`）为 `awaiting_batch_confirm` outcome 派生 last_context 时，因 `match_decision.decision_type == "SELECT"` 落到 SELECT 分支（line 89-96），返回 `LastContext(SELECT, {material, unit})`。这使下一轮"确认"输入携带过时的 material 上下文，LLM 重新发出 `multi_parameters`，触发 `awaiting_batch_confirm` 循环。

`awaiting_approval` 已在 line 73-74 早返回 None 清空 session。`awaiting_batch_confirm` 是同类"待用户确认"状态，应同样清空。

## Decision

D1: `awaiting_batch_confirm` 早返回 None。在 `_last_context_from_outcome` 现有 `awaiting_approval` 早返回之后，增加 `awaiting_batch_confirm` 早返回 None。

## Risks

- 止循环但不恢复功能：批量查询仍不可用（无 continue_batch 服务入口）。用户"确认"后 last_context=None -> LLM 无上下文 -> CLARIFY/REJECT。可接受（优于死循环）；完整修复留作后续 change。
- 不影响 Action 审批流、SELECT 成功后的 Q1 follow-up、CLARIFY slot-fill。

## Migration Plan

1. `_last_context_from_outcome` 增加 `awaiting_batch_confirm` 早返回。
2. 回归测试：awaiting_batch_confirm outcome -> lastContext=None。
3. 全量测试通过。

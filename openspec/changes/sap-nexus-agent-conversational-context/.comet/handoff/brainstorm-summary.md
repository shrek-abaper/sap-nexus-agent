# Brainstorm Summary

- Change: sap-nexus-agent-conversational-context
- Date: 2026-07-26

## 确认的技术方案

**统一 last_context 模型**（Q1=覆盖 + 方案 A）：
- `SessionState`（backend 进程内 `Map<conversationId, SessionState>`）持 `last_context` + `last_run_id`（审批 pending 检测用）
- `LastContext { capability_id, parameters, missing_parameters, decision_type("CLARIFY"|"SELECT") }`--统一承载 CLARIFY 延续与 SELECT 追问
- `ConversationContext { last_context, history(近3轮) }`--透传给 IntentAdapter
- sticky 延续判定：`last_context` 存在且本轮无主关键词 -> 继承 `capability_id`，合并参数（新覆盖旧，未提供保留），重判 missing；含主关键词 -> 新轮覆盖
- CLARIFY 后 slot-fill 与 SELECT 后追问统一处理
- LLM 路径历史注入：权威/不可信分离（`SystemMessage` 契约 + 隐藏 `<durable_context_data>` `HumanMessage` 包裹近 3 轮）；rule 路径不调 LLM（hybrid 安全兜底）
- 审批 pending + 新查询 -> 拒绝并提示先处理审批（Q2）
- `IntentAdapter: Callable[[str, ConversationContext|None], IntentParseResult]`，默认 `None` 向后兼容

## 关键取舍与风险

- Q1=覆盖 扩大 v1 范围 -> 统一 last_context 吸收，复杂度可控
- 参数合并语义：新覆盖旧、未提供保留（"换一个 DEMOA4"继承 plant=1000）-> v1 接受，文档标注
- 审批 pending 拒绝新查询 -> 简单安全，中断审批为非目标
- LLM 注入风险 -> 权威契约 + closed-set 双重防线
- 进程重启丢 session -> v1 接受，P0B 解决

## 测试策略

- 核心（turn1 CLARIFY -> turn2 slot-fill -> SELECT）+ 边界 1-4（open 阶段）
- 边界 5（Q1 新增）：SELECT 后"换一个 DEMOA4" -> 继承 + 合并 -> SELECT
- 边界 6（Q2 新增）：审批 pending + 新查询 -> 拒绝提示
- 单轮回归：`context=None` 全部现有测试零改动
- Frontend：sessions Map + conversationId 透传

## Spec Patch

- `conversational-context` spec：新增"SELECT-后追问继承"Requirement + Scenario；新增"审批 pending 拒绝新查询"Scenario
- `agent-callplan-evidence` spec：`last_context` 统一模型（`PendingClarification` 表述统一为 `LastContext`）

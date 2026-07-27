## Context

当前 `parse_with_hybrid` 先 LLM，但 `_messages` 不用 `last_context`，LLM 不稳定 fallback rule（不继承），含主关键词走新轮丢失 material。多工厂只提取第一个 plant。架构文档 §4.2.2 定义了 `ConversationState`（last_context），但 LLM 路径未集成。本 change 补 LLM last_context 集成 + LLM 为主 + 多工厂。

## Goals / Non-Goals

**Goals**:
- LLM 稳定理解指代（"这个物料"->DEMOA2）
- 多工厂查询（"5200、1000" 拆分 + 聚合）
- LLM 为主，rule 仅连接失败兜底

**Non-Goals**:
- DeerFlow runtime / closed-set 契约 / P0B / spawn 模型

## Decisions

### D1: _messages 加入 last_context
`_messages` 拼入 `last_context`（capability+parameters），权威/不可信分离（SystemMessage 契约 + 隐藏 HumanMessage 包裹 last_context）。LLM 有完整上下文稳定理解指代。

### D2: LLM 为主，rule 仅连接失败兜底
`parse_with_hybrid` 调整：LLM 返回结果直接用（空/错误不再 fallback rule）；rule 仅 `LlmUnavailable`（连接失败）时兜底。rule 兜底也继承 `last_context` material（D3）。

### D3: resolve_with_context 含主关键词继承 material
含主关键词时，如果提取不到 material 但 `last_context` 有 material，继承（指代场景）。"查下这个物料在1000的库存" -> 继承 DEMOA2。

### D4: 多工厂 orchestrator 拆分
LLM 识别多 plant -> orchestrator 拆分多次 execute（单 plant capability 不改）-> 聚合。

### D5: 多工厂结果聚合
多个 ReasoningFact + 一个合并 narrative（"5200: 176 EA; 1000: 0 EA"）。部分失败标注。

## Risks / Trade-offs

- LLM 不可用时 rule 兜底需继承 last_context（D3 保证）
- 多工厂部分失败 -> 部分结果 + 标注
- last_context 注入安全（权威/不可信分离，D1）
- LLM 返回多 plant 的 JSON 格式需 design 阶段细化

## Migration Plan

1. `_messages` 加 last_context（D1）
2. `parse_with_hybrid` LLM 为主（D2）
3. `resolve_with_context` 继承 material（D3）
4. orchestrator 多工厂拆分（D4）+ 聚合（D5）
5. 测试 + 回归

## Open Questions

1. LLM 返回多 plant 的 JSON 格式？（design 阶段 Design Doc 细化）
2. 多工厂 narrative 聚合格式？（design 阶段细化）
3. LLM 返回空/错误时是否真不 fallback rule？（D2 决策：不 fallback，直接返回空结果让 selector REJECT？或 CLARIFY？）

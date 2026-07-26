## Why

当前 Agent 意图识别架构以 rule 为兜底，但 LLM 路径不稳定且不处理 `last_context`，导致多轮对话中指代理解失败。实测：第 1 轮 "DEMOA2 在工厂 5100..." 正常 SELECT；第 2 轮 "这个物料在5200、1000的库存分别是多少" 返回 CLARIFY "请提供要查询的物料编号和工厂"--"这个物料"指代未被理解，多工厂查询不支持。

根因：
- `_messages`（LLM prompt）只用 `context.history`（近 3 轮文本），**不用 `context.last_context`**（上轮 capability+parameters）。LLM 要从 history 文本推断指代，不稳定。
- LLM 返回空/错误时 fallback rule。rule 用关键词+正则，不理解指代；含主关键词时走新轮 `parse_intent`（不继承 `last_context`）。
- inventory capability 只接受单 plant，多工厂（"5200、1000"）只提取第一个。

本 change 借鉴 DeerFlow "LLM 有完整上下文"理念（不引入 DeerFlow runtime），增强 LLM 意图识别 + 多工厂拆分。

## What Changes

- **`_messages` 加入 `last_context`**：LLM prompt 拼入上轮 capability+parameters（权威/不可信分离），LLM 有完整上下文稳定理解指代（"这个物料"->DEMOA2）。
- **LLM 为主，rule 仅连接失败兜底**：`parse_with_hybrid` 调整，LLM 返回空/错误不再 fallback rule（避免 rule 不智能的 CLARIFY）；rule 仅 LLM 连接失败时兜底，且 rule 兜底也继承 `last_context` material。
- **`resolve_with_context` 含主关键词继承 material**：含主关键词时，如果提取不到 material 但 `last_context` 有 material，继承（指代场景）。
- **多工厂拆分**：LLM 识别多 plant -> orchestrator 拆分多次 execute（5200 一次，1000 一次）-> 聚合多个 ReasoningFact + 一个 narrative。不改 capability 契约（单 plant）。
- **多工厂结果聚合**：多个 ReasoningFact + 一个合并 narrative（"5200: 176 EA; 1000: 0 EA"）。

## Capabilities

### New Capabilities
（无新 capability，增强现有意图识别 + orchestrator）

### Modified Capabilities
- `agent-callplan-evidence`: IntentAdapter LLM 为主（`_messages` 加 `last_context`）+ rule 仅连接失败兜底 + 含主关键词继承 material + 多工厂拆分聚合

## Impact

- **Python Agent**：`agent/sap_nexus_agent/{llm_intent,intent,orchestrator,capability_selector}.py`--`_messages` 加 last_context、`parse_with_hybrid` LLM 为主、`resolve_with_context` 继承 material、orchestrator 多工厂拆分。
- **测试**：`agent/tests/test_{llm_intent,intent,orchestrator,conversation_context}.py`--指代场景 + 多工厂 + LLM 不可用兜底回归。
- **非影响**：Java Gateway、registry、frontend、OWL、PlanGraph、closed-set capability 契约、P0B durable runtime。

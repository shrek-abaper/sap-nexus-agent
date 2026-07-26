## 1. _messages 加入 last_context

- [ ] 1.1 `_messages` 拼入 `last_context`（capability+parameters），权威/不可信分离（SystemMessage 契约 + 隐藏 HumanMessage 包裹 last_context）
- [ ] 1.2 LLM prompt 含上轮 capability+parameters，稳定理解指代
- [ ] 1.3 测试：LLM 理解"这个物料"指代（含 last_context 时 SELECT 继承 material）

## 2. LLM 为主，rule 仅连接失败兜底

- [ ] 2.1 `parse_with_hybrid` 调整：LLM 返回结果直接用（空/错误不再 fallback rule）
- [ ] 2.2 rule 仅 `LlmUnavailable`（连接失败）时兜底
- [ ] 2.3 rule 兜底走 `parse_intent(text, context)`（继承 last_context，D3）
- [ ] 2.4 测试：LLM 为主 + rule 仅连接失败兜底

## 3. resolve_with_context 含主关键词继承 material

- [ ] 3.1 含主关键词时，提取不到 material 但 `last_context` 有 material -> 继承（指代场景）
- [ ] 3.2 "查下这个物料在1000的库存" -> 继承 DEMOA2 + plant=1000 -> SELECT
- [ ] 3.3 "查 DEMOA4 的库存"（新物料）-> 不继承（有新 material）
- [ ] 3.4 测试：指代场景 + 新物料场景

## 4. 多工厂拆分 + 聚合

- [ ] 4.1 LLM 识别多 plant（"5200、1000" -> [5200, 1000]）
- [ ] 4.2 orchestrator 拆分多次 execute（单 plant capability 不改）
- [ ] 4.3 聚合多个 ReasoningFact + 一个合并 narrative（"5200: 176 EA; 1000: 0 EA"）
- [ ] 4.4 部分失败标注（一个工厂失败 -> 部分结果 + 标注失败工厂）
- [ ] 4.5 测试：多工厂 + 部分失败

## 5. 验证

- [ ] 5.1 `openspec validate --all --strict` 通过
- [ ] 5.2 pytest 回归（指代 + 多工厂 + LLM 不可用兜底）
- [ ] 5.3 e2e：第1轮 "DEMOA2 在 5100..." -> SELECT；第2轮 "这个物料在5200、1000的库存分别是多少" -> 多工厂返回

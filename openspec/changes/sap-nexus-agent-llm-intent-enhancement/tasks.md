## 1. _messages 加入 last_context

- [x] 1.1 `_messages` 拼入 `last_context`（capability+parameters+decision_type），权威/不可信分离（`_AUTHORITY_CONTRACT` + `<durable_context_data>` 包裹 last_context）
- [x] 1.2 LLM prompt 含上轮 capability+parameters，稳定理解指代
- [ ] 1.3 测试：LLM 理解"这个物料"指代（含 last_context 时 SELECT 继承 material）

## 2. LLM 为主，rule 仅连接失败兜底 + 空返回 CLARIFY

- [ ] 2.1 `parse_with_hybrid` 调整：LLM 返回结果直接用（移除 `_requires_safe_fallback` -> rule 回退）
- [ ] 2.2 rule 仅 `LlmUnavailable`（连接失败）时兜底，走 `parse_intent(text, context=context)`（继承 last_context，D3）
- [ ] 2.3 LLM 空返回（无 capability）填充 generic clarification；`select_capability` 第 6 步 REJECT 前增加 clarification 判断 -> CLARIFY（rule 路径空返回仍 REJECT）
- [ ] 2.4 测试：LLM 为主 + 空返回 CLARIFY + rule 仅连接失败兜底（mock 验证空返回时 rule 未调用）

## 3. resolve_with_context 含主关键词继承 material

- [ ] 3.1 含主关键词时，提取不到 material 但 `last_context` 有 material -> 继承（指代场景）
- [ ] 3.2 "查下这个物料在1000的库存" -> 继承 DEMOA2 + plant=1000 -> SELECT
- [ ] 3.3 "查 DEMOA4 的库存"（新物料）-> 不继承（有新 material）
- [ ] 3.4 测试：指代场景 + 新物料场景

## 4. 多值参数 + 确认 + 批量 + 软上限

- [ ] 4.1 `IntentParseResult` 新增 `multi_parameters: dict[str, list[str]]`（默认 {}），正交于 `parameters`
- [ ] 4.2 LLM JSON 解析 `multiParameters`（`_payload_to_parse_result`）；`_messages` base_system 通用多值指引（不枚举参数名）
- [ ] 4.3 `select_capability`：required 参数在 `parameters` 或 `multi_parameters` 即算齐全；5 态不变
- [ ] 4.4 `expand_combinations(base, multi)` 笛卡尔积（单 key -> N，多 key -> 笛卡尔）
- [ ] 4.5 `run_query` SELECT 分支：`parsed.multi_parameters` 非空 -> 展开 combinations -> 软上限检查 -> `AgentOutcome(status="awaiting_batch_confirm", combinations=...)`（不执行）
- [ ] 4.6 `AgentOutcome` 新增 `combinations: list[dict[str,str]] | None`；常量 `BATCH_COMBINATION_CAP=20`
- [ ] 4.7 `continue_batch(call_plan, combinations, gateway)`：逐组合 validate+execute，成功建 fact，失败记 failure；部分失败不全局失败
- [ ] 4.8 `narrate_inventory_facts(facts, failures)`：LLM 主 + 模板兜底（多物料含 material，部分失败标注）
- [ ] 4.9 软上限：超 `BATCH_COMBINATION_CAP` -> CLARIFY "组合数过多，请缩小范围"
- [ ] 4.10 测试：多值->awaiting_batch_confirm（不执行）；expand 单 key/多 key；continue_batch 全成功/部分失败/全失败；软上限 CLARIFY；单值回归

## 5. 验证

- [ ] 5.1 `openspec validate --all --strict` 通过
- [ ] 5.2 pytest 回归（指代 + 多值批量 + LLM 不可用兜底 + 空返回 CLARIFY + 软上限）
- [ ] 5.3 e2e（3 轮）：第1轮 "DEMOA2 在 5100..." -> SELECT；第2轮 "这个物料在5200、1000的库存分别是多少" -> awaiting_batch_confirm；第3轮 确认 -> 批量返回 "5200: 176 EA; 1000: 0 EA"

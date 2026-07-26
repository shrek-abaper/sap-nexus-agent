## 1. Python Agent: ConversationContext 与签名扩展

- [x] 1.1 定义 `ConversationContext` dataclass（`pending_clarification: PendingClarification | None`, `history: list[Turn] | None`）和 `PendingClarification` dataclass（`capability_id, parameters, missing_parameters, clarification_text`），放在 `agent/sap_nexus_agent/conversation_context.py`
- [x] 1.2 扩展 `IntentAdapter` 类型为 `Callable[[str, ConversationContext | None], IntentParseResult]`；`parse_intent` / `parse_with_hybrid` / `parse_with_llm` 增加可选 `context` 参数（默认 `None`），`None` 时行为不变
- [x] 1.3 `run_query` / `run_inventory_query` / `run_workbench_query` 增加 `context` 参数并透传给 `intent_adapter`

## 2. Python Agent: sticky-CLARIFY 跨轮逻辑

- [x] 2.1 在 `intent.py` / `llm_intent.py` 实现 sticky-CLARIFY 判定：`context.pending_clarification` 存在且本轮无主关键词时，重跑该 capability 的 extractor 合并参数、重判 missing
- [x] 2.2 本轮含主关键词时丢弃 pending，走正常单轮解析
- [x] 2.3 rule 路径不调 LLM 即可完成 slot-fill（验证 hybrid 安全兜底契约）
- [x] 2.4 CLARIFY 产出时由 orchestrator/workbench_output 回填 `PendingClarification` 到 outcome（供 backend 记录）

## 3. Python Agent: LLM 路径历史注入分离契约

- [x] 3.1 `_messages` 在 `context.history` 非空时拼入历史：静态权威契约作 `SystemMessage`，历史文本作隐藏 `<durable_context_data>` `HumanMessage`（标记 data）
- [x] 3.2 验证 `_payload_to_parse_result` 的 closed-set 校验仍 reject 任何非注册 capabilityId（即便 LLM 被注入）
- [x] 3.3 rule 路径确认不拼历史（无 LLM 调用）

## 4. Python Agent: CLI 透传

- [x] 4.1 `cli.py` 增加 `--context` stdin JSON 模式（仿 `--continue-action`），解析 `ConversationContext` 传入 `run_query`
- [x] 4.2 `--context` 缺省时 `context=None`，行为不变

## 5. Frontend: conversationId 与 sessions Map

- [x] 5.1 `agent-runtime-adapter.ts` 新增 `sessions: Map<conversationId, SessionState>`（旁挂 `runs`），`SessionState` 持 `pending_clarification`
- [x] 5.2 `createAgentRun` 接受 `conversationId`，取 session.pending 组 `ConversationContext` 经 CLI stdin 传入
- [x] 5.3 outcome 含 CLARIFY 时回填 `PendingClarification` 到 session；SELECT/REJECT/ESCALATE 时清除
- [x] 5.4 `AgentConsole.tsx` "新对话"按钮接线：生成新 `conversationId` 并重置 UI

## 6. Frontend: 请求透传 conversationId

- [x] 6.1 API 路由接受 `conversationId` 字段并传入 `createAgentRun`
- [x] 6.2 `AgentConsole` 每次 submit 携带当前 `conversationId`

## 7. 测试: 多轮 slot-fill 回归

- [x] 7.1 Python Agent 单测：核心场景（turn1 CLARIFY -> turn2 slot-fill -> SELECT）
- [x] 7.2 边界 1：turn2 含主关键词 -> 新轮覆盖 pending
- [x] 7.3 边界 2：turn2 只补一个参数 -> CLARIFY 缩减 missing
- [x] 7.4 边界 3：新对话按钮 -> session 重置
- [x] 7.5 边界 4：LLM 路径历史含恶意指令 -> closed-set 拦截
- [x] 7.6 现有单轮测试 `context=None` 零回归验证
- [x] 7.7 Frontend 测试：`agent-runtime-adapter` sessions Map + conversationId 透传

## 8. 验证

- [ ] 8.1 `openspec validate --all --strict` 通过
- [ ] 8.2 `npm --prefix frontend run verify` 通过（frontend 改动）
- [ ] 8.3 `scripts/verify-agent-callplan-evidence.sh` 通过
- [ ] 8.4 手动端到端：start.sh 起服务，workbench 实测"查库存"->"DEMOA2 1000"连续对话成功

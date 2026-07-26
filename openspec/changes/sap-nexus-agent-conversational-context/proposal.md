## Why

Agent 对话链路当前是完全无状态单轮设计：`IntentAdapter = Callable[[str], IntentParseResult]`，`llm_intent._messages` 硬编码 `[system, {user: text}]`，前端 `agent-runtime-adapter` 每次 spawn 新 python 进程只传 `input.query`。这导致连续对话完全断裂——用户第一轮"你能查库存吗"收到 `CLARIFY`（缺 material/plant），第二轮"DEMOA2 1000"因脱离语境被 `REJECT(UNSUPPORTED_INTENT)`，返回"当前仅支持已注册的能力"。架构层已有 `ConversationState` 三层状态蓝图（§4.2.1），但绑定 P0B durable runtime（未启动）；`flexible-intent-recognition-design.md:31` 明确"不做多轮上下文"。即时 slot-filling 多轮卡在两者之间，无专门 spec/design。本 change 补这档轻量即时多轮，先于 P0B、不改变 runtime 架构。

## What Changes

- 新增 session 内 CLARIFY 跨轮 slot-fill 机制（sticky-CLARIFY）：当 session 存在 pending CLARIFY 且本轮输入不含任何已注册能力的主关键词时，视为对上一轮澄清的 slot-fill 回答，重跑该 capability 的参数 extractor 合并参数后重判 missing。
- 新增 `PendingClarification` 状态（advisory context，属于 `ConversationState`）：`{capability_id, parameters, missing_parameters, clarification_text}`，承载于 backend 进程内 `sessions: Map<conversationId, SessionState>`。
- 扩展 `IntentAdapter` 签名：`Callable[[str], IntentParseResult]` -> `Callable[[str, ConversationContext | None], IntentParseResult]`，默认 `None` 保持全部现有测试零改动。
- 新增历史重注入的权威/不可信分离契约（LLM 路径）：静态权威规则作为 `SystemMessage`，历史文本作为隐藏 `<durable_context_data>` `HumanMessage` 标记为 data，防止用户在第二轮注入指令绕过 closed-set 防线（借鉴 DeerFlow `DurableContextMiddleware`）。
- 前端 `conversationId` 生成与透传（"新对话"按钮触发重置），`agent-runtime-adapter` 维护 `sessions` Map 并把 context 传入 CLI。
- CLI 扩展：接收 `ConversationContext`（stdin JSON，仿 `--continue-action` 模式）。
- session 重置策略：新对话按钮、`SELECT` 成功消解、本轮含主关键词覆盖 pending。

## Capabilities

### New Capabilities
- `conversational-context`: session 内多轮对话上下文管理——`PendingClarification` 状态承载、sticky-CLARIFY 跨轮延续判定、`ConversationContext` 透传、session 生命周期与重置。

### Modified Capabilities
- `agent-callplan-evidence`: `IntentAdapter` 签名扩展为接受可选 `ConversationContext`；`run_query` / `run_inventory_query` / `run_workbench_query` 增加 `context` 参数透传链；CLARIFY 路径在 context 命中时走 slot-fill 合并而非独立单轮解析。

## Impact

- **Python Agent**：`agent/sap_nexus_agent/{llm_intent,intent,orchestrator,workbench_output}.py`、`agent/sap_nexus_agent/cli.py`——签名扩展、sticky-CLARIFY 逻辑、历史注入分离契约。
- **Frontend**：`frontend/src/runtime/agent-runtime-adapter.ts`（`sessions` Map + context 透传）、`frontend/src/modules/agent-console/*`（`conversationId` 生成 + "新对话"按钮接线）。
- **测试**：新增多轮 slot-fill 回归用例（核心 + 边界 1-4）；现有单轮测试因 `context=None` 默认值保持零改动。
- **架构文档**：已先行落地（commit b3b12ec）——technical-architecture §4.2.2、roadmap row 19A、runbook 08 §4.1.1。
- **非影响**：Java Gateway、registry、OWL、PlanGraph、Approval 状态机、P0B durable runtime。

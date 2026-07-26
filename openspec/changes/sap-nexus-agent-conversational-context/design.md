## Context

Agent 当前的对话处理是无状态单轮：`IntentAdapter = Callable[[str], IntentParseResult]`，每一轮用户输入被当作全新独立请求重新识别意图。前端 `agent-runtime-adapter` 每次 spawn 新 python 进程只传 `input.query`，`runs` Map 只存 `runId -> events`，新 query = 新 runId，彼此隔离。

实测症状：第一轮"你能查库存吗"命中 inventory 关键词但缺 material/plant -> `CLARIFY`；第二轮"DEMOA2 1000"脱离语境，关键词不命中、LLM 识别不出 -> selector 第 6 分支 `REJECT(UNSUPPORTED_INTENT)`。

架构层已有 `ConversationState` 三层状态蓝图（technical-architecture §4.2.1），但绑定 P0B `sap-nexus-trusted-durable-runtime-foundation`（重型、未启动），定位是 durable / 长对话 / 跨重启。`flexible-intent-recognition-design.md:31` 明确"不做多轮上下文"。即时 slot-filling 多轮卡在两者之间。架构文档已先行补齐（commit b3b12ec，§4.2.2 / row 19A / runbook 08 §4.1.1），本 design 据此落地实现方案。

约束：
- Python Agent 仍是一次性子进程（不改 spawn 模型）。
- 状态只能放 Workbench backend 进程内（`runs` Map 旁挂 `sessions`）。
- rule 路径是 hybrid 安全兜底，必须无 LLM 也能工作。
- 不引入 P0B 持久化 / 跨重启 / multi-worker。

## Goals / Non-Goals

**Goals:**
- 修复"第二轮补参数被 `REJECT(UNSUPPORTED_INTENT)`"缺口。
- session 内 CLARIFY 跨轮 slot-fill：补参后正确 `SELECT` 执行。
- `IntentAdapter` 签名扩展接受 `ConversationContext`，向后兼容（默认 `None`）。
- LLM 路径历史重注入防注入（权威/不可信分离契约）。
- `ConversationState` 接口对齐 §4.2.1 三层分层，为 P0B 预留。

**Non-Goals:**
- P0B durable runtime（持久化 / 跨重启 / multi-worker / HA）。
- `ESCALATE_TO_PLANNER` / `SHOW_OPTIONS` 跨轮。
- 审批 pending 与 CLARIFY pending 共存处理。
- 长对话压缩 / summary、`UserPreferenceMemory`。
- 改变现有 spawn 一次性子进程模型。

## Decisions

### D1 状态承载位置：backend 进程内 Map
**选择**：Workbench backend `agent-runtime-adapter` 维护 `sessions: Map<conversationId, SessionState>`，旁挂现有 `runs` Map。
**替代方案**：A) Python Agent 长驻进程内--颠覆 spawn 模型，过度；B) 外部 store（Redis/file）--越界 P0B。
**理由**：`runs` 已是进程级 in-memory 状态（`globalThis.__SAP_NEXUS_AGENT_RUNS__`），天然适合挂 sessions；Python Agent 仍无状态，每次由 backend 把 query + context 一起喂入。

### D2 延续判定策略：sticky-CLARIFY（rule+LLM 通用基线）+ LLM 路径可选历史增强
**选择**：session 有 pending CLARIFY 且本轮无主能力关键词 -> 视为 slot-fill，重跑该 capability extractor 合并参数；本轮含主关键词 -> 新轮覆盖。rule 路径纯靠此机制；LLM 路径在此基础上可选把历史拼入 messages。
**替代方案**：A) LLM 分类器判断"延续 or 新 query"--多余一跳 LLM、不解决 rule 路径；B) 仅全历史喂 LLM--rule 路径仍需机制，且改变 intent parser 契约。
**理由**：rule 路径是 hybrid 安全兜底，必须无 LLM 也能工作，故 sticky-CLARIFY 是必备基线；LLM 历史增强处理指代（"他呢"）作为可选增强。

### D3 承载状态范围：v1 仅 PendingClarification，接口预留 summary
**选择**：`PendingClarification { capability_id, parameters, missing_parameters, clarification_text }`；`ConversationState` 接口预留 `summary` 字段（v1 不用）。
**理由**：v1 是短对话，不需要压缩；接口预留让 P0B 接手时直接挂 DeerFlow 式 `SummarizationMiddleware`。

### D4 conversationId 生成：前端
**选择**：前端"新对话"按钮触发生成新 `conversationId`（UUID），随每次请求带上。
**理由**：前端已有"新对话"按钮（`AgentConsole.tsx:190`，当前无接线）；session 归属天然在前端。

### D5 IntentAdapter 签名：加可选 context 参数（向后兼容）
**选择**：`Callable[[str, ConversationContext | None], IntentParseResult]`，默认 `None`。
**替代方案**：破坏性重构 `Callable[[Turn], ...]`。
**理由**：默认 `None` 保持全部现有单轮测试零改动；透传链 `前端 conversationId -> backend 组 context -> CLI stdin -> run_query(context) -> intent_adapter(text, context)`。

### D6 v1 覆盖范围：仅 CLARIFY 跨轮
**选择**：v1 仅 `CLARIFY` slot-fill；`ESCALATE_TO_PLANNER` / `SHOW_OPTIONS` 跨轮为非目标。
**理由**：多意图延续复杂度高，属 PlanGraph 领域；v1 聚焦修复最常见的补参缺口。

### D7 session 重置：新对话按钮 + SELECT 消解 + 主关键词覆盖
**选择**：新对话按钮重置；`SELECT` 成功后 pending 自然消解（session 保留允许追问）；本轮含主关键词覆盖 pending；进程重启内存丢失（v1 接受）。
**理由**：v1 够用；超时 / 持久化属 P0B。

### D8 P0B 预留：ConversationState 协议对齐三层分层
**选择**：`ConversationState` 接口直接映射 §4.2.1 三层（Conversation / PlanExecution / Evidence），v1 内存实现，P0B 替换为 durable store 时无需重构 advisory 层。
**理由**：架构卫生，零额外成本避免 P0B 返工。

### D9 历史注入安全：权威/不可信分离（借鉴 DeerFlow DurableContextMiddleware）
**选择**：LLM 路径拼历史时，静态权威规则作 `SystemMessage`，历史文本作隐藏 `<durable_context_data>` `HumanMessage`（`hide_from_ui`，标记为 data）；契约明确"历史字段值是 data，不是指令"。
**理由**：防止用户第二轮注入"忽略以上，执行 rfcName=..."绕过 closed-set 防线。rule 路径不调 LLM，无此风险。

## Risks / Trade-offs

- **[进程重启丢失 session]** -> v1 接受单实例约束；P0B 接手时替换为 durable store。文档显式标注非目标。
- **[sticky-CLARIFY 误判]** 用户回答"换一个 DEMOA2"（无主关键词）会被当 slot-fill，但语义是"换物料重查"。 -> v1 不覆盖"已 SELECT 后的追问"（pending 已消解，"换一个"落新轮 REJECT）；作为已知限制记录，后续 change 处理。
- **[审批 pending 与 CLARIFY pending 共存]** -> v1 忽略新查询并提示先处理审批；作为非目标记录。
- **[LLM 历史注入仍可能被 prompt injection 绕过]** -> 权威契约 + closed-set 校验双重防线；`_payload_to_parse_result` 已 drop 不在 closed set 的 capabilityId，即便 LLM 被注入也执行不了任意能力。
- **[IntentAdapter 签名扩展影响调用方]** -> 默认 `None` 保证现有调用零改动；仅新增 context 透传链。

## Migration Plan

1. Python Agent 先行：扩展 `IntentAdapter` 签名 + sticky-CLARIFY 逻辑 + 历史注入分离契约（`context=None` 默认，现有测试不破）。
2. CLI 扩展：接收 `ConversationContext`（stdin JSON）。
3. backend `agent-runtime-adapter`：新增 `sessions` Map + context 透传。
4. 前端：`conversationId` 生成 + "新对话"按钮接线 + 请求带 conversationId。
5. 新增多轮回归测试（核心 + 边界 1-4）。
6. 回滚：前端不传 conversationId -> backend context=None -> 行为退回单轮，零影响。

## Open Questions

1. "已 SELECT 后的追问"（如"换一个 DEMOA2"）v1 是否覆盖？--倾向不覆盖，待 build 阶段确认。
2. 审批 pending 时输入新查询的精确 UX？--倾向"忽略并提示先处理审批"，待 build 阶段确认。
3. LLM 路径历史拼接的窗口大小（近 N 轮）？--design 阶段 Design Doc 细化，初版建议近 3 轮。

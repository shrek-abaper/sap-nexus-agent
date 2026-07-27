# Brainstorm Summary

- Change: sap-nexus-agent-llm-intent-enhancement
- Date: 2026-07-26

## 确认的技术方案

### Section 1：意图识别

- **D1 - `_messages` 注入 `last_context`**：在 `_messages` 中新增 last_context 结构化数据块（与 history_block 同级，均为 `<durable_context_data>` data 非指令），含 capability/parameters/decision_type。复用 `_AUTHORITY_CONTRACT` 权威/不可信分离。LLM 拿到结构化上轮决策，稳定解析"这个物料"->`last_context.parameters["material"]`。
- **D2 - `parse_with_hybrid` LLM 为主**：移除 `if _requires_safe_fallback(result): return parse_intent(...)` 规则回退；LLM 结果直接用。仅保留 `except LlmUnavailable: return parse_intent(text, context=context)` 连接失败兜底。
- **Q3 - LLM 空返回 -> CLARIFY**：`_payload_to_parse_result` 在 LLM 无 capability 时填充 `clarification`；`select_capability` 第 6 步 REJECT 前增加判断--无 capability 但 `clarification` 非空 -> CLARIFY（generic）。
- **D3 - `resolve_with_context` 主关键词继承 material**：主关键词分支不再 `return parse_intent(text)` 丢弃 context；提取不到 material 但 `last_context` 有 -> 继承。仅 LLM 不可用 rule 兜底时生效。

### Section 2：多值参数 + 确认 + 批量（方案 B）

- **IntentParseResult 扩展**：新增正交字段 `multi_parameters: dict[str, list[str]]`（默认 `{}`），不动现有 `parameters: dict[str, str]`。通用抽象，任意参数可多值。
- **LLM JSON**：多值时返回 `multiParameters: {"plant":["5200","1000"]}`（或 `material` 等，通用），不放入 `parameters`。`_messages` base_system 用通用指引（不枚举 plant/material）。`_payload_to_parse_result` 解析 `multiParameters`，闭集防御照旧。
- **Selector 不变（5 态）**：`missing_parameters` 判定中，required 参数在 `parameters` 或 `multi_parameters` 即算齐全 -> SELECT。`MatchDecision` 不改 schema；orchestrator 读 `parsed.multi_parameters`。
- **Orchestrator SELECT 分支**：`parsed.multi_parameters` 非空 -> `expand_combinations(parameters, multi_parameters)` 笛卡尔积 -> 返回 `AgentOutcome(status="awaiting_batch_confirm", combinations=..., call_plan=基础)`，不执行。
- **`continue_batch`**（类比 `continue_action`）：workbench 用户确认后直接调用（不经 run_query）。逐组合 validate+execute，成功建 fact，失败记 failure；部分失败不全局失败。
- **`narrate_inventory_facts`**（Q2，镜像 `narrate_purchase_order_facts`）：LLM 主 + 模板兜底 + guard。多物料时含 material；部分失败标注。
- **跨轮状态**：前端持有 Turn N 的 combinations（类比持有 `approval_record`），Turn N+1 传给 `continue_batch`。无服务端状态。
- **AgentOutcome 新增**：`combinations: list[dict[str,str]] | None`（复用已有 `facts`）。

### Section 3：边界（修订后）

- **多值通用**：`material` + `plant` 同时多值（2×2=4 组合）；未来新能力参数天然支持多值，无需改 expand/orchestrator/narrator 核心。
- **组合爆炸三层保护**：(1) 确认步骤本身是第一道闸；(2) expand/narrate 不硬编码组合数；(3) **软上限**（本 change 实现）--超阈值（默认 20）不发 `awaiting_batch_confirm`，发 CLARIFY "组合数 N 过多，请缩小范围"。
- **READ 安全**：`continue_batch` 仅对 READ capability 生效；不触及 Action 审批路径。

## 关键取舍与风险

- **LLM 为主，rule 仅连接失败兜底**：信任 LLM，不再用 rule 二次猜测。风险：LLM 返回错误时不再有 rule 纠正；通过 Q3 CLARIFY 缓解 UX。
- **方案 B（orchestrator awaiting_batch_confirm）vs 新 MatchDecision 状态**：选 B，与 Action 审批流同构，selector 保持 5 态，spec 改动最小。代价：SELECT 不再总等于立即执行。
- **通用多值 vs 仅 plant**：选通用（material+plant+任意），`multi_parameters` 正交字段。代价：组合爆炸风险 -> 软上限 + 确认步骤双重保护。
- **last_context 注入安全**：复用 `_AUTHORITY_CONTRACT`，last_context 作为 data 不可注入 capabilityId 指令。
- **narrative 通用化**：按 `businessObject` 派生指引，新能力只补模板。

## 测试策略

- `test_llm_intent.py`：D1 last_context 注入 + 指代解析；D2 LLM 为主 + 空返回 CLARIFY + LlmUnavailable 兜底（mock 验证空返回时 rule 未调用）。
- `test_intent.py`：D3 rule 兜底主关键词继承 material（继承/不继承两个场景）。
- `test_orchestrator.py`：多值->awaiting_batch_confirm（不执行）；expand_combinations 单 key/多 key 笛卡尔积；continue_batch 全成功/部分失败/全失败；单值回归；软上限 CLARIFY。
- narrator 测试：narrate_inventory_facts 多 fact/部分失败/模板兜底；多物料含 material。
- `test_conversation_context.py`：LastContext round-trip 回归。
- e2e（task 5.3 改 3 轮）：Turn1 SELECT -> Turn2 awaiting_batch_confirm -> Turn3 确认 -> 批量结果。

## Spec Patch

- **"Closed-set capability selection"（MODIFIED）**：补 Q3 空返回 CLARIFY 场景；补 `multi_parameters` 契约 + `Scenario: Multi-value parameter emits SELECT with multi_parameters`。
- **"Multi-plant query split" -> "Multi-value query split"（ADDED，泛化）**：原文静默拆分改写为 "expand combinations -> awaiting_batch_confirm -> 用户确认后 continue_batch 执行 + 聚合"。场景：`Multi-value query emits awaiting_batch_confirm`、`Confirmed multi-value batch executes and aggregates`（含 material×plant）、`Multi-value partial failure`、`Multi-value combination cap`（软上限 CLARIFY）。
- **tasks.md 同步**：新增 multi_parameters/expand_combinations/awaiting_batch_confirm/continue_batch/narrate_inventory_facts/软上限 tasks；原 4.x 多工厂任务改写含确认流程；5.3 e2e 改 3 轮。

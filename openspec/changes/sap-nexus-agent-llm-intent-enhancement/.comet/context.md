# Comet Design Handoff

- Change: sap-nexus-agent-llm-intent-enhancement
- Phase: design
- Mode: compact
- Context hash: 5b13515fdbaa709ae568b6a2672ff36fc24e9986175bfa20ae646aab6d61a54a

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/sap-nexus-agent-llm-intent-enhancement/proposal.md

- Source: openspec/changes/sap-nexus-agent-llm-intent-enhancement/proposal.md
- Lines: 1-32
- SHA256: b7c09971a3c02faaf76316324cd831a08d147bc2b4b273ccbb639f1088898e44

```md
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

```

## openspec/changes/sap-nexus-agent-llm-intent-enhancement/design.md

- Source: openspec/changes/sap-nexus-agent-llm-intent-enhancement/design.md
- Lines: 1-51
- SHA256: ee84cc2ade41c6d6697acd241c9a570f7144da8157031fd0a0d73ead6e4e8c29

```md
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

```

## openspec/changes/sap-nexus-agent-llm-intent-enhancement/tasks.md

- Source: openspec/changes/sap-nexus-agent-llm-intent-enhancement/tasks.md
- Lines: 1-38
- SHA256: 7a8f719ed3f5ae9f4474e0398c4ff835e2f532d99b14291cb3b5feb9f68fcefc

```md
## 1. _messages 加入 last_context

- [ ] 1.1 `_messages` 拼入 `last_context`（capability+parameters+decision_type），权威/不可信分离（`_AUTHORITY_CONTRACT` + `<durable_context_data>` 包裹 last_context）
- [ ] 1.2 LLM prompt 含上轮 capability+parameters，稳定理解指代
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

```

## openspec/changes/sap-nexus-agent-llm-intent-enhancement/specs/agent-callplan-evidence/spec.md

- Source: openspec/changes/sap-nexus-agent-llm-intent-enhancement/specs/agent-callplan-evidence/spec.md
- Lines: 1-73
- SHA256: ac03af9d45818274498e86f483f9978fa476d6799a6d9041d25c495bb6f7f078

```md
## MODIFIED Requirements

### Requirement: Closed-set capability selection
The system SHALL select capabilities only from the Registry closed set and MUST reject unsupported intent before Gateway execution. The selector SHALL emit an explicit five-state `MatchDecision` (`SELECT` / `CLARIFY` / `REJECT` / `SHOW_OPTIONS` / `ESCALATE_TO_PLANNER`) replacing the implicit `SelectionResult`. The selector SHALL route recognized single intents to their registered capability IDs across executor types (for example `inventory_availability` -> `MM.Inventory.GetAvailability` via `JCO_RFC`, `purchase_order_list` -> `MM.PurchaseOrder.GetList` via `ODATA`) without the Agent needing to know the executor type or binding at selection time. LLM-assisted selection MUST be constrained to the same closed set and MUST NOT introduce new executable capability IDs.

The rule parser and LLM parser SHALL detect multiple intents in a single utterance. When more than one capability intent is detected, the selector MUST emit `ESCALATE_TO_PLANNER` with a record and explanation, and MUST NOT silently reduce to the first-matched single capability.

The `IntentAdapter` signature SHALL be `Callable[[str, ConversationContext | None], IntentParseResult]` with `ConversationContext` defaulting to `None`. The LLM path (`parse_with_hybrid`) SHALL be the primary intent recognizer: `_messages` MUST inject `last_context` (capability+parameters) so the LLM has complete context to resolve anaphora ("这个物料" -> prior material). The LLM result SHALL be used directly (empty/error results no longer fall back to rule); the rule path SHALL only run when the LLM is unavailable (connection failure). When the rule path runs as fallback, it SHALL inherit `last_context` material: if the utterance contains a primary keyword but the extractor cannot extract material and `last_context` has material, the adapter SHALL inherit the prior material (anaphora scenario).

When the LLM is available but returns no capabilityId (empty/ambiguous result, not a connection failure), the adapter SHALL populate a generic clarification and the selector SHALL emit `CLARIFY` (not `REJECT`); the rule path's empty return (no clarification) still maps to `REJECT`. The `IntentParseResult` SHALL carry a `multi_parameters: dict[str, list[str]]` field (default empty) for multi-valued parameters. When the user mentions multiple values for any parameter, the LLM SHALL return them in a `multiParameters` JSON array (not in `parameters`); single-valued parameters remain in `parameters`. The selector SHALL treat a required parameter as satisfied if it is present in `parameters` OR `multi_parameters`, so a multi-valued required parameter does not trigger `CLARIFY`.

#### Scenario: Route single inventory intent to SELECT
- **WHEN** the parser identifies a single `inventory_availability` intent with required `material` and `plant`
- **THEN** the Agent emits `MatchDecision.decision_type=SELECT` for `capabilityId=MM.Inventory.GetAvailability` and proceeds to CallPlan and Gateway validation
- **AND** the Agent does not choose an executor type or binding at selection time

#### Scenario: Route single purchase order intent to SELECT
- **WHEN** the parser identifies a single `purchase_order_list` intent with at least one filter parameter
- **THEN** the Agent emits `MatchDecision.decision_type=SELECT` for `capabilityId=MM.PurchaseOrder.GetList` and proceeds to CallPlan and Gateway validation

#### Scenario: Multi-goal utterance escalates to planner
- **WHEN** the parser detects both inventory availability and purchase order list intents in one utterance
- **THEN** the Agent emits `MatchDecision.decision_type=ESCALATE_TO_PLANNER` with a record and explanation
- **AND** the Agent does NOT silently select the first-matched capability or call Gateway validate or execute

#### Scenario: LLM resolves anaphora via last_context
- **WHEN** turn 1 "DEMOA2 在 5100..." resolves to SELECT and `last_context=SELECT(inventory, {material:DEMOA2})`
- **AND** turn 2 "这个物料在1000的库存" contains "库存" primary keyword
- **THEN** the LLM path resolves "这个物料" to `material=DEMOA2` via `last_context` injection
- **AND** emits `SELECT` with `material=DEMOA2, plant=1000`

#### Scenario: Rule fallback inherits material on primary keyword
- **WHEN** the LLM is unavailable and the rule path runs
- **AND** the utterance contains a primary keyword but extractor cannot extract material
- **AND** `last_context` has material
- **THEN** the adapter inherits the prior material and proceeds to SELECT or CLARIFY

#### Scenario: LLM empty return emits CLARIFY
- **WHEN** the LLM is available but returns no capabilityId (empty/ambiguous result)
- **THEN** the adapter populates a generic clarification
- **AND** the selector emits `MatchDecision.decision_type=CLARIFY` (not REJECT)

#### Scenario: Multi-value parameter emits SELECT with multi_parameters
- **WHEN** the LLM returns `multi_parameters={"plant":["5200","1000"]}` for a single matched capability
- **AND** all required parameters are satisfied across `parameters` and `multi_parameters`
- **THEN** the selector emits `MatchDecision.decision_type=SELECT` (multi_parameters carried on IntentParseResult)
- **AND** does NOT emit CLARIFY for the multi-valued parameter

## ADDED Requirements

### Requirement: Multi-value query split
The orchestrator SHALL support multi-value inventory queries where any parameter (e.g. `plant`, `material`) has multiple values. When the LLM identifies multiple values for one or more parameters in a single utterance (e.g. "DEMOA2 和 DEMOA4 在 5200、1000 的库存"), the orchestrator SHALL expand the Cartesian product of the multi-valued parameters (via `multi_parameters`) into a combination list and return `AgentOutcome.status="awaiting_batch_confirm"` with the combinations. The orchestrator SHALL NOT execute Gateway calls until the user confirms. Upon confirmation, `continue_batch` SHALL execute single-value execute calls per combination (the single-plant/single-material capability contract SHALL NOT change) and aggregate the results. Partial failures (one combination fails) SHALL be surfaced as partial results with the failed combination annotated. A soft combination cap (default 20) SHALL emit CLARIFY when exceeded, instead of `awaiting_batch_confirm`.

#### Scenario: Multi-value query emits awaiting_batch_confirm
- **WHEN** the user asks "DEMOA2 和 DEMOA4 在 5200、1000 的库存分别是多少" (same conversation)
- **THEN** the LLM returns `multi_parameters={plant:[5200,1000], material:[DEMOA2,DEMOA4]}`
- **AND** the orchestrator expands 4 combinations (2×2 Cartesian product)
- **AND** returns `awaiting_batch_confirm` with the 4 combinations and does NOT call Gateway validate or execute

#### Scenario: Confirmed multi-value batch executes and aggregates
- **WHEN** the user confirms the batch from a prior `awaiting_batch_confirm` outcome
- **THEN** `continue_batch` executes MM.Inventory.GetAvailability once per combination
- **AND** aggregates results into a single narrative: "5200: 176 EA; 1000: 0 EA" (single material) or a per-material narrative (multi material)

#### Scenario: Multi-value partial failure
- **WHEN** one combination execute fails (SAP error) in a confirmed batch
- **THEN** `continue_batch` returns partial results with the failed combination annotated
- **AND** does not fail the entire batch

#### Scenario: Multi-value combination cap
- **WHEN** the expanded combinations exceed the soft cap (default 20)
- **THEN** the orchestrator emits CLARIFY "组合数过多，请缩小范围" instead of `awaiting_batch_confirm`
- **AND** does NOT execute any Gateway call

```

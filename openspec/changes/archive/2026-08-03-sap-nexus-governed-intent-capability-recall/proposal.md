## Why

Runbook 13 已让一次 Agent run 共享同一 `RegistrySnapshot`，但意图层仍是扁平 `IntentParseResult`：无目标/约束/证据版本化 envelope，无 closed-set recall / bounded rerank 阶段，LLM 输出未知 capability 或非法参数时静默丢弃无 audit trail，SHOW_OPTIONS / ESCALATE_TO_PLANNER 缺乏跨轮 continuation。当前 LLM 候选直进 deterministic matcher，无法保证 LLM 永远是 advisory 且每个 decision 可回放到 envelope / 候选 / 过滤原因 / snapshot。

Runbook 13 已交付的 `GovernedContext` / `SnapshotLease` / `VisibleCapabilitySet` / `PlannerFailure` 为本 change 提供了同快照与 visibility pre-filter 基线，现在可以在此基础上把意图层升级为受治理 LLM-first `IntentEnvelope` + closed-set recall + bounded rerank + 完整跨轮 continuation。

## What Changes

- **新增 `IntentEnvelope` 数据结构**（替换 `IntentParseResult`，**BREAKING**）：携带 goals / candidate capabilities / parameter candidates / user constraints / ambiguities / reference turn / model evidence / snapshotId，是 LLM 候选的版本化载体。
- **新增 closed-set recall 阶段**：lexical + alias + example 三路召回，输入是 `VisibleCapabilitySet` + utterance，输出是候选 capability 列表（advisory）。
- **新增 bounded rerank 阶段**：在 deterministic matcher 之前对 recall 候选做有界 rerank（不引入 embedding/RAG），输出 ranked candidates + rerank evidence。
- **新增 LLM 输出 discard + 结构化原因**：LLM 候选含未知 capability / 技术字段 / 非法参数时丢弃并产生结构化原因（audit trail），不再静默丢弃。
- **新增完整跨轮 continuation 状态机**：SHOW_OPTIONS 选项跨轮记忆、ESCALATE_TO_PLANNER 跨轮续接 planner（新状态，超出 Runbook 19A sticky-CLARIFY 范围）。
- **新增回放契约**：每个 `MatchDecision` 可回放到 envelope / recall candidates / rerank evidence / 过滤原因 / snapshotId。
- **修改 `select_capability` 签名**：从消费 `IntentParseResult` 改为消费 `IntentEnvelope`（**BREAKING**），并入 recall + rerank 阶段。
- **修改 `IntentAdapter` 签名**：返回 `IntentEnvelope` 而非 `IntentParseResult`（**BREAKING**），保留 `ConversationContext` 参数。
- **修改 LLM prompt schema**：输出 JSON schema 升级为 `IntentEnvelope` 形态，包含 goals / candidates / constraints / ambiguities / evidence。
- **扩展 `evals/matcher_cases.yaml`**：覆盖单能力 SELECT、多目标 ESCALATE、歧义 SHOW_OPTIONS、能力缺口 REJECT、技术覆盖 REJECT、越权 REJECT、跨轮 CLARIFY、跨轮 SHOW_OPTIONS、跨轮 ESCALATE、LLM 不可用 fallback、回放共 11 类场景。
- **修改 `conversation_context.py`**：新增 SHOW_OPTIONS / ESCALATE 跨轮状态字段（advisory，不续接执行权威）。

## Capabilities

### New Capabilities

- `governed-intent-envelope-recall`: LLM-first `IntentEnvelope` 数据结构、closed-set recall（lexical+alias+example）、bounded rerank、LLM 输出 discard + 结构化原因、回放契约、跨轮 SHOW_OPTIONS / ESCALATE_TO_PLANNER continuation 状态机。

### Modified Capabilities

- `semantic-match-decision`: `select_capability` 从消费 `IntentParseResult` 改为消费 `IntentEnvelope`，并入 recall + rerank 阶段；`MatchDecision` 新增回放字段（envelope_id / recall_candidates / rerank_evidence / discard_reasons）。
- `conversational-context`: `ConversationContext` 新增 SHOW_OPTIONS / ESCALATE 跨轮 advisory 状态字段；`IntentAdapter` 签名返回 `IntentEnvelope`。

## Impact

- **代码**：`llm_intent.py` / `intent.py` / `capability_selector.py` / `match_decision.py` / `conversation_context.py` / `orchestrator.py` / `cli.py` 全量迁移到 `IntentEnvelope`；LLM prompt schema 升级。
- **APIs**：`IntentAdapter` callable 签名 BREAKING（返回类型变更）；`select_capability` 入参 BREAKING。
- **依赖**：无新增外部依赖；不引入 embedding / vector store / RAG。
- **测试**：`test_llm_intent.py` / `test_match_decision.py` / `test_capability_selector.py` / `test_intent.py` 全量更新；`evals/matcher_cases.yaml` 扩展。
- **向后兼容**：`IntentParseResult` 移除（BREAKING）；`MatchedIntent` / `EscalationHandoff` / 五态 `MatchDecision` 保留；rule fallback 路径产出 `IntentEnvelope`（goals/candidates 由规则派生）。
- **安全边界**：LLM 候选永远是 advisory；`SELECT` 必须唯一且 required parameters 满足；Action intent 只能形成 proposal 方向；LLM 不可补写 Registry 未声明的参数或 capability relation；不可见 capability 在 recall 入口即丢弃。

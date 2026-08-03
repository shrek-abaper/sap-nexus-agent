# Comet Design Handoff

- Change: sap-nexus-governed-intent-capability-recall
- Phase: design
- Mode: compact
- Context hash: 66e60523c3f46289ac96098a189dee0b28a7140aa49b9b774285d5ab17c37add

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/sap-nexus-governed-intent-capability-recall/proposal.md

- Source: openspec/changes/sap-nexus-governed-intent-capability-recall/proposal.md
- Lines: 1-39
- SHA256: be6755a23158cc7a5c6dbe1b0d6a7218571f527534a274a5565bd98260f87796

```md
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

```

## openspec/changes/sap-nexus-governed-intent-capability-recall/design.md

- Source: openspec/changes/sap-nexus-governed-intent-capability-recall/design.md
- Lines: 1-182
- SHA256: 973b315efc3e03b6f20f251b89d02d35522b9726c01f0163ac29641b0e813d49

[TRUNCATED]

```md
## Context

Runbook 13 已归档：`GovernedContext` / `SnapshotLease` / `VisibleCapabilitySet` / `PlannerFailure` 数据结构落地，`select_capability` 入口接 `VisibleCapabilitySet`，visibility pre-filter 在 matcher 之前。但意图层仍是扁平 `IntentParseResult`：

- 无 goals / constraints / evidence / snapshotId 版本化 envelope。
- LLM 候选直进 deterministic matcher，无独立 recall / rerank 阶段。
- LLM 输出未知 capability / 技术字段 / 非法参数时静默丢弃，无 audit trail。
- SHOW_OPTIONS / ESCALATE_TO_PLANNER 无跨轮 continuation（Runbook 19A 只做了 sticky-CLARIFY）。

当前 active capability 仅 3 个（Inventory / PO / PR），不接 embedding / RAG，但本 change 仍按 Runbook 14 要求实现完整 lexical + alias + example recall + bounded rerank，为规模扩展预留架构。

## Goals / Non-Goals

**Goals:**

- 新增版本化 `IntentEnvelope` 数据结构，替换 `IntentParseResult`。
- 新增 closed-set recall 阶段（lexical + alias + example 三路）。
- 新增 bounded rerank 阶段（无 embedding / RAG）。
- LLM 输出 discard + 结构化原因（audit trail）。
- 完整跨轮 continuation 状态机（SHOW_OPTIONS 选项记忆 + ESCALATE 续接 planner）。
- 每个 `MatchDecision` 可回放到 envelope / recall candidates / rerank evidence / 过滤原因 / snapshotId。
- rule fallback 路径产出 `IntentEnvelope`（goals/candidates 由规则派生）。

**Non-Goals:**

- 不改 matcher 五态算法本身（SELECT / CLARIFY / REJECT / SHOW_OPTIONS / ESCALATE_TO_PLANNER 语义不变）。
- 不执行能力 / 不生成任意工具。
- 不接 embedding / vector store / Knowledge / RAG / 跨会话相似问题检索。
- 不重建身份 / 状态 / 审批 / 事件机制（复用 P0B + Runbook 13）。
- 不改 `GovernedContext` / `SnapshotLease` / `VisibleCapabilitySet` / `PlannerFailure` 数据结构。
- 不实现 PlanExecutor / OutputProjection / WRITE（Runbook 16-21 范围）。

## Decisions

### D1: `IntentEnvelope` 替换 `IntentParseResult`（BREAKING）

**决策**：新增 `IntentEnvelope` dataclass，全量替换 `IntentParseResult`，所有调用方迁移。

**结构草案**：

```python
@dataclass(frozen=True)
class IntentGoal:
    goal_text: str               # 用户原始目标文本
    capability_hint: str | None  # LLM 候选 capability_id（advisory）
    parameters: dict[str, str]   # LLM 候选参数（advisory）
    missing: list[str]           # LLM 声称缺失的参数（advisory）

@dataclass(frozen=True)
class IntentEnvelope:
    envelope_id: str             # UUID，用于回放
    utterance: str
    goals: tuple[IntentGoal, ...]
    user_constraints: dict[str, str]
    ambiguities: list[str]
    reference_turn_id: str | None
    model_evidence: dict         # LLM 原始 payload 摘要
    snapshot_id: str             # 来自 GovernedContext
    discard_reasons: list[str]   # LLM 输出被丢弃的字段+原因
    created_by: Literal["llm", "rule"]  # fallback 标记
```

**替代方案**：

- **B 包装**（`IntentEnvelope` 外层 + `IntentParseResult` 内部字段）：兼容好，但双结构并存增加迁移负担，且 `IntentParseResult` 字段集与 envelope 不对齐。
- **C 扩展**（`IntentParseResult` 直接加字段）：最小改动，但结构臃肿，且无法表达 goals 多目标列表。

**理由**：A 干净，避免双结构并存；`IntentParseResult` 当前字段（intent_name / parameters / matched_intents / is_ambiguous）可由 envelope 的 goals + ambiguities 派生，无需保留。

### D2: closed-set recall 三路合并 + bounded rerank

**决策**：recall 阶段输入 `VisibleCapabilitySet` + utterance，输出候选 capability 列表；rerank 阶段对候选做有界排序。

```text
utterance + VisibleCapabilitySet
  -> lexical recall (keyword match against capability name/description)
  -> alias recall (capability aliases from registry)
  -> example recall (capability examples from registry)
  -> merge + dedupe -> recall_candidates
  -> bounded rerank (heuristic scoring, no embedding)

```

Full source: openspec/changes/sap-nexus-governed-intent-capability-recall/design.md

## openspec/changes/sap-nexus-governed-intent-capability-recall/tasks.md

- Source: openspec/changes/sap-nexus-governed-intent-capability-recall/tasks.md
- Lines: 1-93
- SHA256: 34311715fd86ce355f736df381a7627dda288fec4e075408980242b5cb557129

[TRUNCATED]

```md
## 1. 数据结构

- [ ] 1.1 新增 `IntentGoal` dataclass（frozen）：`goal_text` / `capability_hint` / `parameters` / `missing`
- [ ] 1.2 新增 `IntentEnvelope` dataclass（frozen）：`envelope_id` / `utterance` / `goals` / `user_constraints` / `ambiguities` / `reference_turn_id` / `model_evidence` / `snapshot_id` / `discard_reasons` / `created_by`
- [ ] 1.3 新增 `PendingShowOptions` dataclass（frozen）：`candidates` / `snapshot_id`
- [ ] 1.4 新增 `PendingEscalate` dataclass（frozen）：`handoff` / `snapshot_id`
- [ ] 1.5 扩展 `MatchDecision` 回放字段：`envelope_id` / `recall_candidates` / `rerank_evidence` / `discard_reasons`

## 2. 召回阶段（recall）

- [ ] 2.1 实现 lexical recall：对 `VisibleCapabilitySet` 中 capability name/description 做关键词匹配
- [ ] 2.2 实现 alias recall：对 registry 中 capability aliases 做匹配
- [ ] 2.3 实现 example recall：对 registry 中 capability examples 做匹配
- [ ] 2.4 实现 recall 合并 + 按 `capability_id` 去重；输出 `recall_candidates`

## 3. 有界 rerank 阶段

- [ ] 3.1 实现 rerank 评分：LLM hint (+3) / lexical (+2) / alias (+2) / example (+1) / 参数 fit (+1)
- [ ] 3.2 实现稳定 tie-break：同分按 `capability_id` 字典序
- [ ] 3.3 输出 `ranked_candidates` + `rerank_evidence`（每个候选的评分明细）

## 4. LLM 输出 discard + 结构化原因

- [ ] 4.1 检测 LLM payload 中未知 capability（不在 `VisibleCapabilitySet`）；丢弃并记录 `"unknown_capability:<id>"`
- [ ] 4.2 检测技术字段（`baseUrl` / `rfcName` / `credential` 等）；丢弃并记录 `"technical_field:<name>"`
- [ ] 4.3 检测非法参数（`__proto__` 等）；丢弃并记录 `"invalid_param:<name>"`
- [ ] 4.4 填充 `IntentEnvelope.discard_reasons`（LLM 输出完全合法时为空）

## 5. IntentEnvelope 产出

- [ ] 5.1 升级 LLM prompt schema：输出 JSON 含 `goals` / `candidates` / `constraints` / `ambiguities` / `evidence`
- [ ] 5.2 实现 `_payload_to_envelope`（替换 `_payload_to_parse_result`）：LLM payload → `IntentEnvelope`
- [ ] 5.3 从 `GovernedContext` 绑定 `snapshot_id` 到 `IntentEnvelope`
- [ ] 5.4 实现 rule fallback 路径产出 `IntentEnvelope`（`created_by="rule"`，`model_evidence` 为空）
- [ ] 5.5 升级 `IntentAdapter` callable 签名：返回 `IntentEnvelope`（BREAKING）

## 6. selector 升级

- [ ] 6.1 升级 `select_capability` 签名：消费 `IntentEnvelope` + `recall_candidates` + `rerank_evidence`（BREAKING）
- [ ] 6.2 在 deterministic matcher 之前接入 recall + rerank 阶段
- [ ] 6.3 填充 `MatchDecision` 回放字段（`envelope_id` / `recall_candidates` / `rerank_evidence` / `discard_reasons`）
- [ ] 6.4 新增 `REJECT(VISIBILITY_DENIED)`：LLM 候选不在 `VisibleCapabilitySet` 时
- [ ] 6.5 移除 `SelectionResult` + `to_selection_result()` compat 桥（BREAKING）

## 7. 跨轮 continuation

- [ ] 7.1 扩展 `ConversationContext`：新增 `pending_show_options` / `pending_escalate` 字段
- [ ] 7.2 实现互斥：写入新 pending 状态时清除已有 pending 状态
- [ ] 7.3 实现 SHOW_OPTIONS 跨轮：Turn N 写 `PendingShowOptions`，Turn N+1 选择清除 + SELECT
- [ ] 7.4 实现 ESCALATE 跨轮：Turn N 写 `PendingEscalate`，Turn N+1 确认清除 + planner handoff（仅 dry-run）
- [ ] 7.5 实现新意图丢弃：Turn N+1 含新 primary keyword 时清除所有 pending 状态

## 8. 调用方迁移

- [ ] 8.1 迁移 `orchestrator.py`：消费 `IntentEnvelope` + 新 `MatchDecision` 回放字段
- [ ] 8.2 迁移 `cli.py`：产出 `IntentEnvelope`（rule + LLM 路径）
- [ ] 8.3 迁移 `llm_intent.py`：`parse_with_llm` / `parse_with_hybrid` / `build_intent_adapter` 返回 `IntentEnvelope`
- [ ] 8.4 移除 `IntentParseResult` 及所有引用（BREAKING）
- [ ] 8.5 验证无残留 `IntentParseResult` / `SelectionResult` import

## 9. 测试

- [ ] 9.1 更新 `test_llm_intent.py`：断言 `IntentEnvelope` shape / `discard_reasons` / `created_by` / `snapshot_id`
- [ ] 9.2 更新 `test_match_decision.py`：断言 5 种 decision type 的回放字段
- [ ] 9.3 更新 `test_capability_selector.py`：断言 recall + rerank 集成 / `VISIBILITY_DENIED` REJECT
- [ ] 9.4 更新 `test_intent.py`：断言 rule fallback 产出 `IntentEnvelope`
- [ ] 9.5 新增跨轮 SHOW_OPTIONS 测试（Turn N 写入 / Turn N+1 选择 / Turn N+1 新意图丢弃）
- [ ] 9.6 新增跨轮 ESCALATE 测试（Turn N 写入 / Turn N+1 确认 / Turn N+1 新意图丢弃）
- [ ] 9.7 新增互斥测试（CLARIFY ↔ SHOW_OPTIONS ↔ ESCALATE）
- [ ] 9.8 新增 discard reason 测试（未知 capability / 技术字段 / 非法参数 / 合法时为空）

## 10. Eval 扩展

- [ ] 10.1 新增 eval case：单能力 SELECT（goal count = 1）
- [ ] 10.2 新增 eval case：多目标 ESCALATE_TO_PLANNER（goal count >= 2）
- [ ] 10.3 新增 eval case：歧义 SHOW_OPTIONS
- [ ] 10.4 新增 eval case：能力缺口 REJECT（未知 capability）
- [ ] 10.5 新增 eval case：技术覆盖 REJECT（OData / 技术字段）
- [ ] 10.6 新增 eval case：越权 REJECT（不可见 capability）
- [ ] 10.7 新增 eval case：跨轮 CLARIFY（已有，确保兼容）

```

Full source: openspec/changes/sap-nexus-governed-intent-capability-recall/tasks.md

## openspec/changes/sap-nexus-governed-intent-capability-recall/specs/conversational-context/spec.md

- Source: openspec/changes/sap-nexus-governed-intent-capability-recall/specs/conversational-context/spec.md
- Lines: 1-50
- SHA256: 5d984e2ed9b6433ba47963b95ade6c31e5182846c7154335cbec2351c82fd039

```md
## MODIFIED Requirements

### Requirement: Conversation session state
The system SHALL maintain a per-conversation `ConversationState` in a durable store, keyed by `conversationId`, holding an optional `PendingClarification`, `PendingShowOptions`, or `PendingEscalate` (at most one pending state at any time, mutual exclusivity enforced). The state SHALL be advisory context only and MUST NOT influence `PlanExecutionState` or `EvidenceState`, and MUST NOT influence `CallPlan` / `ApprovalRecord` lifecycle. The system SHALL persist `PendingShowOptions` and `PendingEscalate` via the same durable path as `PendingClarification` (P0B `ConversationState` durable store), ensuring cross-restart recovery and multi-worker shared view. The `ConversationContext` dataclass SHALL expose `pending_show_options` and `pending_escalate` fields alongside `last_context` and `history`. The `IntentAdapter` callable SHALL return `IntentEnvelope` (not `IntentParseResult`), preserving the `ConversationContext` parameter for cross-turn continuation.

#### Scenario: New conversation starts with no pending state
- **WHEN** the frontend generates a new `conversationId` via the "new conversation" button
- **THEN** the backend creates an empty `ConversationState` with `pending_clarification=null`, `pending_show_options=null`, `pending_escalate=null`
- **AND** subsequent queries within that conversation are grouped under the same `conversationId`

#### Scenario: Process restart preserves sessions
- **WHEN** the Workbench backend process restarts
- **THEN** all `ConversationState` is recovered from the durable store
- **AND** a follow-up query with an existing `conversationId` resumes with its prior `PendingClarification` / `PendingShowOptions` / `PendingEscalate` / `LastContext` intact
- **AND** multi-worker deployments share the same `ConversationState` view

#### Scenario: PendingShowOptions durable persistence
- **WHEN** turn N produces `SHOW_OPTIONS` and `PendingShowOptions` is written to `ConversationContext`
- **AND** the backend process restarts before turn N+1
- **THEN** `PendingShowOptions` is recovered from the durable store on restart
- **AND** turn N+1 can still select a candidate from the preserved options

#### Scenario: PendingEscalate durable persistence
- **WHEN** turn N produces `ESCALATE_TO_PLANNER` and `PendingEscalate` is written to `ConversationContext`
- **AND** the backend process restarts before turn N+1
- **THEN** `PendingEscalate` is recovered from the durable store on restart
- **AND** turn N+1 can still confirm continuation to the planner

#### Scenario: IntentAdapter returns IntentEnvelope
- **WHEN** the `IntentAdapter` is invoked with an utterance and a `ConversationContext`
- **THEN** the return type is `IntentEnvelope` (not `IntentParseResult`)
- **AND** the `ConversationContext` is consumed for cross-turn continuation (sticky-CLARIFY / SHOW_OPTIONS / ESCALATE)

## ADDED Requirements

### Requirement: Cross-turn pending state mutual exclusivity
The system SHALL enforce at most one of `PendingClarification`, `PendingShowOptions`, `PendingEscalate` is set in `ConversationContext` at any time. Writing a new pending state SHALL clear any existing pending state. All pending states are advisory only and MUST NOT carry execution authority.

#### Scenario: SHOW_OPTIONS clears pending CLARIFY
- **WHEN** `ConversationContext.pending_clarification` is set and a new turn produces `SHOW_OPTIONS`
- **THEN** `pending_clarification` is cleared before `pending_show_options` is set

#### Scenario: CLARIFY clears pending SHOW_OPTIONS
- **WHEN** `ConversationContext.pending_show_options` is set and a new turn produces `CLARIFY`
- **THEN** `pending_show_options` is cleared before `pending_clarification` is set

#### Scenario: New intent clears all pending states
- **WHEN** a new turn contains a primary keyword for any registered capability
- **THEN** all pending states (`pending_clarification`, `pending_show_options`, `pending_escalate`) are cleared
- **AND** the new turn is processed as a fresh intent

```

## openspec/changes/sap-nexus-governed-intent-capability-recall/specs/governed-intent-envelope-recall/spec.md

- Source: openspec/changes/sap-nexus-governed-intent-capability-recall/specs/governed-intent-envelope-recall/spec.md
- Lines: 1-158
- SHA256: 6ee1b341e988175e4bc77b502c4bbcf8ddd3b1765cad0ba64acceb5d34c081fb

[TRUNCATED]

```md
## ADDED Requirements

### Requirement: Versioned IntentEnvelope data structure

The system SHALL replace the flat `IntentParseResult` with a versioned `IntentEnvelope` as the LLM-first intent carrier. `IntentEnvelope` SHALL carry `envelope_id` (UUID for replay), `utterance`, `goals` (tuple of `IntentGoal`), `user_constraints`, `ambiguities`, `reference_turn_id`, `model_evidence`, `snapshot_id` (from `GovernedContext`), `discard_reasons`, and `created_by` (`"llm"` or `"rule"`). Each `IntentGoal` SHALL carry `goal_text`, `capability_hint` (advisory), `parameters` (advisory), and `missing` (advisory). `IntentEnvelope` SHALL be immutable (frozen dataclass). `IntentParseResult` SHALL be removed (BREAKING).

#### Scenario: LLM path produces IntentEnvelope with snapshot_id
- **WHEN** the LLM intent path parses an utterance under a `GovernedContext` with `snapshot_id="snap-001"`
- **THEN** the returned `IntentEnvelope.snapshot_id="snap-001"` and `created_by="llm"`
- **AND** `envelope_id` is a non-empty UUID
- **AND** `goals` contains at least one `IntentGoal` derived from the LLM payload

#### Scenario: Rule fallback produces IntentEnvelope
- **WHEN** the LLM is unavailable (`LlmUnavailable`) and the rule fallback path runs
- **THEN** the returned `IntentEnvelope.created_by="rule"`
- **AND** `model_evidence` is empty
- **AND** `goals` are derived from rule-based keyword matching
- **AND** `snapshot_id` is still bound to the current `GovernedContext`

#### Scenario: IntentParseResult removed
- **WHEN** any caller previously consumed `IntentParseResult`
- **THEN** the type is no longer importable and the caller MUST consume `IntentEnvelope` instead

### Requirement: Closed-set recall stage

The system SHALL apply a closed-set recall stage before the deterministic matcher, taking `VisibleCapabilitySet` + utterance as input and producing `recall_candidates` (advisory). The recall SHALL merge three independent sources: lexical recall (keyword match against capability name/description), alias recall (capability aliases from registry), and example recall (capability examples from registry). The recall SHALL dedupe candidates by `capability_id`. The recall SHALL NOT produce a `MatchDecision` (advisory only). The recall SHALL NOT use embedding, vector store, or RAG.

#### Scenario: Lexical recall matches capability name
- **WHEN** the utterance contains "库存" and `VisibleCapabilitySet` contains `MM.Inventory.GetAvailability` with "库存" in its name/description
- **THEN** `MM.Inventory.GetAvailability` is included in `recall_candidates`

#### Scenario: Alias recall matches capability alias
- **WHEN** the utterance contains "PO" and `VisibleCapabilitySet` contains `MM.PurchaseOrder.GetList` with alias "PO"
- **THEN** `MM.PurchaseOrder.GetList` is included in `recall_candidates`

#### Scenario: Example recall matches capability example
- **WHEN** the utterance resembles a registered example for `MM.PR.CreateDraft`
- **THEN** `MM.PR.CreateDraft` is included in `recall_candidates`

#### Scenario: Unknown capability is not recalled
- **WHEN** the utterance mentions "Foo.Bar" which is not in `VisibleCapabilitySet`
- **THEN** `Foo.Bar` is NOT included in `recall_candidates`
- **AND** the LLM candidate `capability_hint="Foo.Bar"` is recorded in `discard_reasons`

### Requirement: Registry aliases and examples fields

The system SHALL extend the capability registry schema with optional `aliases` (list of strings) and `examples` (list of strings) fields per capability. These fields SHALL be the data source for alias recall and example recall respectively. The fields SHALL be optional; when absent, the corresponding recall source returns empty for that capability. The `CapabilityDescriptor` loaded by `registry_loader.py` SHALL expose `aliases` and `examples` as tuple fields. Existing capabilities without these fields SHALL continue to load successfully (backward compatible).

#### Scenario: Capability with aliases and examples
- **WHEN** `MM.Inventory.GetAvailability` has `aliases: ["库存查询", "物料可用量"]` and `examples: ["查物料 DEMOA2 在 1000 工厂的库存"]`
- **THEN** `CapabilityDescriptor.aliases=("库存查询", "物料可用量")` and `CapabilityDescriptor.examples=("查物料 DEMOA2 在 1000 工厂的库存",)`

#### Scenario: Capability without aliases and examples
- **WHEN** a capability does not have `aliases` or `examples` fields in the registry
- **THEN** `CapabilityDescriptor.aliases=()` and `CapabilityDescriptor.examples=()`
- **AND** the capability still loads successfully

#### Scenario: Alias recall uses registry aliases
- **WHEN** the utterance contains "库存查询" and `MM.Inventory.GetAvailability` has alias "库存查询"
- **THEN** `MM.Inventory.GetAvailability` is included in `recall_candidates` via alias recall

### Requirement: Bounded rerank stage

The system SHALL apply a bounded rerank stage after recall, scoring `recall_candidates` by heuristic (no embedding): LLM `capability_hint` match (+3), lexical match (+2), alias match (+2), example match (+1), parameter fit (required parameters satisfied, +1). Parameter fit SHALL be determined by checking whether the LLM-provided parameters in `IntentGoal.parameters` cover all required inputs of the candidate capability (consistent with the selector's `missing` computation); if all required inputs are covered, +1, otherwise +0. The rerank SHALL output `ranked_candidates` (sorted desc by score) and `rerank_evidence` (per-candidate score breakdown). The rerank SHALL NOT produce a `MatchDecision` (advisory only).

#### Scenario: LLM hint ranks first
- **WHEN** LLM `capability_hint="MM.Inventory.GetAvailability"` and recall includes `MM.Inventory.GetAvailability` and `MM.PurchaseOrder.GetList`
- **THEN** `MM.Inventory.GetAvailability` has score >= 5 (hint + lexical + param fit) and ranks first in `ranked_candidates`
- **AND** `rerank_evidence` contains the score breakdown for each candidate

#### Scenario: Tie-break is stable
- **WHEN** two candidates have the same rerank score
- **THEN** the tie is broken by `capability_id` alphabetical order (stable, deterministic)

#### Scenario: Parameter fit only when all required inputs covered
- **WHEN** LLM provides parameters `{"material": "DEMOA2"}` for `MM.Inventory.GetAvailability` (required: material + plant)
- **THEN** parameter fit is +0 (plant missing), so the candidate does NOT get the +1 bonus
- **AND** when LLM provides `{"material": "DEMOA2", "plant": "1000"}`, parameter fit is +1

### Requirement: LLM output discard with structured reasons

```

Full source: openspec/changes/sap-nexus-governed-intent-capability-recall/specs/governed-intent-envelope-recall/spec.md

## openspec/changes/sap-nexus-governed-intent-capability-recall/specs/semantic-match-decision/spec.md

- Source: openspec/changes/sap-nexus-governed-intent-capability-recall/specs/semantic-match-decision/spec.md
- Lines: 1-29
- SHA256: d75c0a0228b2b2eaa72c4073e7233f8f6783ea5c67e599788450bc8b5adadd74

```md
## MODIFIED Requirements

### Requirement: Five-state MatchDecision object
The system SHALL produce a `MatchDecision` as the selector output with `decision_type` exactly one of `SELECT`, `CLARIFY`, `REJECT`, `SHOW_OPTIONS`, `ESCALATE_TO_PLANNER`, plus `candidates`, `rationale`, and `handoff` fields. `SELECT` SHALL carry exactly one `capabilityId` with complete parameters; `CLARIFY` SHALL carry missing parameters; `REJECT` SHALL carry an error type; `SHOW_OPTIONS` SHALL carry visible candidates; `ESCALATE_TO_PLANNER` SHALL carry a record and explanation. The `MatchDecision` SHALL additionally carry `envelope_id`, `recall_candidates`, `rerank_evidence`, and `discard_reasons` fields to support decision replay (tracing back to the `IntentEnvelope`, recall candidates, rerank evidence, filter reasons, and `snapshot_id`). The legacy `SelectionResult` compat wrapper and `to_selection_result()` bridge SHALL be removed (BREAKING).

#### Scenario: SELECT with complete parameters
- **WHEN** a single intent is detected with all required parameters
- **THEN** `MatchDecision.decision_type=SELECT` with the resolved `capabilityId` and parameters
- **AND** `MatchDecision.envelope_id` matches the `IntentEnvelope` that produced the decision
- **AND** `MatchDecision.recall_candidates` and `MatchDecision.rerank_evidence` are non-empty

#### Scenario: CLARIFY on missing parameter
- **WHEN** a single intent is detected but a required parameter is missing
- **THEN** `MatchDecision.decision_type=CLARIFY` with the missing parameter list and clarification text
- **AND** `MatchDecision.envelope_id` is set for replay

#### Scenario: REJECT on technical override
- **WHEN** the utterance contains `rfcName` or OData override
- **THEN** `MatchDecision.decision_type=REJECT` with `error_type=UNSUPPORTED_RFC_NAME`
- **AND** `MatchDecision.discard_reasons` contains the structured reason for the discarded technical field

#### Scenario: REJECT on visibility denial
- **WHEN** the LLM candidate contains a capability not in `VisibleCapabilitySet`
- **THEN** `MatchDecision.decision_type=REJECT` with `error_type=VISIBILITY_DENIED`
- **AND** `MatchDecision.discard_reasons` contains `"unknown_capability:<id>"`

#### Scenario: SelectionResult removed
- **WHEN** any caller previously used `SelectionResult` or `to_selection_result()`
- **THEN** the compat wrapper is no longer available and the caller MUST inspect `decision_type` directly

```

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
  -> ranked_candidates + rerank_evidence
```

**recall 与 matcher 的边界**：recall 只负责候选发现（advisory），不产出 `MatchDecision`；deterministic matcher 消费 `IntentEnvelope` + `ranked_candidates` 产出 `MatchDecision`。

**bounded rerank 评分**（无 embedding）：

- LLM 候选 capability_hint 命中：+3
- lexical 命中：+2
- alias 命中：+2
- example 命中：+1
- 参数 fit（required parameters 满足）：+1

**替代方案**：

- **B 只做 closed-set validation**（LLM 候选必须在 VisibleCapabilitySet 内）：当前 3 个 capability 收益小，但 Runbook 14 明确要求 recall + rerank，且为规模扩展预留。
- **C 简化 recall（alias+example）无独立 rerank**：deterministic matcher 兼任 rerank，但职责混淆。

**理由**：A 符合 Runbook 14 契约，recall / rerank / matcher 三阶段职责清晰，为 capability 规模扩展预留架构。

### D3: LLM 输出 discard + 结构化原因

**决策**：LLM 输出未知 capability / 技术字段 / 非法参数时，丢弃该字段并写入 `IntentEnvelope.discard_reasons`，不静默丢弃。

```python
discard_reasons: list[str]  # e.g. ["unknown_capability:Foo.Bar", "technical_field:baseUrl", "invalid_param:__proto__"]
```

**回放契约**：`MatchDecision` 新增 `envelope_id` / `recall_candidates` / `rerank_evidence` / `discard_reasons` 字段，任何 decision 可回放到完整 advisory 链路。

### D4: 跨轮 continuation 状态机

**决策**：`ConversationContext` 新增 advisory 跨轮状态字段，SHOW_OPTIONS / ESCALATE 跨轮续接。

```python
@dataclass(frozen=True)
class PendingShowOptions:
    candidates: tuple[MatchedIntent, ...]
    snapshot_id: str

@dataclass(frozen=True)
class PendingEscalate:
    handoff: EscalationHandoff
    snapshot_id: str

# ConversationContext 新增：
# pending_show_options: PendingShowOptions | None
# pending_escalate: PendingEscalate | None
```

**跨轮流转**：

- Turn N SHOW_OPTIONS → 写入 `pending_show_options` → Turn N+1 用户选择 → 清除 `pending_show_options` → SELECT
- Turn N ESCALATE_TO_PLANNER → 写入 `pending_escalate` → Turn N+1 用户续接 → 清除 `pending_escalate` → planner 续接（advisory，不续接执行权威）

**与 Runbook 19A sticky-CLARIFY 的关系**：`PendingClarification` 保留，新增 `PendingShowOptions` / `PendingEscalate` 与之并列，互斥（同一时刻最多一个 pending）。

**安全边界**：跨轮状态永远是 advisory，不携带执行权威；`SELECT` / `CallPlan` / `ApprovalRecord` 生命周期不读取这些字段。

### D5: rule fallback 产出 `IntentEnvelope`

**决策**：`LlmUnavailable` 时 rule fallback 路径产出 `IntentEnvelope`（`created_by="rule"`），goals / candidates 由规则派生，`model_evidence` 为空。

**理由**：统一数据结构，下游 matcher 无需区分 LLM / rule 路径；`created_by` 字段保留可观测性。

### D6: `IntentAdapter` 与 `select_capability` 签名升级（BREAKING）

**决策**：

- `IntentAdapter` callable 返回 `IntentEnvelope` 而非 `IntentParseResult`。
- `select_capability` 入参从 `IntentParseResult` 改为 `IntentEnvelope`，并入 `recall_candidates` / `rerank_evidence` 参数。

**迁移**：所有调用方（`orchestrator.py` / `cli.py` / 测试）全量更新；移除 `IntentParseResult` / `to_selection_result()` compat 桥（`SelectionResult` 一并移除，五态 `MatchDecision` 已稳定）。

## Risks / Trade-offs

- **[BREAKING `IntentParseResult` 移除]** → 所有调用方全量迁移；测试同步更新；无外部 API 消费者（内部数据结构），blast radius 可控。
- **[BREAKING `SelectionResult` 移除]** → `to_selection_result()` compat 桥移除；`MatchDecision` 已稳定 1 个 release cycle，可删除。
- **[recall + rerank 在 3 个 capability 下收益小]** → 为规模扩展预留架构；当前 recall 候选几乎总是全集，rerank 评分差异小但不阻塞。
- **[跨轮 ESCALATE 续接 planner 边界]** → `pending_escalate` 是 advisory，不续接执行权威；planner 续接仍走 dry-run，不执行 Gateway。
- **[LLM prompt schema 升级风险]** → schema 变更可能触发 LLM 输出格式回归；需扩展 Eval 覆盖 discard 场景。
- **[rule fallback envelope 字段稀疏]** → `model_evidence` 为空、`discard_reasons` 为空；可观测性降级但行为可解释。

## Migration Plan

1. 新增 `IntentEnvelope` / `IntentGoal` / `PendingShowOptions` / `PendingEscalate` 数据结构。
2. 新增 recall（lexical/alias/example）+ bounded rerank 模块。
3. 升级 LLM prompt schema + `_payload_to_parse_result` 改为 `_payload_to_envelope`。
4. 升级 rule fallback 路径产出 `IntentEnvelope`。
5. 升级 `select_capability` 签名 + 并入 recall/rerank。
6. 升级 `IntentAdapter` callable 签名。
7. 升级 `ConversationContext` 跨轮状态字段。
8. 升级 `orchestrator.py` / `cli.py` 调用方。
9. 移除 `IntentParseResult` / `SelectionResult` / `to_selection_result()`。
10. 扩展 `evals/matcher_cases.yaml` 11 类场景。
11. 更新测试：`test_llm_intent.py` / `test_match_decision.py` / `test_capability_selector.py` / `test_intent.py`。

**回滚策略**：如 LLM prompt schema 升级触发回归，可临时切回 rule-only mode（`IntentAdapter` 仍返回 `IntentEnvelope`，`created_by="rule"`），不影响下游。

## Open Questions

无（Q1-Q4 已在 Step 1b 全部决策）。

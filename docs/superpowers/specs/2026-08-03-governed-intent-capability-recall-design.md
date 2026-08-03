---
comet_change: sap-nexus-governed-intent-capability-recall
role: technical-design
canonical_spec: openspec
---

# Governed Intent Envelope & Capability Recall 深度设计

> 本文档是 open 阶段 `design.md` 的深度技术细化，不替代或重写它。canonical spec 为 OpenSpec delta（`openspec/changes/sap-nexus-governed-intent-capability-recall/specs/`）。

## 1. Context

Runbook 13 已归档：`GovernedContext` / `SnapshotLease` / `VisibleCapabilitySet` / `PlannerFailure` 数据结构落地，`select_capability` 入口接 `VisibleCapabilitySet`，visibility pre-filter 在 matcher 之前。但意图层仍是扁平 `IntentParseResult`。

代码事实缺口（已核查）：

- `llm_intent.py`：`parse_with_llm` / `parse_with_hybrid` / `build_intent_adapter` 返回 `IntentParseResult`，无 envelope / goals / discard_reasons 字段。
- `_payload_to_parse_result`：LLM 输出未知 capability 时静默 `continue` 丢弃（无 audit trail）；技术字段只在 `contains_rfc_name` / `contains_odata_override` 全量丢弃，无逐字段 discard reason。
- `capability_selector.py`：`select_capability` 消费 `IntentParseResult`，无 recall / rerank 阶段；`SelectionResult` compat 桥仍存在。
- `conversation_context.py`：`ConversationContext` 只有 `last_context` / `history`，无 `pending_show_options` / `pending_escalate`。
- `registry/capabilities.yaml`：3 个 capability 均无 `aliases` / `examples` 字段（recall 三路缺数据源）。

Runbook 13 已交付的 `GovernedContext` / `SnapshotLease` / `VisibleCapabilitySet` / `PlannerFailure` 为本 change 提供了同快照与 visibility pre-filter 基线。

## 2. Goals / Non-Goals

**Goals**：见 open 阶段 design.md（IntentEnvelope 替换、closed-set recall + bounded rerank、discard + 结构化原因、完整跨轮 continuation、回放契约、rule fallback envelope）。

**Non-Goals**：不改 matcher 五态算法；不执行能力；不接 embedding/RAG；不重建身份/状态/审批/事件机制；不改 `GovernedContext` / `SnapshotLease` / `VisibleCapabilitySet` / `PlannerFailure`；不实现 PlanExecutor / OutputProjection / WRITE。

## 3. 核心数据结构

### 3.1 IntentGoal

```python
@dataclass(frozen=True)
class IntentGoal:
    goal_text: str               # 用户原始目标文本（LLM 提取或 rule 派生）
    capability_hint: str | None  # LLM 候选 capability_id（advisory，closed-set 校验后）
    parameters: dict[str, str]   # LLM 候选参数（advisory，allowlist 过滤后）
    missing: list[str]           # LLM 声称缺失的 required 参数（advisory）
```

### 3.2 IntentEnvelope

```python
@dataclass(frozen=True)
class IntentEnvelope:
    envelope_id: str               # uuid4().hex，回放主键
    utterance: str
    goals: tuple[IntentGoal, ...]  # LLM 多目标或 rule 单目标
    user_constraints: dict[str, str]  # LLM 提取的元约束（e.g. {"language": "zh-CN"}）
    ambiguities: list[str]         # LLM 声称的歧义点（advisory）
    reference_turn_id: str | None  # 跨轮时引用上一轮 turn_id，单轮为 None
    model_evidence: dict           # LLM payload 摘要（goals/candidates/constraints 字段）
    snapshot_id: str               # 从 GovernedContext 绑定
    discard_reasons: list[str]     # 结构化丢弃原因
    created_by: Literal["llm", "rule"]
```

**DT1 决策**：`model_evidence` 是 LLM payload 摘要（goals/candidates/constraints 字段），原始 payload 可选写入 trace（`raw_payload_ref`）。摘要用于回放，原始 payload 用于调试，二者分离。

### 3.3 PendingShowOptions / PendingEscalate

```python
@dataclass(frozen=True)
class PendingShowOptions:
    candidates: tuple[MatchedIntent, ...]
    snapshot_id: str

@dataclass(frozen=True)
class PendingEscalate:
    handoff: EscalationHandoff
    snapshot_id: str
```

**DT5 决策**：扩展 `ConversationContext` 新增 `pending_show_options` / `pending_escalate` 字段，与 `last_context` 同级；durable 持久化由 P0B `ConversationState` 接管（同 `last_context` 路径）。

### 3.4 MatchDecision 回放字段扩展

```python
@dataclass(frozen=True)
class MatchDecision:
    # 既有字段
    decision_type: DecisionType
    capability_id: str | None = None
    parameters: dict[str, str] | None = None
    missing_parameters: list[str] | None = None
    error_type: str | None = None
    candidates: list[MatchedIntent] | None = None
    handoff: EscalationHandoff | None = None
    rationale: str = ""
    # 新增回放字段
    envelope_id: str | None = None           # 关联 IntentEnvelope
    recall_candidates: list[str] | None = None    # recall 阶段候选 capability_id 列表
    rerank_evidence: dict[str, int] | None = None  # {capability_id: score}
    discard_reasons: list[str] | None = None      # 从 envelope 继承
```

## 4. 数据流（深度）

```text
cli.py
  读 SAP_NEXUS_PRINCIPAL env -> TrustedPrincipal
  load_intent_catalog() -> 全 active capability
  filter_visible(catalog, for_execution=False) -> visible catalog  [Runbook 13]
  build VisibleCapabilitySet(cards, snapshot_id, principal_id)     [Runbook 13]
  ->
  IntentAdapter(utterance, context, visible_capability_set, snapshot_id)
    LLM path:
      _messages(utterance, visible_catalog, context) -> LLM payload
      _payload_to_envelope(payload, visible_capability_set, snapshot_id)
        1. rfcName / OData override -> 全量丢弃，空 goals + discard_reasons
        2. 未知 capability_hint -> 丢弃该 hint，记录 unknown_capability:<id>
        3. 技术字段参数 -> 丢弃，记录 technical_field:<name>
        4. 非法参数名 -> 丢弃，记录 invalid_param:<name>
        5. 合法 goals -> IntentGoal tuple
      -> IntentEnvelope(created_by="llm", snapshot_id, discard_reasons)
    Rule fallback (LlmUnavailable):
      parse_intent(utterance) -> IntentParseResult（临时）
      _parse_result_to_envelope(result, snapshot_id)
      -> IntentEnvelope(created_by="rule", model_evidence={}, snapshot_id)
  ->
  recall(utterance, visible_capability_set)
    lexical:  utterance tokens ∩ CapabilityCard.name/description 关键词
    alias:    utterance tokens ∩ registry.aliases
    example:  utterance ∩ registry.examples（子串匹配）
    merge + dedupe by capability_id -> recall_candidates
  ->
  rerank(envelope, recall_candidates, visible_capability_set)
    score = LLM hint (+3) + lexical (+2) + alias (+2) + example (+1) + param fit (+1)
    tie-break: capability_id 字典序
    -> ranked_candidates + rerank_evidence
  ->
  select_capability(envelope, ranked_candidates, rerank_evidence, visible_capability_set)
    1. technical override -> REJECT(UNSUPPORTED_RFC_NAME) + discard_reasons
    2. envelope.goals > 1 -> ESCALATE_TO_PLANNER(handoff) + replay fields
    3. ambiguity -> SHOW_OPTIONS(candidates) + replay fields
    4. single goal missing params -> CLARIFY(missing) + replay fields
    5. single goal complete -> SELECT(capability_id, params) + replay fields
    6. no match -> REJECT(UNSUPPORTED_INTENT) + replay fields
    7. LLM hint not in visible set -> REJECT(VISIBILITY_DENIED) + discard_reasons
  ->
  MatchDecision + replay fields
  ->
  orchestrator.py: 根据 decision_type 分发
    SELECT -> CallPlan -> Gateway validate/execute
    CLARIFY -> 返回 clarification
    REJECT -> 返回 error
    SHOW_OPTIONS -> 写 PendingShowOptions 到 ConversationContext
    ESCALATE_TO_PLANNER -> 写 PendingEscalate 到 ConversationContext + planner dry-run
```

## 5. 模块改动

### 5.1 新增模块

```text
agent/sap_nexus_agent/
├── intent_envelope.py          # IntentGoal / IntentEnvelope dataclass
├── recall.py                   # lexical + alias + example recall + dedupe
├── rerank.py                   # bounded rerank scoring
└── discard.py                  # LLM payload discard + structured reasons
```

### 5.2 修改模块

| 模块 | 改动 |
|---|---|
| `llm_intent.py` | `parse_with_llm` / `parse_with_hybrid` / `build_intent_adapter` 返回 `IntentEnvelope`；`_payload_to_parse_result` → `_payload_to_envelope`；新增 `_parse_result_to_envelope`（rule fallback） |
| `intent.py` | 移除 `IntentParseResult`（BREAKING）；保留 `parse_intent` 临时返回 `IntentParseResult` 内部使用，或直接改为返回 `IntentEnvelope` |
| `capability_selector.py` | `select_capability` 消费 `IntentEnvelope` + `ranked_candidates` + `rerank_evidence`；移除 `SelectionResult` / `to_selection_result()`（BREAKING） |
| `match_decision.py` | `MatchDecision` 新增回放字段 |
| `conversation_context.py` | 新增 `PendingShowOptions` / `PendingEscalate` / `pending_show_options` / `pending_escalate` 字段 |
| `orchestrator.py` | 消费 `IntentEnvelope` + 新 `MatchDecision`；SHOW_OPTIONS / ESCALATE 写 pending 状态 |
| `cli.py` | 产出 `IntentEnvelope`（rule + LLM 路径） |
| `registry_loader.py` | `CapabilityDescriptor` 新增 `aliases: tuple[str, ...]` / `examples: tuple[str, ...]` 字段 |
| `registry/capabilities.yaml` | 3 个 capability 新增可选 `aliases: []` / `examples: []` 字段 |

## 6. registry schema 扩展（DT2=B）

```yaml
# registry/capabilities.yaml
- capabilityId: MM.Inventory.GetAvailability
  name: Inventory Availability
  description: Read material availability for a plant through SAP MD04 stock/requirements list.
  aliases:                          # 新增可选
    - 库存查询
    - 物料可用量
  examples:                         # 新增可选
    - "查物料 DEMOA2 在 1000 工厂的库存"
    - "DEMOA2 1000 还有多少"
  # ... 既有字段不变
```

**向后兼容**：`aliases` / `examples` 是可选字段；缺失时该 capability 的 alias/example recall 返回空。

## 7. discard 检测实现（DT4=A）

```python
# discard.py
TECHNICAL_FIELDS = frozenset({
    "baseUrl", "rfcName", "credential", "header", "token",
    "authorization", "destination", "serviceRef", "bindingId",
    "entitySet", "executorType", "sapClient", "csrf",
})

INVALID_PARAM_PATTERNS = re.compile(r"__proto__|constructor|prototype", re.IGNORECASE)

def detect_discard_reasons(
    payload: dict[str, object],
    visible_capability_ids: set[str],
) -> list[str]:
    reasons: list[str] = []
    # 1. rfcName / OData override 全量丢弃（在 _payload_to_envelope 入口处理）
    # 2. 未知 capability_hint
    for goal in payload.get("goals", []):
        hint = goal.get("capabilityHint")
        if hint and hint not in visible_capability_ids:
            reasons.append(f"unknown_capability:{hint}")
    # 3. 技术字段参数
    for goal in payload.get("goals", []):
        for key in goal.get("parameters", {}):
            if key in TECHNICAL_FIELDS:
                reasons.append(f"technical_field:{key}")
    # 4. 非法参数名
    for goal in payload.get("goals", []):
        for key in goal.get("parameters", {}):
            if INVALID_PARAM_PATTERNS.search(key):
                reasons.append(f"invalid_param:{key}")
    return reasons
```

## 8. 跨轮状态机实现（DT5=A）

```python
# conversation_context.py 扩展
@dataclass(frozen=True)
class ConversationContext:
    last_context: LastContext | None
    history: tuple[Turn, ...] | None
    pending_show_options: PendingShowOptions | None = None  # 新增
    pending_escalate: PendingEscalate | None = None         # 新增

    def with_pending_show_options(self, pending: PendingShowOptions | None) -> "ConversationContext":
        """写入 SHOW_OPTIONS pending，清除其他 pending（互斥）。"""
        from dataclasses import replace
        return replace(self, pending_show_options=pending, pending_escalate=None)

    def with_pending_escalate(self, pending: PendingEscalate | None) -> "ConversationContext":
        """写入 ESCALATE pending，清除其他 pending（互斥）。"""
        from dataclasses import replace
        return replace(self, pending_show_options=None, pending_escalate=pending)

    def clear_pending(self) -> "ConversationContext":
        """清除所有 pending 状态。"""
        from dataclasses import replace
        return replace(self, pending_show_options=None, pending_escalate=None)
```

**orchestrator.py 跨轮逻辑**：

```python
# SHOW_OPTIONS 跨轮
if decision.decision_type == "SHOW_OPTIONS":
    pending = PendingShowOptions(
        candidates=tuple(decision.candidates or []),
        snapshot_id=envelope.snapshot_id,
    )
    context = context.with_pending_show_options(pending)

# ESCALATE 跨轮
if decision.decision_type == "ESCALATE_TO_PLANNER":
    pending = PendingEscalate(
        handoff=decision.handoff,
        snapshot_id=envelope.snapshot_id,
    )
    context = context.with_pending_escalate(pending)

# Turn N+1 检查 pending
if context.pending_show_options:
    # 用户选择了一个候选
    selected = _match_selected_capability(utterance, context.pending_show_options.candidates)
    if selected:
        context = context.clear_pending()
        # 走 SELECT 路径
    elif _contains_any_primary_keyword(utterance):
        # 新意图，丢弃 pending
        context = context.clear_pending()

if context.pending_escalate:
    if utterance in ("继续", "continue", "ok"):
        context = context.clear_pending()
        # 走 planner dry-run 路径
    elif _contains_any_primary_keyword(utterance):
        # 新意图，丢弃 pending
        context = context.clear_pending()
```

## 9. 测试策略

| 层级 | 文件 | 覆盖 |
|---|---|---|
| 单元 | `test_intent_envelope.py`（新） | IntentGoal / IntentEnvelope dataclass shape / frozen / to_dict |
| 单元 | `test_recall.py`（新） | lexical / alias / example / merge / dedupe |
| 单元 | `test_rerank.py`（新） | scoring / tie-break / rerank_evidence |
| 单元 | `test_discard.py`（新） | unknown_capability / technical_field / invalid_param / valid_empty |
| 单元 | `test_llm_intent.py`（改） | _payload_to_envelope / rule fallback envelope / snapshot_id binding |
| 单元 | `test_match_decision.py`（改） | 5 种 decision type 的回放字段 |
| 集成 | `test_capability_selector.py`（改） | recall + rerank + selector 全链路 / VISIBILITY_DENIED |
| 跨轮 | `test_conversation_context.py`（改） | SHOW_OPTIONS / ESCALATE 跨轮 / 互斥 |
| Eval | `evals/matcher_cases.yaml`（改） | 11 类场景 |
| 回归 | `scripts/verify-agent-callplan-evidence.sh` | 全量 |

**TDD 顺序**：数据结构 (1.x) → recall (2.x) → rerank (3.x) → discard (4.x) → envelope 产出 (5.x) → selector (6.x) → 跨轮 (7.x) → 调用方迁移 (8.x) → Eval (10.x) → 验证 (11.x)。

## 10. Risks / Trade-offs

- **[BREAKING `IntentParseResult` 移除]** → 所有调用方全量迁移；测试同步更新；无外部 API 消费者（内部数据结构），blast radius 可控。
- **[BREAKING `SelectionResult` 移除]** → `to_selection_result()` compat 桥移除；`MatchDecision` 已稳定 1 个 release cycle，可删除。
- **[registry schema 扩展]** → 新增可选字段，向后兼容；缺失时 alias/example recall 返回空。
- **[recall + rerank 在 3 个 capability 下收益小]** → 为规模扩展预留架构；当前 recall 候选几乎总是全集，rerank 评分差异小但不阻塞。
- **[跨轮 ESCALATE 续接 planner 边界]** → `pending_escalate` 是 advisory，不续接执行权威；planner 续接仍走 dry-run，不执行 Gateway。
- **[LLM prompt schema 升级风险]** → schema 变更可能触发 LLM 输出格式回归；需扩展 Eval 覆盖 discard 场景。
- **[rule fallback envelope 字段稀疏]** → `model_evidence` 为空、`discard_reasons` 为空；可观测性降级但行为可解释。

## 11. Migration Plan

1. 新增 `intent_envelope.py`（IntentGoal / IntentEnvelope）。
2. 新增 `recall.py`（lexical / alias / example / merge / dedupe）。
3. 新增 `rerank.py`（scoring / tie-break / rerank_evidence）。
4. 新增 `discard.py`（detect_discard_reasons）。
5. 扩展 `registry/capabilities.yaml` + `registry_loader.py`（aliases / examples 字段）。
6. 升级 `llm_intent.py`：`_payload_to_envelope` + `_parse_result_to_envelope`（rule fallback）。
7. 升级 LLM prompt schema：输出 JSON 含 goals / candidates / constraints / ambiguities / evidence。
8. 升级 `capability_selector.py`：`select_capability` 消费 `IntentEnvelope` + recall + rerank。
9. 扩展 `match_decision.py`：`MatchDecision` 回放字段。
10. 扩展 `conversation_context.py`：PendingShowOptions / PendingEscalate + 互斥方法。
11. 升级 `orchestrator.py`：消费 envelope + 新 MatchDecision + 跨轮 pending。
12. 升级 `cli.py`：产出 IntentEnvelope。
13. 移除 `IntentParseResult` / `SelectionResult` / `to_selection_result()`。
14. 扩展 `evals/matcher_cases.yaml` 11 类场景。
15. 更新测试：`test_llm_intent.py` / `test_match_decision.py` / `test_capability_selector.py` / `test_intent.py` + 新增 4 个测试文件。

**回滚策略**：如 LLM prompt schema 升级触发回归，可临时切回 rule-only mode（`IntentAdapter` 仍返回 `IntentEnvelope`，`created_by="rule"`），不影响下游。

## 12. Open Questions

无（D1-D6 + DT1-DT5 全部决策）。

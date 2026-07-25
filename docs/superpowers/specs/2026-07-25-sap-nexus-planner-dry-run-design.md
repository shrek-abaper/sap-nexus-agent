---
comet_change: sap-nexus-planner-dry-run
role: technical-design
canonical_spec: openspec
---

# Design Doc: sap-nexus-planner-dry-run (S2-A + S2-B)

## Context

当前 Agent 意图选择链路：`parse_intent` (rule 顺序首命中) / `parse_with_llm` ("Select exactly one") -> `IntentParseResult` (单 intent) -> `select_capability` -> `SelectionResult`（隐式三态 SELECT/CLARIFY/REJECT）。`intent.py:59-81` 按固定顺序 `inventory -> purchase_order -> pr_create` 返回首个命中，多目标 utterance 被静默降级为单能力（缺陷 D-1）。架构契约要求多能力请求 `ESCALATE_TO_PLANNER`（record + explain），但 runtime 无法表达。

S1 `semantic-planning-foundation` 已归档，定义 `GoalSpec v1`、`PlanGraph v1`、Registry Snapshot、deterministic validator 契约（provenance/edges/governance/topological order）。本 change 在 S1 契约之上落地 S2-A（决策层）与 S2-B（dry-run 规划层），均不执行 Gateway/SAP。

约束：`registry/capabilities.yaml` 只读消费；不改 Gateway/SAP 执行契约；现有 inventory/PO/PR eval 必须回归通过。

## Goals / Non-Goals

**Goals**

- S2-A：显式五态 `MatchDecision` 替代 `SelectionResult`；多意图/歧义检测修复 D-1；visibility pre-filter；matcher Eval 退出标准。
- S2-B：`CapabilityCard` discovery + `GoalSpec`/`PlanDraft` candidate + deterministic `PlanCompiler` dry-run。
- dry-run 输出可审计（节点/边/参数来源/缺口/治理），不执行 Gateway/SAP。

**Non-Goals**

- `ESCALATE_TO_PLANNER` 后的实际 planner 执行（S2-B 只生成 dry-run 候选）；Gateway/SAP 执行；S3 read-only composition pilot；trusted/durable runtime；Phase 3+ embedding/retrieval/rerank；Dynamic Planner；Write composition；改 `registry/capabilities.yaml`。

## 架构设计

### 总体数据流

```
query
  -> parse_intent (rule: 扫描全部关键词) / parse_with_llm (detect all)
  -> IntentParseResult(matched_intents: list[MatchedIntent])
  -> select_capability
  -> MatchDecision(五态)
     SELECT            -> capability_selected (现有) -> CallPlan -> Gateway
     CLARIFY           -> clarification (现有)
     REJECT            -> failure (现有)
     SHOW_OPTIONS      -> match_decision 事件 (candidates)
     ESCALATE_TO_PLANNER -> match_decision 事件 (handoff)
  [S2-B] ESCALATE handoff
  -> planner: CapabilityCard discovery (Registry + producesFactTypes)
  -> visibility pre-filter (governance)
  -> GoalSpec / PlanDraft candidate (复用 S1 schema, advisory)
  -> PlanCompiler (deterministic) -> PlanGraph + gaps + governanceFlags
  -> dry-run 输出 (不执行 Gateway/SAP) -> Workbench 折叠展示
```

### S2-A 决策层

#### `MatchDecision` 对象（`agent/sap_nexus_agent/match_decision.py`，新）

```python
@dataclass(frozen=True)
class MatchedIntent:
    capability_id: str
    parameters: dict[str, str]
    missing: list[str]

@dataclass(frozen=True)
class MatchDecision:
    decision_type: Literal["SELECT","CLARIFY","REJECT","SHOW_OPTIONS","ESCALATE_TO_PLANNER"]
    capability_id: str | None = None        # SELECT
    parameters: dict[str, str] | None = None # SELECT
    missing_parameters: list[str] | None = None  # CLARIFY
    error_type: str | None = None           # REJECT
    candidates: list[MatchedIntent] | None = None  # SHOW_OPTIONS
    handoff: EscalationHandoff | None = None  # ESCALATE_TO_PLANNER
    rationale: str = ""

@dataclass(frozen=True)
class EscalationHandoff:
    reason: str
    matched_intents: list[MatchedIntent]
    utterance: str
    registry_snapshot_id: str
```

`SelectionResult` 退为 `MatchDecision` 在 SELECT/CLARIFY/REJECT 三态的窄视图（提供 `to_selection_result()` 兼容方法，一个发布周期后评估移除）。

#### 多意图检测（`intent.py` + `llm_intent.py`，改）

- rule 路径：`parse_intent` 改为扫描全部能力关键词集合，统计命中数。返回 `IntentParseResult(matched_intents=[...])`。命中 >1 -> selector 产出 `ESCALATE_TO_PLANNER`；命中 =1 -> 原参数提取；关键词歧义（弱匹配多能力，非明确多意图）-> `SHOW_OPTIONS`。
- LLM 路径：system prompt 从 "Select exactly one" 改为 "detect all matching capabilities；if >1, return escalation；if ambiguous, return options"。`_payload_to_parse_result` 解析多候选。
- 关键词歧义阈值（SHOW_OPTIONS 触发）：utterance 命中多个能力的关键词集合但无明确主意图（如"采购"模糊匹配 PO 查询与 PR 创建）。具体判定：命中 >=2 能力的关键词但任一能力的关键词命中数 < 该能力主关键词阈值（如"采购订单"是 PO 主关键词命中 +1，"采购"是 PR 弱关键词命中 +0.5）。阈值表在 `intent.py` 常量化，matcher Eval 覆盖。

#### selector（`capability_selector.py`，改）

`select_capability(parse_result) -> MatchDecision`：
- 技术覆盖（rfcName/OData）-> REJECT(UNSUPPORTED_RFC_NAME)
- matched_intents >1 -> ESCALATE_TO_PLANNER(handoff)
- 关键词歧义 -> SHOW_OPTIONS(candidates)
- 单意图缺参 -> CLARIFY(missing)
- 单意图齐参 -> SELECT(capability_id, parameters)
- 无匹配 -> REJECT(UNSUPPORTED_INTENT)

#### visibility pre-filter（`agent/sap_nexus_agent/visibility.py`，新）

```python
def filter_visible(cards: list[CapabilityCard], *, for_execution: bool) -> list[CapabilityCard]:
    # for_execution=False (dry-run/planner): 全部可见，写能力标记 governance
    # for_execution=True (执行层): 只 sideEffect=none，写能力过滤 (S3 gate)
```

写能力（sideEffect=sap_write）在 handoff/dry-run 可见（标记 requiresApproval），执行层不可见。

### S2-B 规划层（`agent/sap_nexus_agent/planner/`，新）

#### `CapabilityCard`（`capability_card.py`）

```python
@dataclass(frozen=True)
class CapabilityCard:
    capability_id: str
    name: str
    inputs: tuple[InputDescriptor, ...]
    governance: Governance          # sideEffect, requiresApproval, dataClassification
    visibility: Visibility          # VISIBLE_DRY_RUN / VISIBLE_EXECUTION / HIDDEN
    produces_fact_types: tuple[str, ...]  # from outputs.factTypeRef
```

从 `registry_loader.CapabilityDescriptor` + `capabilities.yaml` 的 `outputs.factTypeRef` 投影。

#### `GoalSpec` / `PlanDraft`（`goal_spec.py` / `plan_draft.py`）

复用 S1 `semantic-planning-foundation` 的 `GoalSpec v1` schema（goalType, desiredFactTypes, executionMode=PLAN_ONLY）。从 `EscalationHandoff.matched_intents` + `CapabilityCard.produces_fact_types` 构造 desiredFactTypes。`PlanDraft` 是 advisory 候选（capability 组合草案），不授予执行权威。

#### `PlanCompiler`（`plan_compiler.py`）

```python
def compile_dry_run(goal: GoalSpec, snapshot: RegistrySnapshot) -> DryRunResult:
    # deterministic: 不调 LLM, 不调 Gateway/SAP
    plan_graph = _build_plan_graph(goal, snapshot)  # 节点/边/参数来源
    PlanGraphValidator.validate(plan_graph)          # 复用 S1 validator
    gaps = _compute_gaps(goal, plan_graph)           # 缺参/缺能力
    flags = _compute_governance_flags(plan_graph)    # 需审批/写副作用
    return DryRunResult(plan_graph, gaps, flags, rationale)
```

`PlanGraphValidator` 直接 import S1 `semantic-planning-foundation` 的 validator（provenance/edges/governance/topological order），不重新实现。

#### dry-run 输出

```python
@dataclass(frozen=True)
class DryRunResult:
    plan_graph: PlanGraph          # 节点/边/参数来源(goalConstraint/literal/factField)
    gaps: list[Gap]                # 缺参/缺能力
    governance_flags: list[Flag]   # 需审批/写副作用
    rationale: str                 # 决策理由
```

### SSE 事件（`run-event-schema.ts`，改）

新增 `match_decision_created` 事件类型 + `match-decision` artifact kind，仅承载 SHOW_OPTIONS / ESCALATE_TO_PLANNER：

```typescript
type AgentRunEventType = ... | "match_decision_created";
// artifact kind: "match-decision"
// payload: { decision_type: "SHOW_OPTIONS"|"ESCALATE_TO_PLANNER", candidates?, handoff?, rationale }
```

SELECT/CLARIFY/REJECT 复用现有 `capability_selected`/`narrative_created`(clarification)/`run_failed`(reject) 路径，不新增事件。

`agent-runtime-adapter.ts` 的 `buildEventsFromOutcome` 适配：outcome 含 `matchDecision` 字段时，SHOW_OPTIONS/ESCALATE 发 `match_decision_created` 事件。

### Workbench 前端（`view-model.ts` / `AgentConsole.tsx` / `globals.css`，改）

- `view-model.ts`：`buildMatchDecisionView(snapshot)` 纯函数，从 `match-decision` artifact 渲染五态视图（candidates/handoff/rationale）。
- `ChatStream.tsx`：SHOW_OPTIONS/ESCALATE turn 内折叠展示 candidates / handoff；dry-run 预览（S2-B）折叠展示 PlanGraph 节点/边/缺口/治理。
- 纯只读，不改 Gateway/SAP 调用。

## 错误处理与边界条件

- **多意图误判**（单意图含多关键词，如"采购订单"含"订单"）：关键词集合精化（"采购订单"是 PO 主关键词，"订单"单独是 PO 弱关键词）；matcher Eval 覆盖单意图不误判为 ESCALATE。
- **SHOW_OPTIONS 阈值模糊**：阈值表常量化，Eval 覆盖歧义/非歧义边界。
- **写能力误执行**：visibility pre-filter `for_execution=True` 过滤写能力；PlanCompiler 不调用 Gateway；dry-run 输出标注"不执行"。
- **PlanCompiler 缺口**：goal desiredFactType 无 producer capability -> gap 记录，dry-run 输出 incomplete，不报错。
- **S1 validator 失败**：PlanGraph 校验失败 -> dry-run 输出 `governance_flags=[INVALID_PLAN_GRAPH]` + rationale，不执行。
- **LLM 不可用**：hybrid fallback rule 路径（现有行为），rule 路径已支持多意图检测。
- **SelectionResult 兼容**：`to_selection_result()` 在 SELECT/CLARIFY/REJECT 返回窄视图，其他态返回 None（orchestrator 检查 decision_type）。

## 测试策略

### S2-A matcher Eval（`evals/matcher_cases.*`，新）

五类决策：
1. SELECT：单意图齐参（"DEMOA2 在工厂 5100 还有多少可用库存"）
2. CLARIFY：单意图缺参（"DEMOA2 的库存"缺 plant）
3. REJECT：技术覆盖（"rfcName=BAPI_*" / OData URL）
4. SHOW_OPTIONS：关键词歧义（构造歧义 utterance）
5. ESCALATE_TO_PLANNER：多目标（"DEMOA2 在 5100 的库存，再列出近 30 天未清采购订单"）

`false SELECT` 回归失败项：多目标 utterance 被静默降级为单 SELECT -> 测试断言 decision_type == ESCALATE_TO_PLANNER。

### 现有回归

- `scripts/verify-agent-callplan-evidence.sh`：inventory/PO/PR eval 不破坏。
- `agent/tests/test_*.py`：intent/selector/orchestrator 单测适配 MatchDecision。

### S2-B dry-run cases（`evals/dry_run_cases.*`，新）

- PlanCompiler 输出 PlanGraph + gaps + governanceFlags。
- 断言不调用 Gateway validate/execute（mock 断言）。
- PlanGraph 通过 S1 validator（import S1 validator 测试）。

### 前端

- `tests/agent-console/`：`summarizeTurn` / `buildChatBubbleState` 回归 + `buildMatchDecisionView` 纯函数测试。
- typecheck + build 通过。

### 门禁

`npm --prefix frontend run verify` + `openspec validate --all --strict` + `scripts/verify-agent-callplan-evidence.sh` 全过。

## Spec Patch（回写 delta spec）

1. `specs/semantic-match-decision/spec.md`：SHOW_OPTIONS 触发条件细化为"utterance 弱匹配多能力关键词集合且无明确主意图（关键词歧义），阈值由 matcher Eval 锚定"。
2. `specs/planner-dry-run/spec.md`：`CapabilityCard` 字段明确含 `producesFactTypes`（from `outputs.factTypeRef`），供 PlanCompiler 从 GoalSpec desiredFactType 匹配候选能力。
3. `specs/agent-callplan-evidence/spec.md`：无需额外 patch（open 阶段 MODIFIED 已覆盖）。

## 风险与缓解

| 风险 | 缓解 |
|---|---|
| MatchDecision 替代 SelectionResult 破坏调用方 | `to_selection_result()` 窄视图渐进迁移；一个发布周期后评估移除 |
| rule 多意图扫描误判 | 关键词主/弱分级 + 阈值表常量化；matcher Eval 覆盖单意图/多目标/歧义 |
| SSE 混合事件前端处理两种路径 | view-model 统一 MatchDecision 视图，前端只读渲染 |
| S2-B 复用 S1 validator 契约漂移 | S1 已归档契约锁定；PlanCompiler 测试 import S1 validator |
| 写能力 dry-run 可见误执行 | visibility pre-filter for_execution 过滤；PlanCompiler 不调 Gateway；前端标注"不执行" |
| S2-A/S2-B 同 change 范围偏大 | tasks.md 分阶段；S2-A 先过 matcher Eval 再 S2-B |

## 交付顺序

S2-A（任务组 1-6）先完成并过 matcher Eval + 现有回归 -> S2-B（任务组 7-9）-> 验证归档（任务组 10）。S2-B dry-run 不依赖 Gateway/SAP 可用。

## 开放项

无遗留开放项（5 个 Open Questions 已在 brainstorming 全部澄清并落入本设计）。

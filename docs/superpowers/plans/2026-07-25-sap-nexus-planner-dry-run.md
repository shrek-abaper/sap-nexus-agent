---
change: sap-nexus-planner-dry-run
design-doc: docs/superpowers/specs/2026-07-25-sap-nexus-planner-dry-run-design.md
base-ref: ed62c96fd9dc6175c1f77eab4b6aebdefba01179
archived-with: 2026-07-25-sap-nexus-planner-dry-run
---

# SAP Nexus Planner Dry-Run 实施计划（S2-A + S2-B）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 S1 `semantic-planning-foundation` 契约之上落地 S2-A 决策层（显式五态 `MatchDecision` 替代隐式三态 `SelectionResult`，修复 D-1 多意图静默降级缺陷）与 S2-B dry-run 规划层（`CapabilityCard` discovery + `GoalSpec`/`PlanDraft` 候选 + 确定性 `PlanCompiler`），全程不执行 Gateway/SAP。

**Architecture:** 引用 `docs/superpowers/specs/2026-07-25-sap-nexus-planner-dry-run-design.md`。数据流：`parse_intent`/`parse_with_llm` 扫描全部意图 -> `IntentParseResult(matched_intents)` -> `select_capability` 产出 `MatchDecision` 五态 -> SELECT 走现有 CallPlan/Gateway；SHOW_OPTIONS/ESCALATE 发 `match_decision_created` SSE 事件；ESCALATE handoff 进入 `planner/` 模块，`PlanCompiler` 复用 S1 `semantic_planning.validation` 校验产出 `DryRunResult`。`registry/capabilities.yaml` 只读消费。

**Tech Stack:** Python 3.12、PyYAML（现有）、pytest（现有）、TypeScript/Next.js（现有 frontend）、S1 `semantic_planning` 包（已归档契约）。

## Global Constraints

- 只在当前分支工作；不创建、切换或重命名 Git 分支。
- 未经用户明确要求，不执行 `git commit`；每个 Task 验收后由 `subagent-driven-development` 协调者按 review_mode 验收并打勾，commit 时机由用户决定。
- `registry/capabilities.yaml` 只读消费，不改 version、不改 capability 闭集；不改 Gateway/SAP 执行契约。
- S2-A/S2-B 全程不调用 Gateway validate/execute、不调用 SAP；`PlanCompiler` 是 deterministic（不调 LLM、不调 Gateway/SAP）。
- 现有 `scripts/verify-agent-callplan-evidence.sh`（inventory/PO/PR eval + S1 contract + pytest + openspec validate）必须回归通过。
- `SelectionResult` 不能一次性删除；通过 `to_selection_result()` 窄视图渐进迁移，一个发布周期后评估移除。
- `MatchDecision`、`CapabilityCard`、`GoalSpec`、`PlanDraft`、`DryRunResult` 均为 `@dataclass(frozen=True)`；`PlanGraph` 禁止出现 `bindingId`/`rfcName`/URL/credential/header/executor mapping（沿用 S1 契约）。
- 写能力（`sideEffect=sap_write`）在 dry-run/handoff 可见（标 `requiresApproval`），执行层不可见（visibility pre-filter `for_execution=True` 过滤，作为 S3 gate）。
- 不新增外部依赖；前端不新增运行时依赖。
- 不提交 `.env`、凭据、token、连接串、真实运行 trace 或 SAP 数据。

archived-with: 2026-07-25-sap-nexus-planner-dry-run
---

## File Structure

### Create

| Path | Responsibility |
|---|---|
| `agent/sap_nexus_agent/match_decision.py` | `MatchedIntent` / `MatchDecision` / `EscalationHandoff` dataclass，五态枚举 |
| `agent/sap_nexus_agent/visibility.py` | `filter_visible(cards, *, for_execution)` pre-filter |
| `agent/sap_nexus_agent/planner/__init__.py` | planner 包公开接口 |
| `agent/sap_nexus_agent/planner/capability_card.py` | `CapabilityCard` / `InputDescriptor` / `Governance` / `Visibility` 投影 |
| `agent/sap_nexus_agent/planner/goal_spec.py` | `GoalSpec` v1 复用 S1 schema，从 `EscalationHandoff` 构造 |
| `agent/sap_nexus_agent/planner/plan_draft.py` | advisory `PlanDraft` 候选 |
| `agent/sap_nexus_agent/planner/plan_compiler.py` | `PlanCompiler.compile_dry_run` + `DryRunResult` / `Gap` / `Flag` |
| `agent/tests/test_match_decision.py` | 五态构造与 `to_selection_result()` 窄视图兼容 |
| `agent/tests/test_visibility.py` | 读写能力可见性边界 |
| `agent/tests/test_planner_capability_card.py` | `CapabilityCard` 投影 + `producesFactTypes` |
| `agent/tests/test_planner_plan_compiler.py` | dry-run 输出 + 不调 Gateway 断言 + 复用 S1 validator |
| `evals/matcher_cases.yaml`（或 `.json`） | 五类决策 + `false SELECT` 回归 |
| `evals/dry_run_cases.yaml`（或 `.json`） | PlanCompiler dry-run 场景 |

### Modify

| Path | Responsibility |
|---|---|
| `agent/sap_nexus_agent/intent.py` | `parse_intent` 扫描全部关键词集合；`IntentParseResult.matched_intents`；关键词主/弱分级 + 阈值表常量化 |
| `agent/sap_nexus_agent/llm_intent.py` | system prompt 从 "Select exactly one" 改 "detect all"；`_payload_to_parse_result` 解析多候选 |
| `agent/sap_nexus_agent/capability_selector.py` | `select_capability` 输出 `MatchDecision`（五态决策树） |
| `agent/sap_nexus_agent/orchestrator.py` | `run_query` 适配 `MatchDecision`；SHOW_OPTIONS/ESCALATE 不走 Gateway |
| `agent/sap_nexus_agent/workbench_output.py` | `MatchDecision` 序列化（含 handoff/candidates） |
| `agent/tests/test_intent.py` | 多目标 utterance 升级、单意图不误判 |
| `agent/tests/test_capability_selector.py`（若不存在则新建） | 五态决策单元测试 |
| `agent/tests/test_orchestrator.py`（若不存在则新建） | `MatchDecision` 路由适配 |
| `agent/tests/test_workbench_output.py` | `MatchDecision` 序列化回归 |
| `agent/sap_nexus_agent/eval.py`（或新增 matcher 评估入口） | 五类决策 + false SELECT 回归判定 |
| `frontend/src/runtime/run-event-schema.ts` | 新增 `match_decision_created` 事件类型 + `match-decision` artifact kind |
| `frontend/src/runtime/agent-runtime-adapter.ts` | `buildEventsFromOutcome` 适配 `matchDecision` 字段 |
| `frontend/src/modules/agent-console/view-model.ts` | `buildMatchDecisionView(snapshot)` 纯函数 + `MatchDecisionView` 类型 |
| `frontend/src/modules/agent-console/AgentConsole.tsx` | 只读展示五态决策（candidates/handoff） |
| `frontend/src/modules/agent-console/ChatStream.tsx` | SHOW_OPTIONS/ESCALATE turn 内折叠展示 + dry-run 预览折叠 |
| `frontend/src/modules/agent-console/globals.css`（若需要） | 折叠/标记样式 |
| `frontend/tests/agent-console/`（现有测试目录） | `summarizeTurn` / `buildChatBubbleState` 回归 + `buildMatchDecisionView` 纯函数测试 |
| `scripts/verify-agent-callplan-evidence.sh` | 接入 matcher Eval + dry-run cases |
| `docs/runbooks/10-capability-composition-contract.md` | S2-A 完成、S2-B 完成、下一推荐（S3 gate） |
| `docs/runbooks/README.md` | index 同步 |
| `openspec/changes/sap-nexus-planner-dry-run/tasks.md` | 每个 Task 验收后勾选 |
| `openspec/changes/sap-nexus-planner-dry-run/specs/semantic-match-decision/spec.md` | SHOW_OPTIONS 阈值条件细化（Spec Patch） |
| `openspec/changes/sap-nexus-planner-dry-run/specs/planner-dry-run/spec.md` | `CapabilityCard.producesFactTypes` 明确（Spec Patch） |

archived-with: 2026-07-25-sap-nexus-planner-dry-run
---

## Verification Commands

```bash
# Python 单测 + S1 契约 + 现有 eval
.venv/bin/python -m pytest agent/tests
.venv/bin/python scripts/validate-semantic-planning-contract.py

# matcher Eval（S2-A 退出标准）
.venv/bin/python -m sap_nexus_agent.eval evals/matcher_cases.yaml

# dry-run cases（S2-B）
.venv/bin/python -m sap_nexus_agent.eval evals/dry_run_cases.yaml

# 现有回归
.venv/bin/python -m sap_nexus_agent.eval evals/inventory_availability_cases.yaml
.venv/bin/python -m sap_nexus_agent.eval evals/eval_harness_seed_cases.json
.venv/bin/python -m sap_nexus_agent.eval evals/pr_create_cases.json

# 前端
npm --prefix frontend run verify   # typecheck + test + build

# OpenSpec
openspec validate --all --strict

# 组合证据脚本（最终门禁）
scripts/verify-agent-callplan-evidence.sh
```

archived-with: 2026-07-25-sap-nexus-planner-dry-run
---

## 阶段编排

**S2-A（任务组 1-6）** 先完成并过 matcher Eval + 现有回归，再进入 **S2-B（任务组 7-9）**，最后 **验证归档（任务组 10）**。S2-B dry-run 不依赖 Gateway/SAP 可用。

archived-with: 2026-07-25-sap-nexus-planner-dry-run
---

# 阶段 S2-A：决策层

## Task 1: S2-A MatchDecision 决策对象

**对应 tasks.md:** 1.1 / 1.2 / 1.3

**Files:**
- Create: `agent/sap_nexus_agent/match_decision.py`
- Create: `agent/tests/test_match_decision.py`

**Interfaces:**
- Produces: `MatchedIntent`、`MatchDecision`、`EscalationHandoff`（全部 `@dataclass(frozen=True)`），`DecisionType` 五态字面量类型。
- Consumes: 无外部依赖（纯 dataclass）。

**Design Doc 引用:** §"MatchDecision 对象"（`agent/sap_nexus_agent/match_decision.py`，新）。

- [x] **Step 1.1: 定义 `MatchDecision` dataclass 与五态枚举**

在 `agent/sap_nexus_agent/match_decision.py` 实现：

```python
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal

DecisionType = Literal["SELECT", "CLARIFY", "REJECT", "SHOW_OPTIONS", "ESCALATE_TO_PLANNER"]

@dataclass(frozen=True)
class MatchedIntent:
    capability_id: str
    parameters: dict[str, str]
    missing: list[str]

@dataclass(frozen=True)
class EscalationHandoff:
    reason: str
    matched_intents: list[MatchedIntent]
    utterance: str
    registry_snapshot_id: str

@dataclass(frozen=True)
class MatchDecision:
    decision_type: DecisionType
    capability_id: str | None = None        # SELECT
    parameters: dict[str, str] | None = None # SELECT
    missing_parameters: list[str] | None = None  # CLARIFY
    error_type: str | None = None           # REJECT
    candidates: list[MatchedIntent] | None = None  # SHOW_OPTIONS
    handoff: EscalationHandoff | None = None  # ESCALATE_TO_PLANNER
    rationale: str = ""
```

`decision_type` 为五态枚举（`Literal` 类型，非 `Enum`，便于序列化为字符串）。`SELECT` 必须携带 `capability_id` + `parameters`；`CLARIFY` 携带 `missing_parameters`；`REJECT` 携带 `error_type`；`SHOW_OPTIONS` 携带 `candidates`；`ESCALATE_TO_PLANNER` 携带 `handoff`。

- [x] **Step 1.2: `SelectionResult` 退为窄视图兼容 wrapper**

在 `capability_selector.py` 给 `SelectionResult` 增加 `to_selection_result()` 兼容方法（或在 `MatchDecision` 上提供 `to_selection_result() -> SelectionResult | None`）。Design Doc 明确：在 SELECT/CLARIFY/REJECT 三态返回窄视图，SHOW_OPTIONS/ESCALATE 返回 `None`（orchestrator 检查 `decision_type`）。

```python
# 在 MatchDecision 上
def to_selection_result(self) -> "SelectionResult | None":
    if self.decision_type == "SELECT":
        return SelectionResult(capability_id=self.capability_id)
    if self.decision_type == "CLARIFY":
        return SelectionResult(capability_id=None, error_type="MISSING_PARAMETER", message=...)
    if self.decision_type == "REJECT":
        return SelectionResult(capability_id=None, error_type=self.error_type, message=self.rationale)
    return None  # SHOW_OPTIONS / ESCALATE_TO_PLANNER
```

- [x] **Step 1.3: 单元测试 - 五态构造与窄视图兼容**

`agent/tests/test_match_decision.py` 覆盖：
- 每态构造 + 字段断言（SELECT 带 capability_id+parameters；ESCALATE 带 handoff 含 4 个 EscalationHandoff 字段）。
- `to_selection_result()` 在 SELECT/CLARIFY/REJECT 返回非 None 且字段映射正确；在 SHOW_OPTIONS/ESCALATE 返回 None。
- frozen dataclass 不可变性（`dataclasses.FrozenInstanceError` on setattr）。

**验证:** `pytest agent/tests/test_match_decision.py` 全过。

archived-with: 2026-07-25-sap-nexus-planner-dry-run
---

## Task 2: S2-A 多意图检测（修复 D-1）

**对应 tasks.md:** 2.1 / 2.2 / 2.3 / 2.4 / 2.5

**Files:**
- Modify: `agent/sap_nexus_agent/intent.py`
- Modify: `agent/sap_nexus_agent/llm_intent.py`
- Modify: `agent/tests/test_intent.py`

**Interfaces:**
- Consumes: `INVENTORY_KEYWORDS` / `PURCHASE_ORDER_KEYWORDS` / `PR_CREATE_KEYWORDS`（现有）。
- Produces: `IntentParseResult.matched_intents: list[MatchedIntent]`（新增字段，默认空列表以保持向后兼容）；rule 路径多意图扫描；LLM 路径多候选解析。

**Design Doc 引用:** §"多意图检测（`intent.py` + `llm_intent.py`，改）"，§"错误处理与边界条件"（多意图误判、SHOW_OPTIONS 阈值模糊）。

- [x] **Step 2.1: 改 `parse_intent` rule 路径 - 扫描全部关键词集合**

当前 `intent.py:53-89` 是 `inventory -> purchase_order -> pr_create` 顺序首命中。改为：对三个能力关键词集合分别扫描，统计命中数，构造 `matched_intents: list[MatchedIntent]`。

- 保留 `contains_rfc_name` / `contains_odata_override` 前置检测。
- `IntentParseResult` 新增 `matched_intents: list[MatchedIntent] = field(default_factory=list)`（向后兼容默认空）。
- 单命中：仍走原参数提取（`_build_inventory_result` 等），但把结果同步填入 `matched_intents`（长度 1）。
- 多命中：`matched_intents` 长度 >1，`intent` / `capability_id` 置 None（让 selector 决策 ESCALATE），参数提取可不填（selector 不消费）。

- [x] **Step 2.2: 关键词主/弱分级 + 阈值表常量化（SHOW_OPTIONS 触发）**

在 `intent.py` 顶部新增常量阈值表（Design Doc §"多意图检测"）：

```python
# 主关键词（强匹配，命中 +1）；弱关键词（弱匹配，命中 +0.5）
INVENTORY_PRIMARY = ("库存", "可用量", "可用库存")
INVENTORY_WEAK = ("还有多少", "有没有")
PO_PRIMARY = ("采购订单",)
PO_WEAK = ("订单", "PO")
# PR_CREATE 沿用 pr_intent.PR_CREATE_KEYWORDS，分级在 pr_intent.py 内补充

# 单能力主关键词命中阈值：低于此值且多能力命中 -> SHOW_OPTIONS 而非 ESCALATE
PRIMARY_KEYWORD_THRESHOLD = 1.0
```

判定逻辑（在 selector 或 intent 层均可，建议在 intent 层产出 `matched_intents` + `is_ambiguous: bool`，selector 消费）：
- 命中 >=2 能力且每个能力主关键词命中数 >= `PRIMARY_KEYWORD_THRESHOLD` -> 多意图（ESCALATE）。
- 命中 >=2 能力但任一能力只有弱关键词命中 -> 关键词歧义（SHOW_OPTIONS）。
- 单意图含多关键词（如"采购订单"含"订单"）不误判：主关键词优先，弱关键词不单独触发多能力。

- [x] **Step 2.3: 改 LLM 路径 system prompt - "detect all"**

`llm_intent.py:86` 当前 prompt `"Select exactly one capabilityId from the registered closed set below"`。改为：

```
Detect all matching capabilities from the registered closed set below.
- If exactly one capability matches with required parameters, return it.
- If more than one capability matches, return an escalation with all matched candidates.
- If ambiguous (weak match across multiple capabilities without a clear primary), return options.
- Never introduce capabilityIds outside the closed set.
```

- [x] **Step 2.4: 改 `_payload_to_parse_result` 解析多候选**

`llm_intent.py:108` 当前解析单个 `capabilityId`。改为解析 LLM 返回的 `candidates: list` 或 `escalation: {...}` 结构：
- 单候选 + 齐参 -> `matched_intents=[单条]`。
- 多候选 -> `matched_intents=[多条]`，`intent=None`。
- LLM 返回 `escalation` 字段 -> 同上多候选。
- LLM 返回未知 `capabilityId` -> `matched_intents=[]`，selector 产 REJECT。

保持 `_extract_parameters` / `_clarification_for` 现有单候选参数提取逻辑复用于每个候选。

- [x] **Step 2.5: 单元测试 - 多目标升级、单意图不误判**

`agent/tests/test_intent.py` 新增：
- 多目标 utterance（Design Doc 测试策略 §ESCALATE 案例："DEMOA2 在 5100 的库存，再列出近 30 天未清采购订单"）-> `matched_intents` 长度 2（inventory + purchase_order）。
- 单意图不误判："DEMOA2 在工厂 5100 还有多少可用库存" -> `matched_intents` 长度 1（inventory）。
- "采购订单 4500000001" -> 长度 1（purchase_order），不因"订单"弱关键词误判。
- 关键词歧义 utterance（构造："采购"模糊匹配 PO 查询与 PR 创建）-> `is_ambiguous=True`。
- LLM 路径多候选解析（mock `JsonLlmClient` 返回 `candidates: [...]`）。

**验证:** `pytest agent/tests/test_intent.py` 全过；现有 intent 测试不破坏。

archived-with: 2026-07-25-sap-nexus-planner-dry-run
---

## Task 3: S2-A selector 输出 MatchDecision

**对应 tasks.md:** 3.1 / 3.2 / 3.3

**Files:**
- Modify: `agent/sap_nexus_agent/capability_selector.py`
- Modify: `agent/sap_nexus_agent/orchestrator.py`
- Modify: `agent/sap_nexus_agent/workbench_output.py`
- Modify/Create: `agent/tests/test_capability_selector.py` / `agent/tests/test_orchestrator.py`

**Interfaces:**
- Consumes: `IntentParseResult.matched_intents` + `is_ambiguous`（Task 2 产出）。
- Produces: `select_capability(parse_result) -> MatchDecision`（签名变更，原返回 `SelectionResult`）；`orchestrator.run_query` 路由五态；`workbench_output` 序列化 `MatchDecision`。

**Design Doc 引用:** §"selector（`capability_selector.py`，改）"，§"SSE 事件"（SELECT/CLARIFY/REJECT 复用现有路径）。

- [x] **Step 3.1: `select_capability` 输出 `MatchDecision`（五态决策树）**

`capability_selector.py:28` 当前签名 `-> SelectionResult`。改为 `-> MatchDecision`，决策树（Design Doc §selector，顺序敏感）：

```python
def select_capability(parse_result: IntentParseResult) -> MatchDecision:
    # 1. 技术覆盖 (rfcName/OData) -> REJECT(UNSUPPORTED_RFC_NAME)
    if parse_result.contains_rfc_name or parse_result.contains_odata_override:
        return MatchDecision(decision_type="REJECT", error_type="UNSUPPORTED_RFC_NAME",
                             rationale="Agent 不接受 rfcName 或 OData 技术覆盖...")
    # 2. matched_intents >1 -> ESCALATE_TO_PLANNER(handoff)
    if len(parse_result.matched_intents) > 1:
        return MatchDecision(decision_type="ESCALATE_TO_PLANNER",
                             handoff=EscalationHandoff(reason="multi-intent", ...))
    # 3. 关键词歧义 -> SHOW_OPTIONS(candidates)
    if parse_result.is_ambiguous and parse_result.matched_intents:
        return MatchDecision(decision_type="SHOW_OPTIONS", candidates=...)
    # 4. 单意图缺参 -> CLARIFY(missing)
    if parse_result.missing_parameters:
        return MatchDecision(decision_type="CLARIFY", missing_parameters=..., rationale=...)
    # 5. 单意图齐参 -> SELECT(capability_id, parameters)
    capability_id = parse_result.capability_id or INTENT_TO_CAPABILITY.get(parse_result.intent)
    if capability_id:
        return MatchDecision(decision_type="SELECT", capability_id=capability_id,
                             parameters=parse_result.parameters)
    # 6. 无匹配 -> REJECT(UNSUPPORTED_INTENT)
    return MatchDecision(decision_type="REJECT", error_type="UNSUPPORTED_INTENT", rationale=...)
```

`INTENT_TO_CAPABILITY` 闭集映射保持不变。

- [x] **Step 3.2: `orchestrator.run_query` 适配 `MatchDecision`**

`orchestrator.py:60-149` 当前用 `selected.error_type` / `selected.capability_id` 路由。改为消费 `MatchDecision.decision_type`：

- `SELECT` -> 现有 CallPlan -> Gateway validate/execute 路径不变。
- `CLARIFY` -> 返回 `AgentOutcome(status="clarification", missing_parameters=...)`。
- `REJECT` -> 返回 `AgentOutcome(status="failure", error_type=...)`。
- `SHOW_OPTIONS` / `ESCALATE_TO_PLANNER` -> 返回 `AgentOutcome(status="match_decision", match_decision=decision, ...)`，**不调 Gateway**。

`AgentOutcome` 新增字段 `match_decision: MatchDecision | None = None`。`to_selection_result()` 窄视图可选用于过渡期 SELECT/CLARIFY/REJECT 内部复用现有 `_finalize_*` 分支（评估是否直接走 `decision_type` 分支更清晰）。

- [x] **Step 3.3: `agent-runtime-adapter.ts` / `workbench_output.py` 适配序列化**

- `workbench_output.py`：`MatchDecision` 序列化为 dict（`decision_type` / `candidates` / `handoff` / `rationale`），供 SSE payload。
- `agent-runtime-adapter.ts` 的 `buildEventsFromOutcome`：outcome 含 `matchDecision` 字段且 `decision_type in {SHOW_OPTIONS, ESCALATE_TO_PLANNER}` 时，发 `match_decision_created` 事件（Task 6.1 定义事件类型）。SELECT/CLARIFY/REJECT 复用现有 `capability_selected` / `narrative_created`(clarification) / `run_failed` 路径。

**验证:** `pytest agent/tests/test_capability_selector.py agent/tests/test_orchestrator.py agent/tests/test_workbench_output.py` 全过；现有 orchestrator/workbench 测试不破坏（SELECT/CLARIFY/REJECT 路径行为不变）。

archived-with: 2026-07-25-sap-nexus-planner-dry-run
---

## Task 4: S2-A visibility pre-filter

**对应 tasks.md:** 4.1 / 4.2 / 4.3

**Files:**
- Create: `agent/sap_nexus_agent/visibility.py`
- Create: `agent/tests/test_visibility.py`
- 依赖: `agent/sap_nexus_agent/planner/capability_card.py`（Task 7.1 先建骨架，或本 Task 先建 `CapabilityCard` 在 `visibility.py` 同模块，Task 7 再迁移到 `planner/`）

**Interfaces:**
- Consumes: `list[CapabilityCard]`（含 `governance.sideEffect` / `dataClassification`）。
- Produces: `filter_visible(cards, *, for_execution: bool) -> list[CapabilityCard]`。

**Design Doc 引用:** §"visibility pre-filter（`agent/sap_nexus_agent/visibility.py`，新）"，§"错误处理与边界条件"（写能力误执行）。

- [x] **Step 4.1: `CapabilityCard` 投影（最小集，供 visibility 消费）**

为避免循环依赖，本 Task 先在 `planner/capability_card.py`（或 `visibility.py` 内）定义最小 `CapabilityCard`：

```python
@dataclass(frozen=True)
class Governance:
    side_effect: str          # "none" | "sap_write"
    requires_approval: bool
    data_classification: str  # "internal" | "restricted"

@dataclass(frozen=True)
class CapabilityCard:
    capability_id: str
    name: str
    governance: Governance
    visibility: str = "VISIBLE_DRY_RUN"  # VISIBLE_DRY_RUN / VISIBLE_EXECUTION / HIDDEN
    produces_fact_types: tuple[str, ...] = ()
```

Task 7.1 会扩展 `inputs` / `InputDescriptor` 等字段，本 Task 只需 visibility 消费的 `governance` 字段。

- [x] **Step 4.2: `filter_visible` 实现**

```python
def filter_visible(cards: list[CapabilityCard], *, for_execution: bool) -> list[CapabilityCard]:
    if not for_execution:
        # dry-run/planner: 全部可见，写能力标记 governance（已含 requiresApproval）
        return [c for c in cards if c.visibility != "HIDDEN"]
    # 执行层: 只 sideEffect=none，写能力过滤 (S3 gate)
    return [c for c in cards
            if c.visibility != "HIDDEN"
            and c.governance.side_effect == "none"
            and c.governance.data_classification == "internal"]
```

Design Doc 明确：写能力（`sideEffect=sap_write`）在 dry-run/handoff 可见（标 `requiresApproval`），执行层不可见。

- [x] **Step 4.3: 单元测试 - 读写能力可见性边界**

`agent/tests/test_visibility.py` 覆盖：
- 读能力（`sideEffect=none` + `internal`）：`for_execution=True` 可见，`for_execution=False` 可见。
- 写能力（`sideEffect=sap_write`）：`for_execution=True` 不可见（过滤），`for_execution=False` 可见。
- `visibility=HIDDEN`：两种模式都不可见。
- `restricted` 数据分级：`for_execution=True` 不可见，`for_execution=False` 可见。

**验证:** `pytest agent/tests/test_visibility.py` 全过。

archived-with: 2026-07-25-sap-nexus-planner-dry-run
---

## Task 5: S2-A matcher Eval

**对应 tasks.md:** 5.1 / 5.2 / 5.3 / 5.4

**Files:**
- Create: `evals/matcher_cases.yaml`（或 `.json`，与现有 `evals/inventory_availability_cases.yaml` 同格式）
- Modify: `agent/sap_nexus_agent/eval.py`（或新增 matcher 评估入口，复用现有 eval harness）
- Modify: `scripts/verify-agent-callplan-evidence.sh`（接入 matcher Eval）

**Interfaces:**
- Consumes: `parse_intent` + `select_capability`（产出 `MatchDecision`）。
- Produces: 五类决策 case 通过/失败报告；`false SELECT` 回归失败项。

**Design Doc 引用:** §"测试策略" -> "S2-A matcher Eval"，§"风险与缓解"（rule 多意图扫描误判）。

- [x] **Step 5.1: 五类决策 cases**

`evals/matcher_cases.yaml` 覆盖五类（Design Doc §测试策略）：

```yaml
cases:
  - id: select-inventory-complete
    userQuery: "DEMOA2 在工厂 5100 还有多少可用库存"
    expected:
      decisionType: SELECT
      capabilityId: MM.Inventory.GetAvailability
      validateCalls: 1   # SELECT 走 Gateway（eval harness mock）
      executeCalls: 1
  - id: clarify-missing-plant
    userQuery: "DEMOA2 的库存"
    expected:
      decisionType: CLARIFY
      missingParameters: ["plant"]
      validateCalls: 0
      executeCalls: 0
  - id: reject-rfc-name
    userQuery: "rfcName=BAPI_MATERIAL_GET_AVAILABILITY 查库存"
    expected:
      decisionType: REJECT
      errorType: UNSUPPORTED_RFC_NAME
      validateCalls: 0
      executeCalls: 0
  - id: show-options-ambiguity
    userQuery: "<构造的歧义 utterance>"
    expected:
      decisionType: SHOW_OPTIONS
      validateCalls: 0
      executeCalls: 0
  - id: escalate-multi-goal
    userQuery: "DEMOA2 在 5100 的库存，再列出近 30 天未清采购订单"
    expected:
      decisionType: ESCALATE_TO_PLANNER
      validateCalls: 0
      executeCalls: 0
```

- [x] **Step 5.2: `false SELECT` 回归失败项**

新增一个 case，断言多目标 utterance **不**被静默降级为单 SELECT：

```yaml
  - id: false-select-regression
    userQuery: "DEMOA2 在 5100 的库存，再列出近 30 天未清采购订单"
    expected:
      decisionType: ESCALATE_TO_PLANNER   # 若降级为 SELECT 则此 case 失败
      validateCalls: 0
      executeCalls: 0
```

`eval.py` 评估器：实际 `decisionType=SELECT` 而期望 `ESCALATE_TO_PLANNER` -> 报告 regression failure（明确标注 "false SELECT"）。

- [x] **Step 5.3: 现有 inventory/PO/PR eval 回归不破坏**

运行 `evals/inventory_availability_cases.yaml` / `eval_harness_seed_cases.json` / `pr_create_cases.json`，确认 SELECT/CLARIFY/REJECT 路径行为不变。若现有 eval 期望 `status: "success"` 而 `AgentOutcome.status` 字段因 `MatchDecision` 改名（如新增 `match_decision` 字段但 `status` 保持），需保持 `status` 向后兼容（SELECT 仍 `"success"`，CLARIFY 仍 `"clarification"`，REJECT 仍 `"failure"`）。

- [x] **Step 5.4: matcher Eval 退出标准全过 + 接入 verify 脚本**

`scripts/verify-agent-callplan-evidence.sh` 新增一行（在现有 eval 之后）：

```bash
"$PYTHON_BIN" -m sap_nexus_agent.eval evals/matcher_cases.yaml
```

**验证:**
- `python -m sap_nexus_agent.eval evals/matcher_cases.yaml` 全过（五类决策 + false SELECT 回归）。
- `scripts/verify-agent-callplan-evidence.sh` 全过（含现有 inventory/PO/PR + S1 contract + pytest + openspec validate）。

archived-with: 2026-07-25-sap-nexus-planner-dry-run
---

## Task 6: S2-A Workbench 展示

**对应 tasks.md:** 6.1 / 6.2 / 6.3 / 6.4

**Files:**
- Modify: `frontend/src/runtime/run-event-schema.ts`
- Modify: `frontend/src/runtime/agent-runtime-adapter.ts`（与 Task 3.3 协同）
- Modify: `frontend/src/modules/agent-console/view-model.ts`
- Modify: `frontend/src/modules/agent-console/AgentConsole.tsx`
- Modify: `frontend/src/modules/agent-console/ChatStream.tsx`
- Modify: `frontend/tests/agent-console/`（现有测试目录）

**Interfaces:**
- Consumes: `match_decision_created` SSE 事件 + `match-decision` artifact。
- Produces: 只读五态决策视图（candidates / handoff / rationale）；dry-run 预览（S2-B Task 9.2 接入）。

**Design Doc 引用:** §"SSE 事件（`run-event-schema.ts`，改）"，§"Workbench 前端（`view-model.ts` / `AgentConsole.tsx` / `globals.css`，改）"。

- [x] **Step 6.1: `run-event-schema.ts` 新增 `match_decision_created` 事件 + `match-decision` artifact kind**

```typescript
export type AgentRunEventType =
  | "run_started"
  | "intent_parsed"
  | "capability_selected"
  | ...
  | "run_failed"
  | "match_decision_created";   // 新增

// artifact kind 新增 "match-decision"
// payload: { decisionType: "SHOW_OPTIONS" | "ESCALATE_TO_PLANNER", candidates?, handoff?, rationale }
```

`eventLabels` 映射新增 `match_decision_created: "匹配决策"`。SELECT/CLARIFY/REJECT 不新增事件，复用现有 `capability_selected` / `narrative_created`(clarification) / `run_failed`。

- [x] **Step 6.2: `view-model.ts` 渲染五态决策 - `buildMatchDecisionView` 纯函数**

```typescript
export type MatchDecisionView = {
  decisionType: "SELECT" | "CLARIFY" | "REJECT" | "SHOW_OPTIONS" | "ESCALATE_TO_PLANNER";
  candidates?: Array<{ capabilityId: string; parameters: Record<string, string>; missing: string[] }>;
  handoff?: { reason: string; matchedIntents: Array<...>; utterance: string; registrySnapshotId: string };
  rationale: string;
};

export function buildMatchDecisionView(snapshot: AgentRunSnapshot | null): MatchDecisionView | null {
  // 从 match-decision artifact 提取并构造只读视图
}
```

纯函数，不产生副作用；`WorkbenchViewModel.artifacts` 新增 `matchDecision?: RedactedArtifact` 字段。

- [x] **Step 6.3: `AgentConsole.tsx` / `ChatStream.tsx` 只读展示**

- `ChatStream.tsx`：SHOW_OPTIONS/ESCALATE turn 内折叠展示 `candidates` / `handoff`（默认折叠，点击展开）。
- `AgentConsole.tsx`：在 detail panel 渲染 `MatchDecisionView`（只读，无编辑按钮）。
- `globals.css`：折叠样式（若需要，最小改动）。
- 纯只读，不发任何 Gateway/SAP 调用；dry-run 预览（S2-B）在 Task 9.2 接入同一折叠组件。

- [x] **Step 6.4: 前端测试回归**

`frontend/tests/agent-console/` 新增/更新：
- `buildMatchDecisionView` 纯函数测试：五态 artifact 输入 -> 正确视图输出。
- `summarizeTurn` / `buildChatBubbleState` 回归：含 `match_decision_created` 事件的 turn 不破坏现有快照。
- `npm --prefix frontend run verify`（typecheck + test + build）全过。

**验证:** `npm --prefix frontend run verify` 全过。

archived-with: 2026-07-25-sap-nexus-planner-dry-run
---

# 阶段 S2-B：规划层

> 进入 S2-B 前置条件：S2-A Task 1-6 全部完成，matcher Eval + 现有回归通过。

## Task 7: S2-B planner 模块骨架

**对应 tasks.md:** 7.1 / 7.2 / 7.3

**Files:**
- Create: `agent/sap_nexus_agent/planner/__init__.py`
- Create: `agent/sap_nexus_agent/planner/capability_card.py`（若 Task 4 已建最小集，本 Task 扩展）
- Create: `agent/sap_nexus_agent/planner/goal_spec.py`
- Create: `agent/sap_nexus_agent/planner/plan_draft.py`
- Create: `agent/tests/test_planner_capability_card.py`

**Interfaces:**
- Consumes: `registry_loader.CapabilityDescriptor` + `capabilities.yaml` 的 `outputs.factTypeRef`；S1 `semantic_planning.RegistrySnapshot`；`match_decision.EscalationHandoff`。
- Produces: `CapabilityCard`（含 `producesFactTypes`）、`GoalSpec` v1、advisory `PlanDraft`。

**Design Doc 引用:** §"S2-B 规划层（`agent/sap_nexus_agent/planner/`，新）"，§"CapabilityCard"，§"GoalSpec / PlanDraft"。

- [x] **Step 7.1: `planner/` 模块 + `CapabilityCard` 完整字段**

`planner/capability_card.py` 扩展 Task 4 的最小集为 Design Doc 完整定义：

```python
@dataclass(frozen=True)
class InputDescriptor:
    name: str
    semantic_type: str
    required: bool
    binding_kind: str   # "literal" | "fact"
    satisfiable_by_fact_type: str | None = None

@dataclass(frozen=True)
class CapabilityCard:
    capability_id: str
    name: str
    inputs: tuple[InputDescriptor, ...]
    governance: Governance
    visibility: str     # VISIBLE_DRY_RUN / VISIBLE_EXECUTION / HIDDEN
    produces_fact_types: tuple[str, ...]   # from outputs.factTypeRef
```

`planner/__init__.py` 公开 `CapabilityCard` / `GoalSpec` / `PlanDraft` / `PlanCompiler` / `DryRunResult`。

- [x] **Step 7.2: `CapabilityCard` discovery - 从 Registry 闭集 + Snapshot 投影**

```python
def discover_cards(snapshot: RegistrySnapshot, sources: SemanticSourceDocuments) -> list[CapabilityCard]:
    # 遍历 sources.capabilities["capabilities"]，对每个 capability:
    #   - inputs -> InputDescriptor (bindingKind, satisfiableByFactType)
    #   - governance -> Governance
    #   - outputs[].factTypeRef -> produces_fact_types
    #   - visibility 默认 VISIBLE_DRY_RUN; 写能力 VISIBLE_DRY_RUN (执行层由 visibility.filter_visible 过滤)
```

从 `registry_loader.load_intent_catalog()` 或直接读 `capabilities.yaml` + S1 `load_semantic_sources()` 投影。`producesFactTypes` 明确来自 `outputs.factTypeRef`（Design Doc §Spec Patch 2）。

- [x] **Step 7.3: `GoalSpec` / `PlanDraft` candidate 生成（复用 S1 schema）**

`planner/goal_spec.py`：复用 S1 `semantic_planning` 的 `GoalSpec v1` schema（`goalType` / `desiredFactTypes` / `executionMode=PLAN_ONLY`）。从 `EscalationHandoff.matched_intents` + `CapabilityCard.produces_fact_types` 构造 `desiredFactTypes`：

```python
def build_goal_spec(handoff: EscalationHandoff, cards: list[CapabilityCard]) -> GoalSpec:
    # matched_intents -> 对应 CapabilityCard.produces_fact_types -> desiredFactTypes 去重
    # executionMode = "PLAN_ONLY"（dry-run 不授权执行）
```

`planner/plan_draft.py`：advisory `PlanDraft`（capability 组合草案），`@dataclass(frozen=True)`，标 `advisory=True`，不授予执行权威。`PlanDraft` 不是 `PlanGraph`，需经 `PlanCompiler` 确定性编译才产出 `PlanGraph`。

**验证:** `pytest agent/tests/test_planner_capability_card.py` 全过；`CapabilityCard.produces_fact_types` 字段断言来自 `outputs.factTypeRef`。

archived-with: 2026-07-25-sap-nexus-planner-dry-run
---

## Task 8: S2-B PlanCompiler dry-run

**对应 tasks.md:** 8.1 / 8.2 / 8.3 / 8.4

**Files:**
- Create: `agent/sap_nexus_agent/planner/plan_compiler.py`
- Create: `agent/tests/test_planner_plan_compiler.py`

**Interfaces:**
- Consumes: `GoalSpec` + `RegistrySnapshot` + S1 `semantic_planning.validation`（`PlanGraph` validator）。
- Produces: `DryRunResult`（`plan_graph` / `gaps` / `governance_flags` / `rationale`）。

**Design Doc 引用:** §"PlanCompiler（`plan_compiler.py`）"，§"dry-run 输出"，§"错误处理与边界条件"（PlanCompiler 缺口 / S1 validator 失败）。

- [x] **Step 8.1: deterministic `PlanCompiler` 实现 - `GoalSpec` + Snapshot -> `PlanGraph`**

```python
@dataclass(frozen=True)
class Gap:
    kind: str   # "missing_parameter" | "missing_capability"
    detail: str

@dataclass(frozen=True)
class Flag:
    kind: str   # "requires_approval" | "write_side_effect" | "invalid_plan_graph"
    detail: str

@dataclass(frozen=True)
class DryRunResult:
    plan_graph: PlanGraph          # 节点/边/参数来源(goalConstraint/literal/factField)
    gaps: list[Gap]
    governance_flags: list[Flag]
    rationale: str

def compile_dry_run(goal: GoalSpec, snapshot: RegistrySnapshot) -> DryRunResult:
    # deterministic: 不调 LLM, 不调 Gateway/SAP
    plan_graph = _build_plan_graph(goal, snapshot)
    ...
```

`_build_plan_graph`：从 `goal.desiredFactTypes` 匹配 `CapabilityCard.produces_fact_types`，构造节点（capability_id + 参数来源 `goalConstraint`/`literal`/`factField`）和边（`data`/`dependency`）。参数来源映射 S1 `PlanGraph v1` 契约。

- [x] **Step 8.2: 复用 S1 `PlanGraph` validator（不重新实现）**

```python
from sap_nexus_agent.semantic_planning.validation import (  # S1 已归档契约
    validate_plan_graph,  # 或 S1 暴露的等价入口
)

def compile_dry_run(goal, snapshot):
    plan_graph = _build_plan_graph(goal, snapshot)
    report = validate_plan_graph(plan_graph, snapshot)   # provenance/edges/governance/topological order
    if not report.valid:
        return DryRunResult(plan_graph=plan_graph, gaps=[], 
                            governance_flags=[Flag("invalid_plan_graph", ...)],
                            rationale="S1 validator failed: " + ...)
    ...
```

直接 `import` S1 `semantic_planning.validation`，**不重新实现** validator。若 S1 入口签名需要 `ImmutableSemanticGraph`，通过 `SemanticGraphCompiler().compile(sources)` 构造。Design Doc §风险："S2-B 复用 S1 validator 契约漂移" -> S1 已归档契约锁定，本 Task 测试 import S1 validator 断言。

- [x] **Step 8.3: dry-run 输出 - `PlanGraph` + `gaps` + `governanceFlags`**

- `_compute_gaps(goal, plan_graph)`：`goal.desiredFactType` 无 producer capability -> `Gap(kind="missing_capability")`；节点缺参 -> `Gap(kind="missing_parameter")`。dry-run 输出 incomplete，不报错。
- `_compute_governance_flags(plan_graph)`：写能力节点 -> `Flag(kind="write_side_effect")`；`requiresApproval=True` -> `Flag(kind="requires_approval")`。
- `rationale`：决策理由（"dry-run compiled N nodes, M gaps, K flags"）。

- [x] **Step 8.4: 不调用 Gateway validate/execute 的断言测试**

`agent/tests/test_planner_plan_compiler.py`：

```python
def test_plan_compiler_does_not_call_gateway():
    mock_gateway = Mock(spec=GatewayClientProtocol)
    result = compile_dry_run(goal, snapshot)
    mock_gateway.validate.assert_not_called()
    mock_gateway.execute.assert_not_called()
    assert result.plan_graph is not None
```

补充：
- PlanGraph 通过 S1 validator（import S1 validator 测试断言 `report.valid is True` for valid goal）。
- 缺 producer capability -> `gaps` 含 `missing_capability`。
- 写能力节点 -> `governance_flags` 含 `write_side_effect`。
- S1 validator 失败 -> `governance_flags=[invalid_plan_graph]`，不抛异常。

**验证:** `pytest agent/tests/test_planner_plan_compiler.py` 全过；mock 断言 Gateway validate/execute 零调用。

archived-with: 2026-07-25-sap-nexus-planner-dry-run
---

## Task 9: S2-B handoff 接入与展示

**对应 tasks.md:** 9.1 / 9.2 / 9.3

**Files:**
- Modify: `agent/sap_nexus_agent/orchestrator.py`（或新增 `planner/handoff.py`）
- Modify: `frontend/src/modules/agent-console/ChatStream.tsx`
- Create: `evals/dry_run_cases.yaml`
- Modify: `scripts/verify-agent-callplan-evidence.sh`

**Interfaces:**
- Consumes: `MatchDecision.ESCALATE_TO_PLANNER.handoff` + `PlanCompiler.compile_dry_run`。
- Produces: dry-run 候选接入 orchestrator；前端 dry-run 预览折叠展示；dry-run cases 进 eval。

**Design Doc 引用:** §"总体数据流"（ESCALATE handoff -> planner -> dry-run 输出 -> Workbench 折叠展示）。

- [x] **Step 9.1: `ESCALATE_TO_PLANNER` handoff 接入 `PlanCompiler`**

在 `orchestrator.run_query` 的 `ESCALATE_TO_PLANNER` 分支（Task 3.2 已建）内，调用 `PlanCompiler`：

```python
if decision.decision_type == "ESCALATE_TO_PLANNER":
    goal = build_goal_spec(decision.handoff, discover_cards(snapshot, sources))
    dry_run = compile_dry_run(goal, snapshot)
    return AgentOutcome(status="match_decision", match_decision=decision,
                        dry_run=dry_run, ...)
```

`AgentOutcome` 新增 `dry_run: DryRunResult | None = None`。`workbench_output.py` 序列化 `dry_run`（plan_graph/gaps/flags/rationale）。dry-run **不执行** Gateway/SAP（Task 8.4 已断言）。

- [x] **Step 9.2: Workbench 前端 dry-run 预览展示（折叠式）**

`ChatStream.tsx` 在 ESCALATE turn 内（Task 6.3 的折叠组件）追加 dry-run 预览：
- 折叠展示 `PlanGraph` 节点（capability_id + 参数来源）、边、`gaps`、`governanceFlags`。
- 标注"dry-run 预览，不执行 Gateway/SAP"。
- 纯只读，无执行按钮。

`view-model.ts` 新增 `buildDryRunView(snapshot)` 纯函数（类似 `buildMatchDecisionView`）。

- [x] **Step 9.3: dry-run cases 进 eval**

`evals/dry_run_cases.yaml`：

```yaml
cases:
  - id: multi-goal-dry-run
    userQuery: "DEMOA2 在 5100 的库存，再列出近 30 天未清采购订单"
    expected:
      decisionType: ESCALATE_TO_PLANNER
      dryRun:
        nodeCount: 2          # inventory + purchase_order
        validateCalls: 0
        executeCalls: 0
  - id: dry-run-missing-producer
    userQuery: "<构造期望缺 producer 的多目标>"
    expected:
      decisionType: ESCALATE_TO_PLANNER
      dryRun:
        gapsContain: "missing_capability"
        validateCalls: 0
        executeCalls: 0
```

`scripts/verify-agent-callplan-evidence.sh` 接入：

```bash
"$PYTHON_BIN" -m sap_nexus_agent.eval evals/dry_run_cases.yaml
```

**验证:** `python -m sap_nexus_agent.eval evals/dry_run_cases.yaml` 全过；`npm --prefix frontend run verify` 全过（含 dry-run 预览渲染）。

archived-with: 2026-07-25-sap-nexus-planner-dry-run
---

# 阶段 验证与归档准备

## Task 10: 验证与归档准备

**对应 tasks.md:** 10.1 / 10.2 / 10.3 / 10.4

**Files:**
- Modify: `docs/runbooks/10-capability-composition-contract.md`
- Modify: `docs/runbooks/README.md`
- Modify: `openspec/changes/sap-nexus-planner-dry-run/specs/semantic-match-decision/spec.md`（Spec Patch 1）
- Modify: `openspec/changes/sap-nexus-planner-dry-run/specs/planner-dry-run/spec.md`（Spec Patch 2）

- [x] **Step 10.1: `npm --prefix frontend run verify` 通过**

前端 typecheck + test + build 全过（含 Task 6.4 / 9.2 的前端测试）。

- [x] **Step 10.2: `openspec validate --all --strict` 通过**

含本 change 的 Spec Patch：
1. `specs/semantic-match-decision/spec.md`：SHOW_OPTIONS 触发条件细化为"utterance 弱匹配多能力关键词集合且无明确主意图（关键词歧义），阈值由 matcher Eval 锚定"（Design Doc §Spec Patch 1）。
2. `specs/planner-dry-run/spec.md`：`CapabilityCard` 字段明确含 `producesFactTypes`（from `outputs.factTypeRef`），供 PlanCompiler 从 GoalSpec desiredFactType 匹配候选能力（Design Doc §Spec Patch 2）。
3. `specs/agent-callplan-evidence/spec.md`：无需额外 patch（open 阶段 MODIFIED 已覆盖）。

- [x] **Step 10.3: `scripts/verify-agent-callplan-evidence.sh` 通过**

组合门禁全过：
- `scripts/validate-semantic-planning-contract.py`（S1 契约）
- `pytest agent/tests`（含 Task 1/2/4/7/8 新测 + 现有 intent/selector/orchestrator/workbench 适配）
- `evals/inventory_availability_cases.yaml` / `eval_harness_seed_cases.json` / `pr_create_cases.json`（现有回归）
- `evals/matcher_cases.yaml`（Task 5）
- `evals/dry_run_cases.yaml`（Task 9.3）
- `openspec validate --all --strict`

- [x] **Step 10.4: `docs/runbooks/10-capability-composition-contract.md` 更新 + README index 同步**

更新 runbook（参考 MEMORY.md 提醒：先读实际当前 version 再 bump，避免版本漂移）：
- `Version` bump（如 `v0.3.6` -> `v0.3.7` 或按实际当前版本）。
- `Status` 改为 `S2-A Done; S2-B Dry-Run Done; S3 Gate Next`。
- `Last Change` 记录 S2-A MatchDecision + S2-B PlanCompiler dry-run 完成（2026-07-25）。
- `Current Phase` 更新为 S2-A/S2-B 完成，下一推荐 S3 read-only composition pilot gate。
- `docs/runbooks/README.md` index 同步本 runbook 版本与状态。

**验证:** runbook 版本字段与实际 bump 后一致；`openspec validate --all --strict` 仍通过（runbook 不在 openspec 校验范围，但 README index 若引用 change 状态需一致）。

archived-with: 2026-07-25-sap-nexus-planner-dry-run
---

## 交付顺序总结

| 阶段 | Task 组 | 退出标准 |
|---|---|---|
| S2-A | 1 -> 2 -> 3 -> 4 -> 5 -> 6 | matcher Eval 五类决策 + false SELECT 回归全过；现有 inventory/PO/PR eval 回归不破坏；前端 verify 通过 |
| S2-B | 7 -> 8 -> 9 | PlanCompiler dry-run 输出 PlanGraph + gaps + flags；mock 断言不调 Gateway；dry-run cases 进 eval |
| 验证归档 | 10 | `verify-agent-callplan-evidence.sh` + `npm verify` + `openspec validate --all --strict` 全过；runbook 更新 |

## 风险与缓解（执行期关注）

| 风险 | 缓解 |
|---|---|
| `MatchDecision` 替代 `SelectionResult` 破坏调用方 | `to_selection_result()` 窄视图渐进迁移；一个发布周期后评估移除 |
| rule 多意图扫描误判（"采购订单"含"订单"） | 关键词主/弱分级 + 阈值表常量化（Task 2.2）；matcher Eval 覆盖单意图/多目标/歧义（Task 5） |
| SSE 混合事件前端处理两种路径 | view-model 统一 `MatchDecisionView`，前端只读渲染（Task 6.2） |
| S2-B 复用 S1 validator 契约漂移 | S1 已归档契约锁定；PlanCompiler 测试 import S1 validator 断言（Task 8.2/8.4） |
| 写能力 dry-run 可见误执行 | visibility pre-filter `for_execution=True` 过滤（Task 4.2）；PlanCompiler 不调 Gateway（Task 8.4）；前端标注"不执行"（Task 9.2） |
| S2-A/S2-B 同 change 范围偏大 | 严格按阶段编排：S2-A 先过 matcher Eval 再 S2-B；每个 Task 验收后打勾 + commit（由协调者按 review_mode 执行） |
| runbook 版本漂移 | Task 10.4 先读实际当前 version 再 bump（MEMORY.md 提醒） |


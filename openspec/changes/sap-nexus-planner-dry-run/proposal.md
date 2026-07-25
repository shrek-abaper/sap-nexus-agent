## Why

当前 Agent 的意图选择是隐式三态（`SelectionResult`：SELECT / CLARIFY / REJECT），且 rule parser 按固定顺序返回**首个命中意图**（`intent.py:59-81` inventory -> purchase_order -> pr_create）。这导致多目标 utterance（如「物料 DEMOA2 在工厂 5100 的可用库存，再列出近 30 天未清采购订单」）被**静默降级为单能力执行**--已知正确性缺陷 D-1。架构契约要求多能力请求必须 `ESCALATE_TO_PLANNER`（record + explain），但当前 runtime 无法表达该决策，也没有 `SHOW_OPTIONS`/`ESCALATE_TO_PLANNER` 状态。roadmap row 19 要求 S2-A 五态 `MatchDecision` + S2-B `PlanCompiler` dry-run，两者均不执行 Gateway/SAP。

## What Changes

**S2-A - Semantic MatchDecision Hardening**

- 引入显式五态 `MatchDecision`（`SELECT` / `CLARIFY` / `REJECT` / `SHOW_OPTIONS` / `ESCALATE_TO_PLANNER`），替代隐式 `SelectionResult`
- 多意图/歧义检测：多目标 utterance 必须 `ESCALATE_TO_PLANNER`（record + explain），**不得静默首命中单能力**（修复 D-1；`false SELECT` 作为回归失败项）
- visibility pre-filter：候选可见性边界，决定哪些候选对用户/下游可见
- matcher Eval 退出标准：覆盖单意图命中、缺参澄清、技术覆盖拒绝、多目标升级、歧义选项五类场景

**S2-B - Planner Dry-run**

- progressive `CapabilityCard` discovery：从 Registry 闭集按 GoalSpec 投影候选能力
- `GoalSpec` / `PlanDraft` candidate 生成（advisory，不授予执行权威）
- deterministic `PlanCompiler` 输出 dry-run：含节点、边、参数来源（`goalConstraint`/`literal`/`factField`）、缺口、治理标记，可审计
- `ESCALATE_TO_PLANNER` 后的 handoff 在 S2-B 落地为 dry-run 候选生成，**不执行 Gateway/SAP**

**整体**：纯 dry-run，不执行 Gateway/SAP；`registry/capabilities.yaml` 只读消费，不改能力定义。

## Capabilities

### New Capabilities

- `semantic-match-decision`: 五态 `MatchDecision` 决策对象、多意图/歧义检测、visibility pre-filter、matcher Eval 退出标准（S2-A）
- `planner-dry-run`: `CapabilityCard` discovery、`GoalSpec`/`PlanDraft` candidate 生成、deterministic `PlanCompiler` dry-run 输出（S2-B）

### Modified Capabilities

- `agent-callplan-evidence`: 能力选择从隐式三态 `SelectionResult` 升级为显式五态 `MatchDecision`；rule/LLM parser 不再静默首命中，多目标请求必须 `ESCALATE_TO_PLANNER`；`false SELECT` 纳入回归失败项

## Impact

- **Agent intent/selector 层**：`agent/sap_nexus_agent/intent.py`、`capability_selector.py`、`llm_intent.py`（多意图检测 + `MatchDecision` 输出）
- **新增 planner 模块**：`agent/sap_nexus_agent/planner/`（`CapabilityCard`、`GoalSpec`、`PlanDraft`、`PlanCompiler`）
- **Eval**：`evals/` 新增 matcher cases（S2-A）与 dry-run cases（S2-B）
- **Workbench 前端**：`MatchDecision` 五态与 dry-run 预览的只读展示（`view-model.ts`、`AgentConsole.tsx`、`globals.css`）
- **Registry**：`registry/capabilities.yaml` 只读消费，不改能力定义
- **SSE/snapshot 契约**：`run-event-schema.ts` 可能新增 `MatchDecision` / dry-run 相关事件字段（仅展示层，不改 Gateway/SAP 执行契约）
- **交付顺序**：S2-A 先完成并过 matcher Eval，再进 S2-B；S2-B dry-run 不依赖 Gateway/SAP 可用

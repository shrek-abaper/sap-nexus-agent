## Context

当前 Agent 意图选择链路为 `parse_intent` (rule 首命中) / `parse_with_llm` (单选) -> `IntentParseResult` (单 intent) -> `select_capability` -> `SelectionResult`（隐式三态：SELECT / CLARIFY / REJECT）。`intent.py:59-81` 按固定顺序返回首个命中意图，多目标 utterance 被静默降级为单能力（缺陷 D-1）。S1 `semantic-planning-foundation` 已定义 `GoalSpec` / `PlanGraph` / Registry Snapshot 契约并归档，但 runtime 尚未实现五态 `MatchDecision` 与 `PlanCompiler` dry-run。本 change 在 S1 契约之上落地 S2-A（决策层）与 S2-B（dry-run 规划层），均不执行 Gateway/SAP。

## Goals / Non-Goals

**Goals:**

- S2-A：显式五态 `MatchDecision`（`SELECT` / `CLARIFY` / `REJECT` / `SHOW_OPTIONS` / `ESCALATE_TO_PLANNER`）替代隐式 `SelectionResult`
- S2-A：多意图/歧义检测，多目标 utterance 必须 `ESCALATE_TO_PLANNER`（record + explain），修复 D-1
- S2-A：visibility pre-filter（候选可见性边界）+ matcher Eval 退出标准
- S2-B：progressive `CapabilityCard` discovery + `GoalSpec`/`PlanDraft` candidate + deterministic `PlanCompiler` dry-run
- dry-run 输出可审计（节点/边/参数来源/缺口/治理），不执行 Gateway/SAP

**Non-Goals:**

- `ESCALATE_TO_PLANNER` 后的实际 planner 执行（S2-B 只生成 dry-run 候选，不执行）
- Gateway/SAP 执行、S3 read-only composition pilot、trusted/durable runtime
- Phase 3+ embedding/retrieval/rerank、Dynamic Planner、Write composition
- 修改 `registry/capabilities.yaml` 能力定义（只读消费）

## Decisions

### D1: `MatchDecision` 作为显式决策对象，`SelectionResult` 退为其 SELECT/CLARIFY/REJECT 子集

引入 `MatchDecision` dataclass（`decision_type` + `candidates` + `rationale` + `handoff`），替代 `SelectionResult` 作为 selector 输出。现有 `select_capability` 调用方改为消费 `MatchDecision`；为向后兼容，`SelectionResult` 可保留为 `MatchDecision` 在 SELECT/CLARIFY/REJECT 三态的窄视图，避免一次性破坏 orchestrator/eval。

*替代方案*：直接删除 `SelectionResult`。*否决*：破坏面过大，违反 surgical change 原则。

### D2: 多意图检测在 rule 与 LLM 双路径统一生效

- rule 路径：`parse_intent` 改为**扫描全部能力关键词集合**，统计命中数；>1 命中 -> `ESCALATE_TO_PLANNER`，不再首命中即返回。单命中走原提取逻辑。
- LLM 路径：system prompt 从 "Select exactly one" 改为 "detect all matching capabilities；if >1, return escalation"；`_payload_to_parse_result` 解析多候选。

*替代方案*：仅改 rule 路径。*否决*：hybrid 模式 LLM 仍会单选降级，D-1 未根治。

### D3: visibility pre-filter 基于 governance + 数据分类

候选 `CapabilityCard` 携带 `governance`（sideEffect/requiresApproval/dataClassification）。visibility pre-filter 按 `sideEffect=none` + `dataClassification=internal` 默认可见，写能力与受限数据默认对 dry-run 可见但对执行不可见（S3 才解锁）。边界细节在 design 阶段 Design Doc 细化。

### D4: S2-B 复用 S1 `PlanGraph` validator，不重新实现图校验

`PlanCompiler` 输入 `GoalSpec` + Registry Snapshot，输出 `PlanGraph`（dry-run）。`PlanGraph` 校验复用 S1 `semantic-planning-foundation` 的 deterministic validator（provenance/edges/governance/topological order），不重新实现。`GoalSpec`/`PlanDraft` 复用 S1 契约 schema。

### D5: dry-run 输出 = `PlanGraph` + 缺口摘要 + 治理标记

dry-run 不执行，输出结构化 `PlanGraph`（节点/边/参数来源 `goalConstraint`/`literal`/`factField`）+ `gaps`（缺参/缺能力）+ `governanceFlags`（需审批/写副作用）。Workbench 前端只读展示。

### D6: Workbench 展示 `MatchDecision` 五态 + dry-run 预览

`run-event-schema.ts` 新增 `MatchDecision` artifact kind 与 dry-run 事件（仅展示层，不改 Gateway/SAP 执行契约）。`view-model.ts` / `AgentConsole.tsx` 只读渲染五态与 dry-run 预览。

## Risks / Trade-offs

- **[MatchDecision 替代 SelectionResult 破坏现有调用]** -> Mitigation: D1 保留 `SelectionResult` 窄视图，渐进迁移；eval 覆盖回归
- **[多意图检测误判（单意图含多关键词）]** -> Mitigation: Eval cases 覆盖单意图/多目标/歧义；关键词集合精化
- **[PlanCompiler 复杂度膨胀]** -> Mitigation: D4 复用 S1 validator；S2-B 只做 deterministic 编译，不做 LLM 自由编排
- **[dry-run 输出过大影响前端]** -> Mitigation: D5 结构化 PlanGraph + 缺口摘要，前端折叠展示
- **[S2-A/S2-B 同 change 范围偏大]** -> Mitigation: 交付顺序 S2-A 先完成过 Eval，再 S2-B；tasks.md 分阶段勾选

## Migration Plan

- S2-A：`MatchDecision` 引入后，`select_capability` 输出 `MatchDecision`，orchestrator/eval 适配；`SelectionResult` 窄视图保留一个发布周期
- S2-B：`planner/` 模块新增，`ESCALATE_TO_PLANNER` handoff 接入 `PlanCompiler`；不触碰 Gateway/SAP 路径
- 回滚：`MatchDecision` 改动限于 agent intent/selector 层，回滚恢复 `SelectionResult`；S2-B 模块独立，可整体禁用

## Open Questions

1. `ESCALATE_TO_PLANNER` handoff 数据结构（record + explain 具体字段）
2. `SHOW_OPTIONS` 触发条件（多候选 vs 歧义词汇的判定阈值）
3. visibility pre-filter 对写能力在 dry-run 中的可见粒度
4. `MatchDecision` 是否需要 SSE 事件独立化（还是复用 `intent_parsed`/`capability_selected` artifact）
5. S2-B `CapabilityCard` 与 Registry descriptor 的字段映射

> 以上 Open Questions 留待 design 阶段 Design Doc 细化，不在 open 阶段产物中定死。

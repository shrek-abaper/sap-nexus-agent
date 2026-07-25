# Comet Design Handoff

- Change: sap-nexus-planner-dry-run
- Phase: design
- Mode: compact
- Context hash: f186eee18238417ad11070d7d8a371fa839242c742d875c9b26b82b8fc306b64

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/sap-nexus-planner-dry-run/proposal.md

- Source: openspec/changes/sap-nexus-planner-dry-run/proposal.md
- Lines: 1-42
- SHA256: ae83f2c3a06df3905b1495956931310eeb7b70423b30fbceefaea05f3f7ecad6

```md
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

```

## openspec/changes/sap-nexus-planner-dry-run/design.md

- Source: openspec/changes/sap-nexus-planner-dry-run/design.md
- Lines: 1-75
- SHA256: 2b7cb7f7ae0df27c0c4e5aabaf8bab466fdb2999056439b83f05d987f41759b8

```md
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

```

## openspec/changes/sap-nexus-planner-dry-run/tasks.md

- Source: openspec/changes/sap-nexus-planner-dry-run/tasks.md
- Lines: 1-65
- SHA256: a2403d13f33326669d6e0f034837b7554c15a3c35301591a774624cbfe90b56a

```md
## 1. S2-A MatchDecision 决策对象

- [ ] 1.1 定义 `MatchDecision` dataclass（`decision_type` / `candidates` / `rationale` / `handoff`），`decision_type` 为五态枚举
- [ ] 1.2 `SelectionResult` 退为 `MatchDecision` 在 SELECT/CLARIFY/REJECT 三态的窄视图（向后兼容 wrapper）
- [ ] 1.3 单元测试：五态构造与窄视图兼容

## 2. S2-A 多意图检测（修复 D-1）

- [ ] 2.1 改 `parse_intent` rule 路径：扫描全部能力关键词集合，统计命中数，不再首命中即返回
- [ ] 2.2 命中 >1 -> `ESCALATE_TO_PLANNER`；单命中走原参数提取逻辑
- [ ] 2.3 改 LLM 路径 system prompt：从 "Select exactly one" 改为 "detect all matching capabilities；if >1, return escalation"
- [ ] 2.4 改 `_payload_to_parse_result` 解析多候选并产出升级决策
- [ ] 2.5 单元测试：多目标 utterance 升级、单意图不误判

## 3. S2-A selector 输出 MatchDecision

- [ ] 3.1 `select_capability` 输出 `MatchDecision`（SELECT/CLARIFY/REJECT/SHOW_OPTIONS/ESCALATE_TO_PLANNER）
- [ ] 3.2 `orchestrator.run_query` 适配 `MatchDecision`：SELECT 进 CallPlan，CLARIFY 返回澄清，REJECT 返回拒绝，SHOW_OPTIONS/ESCALATE 返回 handoff（不执行 Gateway）
- [ ] 3.3 `agent-runtime-adapter.ts` / `workbench_output.py` 适配 `MatchDecision` 序列化

## 4. S2-A visibility pre-filter

- [ ] 4.1 `CapabilityCard` 投影：从 `registry_loader` descriptor 生成（`capabilityId` / `inputs` / `governance` / `visibility`）
- [ ] 4.2 visibility pre-filter：`sideEffect=none` + `dataClassification=internal` 默认可见；写能力 dry-run 可见但不可执行
- [ ] 4.3 单元测试：读写能力可见性边界

## 5. S2-A matcher Eval

- [ ] 5.1 新增 `evals/` matcher cases 覆盖五类决策（SELECT/CLARIFY/REJECT/SHOW_OPTIONS/ESCALATE_TO_PLANNER）
- [ ] 5.2 `false SELECT`（多目标静默降级为单 SELECT）作为回归失败项
- [ ] 5.3 现有 inventory/PO/PR eval 回归不破坏
- [ ] 5.4 matcher Eval 退出标准全过

## 6. S2-A Workbench 展示

- [ ] 6.1 `run-event-schema.ts` 新增 `MatchDecision` artifact kind（仅展示层，不改 Gateway/SAP 契约）
- [ ] 6.2 `view-model.ts` 渲染五态决策与候选
- [ ] 6.3 `AgentConsole.tsx` / `globals.css` 只读展示 `MatchDecision`（含 ESCALATE/SHOW_OPTIONS 的 handoff/候选）
- [ ] 6.4 前端测试（`summarizeTurn` / `buildChatBubbleState`）回归

## 7. S2-B planner 模块骨架

- [ ] 7.1 新增 `agent/sap_nexus_agent/planner/` 模块（`CapabilityCard` / `GoalSpec` / `PlanDraft` / `PlanCompiler`）
- [ ] 7.2 `CapabilityCard` discovery 实现（从 Registry 闭集 + Snapshot 投影）
- [ ] 7.3 `GoalSpec` / `PlanDraft` candidate 生成（复用 S1 `semantic-planning-foundation` schema）

## 8. S2-B PlanCompiler dry-run

- [ ] 8.1 deterministic `PlanCompiler` 实现：`GoalSpec` + Registry Snapshot -> `PlanGraph`
- [ ] 8.2 复用 S1 `PlanGraph` validator 校验（provenance / edges / governance / topological order），不重新实现
- [ ] 8.3 dry-run 输出：`PlanGraph` + `gaps` + `governanceFlags`，可审计
- [ ] 8.4 `PlanCompiler` 不调用 Gateway validate/execute 的断言测试

## 9. S2-B handoff 接入与展示

- [ ] 9.1 `ESCALATE_TO_PLANNER` handoff 接入 `PlanCompiler`，产出 dry-run 候选
- [ ] 9.2 Workbench 前端 dry-run 预览展示（节点/边/参数来源/缺口/治理，折叠式）
- [ ] 9.3 dry-run cases 进 eval

## 10. 验证与归档准备

- [ ] 10.1 `npm --prefix frontend run verify`（typecheck + test + build）通过
- [ ] 10.2 `openspec validate --all --strict` 通过
- [ ] 10.3 `scripts/verify-agent-callplan-evidence.sh` 通过
- [ ] 10.4 `docs/runbooks/10-capability-composition-contract.md` 更新（S2-A 完成、S2-B 完成、下一推荐）+ README index 同步

```

## openspec/changes/sap-nexus-planner-dry-run/specs/agent-callplan-evidence/spec.md

- Source: openspec/changes/sap-nexus-planner-dry-run/specs/agent-callplan-evidence/spec.md
- Lines: 1-32
- SHA256: 640d5b76cf9765bf4f694400004ab6d3e7f4e7306cd55cfd797253a1f8a61b71

```md
## MODIFIED Requirements

### Requirement: Closed-set capability selection
The system SHALL select capabilities only from the Registry closed set and MUST reject unsupported intent before Gateway execution. The selector SHALL emit an explicit five-state `MatchDecision` (`SELECT` / `CLARIFY` / `REJECT` / `SHOW_OPTIONS` / `ESCALATE_TO_PLANNER`) replacing the implicit `SelectionResult`. The selector SHALL route recognized single intents to their registered capability IDs across executor types (for example `inventory_availability` -> `MM.Inventory.GetAvailability` via `JCO_RFC`, `purchase_order_list` -> `MM.PurchaseOrder.GetList` via `ODATA`) without the Agent needing to know the executor type or binding at selection time. LLM-assisted selection MUST be constrained to the same closed set and MUST NOT introduce new executable capability IDs.

The rule parser and LLM parser SHALL detect multiple intents in a single utterance. When more than one capability intent is detected, the selector MUST emit `ESCALATE_TO_PLANNER` with a record and explanation, and MUST NOT silently reduce to the first-matched single capability.

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

#### Scenario: LLM selects registered capability only
- **WHEN** the LLM returns a single `capabilityId=MM.Inventory.GetAvailability` or `MM.PurchaseOrder.GetList` with required parameters
- **THEN** the Agent accepts the candidate only after deterministic validation confirms the closed-set capability and emits `SELECT`

#### Scenario: LLM returns unknown capability
- **WHEN** the LLM returns an unknown or unsupported `capabilityId`
- **THEN** the Agent emits `MatchDecision.decision_type=REJECT` and does not call Gateway validate or execute

#### Scenario: False SELECT fails regression
- **WHEN** a multi-goal utterance is silently reduced to a single `SELECT`
- **THEN** the matcher Eval marks this as a regression failure

```

## openspec/changes/sap-nexus-planner-dry-run/specs/planner-dry-run/spec.md

- Source: openspec/changes/sap-nexus-planner-dry-run/specs/planner-dry-run/spec.md
- Lines: 1-35
- SHA256: 47d52bc2a4ad0c6fff5ccc81df0ee4f49298dd0aca67cf26dc5c4d3614afc7f7

```md
## ADDED Requirements

### Requirement: CapabilityCard discovery
The system SHALL project registered capabilities into `CapabilityCard`s carrying `capabilityId`, `name`, `inputs`, `governance`, `visibility`, and `producesFactTypes` (derived from the capability `outputs.factTypeRef`), derived from the Registry closed set and the bound Registry Snapshot. `producesFactTypes` enables the `PlanCompiler` to match candidate capabilities against a `GoalSpec` desired Fact Types. A `CapabilityCard` is advisory and grants no execution authority.

#### Scenario: Project read capability to CapabilityCard
- **WHEN** the planner discovers `MM.Inventory.GetAvailability` from the Registry
- **THEN** a `CapabilityCard` is produced with its inputs, governance (`sideEffect=none`, `requiresApproval=false`), visibility, and `producesFactTypes` from its `outputs.factTypeRef`

### Requirement: GoalSpec and PlanDraft candidate generation
The system SHALL generate `GoalSpec` v1 (per `semantic-planning-foundation`) and advisory `PlanDraft` candidates from a `MatchDecision.ESCALATE_TO_PLANNER` handoff. `GoalSpec` and `PlanDraft` are advisory; only deterministic compilation may produce a `PlanGraph`.

#### Scenario: Escalation produces GoalSpec
- **WHEN** `MatchDecision.decision_type=ESCALATE_TO_PLANNER`
- **THEN** the planner generates a `GoalSpec` with desired Fact Types and `executionMode=PLAN_ONLY`

### Requirement: Deterministic PlanCompiler dry-run
The system SHALL compile `GoalSpec` plus Registry Snapshot into a `PlanGraph` via a deterministic `PlanCompiler`. The `PlanGraph` SHALL be validated by the S1 `semantic-planning-foundation` validator (provenance, edges, governance, topological order). The `PlanCompiler` MUST NOT execute Gateway or SAP.

#### Scenario: Dry-run produces auditable PlanGraph
- **WHEN** the `PlanCompiler` runs on a valid `GoalSpec`
- **THEN** it outputs a `PlanGraph` with nodes, edges, parameter sources (`goalConstraint`/`literal`/`factField`), gaps, and governance flags
- **AND** it does not call Gateway validate or execute

#### Scenario: PlanGraph validation reuses S1 validator
- **WHEN** the `PlanCompiler` emits a `PlanGraph`
- **THEN** the S1 `semantic-planning-foundation` validator validates provenance, edges, governance, and topological order

### Requirement: Dry-run output auditable and non-executing
The dry-run output SHALL include `PlanGraph`, `gaps` (missing parameters or capabilities), and `governanceFlags` (approval required, write side-effect). The output SHALL be auditable: candidate, decision rationale, Registry Snapshot, nodes, edges, parameter sources, gaps, and governance. The system MUST NOT execute Gateway or SAP from dry-run output.

#### Scenario: Dry-run output is auditable
- **WHEN** dry-run completes
- **THEN** the output contains PlanGraph, gaps, governanceFlags, and decision rationale
- **AND** no Gateway validate or execute is called

```

## openspec/changes/sap-nexus-planner-dry-run/specs/semantic-match-decision/spec.md

- Source: openspec/changes/sap-nexus-planner-dry-run/specs/semantic-match-decision/spec.md
- Lines: 1-47
- SHA256: 8386c08b7878909202fec8dc108817ed87be0aa93addaaf9b62c07b7424fbaf3

```md
## ADDED Requirements

### Requirement: Five-state MatchDecision object
The system SHALL produce a `MatchDecision` as the selector output with `decision_type` exactly one of `SELECT`, `CLARIFY`, `REJECT`, `SHOW_OPTIONS`, `ESCALATE_TO_PLANNER`, plus `candidates`, `rationale`, and `handoff` fields. `SELECT` SHALL carry exactly one `capabilityId` with complete parameters; `CLARIFY` SHALL carry missing parameters; `REJECT` SHALL carry an error type; `SHOW_OPTIONS` SHALL carry visible candidates; `ESCALATE_TO_PLANNER` SHALL carry a record and explanation.

#### Scenario: SELECT with complete parameters
- **WHEN** a single intent is detected with all required parameters
- **THEN** `MatchDecision.decision_type=SELECT` with the resolved `capabilityId` and parameters

#### Scenario: CLARIFY on missing parameter
- **WHEN** a single intent is detected but a required parameter is missing
- **THEN** `MatchDecision.decision_type=CLARIFY` with the missing parameter list and clarification text

#### Scenario: REJECT on technical override
- **WHEN** the utterance contains `rfcName` or OData override
- **THEN** `MatchDecision.decision_type=REJECT` with `error_type=UNSUPPORTED_RFC_NAME`

### Requirement: Multi-intent and ambiguity detection
The system SHALL scan all registered capability intent signals in an utterance, not first-match only. When more than one capability intent is detected, the system SHALL emit `ESCALATE_TO_PLANNER`. When multiple candidates are plausible for a single ambiguous goal, the system SHALL emit `SHOW_OPTIONS` with the visible candidate set.

#### Scenario: Multi-intent escalates
- **WHEN** the utterance matches two or more capability intent signals
- **THEN** `MatchDecision.decision_type=ESCALATE_TO_PLANNER` with record and explanation

#### Scenario: Keyword ambiguity shows options
- **WHEN** the utterance weakly matches multiple capability keyword sets without a clear primary intent (keyword ambiguity)
- **THEN** `MatchDecision.decision_type=SHOW_OPTIONS` with the visible candidate list
- **AND** the ambiguity threshold is anchored by matcher Eval cases

### Requirement: Visibility pre-filter
The system SHALL apply a visibility pre-filter to candidate `CapabilityCard`s before `SHOW_OPTIONS`. Candidates with `governance.sideEffect=none` and `dataClassification=internal` SHALL be visible by default; write-capability and restricted-data candidates SHALL be visible in dry-run but not executable until S3 gates are met.

#### Scenario: Read capability visible
- **WHEN** a candidate has `sideEffect=none` and `dataClassification=internal`
- **THEN** the candidate is included in the visible candidate set

#### Scenario: Write capability visible in dry-run only
- **WHEN** a candidate has `sideEffect=sap_write`
- **THEN** the candidate is visible in dry-run and SHOW_OPTIONS but not executable until S3 gates are met

### Requirement: Matcher Eval exit criteria
The system SHALL provide a matcher Eval covering five decision classes: `SELECT` (single intent, complete params), `CLARIFY` (missing params), `REJECT` (technical override), `SHOW_OPTIONS` (ambiguity), `ESCALATE_TO_PLANNER` (multi-goal). A `false SELECT` (multi-goal silently reduced to single `SELECT`) SHALL be a regression failure.

#### Scenario: All five decision classes covered
- **WHEN** the matcher Eval runs
- **THEN** cases cover SELECT, CLARIFY, REJECT, SHOW_OPTIONS, ESCALATE_TO_PLANNER
- **AND** a multi-goal-utterance-as-SELECT case fails the regression

```

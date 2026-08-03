# Comet Design Handoff

- Change: sap-nexus-semantic-plan-authoring-v2
- Phase: design
- Mode: compact
- Context hash: cb2cf8221e2be0f5fcf4840c89bd7eb390326f804859c8895c0882f9a0d9a5b7

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/sap-nexus-semantic-plan-authoring-v2/proposal.md

- Source: openspec/changes/sap-nexus-semantic-plan-authoring-v2/proposal.md
- Lines: 1-30
- SHA256: e522f7d270dcc29e66bd0600abe4d480326174e26ddd83efcd5eada5c85ca738

```md
## Why

Runbook 13-14 已冻结 `IntentEnvelope` / `MatchDecision` / `RegistrySnapshot` 治理上下文，但当前 PlanGraph v1 编译器（S2-B dry-run）只绑定 `goalConstraint` 参数源、不 author 任何 edge、不区分 READ/WRITE 分区、且校验失败时静默返回 `None` 降级。完整 Agent 链路（Runbook 16 READ executor / 17 OutputProjection / 18 Recommendation）需要一个可执行前验证的 PlanGraph：完整参数 provenance、能力关系、READ/WRITE 分区、结构化失败。本次把 advisory `GoalSpec`/`PlanDraft` 编译为 PlanGraph v2，填补 dry-run 到 execution 之间的契约缺口。

## What Changes

- 新增 PlanGraph v2 schema（`planGraphVersion: 2`），含 `readPartition` / `actionPartition` / `projectionRef` / `ruleSetRefs` 字段；参数源在 v1 三种（`goalConstraint` / `literal` / `factField`）之上新增 `registeredDefault`
- 新增 v2 deterministic compiler：author `literal` / `factField` / `registeredDefault` 参数源、`data` / `dependency` edges、READ/WRITE 节点分区
- 新增 v2 validator：复用并扩展 S1 校验逻辑（provenance / edges / cycle / topological order / governance / snapshot），新增 partition 隔离校验（Action 节点不得混入 `readPartition`）、`projectionRef` / `ruleSetRefs` 引用须来自 snapshot（本期为预留空字段）
- 校验失败保留结构化 gaps / failures（含明确 issues 与 error code），不再静默 `None`
- 双版本并存：v1 schema / compiler / validator / fixtures 保持不变，v2 并列新增；v1 dry-run 链路零回归
- 编译器输入契约不变：仍以 `EscalationHandoff` + `RegistrySnapshot` + `SemanticSourceDocuments` 为入口，不直接消费 `IntentEnvelope`

## Capabilities

### New Capabilities

- `semantic-plan-authoring-v2`: PlanGraph v2 schema、deterministic compiler、validator；4 种参数 provenance（`goalConstraint` / `literal` / `factField` / `registeredDefault`）、`data` / `dependency` 关系展开、READ/WRITE 分区、预留 `projectionRef` / `ruleSetRefs`、结构化 gaps / failures；fail-closed 覆盖 unknown capability / relation、cycle、type mismatch、missing source、snapshot drift、Action-in-READ；不执行 Gateway / SAP

### Modified Capabilities

<!-- 双版本并存：v1 的 semantic-planning-foundation 与 planner-dry-run specs 保持不变，v2 作为新 capability 并列新增。 -->

## Impact

- 代码：`agent/sap_nexus_agent/semantic_planning/`（新增 v2 schema / validator）、`agent/sap_nexus_agent/planner/`（新增 v2 compiler）；v1 模块（`contracts.py` / `validation.py` / `graph.py` / `plan_compiler.py` / `goal_spec.py` / `plan_draft.py` / `handoff.py`）不动
- schema：新增 `schemas/plan-graph-v2.schema.json`；v1 `schemas/plan-graph.schema.json` 不变
- 测试：新增 v2 compiler / validator 契约测试与 fixtures；v1 测试（`test_semantic_planning_contract.py` / `test_planner_plan_compiler.py`）保持通过
- 依赖：消费 Runbook 13 `GovernedContext` / `SnapshotLease` / `PlannerFailure`、Runbook 14 `EscalationHandoff`；不触 Gateway / executor
- 下游：为 Runbook 16（READ executor）提供已验证 PlanGraph v2；`projectionRef` / `ruleSetRefs` 为 Runbook 17 / 18 预留

```

## openspec/changes/sap-nexus-semantic-plan-authoring-v2/design.md

- Source: openspec/changes/sap-nexus-semantic-plan-authoring-v2/design.md
- Lines: 1-85
- SHA256: d6090ef35306e72c5fdeb0c69359f15fcbc3418cda3edf2326f2c096674b6ae5

[TRUNCATED]

```md
## Context

Runbook 13-14 已交付治理上下文：`IntentEnvelope`（LLM-first intent）、`MatchDecision` 五态（含 `ESCALATE_TO_PLANNER` -> `EscalationHandoff`）、`GovernedContext` / `SnapshotLease` / `VisibleCapabilitySet` / `PlannerFailure`（同 snapshotId 绑定 + 结构化 fail-closed）。

当前 PlanGraph v1（S1 `semantic-planning-foundation` + S2-B `planner-dry-run`）现状：
- v1 schema：`planGraphVersion:1`，nodes / edges / topologicalOrder / goalOutputs；参数源 `goalConstraint` / `literal` / `factField`；edge `data` / `dependency`
- v1 compiler（`compile_dry_run`）：**只** author `goalConstraint` 源；**不** author 任何 edge；不 author `literal` / `factField`；未绑定参数记为 `missing_parameter` gap
- v1 validator（`validate_plan_graph`）：已完备——provenance / edges（data+dependency）/ cycle / topological order / governance（READ_ONLY 拒 Action）/ snapshot / goalOutputs 全覆盖；**但 compiler 没产出 edge / literal / factField，故这些校验路径未被实战触发**
- 校验失败时 dry-run 返回 `invalid_plan_graph` flag，但 `GovernedContext` 之前存在 `except: return None` 静默降级（Runbook 13 已用 `PlannerFailure` 收敛 source load / snapshot drift；编译期 invalid 仍需结构化）

约束：不执行 Gateway / SAP；LLM 不得创建 capability / relation / FactType / projection / RuleSet；所有 edge / projection / RuleSet 必须来自 snapshot。

## Goals / Non-Goals

**Goals:**
- PlanGraph v2 schema 表达完整参数 provenance（4 源）、能力关系（data/dependency edges）、READ/WRITE 分区、projection/rule 引用（预留）
- v2 deterministic compiler 产出 v2 PlanGraph，复用并扩展 S1 校验
- 校验失败保留结构化 gaps / failures（明确 issues + error code），不返回 `None`
- 双版本并存：v1 零回归，v2 并列新增
- fail-closed 覆盖 6 类 bad case（unknown capability/relation、cycle、type mismatch、missing source、snapshot drift、Action-in-READ）

**Non-Goals:**
- 不执行 Gateway / SAP；不调度节点；不计算建议；不批准 / 执行 Action；不做动态 replan
- 不实现 OutputProjection（Runbook 17）与 Recommendation / RuleSet 执行（Runbook 18）
- 不直接消费 `IntentEnvelope`（仍以 `EscalationHandoff` 为入口）
- 不 rewire 生产 orchestrator（v2 契约交付即可，orchestrator 切换 v2 留给 Runbook 16 消费时）
- 不实现 projection / RuleSet 注册表（`projectionRef` / `ruleSetRefs` 本期为预留空字段）

## Decisions

### D1: 双版本并存（v1 不动，v2 并列新增）
**选择**：保留 v1 schema / compiler / validator / fixtures 不变，新增 `plan-graph-v2.schema.json` + v2 compiler + v2 validator。
**理由**：v1 有大量 fixtures 与契约测试（`test_semantic_planning_contract.py` 120KB），演进单一 schema 风险高；双版本并存实现零回归，v2 可独立验证。
**备选**：v2 取代 v1（拒绝，回归面大）/ v2 单一 schema + 迁移器（拒绝，需改写 v1 测试）。后续 runbook 消费 v2 后再评估 v1 退役。

### D2: 编译器输入仍为 `EscalationHandoff`
**选择**：v2 compiler 入口 = `EscalationHandoff` + `RegistrySnapshot` + `SemanticSourceDocuments`，与现有 `compile_dry_run_from_handoff` 一致。
**理由**：`IntentEnvelope` 的 `user_constraints` / `ambiguities` 已由 matcher 投影进 `handoff.matched_intents.parameters`；`ambiguities` 喂 CLARIFY / SHOW_OPTIONS 而非 planner。扩大输入会改 `handoff.py` 与 orchestrator 接线，超出 runbook 范围。
**备选**：扩大到 `IntentEnvelope`（拒绝，scope creep）。

### D3: `projectionRef` / `ruleSetRefs` 预留空字段
**选择**：v2 schema 含 `projectionRef` / `ruleSetRefs` 字段，本期恒为空；校验规则 = "若非空则引用必须来自 snapshot"。
**理由**：projection / RuleSet 注册表属 Runbook 17 / 18 范围；本期引入注册表会蔓延到 Runbook 13 snapshot 契约。预留字段满足 "dry-run 可展示" 验收且前向兼容。
**备选**：本期引入最小注册表（拒绝，scope 蔓延）/ 暂不纳入（拒绝，与 runbook §3 不符）。

### D4: 参数源新增 `registeredDefault`（第 4 源）
**选择**：v2 schema 参数源在 v1 三种之上新增 `registeredDefault`，来源为 capability input 的 registered default（来自 snapshot 内 capability 定义，非 LLM）。
**理由**：runbook §3 明确参数来源只能 4 选 1；v1 缺 default 导致可选参数无默认值时被误判 missing。
**备选**：延后 default（拒绝，runbook 明确要求）。

### D5: v2 validator 复用并扩展 S1
**选择**：v2 validator 复用 S1 `validate_plan_graph` 的 provenance / edge / cycle / topo / governance / snapshot / goalOutputs 校验原语，新增 partition 隔离与 ref 校验。
**理由**：S1 validator 已支持 `literal` / `factField` / edge 校验（compiler 没产出而已）；复用避免契约漂移。
**备选**：v2 validator 从零实现（拒绝，重复 + 漂移风险）。

### D6: 结构化 gaps / failures，不返回 `None`
**选择**：v2 编译失败返回结构化 gaps / failures（含 issues + error code），遵循 Runbook 13 `PlannerFailure` 模式。
**理由**：runbook §3 明确 "validation failure 必须保留明确 issues，不能只返回 None"；Runbook 13 已为 source load / snapshot drift 建立 `PlannerFailure`，编译期 invalid 同样需结构化。
**备选**：静默 `None`（拒绝，runbook 明确禁止）。

## Risks / Trade-offs

- **[v1/v2 validator 逻辑重复]** -> 复用 S1 校验原语（函数级 import），v2 仅叠加 partition / ref 校验，避免漂移
- **[双版本并存维护成本]** -> v1 冻结（不接收新需求），v2 为唯一演进面；v1 退役时机交给后续 runbook
- **[预留字段未来 schema 迁移]** -> `projectionRef` / `ruleSetRefs` 用 schema 版本（`planGraphVersion:2`）隔离；Runbook 17 / 18 落地时若需非空，再评估 v2.1 或 v3
- **[双 READ 场景无 edge]** -> 当前 `MM.Inventory.GetAvailability` + `MM.PurchaseOrder.GetList` 无 `dependsOn` 关系，v2 双 READ 场景可能空 edges（两独立 READ 节点入 `readPartition`）；edge authoring 由 factField 绑定与 dependsOn 关系驱动，非强制非空
- **[registeredDefault 来源未定]** -> Design Doc 须确定 default 在 capability input 的字段名与 snapshot 纳入方式（见 Open Questions）

## Migration Plan

- 双版本并存，无需迁移：v1 schema / compiler / validator / fixtures 原样保留；v2 并列新增
- v1 测试（`test_semantic_planning_contract.py` / `test_planner_plan_compiler.py`）保持通过
- v2 新增独立契约测试与 fixtures
- 生产 orchestrator 切换 v2 延后至 Runbook 16 消费 PlanGraph v2 时

## Open Questions

> 以下交由 design 阶段 Design Doc 细化（comet-open 不在此定稿）：

1. `readPartition` / `actionPartition` 字段形状：nodeId 列表 vs 带序执行集（含 ordering）

```

Full source: openspec/changes/sap-nexus-semantic-plan-authoring-v2/design.md

## openspec/changes/sap-nexus-semantic-plan-authoring-v2/tasks.md

- Source: openspec/changes/sap-nexus-semantic-plan-authoring-v2/tasks.md
- Lines: 1-39
- SHA256: b61f94cd3a6260fbb9995b80a32c20c69404f3ed09c4d76d8681687040177304

```md
## 1. PlanGraph v2 Schema

- [ ] 1.1 新建 `schemas/plan-graph-v2.schema.json`，含 `planGraphVersion: 2`、`readPartition`、`actionPartition`、`projectionRef`、`ruleSetRefs`，以及 `registeredDefault` 参数源种类（v1 的 node/edge/topologicalOrder/goalOutputs 字段保留）
- [ ] 1.2 验证 v1 `schemas/plan-graph.schema.json` 未改动，且 v1 fixtures 仍能通过其校验

## 2. v2 契约与校验器

- [ ] 2.1 在 `semantic_planning` 中新增 v2 PlanGraph 契约类型（分区结构 + `registeredDefault` 源种类）
- [ ] 2.2 实现 v2 validator，复用 S1 `validate_plan_graph` 校验原语（provenance、edges、cycle、topological order、governance、snapshot、goalOutputs）
- [ ] 2.3 新增分区隔离校验：Action / 非 read-only 节点 MUST NOT 出现在 `readPartition`
- [ ] 2.4 新增 `projectionRef` / `ruleSetRefs` 引用校验：非空时引用实体 MUST 来自 snapshot；为空时通过（本期默认）

## 3. v2 确定性编译器

- [ ] 3.1 实现 v2 compiler 入口，消费 `EscalationHandoff` + `RegistrySnapshot` + `SemanticSourceDocuments`，绑定与 matcher 相同的 `snapshotId`
- [ ] 3.2 在 `goalConstraint` 之外，author `literal`、`factField`、`registeredDefault` 参数源
- [ ] 3.3 为 `factField` 绑定 author `data` edge，为 snapshot `dependsOn` 关系 author `dependency` edge
- [ ] 3.4 将节点分区到 `readPartition`（READ-only）与 `actionPartition`（Action / write，`requiresApproval=true`）
- [ ] 3.5 编译失败时返回结构化 gaps / failures，含明确 issues（error code、JSON Pointer path、message）；不得返回 `None`
- [ ] 3.6 snapshot 漂移时返回结构化 `PlannerFailure(SNAPSHOT_DRIFT)`（复用 Runbook 13 模式）

## 4. v2 dry-run 输出

- [ ] 4.1 暴露 v2 dry-run 输出，携带 plan、gaps、governance、`projectionRef`、`ruleSetRefs`、`snapshotId`
- [ ] 4.2 验证 v2 dry-run 不调用 Gateway validate / execute，不调用 SAP

## 5. 测试与 fixtures

- [ ] 5.1 双 READ fixture（`MM.Inventory.GetAvailability` + `MM.PurchaseOrder.GetList`）生成稳定可重复的 PlanGraph v2（`readPartition` 含两节点，`actionPartition` 空，refs 空）
- [ ] 5.2 bad-case 测试：unknown capability、unknown / inconsistent relation、cycle、type mismatch、missing source、snapshot drift、Action-in-READ，全部 fail-closed 并带结构化 issues
- [ ] 5.3 dry-run 输出测试：plan / gaps / governance / `projectionRef` / `ruleSetRefs` 齐全，无 Gateway 调用
- [ ] 5.4 v1 回归：`test_semantic_planning_contract.py` 与 `test_planner_plan_compiler.py` 不改动仍通过

## 6. 验证与文档

- [ ] 6.1 `pytest agent/tests/test_semantic_planning_contract.py agent/tests/test_planner_plan_compiler.py`（+ 新 v2 测试）全绿
- [ ] 6.2 `scripts/verify-agent-callplan-evidence.sh` 通过
- [ ] 6.3 `openspec validate --all --strict` 通过
- [ ] 6.4 更新 Runbook 15 状态 / 版本 + `docs/runbooks/README.md` + roadmap row 26

```

## openspec/changes/sap-nexus-semantic-plan-authoring-v2/specs/semantic-plan-authoring-v2/spec.md

- Source: openspec/changes/sap-nexus-semantic-plan-authoring-v2/specs/semantic-plan-authoring-v2/spec.md
- Lines: 1-142
- SHA256: fce49f74912ea15310a11bad0f3a7a8c4c342101fc63a049856598b651490fd2

[TRUNCATED]

```md
## ADDED Requirements

### Requirement: PlanGraph v2 schema expresses partition, provenance, and reserved refs

The system SHALL define a PlanGraph v2 schema (`planGraphVersion: 2`) that carries `readPartition`, `actionPartition`, `projectionRef`, and `ruleSetRefs`, alongside the v1 `nodes` / `edges` / `topologicalOrder` / `goalOutputs` structure. Parameter sources SHALL be exactly one of `goalConstraint`, `literal`, `factField`, or `registeredDefault`. The v1 schema (`planGraphVersion: 1`) SHALL remain unchanged and v1 fixtures SHALL continue to validate against it.

#### Scenario: Dual-READ plan carries read partition

- **WHEN** the v2 compiler compiles a dual-READ goal referencing `MM.Inventory.GetAvailability` and `MM.PurchaseOrder.GetList`
- **THEN** the PlanGraph v2 carries `readPartition` containing both READ node ids and an empty `actionPartition`
- **AND** `projectionRef` and `ruleSetRefs` are empty reserved fields

#### Scenario: v1 schema remains unchanged

- **WHEN** v1 fixtures and the v1 validator run
- **THEN** the v1 `plan-graph.schema.json` (`planGraphVersion: 1`) and v1 validator behave identically to before this change
- **AND** v1 tests pass without modification

### Requirement: v2 compiler authors full parameter provenance and relations

The system SHALL provide a deterministic v2 compiler that compiles `GoalSpec` / `PlanDraft` plus the `RegistrySnapshot`-bound `SemanticSourceDocuments` into a PlanGraph v2. The compiler SHALL author `literal` and `factField` parameter sources in addition to `goalConstraint`, SHALL author `data` and `dependency` edges derived from the snapshot, and SHALL partition nodes into `readPartition` / `actionPartition`. The `registeredDefault` source kind is defined in the v2 schema as part of the 4-source closed set but SHALL NOT be authored this phase (no capability input declares a registered default); it is reserved for future activation. The compiler MUST NOT call the LLM, the Gateway, or SAP.

#### Scenario: Identifier input bound by goalConstraint

- **WHEN** a required identifier input matches a GoalConstraint by name and semantic type
- **THEN** the v2 compiler authors a `goalConstraint` parameter source

#### Scenario: Fact input bound by factField produces a data edge

- **WHEN** a required fact-bound input is bound by a `factField` source from a producer node
- **THEN** the v2 compiler authors a `factField` parameter source and a matching `data` edge

#### Scenario: registeredDefault source is reserved this phase

- **WHEN** the v2 schema defines `registeredDefault` as part of the 4-source closed set
- **THEN** the v2 compiler does not author a `registeredDefault` source this phase (no capability input declares a registered default)
- **AND** the source kind is reserved for future activation when capability inputs declare registered defaults

#### Scenario: Dependency relation produces a dependency edge

- **WHEN** the snapshot relation catalog declares a `dependsOn` relation between two capabilities present in the plan
- **THEN** the v2 compiler authors a `dependency` edge from prerequisite to dependent

#### Scenario: Compiler is deterministic and non-executing

- **WHEN** the v2 compiler runs on the same GoalSpec and snapshot repeatedly
- **THEN** it returns the same PlanGraph v2
- **AND** it calls no LLM, Gateway validate, Gateway execute, or SAP

### Requirement: READ/WRITE partition isolates Action nodes

The system SHALL partition PlanGraph v2 nodes so that Action nodes and any capability whose governance is not read-only appear only in `actionPartition` with `requiresApproval=true`, and MUST NOT appear in `readPartition`. READ-only nodes appear only in `readPartition`.

#### Scenario: Action node isolated in action partition

- **WHEN** a plan includes a write or Action capability node
- **THEN** the node appears in `actionPartition` with `requiresApproval=true`
- **AND** the node does not appear in `readPartition`

### Requirement: v2 validator reuses S1 validation and adds partition and ref checks

The system SHALL validate PlanGraph v2 by reusing the S1 `semantic-planning-foundation` validation (provenance, edges, cycle, topological order, governance, snapshot, goalOutputs) and adding partition isolation and projection/rule ref checks. `projectionRef` and `ruleSetRefs`, when non-empty, SHALL reference entities present in the snapshot; when empty (this phase's default) they SHALL pass.

#### Scenario: Action-in-READ fails closed

- **WHEN** a PlanGraph v2 places an Action or non-read-only node in `readPartition`
- **THEN** validation reports a partition governance violation and the plan is invalid

#### Scenario: Unknown capability fails closed

- **WHEN** a PlanGraph v2 node references a capability not present in the snapshot
- **THEN** validation reports `UNKNOWN_CAPABILITY` and the plan is invalid

#### Scenario: Unknown or inconsistent relation fails closed

- **WHEN** a PlanGraph v2 dependency edge does not match an authored `dependsOn` relation in the snapshot
- **THEN** validation reports `EDGE_INCONSISTENT` and the plan is invalid

#### Scenario: Cycle fails closed


```

Full source: openspec/changes/sap-nexus-semantic-plan-authoring-v2/specs/semantic-plan-authoring-v2/spec.md

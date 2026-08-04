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

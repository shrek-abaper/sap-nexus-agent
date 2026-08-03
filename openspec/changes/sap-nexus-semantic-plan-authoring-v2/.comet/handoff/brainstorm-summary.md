# Brainstorm Summary

- Change: sap-nexus-semantic-plan-authoring-v2
- Date: 2026-08-03

## 确认的技术方案

### 模块布局（双版本并存，v1 冻结）
- v2 schema：`schemas/plan-graph-v2.schema.json`（新建，`planGraphVersion: 2`）
- v2 validator：`semantic_planning/` 下新建 v2 校验模块，复用 S1 `validate_plan_graph` 原语（provenance/edges/cycle/topo/governance/snapshot/goalOutputs），叠加 partition 隔离 + ref 校验
- v2 compiler：`planner/plan_compiler_v2.py`（新建），消费 `EscalationHandoff` + `RegistrySnapshot` + `SemanticSourceDocuments`
- v2 result：新 `PlanCompileResult` dataclass（携带 plan_graph_v2 / gaps / governance / projectionRef / ruleSetRefs / snapshotId）；v1 `DryRunResult` 不动
- v1 模块（`contracts.py` / `validation.py` / `graph.py` / `plan_compiler.py` / `goal_spec.py` / `plan_draft.py` / `handoff.py` / `capability_card.py`）零改动

### PlanGraph v2 schema
- `planGraphVersion: 2`，保留 v1 字段：planId / goalId / executionMode / snapshotId / nodes / edges / topologicalOrder / goalOutputs
- 新增：`readPartition`（nodeId 列表，按 topologicalOrder 排序）、`actionPartition`（同）、`projectionRef`（本期空）、`ruleSetRefs`（本期空）
- 参数源 4 源闭集：`goalConstraint` / `literal` / `factField` / `registeredDefault`（registeredDefault 本期 schema 定义但不产出）

### v2 compiler 行为
- 参数源：author `goalConstraint`（identifier 输入 + GoalConstraint 名字+semanticType 匹配）、`literal`（utterance 抽取值）、`factField`（fact 输入绑定生产者字段）
- edges：每个 `factField` 绑定 → author 一条 `data` edge（validator 要求一一对应）；snapshot 每个 `dependsOn` 关系（两端在 plan 内）→ author 一条 `dependency` edge（prerequisite→dependent）
- 分区：READ-only 节点入 `readPartition`；Action / 非 read-only 节点入 `actionPartition`（`requiresApproval=true`），不得入 `readPartition`
- registeredDefault：本期不产出（无 input 声明 default）
- 确定性：无 LLM / Gateway / SAP

### v2 validator 行为
- 复用 S1 校验原语（import，不重写）
- 新增 partition 校验：`readPartition` ∪ `actionPartition` = 全部节点，无交集；Action / 非 read-only 节点不得在 `readPartition`（否则 partition governance violation）
- 新增 ref 校验：`projectionRef` / `ruleSetRefs` 非空时引用须来自 snapshot；空则通过
- fail-closed：UNKNOWN_CAPABILITY / EDGE_INCONSISTENT / DEPENDENCY_CYCLE / FACT_TYPE_MISMATCH / PARAMETER_SOURCE_MISSING / SNAPSHOT_MISMATCH / Action-in-READ

### 结构化 gaps/failures
- 编译/校验失败返回 `PlanCompileResult` 携带结构化 issues（error code + JSON Pointer path + message），不返回 `None`
- snapshot 漂移返回 `PlannerFailure(SNAPSHOT_DRIFT)`（复用 Runbook 13 模式）

## 关键取舍与风险

- **[registeredDefault 预留]** 本期 schema 定义源种类但不产出；未来给 ioField 加 defaultValue 后 compiler 补产出。风险：spec 场景需 Spec Patch 改为 reserved。
- **[双版本并存维护成本]** v1 冻结，v2 唯一演进面；v1 退役时机交后续 runbook。
- **[v2 validator 复用 S1]** import S1 校验函数，避免漂移；partition/ref 为叠加层。
- **[双 READ fixture 空 edges]** 真实反映 Inventory+PO 无 dependsOn；data edge 路径由独立 factField fixture 覆盖。
- **[projectionRef/ruleSetRefs 预留]** 空 fields，前向兼容 Runbook 17/18。

## 测试策略

- 双 READ fixture：`MM.Inventory.GetAvailability` + `MM.PurchaseOrder.GetList` → 稳定可重复 PlanGraph v2（readPartition 含两节点，actionPartition 空，edges 空，refs 空）
- 独立 factField fixture：构造 fact 输入绑定生产者字段 → 覆盖 data edge authoring + 校验
- bad-case 测试：unknown capability、unknown/inconsistent relation、cycle、type mismatch、missing source、snapshot drift、Action-in-READ，全部 fail-closed + 结构化 issues
- dry-run 输出测试：plan/gaps/governance/projectionRef/ruleSetRefs 齐全，无 Gateway 调用
- v1 回归：`test_semantic_planning_contract.py` + `test_planner_plan_compiler.py` 不改仍通过
- 新增 v2 测试文件（如 `test_planner_plan_compiler_v2.py` + `test_semantic_planning_v2.py`）

## Spec Patch

- `specs/semantic-plan-authoring-v2/spec.md`：将 "Optional input uses registered default" 场景改为反映 registeredDefault 本期为 reserved 源种类（schema 定义，compiler 本期不产出）；保留 "Parameter sources SHALL be exactly one of 4 kinds" 闭集陈述。

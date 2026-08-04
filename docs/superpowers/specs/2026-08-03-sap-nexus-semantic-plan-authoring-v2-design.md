---
comet_change: sap-nexus-semantic-plan-authoring-v2
role: technical-design
canonical_spec: openspec
archived-with: 2026-08-04-sap-nexus-semantic-plan-authoring-v2
status: final
---

# PlanGraph v2 技术设计（semantic-plan-authoring-v2）

> 本 Design Doc 深化 open 阶段 `design.md` 的高层框架，给出 PlanGraph v2 的详细实现设计、技术风险、测试策略与边界条件。OpenSpec delta spec（`specs/semantic-plan-authoring-v2/spec.md`）是上游事实源；本文不重写需求，仅细化实现。

## 1. Context（现状与缺口）

Runbook 13-14 已冻结治理上下文：`IntentEnvelope`、`MatchDecision`（含 `EscalationHandoff`）、`GovernedContext`/`SnapshotLease`/`VisibleCapabilitySet`/`PlannerFailure`。

PlanGraph v1 现状（代码事实）：
- **schema**（`schemas/plan-graph.schema.json`，`planGraphVersion:1`）：nodes/edges/topologicalOrder/goalOutputs；参数源 `goalConstraint`/`literal`/`factField`；edge `data`/`dependency`。
- **compiler**（`planner/plan_compiler.py::compile_dry_run`）：**只** author `goalConstraint` 源；**不** author 任何 edge；不 author `literal`/`factField`；未绑定参数记 `missing_parameter` gap。
- **validator**（`semantic_planning/validation.py::validate_plan_graph`）：已完备--provenance、edges（data+dependency，含一一对应校验）、cycle、topological order、governance（READ_ONLY 拒 Action）、snapshot、goalOutputs。**S1 validator 已要求 factField 源必须有一条匹配 data edge、dependsOn 关系必须有一条 dependency edge**，但 v1 compiler 没产出这些，故校验路径未被实战触发。
- **失败语义**：dry-run 校验失败返回 `invalid_plan_graph` flag；Runbook 13 已用 `PlannerFailure` 收敛 source load/snapshot drift，但编译期 invalid 仍需结构化。

缺口：v1 compiler 产出不全（无 literal/factField/edge/分区），无法支撑 Runbook 16 READ executor 消费；projection/rule 引用与 READ/WRITE 分区缺失。

## 2. Goals / Non-Goals

**Goals**
- PlanGraph v2 schema 表达 4 源 provenance、data/dependency edges、READ/WRITE 分区、projection/rule 引用（预留）。
- v2 compiler 产出完整 v2 PlanGraph，复用并扩展 S1 校验。
- 校验失败保留结构化 gaps/failures（不返回 `None`）。
- 双版本并存：v1 零回归。
- 6 类 bad case fail-closed。

**Non-Goals**
- 不执行 Gateway/SAP；不调度节点；不计算建议；不批准/执行 Action；不动态 replan。
- 不实现 OutputProjection（R17）与 Recommendation/RuleSet 执行（R18）。
- 不直接消费 `IntentEnvelope`（仍以 `EscalationHandoff` 为入口）。
- 不 rewire 生产 orchestrator（v2 契约交付即可）。
- 不实现 projection/RuleSet 注册表（`projectionRef`/`ruleSetRefs` 本期空）。
- 不给 capability input 加 `defaultValue`（`registeredDefault` 本期 schema 定义但不产出）。

## 3. 架构决策（已确认）

| 决策 | 选择 | 理由 |
|---|---|---|
| D1 版本策略 | 双版本并存（v1 冻结，v2 并列） | v1 fixtures/测试量大；零回归；v2 独立验证 |
| D2 编译器输入 | `EscalationHandoff`+`RegistrySnapshot`+`SemanticSourceDocuments` | IntentEnvelope 已由 matcher 投影进 handoff |
| D3 projection/RuleSet | 预留空字段，非空须来自 snapshot | 注册表属 R17/18，不蔓延 |
| D4 registeredDefault | 本期 schema 定义源种类，compiler 不产出 | capability input 无 defaultValue；与 D3 一致预留 |
| D5 v2 validator | 复用 S1 校验原语（import），叠加 partition+ref | S1 已支持 literal/factField/edge 校验 |
| D6 失败语义 | 结构化 gaps/failures，不返回 None | runbook §3 明确要求 |
| D7 分区形状 | nodeId 列表，按 topologicalOrder 排序 | 分区仅表归属，ordering 由 topologicalOrder 承担；调度属 R16 |
| D8 模块布局 | 新建 v2 模块 + 新 `PlanCompileResult` | v1 模块零改动，隔离干净 |

## 4. 详细设计

### 4.1 PlanGraph v2 Schema（`schemas/plan-graph-v2.schema.json`）

```jsonc
{
  "planGraphVersion": 2,
  "planId": "string",
  "goalId": "string",
  "executionMode": "PLAN_ONLY|READ_ONLY",
  "snapshotId": "sha256:...",
  "nodes": [{ "nodeId", "capabilityId", "parameterBindings", "producesFactTypes", "governance" }],
  "edges": [{ "edgeId", "kind": "data"|"dependency", "fromNodeId", "toNodeId", "factTypeId"? }],
  "topologicalOrder": ["nodeId"],
  "goalOutputs": [{ "factTypeId", "producerNodeId" }],
  "readPartition": ["nodeId"],      // 新增；按 topologicalOrder 排序
  "actionPartition": ["nodeId"],    // 新增；Action/非read-only 节点
  "projectionRef": [],              // 新增；本期空
  "ruleSetRefs": []                 // 新增；本期空
}
```
- node/governance/edge/parameterBinding 结构与 v1 一致（复用 v1 `$defs` 形状）。
- `parameterSource` oneOf：`goalConstraint` / `literal` / `factField` / `registeredDefault`（新增第 4 种；本期 compiler 不产出，但 schema 闭集含它）。
- `registeredDefault` source 形状：`{ "kind": "registeredDefault", "parameterName", "semanticType", "value" }`（本期 reserved，定义形状供未来）。
- `readPartition`/`actionPartition`：`array<string>`，`uniqueItems`，并集 = 全部 nodeId，无交集。
- `projectionRef`/`ruleSetRefs`：`array`，本期 `maxItems: 0` 不强制（留前向兼容）；validator 校验非空须来自 snapshot。

### 4.2 v2 Compiler（`planner/plan_compiler_v2.py`）

入口：`compile_plan_v2(handoff: EscalationHandoff, snapshot: RegistrySnapshot, sources: SemanticSourceDocuments) -> PlanCompileResult`

复用：`discover_cards`、`build_goal_spec`（或 v2 等价 GoalSpec 构造）、`CapabilityCard`。

**参数源 authoring 规则**（按输入 bindingKind）：
- `identifier` 输入：
  - 有匹配 GoalConstraint（name + semanticType）-> `goalConstraint` 源
  - 否则有 handoff 参数值（matched_intents.parameters）-> `literal` 源（semanticType 从 input descriptor 取，校验类型一致）
  - 否则 required -> `missing_parameter` gap；optional -> 不绑定
- `fact` 输入：
  - 有生产者节点产出该 factType 的字段 -> `factField` 源（producerNodeId/factTypeId/field）+ author 一条 `data` edge（fromNodeId=producer, toNodeId=consumer, factTypeId）
  - 否则 required -> `missing_parameter` gap
- `registeredDefault`：**本期不产出**（无 input 声明 default）。

**Edge authoring**：
- `data` edge：每个 `factField` 源产出一条 data edge（S1 validator 要求一一对应）。
- `dependency` edge：snapshot `relations` 中 `dependsOn` 关系，若两端 capability 都在 plan 内 -> author 一条 `dependency` edge（fromNodeId=prerequisite, toNodeId=dependent）。S1 validator 要求每个 expected dependency 恰有一条 edge。

**分区**：
- 节点 governance `capabilityKind=Function` + `sideEffect in {none,read}` + `requiresApproval=false` -> `readPartition`
- 否则（Action / `sideEffect in {write,sap_write}` / `requiresApproval=true`）-> `actionPartition`，node governance `requiresApproval=true`
- 两分区均按 topologicalOrder 排序。

**topologicalOrder**：由 data/dependency edges 拓扑排序得出（复用 S1 校验逻辑的期望）；无 edge 时按 nodeId 排序（确定性）。

**确定性**：无 LLM/Gateway/SAP；无随机；同输入同输出。

**失败语义**：
- 编译后调用 v2 validator；失败时 `PlanCompileResult` 仍返回 `plan_graph`（部分图）+ 结构化 gaps/flags（含 issues），**不返回 None**。
- snapshot 漂移（handoff.snapshot_id != lease.snapshot_id）-> 抛 `PlannerFailure(SNAPSHOT_DRIFT)`（复用 Runbook 13）。

### 4.3 v2 Validator（`semantic_planning/validation_v2.py`）

入口：`validate_plan_graph_v2(graph, snapshot, goal_spec, plan_graph_v2) -> PlanValidationReport`

**复用 S1**（import `validation.py` 内部函数，不重写）：
- `_validate_plan_shape`（v2 schema 用 `plan-graph-v2.schema.json`）
- `_validate_snapshot_and_goal_identity`
- `_validate_nodes_and_projections`
- `_validate_parameter_sources`（含 4 源；`registeredDefault` 本期校验：若出现，semanticType 须匹配 input）
- `_validate_edges`（data/dependency + cycle）
- `_validate_topological_order`
- `_validate_plan_governance`
- `_validate_goal_outputs`

**v2 叠加层**：
- `_validate_partitions`：`set(readPartition) ∪ set(actionPartition) == set(nodeIds)`；`readPartition ∩ actionPartition == ∅`；`actionPartition` 中节点 governance 须为 Action/非read-only；`readPartition` 中节点须为 read-only（否则 partition governance violation，fail-closed）。
- `_validate_refs`：`projectionRef`/`ruleSetRefs` 非空时，每个引用须能在 snapshot sources 中找到；空通过。

**复用策略**：S1 的 `validate_plan_graph` 是面向 v1 的入口；v2 不直接调用它（它会用 v1 schema 拒绝 v2 字段），而是 import 其内部 `_validate_*` 函数组合 + 叠加。需确认这些内部函数的可 import 性（当前为模块私有 `_` 前缀，但同包 import 合法）。

### 4.4 结果类型（`planner/plan_compiler_v2.py`）

```python
@dataclass(frozen=True)
class PlanCompileResult:
    plan_graph: dict[str, Any]      # v2 PlanGraph（校验失败也返回部分图）
    gaps: list[Gap]                 # 复用 v1 Gap 数据类形状
    governance_flags: list[Flag]    # 复用 v1 Flag 形状
    projection_ref: list            # 本期空
    rule_set_refs: list             # 本期空
    snapshot_id: str
    rationale: str
```
- `Gap`/`Flag`：从 v1 `plan_compiler` import 复用（`missing_capability`/`missing_parameter`；`approval_required`/`write_side_effect`/`invalid_plan_graph`），保证审计字段一致。
- 校验失败时 `governance_flags` 含 `invalid_plan_graph` + 结构化 issues（在 rationale 或扩展字段中携带 path/code/message）；不返回 None。

### 4.5 模块布局

- 新建 `schemas/plan-graph-v2.schema.json`
- 新建 `agent/sap_nexus_agent/semantic_planning/validation_v2.py`
- 新建 `agent/sap_nexus_agent/planner/plan_compiler_v2.py`（含 `PlanCompileResult`）
- `planner/handoff.py`：新增 `compile_plan_v2_from_handoff` 入口（v1 `compile_dry_run_from_handoff` 不动）
- v1 模块零改动

## 5. 测试策略

| 测试 | 文件 | 覆盖 |
|---|---|---|
| 双 READ fixture | `test_planner_plan_compiler_v2.py` | Inventory+PO -> 稳定 v2（readPartition 两节点/空 edges/空 refs/可重复） |
| factField fixture | 同上 | fact 输入绑定生产者 -> data edge authoring + 校验 |
| bad-case | 同上 + `test_semantic_planning_v2.py` | unknown capability、unknown/inconsistent relation、cycle、type mismatch、missing source、snapshot drift、Action-in-READ -> 全 fail-closed + 结构化 issues |
| dry-run 输出 | `test_planner_plan_compiler_v2.py` | plan/gaps/governance/projectionRef/ruleSetRefs/snapshotId 齐全，无 Gateway |
| partition 校验 | `test_semantic_planning_v2.py` | Action 入 readPartition -> violation；并集/无交集 |
| v1 回归 | `test_semantic_planning_contract.py`/`test_planner_plan_compiler.py` | 不改仍通过 |

## 6. Spec Patch

`specs/semantic-plan-authoring-v2/spec.md`：
- 保留 "Parameter sources SHALL be exactly one of `goalConstraint`, `literal`, `factField`, or `registeredDefault`"（4 源闭集）。
- 将 "#### Scenario: Optional input uses registered default" 改为反映 `registeredDefault` 本期为 reserved 源种类（schema 定义，compiler 本期不产出，待 capability input 声明 default 后补产出）。

## 7. Risks / Trade-offs

- **[S1 内部函数 import]** v2 validator import S1 的 `_validate_*` 私有函数。-> 同包 import 合法；若 S1 重构，v2 跟随。备选：抽公共接口（推迟到需时）。
- **[registeredDefault 预留]** 本期不产出，spec 场景降级为 reserved。-> 未来加 defaultValue 时补 compiler 产出 + 恢复场景。
- **[双版本并存成本]** v1 冻结，v2 唯一演进面。-> v1 退役交后续 runbook。
- **[双 READ 空 edges]** 真实反映无 dependsOn；data edge 由独立 fixture 覆盖。-> 不在主 fixture 强造 edge。
- **[projectionRef/ruleSetRefs 预留]** 空 fields。-> R17/18 落地时评估 schema 升级。

## 8. 边界条件

- snapshot 漂移 -> `PlannerFailure(SNAPSHOT_DRIFT)`，不返回 None。
- 编译期 invalid（schema/provenance/edge/cycle）-> `PlanCompileResult` 带结构化 issues，不返回 None，不抛异常（除非 snapshot 漂移）。
- LLM 不得创建 capability/relation/FactType/projection/RuleSet；所有 edge/ref 须来自 snapshot。
- Action 节点 `requiresApproval=true`，仅入 `actionPartition`。
- 不调用 Gateway validate/execute、不调用 SAP。


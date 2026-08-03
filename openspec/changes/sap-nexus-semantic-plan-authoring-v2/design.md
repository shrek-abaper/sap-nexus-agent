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
2. `data` / `dependency` edge authoring 规则：`factField` 绑定是否自动产出 data edge；`dependsOn` 关系如何映射 dependency edge
3. `registeredDefault` source 形状与 default 在 capability input 的字段名 / snapshot 纳入方式
4. v2 模块布局：新建 `plan_compiler_v2` 模块 vs 扩展现有 `planner/` 模块
5. v2 compiler 与 v1 `DryRunResult` 的关系：新建 v2 result 类型 vs 扩展 `DryRunResult`
6. 双 READ 场景 fixture 是否需要引入 factField 绑定以覆盖 data edge 路径

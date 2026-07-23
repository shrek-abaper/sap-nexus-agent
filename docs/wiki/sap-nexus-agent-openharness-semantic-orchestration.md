# SAP Nexus Agent OpenHarness 对比与语义智能编排路线

## 文档版本

| 字段 | 内容 |
|---|---|
| 文档名称 | `SAP Nexus Agent OpenHarness 对比与语义智能编排路线` |
| 当前版本 | `v0.1.0` |
| 状态 | `Decision Baseline Draft` |
| 创建日期 | `2026-07-18` |
| 最近更新 | `2026-07-18` |
| 维护目录 | `docs/wiki/` |
| 文档定位 | 记录 OpenHarness 对比结论，并定义 SAP Nexus 后续语义规划、只读多能力组合和受治理能力演进路线 |
| 关联技术架构 | `docs/wiki/sap-nexus-agent-technical-architecture.md` |
| 关联技术选型 | `docs/wiki/sap-nexus-agent-technology-selection.md` |
| 关联实施路线 | `docs/wiki/sap-nexus-agent-implementation-roadmap.md` |
| 关联 Runbook | `docs/runbooks/10-capability-composition-contract.md` |

---

## 1. 结论先行

OpenHarness 值得借鉴，但不作为 SAP Nexus Agent 的运行内核或直接依赖。它提供的是通用 Agent Harness：模型循环、工具注册、按需 Skill、权限、Hook、Dry-run、Memory、Task 和 Multi-Agent；它不提供 OWL / RDF、Fact Type、Capability Relation 或本体依赖图 Planner。

SAP Nexus 的推荐方向是：

```text
OpenHarness 可借鉴的 Harness 机制
+ SAP Nexus 现有 Capability Registry / Gateway / Approval / Evidence / Eval
+ 新增确定性语义规划控制面
= 受治理的智能编排 Agent
```

“自由编排”在本项目中的准确含义是：

- Agent 可根据自然语言目标，在已发布、已版本化的能力关系图中组合已注册能力。
- LLM 可提出 `GoalSpec` 和 `PlanDraft`，但不能直接获得执行权。
- 确定性 `PlanCompiler` 负责类型匹配、依赖解析、参数绑定、拓扑排序和治理校验。
- 能力或本体不足时输出 `CAPABILITY_GAP`，可以生成 draft，但不能自动发布新能力或新执行绑定。
- 任意 Write 节点仍逐步绑定 Human Approval，不因处于组合计划中而降低治理等级。

首个已确认的只读多能力组合场景是：

```text
物料库存 + 采购订单供给概览
```

该场景只组合两个已注册 Read Function：

```text
MM.Inventory.GetAvailability
+ MM.PurchaseOrder.GetList
-> MaterialSupplySnapshot
```

它不承诺缺货预测、采购数量计算或自动创建 PR；这些结论需要额外的需求、交期、在途、规则和审批事实。

---

## 2. 对比证据范围

本次对比基于：

- OpenHarness `main@9b2efd795c6aa09f88b0c257d269a9e518da6ae7`，项目版本 `0.1.9`。
- OpenHarness 的 `QueryEngine`、Tool Registry、Skill loader、Permission checker、Hook executor、Dry-run 和 Multi-Agent 代码与 README。
- SAP Nexus 当前 `main` 上的 Registry、CallPlan、Gateway、ReasoningFact、Approval、Eval、OWL skeleton、架构、路线和 runbook。

当前 SAP Nexus runtime 事实：

- Active capability 共 3 个：`MM.Inventory.GetAvailability`、`MM.PurchaseOrder.GetList`、`MM.PR.CreateDraft`。
- Capability selector 仍是固定 `intent -> capabilityId` 闭集映射。
- `CallPlan` 当前只承载单个 `capabilityId`，不是 DAG。
- `semanticType` / `ontologyIri` 已存在，但关系本体和一等 `factTypeId` 尚未进入 schema/runtime。
- 当前没有 `ontology/capability-relations.yaml`、`PlanGraph` 或 Dynamic Planner runtime。

---

## 3. OpenHarness 机制对照

| OpenHarness 机制 | 可借鉴到 SAP Nexus | 不直接照搬的部分 |
|---|---|---|
| Agent loop | `observe -> plan/repair -> validate -> execute -> observe` 的长任务循环 | 模型不能直接决定 SAP 技术调用或越过 CallPlan |
| Tool Registry + JSON Schema | 结构化、自描述的 planner meta-tools 和 typed contracts | 不把每个 SAP executor 暴露为任意 Tool |
| Tool Search | 能力候选搜索、按领域加载能力卡片 | 字符串搜索不足以承担关系本体规划 |
| On-demand Skill | 按领域加载业务规则、能力说明、eval 指南 | 项目目录 Skill 不是执行权威，不能自动发布能力 |
| Permission Modes | 映射为 `PLAN_ONLY` / `READ_EXECUTE` / `ACTION_APPROVAL` | 不提供 SAP Write 的 `full_auto` 模式 |
| Pre/Post Hooks | 节点前后策略、审计、脱敏、证据检查 | LLM Hook 只能 advisory，不能作为权威治理门禁 |
| Dry-run | 计划预览、缺参、依赖、治理和能力缺口诊断 | 不能停留在配置 readiness，必须验证业务 PlanGraph |
| Memory/Resume | 保存 Goal、PlanGraph、节点状态和 Registry Snapshot | 聊天记忆不能替代版本化计划与执行证据 |
| Multi-Agent | Planner / Critic / Evaluator 可作为离线建议角色 | 多 Agent 不共享或争抢 SAP 执行权 |
| Parallel tools | 允许无依赖、无副作用 Read 节点并行 | 有依赖、Write 或事务节点不得隐式并发 |
| Plugin ecosystem | 未来可形成受签名、受评审的 domain capability pack | 不加载未受信本地插件成为生产能力 |

直接引入 OpenHarness runtime 的代价大于收益：它会与现有 Python Agent、Gateway、审批和 Trace 形成第二套执行编排权威。项目只吸收机制和设计经验，不增加 OpenHarness 运行时依赖。

---

## 4. 核心领域模型

语义智能编排需要新增以下一等对象。名称是后续正式 design 的输入，不代表 schema 已实现。

| 对象 | 职责 | 是否执行权威 |
|---|---|---|
| `GoalSpec` | 表达用户要获得的目标事实、约束、范围、时效和风险偏好 | 否，LLM candidate |
| `FactType` | 统一输出事实词汇，避免同一事实散落为多个字符串 | 是，发布词汇表 |
| `CapabilityRelation` | 表达 `producesFactType`、`consumesFactType`、`dependsOn`、`precondition` | 是，发布关系层 |
| `PlanDraft` | LLM 基于候选能力提出的计划草案 | 否，必须编译校验 |
| `PlanGraph` | 已解析、已排序、绑定 Registry Snapshot 的可执行 DAG | 是，计划权威 |
| `PlanNode` | 单个注册 capability 的调用、输入来源、输出 Fact、治理状态 | 是，节点执行契约 |
| `PolicyDecision` | 记录 schema、governance、approval、side effect 和环境校验结果 | 是，fail-closed |
| `CapabilityGap` | 描述目标不可达时缺失的 Fact Type、能力或关系 | 否，诊断与 draft 输入 |
| `RegistrySnapshot` | 固定本次计划使用的 capability / binding / relation 版本 | 是，回放权威 |

核心关系：

```text
User Intent
-> GoalSpec
-> desired FactType[]
-> capability relation graph search
-> PlanDraft
-> deterministic PlanCompiler
-> PolicyDecision
-> PlanGraph bound to RegistrySnapshot
-> existing Gateway validate / execute
-> ExecutionResult
-> ReasoningFact with FactType lineage
-> observe / repair / complete
```

### 4.1 GoalSpec 最小方向

```yaml
goalId: goal-...
goalType: MaterialSupplySnapshot
desiredFactTypes:
  - sapnexus:InventoryAvailabilityFact
  - sapnexus:PurchaseOrderSupplyFact
constraints:
  material: DEMOA4B
  plant: "5300"
executionMode: READ_ONLY
```

### 4.2 PlanGraph 最小方向

```yaml
planId: plan-...
registrySnapshot: registry-v...
executionMode: READ_ONLY
nodes:
  - nodeId: inventory
    capabilityId: MM.Inventory.GetAvailability
    parameters:
      material: ${goal.constraints.material}
      plant: ${goal.constraints.plant}
  - nodeId: purchaseOrders
    capabilityId: MM.PurchaseOrder.GetList
    parameters:
      material: ${goal.constraints.material}
      plant: ${goal.constraints.plant}
edges: []
outputs:
  - sapnexus:InventoryAvailabilityFact
  - sapnexus:PurchaseOrderSupplyFact
```

首个场景的两个 Read 节点没有数据依赖，可以在通过全部校验后并行执行；结果必须先归一为 Fact，再形成 `MaterialSupplySnapshot`，不能让 Narrator 直接拼裸 SAP/OData 返回。

---

## 5. 目标架构

```text
Natural Language
        |
        v
Goal Interpreter
-> GoalSpec candidate
        |
        v
Semantic Capability Discovery
-> Capability Registry Snapshot
-> Fact Type Catalog
-> Capability Relation Graph
        |
        v
Planner
-> PlanDraft containing capabilityId / factTypeId only
        |
        v
Deterministic PlanCompiler
-> type matching
-> dependency resolution
-> parameter binding
-> topological ordering
        |
        v
Policy + Dry-run Validator
-> schema / governance / side effect / approval / reachability
        |
        v
PlanGraph
-> READ nodes / reasoning nodes / approval barriers / ACTION nodes
        |
        v
Existing Gateway Family
-> ExecutionResult -> ReasoningFact -> Trace / Eval
```

新增控制面位于 Intent Harness 与现有 CallPlan/Gateway 之间。Gateway 不吸收业务语义、Planner 或本体查询；它继续只接受 `capabilityId` 和受控参数，并通过 `bindingId` 解析技术执行。

---

## 6. 分阶段实施路线

### S0：文档决策基线

状态：本轮完成文档同步，不实现 runtime。

交付：

- OpenHarness 采纳/拒绝边界。
- 语义规划控制面对象和层次。
- 首个只读组合场景。
- OpenSpec / Comet 拆分和验收口径。

### S1：Semantic Planning Foundation

建议 change：`sap-nexus-semantic-planning-foundation`

范围：

- `FactType` 词汇表和 schema。
- `CapabilityRelation` edge list 和 schema。
- `GoalSpec`、`PlanGraph` schema。
- Registry / relation 引用完整性、循环依赖、Fact 类型兼容校验。
- PlanGraph 绑定 Registry Snapshot/version。

不包含：

- LLM Planner。
- SAP 执行。
- 图数据库。
- Write 组合。

### S2：Planner Dry-run

建议 change：`sap-nexus-planner-dry-run`

范围：

- 自然语言到 `GoalSpec` candidate。
- 能力候选发现和 `PlanDraft`。
- 确定性 `PlanCompiler`。
- Dry-run 输出节点、边、参数来源、缺失输入、能力缺口、治理和审批点。
- 不执行 Gateway / SAP。

### S3：Read-only Composition Pilot

建议 change：`sap-nexus-read-composition-pilot`

首个场景：

```text
物料库存 + 采购订单供给概览
```

范围：

- 只允许 `sideEffect=none` 的 active Function。
- 每个节点继续走现有 Gateway `validate -> execute`。
- 无依赖 Read 节点可并行；失败状态必须显式。
- 输出 `MaterialSupplySnapshot`，保留每个 Fact 的 lineage 和 trace。
- 不输出缺货预测或采购数量结论。

### S4：Reasoning / Recommendation Integration

建议与现有 `sap-nexus-recommendation-reasoning` 合并评估，不重复建设第二套推理层。

范围：

- `ReasoningFact[] -> RecommendationPlan`。
- 规则和建议必须声明事实依赖、口径和缺失事实。
- Recommendation 只提出建议，不自动转换为 Action。

### S5：Governed Capability / Ontology Authoring

建议 change：`sap-nexus-governed-capability-authoring`

允许 Agent 生成：

- `CandidateCapabilitySpec` draft。
- `FactType` / relation draft。
- Eval case draft。
- Composite Capability draft。

发布必须经过 schema/SHACL、governance review、sandbox smoke、Eval regression 和 Human Publish。Agent 不得自动注册 executor binding 或提升权限。

### S6：Dynamic Planner

保持 `Phase 3+ / Reserved`。只有关系本体、Dry-run、Read pilot 和 Eval 证明稳定，并满足能力规模、多域或多能力请求比例触发条件后才启动。

Dynamic Planner 仍只能在已发布关系图内工作；它不能生成任意 RFC、URL、SQL、HTTP payload 或未注册 capability。

---

## 7. 技术选型

| 维度 | 近期选型 | 理由 |
|---|---|---|
| Planner implementation | 现有 Python Agent 内独立模块 | 复用当前 Intent、Registry client、CallPlan、Fact 和 Eval，不引入第二运行时 |
| Fact Type / Relation source | YAML + JSON Schema | 可 review、可 version、与现有 Registry 一致 |
| Graph query | 进程内只读 DAG/graph | 当前节点数十量级，无图数据库必要 |
| Plan persistence | JSON/JSONL + Registry Snapshot id | 支持 trace、replay 和早期调试 |
| LLM role | `GoalSpec` / `PlanDraft` candidate | 开放理解，不持有执行权 |
| Compile / policy | Deterministic Python | 可测、可复现、fail-closed |
| Execution | 现有 Gateway Family | 不改变 capability/binding 执行权威 |
| Validation | JSON Schema + Registry validator + Eval Harness | 当前真实质量门禁 |
| OWL / SHACL | ROI spike 后再引入 | 当前不作为 runtime 依赖或门禁 |
| OpenHarness | 设计参考，不增加依赖 | 避免双 Agent runtime 和双执行权威 |

---

## 8. 安全与失败边界

- Planner 输出只能引用已发布 `capabilityId` 和 `factTypeId`。
- `PlanCompiler` 必须拒绝未知节点、未知边、循环依赖、类型不兼容和无来源参数。
- Registry Snapshot 在计划创建后不可静默漂移；版本变化必须重新编译或明确拒绝。
- `READ_ONLY` 计划中出现 Action 时必须整体拒绝。
- Write 节点必须逐节点审批，不能用一个 composite approval 覆盖参数已变化的子节点。
- Prompt/LLM Hook 只能提出风险提示，不能替代 deterministic policy。
- 关系图不可用时不得靠 LLM 猜测依赖；退回已发布 Registry Snapshot 或输出 `CAPABILITY_GAP`。
- 部分 Read 失败必须标注 incomplete，不得把部分事实叙述为完整业务结论。
- 组合链含 Write 时，未来必须声明 `partialFailurePolicy` 和 `compensationPolicy`，本轮不实现。

---

## 9. Eval Harness 扩展

| 指标 | 含义 | 第一阶段要求 |
|---|---|---|
| `goalInterpretationAccuracy` | GoalSpec 是否准确表达目标事实和约束 | 建立 seed baseline |
| `planGroundingRate` | 节点和边是否全部来自发布 Registry / relation graph | `100%` |
| `planValidityRate` | PlanGraph 是否通过类型、依赖和治理校验 | 建立正反例 |
| `capabilityGapAccuracy` | 不可达目标是否正确指出缺失 Fact/能力/关系 | 建立 bad cases |
| `factLineageCompleteness` | 每个组合结论是否可追溯到节点与原始证据 | `100%` |
| `unsafePlanBlockRate` | 未注册、越权、危险或审批缺失计划是否被阻断 | `100%` |
| `writeApprovalBypassRate` | Write 是否可能绕过审批 | `0` |
| `replanRecoveryRate` | Read 节点失败后能否安全停止或在图内修订 | S3 后评估 |

最小 bad case：

- 用户要求提供任意 `rfcName` / OData URL / SQL。
- Goal 需要未注册 Fact Type。
- PlanDraft 引用不存在的 capability。
- PlanGraph 出现循环依赖。
- 上游 Fact 类型不能满足下游输入。
- `READ_ONLY` 计划包含 `MM.PR.CreateDraft`。
- Registry Snapshot 在 dry-run 与 execute 间变化。
- 一个 Read 节点失败但 Narrator 试图输出完整供给结论。

---

## 10. 当前决策状态与下一步

| 决策 | 状态 |
|---|---|
| OpenHarness 作为设计参考 | 已确认 |
| 直接采用 OpenHarness runtime | 拒绝 |
| 新增 OpenHarness 代码依赖 | 拒绝 |
| 首个场景：物料库存 + 采购订单供给概览 | 已确认 |
| S1 Semantic Planning Foundation | 下一正式 design 输入 |
| S2 Planner Dry-run | S1 后设计/实施 |
| S3 Read-only Composition Pilot | S2 验证后实施 |
| 自动本体/能力发布 | 禁止；只允许 draft + human publish |
| Dynamic Planner | Phase 3+ / Reserved |
| Write composition | Reserved；保持逐节点审批和事务边界 |

下一步不是直接编码，而是为 `sap-nexus-semantic-planning-foundation` 创建正式 design，明确 S1 的 schema、模块边界、数据流、错误模型和 Eval cases；用户批准 design 后再进入实施计划。

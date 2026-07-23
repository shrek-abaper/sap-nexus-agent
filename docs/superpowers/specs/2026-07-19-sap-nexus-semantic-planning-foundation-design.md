---
comet_change: sap-nexus-semantic-planning-foundation
role: technical-design
canonical_spec: openspec
archived-with: 2026-07-19-sap-nexus-semantic-planning-foundation
status: final
---

# SAP Nexus 语义规划基础技术设计

## 1. 背景

SAP Nexus Agent 当前支持三个已激活、已注册的能力：

| 能力 | 类型 | 副作用 | 运行状态 |
|---|---|---|---|
| `MM.Inventory.GetAvailability` | `Function` | `none` | 已通过 JCo RFC 上线 |
| `MM.PurchaseOrder.GetList` | `Function` | `none` | 已通过 OData 上线 |
| `MM.PR.CreateDraft` | `Action` | `sap_write` | 已在 Human Approval 保护下上线 |

当前 Agent 只选择一个已注册的 `capabilityId`，构建单能力 `CallPlan`，并且仅向 Gateway 发送能力标识与受治理参数。Gateway 负责解析白名单中的 `bindingId`；调用方和 LLM 都不能提供 RFC 名称、服务 URL、绑定标识、凭据或执行器映射。

这一封闭执行契约是正确的，并保持不变。当前缺失的是确定性的语义控制平面；在未来允许任何多能力规划之前，它必须能够回答三个问题：

1. 每个已注册能力能够产生或消费哪些规范业务 Fact Type？
2. 所请求的语义目标能否通过已发布的能力图到达？
3. 提议的 `PlanGraph` 是否只包含已注册能力、类型化参数来源、兼容的 Fact Type、有效的治理投影，以及一个不可变的 Registry Snapshot？

`docs/wiki/sap-nexus-agent-openharness-semantic-orchestration.md` 中的 OpenHarness 对比为 Agent 循环、工具发现、dry-run、权限和恢复机制提供设计参考。OpenHarness 不会作为依赖引入，也不会成为第二个执行权威。SAP Nexus 继续在现有契约下掌控确定性编译、治理、审批和 Gateway 执行。

## 2. 当前状态证据

本设计基于以下仓库事实：

- `registry/capabilities.yaml` 的版本为 `1`，负责语义能力元数据、输入、输出、治理，以及 `executorBinding.bindingId` 引用。
- `registry/executor-bindings.yaml` 的版本为 `1`，负责白名单中的技术执行细节。
- `schemas/capability.schema.json` 已包含语义输入/输出字段，但尚无一等的 `FactType` 引用或参数绑定分类。
- `ontology/` 包含离线 OWL 标识脚手架，但没有 `fact-types.yaml` 或 `capability-relations.yaml` 运行时契约。
- `agent/sap_nexus_agent/call_plan.py` 表示单个能力，而不是 DAG。
- `agent/sap_nexus_agent/reasoning_fact.py` 表示当前执行证据，并非规划图的 Fact Type 目录。
- `agent/sap_nexus_agent/capability_selector.py` 和 LLM 意图适配器从已激活、已注册的封闭集合中选择能力；它们不执行图规划。
- 多能力运行时、图数据库、动态规划器和任意工具调用均不存在。

这些是约束，不是可以绕过的缺口。S1 在不改变当前执行路径的前提下，围绕这些约束增加契约和确定性验证。

## 3. 目标与非目标

### 3.1 目标

S1 必须：

- 发布规范、版本化的 `FactType` 目录。
- 在能力输入和主要输出中增加可推导的 Fact Type 声明。
- 在独立关系目录中只发布不可推导的 `dependsOn` 和 `precondition` 关系。
- 将四个源契约编译为不可变的内存语义图。
- 定义版本化的 `GoalSpec`、`PlanGraph` 和 `RegistrySnapshot` 契约。
- 通过对四个源文档进行规范化和哈希，构建确定性的 Registry Snapshot。
- 使用彼此独立的确定性报告，分别验证源契约、目标可达性和手工编写的 PlanGraph fixture。
- 使用两个彼此独立的读能力建立首个物料供应 fixture。
- 对未知标识、循环、类型不匹配、参数来源缺失、治理违规、投影漂移和快照漂移实行 fail-closed。

### 3.2 非目标

S1 不得：

- 解释自然语言或调用 LLM。
- 生成 `PlanDraft` 或 `PlanGraph` 实例。
- 执行 `PlanGraph`、调用 Gateway 或调用 SAP。
- 改变当前 selector、orchestrator、`CallPlan`、`ReasoningFact`、Gateway API、审批、前端或 trace 行为。
- 增加图数据库、向量搜索、OWL runtime、SHACL runtime、OpenHarness runtime、插件加载或多 Agent 执行。
- 增加写能力组合、补偿、部分失败执行或组合审批。
- 根据物料供应 fixture 推断短缺、推荐采购数量或创建 PR。

自然语言解释和确定性计划编译属于 S2。只读执行属于 S3。

## 4. 决策与备选方案

### 4.1 选定方案：权威分离，并编译为单一不可变图

选定的设计按照语义所有权拆分人工编写的事实源，再编译出一个只读图：

```text
registry/capabilities.yaml
  output.factTypeRef
  input.bindingKind
  input.satisfiableByFactType
               \
ontology/fact-types.yaml -----> SemanticGraphCompiler -----> ImmutableSemanticGraph
               /
ontology/capability-relations.yaml
  dependsOn
  precondition

registry/executor-bindings.yaml -----> RegistrySnapshot only
```

所有权边界如下：

| 来源 | 权威负责 | 不负责 |
|---|---|---|
| `registry/capabilities.yaml` | 能力标识；输入/输出声明；治理；推导 `producesFactType` 和 `consumesFactType` | 技术绑定内容；人工重复声明的派生图边 |
| `ontology/fact-types.yaml` | 规范 Fact Type 词汇表和语义键 | 能力执行、图拓扑、技术映射 |
| `ontology/capability-relations.yaml` | 不可推导的 `dependsOn` 和 `precondition` 关系 | `producesFactType`、`consumesFactType`、执行器映射 |
| `registry/executor-bindings.yaml` | 白名单中的技术执行器绑定 | 业务语义或规划器决策 |
| `SemanticGraphCompiler` 输出 | 从所有人工编写的语义契约派生出的统一不可变读模型 | 人工编写的事实源或执行权威 |

不得在 `capability-relations.yaml` 中重复声明 `producesFactType` 和 `consumesFactType`。重复声明会产生两个可写事实源，并使漂移解决规则变得模糊。

### 4.2 否决方案：关系目录拥有所有图边

此方案能够集中浏览图，但会重复能力 IO 已表达的事实。输出可能声明 `factTypeRef=A`，关系文件却声明 `producesFactType=B`。解决这种冲突需要任意指定优先级规则，因此否决此方案。

### 4.3 否决方案：从能力 IO 推导所有关系

IO 可以推导生产和消费关系，但无法表达不传递数据的业务先决条件或顺序。将 `dependsOn` 或资格前置条件编码为伪输入会破坏参数语义，因此否决此方案。

### 4.4 否决方案：以 OpenHarness 或图数据库作为运行时权威

OpenHarness 是有价值的设计证据，但引入其运行时会与现有 Agent/Gateway 循环和权限权威重复。当前图规模和查询复杂度尚不足以证明引入图数据库及其运行状态是合理的。S1 使用版本化文件和进程内不可变图。

## 5. 领域模型

### 5.1 核心实体

| 实体 | 含义 | 权威来源 |
|---|---|---|
| `FactType` | 具有稳定语义标识的已发布业务事实词汇 | 编写于 `fact-types.yaml` |
| `Capability` | 具有类型化 IO 和治理信息的已注册 Function 或 Action | 编写于 `capabilities.yaml` |
| `CapabilityRelation` | 不可推导的依赖或前置条件 | 编写于 `capability-relations.yaml` |
| `ImmutableSemanticGraph` | 编译得到的节点以及派生/人工编写的边 | 派生读模型 |
| `GoalSpec` | 对目标 Fact Type 和约束的类型化陈述 | 外部输入，绝不是执行权威 |
| `PlanGraph` | 绑定快照且可确定性验证的能力 DAG | 规划契约；执行能力保留 |
| `RegistrySnapshot` | 计划使用的所有源契约的内容标识 | 不可变版本边界 |
| `CapabilityGap` | 已发布 Fact Type 没有活跃生产者时的诊断信息 | 报告输出，而非能力草稿 |

### 5.2 关系语义

编译器暴露四种关系类型：

| 关系 | 源 | 目标 | 含义 |
|---|---|---|---|
| `producesFactType` | Capability | Fact Type | 从主要输出的 `factTypeRef` 推导 |
| `consumesFactType` | Capability | Fact Type | 从具有 `bindingKind=fact` 的输入推导 |
| `dependsOn` | Capability | Capability | 源能力要求目标能力更早出现在计划中 |
| `precondition` | Capability | Fact Type | 源能力要求该 Fact Type 作为资格条件，但不一定作为参数值 |

`precondition` 被有意设计为不同于 `consumesFactType`：被消费的 Fact 提供参数，而前置条件证明业务状态。S1 验证并暴露二者，但不在运行时评估前置条件。

## 6. 源契约

### 6.1 Capability Registry 版本 2

`registry/capabilities.yaml` 从版本 `1` 原子迁移到版本 `2`。混合 v1/v2 条目无效。

每个输入都新增 `bindingKind`：

```yaml
inputs:
  - name: material
    semanticName: materialNumber
    semanticType: sapnexus:MaterialNumber
    bindingKind: identifier
    required: true
    type: string
    sapParameter: MATERIAL
```

规则：

- `bindingKind` 为必填项，取值只能为 `identifier` 或 `fact`。
- `bindingKind=identifier` 表示参数由 Goal 约束或显式类型化 literal 提供。
- `bindingKind=identifier` 不得声明 `satisfiableByFactType`。
- `bindingKind=fact` 表示之前节点的 Fact 字段可以满足该参数。
- `bindingKind=fact` 必须且只能声明一个引用已发布 Fact Type 的 `satisfiableByFactType`。
- S1 将所有现有输入迁移为 `identifier`；不会虚构能力间数据流。

每个具有 `evidenceRole=primaryFact` 的输出都新增 `factTypeRef`：

```yaml
outputs:
  - name: availableQuantity
    semanticType: sapnexus:AvailableQuantity
    type: number
    evidenceRole: primaryFact
    factTypeRef: sapnexus:InventoryAvailabilityFact
```

规则：

- `primaryFact` 输出必须引用一个已发布的 Fact Type。
- 非主要输出可以省略 `factTypeRef`。
- 如果非主要输出声明了 `factTypeRef`，该引用仍必须可解析。
- 一个能力可以通过多个输出产生多个 Fact Type，但重复的 `(capabilityId, factTypeRef)` 图边会被确定性地合并。

初始映射：

| 能力 | 主要输出 | `factTypeRef` |
|---|---|---|
| `MM.Inventory.GetAvailability` | `availableQuantity` | `sapnexus:InventoryAvailabilityFact` |
| `MM.PurchaseOrder.GetList` | `purchaseOrders` | `sapnexus:PurchaseOrderSupplyFact` |
| `MM.PR.CreateDraft` | `prNumber` | `sapnexus:PurchaseRequisitionCreatedFact` |

现有 `executor`、`executorBinding`、`evalLinkage` 和治理行为保持不变。

### 6.2 Fact Type 目录

`ontology/fact-types.yaml` 是新增的版本化目录：

```yaml
version: 1
factTypes:
  - factTypeId: sapnexus:InventoryAvailabilityFact
    name: Inventory Availability Fact
    description: Available inventory quantity for a material and plant.
    businessObject: InventoryStock
    predicate: sapnexus:hasInventoryAvailability
    semanticType: sapnexus:InventoryAvailability
    keyedBy:
      - sapnexus:MaterialNumber
      - sapnexus:Plant
  - factTypeId: sapnexus:PurchaseOrderSupplyFact
    name: Purchase Order Supply Fact
    description: Purchase-order supply items for a material and plant.
    businessObject: PurchaseOrder
    predicate: sapnexus:hasPurchaseOrderSupply
    semanticType: sapnexus:PurchaseOrderSupply
    keyedBy:
      - sapnexus:MaterialNumber
      - sapnexus:Plant
  - factTypeId: sapnexus:PurchaseRequisitionCreatedFact
    name: Purchase Requisition Created Fact
    description: Identity of a purchase requisition created by an approved Action.
    businessObject: PurchaseRequisition
    predicate: sapnexus:hasCreatedPurchaseRequisition
    semanticType: sapnexus:PurchaseRequisitionCreated
    keyedBy:
      - sapnexus:PrNumber
```

字段语义：

| 字段 | 契约 |
|---|---|
| `factTypeId` | 供目标、能力 IO、图边和计划使用的稳定唯一 compact IRI |
| `name` | 人类可读标签，不作为标识 |
| `description` | 业务定义和口径边界 |
| `businessObject` | Fact 所描述的现有领域对象 |
| `predicate` | Fact 所表示的语义断言 |
| `semanticType` | 规范 payload 含义，与传输层 JSON 类型不同 |
| `keyedBy` | 定义 Fact 范围的非空、有序语义标识集合 |

`keyedBy` 条目是语义标识，不是 YAML 字段路径或 SAP 参数名。

### 6.3 能力关系目录

`ontology/capability-relations.yaml` 初始为空，因为首个 pilot 没有数据依赖或顺序依赖：

```yaml
version: 1
relations: []
```

Schema 对未来人工编写的关系使用可辨识联合：

```yaml
relations:
  - relationId: relation.example.depends-on
    relationType: dependsOn
    capabilityId: MM.Example.Dependent
    dependsOnCapabilityId: MM.Example.Prerequisite
  - relationId: relation.example.precondition
    relationType: precondition
    capabilityId: MM.Example.Action
    requiredFactType: sapnexus:ExampleEligibilityFact
```

规则：

- `relationId` 唯一。
- `dependsOn` 要求两个现有能力 ID，并禁止 `requiredFactType`。
- `precondition` 要求一个现有能力 ID 和一个已发布 Fact Type，并禁止 `dependsOnCapabilityId`。
- 自依赖和重复语义边无效。
- 显式 `dependsOn` 边构成的循环无效。
- 禁止将 `producesFactType` 和 `consumesFactType` 作为人工编写的 `relationType` 值。

### 6.4 Executor Binding 目录

`registry/executor-bindings.yaml` 保持版本 `1`。S1 将其纳入 `RegistrySnapshot`，因为即使它不贡献语义图边，技术映射漂移仍会改变计划的含义和重放安全性。

LLM、`GoalSpec` 和 `PlanGraph` 绝不包含 `bindingId`、`rfcName`、服务 URL、凭据或执行器映射。

## 7. 编译后的语义图

### 7.1 编译器职责

`SemanticGraphCompiler` 接收已经解析且通过 schema 验证的源文档，然后：

1. 按稳定 ID 索引 Fact Type 和能力。
2. 从输出 `factTypeRef` 值推导 `producesFactType` 边。
3. 从 fact-bound 输入推导 `consumesFactType` 边。
4. 添加经过验证的 `dependsOn` 和 `precondition` 边。
5. 检测重复语义边和 `dependsOn` 循环。
6. 返回图之前冻结所有节点和邻接集合。

它不选择能力、不搜索计划、不绑定参数、不调用策略服务，也不执行任何操作。

### 7.2 确定性与不可变性

- 节点按稳定 ID 建立索引。
- 边按 `(relationType, sourceId, targetId)` 排序。
- 重复的源声明在编译前失败；重复的派生边合并为一条图边。
- 返回的图只暴露不可变 mapping/tuple。
- 编译器不执行文件系统写入、网络调用、时钟读取、随机 ID 生成或依赖环境的解析。

该图是读模型。四个版本化源文档仍然是权威来源。

## 8. GoalSpec 契约

最小版本化结构：

```yaml
goalSpecVersion: 1
goalId: goal.material-supply.fixture-001
goalType: sapnexus:MaterialSupplySnapshot
executionMode: READ_ONLY
desiredFactTypes:
  - sapnexus:InventoryAvailabilityFact
  - sapnexus:PurchaseOrderSupplyFact
constraints:
  - name: material
    semanticType: sapnexus:MaterialNumber
    value: DEMOA4B
  - name: plant
    semanticType: sapnexus:Plant
    value: "5300"
```

规则：

- S1 中的 `goalSpecVersion` 必须恰好为 `1`。
- 必须提供 `goalId`、`goalType` 和至少一个 `desiredFactTypes` 条目。
- `executionMode` 只能是 `PLAN_ONLY` 或 `READ_ONLY`。
- 目标 Fact Type ID 必须唯一，且必须存在于已发布目录中。
- 约束名称必须唯一。
- 约束包含 `name`、语义 `semanticType` 和 JSON 标量 `value`（`string`、`number`、`integer` 或 `boolean`）。
- `GoalSpec` 绝不包含能力 ID、执行器标识、技术映射、审批覆盖或计划边。

`PLAN_ONLY` 允许执行可达性分析和验证，但不授权执行。它只能携带 Action 在 Registry 中未经修改的治理投影来描述 Action；绝不授予审批或执行权限。`READ_ONLY` 还要求每个符合条件的生产者及被引用能力的投影均为 `kind=Function`、`sideEffect=none`、`requiresApproval=false` 和 `approvalPolicy=not_required`。已发布但没有活跃生产者的 Fact Type 产生 `CAPABILITY_GAP`；已有活跃生产者、但所有生产者均与请求的执行模式不兼容的已发布 Fact Type 产生 `GOVERNANCE_VIOLATION`。S1 验证这些规则，但仍不执行任何操作。

## 9. PlanGraph 契约

### 9.1 混合快照模型

`PlanGraph` 存储验证和后续审计所需的最小不可变规划投影：

- 计划、目标和快照标识。
- 每个节点的能力标识。
- 参数绑定及其类型化来源。
- 产生的 Fact Type。
- 从 Registry 派生的治理投影。
- 显式数据边/依赖边。
- 确定性拓扑顺序。
- 目标输出的生产者投影。

它不复制完整 Registry，也绝不存储 `rfcName`、`bindingId`、URL、凭据、执行器映射、header 或任意技术请求细节。

### 9.2 最小结构

```yaml
planGraphVersion: 1
planId: plan.material-supply.fixture-001
goalId: goal.material-supply.fixture-001
executionMode: READ_ONLY
snapshotId: sha256:4c59604f35d8e90e360e4dc2fca67ad0ec3a425e841288a06ec56ce71a85b6fd
nodes:
  - nodeId: inventory
    capabilityId: MM.Inventory.GetAvailability
    parameterBindings:
      - parameterName: material
        source:
          kind: goalConstraint
          constraintName: material
      - parameterName: plant
        source:
          kind: goalConstraint
          constraintName: plant
    producesFactTypes:
      - sapnexus:InventoryAvailabilityFact
    governance:
      capabilityKind: Function
      sideEffect: none
      requiresApproval: false
      approvalPolicy: not_required
  - nodeId: purchaseOrders
    capabilityId: MM.PurchaseOrder.GetList
    parameterBindings:
      - parameterName: material
        source:
          kind: goalConstraint
          constraintName: material
      - parameterName: plant
        source:
          kind: goalConstraint
          constraintName: plant
    producesFactTypes:
      - sapnexus:PurchaseOrderSupplyFact
    governance:
      capabilityKind: Function
      sideEffect: none
      requiresApproval: false
      approvalPolicy: not_required
edges: []
topologicalOrder:
  - inventory
  - purchaseOrders
goalOutputs:
  - factTypeId: sapnexus:InventoryAvailabilityFact
    producerNodeId: inventory
  - factTypeId: sapnexus:PurchaseOrderSupplyFact
    producerNodeId: purchaseOrders
```

该 fixture 没有边，因为两个节点都直接从 Goal 约束接收 `material` 和 `plant`。`topologicalOrder` 提供确定性遍历顺序；它并不表示这些独立节点必须串行执行。

### 9.3 参数来源联合类型

每个能力参数最多出现一次，并且恰好有一个来源：

| `source.kind` | 必填字段 | 含义 |
|---|---|---|
| `goalConstraint` | `constraintName` | 从类型化 Goal 约束读取 |
| `literal` | `semanticType`, `value` | 嵌入手工编写计划的显式类型化标量 |
| `factField` | `producerNodeId`, `factTypeId`, `field` | 从之前节点产生的 Fact 中读取字段 |

禁止出现属于其他联合分支的字段。Goal 约束和 literal 只能绑定 `bindingKind=identifier` 输入。`factField` 来源只能绑定 `bindingKind=fact` 输入，并要求一条匹配的 `data` 边，且目标输入的 `satisfiableByFactType` 必须等于 `factTypeId`。其 `field` 必须指向生产者能力的一个输出，且该输出的 `factTypeRef` 等于同一 Fact Type。

### 9.4 边联合类型

```yaml
edges:
  - edgeId: edge.inventory-to-example
    kind: data
    fromNodeId: inventory
    toNodeId: example
    factTypeId: sapnexus:InventoryAvailabilityFact
  - edgeId: edge.prerequisite-to-example
    kind: dependency
    fromNodeId: prerequisite
    toNodeId: example
```

规则：

- `data` 要求 `factTypeId`；`dependency` 禁止该字段。
- 每个端点都必须存在于 `nodes` 中。
- `data` 边的源节点必须产生该 Fact Type。
- `data` 边必须对应目标节点上的至少一个 `factField` 参数绑定。
- 每个 `factField` 参数绑定必须恰好有一条匹配的 `data` 边。
- `dependency` 边必须对应已发布的 `dependsOn` 关系，并在 PlanGraph 中采用从先决节点指向依赖节点的方向。
- 完整边集合必须无环，并且与 `topologicalOrder` 完全一致。

### 9.5 编译器产生的投影

`producesFactTypes`、`governance`、`topologicalOrder` 和 `goalOutputs` 是 S2 中由编译器确定性产生的投影。在 S1 中，它们只出现在 fixture 中，并且必须与 `snapshotId` 绑定的源契约一致。候选计划不能通过编辑这些字段削弱副作用、移除审批、虚构 Fact Type 或改变顺序。

## 10. RegistrySnapshot 契约

### 10.1 纳入的来源

一个快照恰好覆盖：

```text
registry/capabilities.yaml
registry/executor-bindings.yaml
ontology/fact-types.yaml
ontology/capability-relations.yaml
```

OWL 文件被排除，因为它们是离线、非权威镜像。Eval 文件被排除，因为它们是发布证据，而非计划语义。Schema 被排除，因为其版本由已接受的文档版本和应用代码体现；schema 实现变更需要独立的发布证据。

### 10.2 规范化

对于每个源文档：

1. 将 YAML 解析为受支持的数据模型。
2. 将其规范化为不含 YAML tag 或 alias 的 JSON 兼容对象。
3. 使用递归排序的对象键、原始数组顺序、UTF-8、无无意义空白和稳定分隔符 `,` 与 `:` 进行序列化。
4. 对 UTF-8 字节计算 SHA-256。

然后构建规范聚合对象：键为四个仓库相对路径，值为规范化后的源文档。对该对象应用相同的序列化和哈希算法。外部标识为：

```text
snapshotId = "sha256:" + lowercase_hex(sha256(canonical_aggregate_utf8))
```

对象键顺序和 YAML 空白不能改变 digest。数组顺序仍然有意义，因此 Registry/关系的重新排序可被发现和审查。

### 10.3 快照清单

```yaml
snapshotVersion: 1
canonicalizationVersion: 1
snapshotId: sha256:4c59604f35d8e90e360e4dc2fca67ad0ec3a425e841288a06ec56ce71a85b6fd
sources:
  - path: ontology/capability-relations.yaml
    documentVersion: 1
    digest: sha256:10b86710f08b7fd4341b149446ca15e3d1d93cd83b964a994b65964e457a79f2
  - path: ontology/fact-types.yaml
    documentVersion: 1
    digest: sha256:2465f7c86ec22e3363074c3dd51ed08827c144b6e63a38cf247a2d193f686758
  - path: registry/capabilities.yaml
    documentVersion: 2
    digest: sha256:9955512b119e66c32f4281820e3491e8c34365c46b77df35a26ee783017c167b
  - path: registry/executor-bindings.yaml
    documentVersion: 1
    digest: sha256:d0742e4e31b93ee22790c68ff2537813cd01843becc1ce543ad498c523a5bd73
```

上述 digest 值是语法有效的设计示例，并非未来迁移后文件的哈希值。实现 fixture 根据 fixture 内容计算其值，而不是复制这些示例。源条目按 `path` 排序。

S1 在内存和测试 fixture 中构建并验证清单。持久化快照的存储和保留延后到 S2/S3，在设计计划和 trace 存储时处理。具有未知或不匹配 `snapshotId` 的 `PlanGraph` 将 fail-closed。

## 11. 验证与报告模型

### 11.1 独立报告

验证返回三种报告，而不是一个职责过载的结果：

| 报告 | 输入 | 职责 |
|---|---|---|
| `ContractValidationReport` | 四个源文档 | Schema、唯一性、引用、派生图、关系循环、快照构建 |
| `GoalReachabilityReport` | 有效图 + `GoalSpec` | Goal schema、已知 Fact Type、活跃生产者可达性、能力缺口 |
| `PlanValidationReport` | 有效图 + snapshot + `GoalSpec` + `PlanGraph` | 快照、节点、投影、参数来源、边、拓扑、治理、目标满足情况 |

每份报告包含：

```yaml
valid: false
issues:
  - code: UNKNOWN_FACT_TYPE
    path: /desiredFactTypes/0
    message: Fact Type sapnexus:UnknownFact is not published.
```

Issue 路径使用针对逻辑解析文档的 JSON Pointer 表示法。Issue 按 `(path, code, message)` 确定性排序。验证器会在安全的前提下收集彼此独立的错误，但先决条件无效时不会运行后续阶段。

### 11.2 错误分类

| 错误码 | 报告 | 含义 |
|---|---|---|
| `SCHEMA_INVALID` | 任意 | 文档结构或版本无效 |
| `DUPLICATE_ID` | Contract/Plan | 稳定标识在其命名空间内重复 |
| `UNKNOWN_FACT_TYPE` | 任意 | 引用的 Fact Type 未发布 |
| `UNKNOWN_CAPABILITY` | Contract/Plan | 引用的能力未注册 |
| `RELATION_ENDPOINT_NOT_FOUND` | Contract | 人工编写的关系端点无法解析 |
| `DEPENDENCY_CYCLE` | Contract/Plan | 依赖图存在循环 |
| `FACT_TYPE_MISMATCH` | Contract/Plan | 生产者 Fact Type 无法满足声明的消费者输入 |
| `PARAMETER_SOURCE_MISSING` | Plan | 必需的能力参数没有来源 |
| `PARAMETER_SOURCE_DUPLICATE` | Plan | 能力参数有多个来源 |
| `EDGE_INCONSISTENT` | Plan | 边、参数来源、关系或拓扑不一致 |
| `GOVERNANCE_VIOLATION` | Goal/Plan | 执行模式与活跃生产者/能力治理不兼容 |
| `PLAN_PROJECTION_MISMATCH` | Plan | 复制的 Fact Type/治理/顺序/输出投影与编译事实不一致 |
| `SNAPSHOT_MISMATCH` | Plan | 计划快照标识与提供的不可变快照不匹配 |
| `GOAL_OUTPUT_UNSATISFIED` | Plan | 没有任何有效计划节点被投影为产生目标 Fact Type |
| `CAPABILITY_GAP` | Goal | 已发布 Fact Type 没有活跃生产者 |

`CAPABILITY_GAP` 只适用于 Fact Type 已发布、但没有活跃能力产生它的情况。如果 Fact Type 未发布，错误为 `UNKNOWN_FACT_TYPE`；系统不得根据未知字符串虚构缺口或能力草稿。

### 11.3 验证顺序

```text
parse + schema validate sources
-> validate unique IDs and v2 IO invariants
-> validate cross-document references
-> compile immutable semantic graph
-> validate relation cycles
-> build RegistrySnapshot
-> validate GoalSpec and reachability
-> validate PlanGraph schema and snapshot
-> validate nodes and compiler projections
-> validate parameter sources and edges
-> validate topology, governance, and goal outputs
```

该顺序可以避免将级联错误误报为具有误导性的规划器失败。

## 12. 模块与文件边界

S1 实现应与当前运行时路径隔离：

```text
ontology/
  fact-types.yaml
  capability-relations.yaml

schemas/
  capability.schema.json              # migrate registry document to v2
  fact-type-catalog.schema.json
  capability-relation.schema.json
  goal-spec.schema.json
  plan-graph.schema.json
  registry-snapshot.schema.json

agent/sap_nexus_agent/semantic_planning/
  __init__.py
  contracts.py                        # immutable contract/report value objects
  loader.py                           # parse the four governed source documents
  graph.py                            # SemanticGraphCompiler + immutable graph
  snapshot.py                         # canonical JSON and SHA-256 manifest
  validation.py                       # contract, goal, and plan validators

scripts/
  validate-semantic-planning-contract.py

agent/tests/
  test_semantic_planning_contract.py
  fixtures/semantic_planning/
```

边界规则：

- 该 package 可由测试和未来 S2 工作导入，但 S1 中的 `orchestrator.py` 不调用它。
- 脚本是轻量 CLI wrapper；验证逻辑位于 package 中。
- 扩展或组合当前 Registry 验证器，从而只存在一个发布 gate，而不是两个相互矛盾的验证器。
- 任何模块都不得导入 `gateway_client`、`orchestrator`、`llm_client`、前端代码、Java Gateway 代码或 SAP library。
- 除非未来实施计划证明当前项目 parser 无法保留指定的规范数据模型，否则不需要新增外部依赖。

测试 fixture 的精确拆分属于实施计划；上述所有权边界不属于实施计划的自由裁量范围。

## 13. 迁移与兼容性

### 13.1 原子迁移

实施变更执行一次原子契约迁移：

1. 添加新的 schema 和语义目录。
2. 将 `registry/capabilities.yaml` 从版本 `1` 更新为版本 `2`。
3. 为每个现有输入添加 `bindingKind=identifier`。
4. 为每个现有主要 Fact 输出添加已批准的 `factTypeRef`。
5. 更新 `schemas/capability.schema.json` 以强制执行条件规则。
6. 更新现有 Registry 验证器/测试，使其接受版本 `2`，并拒绝混合或不完整迁移。
7. 添加语义图、快照、GoalSpec 和 PlanGraph 验证测试。

不提供双读宽限期。仓库是一个统一部署单元，同时允许两个版本会削弱发布 gate。

### 13.2 运行时兼容性证明

虽然运行时行为不变，但 S1 必须证明当前消费者能够兼容新元数据：

- Registry loader 仍返回相同的三个活跃能力 ID 和当前意图描述符。
- 现有 Agent selector/orchestrator/CallPlan 测试保持不变并通过。
- 现有 Gateway Registry 和执行验证保持不变并通过。
- 现有库存、采购订单和 PR eval 基线继续有效。
- 当前序列化的 `CallPlan` 或 `ReasoningFact` 契约均不改变。

### 13.3 OWL 镜像

OWL 可以为离线文档镜像稳定的 `FactType` 概念和关系属性。YAML + JSON Schema + 确定性验证器仍是权威。OWL 不匹配不能静默覆盖或修复 YAML 契约，S1 运行时/测试成功也不得要求加载 OWL。

## 14. 首个 Pilot Fixture 边界

唯一的 S1 多能力 fixture 是：

```text
MM.Inventory.GetAvailability
+ MM.PurchaseOrder.GetList
-> sapnexus:MaterialSupplySnapshot goal
```

它证明：

- 一个 Goal 可以请求两个已发布 Fact Type。
- 两个活跃读能力可以彼此独立地满足 Goal。
- 共享标识可以来自类型化 Goal 约束。
- 有效 PlanGraph 可以包含多个已注册节点且没有边。
- 可以确定性验证快照和治理投影。

它不证明：

- 运行时并行执行。
- 组合并持久化的 `MaterialSupplySnapshot` payload。
- 短缺预测或供需冲抵。
- 采购数量推荐。
- 自动创建或建议创建 PR。
- Fact 到参数的数据流。

S2 证明 dry-run 行为后，由 S3 负责执行和结果聚合。

## 15. 测试矩阵

| 范围 | 正向证据 | 反向证据 |
|---|---|---|
| Capability v2 | 三个活跃能力全部通过验证 | 缺少 `bindingKind`；fact 输入没有 `satisfiableByFactType`；identifier 输入却带有该字段；主要输出没有 `factTypeRef` |
| Fact Type 目录 | 三个初始唯一 Fact Type 通过验证 | 重复 ID；空 `keyedBy`；目录版本格式错误 |
| 关系目录 | 空 v1 目录可编译 | 未知能力/Fact 端点；禁止的派生关系；自环；依赖循环 |
| 图编译器 | 推导出预期生产者边且结果不可变 | 未知的输出/输入 Fact 引用；非确定性或重复的人工编写边 |
| 快照 | 重复的规范输入产生相同 digest | 任何源内容/数组顺序变化都会改变聚合 digest；未知规范化版本失败 |
| GoalSpec | 首个 pilot Goal 可达 | 未知目标 Fact；重复约束；已发布 Fact 没有活跃生产者时产生 `CAPABILITY_GAP` |
| 计划节点 | 两个已注册读节点都与投影匹配 | 未知能力；虚构 Fact；过期治理投影 |
| 参数来源 | `material` 和 `plant` 各自从 Goal 约束绑定一次 | 必需来源缺失；来源重复；约束语义不匹配 |
| 数据边 | 匹配的 factField 绑定和 data 边通过验证 | 边缺失/重复；生产者不输出 Fact；目标输入无法消费 Fact |
| 依赖/拓扑 | 无环边顺序通过验证 | 边与已发布关系或拓扑顺序冲突；存在循环 |
| 治理 | `READ_ONLY` 只包含无副作用 Function | `READ_ONLY` 中包含 Action 或写/审批投影 |
| Goal 输出 | 两个目标 Fact Type 都映射到生产者 | 目标 Fact 没有生产者映射，或映射指向错误节点 |
| 兼容性 | 现有 loader、Agent、Gateway、eval 和证据检查通过 | 任何当前单能力序列化契约发生变化 |

Fixture 断言和报告 issue 顺序必须精确；在已有结构化错误码和路径时，测试不应只依赖子字符串错误匹配。

## 16. 验收标准

只有满足以下所有条件，S1 才能通过验收：

- `capabilities.yaml` 原子迁移到 v2，不存在缺失或相互矛盾的绑定元数据。
- 三个初始 Fact Type 及其主要输出映射已发布并通过验证。
- 空 v1 关系目录能够编译，并禁止人工编写派生边。
- `SemanticGraphCompiler` 在没有运行时依赖的情况下返回预期的不可变生产者图。
- Registry Snapshot 生成具有确定性，且恰好包含四个受治理来源。
- 有效的 GoalSpec 和 PlanGraph pilot fixture 通过。
- 每个已批准错误码都在适用时至少有一个聚焦的反向测试。
- 报告路径和 issue 顺序具有确定性。
- 现有单能力 selector、`CallPlan`、Gateway、审批、Fact、前端和 SAP 行为保持不变。
- S1 测试中不发生任何 LLM、Gateway、SAP、图数据库、OWL runtime 或 OpenHarness runtime 调用。
- 仓库验证和严格 OpenSpec 验证通过。

## 17. 风险与压力测试

| 风险/最强反对意见 | 设计应对 | 失败信号 |
|---|---|---|
| 新语义层变成重复 Registry | 每个人工编写的事实只有一个所有者；图边由此派生；投影不匹配即失败 | 同一关系可以在两个文件中独立编辑 |
| Snapshot ID 提供哈希但不提供重放内容 | S1 只定义标识；S2/S3 必须在执行前设计内容寻址的保留机制 | 持久化计划可以执行，但无法解析其源快照 |
| `FactType` 变成改名后的输出字段 | Fact 标识包含业务对象、谓词、语义 payload 含义和语义键 | Fact Type 仅在 UI 标签或传输字段名上不同 |
| PlanGraph 成为控制执行器的后门 | 技术字段不存在且被 schema 禁止；Gateway 仍负责解析绑定 | Plan 或 Goal 可以选择 `bindingId`、RFC、服务、URL 或凭据 |
| 信任 READ_ONLY 标签而不验证 | 治理由绑定 Registry 投影，并以 fail-closed 方式比较 | Action 在 READ_ONLY 计划中通过验证 |
| 首个空关系目录证明的内容太少 | 它有意在不虚构依赖的情况下证明多输出可达性；数据边场景使用隔离 fixture | Pilot 声称证明了依赖规划或运行时并行 |
| 原子 v2 迁移破坏当前运行时 reader | 现有 loader/Gateway/eval 验证是发布 gate | 任何当前单能力契约或行为发生回归 |
| S1 悄然扩展成规划器 | Package 不提供自然语言、搜索、绑定生成或执行 API | S1 生产代码根据用户语言输出新的 PlanGraph |

最有力的备选方案是将 Fact Type 推迟到 LLM 规划器存在后再建设。但这会让 LLM 在系统能够确定性验证词汇和计划结构之前先虚构二者。选定顺序有意与此相反：先发布语义，再验证手工编写的 fixture，最后才增加候选生成。

## 18. 阶段交接

### S1 向 S2 输出：Planner Dry-run

只有在 S1 已实施、审查、验证并归档后，S2 才能开始。S2 消费：

- 版本化的 Fact Type 和关系目录。
- 不可变语义图 API。
- GoalSpec、PlanGraph 和 RegistrySnapshot schema。
- 确定性报告/错误契约。
- 有效和无效 fixture。

S2 增加从自然语言到 GoalSpec 的候选生成、能力发现、`PlanDraft`、确定性 `PlanCompiler` 和 dry-run 展示。它仍不执行 Gateway 或 SAP。

### S2 向 S3 输出：只读组合 Pilot

只有在 S2 证明 fail-closed dry-run 场景后，S3 才能开始。S3 通过现有 Gateway `validate -> execute` 路径，为已确认的双节点只读场景增加执行，并保留 Fact lineage。它不增加写能力组合。

### S3 之后保留

推荐推理、受治理的能力编写和 Dynamic Planner 仍是彼此独立的变更。Dynamic Planner 继续受稳定语义契约、dry-run 证据、只读 pilot 证据，以及 roadmap/runbook 中记录的规模触发条件约束。

## 19. 未来实施的验证计划

实施计划必须保留仓库现有验证链，并增加聚焦的语义规划测试。预期命令为：

```bash
.venv/bin/python scripts/validate-registry-contract.py registry/capabilities.yaml
.venv/bin/python scripts/validate-semantic-planning-contract.py
.venv/bin/python -m pytest agent/tests/test_registry_contract.py -v
.venv/bin/python -m pytest agent/tests/test_semantic_planning_contract.py -v
scripts/verify-agent-callplan-evidence.sh
openspec list --json
openspec validate --all --strict
git diff --check
```

不需要前端验证，因为 S1 不能修改前端文件。任何需要前端或 live SAP 验证的实现都已经越过批准的 S1 边界，必须返回设计评审。

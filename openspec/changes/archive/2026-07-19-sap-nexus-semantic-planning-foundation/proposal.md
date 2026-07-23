## Why

SAP Nexus 当前只能从注册闭集中选择一个 `capabilityId` 并生成单能力 `CallPlan`，尚不存在可发布、可复现的 Fact Type、能力关系图、GoalSpec/PlanGraph 与 Registry Snapshot 契约。若直接引入自然语言 Planner，LLM 将在缺少确定性语义边界和治理校验的情况下自行发明能力关系，因此需要先建立 S1 语义规划基础层。

## What Changes

- **BREAKING**：将 `registry/capabilities.yaml` 从 version `1` 原子迁移到 version `2`，为所有 input 增加 `bindingKind`，为 primary Fact output 增加 `factTypeRef`。
- 新增 versioned `FactType` catalog 和仅承载 `dependsOn` / `precondition` 的关系 catalog；`producesFactType` / `consumesFactType` 由 capability IO 确定性派生，不重复维护。
- 新增 immutable `SemanticGraphCompiler`、四源 `RegistrySnapshot`、`GoalSpec`、`PlanGraph` 和三类结构化 validation report。
- 新增首个 `MM.Inventory.GetAvailability + MM.PurchaseOrder.GetList` 双 READ 节点、零 edge 的 material-supply Goal/Plan fixtures。
- 将旧 Registry 安全门禁与新语义门禁组合为单一验证入口，并保持现有 selector、orchestrator、`CallPlan`、`ReasoningFact`、Gateway、frontend 和 SAP runtime 不变。
- S1 只加载、编译和验证契约；不调用 LLM/Gateway/SAP，不生成或执行 PlanGraph，不引入 OpenHarness runtime、图数据库或 write composition。

## Capabilities

### New Capabilities

- `semantic-planning-foundation`: 定义并验证 canonical Fact Types、非派生 capability relations、immutable semantic graph、GoalSpec、PlanGraph、Registry Snapshot、reachability 和 fail-closed error/report contracts。

### Modified Capabilities

- `registry-ontology-contract`: 将 Capability Registry 升级到 v2，增加 input binding classification 与 primary output Fact Type reference，同时保持 executor binding、governance、eval linkage 和离线 OWL 边界。

## Impact

- Affected contracts: `registry/capabilities.yaml`、`schemas/capability.schema.json`、新增 semantic planning schemas、`ontology/fact-types.yaml`、`ontology/capability-relations.yaml`。
- Affected Python surface: 新增 `agent/sap_nexus_agent/semantic_planning/` package 和组合 validator CLI；现有 Registry validator 仅扩展 v2 invariants。
- Affected tests/evidence: contract schemas、semantic graph、snapshot、goal/plan fixtures、全部批准错误码和现有 single-capability regression。
- No new external dependency, public Gateway API, SAP executor, frontend surface, runtime planner, graph database, credential, or deployment requirement.

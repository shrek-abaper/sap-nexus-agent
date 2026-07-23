# Comet Design Handoff

- Change: sap-nexus-semantic-planning-foundation
- Phase: design
- Mode: compact
- Context hash: ed65326858b325567d674ea6c8b177d96a7145be11acdfd1885802cc08c54a32

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/sap-nexus-semantic-planning-foundation/proposal.md

- Source: openspec/changes/sap-nexus-semantic-planning-foundation/proposal.md
- Lines: 1-29
- SHA256: b32084b6bf770755bcd1df409790a96406bf9f1ea0fcaf69379269afdd2def7c

```md
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

```

## openspec/changes/sap-nexus-semantic-planning-foundation/design.md

- Source: openspec/changes/sap-nexus-semantic-planning-foundation/design.md
- Lines: 1-81
- SHA256: aee1d26a7957b5f72a9397dbb9367f4f34b6566e7be0879708ae38c1b118122b

[TRUNCATED]

```md
## Context

当前 SAP Nexus Agent 通过注册闭集选择单个 `capabilityId`，使用现有 `CallPlan -> Gateway validate/execute -> ExecutionResult/ReasoningFact` 链路完成读写能力。Registry 已分离业务 capability 与 allowlisted executor binding，但 capability IO 尚未发布 canonical Fact Type，能力之间也没有可确定性编译和校验的关系图。

本 change 是 S1 Semantic Planning Foundation。它在现有 Agent 与 Gateway 之间预留语义控制面契约，但不接入当前 runtime。完整技术决策以 `docs/superpowers/specs/2026-07-19-sap-nexus-semantic-planning-foundation-design.md` 为准，实施步骤以对应 implementation plan 为准。

## Goals / Non-Goals

**Goals:**

- 发布 versioned Fact Type、non-derivable capability relation、GoalSpec、PlanGraph 和 RegistrySnapshot contracts。
- 将 capability IO 编译为 immutable semantic graph，并提供确定性 contract、goal、plan validation reports。
- 将 Registry 原子迁移到 v2，同时证明当前三个 active capability 和 single-capability runtime 不回归。
- 用 inventory + purchase-order 两个独立 READ 节点验证 multi-capability Goal/Plan fixture。

**Non-Goals:**

- 不解释自然语言、不调用 LLM、不生成 PlanDraft/PlanGraph。
- 不执行 PlanGraph、不调用 Gateway/SAP、不改变 selector、orchestrator、CallPlan、ReasoningFact、frontend 或 Java Gateway。
- 不引入 OpenHarness runtime、graph database、OWL runtime、write composition、compensation 或 auto-publish。

## Decisions

### 1. Split authority, one compiled graph

- `registry/capabilities.yaml` owns capability identity、governance、input `bindingKind`/`satisfiableByFactType` 和 output `factTypeRef`。
- `ontology/fact-types.yaml` owns canonical Fact Type definitions。
- `ontology/capability-relations.yaml` only owns authored `dependsOn` and `precondition`。
- `producesFactType` / `consumesFactType` only derive from capability IO and MUST NOT be authored again。
- `SemanticGraphCompiler` returns a recursively immutable in-process graph; source YAML remains authoritative。

选择该方案是为了避免同一 relation 在 Registry 和 relation catalog 中出现两个可写真值。只从 IO 推导全部关系同样不可接受，因为业务 dependency/precondition 不等同于参数传递。

### 2. Atomic Registry v2 migration

`capabilities.yaml` 从 v1 一次性迁移到 v2：每个 input 必须声明 `bindingKind=identifier|fact`；fact input 必须引用 `satisfiableByFactType`，identifier input 禁止该字段；每个 `evidenceRole=primaryFact` output 必须声明 `factTypeRef`。不提供双读期，现有 loader/eval/Gateway regressions 是兼容性 gate。

### 3. Hybrid PlanGraph + RegistrySnapshot

PlanGraph 保存 capability identity、parameter provenance、produced Fact Types、governance projection、edges、topological order 和 snapshotId，不复制 Registry 或 executor mapping。Snapshot 对以下四份 normalized JSON source 做 stable UTF-8 SHA-256：

- `registry/capabilities.yaml`
- `registry/executor-bindings.yaml`
- `ontology/fact-types.yaml`
- `ontology/capability-relations.yaml`

YAML whitespace/object key order不影响 hash，array order保留语义。S1 只构建 manifest；持久化/retention 属于 S2/S3。

### 4. Goal and Plan fail closed

GoalSpec 仅允许 `PLAN_ONLY` / `READ_ONLY`。unknown Fact 报 `UNKNOWN_FACT_TYPE`；published Fact 无 active producer 才报 `CAPABILITY_GAP`；只有治理不兼容 producer 时报 `GOVERNANCE_VIOLATION`。

PlanGraph 参数来源仅允许 `goalConstraint`、`literal`、`factField`，edge 仅允许 `data`、`dependency`。所有 compiler projections 必须与 snapshot-bound Registry 一致；snapshot drift、missing/duplicate source、type mismatch、edge/topology mismatch、governance violation 或 unsatisfied goal 均 fail closed。

### 5. Preserve the existing release gate

现有 `validate_registry_contract` 的 binding、secret、REST、OWL 和 eval 检查全部保留。新 semantic validator 与旧 validator 通过一个 CLI 组合，并接入现有 evidence script；不重写或绕过旧安全门禁。

## Risks / Trade-offs

- [Registry v2 破坏旧读取方] -> 原子迁移全部 inline fixtures，并运行 Registry loader、Agent、eval 和 Gateway evidence regressions。
- [FactType 退化为 output 字段别名] -> Fact Type 必须同时声明 businessObject、predicate、semanticType 和 keyedBy。
- [Snapshot 只有 hash、无法长期 replay] -> S1 只提供 identity；任何 S3 执行前必须设计 content-addressed retention。
- [PlanGraph 成为 executor 控制后门] -> schema 和 validator 禁止 bindingId、RFC、URL、credential、header、executor mapping；Gateway 仍只按 registered capability 解析 binding。
- [空 relation catalog 证明力有限] -> 首个场景只验证 multi-output reachability 和治理/snapshot，不宣称 data dependency 或 runtime parallelism。
- [S1 scope 泄漏到 Planner] -> semantic planning package 不导入 LLM/Gateway/orchestrator，测试只加载、编译和验证 hand-authored fixtures。

## Migration Plan

1. 新增 schemas、Fact Type/relation catalogs 和失败测试。
2. 原子迁移 capability Registry v2 与现有 inline fixtures。
3. 实现 immutable contracts、loader、snapshot 和 semantic graph。
4. 实现 contract、GoalSpec、PlanGraph validators 与批准错误码覆盖。
5. 接入组合 release-gate CLI，运行完整兼容性回归。
6. 更新 verification report、runbook 和 roadmap，经 verify 后再请求 archive。

Rollback 只允许整体回退该 change；不得在一个 revision 中保留 v2 schema 配 v1 registry，或保留 PlanGraph contract 而移除其 Fact Type source。

## Open Questions


```

Full source: openspec/changes/sap-nexus-semantic-planning-foundation/design.md

## openspec/changes/sap-nexus-semantic-planning-foundation/tasks.md

- Source: openspec/changes/sap-nexus-semantic-planning-foundation/tasks.md
- Lines: 1-47
- SHA256: 8c85ef503718b39544b585a23240979bb85262173218586b9c0467ca016bdd54

```md
## 1. Registry v2 与语义 schemas

- [ ] 1.1 先添加 Registry v2、Fact Type catalog 和 relation catalog 的失败 contract tests
- [ ] 1.2 原子迁移 `registry/capabilities.yaml` 到 version 2，为全部 input 增加 `bindingKind`，为三个 primary output 增加已批准 `factTypeRef`
- [ ] 1.3 创建 `ontology/fact-types.yaml`、`ontology/capability-relations.yaml` 及五份 semantic planning JSON Schemas
- [ ] 1.4 同步现有 inline capability fixtures 到 v2，并通过全部 contract schema 正反例

## 2. Immutable contracts、loader 与 Registry Snapshot

- [ ] 2.1 先添加四源 loader、canonical JSON 和 deterministic snapshot 的失败测试
- [ ] 2.2 创建 `semantic_planning` package 的 immutable report/source/snapshot value objects 与安全 YAML loader
- [ ] 2.3 实现四源 canonical SHA-256 snapshot manifest，并通过格式稳定、array order 和内容敏感测试

## 3. Semantic graph 与 contract validation

- [ ] 3.1 先添加 derived producer edges、deep immutability、structured issue sorting 和 invalid source tests
- [ ] 3.2 实现 `SemanticGraphCompiler`，从 capability IO 派生 producer/consumer edges，并加入 authored dependency/precondition edges
- [ ] 3.3 实现 source version、unique ID、Fact reference、binding reference、relation endpoint 和 dependency-cycle validation
- [ ] 3.4 扩展现有 Registry validator 的 v2 IO invariants，完整保留 binding/secret/REST/OWL/eval checks

## 4. GoalSpec reachability

- [ ] 4.1 创建 material-supply Goal fixture，并先添加 reachable/unknown/gap/governance 失败测试
- [ ] 4.2 实现 GoalSpec shape、typed constraint、published Fact、active producer 和 execution-mode validation
- [ ] 4.3 证明 `UNKNOWN_FACT_TYPE`、`CAPABILITY_GAP` 与 `GOVERNANCE_VIOLATION` 语义互不混淆

## 5. PlanGraph validation

- [ ] 5.1 创建双 READ 节点、零 edge 的 material-supply Plan fixture，并先添加 fail-closed matrix
- [ ] 5.2 实现 snapshot/goal identity、registered node、compiler projection、parameter provenance 和 governance validation
- [ ] 5.3 实现 data/dependency edge、Fact compatibility、topological order 和 Goal output validation
- [ ] 5.4 覆盖全部批准错误码，并证明 technical executor override 被拒绝且 validator 不生成或执行 PlanGraph

## 6. 组合 release gate 与兼容性回归

- [ ] 6.1 创建组合旧 Registry gate 与新 semantic gate 的 `validate-semantic-planning-contract.py`
- [ ] 6.2 将组合 CLI 接入 `verify-agent-callplan-evidence.sh`，不删除现有 Agent/eval/OpenSpec commands
- [ ] 6.3 运行 focused schema/registry/semantic/loader tests，并证明三个 active capability runtime descriptor 不变
- [ ] 6.4 运行完整 evidence script 和静态边界扫描，确认没有 LLM/Gateway/SAP/frontend/runtime scope leakage

## 7. Evidence、文档与 Comet closeout

- [ ] 7.1 创建 verification report，记录真实 CLI、pytest、evidence 和 OpenSpec 输出
- [ ] 7.2 同步 runbook 10、runbook index 和 implementation roadmap，将下一阶段设置为 S2 planner dry-run
- [ ] 7.3 运行 `git diff --check`、`openspec validate --all --strict`、完整 evidence script 和 scoped status 检查
- [ ] 7.4 完成 task review 与 final whole-change review，处理所有 Critical/Important findings
- [ ] 7.5 经用户确认后执行 Comet verify/archive；未经明确要求不 commit

```

## openspec/changes/sap-nexus-semantic-planning-foundation/specs/registry-ontology-contract/spec.md

- Source: openspec/changes/sap-nexus-semantic-planning-foundation/specs/registry-ontology-contract/spec.md
- Lines: 1-43
- SHA256: 188986f3b3fc532deb599876b7678b80516f28e526d5d6d16dbe8438dee81a2e

```md
## MODIFIED Requirements

### Requirement: Registry schema validates semantic capability contract
The system SHALL validate `registry/capabilities.yaml` version `2` against a deterministic Registry contract that covers capability identity, semantic metadata, typed inputs, Fact-producing outputs, governance, and executor binding references. Every input MUST declare `bindingKind=identifier|fact`; a fact-bound input MUST reference one published `satisfiableByFactType`, while an identifier input MUST NOT declare that field. Every output with `evidenceRole=primaryFact` MUST reference one published `factTypeRef`.

#### Scenario: All active capabilities pass Registry v2 contract
- **WHEN** the contract validator checks the active `MM.Inventory.GetAvailability`, `MM.PurchaseOrder.GetList`, and `MM.PR.CreateDraft` entries
- **THEN** validation succeeds for their stable identity, semantic IO, governance, eval linkage, and executor binding references
- **AND** each existing input is classified as `bindingKind=identifier`
- **AND** their primary outputs reference `sapnexus:InventoryAvailabilityFact`, `sapnexus:PurchaseOrderSupplyFact`, and `sapnexus:PurchaseRequisitionCreatedFact` respectively
- **AND** the capabilities remain available to existing Agent and Gateway flows by the same `capabilityId`

#### Scenario: Fact-bound input lacks Fact Type reference
- **WHEN** an input declares `bindingKind=fact` without `satisfiableByFactType`
- **THEN** contract validation fails before graph compilation or runtime execution

#### Scenario: Identifier input declares Fact Type reference
- **WHEN** an input declares `bindingKind=identifier` together with `satisfiableByFactType`
- **THEN** contract validation fails as contradictory parameter provenance

#### Scenario: Primary Fact output lacks Fact Type reference
- **WHEN** a primary Fact output omits `factTypeRef` or references an unpublished Fact Type
- **THEN** contract validation fails before the capability can enter the semantic graph

#### Scenario: Malformed capability is rejected before runtime execution
- **WHEN** a Registry entry is missing required identity, semantic fields, governance fields, v2 input/output metadata, eval linkage, or executor binding reference
- **THEN** contract validation fails with a deterministic error
- **AND** the invalid entry is not treated as an executable SAP or external-system capability

## ADDED Requirements

### Requirement: Registry v2 migration is atomic and runtime-compatible
The repository SHALL publish capability schema v2, capability Registry v2, Fact Type catalog, and semantic validators as one atomic change. It MUST NOT support a mixed v1/v2 Registry state or alter current technical executor ownership.

#### Scenario: Existing runtime loader reads migrated Registry
- **WHEN** the current Agent Registry loader reads the v2 document
- **THEN** it returns the same three active capability IDs and current input descriptors
- **AND** it does not copy planning metadata into the current CallPlan

#### Scenario: Technical binding ownership remains unchanged
- **WHEN** a migrated capability is validated or later selected by the current runtime
- **THEN** callers still provide only registered `capabilityId` and governed parameters
- **AND** `bindingId`, RFC/OData details, credentials, and executor mappings remain owned by allowlisted Registry/binding artifacts

```

## openspec/changes/sap-nexus-semantic-planning-foundation/specs/semantic-planning-foundation/spec.md

- Source: openspec/changes/sap-nexus-semantic-planning-foundation/specs/semantic-planning-foundation/spec.md
- Lines: 1-117
- SHA256: ba2b5c8a4bb3bdce1e2f82772d342fae60881f2c5c5b124403d34b36b2cd85f4

[TRUNCATED]

```md
## ADDED Requirements

### Requirement: Canonical Fact Types and capability relations have single owners
The system SHALL publish a versioned Fact Type catalog and a versioned capability relation catalog. Capability output `factTypeRef` SHALL be the only authored source for `producesFactType`; fact-bound input `satisfiableByFactType` SHALL be the only authored source for `consumesFactType`; the relation catalog SHALL author only `dependsOn` and `precondition`.

#### Scenario: Compiler derives production edges
- **WHEN** a primary capability output references a published Fact Type
- **THEN** the semantic graph contains one `producesFactType` edge from the capability to that Fact Type
- **AND** the relation catalog does not repeat that derived edge

#### Scenario: Authored derived edge is rejected
- **WHEN** the relation catalog declares `producesFactType` or `consumesFactType`
- **THEN** contract validation fails before a semantic graph is published

#### Scenario: Missing relation endpoint is rejected
- **WHEN** a `dependsOn` capability or `precondition` Fact Type does not exist
- **THEN** contract validation reports `RELATION_ENDPOINT_NOT_FOUND` at the exact JSON Pointer path

### Requirement: Semantic graph compilation is deterministic and immutable
The system SHALL compile validated capabilities, Fact Types, and authored relations into an in-process immutable semantic graph. Compilation MUST NOT perform filesystem writes, network calls, clock reads, random ID generation, plan search, policy execution, Gateway calls, or SAP calls.

#### Scenario: Equivalent source content produces the same graph
- **WHEN** the compiler receives the same validated semantic source documents repeatedly
- **THEN** it returns the same sorted node/edge indexes
- **AND** callers cannot mutate graph mappings, nested objects, or edge collections

#### Scenario: Dependency cycle fails closed
- **WHEN** authored `dependsOn` relations form a cycle
- **THEN** contract validation reports `DEPENDENCY_CYCLE`
- **AND** no graph or Registry Snapshot is returned as valid

### Requirement: Registry Snapshot binds plans to four governed sources
The system SHALL build `RegistrySnapshot v1` from canonicalized forms of capability Registry, executor-binding catalog, Fact Type catalog, and capability-relation catalog. Canonicalization SHALL normalize YAML to JSON-compatible data, recursively sort object keys, preserve array order, use stable separators and UTF-8, and compute lowercase SHA-256 identifiers.

#### Scenario: Formatting-only changes preserve snapshot identity
- **WHEN** YAML whitespace or object key order changes without changing normalized content
- **THEN** the computed `snapshotId` remains unchanged

#### Scenario: Governed source content changes snapshot identity
- **WHEN** any normalized value or array order in one of the four governed sources changes
- **THEN** the aggregate `snapshotId` changes

#### Scenario: Plan carries stale snapshot
- **WHEN** a PlanGraph `snapshotId` does not match the supplied Registry Snapshot
- **THEN** plan validation reports `SNAPSHOT_MISMATCH`

### Requirement: GoalSpec reachability uses published Fact Types and governance
The system SHALL validate `GoalSpec v1` with semantic `goalType`, unique desired Fact Types, typed scalar constraints, and execution mode `PLAN_ONLY` or `READ_ONLY`. It SHALL distinguish unknown vocabulary, missing producer capability, and governance incompatibility.

#### Scenario: Published Fact Type is reachable
- **WHEN** each desired Fact Type has at least one active producer compatible with the Goal execution mode
- **THEN** `GoalReachabilityReport.valid` is true
- **AND** all desired Fact Types appear in `reachableFactTypes`

#### Scenario: Unknown Fact Type is not converted into a capability gap
- **WHEN** a desired Fact Type is not published
- **THEN** validation reports `UNKNOWN_FACT_TYPE`
- **AND** it does not report `CAPABILITY_GAP` for that string

#### Scenario: Published Fact Type has no active producer
- **WHEN** a desired Fact Type is published but no active capability produces it
- **THEN** validation reports `CAPABILITY_GAP`

#### Scenario: READ_ONLY goal has only Action producer
- **WHEN** a published Fact Type has active producers but all require write side effects or approval
- **THEN** a `READ_ONLY` Goal reports `GOVERNANCE_VIOLATION`
- **AND** a `PLAN_ONLY` Goal does not authorize execution or approval

### Requirement: PlanGraph validates provenance, graph consistency, and projections
The system SHALL validate `PlanGraph v1` nodes against registered capabilities and the bound Registry Snapshot. Parameter sources SHALL be exactly one of `goalConstraint`, `literal`, or `factField`; edges SHALL be exactly one of `data` or `dependency`; produced Fact Types, governance, topological order, and Goal outputs SHALL match compiler-derived truth.

#### Scenario: Independent material-supply plan validates
- **WHEN** the plan contains `MM.Inventory.GetAvailability` and `MM.PurchaseOrder.GetList`, binds `material` and `plant` from Goal constraints, projects both READ governance contracts, and contains no edges
- **THEN** the plan validates against the current snapshot
- **AND** both desired Fact Types map to their registered producer nodes

#### Scenario: Required parameter provenance is missing or duplicated
- **WHEN** a required capability parameter has no source or more than one source
- **THEN** validation reports `PARAMETER_SOURCE_MISSING` or `PARAMETER_SOURCE_DUPLICATE`


```

Full source: openspec/changes/sap-nexus-semantic-planning-foundation/specs/semantic-planning-foundation/spec.md

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

无。S1 权威边界、schemas、错误语义、首个 fixture 和 S2/S3 handoff 已在正式设计评审中确认。

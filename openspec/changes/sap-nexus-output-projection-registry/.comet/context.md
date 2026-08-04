# Comet Design Handoff

- Change: sap-nexus-output-projection-registry
- Phase: design
- Mode: compact
- Context hash: 23910c6316e2d011a3e719f5455d742417a243c29508d93dafeaeccd64a8e059

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/sap-nexus-output-projection-registry/proposal.md

- Source: openspec/changes/sap-nexus-output-projection-registry/proposal.md
- Lines: 1-31
- SHA256: 30a5d5a72a225ef1c4d41949131912efe68f13699524e5c30eb3692602a32dec

```md
## Why

Runbook 16 的 READ PlanExecutor 已能在 TS 侧调度执行 READ 节点并产出节点账本（`PlanExecutorResult`），但多 READ 结果仍以裸节点级形式存在，缺少确定性的组合投影：跨节点事实无法形成可追溯的 `MaterialSupplySnapshot`，freshness / 完整性 / lineage 无结构化口径，partial 失败无契约。LLM 因此被迫在 prompt 中拼接业务事实，违背"事实由版本化确定性规则投影、LLM 仅叙述"的边界。Runbook 17 是 Runbook 16 的直接后继，补上这条投影链路，为 Runbook 18 的 Recommendation 提供可追溯快照输入。

## What Changes

- 新增版本化 `OutputProjection` 注册表与校验机制：projection 声明 required/optional input FactType、output schema、时间口径、partial policy；`@version` 确定性绑定，相同输入 + projection version + snapshotId 产出相同输出 hash。
- 新增 `MaterialSupplySnapshot` 作为首个注册 projection：`{ asOf, sourceFreshness, completeness, facts, lineage, missingFacts, failedNodes, limitations }`，作为组合事实束（非派生业务指标）。
- 新增投影输入组装：从 `PlanExecutorResult` + 节点级 Gateway 结果组装 `PlanExecutionRecord + successful ReasoningFact[]` 作为 projection 输入（executor 现仅产出节点账本，不携带 facts，本轮补齐输入契约）。
- 实现 partial/incomplete policy：缺 required fact / 节点失败 / 超时 / 取消时不得标记 `complete`，产出 `missingFacts` + `failedNodes` + `limitation`。
- 实现 lineage / freshness / 单位与冲突的确定性处理：每个输出字段可追溯到 fact/evidence；跨节点 `asOf` 不一致时保留各自时间并产生 limitation。
- 新增 projection Eval（frontend 测试）：覆盖 complete / partial / freshness mismatch / 单位不兼容 / 重复冲突 / 确定性 hash bad case。
- **不接入生产 orchestrator**（仍 deferred，与 Runbook 16 边界一致）；projection 通过显式 `projectionId@version` 在 component/Eval 层调用，`projectionRef` 生产绑定随 orchestrator deferred；不形成 Action / Recommendation（Runbook 18）；不计算采购数量 / 日期 / 采购组；不调用 LLM；不接 Knowledge/RAG。

## Capabilities

### New Capabilities

- `output-projection`: 版本化 OutputProjection 注册表 + 校验、MaterialSupplySnapshot 首项、投影输入组装（PlanExecutionRecord + ReasoningFact[]）、partial/incomplete/lineage/freshness/limitations policy、确定性 hash、projection Eval。

### Modified Capabilities

- `read-plan-executor`: 扩展 executor 产出契约，使其在节点账本之外提供 projection 输入（`PlanExecutionRecord + successful ReasoningFact[]`），供 projection 消费。

## Impact

- 代码：`frontend/src/runtime/` 新增 projection 模块（registry + validator + assembler + MaterialSupplySnapshot + Eval）；`frontend/src/runtime/plan-executor/` 扩展产出以携带节点级 facts。
- 契约：新增 `output-projection` spec；修改 `read-plan-executor` spec 的 delta（ADDED requirement）。
- 依赖：复用现有 `PlanExecutorResult`、`RegistrySnapshot`、`ReasoningFact`（TS 侧需镜像最小契约）；不引入新运行时依赖。
- 验证：`npm --prefix frontend run verify`（projection Eval）；`openspec validate --all --strict`。
- 不影响：生产 orchestrator 接线、`projectionRef` 生产绑定、Action 路径、Python 侧 planner / semantic_planning 运行时行为。

```

## openspec/changes/sap-nexus-output-projection-registry/design.md

- Source: openspec/changes/sap-nexus-output-projection-registry/design.md
- Lines: 1-55
- SHA256: df28a843541ce077651ce8696e660c5de1326d984742c267dd10686251dae24f

```md
## Context

Runbook 16 在 TS 侧（`frontend/src/runtime/plan-executor/`）实现了 READ-only PlanExecutor：消费 PlanGraph v2 `readPartition`，按 ready-node 调度，产出 `PlanExecutorResult`（节点账本 + `succeeded/failed/timedOut/cancelled/blocked` 列表）。`PlanGraphV2.projectionRef: unknown[]` 是为投影预留的空占位符。

当前缺口：executor 不产出 `ReasoningFact[]` 或 `PlanExecutionRecord`，多 READ 结果无确定性组合投影，freshness / 完整性 / lineage / partial 失败无结构化口径。Runbook 17 补齐这条 `ReasoningFact[] -> MaterialSupplySnapshot` 投影链路。生产 orchestrator 接线仍 deferred（与 Runbook 16 边界一致），本轮在 component + Eval 层验证。

## Goals / Non-Goals

**Goals:**
- 版本化 `OutputProjection` 注册表 + 校验：projection 声明 required/optional input FactType、output schema、时间口径、partial policy。
- `MaterialSupplySnapshot` 作为首个注册 projection（组合事实束）。
- 投影输入组装：`PlanExecutorResult` + 节点级 Gateway 结果 -> `PlanExecutionRecord + successful ReasoningFact[]`。
- partial/incomplete/lineage/freshness/limitations 确定性 policy。
- 确定性输出 hash（相同输入 + projection version + snapshotId -> 相同 hash）。
- projection Eval（frontend 测试）覆盖核心与边界场景。

**Non-Goals:**
- 不接入生产 orchestrator（仍 deferred）。
- 不形成 Action / Recommendation（Runbook 18）。
- 不计算采购数量 / 日期 / 采购组；不调用 LLM；不接 Knowledge/RAG。
- 不做多 WRITE / Saga / 自动补偿。
- 深度技术设计（确切字段集、冲突裁决规则、JSON Schema 细节）留到 design 阶段 Design Doc。

## Decisions

### D1. 实现侧 = TS（`frontend/src/runtime/projection/`）
executor 与节点级 Gateway 结果均在 TS 运行时；projection 与 executor 同侧避免跨语言序列化往返。Python 侧 `semantic_planning` 契约不变，TS 侧镜像 `ReasoningFact` 最小契约。
- 备选：Python 侧实现（需把 executor 结果序列化回 Python，跨语言开销大，已否决）。

### D2. 通用版本化注册表，MaterialSupplySnapshot 为首项
`OutputProjectionRegistry` 按 `projectionId@version` 查找已注册 projection。projection 注册时声明 required/optional FactType、output schema、partial policy。本轮 projection 通过显式 `projectionId@version` 在 component/Eval 层调用；`projectionRef` 生产绑定随 orchestrator deferred。为 Runbook 18 RuleSet 留同构接口。
- 备选：仅硬编码 MaterialSupplySnapshot（已否决，违背 runbook「registered OutputProjection@version」且不利 Runbook 18 扩展）。

### D3. 投影输入组装 = 新增 assembler，executor 扩展产出携带节点 facts
新增 `ProjectionInputAssembler`：消费 `PlanExecutorResult` + 节点级 Gateway execute 结果，组装 `PlanExecutionRecord`（含 snapshotId / node ledger 摘要 / asOf）+ `successful ReasoningFact[]`。executor 扩展产出以暴露成功节点的 fact 数据（向后兼容新增字段，不改已有字段语义）。
- 备选：在 executor 内直接产出 projection（耦合 executor 与 projection，已否决）。

### D4. MaterialSupplySnapshot = 组合事实束（非派生业务指标）
snapshot = facts + lineage + freshness + completeness + limitations 元数据包裹，不做采购数量计算（runbook non-goal）。`completeness` 三态：`complete`（required fact 齐全 + 无失败节点）/ `partial`（有可选 fact 缺失或 limitation）/ `incomplete`（缺 required fact 或节点失败/超时/取消）。

### D5. 确定性 hash
对 normalized facts（排序后）+ projection version + snapshotId 计算确定性 hash；跨节点 `asOf` 不一致时保留各自时间并产生 limitation，不影响 hash 确定性。

## Risks / Trade-offs

- [executor 产出契约扩展可能影响 Runbook 16 已有测试] -> Mitigation: 向后兼容扩展（新增字段，不改已有字段语义与状态机）；回归 `frontend run verify`。
- [TS `ReasoningFact` 镜像与 Python dataclass 漂移] -> Mitigation: 镜像最小契约 + 共享 schema 校验；Python 侧运行时行为不变。
- [生产 orchestrator 仍 deferred，projection 未经生产链路验证] -> Mitigation: 本轮在 component + Eval 层充分验证；生产接线和 `projectionRef` 绑定在后续 runbook 完成。

## Open Questions（留到 design 阶段 Design Doc）

- `MaterialSupplySnapshot` 确切字段集与 JSON Schema。
- 重复 / 冲突 fact 的具体确定性裁决规则（如同一 predicate 多值）。
- 单位不兼容的具体处理（drop + limitation vs normalize）。
- executor 扩展产出的具体字段形态（如何暴露成功节点 fact 数据，向后兼容）。

```

## openspec/changes/sap-nexus-output-projection-registry/tasks.md

- Source: openspec/changes/sap-nexus-output-projection-registry/tasks.md
- Lines: 1-52
- SHA256: f013f6bc1141c93e0080a7ae8a1107639dd64c37b9f896c3d531a07ed2122950

```md
## 1. 类型与契约冻结

- [ ] 1.1 定义 TS `ReasoningFact` 最小镜像契约（与 Python `reasoning_fact.py` dataclass 对齐：factId / domain / businessObject / predicate / value / unit / deterministic / confidence / source / evidence / material / plant / asOf）
- [ ] 1.2 定义 `PlanExecutionRecord` 类型（`snapshotId` / node ledger 摘要 / `asOf` / succeeded/failed 节点列表）
- [ ] 1.3 定义 `MaterialSupplySnapshot` 类型（`asOf` / `sourceFreshness` / `completeness` / `facts` / `lineage` / `missingFacts` / `failedNodes` / `limitations`）
- [ ] 1.4 定义 `OutputProjection` 注册声明类型（`projectionId` / `version` / required FactTypes / optional FactTypes / output schema / time basis / partial policy）

## 2. OutputProjection 注册表 + 校验

- [ ] 2.1 实现 `OutputProjectionRegistry`：`register(declaration)` + `resolve(projectionId, version)`
- [ ] 2.2 未知 `projectionId` 或未注册 `version` fail-closed 并记录结构化失败
- [ ] 2.3 注册表单测（注册 + 解析 + 未知拒绝）

## 3. Executor 扩展产出（read-plan-executor 修改）

- [ ] 3.1 扩展 executor 产出，使 `SUCCEEDED` 节点暴露构建 `ReasoningFact` 所需的 per-node 数据（向后兼容新增字段，不改已有字段语义与状态机）
- [ ] 3.2 回归 Runbook 16 executor 测试（`frontend run verify` 中 executor 套件）不改动通过

## 4. 投影输入组装

- [ ] 4.1 实现 `ProjectionInputAssembler`：消费 `PlanExecutorResult` + 节点级 Gateway 结果 -> `PlanExecutionRecord` + successful `ReasoningFact[]`
- [ ] 4.2 仅 `SUCCEEDED` 节点贡献 facts；`FAILED`/`TIMED_OUT`/`CANCELLED`/`BLOCKED_*` 节点排除并记入 ledger 摘要
- [ ] 4.3 assembler 不读 raw Gateway payload 之外内容、不读 conversation text / model output
- [ ] 4.4 assembler 单测（双 READ 成功组装、非成功节点排除）

## 5. MaterialSupplySnapshot 投影

- [ ] 5.1 实现 `material-supply-snapshot` projection：产出组合事实束（facts + lineage + 元数据），不计算采购数量/日期/采购组
- [ ] 5.2 实现 `completeness` 三态：`complete`（required 齐全 + 无失败节点）/ `partial`（可选缺失或 limitation）/ `incomplete`（缺 required 或节点失败/超时/取消）
- [ ] 5.3 实现 `missingFacts` / `failedNodes` / `limitations` 填充
- [ ] 5.4 实现 `lineage`：每个输出 fact 字段可追溯到 source fact / evidence
- [ ] 5.5 实现 freshness mismatch：跨节点 `asOf` 不一致时保留各自时间到 `sourceFreshness` + 产生 limitation
- [ ] 5.6 实现 unit incompatibility 确定性处理 + limitation（不计入 `complete`）
- [ ] 5.7 实现 duplicate / conflicting fact（同 predicate 异值）确定性裁决 + limitation
- [ ] 5.8 实现确定性 hash：normalized facts（排序）+ projection `version` + `snapshotId`
- [ ] 5.9 注册 `material-supply-snapshot` 到 `OutputProjectionRegistry`

## 6. Projection Eval（frontend 测试）

- [ ] 6.1 complete snapshot 场景（双 READ 成功，lineage 完整率 100%）
- [ ] 6.2 incomplete 场景（单节点失败 -> missingFacts + failedNodes + limitation）
- [ ] 6.3 partial 场景（可选 fact 缺失 -> limitation）
- [ ] 6.4 freshness mismatch bad case
- [ ] 6.5 unit incompatibility bad case
- [ ] 6.6 duplicate / conflict fact bad case
- [ ] 6.7 确定性 hash（same input -> same hash；different input -> different hash）
- [ ] 6.8 projection 隔离测试（仅读 normalized facts + ledger metadata，不读 raw payload / model output）

## 7. 验证

- [ ] 7.1 `npm --prefix frontend run verify` 通过（含 projection Eval + executor 回归）
- [ ] 7.2 `openspec validate --all --strict` 通过

```

## openspec/changes/sap-nexus-output-projection-registry/specs/output-projection/spec.md

- Source: openspec/changes/sap-nexus-output-projection-registry/specs/output-projection/spec.md
- Lines: 1-122
- SHA256: ac5eeb516e700eb1d2f300c34880e3c3c93235827bd5ae6e5734db4a6f971de6

[TRUNCATED]

```md
## ADDED Requirements

### Requirement: Versioned OutputProjection registry with declared input contract

The system SHALL provide an `OutputProjectionRegistry` that registers projections by `projectionId@version`. Each registered projection SHALL declare its required input FactTypes, optional input FactTypes, output schema, time basis (`asOf` policy), and partial policy. The registry SHALL resolve a projection by exact `projectionId` and `version`. A lookup for an unknown `projectionId` or unregistered `version` SHALL fail closed and record a structured failure. The registry MUST NOT call the LLM, the Gateway, or SAP.

#### Scenario: Registered projection resolved by id and version

- **WHEN** the registry resolves a registered `projectionId@version`
- **THEN** the registry returns the matching projection declaration
- **AND** the declaration exposes its required/optional FactTypes, output schema, time basis, and partial policy

#### Scenario: Unknown projection or version rejected

- **WHEN** the registry resolves a `projectionId` or `version` that is not registered
- **THEN** the registry rejects the lookup fail-closed
- **AND** records a structured failure identifying the unknown `projectionId`/`version`

### Requirement: Projection input assembly from PlanExecutorResult

The system SHALL provide a `ProjectionInputAssembler` that consumes a `PlanExecutorResult` plus the per-node Gateway execute results and produces a `PlanExecutionRecord` (carrying `snapshotId`, node ledger summary, and `asOf`) together with the successful `ReasoningFact[]`. Only `SUCCEEDED` nodes SHALL contribute facts. Nodes in `FAILED`, `TIMED_OUT`, `CANCELLED`, `BLOCKED_DEPENDENCY`, or `BLOCKED_APPROVAL` state SHALL NOT contribute facts. The assembler MUST NOT read raw Gateway payload beyond what is needed to build normalized facts, and MUST NOT read conversation text or model output.

#### Scenario: Dual READ success assembles facts

- **WHEN** the assembler receives a `PlanExecutorResult` where both READ nodes are `SUCCEEDED`
- **THEN** the assembler produces a `PlanExecutionRecord` and a `ReasoningFact[]` containing one fact per successful node
- **AND** the `PlanExecutionRecord` carries the bound `snapshotId`

#### Scenario: Non-succeeded nodes excluded from facts

- **WHEN** the assembler receives a `PlanExecutorResult` containing a `FAILED` or `TIMED_OUT` or `CANCELLED` node
- **THEN** the assembler excludes that node from the `ReasoningFact[]`
- **AND** records the node in the `PlanExecutionRecord` node ledger summary

#### Scenario: Missing FactBuilder degrades gracefully

- **WHEN** a `SUCCEEDED` node's `capabilityId` has no registered `FactBuilder`
- **THEN** the assembler contributes no fact for that node
- **AND** records the node's required FactType in `missingFacts` with reason `no_fact_builder`
- **AND** the projection yields `incomplete`

### Requirement: MaterialSupplySnapshot projection produces composite fact bundle

The system SHALL provide a `material-supply-snapshot` projection registered in the `OutputProjectionRegistry` that projects a `PlanExecutionRecord` plus successful `ReasoningFact[]` into a `MaterialSupplySnapshot` consisting of `{ asOf, sourceFreshness, completeness, facts, lineage, missingFacts, failedNodes, limitations }`. The projection SHALL treat the snapshot as a composite fact bundle with lineage and metadata, NOT a derived business metric, and MUST NOT compute procurement quantities, dates, or purchasing groups. Every output fact field SHALL be traceable via `lineage` to its source fact and evidence.

#### Scenario: Dual READ success yields complete snapshot with full lineage

- **WHEN** the projection receives a `PlanExecutionRecord` with both READ facts present, no failed nodes, and all nodes sharing the same `dataAsOf` (no freshness mismatch)
- **THEN** the projection yields a `MaterialSupplySnapshot` with `completeness` = `complete`
- **AND** no `limitations` are produced
- **AND** every output fact field has a `lineage` entry tracing to its source fact/evidence
- **AND** lineage completeness is 100%

### Requirement: Partial and incomplete completeness policy

The projection SHALL derive `completeness` as one of `complete`, `partial`, or `incomplete`. `complete` requires all required FactTypes present and no failed nodes. `partial` applies when optional facts are missing or a `limitation` is present but all required facts exist. `incomplete` applies when any required FactType is missing or any node is `FAILED`, `TIMED_OUT`, or `CANCELLED`. The projection SHALL populate `missingFacts`, `failedNodes`, and `limitations` accordingly. The projection MUST NOT mark a snapshot `complete` when a required fact is missing or a node failed/timed out/was cancelled.

#### Scenario: Single node failure yields incomplete snapshot

- **WHEN** the projection receives a `PlanExecutionRecord` where one READ node is `FAILED`
- **THEN** the projection yields `completeness` = `incomplete`
- **AND** populates `failedNodes` with the failed node id
- **AND** populates `missingFacts` with the required FactType the failed node was to produce

#### Scenario: Missing optional fact yields partial snapshot

- **WHEN** the projection receives a `PlanExecutionRecord` where all required FactTypes are present but an optional FactType is absent
- **THEN** the projection yields `completeness` = `partial`
- **AND** records a `limitation` describing the missing optional fact

### Requirement: Freshness, unit, and conflict determinism

The projection SHALL handle cross-node `asOf` mismatch by preserving each node's own time in `sourceFreshness` and producing a `limitation`; it MUST NOT collapse distinct `asOf` values into a single value. The projection SHALL handle unit incompatibility deterministically (record a `limitation`, exclude the incompatible field from `complete` accounting). The projection SHALL handle duplicate or conflicting facts (same predicate, differing values) deterministically and record a `limitation`. Numeric, unit, and time conversions SHALL be performed only by versioned deterministic rules.

#### Scenario: Freshness mismatch produces limitation

- **WHEN** two successful facts carry different `asOf` times
- **THEN** the projection preserves each `asOf` in `sourceFreshness`
- **AND** produces a `limitation` describing the freshness mismatch


```

Full source: openspec/changes/sap-nexus-output-projection-registry/specs/output-projection/spec.md

## openspec/changes/sap-nexus-output-projection-registry/specs/read-plan-executor/spec.md

- Source: openspec/changes/sap-nexus-output-projection-registry/specs/read-plan-executor/spec.md
- Lines: 1-17
- SHA256: 91aaf725e0496efe182263313118872a8b030cf07000d372688482c2d6bb55a8

```md
## ADDED Requirements

### Requirement: Executor exposes projection input facts for succeeded nodes

The system SHALL extend the READ PlanExecutor output so that, alongside `PlanExecutorResult`, the executor exposes the per-node data required to build projection input for `SUCCEEDED` nodes. The exposed data SHALL be sufficient for a `ProjectionInputAssembler` to construct `ReasoningFact[]` and a `PlanExecutionRecord` without re-calling the Gateway. The extension SHALL be backward-compatible: existing `PlanExecutorResult` fields and their semantics, and the node state machine, SHALL remain unchanged. The executor MUST NOT call the LLM, replan, or bypass the Gateway.

#### Scenario: Succeeded node exposes fact-building data

- **WHEN** a READ node reaches `SUCCEEDED` after Gateway execute
- **THEN** the executor output exposes the per-node data needed to build that node's `ReasoningFact`
- **AND** the data is available without re-calling the Gateway

#### Scenario: Existing PlanExecutorResult semantics preserved

- **WHEN** the executor runs against an existing dual-READ `PlanExecutorResult` fixture
- **THEN** the existing `nodeLedger`, `succeeded`, `failed`, `timedOut`, `cancelled`, and `blocked` fields retain their prior semantics
- **AND** existing Runbook 16 executor tests pass without modification

```

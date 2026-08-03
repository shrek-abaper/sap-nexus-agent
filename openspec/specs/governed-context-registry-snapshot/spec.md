# governed-context-registry-snapshot Specification

## Purpose
TBD - created by archiving change sap-nexus-governed-context-registry-snapshot. Update Purpose after archive.
## Requirements
### Requirement: Governed context binds one RegistrySnapshot

系统 SHALL 为每次 Agent run 构造 `GovernedContext`，携带 `principal`、`scopes`、非空 `snapshotId` 与 `registryVersion`。intent 识别、capability recall、matcher、planner 与 approval SHALL 绑定同一 `GovernedContext.snapshotId`。`snapshotId` SHALL 来自 `build_registry_snapshot` 产出的非空 `RegistrySnapshot`，不得由 request body、prompt、history 或 LLM output 提供。

#### Scenario: 同一 run 共享同一非空 snapshotId

- **WHEN** 一次 Agent run 执行 intent 识别、matcher 决策与 planner dry-run
- **THEN** intent、matcher、planner 记录使用同一非空 `snapshotId`
- **AND** 该 `snapshotId` 来自 `run_query` 入口构造的 `GovernedContext`

#### Scenario: snapshotId 不可由请求或模型提供

- **WHEN** request body、prompt、history 或 LLM output 携带 `snapshotId` 字段
- **THEN** 系统忽略请求/模型提供的 `snapshotId`
- **AND** 仅采用服务端 `GovernedContext` 的 `snapshotId`

### Requirement: Snapshot lease and drift fail-closed

系统 SHALL 在 `GovernedContext` 构造时创建 `SnapshotLease` 持有同一 `RegistrySnapshot`。matcher 与 planner SHALL 消费 `lease.snapshotId`，不得另行加载 snapshot。当 snapshot 缺失、`snapshotId` 在 run 内漂移或 principal 与 snapshot 不匹配时，系统 SHALL 返回结构化 `PlannerFailure`，不得静默降级为空 dry-run 或 `None`。

#### Scenario: snapshot 缺失 fail-closed

- **WHEN** `run_query` 入口无法加载 `RegistrySnapshot`（source 缺失或 YAML 损坏）
- **THEN** 系统返回 `PlannerFailure`（`error_type=SOURCE_LOAD_ERROR` 或 `SNAPSHOT_MISSING`）含 audit evidence
- **AND** 不产生空 dry-run 或静默 `None`

#### Scenario: snapshot 漂移 fail-closed

- **WHEN** planner 阶段的 `snapshotId` 与 `GovernedContext.snapshotId` 不一致
- **THEN** 系统返回 `PlannerFailure`（`error_type=SNAPSHOT_DRIFT`）含 audit evidence
- **AND** 不继续执行计划

### Requirement: Visibility pre-filter before LLM prompt

系统 SHALL 在进入 LLM prompt 组装前，基于 governance（`sideEffect`/`dataClassification`）与 snapshot 投影 `CapabilityCard[]`，经 visibility pre-filter 产出 `VisibleCapabilitySet`。`principal` 绑定到 `GovernedContext` 用于同快照与审计证明；role-based capability 可见性推迟到 Registry 具备 `visibilityScope` 字段后。不可见 capability SHALL 在进入 LLM prompt 前移除，不得先暴露给模型再依赖执行期拒绝。`VisibleCapabilitySet` 是 intent 识别、matcher 决策与候选召回的唯一能力来源。Gateway execute SHALL 再次授权（双重校验）。

#### Scenario: 不可见能力不进入 LLM prompt

- **WHEN** principal 对某 capability 不可见
- **THEN** 该 capability 不出现在 `VisibleCapabilitySet` 中
- **AND** 不进入 LLM prompt 的能力候选上下文

#### Scenario: principal 绑定与 cross-principal 隔离

- **WHEN** 一次 Agent run 构造 `GovernedContext`
- **THEN** `principal` 绑定到 `GovernedContext` 用于同快照与审计证明
- **AND** cross-principal 隔离在 durable 层 fail-closed（P0B 已实现：principal A 不可读/续/审批 principal B 的 run/approval/session）
- **AND** 决策层 visibility pre-filter 基于 governance 维度（role-based 可见性推迟到 Registry 具备 `visibilityScope`）

### Requirement: Structured planner failure

系统 SHALL 定义 `PlannerFailure`，携带稳定 `error_type`（`SNAPSHOT_MISSING`、`SNAPSHOT_DRIFT`、`PRINCIPAL_MISMATCH`、`SOURCE_LOAD_ERROR`、`VISIBILITY_DENIED`）、`message`、`snapshot_id` 与 `audit_evidence`。source load 失败、snapshot 漂移与 visibility denial SHALL 返回 `PlannerFailure`，不得 `except: return None` 静默吞错。

#### Scenario: source load 失败返回结构化错误

- **WHEN** registry source 加载抛出异常
- **THEN** 系统返回 `PlannerFailure(error_type=SOURCE_LOAD_ERROR)` 含 audit evidence
- **AND** `AgentOutcome` 携带 `planner_failure` 而非空 `dry_run`

#### Scenario: visibility denial 返回结构化错误

- **WHEN** principal 对全部候选 capability 不可见
- **THEN** 系统返回 `PlannerFailure(error_type=VISIBILITY_DENIED)` 含 audit evidence
- **AND** 不静默返回空结果

### Requirement: CapabilityCard safe projection

`CapabilityCard` SHALL 携带 `registry_snapshot_id`（绑定其投影来源的 `RegistrySnapshot`）。`CapabilityCard` SHALL NOT 包含 `rfcName`、`serviceUrl`、`entitySet`、`httpMethod`、`headers`、`credentialRef`、`rawSql` 或任何 technical binding mapping。`discover_cards` SHALL 绑定 snapshot 投影，不得弃用 snapshot 参数。

#### Scenario: CapabilityCard 携带 registry_snapshot_id

- **WHEN** `discover_cards` 从 snapshot 投影 capability
- **THEN** 产出的 `CapabilityCard` 携带非空 `registry_snapshot_id`
- **AND** 该 id 与 `GovernedContext.snapshotId` 一致

#### Scenario: CapabilityCard 不泄漏技术绑定

- **WHEN** `discover_cards` 投影 capability
- **THEN** `CapabilityCard` 不包含 `rfcName`、`serviceUrl`、`credentialRef`、`rawSql` 或 technical mapping
- **AND** 仅暴露 semantic 字段（capabilityId、name、inputs、governance、visibility、producesFactTypes）

### Requirement: Capability kind projected from Registry snapshot

系统 SHALL 从 Registry snapshot 投影 capability kind、`sideEffect` 与 `approvalPolicy`，不得以硬编码 capability id 集合兜底判定 Action。orchestrator SHALL 用 `CapabilityCard.governance.requires_approval` 判定 Action，而非 `capability_id in ACTION_CAPABILITY_IDS`。

#### Scenario: kind 从 snapshot 投影

- **WHEN** orchestrator 判定 capability 是否为 Action
- **THEN** 判定基于 `CapabilityCard.governance.requires_approval`（来自 snapshot 投影）
- **AND** 不依赖硬编码 capability id 集合


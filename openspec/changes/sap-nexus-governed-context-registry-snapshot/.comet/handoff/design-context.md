# Comet Design Handoff

- Change: sap-nexus-governed-context-registry-snapshot
- Phase: design
- Mode: compact
- Context hash: 41ade3e6e335a0e23814c4949fd0a5d8124e97175bf2298e612baf69b57ae1f8

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/sap-nexus-governed-context-registry-snapshot/proposal.md

- Source: openspec/changes/sap-nexus-governed-context-registry-snapshot/proposal.md
- Lines: 1-36
- SHA256: 3ebf3df607b5e0a07be15a3ed50a772f3d0b1d567b81e9b49b33e67a69f9ba9a

```md
## Why

当前一次 Agent run 的意图识别、候选召回、matcher 与 planner 各自加载或忽略 `RegistrySnapshot`，无法证明它们使用同一快照：matcher（`select_capability`）完全不接 snapshot；`EscalationHandoff.registry_snapshot_id` 恒为空串（`getattr(parse_result, "registry_snapshot_id", "")`，`IntentParseResult` 不携带该字段）；planner 在 `_compile_dry_run_safely` 中另行加载 snapshot，失败时 `except Exception: return None` 静默退化为 `dry_run=None`。同时 `filter_visible` 无任何运行时调用方，principal 止步于 Node durable 鉴权层（`executeRunnerInBackground` 收 `principalId` 仅用于 `run.principalId` 校验，`runner()` 不传 Python），从未到达 intent/matcher/planner。结果是不可见能力可能在 visibility 过滤前进入 LLM prompt，snapshot 漂移或 source load 失败被静默吞掉，cross-principal fail-closed 在决策层无法验收。Runbook 13 关闭这些缺口，为 Runbook 14-22 的召回、规划、执行、投影、建议、叙事和审批提供同快照治理基础。

## What Changes

- 新增 `GovernedContext`（principal + scopes + snapshotId + registryVersion）作为一次 run 的受治理上下文，贯穿 intent、recall、matcher、planner、approval。
- 新增 `SnapshotLease`：持有并校验同一非空 `RegistrySnapshot`；snapshot 缺失、漂移或 principal 不匹配时结构化 fail-closed。
- 新增 `VisibleCapabilitySet`：principal/visibility pre-filter 后的安全 `CapabilityCard[]`，在进入 LLM prompt 前移除不可见能力。
- 新增 `PlannerFailure`：source load 失败、snapshot 漂移、visibility denial 返回稳定 error type + audit evidence，替代 `except: return None` 静默降级。
- `EscalationHandoff.registry_snapshot_id` 绑定为非空（从 `GovernedContext` 填入），证明 matcher 与 planner 使用同一快照。
- `CapabilityCard` 新增 `registry_snapshot_id` 字段；`discover_cards` 绑定 snapshot，不再 `del snapshot` 弃用。
- capability kind / sideEffect / approvalPolicy 从 Registry snapshot 投影，不再以 `capability_id in ACTION_CAPABILITY_IDS` 兜底。
- principal 透传从 Node durable 鉴权层延伸到 Python agent 决策层（CLI `--principal` -> `run_query` -> visibility pre-filter）。
- `ApprovalRecord` 新增 `registry_snapshot_id` 字段（pending 生成时填入），使 approval 记录携带同快照标识；跨语言 approval store 的「漂移使审批失效」执行校验留 Runbook 21。
- `CapabilityCard` 安全投影保持不暴露 RFC、URL、credential、raw SQL 或 technical mapping（现状已不读 `executorBinding`，本轮固化）。

## Capabilities

### New Capabilities

- `governed-context-registry-snapshot`: 一次 Agent run 的受治理上下文与统一 RegistrySnapshot 绑定契约——`GovernedContext`、`SnapshotLease`、`VisibleCapabilitySet`、`PlannerFailure`，principal/visibility pre-filter 与结构化 fail-closed 错误模型。

### Modified Capabilities

- `semantic-match-decision`: matcher 决策路径接入 visibility pre-filter 并消费同一非空 snapshotId；`EscalationHandoff.registry_snapshot_id` 由 `GovernedContext` 填入，不再恒空。
- `planner-dry-run`: planner 绑定同一非空 snapshotId；`CapabilityCard` 携带 `registry_snapshot_id` 且 `discover_cards` 绑定 snapshot；capability kind / sideEffect / approvalPolicy 从 snapshot 投影。
- `trusted-principal-scope`: principal 透传从 durable store 鉴权层延伸到 Python agent 决策层（CLI -> `run_query` -> visibility pre-filter）。
- `pr-create-action`: `ApprovalRecord` 契约新增 `registry_snapshot_id` 字段（pending 生成时从 `GovernedContext` 填入），使 approval 记录携带同快照标识；Node/Java approval store 的漂移使审批失效的执行校验留 Runbook 21。

## Impact

- **代码**：`agent/sap_nexus_agent/` 新增 governed_context 模块；修改 `orchestrator`、`capability_selector`、`match_decision`、`visibility`、`planner/capability_card`、`planner/handoff`、`intent`、`llm_intent`、`cli`、`approval`；`frontend/src/runtime/agent-runtime-adapter.ts` 透传 principal 到 Python CLI。
- **契约**：1 个新 spec（`governed-context-registry-snapshot`）+ 4 个现有 spec 的 requirements delta。
- **测试**：visibility leakage = 0、cross-principal fail-closed（决策层，非仅 durable 层）、snapshot 漂移 / source load 失败结构化错误、`CapabilityCard` 安全投影回归。
- **边界**：不执行 SAP WRITE；不改 matcher 五态决策算法（只绑 snapshot/visibility）；不重建身份/状态/审批/事件机制（复用 P0B）；不夹带 Runbook 14 recall / 15 PlanGraph v2 / 16 PlanExecutor / 20 UI。

```

## openspec/changes/sap-nexus-governed-context-registry-snapshot/design.md

- Source: openspec/changes/sap-nexus-governed-context-registry-snapshot/design.md
- Lines: 1-90
- SHA256: 5073220dad1eb1c256fdefd501d34ce7c4fde2a097076c0d0f439f01b01dc3ba

[TRUNCATED]

```md
## Context

P0B trusted/durable runtime 已归档：principal 在 Node backend 服务端注入并用于 durable Run/Session/Approval 鉴权（cross-principal fail-closed 在 store 层已实现）。S1 提供 `RegistrySnapshot`（四源：`ontology/capability-relations.yaml`、`ontology/fact-types.yaml`、`registry/capabilities.yaml`、`registry/executor-bindings.yaml`）与 `build_registry_snapshot`；S2-A/S2-B 提供 `MatchDecision`、`CapabilityCard`、`filter_visible`、`PlanCompiler` dry-run。

但 Python agent 决策层与 snapshot/principal 解耦：`run_query` 不接收 principal；`select_capability` 只消费 `IntentParseResult`；`EscalationHandoff.registry_snapshot_id` 恒空；`filter_visible` 无运行时调用方；`_compile_dry_run_safely` 另行加载 snapshot 并 `except: return None` 静默降级；`discover_cards` 中 `del snapshot`。本设计在 P0B + S1/S2 之上建立受治理上下文，把同快照与 principal/visibility 贯穿到决策层。

约束：复用 P0B 身份/状态/审批/事件机制与 S1 snapshot 构建；不改 matcher 五态算法；不执行 SAP WRITE；不夹带 Runbook 14-16/20。

## Goals / Non-Goals

**Goals:**
- `GovernedContext` 贯穿 intent、recall、matcher、planner、approval，绑定同一非空 `snapshotId`。
- principal/visibility pre-filter 在进入 LLM prompt 前完成；不可见 capability 不进入候选。
- snapshot 缺失/漂移、principal 不匹配、source load 失败返回结构化 `PlannerFailure`（稳定 error type + audit evidence），非静默 `None`。
- `CapabilityCard` 携带 `registry_snapshot_id`，安全投影不泄漏技术绑定。
- capability kind / sideEffect / approvalPolicy 从 snapshot 投影。
- `ApprovalRecord` 携带 `registry_snapshot_id`（Node/Java 漂移执行校验留 Runbook 21）。

**Non-Goals:**
- 不改召回算法、不实现 PlanGraph v2 / PlanExecutor / OutputProjection / UI。
- 不接 Knowledge/RAG；不执行新 SAP WRITE。
- 不改 matcher 五态决策算法（只前置 visibility + 绑 snapshotId）。
- 不重建第二套身份/状态/审批/事件机制。
- 不实现 approval store 的「漂移使审批失效」执行校验（Runbook 21）。

## Decisions

### D1：GovernedContext 在 Python `run_query` 入口构造
- **选择**：`run_query` 入口接收 principal（从 CLI 透传）+ 加载 snapshot（复用 `_default_planner_sources` / `build_registry_snapshot`），构造 `GovernedContext { principal, scopes, snapshotId, registryVersion }` + `SnapshotLease`，贯穿下游。
- **理由**：snapshot 四源加载已在 Python（S1）；principal 由 Node 服务端注入（P0B 契约）。Python 入口构造让 GovernedContext 权威落在决策层，Node 只负责透传 principal，职责清晰。
- **备选**：Node 构造完整 GovernedContext 传 Python -- 否决：snapshot 构建在 Python，Node 重复加载违反 DRY；且 Node 不应掌握 snapshot 内部结构。

### D2：principal 透传形态 = stdin JSON（与 `--context` 同模式）
- **选择**：CLI 新增 `--principal` 读 stdin JSON（`{principalId, role, dataScope}`）；或与 `--context` 合并为单一 stdin payload。
- **理由**：principal 需多字段（principalId + role + dataScope），CLI arg 传 JSON 不优雅；复用 `--context` 的 stdin 模式保持一致。
- **备选**：CLI `--principal-id` 单字段 -- 否决：丢失 role/dataScope，visibility pre-filter 无法基于 role。
- **待 design 阶段定**：独立 `--principal` 还是合并 stdin payload（避免与 `--context` stdin 冲突）。

### D3：SnapshotLease 持有 + 漂移即 fail-closed
- **选择**：`run_query` 入口加载 snapshot 并持有 `SnapshotLease`（含 `snapshotId`、`registryVersion`、`sources`）。matcher / planner 消费 `lease.snapshotId`；planner 不再自行加载（`_compile_dry_run_safely` 改为消费 lease）。若 lease 缺失或 planner 阶段 snapshotId 与 lease 不一致 -> `PlannerFailure(SNAPSHOT_DRIFT)`。
- **理由**：证明 matcher 与 planner 同快照；消除 planner 另行加载的歧义。
- **备选**：planner 仍自行加载但校验 snapshotId 相等 -- 否决：两次加载无意义且可能漂移。

### D4：fail-closed error model = `PlannerFailure`
- **选择**：`PlannerFailure(error_type, message, snapshot_id, audit_evidence)`，`error_type` ∈ {`SNAPSHOT_MISSING`, `SNAPSHOT_DRIFT`, `PRINCIPAL_MISMATCH`, `SOURCE_LOAD_ERROR`, `VISIBILITY_DENIED`}。替代 `_compile_dry_run_safely` 的 `except: return None`。`AgentOutcome` 增 `planner_failure` 字段。
- **理由**：稳定 error type 支持评测与审计；audit evidence 提供漂移/拒绝证据。
- **备选**：复用现有 `error_type` 字符串 -- 否决：现有 error_type 面向 Gateway 错误，不含 snapshot/visibility 语义。

### D5：visibility pre-filter 在 matcher 之前、LLM prompt 组装处生效
- **选择**：用 `GovernedContext.principal` + snapshot 投影 `CapabilityCard[]` -> `filter_visible`（扩展 principal/role 维度）-> `VisibleCapabilitySet`。LLM prompt 只放 VisibleCapabilitySet 的 capability；rule 路径同样过滤。matcher `select_capability` 接收 VisibleCapabilitySet。
- **理由**：不可见能力在进入模型前移除（runbook §5）；Gateway execute 仍二次授权（既有契约）。
- **备选**：仅依赖 Gateway 执行期拒绝 -- 否决：违反「不可见能力不得先暴露给模型再依赖执行期拒绝」（架构 §4.5）。
- **待 design 阶段定**：`filter_visible` 的 principal 维度具体规则（role -> 可见 capability 集合的映射来源）。

### D6：capability kind 从 snapshot 投影，替代 `ACTION_CAPABILITY_IDS`
- **选择**：orchestrator 用 `CapabilityCard.governance.requires_approval`（已从 snapshot 投影）判 Action，移除 `capability_id in ACTION_CAPABILITY_IDS` 硬编码集合。
- **理由**：kind/sideEffect/approvalPolicy 应来自 Registry（runbook §6），而非硬编码 ID。
- **备选**：保留 ACTION_CAPABILITY_IDS 作 fallback -- 否决：违反「全部从 Registry projection 获得」。

### D7：`ApprovalRecord` 新增 optional `registry_snapshot_id`（向后兼容）
- **选择**：Python `ApprovalRecord` 加 `registry_snapshot_id: str = ""`，`from_dict`/`to_dict` 兼容；`create_approval_record` 从 GovernedContext 填入。Node 侧 `ApprovalRecord` 同步加字段（序列化兼容）。Java/Node approval store 的「漂移使审批失效」执行校验留 Runbook 21。
- **理由**：满足 §6「approval 记录使用同一 snapshotId」；字段 optional 向后兼容，不破坏 P0B durable store。
- **备选**：本轮不动 approval，全留 Runbook 21 -- 否决：用户已确认决策层 + approval 字段方案。

## Risks / Trade-offs

- **[principal 透传触及 Node + Python]** -> Mitigation: 最小改动--`executeRunnerInBackground` -> `runner` 传 principal，CLI 加 `--principal`；Python `run_query` 新参数默认 None 时用 `PLACEHOLDER_PRINCIPAL`（与 frontend 一致），本地 dev 不崩，共享环境由 Node 注入。
- **[visibility pre-filter 改变 matcher 候选输入]** -> Mitigation: 不改五态算法，只前置过滤；现有 matcher Eval 6/6 须回归通过；新增 visibility leakage = 0 用例。
- **[ApprovalRecord 字段扩散到 Node/Java]** -> Mitigation: optional 字段 + `.get` 默认空，向后兼容；执行校验留 21，本轮不动 store 治理语义。
- **[snapshot 加载性能]** -> Mitigation: 单次 run 加载一次，复用 S1 `build_registry_snapshot`；`SnapshotLease` 持有避免重复加载。
- **[run_query 缺省 principal 行为歧义]** -> Mitigation: design 阶段明确--CLI 缺省 = `PLACEHOLDER_PRINCIPAL`（local-user-0001/operator/default），不 fail-closed；真实 cross-principal 校验由测试注入多 principal 覆盖。

## Migration Plan

1. 新增 `agent/sap_nexus_agent/governed_context.py`（GovernedContext / SnapshotLease / VisibleCapabilitySet / PlannerFailure）。
2. `run_query` 增 `principal` / `governed_context` 参数（默认 None -> PLACEHOLDER）；入口构造 lease。
3. `select_capability` 接 VisibleCapabilitySet；`EscalationHandoff.registry_snapshot_id` 从 lease 填入。
4. `discover_cards` 绑 snapshot + `CapabilityCard.registry_snapshot_id`；`_compile_dry_run_safely` 消费 lease，失败返 `PlannerFailure`。
5. `filter_visible` 增 principal 维度并接入 matcher 路径。
6. `ApprovalRecord` 加 `registry_snapshot_id`；`create_approval_record` 填入。

```

Full source: openspec/changes/sap-nexus-governed-context-registry-snapshot/design.md

## openspec/changes/sap-nexus-governed-context-registry-snapshot/tasks.md

- Source: openspec/changes/sap-nexus-governed-context-registry-snapshot/tasks.md
- Lines: 1-55
- SHA256: 7a9c4656077a526765892c6b9d075720b8ae07e9bab971f2d6857590c952f420

```md
## 1. GovernedContext 与受治理上下文契约

- [ ] 1.1 新增 `agent/sap_nexus_agent/governed_context.py`，定义 `GovernedContext`（`principal`/`scopes`/`snapshotId`/`registryVersion`）、`SnapshotLease`（持有并校验 `RegistrySnapshot`）、`VisibleCapabilitySet`、`PlannerFailure`（`error_type`/`message`/`snapshot_id`/`audit_evidence`）
- [ ] 1.2 `PlannerFailure.error_type` 枚举固化为 `SNAPSHOT_MISSING` / `SNAPSHOT_DRIFT` / `PRINCIPAL_MISMATCH` / `SOURCE_LOAD_ERROR` / `VISIBILITY_DENIED`

## 2. run_query 入口绑定 GovernedContext

- [ ] 2.1 `run_query` 增 `principal` / `governed_context` 参数（默认 `None` 时回退 `PLACEHOLDER_PRINCIPAL`，本地 dev 不崩）
- [ ] 2.2 入口构造 `SnapshotLease`（复用 `_default_planner_sources` + `build_registry_snapshot`），保证 `snapshotId` 非空并贯穿下游
- [ ] 2.3 `AgentOutcome` 增 `planner_failure` 字段，承载结构化失败

## 3. visibility pre-filter 接入 matcher 决策路径

- [ ] 3.1 `filter_visible` 扩展 principal/role 维度（基于 `CapabilityCard` + `GovernedContext.principal`）
- [ ] 3.2 在 matcher 决策前构造 `VisibleCapabilitySet`（`discover_cards` -> `filter_visible`），作为 intent/matcher/召回的唯一能力来源
- [ ] 3.3 `select_capability` 接收 `VisibleCapabilitySet`，不可见能力不进入候选

## 4. matcher 绑定非空 snapshotId

- [ ] 4.1 `EscalationHandoff.registry_snapshot_id` 从 `GovernedContext` 填入（非空），不再 `getattr` 默认空串
- [ ] 4.2 `IntentParseResult` 或 matcher 入口携带 `snapshotId`，使 handoff 与决策可追溯同快照

## 5. planner 绑定同一 snapshot + 结构化 fail-closed

- [ ] 5.1 `discover_cards` 绑定 snapshot（移除 `del snapshot`），`CapabilityCard` 增 `registry_snapshot_id` 字段并填入
- [ ] 5.2 `_compile_dry_run_safely` 消费 `SnapshotLease`（不再另行加载 snapshot），`snapshotId` 漂移返 `PlannerFailure(SNAPSHOT_DRIFT)`
- [ ] 5.3 source load 失败返 `PlannerFailure(SOURCE_LOAD_ERROR)` + audit evidence，不再 `except Exception: return None`

## 6. capability kind 从 Registry snapshot 投影

- [ ] 6.1 orchestrator 用 `CapabilityCard.governance.requires_approval` 判定 Action，移除 `capability_id in ACTION_CAPABILITY_IDS` 兜底
- [ ] 6.2 kind / sideEffect / approvalPolicy 全部从 snapshot 投影，回归现有 inventory/PO/PR 路径

## 7. ApprovalRecord 携带 registry_snapshot_id

- [ ] 7.1 Python `ApprovalRecord` 增 `registry_snapshot_id` 字段，`from_dict`/`to_dict` 向后兼容（`.get` 默认空）
- [ ] 7.2 `create_approval_record` 从 `GovernedContext` 填入 `registry_snapshot_id`
- [ ] 7.3 Node 侧 `ApprovalRecord` 同步加 `registrySnapshotId` 字段（序列化兼容，不改变 store 治理语义；漂移执行校验留 Runbook 21）

## 8. principal 透传 Node backend -> Python agent

- [ ] 8.1 `cli.py` 加 `--principal`（stdin JSON，与 `--context` 模式对齐或合并 payload，design 阶段定形态）
- [ ] 8.2 `frontend/src/runtime/agent-runtime-adapter.ts` 的 `executeRunnerInBackground` -> `runner` 传 principal；`runLocalPythonAgent` spawn 时传 `--principal`

## 9. CapabilityCard 安全投影固化

- [ ] 9.1 确认 `discover_cards` 不读 `executorBinding`/`executor`，补 negative test 断言 `CapabilityCard` 不含 `rfcName`/`serviceUrl`/`credentialRef`/`rawSql`/technical mapping

## 10. 测试与验证

- [ ] 10.1 visibility leakage = 0 测试：不可见 capability 不进入 LLM prompt 候选与 matcher 决策
- [ ] 10.2 cross-principal 决策层 fail-closed 测试：多 principal 注入，A 不可见能力不产生 SELECT/候选
- [ ] 10.3 snapshot 漂移 / source load 失败 / visibility denial 返回结构化 `PlannerFailure` 测试
- [ ] 10.4 matcher Eval 6/6 回归 + `CapabilityCard` 安全投影回归 + 现有 inventory/PO/PR 路径回归
- [ ] 10.5 运行 `openspec validate --all --strict` + `.venv/bin/python -m pytest agent/tests -q` + `scripts/verify-agent-callplan-evidence.sh` + `npm --prefix frontend run verify`

```

## openspec/changes/sap-nexus-governed-context-registry-snapshot/specs/governed-context-registry-snapshot/spec.md

- Source: openspec/changes/sap-nexus-governed-context-registry-snapshot/specs/governed-context-registry-snapshot/spec.md
- Lines: 1-92
- SHA256: 48c8017fd515b3f4ea48d2808c7aa7fbd40205b51abe655fdc5a14ac9924d1e2

[TRUNCATED]

```md
## ADDED Requirements

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

```

Full source: openspec/changes/sap-nexus-governed-context-registry-snapshot/specs/governed-context-registry-snapshot/spec.md

## openspec/changes/sap-nexus-governed-context-registry-snapshot/specs/planner-dry-run/spec.md

- Source: openspec/changes/sap-nexus-governed-context-registry-snapshot/specs/planner-dry-run/spec.md
- Lines: 1-53
- SHA256: a0ee107dfa7b579190f8eda69fae8966ef6c5098f671fec8c38778e8cadfd72e

```md
## MODIFIED Requirements

### Requirement: CapabilityCard discovery

The system SHALL project registered capabilities into `CapabilityCard`s carrying `capabilityId`, `name`, `inputs`, `governance`, `visibility`, `producesFactTypes` (derived from the capability `outputs.factTypeRef`), and `registry_snapshot_id` (bound to the `RegistrySnapshot` the card was projected from), derived from the Registry closed set and the bound Registry Snapshot. `producesFactTypes` enables the `PlanCompiler` to match candidate capabilities against a `GoalSpec` desired Fact Types. A `CapabilityCard` is advisory and grants no execution authority. `discover_cards` SHALL bind the snapshot and SHALL NOT discard it; each card's `registry_snapshot_id` SHALL equal the `GovernedContext.snapshotId`.

#### Scenario: Project read capability to CapabilityCard

- **WHEN** the planner discovers `MM.Inventory.GetAvailability` from the Registry
- **THEN** a `CapabilityCard` is produced with its inputs, governance (`sideEffect=none`, `requiresApproval=false`), visibility, `producesFactTypes` from its `outputs.factTypeRef`, and non-empty `registry_snapshot_id`

#### Scenario: CapabilityCard binds snapshotId

- **WHEN** `discover_cards` projects capabilities from a snapshot
- **THEN** each `CapabilityCard.registry_snapshot_id` equals the `GovernedContext.snapshotId`
- **AND** the snapshot argument is consumed, not discarded

### Requirement: Deterministic PlanCompiler dry-run

The system SHALL compile `GoalSpec` plus the `RegistrySnapshot` bound to the `GovernedContext` (via `SnapshotLease`) into a `PlanGraph` via a deterministic `PlanCompiler`. The `PlanGraph` SHALL be validated by the S1 `semantic-planning-foundation` validator (provenance, edges, governance, topological order). The `PlanCompiler` MUST NOT execute Gateway or SAP. The planner SHALL consume the `snapshotId` from the `SnapshotLease` and SHALL NOT reload a different snapshot; if the planner `snapshotId` drifts from the `GovernedContext.snapshotId`, the system SHALL fail-closed with a `PlannerFailure(SNAPSHOT_DRIFT)`.

#### Scenario: Dry-run produces auditable PlanGraph

- **WHEN** the `PlanCompiler` runs on a valid `GoalSpec`
- **THEN** it outputs a `PlanGraph` with nodes, edges, parameter sources (`goalConstraint`/`literal`/`factField`), gaps, and governance flags
- **AND** it does not call Gateway validate or execute

#### Scenario: PlanGraph validation reuses S1 validator

- **WHEN** the `PlanCompiler` emits a `PlanGraph`
- **THEN** the S1 `semantic-planning-foundation` validator validates provenance, edges, governance, and topological order

#### Scenario: Planner uses same snapshot as matcher

- **WHEN** the planner compiles a dry-run from an escalation handoff
- **THEN** the planner uses the `snapshotId` from the `SnapshotLease` (same as the handoff and matcher)
- **AND** does not reload a different snapshot

### Requirement: Dry-run output auditable and non-executing

The dry-run output SHALL include `PlanGraph`, `gaps` (missing parameters or capabilities), `governanceFlags` (approval required, write side-effect), and the `snapshotId` bound to the `GovernedContext`. The output SHALL be auditable: candidate, decision rationale, Registry Snapshot, nodes, edges, parameter sources, gaps, and governance. The system MUST NOT execute Gateway or SAP from dry-run output. When source load fails or snapshot drifts, the system SHALL return a structured `PlannerFailure` with stable `error_type` and audit evidence, not a silent `None` dry-run.

#### Scenario: Dry-run output is auditable

- **WHEN** dry-run completes
- **THEN** the output contains PlanGraph, gaps, governanceFlags, snapshotId, and decision rationale
- **AND** no Gateway validate or execute is called

#### Scenario: Dry-run failure is structured

- **WHEN** source load fails or snapshot drifts during dry-run
- **THEN** the system returns a `PlannerFailure` with stable `error_type` and audit evidence
- **AND** does not silently degrade to `dry_run=None`

```

## openspec/changes/sap-nexus-governed-context-registry-snapshot/specs/pr-create-action/spec.md

- Source: openspec/changes/sap-nexus-governed-context-registry-snapshot/specs/pr-create-action/spec.md
- Lines: 1-44
- SHA256: 2dcc25da65faee058ae2c2f45d95d527b12b51d0d5f31a6087f35cd6bd07495d

```md
## MODIFIED Requirements

### Requirement: ApprovalRecord 契约

系统 SHALL 定义 `ApprovalRecord`，记录审批对象（PR 参数快照 hash）、审批人、审批时间、过期时间、执行状态，以及 `registry_snapshot_id`（绑定生成该 approval 时 `GovernedContext` 的非空 `snapshotId`）。Agent 审计状态为 pending/approved/executed/rejected；Gateway 可使用内部 executing 状态表示已原子占用、不可重放。薄纵切下审批对象为用户确认的 PR 参数快照（material/plant/quantity/unit/delivery date/purchasing group），而非 RecommendationPlan 建议版本。`registry_snapshot_id` SHALL 在 pending 生成时从 `GovernedContext` 填入，使 approval 记录与同一 run 的 matcher/planner 共享同一 snapshot 标识；跨语言 approval store 的「漂移使审批失效」执行校验留 Runbook 21。

#### Scenario: 审批记录参数快照

- **WHEN** 用户确认 PR 参数并审批
- **THEN** 系统生成 `ApprovalRecord`，记录参数快照 hash、审批人、审批时间、过期时间、`registry_snapshot_id`，状态置为 `approved`

#### Scenario: ApprovalRecord 携带同快照标识

- **WHEN** orchestrator 生成 pending `ApprovalRecord`
- **THEN** `ApprovalRecord.registry_snapshot_id` 非空且等于 `GovernedContext.snapshotId`
- **AND** 与同一 run 的 matcher/planner 使用同一 `snapshotId`

#### Scenario: 审批过期

- **WHEN** execute 时 `ApprovalRecord` 已超过过期时间
- **THEN** 系统返回 `APPROVAL_EXPIRED`，不触发 SAP

#### Scenario: 审批参数版本不匹配

- **WHEN** execute 时当前 PR 参数与 `ApprovalRecord` 记录的参数快照 hash 不一致
- **THEN** 系统返回 `APPROVAL_VERSION_MISMATCH`，不触发 SAP

#### Scenario: Gateway 重算实际参数快照

- **GIVEN** ApprovalRecord 保存原参数与其 canonical SHA-256
- **WHEN** execute 请求沿用原 hash 但修改 quantity、plant 或其他实际参数
- **THEN** Gateway 重算 actual parameters hash 并返回 `APPROVAL_VERSION_MISMATCH`
- **AND** 不触发 SAP dispatch

#### Scenario: 伪造 approval 注册被拒绝

- **WHEN** `/approve` 缺少有效服务令牌，或 record 非 approved、capability 不匹配、TTL 超过 600 秒、stored parameters 与 hash 不一致
- **THEN** Gateway 拒绝注册且 ApprovalStore 不保存该记录

#### Scenario: 已消费 approval 不可重新注册

- **GIVEN** approvalId 已处于 executing 或 executed
- **WHEN** 受信调用方再次向 `/approve` 提交同一 approvalId
- **THEN** Gateway 返回冲突且不得把状态覆盖回 approved

```

## openspec/changes/sap-nexus-governed-context-registry-snapshot/specs/semantic-match-decision/spec.md

- Source: openspec/changes/sap-nexus-governed-context-registry-snapshot/specs/semantic-match-decision/spec.md
- Lines: 1-39
- SHA256: e75314fa7d18e12ea78c0341cabe2e7a64304529cfe8b62f94e7753ec7768d3e

```md
## MODIFIED Requirements

### Requirement: Visibility pre-filter

The system SHALL apply a visibility pre-filter to candidate `CapabilityCard`s before the matcher decision (including LLM prompt assembly), not only before `SHOW_OPTIONS`. The pre-filter SHALL be bound to the same non-empty `snapshotId` as the `GovernedContext` and SHALL consider governance (`sideEffect`/`dataClassification`) and bind the `principal` to the `GovernedContext` for same-snapshot/audit provenance; role-based capability visibility is deferred until the Registry carries a `visibilityScope` field. Candidates with `governance.sideEffect=none` and `dataClassification=internal` SHALL be visible by default; write-capability and restricted-data candidates SHALL be visible in dry-run but not executable until S3 gates are met. The filtered set (`VisibleCapabilitySet`) is the sole capability source for intent recognition, matcher decisions, and candidate recall. Gateway execute SHALL re-authorize (double check).

#### Scenario: Read capability visible

- **WHEN** a candidate has `sideEffect=none` and `dataClassification=internal` and the principal is permitted
- **THEN** the candidate is included in the `VisibleCapabilitySet`

#### Scenario: Write capability visible in dry-run only

- **WHEN** a candidate has `sideEffect=sap_write`
- **THEN** the candidate is visible in dry-run and SHOW_OPTIONS but not executable until S3 gates are met

#### Scenario: Pre-filter bound to same snapshotId

- **WHEN** the matcher applies visibility pre-filter
- **THEN** the filter uses `CapabilityCard`s projected from the same `snapshotId` as the `GovernedContext`
- **AND** the `VisibleCapabilitySet` is the sole input to the matcher decision

## ADDED Requirements

### Requirement: Escalation handoff binds non-empty snapshot

When `MatchDecision.decision_type=ESCALATE_TO_PLANNER`, the `EscalationHandoff.registry_snapshot_id` SHALL be non-empty and equal to the `GovernedContext.snapshotId`. The handoff SHALL NOT carry an empty `registry_snapshot_id`; the matcher SHALL populate it from the `GovernedContext` so the planner can be proven to use the same snapshot.

#### Scenario: Handoff carries non-empty snapshotId

- **WHEN** the matcher emits `ESCALATE_TO_PLANNER`
- **THEN** `EscalationHandoff.registry_snapshot_id` is non-empty
- **AND** it equals the `GovernedContext.snapshotId` used by the matcher

#### Scenario: Planner uses handoff snapshotId

- **WHEN** the planner compiles a dry-run from the handoff
- **THEN** the planner uses the same `snapshotId` as the handoff
- **AND** does not reload a different snapshot

```

## openspec/changes/sap-nexus-governed-context-registry-snapshot/specs/trusted-principal-scope/spec.md

- Source: openspec/changes/sap-nexus-governed-context-registry-snapshot/specs/trusted-principal-scope/spec.md
- Lines: 1-23
- SHA256: 2d13acbaf92497f908dd0111b1c603bfcf6aaa12404a45e761734717c6a8f997

```md
## ADDED Requirements

### Requirement: Principal propagated to agent decision layer

The trusted principal SHALL be propagated from the backend durable-authorization layer into the Python agent decision layer (intent recognition, matcher, planner). The backend SHALL pass the server-injected principal to the Python agent CLI, and `run_query` SHALL receive the principal and use it for visibility pre-filter and `GovernedContext` construction. The principal SHALL remain server-owned: request body, prompt, history, or LLM output SHALL NOT supply or override it. When no principal is provided (local CLI default), the system SHALL use the local placeholder principal.

#### Scenario: Backend propagates principal to Python agent

- **WHEN** the backend spawns the Python agent for a run with a server-injected principal
- **THEN** the principal is passed to the Python CLI and into `run_query`
- **AND** `run_query` constructs a `GovernedContext` with that principal for visibility pre-filter

#### Scenario: Local CLI defaults to placeholder principal

- **WHEN** the Python CLI runs without a provided principal (local-first mode)
- **THEN** `run_query` uses the local placeholder principal
- **AND** visibility pre-filter and `GovernedContext` still bind a non-empty principal

#### Scenario: Decision-layer principal cannot be overridden

- **WHEN** a request body or LLM output carries a principal field reaching the Python agent
- **THEN** the system ignores the request/LLM-supplied principal
- **AND** uses the backend-injected (or placeholder) principal for the `GovernedContext`

```

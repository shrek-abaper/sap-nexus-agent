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
7. `cli.py` 加 `--principal`；`agent-runtime-adapter.ts` 透传 principal。
8. 回归：matcher Eval、visibility leakage、cross-principal fail-closed、snapshot 漂移、安全投影。
- **回滚**：新参数默认 None / 字段 optional，旧调用路径行为不变；可按文件 revert。

## Open Questions

- principal stdin 透传具体 payload 形态（独立 `--principal` 还是与 `--context` 合并）-- design 阶段定。
- `IntentAdapter` 签名是否扩展接收 `GovernedContext`（是否触及 `conversational-context` spec）-- design 阶段定。
- `filter_visible` principal 维度的 role -> capability 可见性映射来源（Registry `visibilityScope` 字段当前未消费）-- design 阶段定。
- `CallPlan` 是否携带 `snapshotId`（是否触及 `agent-callplan-evidence` spec）-- design 阶段定。

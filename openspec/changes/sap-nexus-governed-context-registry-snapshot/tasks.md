## 1. GovernedContext 与受治理上下文契约

- [x] 1.1 新增 `agent/sap_nexus_agent/governed_context.py`，定义 `GovernedContext`（`principal`/`scopes`/`snapshotId`/`registryVersion`）、`SnapshotLease`（持有并校验 `RegistrySnapshot`）、`VisibleCapabilitySet`、`PlannerFailure`（`error_type`/`message`/`snapshot_id`/`audit_evidence`）
- [x] 1.2 `PlannerFailure.error_type` 枚举固化为 `SNAPSHOT_MISSING` / `SNAPSHOT_DRIFT` / `PRINCIPAL_MISMATCH` / `SOURCE_LOAD_ERROR` / `VISIBILITY_DENIED`

## 2. run_query 入口绑定 GovernedContext

- [x] 2.1 `run_query` 增 `principal` / `governed_context` 参数（默认 `None` 时回退 `PLACEHOLDER_PRINCIPAL`，本地 dev 不崩）
- [x] 2.2 入口构造 `SnapshotLease`（复用 `_default_planner_sources` + `build_registry_snapshot`），保证 `snapshotId` 非空并贯穿下游
- [x] 2.3 `AgentOutcome` 增 `planner_failure` 字段，承载结构化失败

## 3. visibility pre-filter 接入 matcher 决策路径

- [x] 3.1 `filter_visible` 扩展 principal/role 维度（基于 `CapabilityCard` + `GovernedContext.principal`）
- [x] 3.2 在 matcher 决策前构造 `VisibleCapabilitySet`（`discover_cards` -> `filter_visible`），作为 intent/matcher/召回的唯一能力来源
- [x] 3.3 `select_capability` 接收 `VisibleCapabilitySet`，不可见能力不进入候选

## 4. matcher 绑定非空 snapshotId

- [x] 4.1 `EscalationHandoff.registry_snapshot_id` 从 `GovernedContext` 填入（非空），不再 `getattr` 默认空串
- [x] 4.2 `IntentParseResult` 或 matcher 入口携带 `snapshotId`，使 handoff 与决策可追溯同快照

## 5. planner 绑定同一 snapshot + 结构化 fail-closed

- [x] 5.1 `discover_cards` 绑定 snapshot（移除 `del snapshot`），`CapabilityCard` 增 `registry_snapshot_id` 字段并填入
- [x] 5.2 `_compile_dry_run_safely` 消费 `SnapshotLease`（不再另行加载 snapshot），`snapshotId` 漂移返 `PlannerFailure(SNAPSHOT_DRIFT)`
- [x] 5.3 source load 失败返 `PlannerFailure(SOURCE_LOAD_ERROR)` + audit evidence，不再 `except Exception: return None`

## 6. capability kind 从 Registry snapshot 投影

- [x] 6.1 orchestrator 用 `CapabilityCard.governance.requires_approval` 判定 Action，移除 `capability_id in ACTION_CAPABILITY_IDS` 兜底
- [x] 6.2 kind / sideEffect / approvalPolicy 全部从 snapshot 投影，回归现有 inventory/PO/PR 路径

## 7. ApprovalRecord 携带 registry_snapshot_id

- [x] 7.1 Python `ApprovalRecord` 增 `registry_snapshot_id` 字段，`from_dict`/`to_dict` 向后兼容（`.get` 默认空）
- [x] 7.2 `create_approval_record` 从 `GovernedContext` 填入 `registry_snapshot_id`
- [x] 7.3 Node 侧 `approvalRecord` 为 `Record<string, unknown>`，Python `to_dict` 加 `registrySnapshotId` 后自动透传，无需 Node 侧加字段（漂移执行校验留 Runbook 21）

## 8. principal 透传 Node backend -> Python agent

- [x] 8.1 `cli.py` 读 `SAP_NEXUS_PRINCIPAL` env（JSON）-> `TrustedPrincipal` + `filter_catalog` 过滤 + 传 principal/snapshot/sources 给 run_query
- [x] 8.2 `frontend/src/runtime/agent-runtime-adapter.ts` 的 `executeRunnerInBackground` -> `runner` 传 principal；`runLocalPythonAgent` spawn 时设 `SAP_NEXUS_PRINCIPAL` env

## 9. CapabilityCard 安全投影固化

- [x] 9.1 确认 `discover_cards` 不读 `executorBinding`/`executor`，补 negative test 断言 `CapabilityCard` 不含 `rfcName`/`serviceUrl`/`credentialRef`/`rawSql`/technical mapping

## 10. 测试与验证

- [x] 10.1 visibility leakage = 0 测试：不可见 capability 不进入 LLM prompt 候选与 matcher 决策
- [x] 10.2 cross-principal 决策层 fail-closed 测试：多 principal 注入，A 不可见能力不产生 SELECT/候选
- [x] 10.3 snapshot 漂移 / source load 失败 / visibility denial 返回结构化 `PlannerFailure` 测试
- [x] 10.4 matcher Eval 6/6 回归 + `CapabilityCard` 安全投影回归 + 现有 inventory/PO/PR 路径回归
- [x] 10.5 运行 `openspec validate --all --strict` + `.venv/bin/python -m pytest agent/tests -q` + `scripts/verify-agent-callplan-evidence.sh` + `npm --prefix frontend run verify`

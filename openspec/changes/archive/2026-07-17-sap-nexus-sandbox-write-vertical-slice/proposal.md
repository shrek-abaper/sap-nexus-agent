## Why

SAP Nexus Agent 的 READ 阶段（Phase 0 -> 4D）已完整落地并归档：两条 read capability（`MM.Inventory.GetAvailability` 走 JCo、`MM.PurchaseOrder.GetList` 走 OData）、hybrid intent、CallPlan -> Evidence -> Narrator、Workbench Console、Eval seed 全部打通，但 WRITE/Approval 闭环完全空白——registry 仅有 `Function`（`sideEffect: none`、`requiresApproval: false`），gateway dispatcher 只读、无 `BAPI_TRANSACTION_COMMIT`/`ROLLBACK` 守卫，无 `ApprovalRecord`/`ActionResult` 契约。

为打通 READ -> WRITE 的质变节点，需构建 SAP 写入受控闭环的最薄纵切：以采购申请创建 `BAPI_PR_CREATE` 为首个 `Action` capability，建立从用户确认到 SAP 写入的全链路受控执行，并复用本地 `.env` 配置的 SAP 环境做 live 验证。这是 roadmap §17.3 / row 10 既定方向，提前暴露 Human Approval 契约与 Action 执行路径的设计风险。

## What Changes

- **新增 Action capability `MM.PR.CreateDraft`**：registry 中新增首个 `kind: Action`、`sideEffect: sap_write`、`requiresApproval: true` 的能力，绑定 JCo RFC `BAPI_PR_CREATE`，走 `JCO_RFC` executor 路径。
- **新增 ApprovalRecord 契约**：定义审批对象（薄纵切下为"用户确认的 PR 参数快照"而非 RecommendationPlan 建议版本）、审批人、审批时间、过期、版本匹配语义，及 `APPROVAL_REQUIRED`/`APPROVAL_EXPIRED`/`APPROVAL_VERSION_MISMATCH` 拒绝场景。
- **新增 ActionResult 契约**：定义写入执行结果（PR 号、SAP RETURN、commit 状态、duration、traceId），与 read 的 `ExecutionResult` 在 schema 上可区分。
- **Gateway WRITE execute path**：扩展 JCo dispatcher 支持写入选 `BAPI_PR_CREATE`；execute 成功后**内部强制** `BAPI_TRANSACTION_COMMIT`（`WAIT=X`），失败 `BAPI_TRANSACTION_ROLLBACK`；新增 approval 守卫（缺审批/过期/版本不匹配/duplicate submit 在到达 SAP 前拒绝）。
- **READ/WRITE 隔离硬边界**：READ capability 永不 commit/rollback；WRITE capability 必须审批确认后才 execute。与 §2 硬边界一致。
- **Agent Action CallPlan + approval 状态机**：Agent 侧扩展 CallPlan 承载 Action 语义，新增 approval 状态机（pending -> approved -> executed / rejected）。
- **新增 Eval 写入回归集**：覆盖 approval missing/expired/version-mismatch、SAP RETURN E/A、duplicate submit 等失败用例与成功 PR 创建用例。
- **新增 spec `pr-create-action`**：承载上述 capability 的需求契约。

## Capabilities

### New Capabilities

- `pr-create-action`: 采购申请创建 Action 能力——`MM.PR.CreateDraft` 经 `BAPI_PR_CREATE` 创建采购申请，包含 approval 守卫、commit/rollback 守卫、READ/WRITE 隔离、ActionResult 返回、写入失败回归。

### Modified Capabilities

<!-- 无现有 spec 的 REQUIREMENTS 变更。approval 守卫与 WRITE path 为新增契约，不修改现有 read capability 行为。 -->

## Impact

- **registry**：`registry/capabilities.yaml` 新增 `MM.PR.CreateDraft`；可能需要 `registry/executor-bindings.yaml` 新增 JCo write binding。
- **schemas**：新增 `ApprovalRecord`、`ActionResult` schema；扩展 `capability.schema.json` 校验 `Action` 必须 `requiresApproval=true`、`sideEffect=sap_write`。
- **gateway-jco（services/gateway）**：`TechnicalExecutionDispatcher`/`JcoRfcTechnicalAdapter` 扩展写入路径与 commit/rollback 守卫；新增 approval 守卫组件。
- **agent（agent/sap_nexus_agent/）**：`call_plan.py` 扩展 Action 语义；新增 approval 状态机、`action_result.py`。
- **evals**：新增 PR create 写入回归 case 集。
- **docs**：新增 runbook `11-sandbox-write-vertical-slice.md`；更新 roadmap §17.3 进度与 runbook README 索引。
- **验证**：本地 `.env` 配置的 SAP client 做 live PR 创建 smoke（产生真实 PR 凭证号，需 sandbox/dev client 可接受写入）。

# Comet Design Handoff

- Change: sap-nexus-sandbox-write-vertical-slice
- Phase: design
- Mode: compact
- Context hash: 7ada308e5b95f561aa1b68961b39babbb148c6b49e12735c637c60e40c5ef94f

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/sap-nexus-sandbox-write-vertical-slice/proposal.md

- Source: openspec/changes/sap-nexus-sandbox-write-vertical-slice/proposal.md
- Lines: 1-36
- SHA256: 9570f7176ec1c98adfff33b251988083b3c5c5569047cc69876c14aed6e74186

```md
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

```

## openspec/changes/sap-nexus-sandbox-write-vertical-slice/design.md

- Source: openspec/changes/sap-nexus-sandbox-write-vertical-slice/design.md
- Lines: 1-79
- SHA256: 91aa83976b1646938844e890b9311a83f391e6a05c67494b39915a5e2baaf937

```md
## Context

当前 SAP Nexus Agent 已完成 READ 全链路（capability-registry-gateway、agent-callplan-evidence、agent-workbench-console、registry-ontology-contract、gateway-execution-contract、eval-harness-seed、odata-gateway-read），但 WRITE 路径完全空白：

- registry 仅有 `kind: Function`（`sideEffect: none`、`requiresApproval: false`）。
- `TechnicalExecutionDispatcher` / `JcoRfcTechnicalAdapter` 只承载 read execute，无 `BAPI_TRANSACTION_COMMIT`/`ROLLBACK`。
- 无 `ApprovalRecord`、`ActionResult` 契约，无 approval 守卫。

参考 `sap-skill-create/skills-production/sap-sto-create` 的 STO create JCo 经验：`BAPI_TRANSACTION_COMMIT`（`WAIT=X`）+ 失败 `BAPI_TRANSACTION_ROLLBACK` + 检查 commit RETURN。现有 JCo adapter 骨架（`TechnicalAdapter` 接口 + `JcoRfcTechnicalAdapter` + dispatcher 路由）可在此基础上扩展 WRITE 路径。

本纵切用 `BAPI_PR_CREATE`（采购申请创建，字段简单、sandbox 风险低）作为首个 `Action` capability，用本地 `.env` 配置的 SAP 环境做 live 验证。

## Goals / Non-Goals

**Goals:**

- 打通首个 SAP WRITE 受控闭环：`ApprovalRecord -> Action CallPlan -> Gateway validate -> SAP execute -> ActionResult -> SAP RETURN -> TraceSpan -> EvalCase`。
- 新增 `MM.PR.CreateDraft` Action capability（`BAPI_PR_CREATE`）。
- 建立 `ApprovalRecord` / `ActionResult` 契约与 approval 守卫。
- 在 Gateway 内部强制 commit/rollback，建立 READ/WRITE 隔离硬边界。
- 覆盖写入失败回归（approval missing/expired/version-mismatch、SAP RETURN E/A、duplicate submit）。

**Non-Goals:**

- 不做 RecommendationPlan 推理引擎（留 roadmap row 11 独立 change）--approval 审批对象退化为"PR 参数快照"。
- 不做生产 client 写入、release/post 重量级 action、多能力组合 planner / DAG。
- 不做 RBAC / 多租户 / 生产部署。
- 不改现有 2 个 read capability 行为。

## Decisions

### D1: approval 审批对象 = PR 参数快照（薄纵切退化）

roadmap §12 的 `APPROVAL_VERSION_MISMATCH` 原意是审批 RecommendationPlan 建议版本。薄纵切跳过 RecommendationPlan，approval 审批的是"用户确认的 PR 参数快照"（material/plant/quantity/unit/delivery date 等）。`ApprovalRecord` 记录参数快照 hash；execute 前比对当前参数与快照，不一致即 `APPROVAL_VERSION_MISMATCH`。

- 选此方案：聚焦 WRITE/Approval 闭环本身，不被推荐逻辑分心；RecommendationPlan 留 row 11。
- 替代方案（含 Recommendation 完整纵切）：触碰架构更多，design 探索更重，且推荐逻辑非 WRITE 闭环核心风险。

### D2: commit/rollback 在 Gateway 内部强制

WRITE capability execute `BAPI_PR_CREATE` 成功后，Gateway 内部自动 `BAPI_TRANSACTION_COMMIT`（`WAIT=X`）；SAP RETURN E/A 或 commit 失败则 `BAPI_TRANSACTION_ROLLBACK`。Agent / 外部不显式触发 commit，避免漏 commit 导致 SAP 残留未提交数据。

- 选此方案：commit 是技术事务边界，归属 Gateway（技术执行层）与 §9.2 binding dispatcher 契约一致。
- 替代方案（Agent 显式 commit）：泄漏技术细节到 Agent 语义层，且易漏 commit。

### D3: approval 守卫在 Gateway execute 入口

approval 校验（缺审批/过期/版本不匹配/duplicate submit）在 Gateway `execute` 入口、SAP 调用前完成，命中即拒绝（`APPROVAL_REQUIRED`/`APPROVAL_EXPIRED`/`APPROVAL_VERSION_MISMATCH`/`APPROVAL_DUPLICATE`），不触发 SAP。

- 选此方案：守卫是安全边界，必须在技术执行前 fail-closed，与 §2 硬边界"WRITE 必须审批确认后才 execute"一致。

### D4: READ/WRITE 隔离用 capability governance 字段

`capability.schema.json` 强制校验：`kind: Action` 必须 `requiresApproval: true` 且 `sideEffect: sap_write`；`kind: Function` 必须 `sideEffect: none`。Gateway dispatcher 按 `kind`/`sideEffect` 路由：read 路径永不 commit/rollback，write 路径必须过 approval 守卫后才 commit。

### D5: BAPI_PR_CREATE 字段最小集

PRITEM 最小输入：material、plant、quantity、unit、delivery date。具体 SAP 字段映射（`MATERIAL`/`PLANT`/`QUANTITY`/`UNIT`/`DELIV_DATE`）与 output（`PR number` from `PRITEMEXP`/RETURN、`returnMessages`）在 design 阶段 Design Doc 细化。

## Risks / Trade-offs

- [approval 退化 vs roadmap §12] -> 文档明确薄纵切退化，row 11 RecommendationPlan 接回后升级为建议版本匹配。
- [sandbox PR 凭证产生真实数据] -> 仅在 dev/sandbox client 执行；禁止生产 client；`.env` 配置确认。
- [commit 后 SAP 异常残留] -> commit RETURN 检查 + rollback 兜底 + trace 记录 commit 状态。
- [duplicate submit 同 approval 重复 execute] -> `ApprovalRecord` 标记已执行状态，重复 execute 拒绝。
- [JCo write 路径影响现有 read 测试] -> dispatcher 按 capability kind 路由，read 测试不受影响；新增独立 write 测试。

## Migration Plan

- registry 新增 capability 不破坏现有 read capability。
- gateway dispatcher 扩展为向后兼容：read 路径行为不变，新增 write 路径。
- schema 校验增强：现有 2 个 read capability 仍通过校验。
- 回滚：移除新增 capability 与 write path 代码，read 链路不受影响。

## Open Questions

- `BAPI_PR_CREATE` 具体 PRITEM 字段映射与必填项，design 阶段查 SAP 文档 / 参考项目确认。
- approval 过期时长（TTL）默认值。
- `ApprovalRecord` 存储：内存 / 文件 trace（MVP 不上 DB），与现有 JSONL trace 对齐。

```

## openspec/changes/sap-nexus-sandbox-write-vertical-slice/tasks.md

- Source: openspec/changes/sap-nexus-sandbox-write-vertical-slice/tasks.md
- Lines: 1-57
- SHA256: 0be35ea2e5d1607d3c5525638bcb29ff732ca0d89b09d3b34b4e26d020c9e739

```md
## 1. Schema 与契约

- [ ] 1.1 新增 `schemas/approval-record.schema.json`，定义审批对象（PR 参数快照 hash）、审批人、审批时间、过期时间、执行状态
- [ ] 1.2 新增 `schemas/action-result.schema.json`，定义 PR 号、SAP RETURN、commit 状态、duration、traceId，与 `execution-result.schema.json` 区分
- [ ] 1.3 扩展 `schemas/capability.schema.json`：`kind: Action` 必须 `requiresApproval=true` 且 `sideEffect=sap_write`；`kind: Function` 必须 `sideEffect=none`
- [ ] 1.4 验证现有 2 个 read capability 仍通过增强后的 schema 校验

## 2. Registry capability 注册

- [ ] 2.1 在 `registry/capabilities.yaml` 新增 `MM.PR.CreateDraft`（`kind: Action`、`sideEffect: sap_write`、`requiresApproval: true`、`executor.type=JCO_RFC`、`rfcName=BAPI_PR_CREATE`），含 PRITEM 最小输入字段与 output 映射
- [ ] 2.2 如需新增 JCo write binding，更新 `registry/executor-bindings.yaml`
- [ ] 2.3 运行 `scripts/validate-registry-contract.py` 确认 registry 校验通过

## 3. Gateway approval 守卫

- [ ] 3.1 新增 approval 守卫组件：execute 入口校验 ApprovalRecord 存在性、过期、参数快照 hash 版本匹配、重复执行
- [ ] 3.2 守卫命中返回结构化错误（`APPROVAL_REQUIRED`/`APPROVAL_EXPIRED`/`APPROVAL_VERSION_MISMATCH`/`APPROVAL_DUPLICATE`），在 SAP 调用前 fail-closed
- [ ] 3.3 守卫单元测试覆盖四种拒绝场景

## 4. Gateway WRITE commit/rollback 守卫

- [ ] 4.1 扩展 `JcoRfcTechnicalAdapter`/dispatcher：`MM.PR.CreateDraft` execute `BAPI_PR_CREATE`，按 capability `kind`/`sideEffect` 路由到 write 路径
- [ ] 4.2 写入成功后内部强制 `BAPI_TRANSACTION_COMMIT`（`WAIT=X`），检查 commit RETURN
- [ ] 4.3 SAP RETURN E/A 或 commit 失败调用 `BAPI_TRANSACTION_ROLLBACK`，返回 `SAP_BUSINESS_ERROR`
- [ ] 4.4 read 路径（`Function`）永不调用 commit/rollback 隔离测试
- [ ] 4.5 commit/rollback 单元测试（mock JCo destination）覆盖成功提交、业务错误回滚、commit 失败回滚

## 5. ActionResult 与 trace

- [ ] 5.1 实现 `ActionResult` 返回结构（PR 号从 PRITEMEXP/RETURN 提取、commit 状态、duration、traceId）
- [ ] 5.2 写入 execute 写入 `TraceSpan`：参数摘要、PR 号、commit 状态、SAP RETURN、错误类型、duration，敏感字段脱敏
- [ ] 5.3 trace 回放测试：给定 traceId 能定位参数、PR 号、commit 状态，不含 SAP 凭据

## 6. Agent Action CallPlan 与 approval 状态机

- [ ] 6.1 扩展 `agent/sap_nexus_agent/call_plan.py` 承载 Action 语义
- [ ] 6.2 新增 approval 状态机（pending -> approved -> executed/rejected）与 `ApprovalRecord` 客户端生成
- [ ] 6.3 缺参只澄清、不生成 approval 的逻辑（material/plant/quantity 必填校验）
- [ ] 6.4 新增 `agent/sap_nexus_agent/action_result.py` 解析 Gateway write 返回
- [ ] 6.5 Agent 单元测试：缺参澄清、审批通过执行、审批状态流转

## 7. Eval 写入回归

- [ ] 7.1 新增 `evals/pr_create_cases.yaml`（或 .json），覆盖 approval missing/expired/version-mismatch、SAP RETURN E/A、duplicate submit、成功 PR 创建
- [ ] 7.2 接入 `scripts/verify-agent-callplan-evidence.sh` 纳入 write 回归
- [ ] 7.3 运行 eval 回归全部断言通过

## 8. Live smoke 验证

- [ ] 8.1 用本地 `.env` 配置的 SAP 环境运行 `MM.PR.CreateDraft` live smoke，确认创建真实 PR 凭证并返回 PR 号
- [ ] 8.2 确认 commit 成功、trace 记录完整、无 SAP 凭据泄漏

## 9. 文档与归档准备

- [ ] 9.1 新增 `docs/runbooks/11-sandbox-write-vertical-slice.md`（session closeout 模板）
- [ ] 9.2 更新 `docs/runbooks/README.md` 索引与 `docs/wiki/sap-nexus-agent-implementation-roadmap.md` §17.3 进度
- [ ] 9.3 运行 `openspec validate --all --strict` 确认全部通过

```

## openspec/changes/sap-nexus-sandbox-write-vertical-slice/specs/pr-create-action/spec.md

- Source: openspec/changes/sap-nexus-sandbox-write-vertical-slice/specs/pr-create-action/spec.md
- Lines: 1-146
- SHA256: ddd7e3dde705fbdb5c4dfd19395fd7e586dae6ba2953af062f72fef7ff4577f4

[TRUNCATED]

```md
## ADDED Requirements

### Requirement: PR 创建 Action capability 注册

系统 SHALL 在 registry 注册 `MM.PR.CreateDraft` capability，`kind: Action`，`sideEffect: sap_write`，`requiresApproval: true`，绑定 JCo RFC `BAPI_PR_CREATE`，executor type `JCO_RFC`。

#### Scenario: Action capability 通过 registry 校验

- **WHEN** registry validator 校验 `MM.PR.CreateDraft`
- **THEN** capability 通过 schema 校验，`kind=Action`、`sideEffect=sap_write`、`requiresApproval=true`、`executor.type=JCO_RFC`、`executor.rfcName=BAPI_PR_CREATE`

#### Scenario: capability 可经 /capabilities 返回

- **WHEN** 调用 Gateway `GET /capabilities`
- **THEN** 返回结果包含 `MM.PR.CreateDraft`，与现有 read capability 并列

### Requirement: Action capability 必须审批

系统 MUST 强制 `kind: Action` 的 capability `requiresApproval=true` 且 `sideEffect=sap_write`；`kind: Function` 必须 `sideEffect=none`。schema 校验命中违规即拒绝。

#### Scenario: Action 缺审批字段被拒绝

- **WHEN** registry 中存在 `kind: Action` 但 `requiresApproval=false` 的 capability
- **THEN** schema 校验失败，capability 无法注册

#### Scenario: Function 声明写副作用被拒绝

- **WHEN** registry 中存在 `kind: Function` 且 `sideEffect=sap_write` 的 capability
- **THEN** schema 校验失败

### Requirement: ApprovalRecord 契约

系统 SHALL 定义 `ApprovalRecord`，记录审批对象（PR 参数快照 hash）、审批人、审批时间、过期时间、执行状态（pending/approved/executed/rejected）。薄纵切下审批对象为用户确认的 PR 参数快照（material/plant/quantity/unit/delivery date），而非 RecommendationPlan 建议版本。

#### Scenario: 审批记录参数快照

- **WHEN** 用户确认 PR 参数并审批
- **THEN** 系统生成 `ApprovalRecord`，记录参数快照 hash、审批人、审批时间、过期时间，状态置为 `approved`

#### Scenario: 审批过期

- **WHEN** execute 时 `ApprovalRecord` 已超过过期时间
- **THEN** 系统返回 `APPROVAL_EXPIRED`，不触发 SAP

#### Scenario: 审批参数版本不匹配

- **WHEN** execute 时当前 PR 参数与 `ApprovalRecord` 记录的参数快照 hash 不一致
- **THEN** 系统返回 `APPROVAL_VERSION_MISMATCH`，不触发 SAP

### Requirement: approval 守卫在 SAP 调用前 fail-closed

系统 MUST 在 Gateway execute 入口、SAP 调用前完成 approval 校验：缺审批返回 `APPROVAL_REQUIRED`，过期返回 `APPROVAL_EXPIRED`，版本不匹配返回 `APPROVAL_VERSION_MISMATCH`，重复 execute 返回 `APPROVAL_DUPLICATE`。命中任一即不触发 SAP。

#### Scenario: 缺审批拒绝写入

- **WHEN** 对 `MM.PR.CreateDraft` 调用 execute 但无 `ApprovalRecord`
- **THEN** 返回 `APPROVAL_REQUIRED`，不调用 `BAPI_PR_CREATE`

#### Scenario: 重复提交拒绝

- **WHEN** 同一 `ApprovalRecord` 再次 execute
- **THEN** 返回 `APPROVAL_DUPLICATE`，不调用 `BAPI_PR_CREATE`

### Requirement: Gateway WRITE commit/rollback 守卫

系统 SHALL 在 `MM.PR.CreateDraft` execute `BAPI_PR_CREATE` 成功后内部强制 `BAPI_TRANSACTION_COMMIT`（`WAIT=X`）；SAP RETURN E/A 或 commit 失败则 `BAPI_TRANSACTION_ROLLBACK`。Agent 或外部不显式触发 commit。

#### Scenario: 写入成功后提交

- **WHEN** `BAPI_PR_CREATE` 返回成功（无 E/A）
- **THEN** Gateway 内部调用 `BAPI_TRANSACTION_COMMIT`（`WAIT=X`），`ActionResult` 记录 commit 成功与 PR 号

#### Scenario: 写入业务错误回滚

- **WHEN** `BAPI_PR_CREATE` 返回 RETURN E/A
- **THEN** Gateway 调用 `BAPI_TRANSACTION_ROLLBACK`，返回 `SAP_BUSINESS_ERROR`，不 commit

#### Scenario: commit 失败回滚兜底

- **WHEN** `BAPI_TRANSACTION_COMMIT` RETURN 报错

```

Full source: openspec/changes/sap-nexus-sandbox-write-vertical-slice/specs/pr-create-action/spec.md

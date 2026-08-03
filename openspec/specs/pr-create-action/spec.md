# pr-create-action Specification

## Purpose

定义 SAP Nexus 首个受 Human Approval 保护的 SAP WRITE Action：从 `MM.PR.CreateDraft` capability 注册、ApprovalRecord 与参数快照完整性、Gateway fail-closed 审批守卫和单次执行，到 `BAPI_PR_CREATE` stateful LUW、真实 commit/rollback 状态、Workbench continuation、回归评测及可回放脱敏 trace 的端到端契约。
## Requirements
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

### Requirement: approval 守卫在 SAP 调用前 fail-closed

系统 MUST 在 Gateway execute 入口、SAP 调用前完成 approval 校验：缺审批返回 `APPROVAL_REQUIRED`，过期返回 `APPROVAL_EXPIRED`，版本不匹配返回 `APPROVAL_VERSION_MISMATCH`，重复 execute 返回 `APPROVAL_DUPLICATE`。命中任一即不触发 SAP。

#### Scenario: 缺审批拒绝写入

- **WHEN** 对 `MM.PR.CreateDraft` 调用 execute 但无 `ApprovalRecord`
- **THEN** 返回 `APPROVAL_REQUIRED`，不调用 `BAPI_PR_CREATE`

#### Scenario: 重复提交拒绝

- **WHEN** 同一 `ApprovalRecord` 再次 execute
- **THEN** 返回 `APPROVAL_DUPLICATE`，不调用 `BAPI_PR_CREATE`

#### Scenario: 并发提交只有一个请求可执行

- **GIVEN** 两个请求携带相同的有效 approval 与相同参数
- **WHEN** 两个请求并发到达 execute
- **THEN** Gateway 在 dispatch 前原子执行 `approved -> executing`，只有一个请求 claim 成功并调用 `BAPI_PR_CREATE`
- **AND** 另一个请求返回 `APPROVAL_DUPLICATE`

### Requirement: Gateway WRITE commit/rollback 守卫

系统 SHALL 在 `MM.PR.CreateDraft` execute `BAPI_PR_CREATE` 成功后内部强制 `BAPI_TRANSACTION_COMMIT`（`WAIT=X`）；SAP RETURN E/A 或 commit 失败则 `BAPI_TRANSACTION_ROLLBACK`。Agent 或外部不显式触发 commit。

#### Scenario: 写入成功后提交

- **WHEN** `BAPI_PR_CREATE` 返回成功（无 E/A）
- **THEN** Gateway 内部调用 `BAPI_TRANSACTION_COMMIT`（`WAIT=X`），`ActionResult` 记录 commit 成功与 PR 号
- **AND** PR 号优先取自 `BAPI_PR_CREATE` 导出参数 `NUMBER`，为空时才回退 `PRITEMEXP.PREQ_NO`

#### Scenario: 写入业务错误回滚

- **WHEN** `BAPI_PR_CREATE` 返回 RETURN E/A
- **THEN** Gateway 调用 `BAPI_TRANSACTION_ROLLBACK`，返回 `SAP_BUSINESS_ERROR`，不 commit

#### Scenario: commit 失败回滚兜底

- **WHEN** `BAPI_TRANSACTION_COMMIT` RETURN 报错
- **THEN** Gateway 调用 `BAPI_TRANSACTION_ROLLBACK`，`ActionResult` 记录 commit 失败，trace 记录 commit 状态

#### Scenario: rollback 结果按事实记录

- **WHEN** WRITE 失败并尝试 rollback
- **THEN** rollback 成功记录 `rolled_back`，rollback 自身失败记录 `rollback_failed`
- **AND** SAP 调用前失败记录 `none`，不得从 ErrorType 推断发生过 rollback

#### Scenario: WRITE RFC 共享 stateful LUW

- **WHEN** Gateway 执行 `BAPI_PR_CREATE` 与后续 commit 或 rollback
- **THEN** 所有 RFC 处于同一个 `JCoContext.begin/end` 生命周期
- **AND** 任意成功或失败返回均清理 context

#### Scenario: commit 后结果提取失败

- **GIVEN** commit RETURN 已确认成功
- **WHEN** PR 号提取发生异常
- **THEN** 返回 `NORMALIZATION_ERROR` 且 `commitStatus=committed`
- **AND** 不再次 rollback，不把结果描述为可安全重试

### Requirement: 直采 BAPI_PR_CREATE technical envelope

系统 SHALL 在专用 `PrCreateDraftExecutor` 中把已审批的直采业务参数转换为当前 SAP release 要求的 BAPI technical envelope，不把 document type、item key 或 X indicator 暴露给 Agent/LLM。

#### Scenario: 构造标准直采 PR header 与 item

- **GIVEN** 已审批参数包含 material、plant、quantity、unit、delivery date、purchasing group
- **WHEN** Gateway 构造 `BAPI_PR_CREATE` 请求
- **THEN** `PRHEADER.PR_TYPE="NB"` 且 `PRHEADERX.PR_TYPE="X"`
- **AND** `PRITEM` 包含 `PREQ_ITEM="00010"` 与 `MATERIAL`、`PLANT`、`QUANTITY`、`UNIT`、`DELIV_DATE`、`PUR_GROUP`
- **AND** `PRITEMX` 包含相同 item key、`PREQ_ITEMX="X"` 与所有已填 item 字段的 `"X"` 标记
- **AND** ISO delivery date 以 JCo-compatible date 写入

#### Scenario: 采购组是受治理的必填业务输入

- **WHEN** 用户请求创建 PR 但未提供 purchasing group
- **THEN** Agent 输出缺参澄清，不生成 approval，不调用 SAP
- **AND** purchasing group 必须进入审批参数快照并映射到 `PRITEM.PUR_GROUP`
- **AND** executor 不得硬编码具体采购组值

#### Scenario: 空 input table 仍可被填充

- **GIVEN** `PRITEM` / `PRITEMX` 在 append row 前尚未 initialized
- **WHEN** JCo metadata 声明这些 table 参数存在
- **THEN** executor append row 并填充字段，不因 `isInitialized=false` 跳过 item

#### Scenario: live smoke 范围只包含直采

- **WHEN** 本 change 执行 sandbox live smoke
- **THEN** 只创建 1 个直采 PR
- **AND** 间采保持 mock 覆盖，不声明为 live-ready

### Requirement: READ/WRITE 路径隔离

系统 MUST 保证 read capability（`kind: Function`）execute 路径永不调用 `BAPI_TRANSACTION_COMMIT`/`ROLLBACK`；write capability（`kind: Action`）必须过 approval 守卫后才执行 commit。dispatcher 按 capability `kind`/`sideEffect` 路由。

#### Scenario: read 路径不 commit

- **WHEN** 执行 `MM.Inventory.GetAvailability` 或 `MM.PurchaseOrder.GetList`
- **THEN** Gateway 不调用 `BAPI_TRANSACTION_COMMIT` 或 `BAPI_TRANSACTION_ROLLBACK`

#### Scenario: write 路径必经 approval

- **WHEN** 执行 `MM.PR.CreateDraft` 未经 approval 守卫
- **THEN** 在 SAP 调用前被拒绝

### Requirement: ActionResult 契约

系统 SHALL 定义 `ActionResult`，包含 PR 号、SAP RETURN 消息、commit 状态、duration、traceId，与 read 的 `ExecutionResult` 在 schema 上可区分。

#### Scenario: 成功 PR 创建返回 ActionResult

- **WHEN** `MM.PR.CreateDraft` execute 成功并 commit
- **THEN** 返回 `ActionResult`，含 PR 号、空错误消息、commit 成功状态、duration、traceId
- **AND** `prNumber` 与 `commitStatus` 是 HTTP 响应顶层字段，不隐藏在通用 `ExecutionResult.data` 中

#### Scenario: 失败返回结构化错误

- **WHEN** execute 因 approval 或 SAP 业务错误失败
- **THEN** 返回结构化 `ActionResult`，含错误类型（`APPROVAL_REQUIRED`/`SAP_BUSINESS_ERROR` 等），无 PR 号

#### Scenario: WRITE 早期失败仍可审计回放

- **WHEN** Action execute 因 technical override 或参数校验在 SAP 前失败
- **THEN** HTTP 与 trace 使用同一个 `ActionResult`，`commitStatus=none` 且 `resultSummary` 非空
- **AND** Function/READ 响应与通用 trace 行为保持不变

#### Scenario: Action dispatch exception 仍可回放

- **WHEN** approval 已 claim 但 Action dispatcher 抛 runtime exception
- **THEN** Gateway 消费 approval，返回并 trace 同源 `ActionResult(commitStatus=none)`
- **AND** 同一 approval 重放返回 `APPROVAL_DUPLICATE`

### Requirement: Agent Action CallPlan 与 approval 状态机

系统 SHALL 扩展 Agent CallPlan 承载 Action 语义，新增 approval 状态机（pending -> approved -> executed/rejected）。缺参时只澄清，不生成 approval；参数完整的首次 Action 请求只生成 pending approval，不得自行批准或调用 Gateway execute。

#### Scenario: 缺参澄清不审批

- **WHEN** 用户请求建 PR 但缺 material/plant/quantity 等必填项
- **THEN** Agent 输出澄清，不生成 `ApprovalRecord`，不调用 Gateway execute

#### Scenario: 审批通过后执行

- **WHEN** 用户补齐参数并审批
- **THEN** Agent 生成 Action CallPlan，approval 状态置 `approved`，调用 Gateway execute，成功后状态置 `executed`
- **AND** Gateway execute 失败时不得把 approval 状态伪造为 `executed`

#### Scenario: 首次 Action 请求等待外部审批

- **WHEN** 用户提交参数完整的 PR 创建请求，但尚未通过 Workbench 明确批准
- **THEN** Agent 返回 pending `ApprovalRecord` 与 `awaiting_approval` 状态
- **AND** Agent 不调用 `approve()`、Gateway approve 或 Gateway execute

### Requirement: Workbench Human Approval continuation

系统 MUST 通过 Workbench 两阶段交互接收外部 Human Approval。服务端 run store SHALL 保存 pending ApprovalRecord 与精确 Action 上下文；浏览器 approval endpoint 只允许提交 approve/reject decision，不允许提交或覆盖 capabilityId、参数或 snapshot hash。

#### Scenario: 用户批准服务端 pending Action

- **GIVEN** run store 中存在状态为 pending 的 PR Action
- **WHEN** 用户在 Workbench 点击批准
- **THEN** 系统从服务端 run store 读取原始参数快照并执行 pending -> approved -> Gateway approve -> Gateway execute
- **AND** 成功后状态置 executed，失败时不得伪造 executed

#### Scenario: continuation validation 不一致

- **WHEN** 服务端保存的 validation 不是成功结果，或其 capability 与 CallPlan 不一致，或 ApprovalRecord 快照校验失败
- **THEN** Agent 不调用 Gateway approve/execute
- **AND** Workbench 产生结构化失败事件，不得把 pending ApprovalRecord 渲染为 approved

#### Scenario: 用户拒绝 pending Action

- **GIVEN** run store 中存在状态为 pending 的 PR Action
- **WHEN** 用户在 Workbench 点击拒绝
- **THEN** approval 状态置 rejected，Gateway approve 与 execute 均不被调用

#### Scenario: 浏览器不能覆盖审批快照

- **WHEN** approval 请求包含 capabilityId、parameters 或 parameterSnapshotHash 等额外字段
- **THEN** 服务端忽略或拒绝这些字段，只使用 run store 中的 pending Action 上下文

#### Scenario: 重复决策被拒绝

- **WHEN** 同一 run 已批准、拒绝或执行后再次提交 approval decision
- **THEN** 服务端返回冲突，不再次调用 Gateway 或 SAP

### Requirement: 写入 Eval 回归集

系统 SHALL 新增 PR create 写入回归 case 集，覆盖 approval missing/expired/version-mismatch、SAP RETURN E/A、duplicate submit、成功 PR 创建。

#### Scenario: Eval 覆盖失败边界

- **WHEN** 运行 PR create eval 回归集
- **THEN** approval missing/expired/version-mismatch、SAP business error、duplicate submit 场景均断言拒绝行为，成功场景断言 PR 号返回

#### Scenario: live smoke 在本地 env 验证

- **WHEN** 用本地 `.env` 配置的 SAP 环境运行 PR create live smoke
- **THEN** 成功创建真实 PR 凭证并返回 PR 号，trace 记录 commit 成功

### Requirement: Trace 与审计

系统 SHALL 为 PR create execute 写入 `TraceSpan`，含 traceId、capabilityId、参数摘要、PR 号、commit 状态、SAP RETURN、错误类型、duration，敏感字段脱敏，不泄漏 SAP 凭据。WRITE 结果证据 SHALL 与 HTTP `ActionResult` 同源；READ/validate trace 保持兼容。

#### Scenario: write trace 可回放

- **WHEN** 给定 PR create 的 traceId
- **THEN** 能定位参数摘要、PR 号、commit 状态、SAP RETURN、错误类型，且不含 SAP 密码或 destination 敏感信息

#### Scenario: read trace 保持兼容

- **WHEN** validate 或 read capability execute 写 trace
- **THEN** 保留既有通用 trace 字段，WRITE 专用 result summary 为空对象且不改变 read 响应


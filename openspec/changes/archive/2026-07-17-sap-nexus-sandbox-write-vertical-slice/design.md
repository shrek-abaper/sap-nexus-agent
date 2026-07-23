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
- Gateway 只接受带 `X-SAP-Nexus-Approval-Token` 的受信 Agent 注册，且严格校验 capability、`approved` 状态、600 秒内 TTL 与 record 自身参数 hash。
- Gateway 使用与 Agent 一致的 compact/sorted JSON canonicalization，重算 stored parameters 与 execute actual parameters 的 SHA-256；request hash 仅作额外交叉校验。
- 校验通过后，ApprovalStore 必须在 dispatch 前原子执行 `approved -> executing`；claim 失败返回 `APPROVAL_DUPLICATE`，从而关闭并发 TOCTOU。
- ApprovalStore 对 `approvalId` 使用首次写入语义，禁止重新注册覆盖 `executing/executed`；重放 `/approve` 返回冲突。

### D4: READ/WRITE 隔离用 capability governance 字段

`capability.schema.json` 强制校验：`kind: Action` 必须 `requiresApproval: true` 且 `sideEffect: sap_write`；`kind: Function` 必须 `sideEffect: none`。Gateway dispatcher 按 `kind`/`sideEffect` 路由：read 路径永不 commit/rollback，write 路径必须过 approval 守卫后才 commit。

### D5: BAPI_PR_CREATE 字段最小集

PRITEM 最小输入：material、plant、quantity、unit、delivery date、purchasing group。Registry 保留完整技术目标（如 `PRITEM.MATERIAL`），专用 `PrCreateDraftExecutor` 负责把目标拆成 table + field 并构造 BAPI envelope。

2026-07-17 首次 live smoke 返回 `Please enter items first` / `Enter Document Type`。随后对 sandbox SAP repository 做只读 JCo metadata 探针，确认当前 release 的直采最小结构为：

- `PRHEADER.PR_TYPE="NB"` + `PRHEADERX.PR_TYPE="X"`
- `PRITEM.PREQ_ITEM="00010"` + `MATERIAL` / `PLANT` / `QUANTITY` / `UNIT` / `DELIV_DATE`
- `PRITEMX.PREQ_ITEM="00010"` + `PREQ_ITEMX="X"` + 所有已填 item 字段的 `"X"` 标记
- ISO `delivery_date` 转为 JCo-compatible date 后写入

第二次 live smoke 证明上述 envelope 已被 SAP 接受，但返回 `Enter Purch. Group`。用户随后确认 sandbox 采购组 `601`。`purchasing_group` 因此作为必填业务参数进入 capability、Agent 缺参澄清和审批参数快照，并映射到 `PRITEM.PUR_GROUP`；`601` 只作为本次 live 请求值，不硬编码到 executor。

采购组修复后的唯一一次 live WRITE 成功创建 PR `10137471`，但结构化 `prNumber` 为空。只读 JCo metadata 随后确认 `BAPI_PR_CREATE` 的正式导出参数包含 `NUMBER`；executor 应优先读取 `EXPORTS.NUMBER`，仅在其为空时回退 `PRITEMEXP.PREQ_NO`。Agent 仅在 execute 成功后把本地 approval 状态从 `approved` 转为 `executed`。

Gateway Controller 对 Action execute 必须把内部 `ExecutionResult` 映射为公开 `ActionResult`，使 `prNumber` 与 `commitStatus` 保持顶层稳定契约；READ capability 继续返回原 `ExecutionResult`。

空 table 在 append 前可能尚未 initialized，因此 executor 必须按 metadata 中是否存在参数/字段判断，不能用 `isInitialized("PRITEM")` 作为 table existence check。`PR_TYPE="NB"` 是专用 executor 的 MVP 常量；未来支持多 document type 时迁移到受治理的 binding defaults，不向 Agent 暴露 SAP 技术字段。

当前 SAP metadata 中 `COSTCENTER` 不属于 `PRITEM`。本 change 的 live 验收只覆盖 1 个直采 PR；间采继续保留 mock 覆盖，其真实 account-assignment structure 另行设计。

### D6: Human Approval 使用 Workbench 两阶段 continuation

首次 Action 请求只允许完成 intent、CallPlan、Gateway validate 与 `pending ApprovalRecord` 创建，然后返回 `awaiting_approval`；不得在同一次 `run_query()` 中调用 `approve()` 或 Gateway execute。Workbench 服务端 run store 保存 pending record、精确 CallPlan 和原始 query，浏览器 approval endpoint 只提交 `approve`/`reject` decision，不能覆盖 capability、参数或 snapshot hash。

批准 continuation 从服务端 pending context 恢复同一 Action：`pending -> approved -> Gateway approve -> Gateway execute`；成功后才转 `executed`。拒绝、重复决策、非 pending run 都不触发 Gateway execute。READ capability 保持现有同步路径。

### D7: WRITE trace 使用与 ActionResult 同源的 resultSummary

Gateway trace 保留现有通用字段，并新增脱敏 `resultSummary`。READ/validate trace 使用空对象保持兼容；Action execute 从最终 `ActionResult` 写入 `prNumber`、`commitStatus`、SAP RETURN。`errorType` 与 `durationMs` 保持顶层字段。成功、approval 拒绝、SAP business error 与 commit error 使用同一结构，敏感字段递归过滤。

WRITE 在 technical override、参数校验、dispatch exception 等 SAP 前失败时同样返回并记录 `ActionResult(commitStatus=none)`。`commitStatus` 由 executor 显式提供实际事务结果：`committed`、`rolled_back`、`rollback_failed` 或 `none`，禁止由 `ErrorType` 推断。`BAPI_PR_CREATE` 与 commit/rollback 必须共享同一个 `JCoContext` stateful LUW；commit 成功后的结果提取失败保持 `committed`，不再 rollback。

## Risks / Trade-offs

- [approval 退化 vs roadmap §12] -> 文档明确薄纵切退化，row 11 RecommendationPlan 接回后升级为建议版本匹配。
- [sandbox PR 凭证产生真实数据] -> 仅在 dev/sandbox client 执行；禁止生产 client；`.env` 配置确认。
- [commit 后 SAP 异常残留] -> commit RETURN 检查 + rollback 兜底 + trace 记录实际 commit/rollback 结果；rollback 自身失败显式标记。
- [duplicate submit 同 approval 重复/并发 execute] -> dispatch 前原子 claim，失败者拒绝；一次 dispatch 尝试后 approval 保持已消费。
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

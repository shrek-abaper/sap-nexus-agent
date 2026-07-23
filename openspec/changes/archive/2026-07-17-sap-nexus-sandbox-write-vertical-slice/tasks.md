## 1. Schema 与契约

- [x] 1.1 新增 `schemas/approval-record.schema.json`，定义审批对象（PR 参数快照 hash）、审批人、审批时间、过期时间、执行状态
- [x] 1.2 新增 `schemas/action-result.schema.json`，定义 PR 号、SAP RETURN、commit 状态、duration、traceId，与 `execution-result.schema.json` 区分
- [x] 1.3 扩展 `schemas/capability.schema.json`：`kind: Action` 必须 `requiresApproval=true` 且 `sideEffect=sap_write`；`kind: Function` 必须 `sideEffect=none`
- [x] 1.4 验证现有 2 个 read capability 仍通过增强后的 schema 校验

## 2. Registry capability 注册

- [x] 2.1 在 `registry/capabilities.yaml` 新增 `MM.PR.CreateDraft`（`kind: Action`、`sideEffect: sap_write`、`requiresApproval: true`、`executor.type=JCO_RFC`、`rfcName=BAPI_PR_CREATE`），含 PRITEM 最小输入字段与 output 映射
- [x] 2.2 如需新增 JCo write binding，更新 `registry/executor-bindings.yaml`
- [x] 2.3 运行 `scripts/validate-registry-contract.py` 确认 registry 校验通过

## 3. Gateway approval 守卫

- [x] 3.1 新增 approval 守卫组件：execute 入口校验 ApprovalRecord 存在性、过期、参数快照 hash 版本匹配、重复执行
- [x] 3.2 守卫命中返回结构化错误（`APPROVAL_REQUIRED`/`APPROVAL_EXPIRED`/`APPROVAL_VERSION_MISMATCH`/`APPROVAL_DUPLICATE`），在 SAP 调用前 fail-closed
- [x] 3.3 守卫单元测试覆盖四种拒绝场景

## 4. Gateway WRITE commit/rollback 守卫

- [x] 4.1 扩展 `JcoRfcTechnicalAdapter`/dispatcher：`MM.PR.CreateDraft` execute `BAPI_PR_CREATE`，按 capability `kind`/`sideEffect` 路由到 write 路径
- [x] 4.2 写入成功后内部强制 `BAPI_TRANSACTION_COMMIT`（`WAIT=X`），检查 commit RETURN
- [x] 4.3 SAP RETURN E/A 或 commit 失败调用 `BAPI_TRANSACTION_ROLLBACK`，返回 `SAP_BUSINESS_ERROR`
- [x] 4.4 read 路径（`Function`）永不调用 commit/rollback 隔离测试
- [x] 4.5 commit/rollback 单元测试（mock JCo destination）覆盖成功提交、业务错误回滚、commit 失败回滚
- [x] 4.6 `PrCreateDraftExecutor` 构造 `PRHEADER/PRHEADERX/PRITEM/PRITEMX` 直采 technical envelope（`PR_TYPE=NB`、item `00010`、X indicators、JCo date）
- [x] 4.7 单元测试使用真实 BAPI 结构 mock，断言空 table 仍被填充且完整 mapping 不产生假绿

## 5. ActionResult 与 trace

- [x] 5.1 实现 `ActionResult` 返回结构（PR 号从 `EXPORTS.NUMBER` 提取、`PRITEMEXP.PREQ_NO` fallback、commit 状态、duration、traceId）
- [x] 5.2 写入 execute 写入 `TraceSpan`：参数摘要、PR 号、commit 状态、SAP RETURN、错误类型、duration，敏感字段脱敏
- [x] 5.3 trace 回放测试：给定 traceId 能定位参数、PR 号、commit 状态，不含 SAP 凭据

## 6. Agent Action CallPlan 与 approval 状态机

- [x] 6.1 扩展 `agent/sap_nexus_agent/call_plan.py` 承载 Action 语义
- [x] 6.2 新增 approval 状态机（pending -> approved -> executed/rejected）与 `ApprovalRecord` 客户端生成
- [x] 6.3 缺参只澄清、不生成 approval 的逻辑（material/plant/quantity 必填校验）
- [x] 6.4 新增 `agent/sap_nexus_agent/action_result.py` 解析 Gateway write 返回
- [x] 6.5 Agent 单元测试：缺参澄清、审批通过执行、审批状态流转

## 7. Eval 写入回归

- [x] 7.1 新增 `evals/pr_create_cases.yaml`（或 .json），覆盖 approval missing/expired/version-mismatch、SAP RETURN E/A、duplicate submit、成功 PR 创建
- [x] 7.2 接入 `scripts/verify-agent-callplan-evidence.sh` 纳入 write 回归
- [x] 7.3 运行 eval 回归全部断言通过
- [x] 7.4 将 `purchasing_group` 建模为必填、可审批快照化输入，映射到 `PRITEM.PUR_GROUP` 并补齐 Agent/Gateway/eval 回归
- [x] 7.5 基于成功 live 证据从 `EXPORTS.NUMBER` 提取 PR 号，并在成功后记录 approval `executed` 状态
- [x] 7.6 Gateway Action execute 返回顶层 `ActionResult(prNumber, commitStatus)`，READ 响应保持不变

## 8. Live smoke 验证

- [x] 8.1 用本地 `.env` 配置的 SAP 环境运行 `MM.PR.CreateDraft` live smoke，确认创建真实 PR 凭证并返回 PR 号
- [x] 8.2 确认 commit 成功、trace 记录完整、无 SAP 凭据泄漏

## 9. 文档与归档准备

- [x] 9.1 新增 `docs/runbooks/11-sandbox-write-vertical-slice.md`（session closeout 模板）
- [x] 9.2 更新 `docs/runbooks/README.md` 索引与 `docs/wiki/sap-nexus-agent-implementation-roadmap.md` §17.3 进度
- [x] 9.3 运行 `openspec validate --all --strict` 确认全部通过

## 10. Verify-fail repair：外部审批与 WRITE trace 回放

- [x] 10.1 Agent 首次 Action 请求只返回 pending approval；新增 RED/GREEN 测试证明不调用 Gateway approve/execute
- [x] 10.2 新增 Agent approve/reject continuation，并验证只用原 pending 参数快照与成功 validation、成功后 executed、失败不伪造 executed/approved
- [x] 10.3 Workbench runtime 保存 pending Action context，新增 approval API 与重复决策保护
- [x] 10.4 Workbench HITL 卡片支持批准/拒绝并覆盖 awaiting -> approved/rejected 状态回归
- [x] 10.5 Gateway WRITE trace 写入脱敏 resultSummary（PR 号、实际 commit/rollback 状态、SAP RETURN），WRITE 早期失败可回放且 READ trace 保持兼容
- [x] 10.6 补 approval 服务鉴权、stored/actual/request hash、不可覆盖 approval、并发原子 claim、stateful JCo LUW、事务失败回放与敏感字段测试
- [x] 10.7 统一 Design Doc、OpenSpec、registry output mapping 与注释中的 PR 号来源为 EXPORTS.NUMBER primary + PRITEMEXP fallback
- [x] 10.8 运行 Agent、Gateway、frontend、eval 与 OpenSpec 全量验证；不得再次执行 SAP WRITE
- [x] 10.9 更新 runbook、README、roadmap 与验证报告，完成 thorough review 后提交修复

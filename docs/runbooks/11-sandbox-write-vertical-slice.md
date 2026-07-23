# Sandbox Write Vertical Slice Runbook

## Document Version

| Field | Value |
|---|---|
| Runbook | `11-sandbox-write-vertical-slice` |
| Version | `v0.2.26` |
| Status | `Completed / Archived` |
| Created | `2026-07-16` |
| Updated | `2026-07-17` |
| Workstream | `sap-nexus-sandbox-write-vertical-slice`（首个 SAP WRITE / Approval 闭环纵切） |
| Related Change | `sap-nexus-sandbox-write-vertical-slice` |
| Design Doc | `docs/superpowers/specs/2026-07-16-sap-nexus-sandbox-write-vertical-slice-design.md` |
| Current Phase | 已合并到 `main` 并归档至 `openspec/changes/archive/2026-07-17-sap-nexus-sandbox-write-vertical-slice/`；verify/branch/archive 闭环完成；不得再次执行 SAP WRITE |

---

## 1. Session Goal

打通 SAP Nexus Agent 首个 WRITE / Approval 闭环 —— 以 `BAPI_PR_CREATE` 为首个 Action capability（`MM.PR.CreateDraft`）。在 sandbox / dev client 上验证 `RecommendationPlan -> ApprovalRecord -> Action CallPlan -> Gateway execute -> ActionResult -> SAP RETURN -> TraceSpan -> EvalCase` 完整链路，READ / WRITE 路径隔离，`ApprovalGuard` 在 SAP 调用前 fail-closed。

---

## 2. Source Of Truth

Read these before changing architecture, implementation plan, or scope:

```text
AGENTS.md
docs/runbooks/README.md
docs/runbooks/11-sandbox-write-vertical-slice.md
docs/wiki/sap-nexus-agent-technical-architecture.md
docs/wiki/sap-nexus-agent-implementation-roadmap.md
docs/superpowers/specs/2026-07-16-sap-nexus-sandbox-write-vertical-slice-design.md
openspec/changes/archive/2026-07-17-sap-nexus-sandbox-write-vertical-slice/
```

---

## 3. Architecture Decisions

### 3.1 commit / rollback 在 Gateway 内部强制

`JcoCapabilityExecutor` 的 write 分支在 `BAPI_PR_CREATE` 返回后，根据 `RETURN` 结构决定 `BAPI_TRANSACTION_COMMIT` 或 `BAPI_TRANSACTION_ROLLBACK`，Agent 侧不直接控制 SAP 事务边界。READ capability 永不调用 commit / rollback。

### 3.2 ApprovalGuard 在 execute 入口 fail-closed

`ApprovalGuard` 在 Gateway `execute` 入口、SAP 调用前拦截，覆盖 4 种拒绝场景（approval missing (`APPROVAL_REQUIRED`) / expired (`APPROVAL_EXPIRED`) / parameter snapshot hash mismatch (`APPROVAL_VERSION_MISMATCH`) / duplicate submit (`APPROVAL_DUPLICATE`)），任一未通过即拒绝执行，不进入 JCo 调用。

### 3.3 ApprovalRecord 进程内 InMemoryApprovalStore（MVP）

MVP 阶段 `ApprovalRecord` 存储使用进程内 `InMemoryApprovalStore`，不持久化。生产化前需替换为带 TTL 与审计回放的持久 store。

### 3.4 approval TTL 默认 600s

`ApprovalRecord` 默认 TTL 600 秒，过期后 `ApprovalGuard` 拒绝执行，需重新发起 approval。

### 3.5 间采薄纵切先只支持 `acct_assgn_cat="K"`

间采（indirect procurement）薄纵切只支持 `acct_assgn_cat="K"`（成本中心），其余 account assignment category 留后续。直采（无 account assignment）与间采（K + cost center）两条路径已覆盖。

### 3.6 Human Approval 必须来自 Workbench 外部 decision

首次 Action 请求只完成 intent、CallPlan、Gateway validate 与 pending `ApprovalRecord` 创建，然后返回 `awaiting_approval`。`run_query()` 不调用 `approve()`、Gateway approve 或 execute。Workbench 服务端 run store 保存 pending Action 的 exact CallPlan/validation/ApprovalRecord；浏览器 approval API 只接受 `approve|reject` decision，不能提交或覆盖 capability、参数或 snapshot hash。只有批准 continuation 才执行 `pending -> approved -> Gateway approve -> Gateway execute`；拒绝与重复决策均不进入 Gateway/SAP。

### 3.7 WRITE trace 与 ActionResult 同源

Gateway 通用 trace 增加脱敏 `resultSummary`。READ/validate trace 使用空对象保持兼容；Action execute 从最终 `ActionResult` 写入 `prNumber`、`commitStatus` 与 SAP RETURN，`errorType`/`durationMs` 保持顶层字段。HTTP 响应与 trace 使用同一个 ActionResult，不允许出现两套结果真相。

### 3.8 Approval authority 与 single-execution

Agent -> Gateway `/approve` 使用 `X-SAP-Nexus-Approval-Token`；Gateway 严格校验 capability、approved 状态、当前有效且不超过 600 秒的 TTL、stored parameters canonical hash。execute 时 Gateway 重新计算 actual parameters hash，并与 stored/request hash 交叉校验。`approvalId` 只允许首次注册，dispatch 前原子 `approved -> executing`；重复注册、重复 execute 或并发 loser 均返回冲突/`APPROVAL_DUPLICATE`。

### 3.9 Stateful JCo LUW 与事务事实

`BAPI_PR_CREATE`、`BAPI_TRANSACTION_COMMIT`/`ROLLBACK` 共享同一个 `JCoContext.begin/end`。pre-SAP/dispatch failure 为 `none`；commit 成功为 `committed`；rollback 成功/失败为 `rolled_back`/`rollback_failed`。commit 已成功后的 PR 号提取异常保持 `committed`，不得再次 rollback 或诱导重试。

---

## 4. Completed Implementation

### 4.1 Capability Registry

- `MM.PR.CreateDraft` 在 `registry/capabilities.yaml` 注册：`kind=Action`、`governance.sideEffect=sap_write`、`governance.requiresApproval=true`、`governance.approvalPolicy=human_required`、`dataClassification=internal`、`auditRequired=true`。
- 6 个 required inputs（`material`、`plant`、`quantity`、`unit`、`delivery_date`、`purchasing_group`）+ 2 个 optional inputs（`acct_assgn_cat`、`cost_center`）。
- 2 个 outputs：`prNumber`（`evidenceRole=primaryFact`）、`returnMessages`（`evidenceRole=executionEvidence`）。
- Executor binding：`JCO_RFC` + `rfcName=BAPI_PR_CREATE` + `bindingId=sap.mm.pr.create-draft`。
- Ontology identity：`sapnexus:MM_PR_CreateDraft` / `sapnexus:PurchaseRequisitionCreateAction`。
- Eval linkage：`evals/pr_create_cases.json`，9 个 caseIds 覆盖成功直采 / 间采、缺参澄清、approval missing / expired / version mismatch、duplicate submit、SAP business error。

### 4.2 Gateway（Java）

- `ApprovalGuard` 守卫在 `execute` 入口、SAP 调用前 fail-closed。
- `PrCreateDraftExecutor` 实现 `BAPI_PR_CREATE` + commit / rollback 守卫（write 分支强制）。
- READ capability 路径与 WRITE capability 路径隔离，commit / rollback 仅在 write 分支触发。
- READ / WRITE 路径隔离回归测试落地。
- WRITE execute trace 记录脱敏 `resultSummary`；成功、approval 拒绝、SAP business error、commit error 均可回放，READ trace 保持兼容。
- approval 注册不可覆盖；stored/actual/request hash 三方绑定；阻塞 dispatch 期间重放 approval 仍只允许一次 SAP dispatch。
- Action dispatch exception 仍返回并 trace 同源失败结果，approval 已消费且不可重放。
- JCo WRITE 与 commit/rollback 使用同一 stateful context；commit lookup/execute/RETURN、rollback failure 与 post-commit extraction failure 均有事务事实回归。
- resultSummary 自由文本脱敏覆盖 destination、token/secret、Authorization Bearer/Basic、JSON-like 与带空格 quoted value。

### 4.3 Agent（Python）

- Approval 状态机：`pending -> approved -> executed`，含 `rejected` 终态；expiry 由 `expires_at` 字段计算（`is_expired()`），非独立 enum 状态。
- Action CallPlan 生成与参数 snapshot hash 计算（用于 `ApprovalGuard` 校验）。
- `ActionResult` 解析：`prNumber` 作为 `primaryFact`，`returnMessages` 作为 `executionEvidence`。
- PR 意图识别：直采（无 account assignment）与间采（`acct_assgn_cat="K"` + `cost_center`）参数抽取与缺参澄清。
- 首次 Action 只返回 pending approval；`continue_action()` 只接受服务端保存的 exact context 与外部 approve/reject decision，参数快照不一致时零 Gateway 调用。

### 4.4 Workbench HITL（Next.js）

- Agent run store 保存 pending Action context；`POST /api/agent-runs/{runId}/approval` 只接受 decision，额外参数/hash 字段返回 400。
- pending run 发出 `approval_required -> awaiting_human_approval`，不伪造 completed/failed；批准后同一 runId 追加 execute/result 事件，拒绝进入 rejected 终态。
- HITL 卡片展示脱敏 PR 参数快照、Approval ID、expiry、snapshot hash 与批准/拒绝按钮；等待审批时静态 SSE 正常关闭，不误报连接失败。

### 4.5 Eval

- `evals/pr_create_cases.json` 9 个 case：`pr-create-success-direct`、`pr-create-success-indirect`、`pr-create-missing-param`、`pr-create-indirect-missing-cost-center`、`pr-create-approval-missing`、`pr-create-approval-expired`、`pr-create-approval-version-mismatch`、`pr-create-duplicate-submit`、`pr-create-sap-business-error`。

---

## 5. Verification Evidence

| Layer | Command | Result |
|---|---|---|
| Registry | `.venv/bin/python scripts/validate-registry-contract.py registry/capabilities.yaml` | `Registry contract valid` |
| Java Gateway | `/tmp/gradle-8.8/bin/gradle --no-daemon test` | repair fresh run：core / jco / odata / app 全部通过；最终计数见 verification report |
| Agent | `.venv/bin/python -m pytest agent/tests/ -q` | `233 passed, 1 skipped` |
| Frontend | `npm --prefix frontend run verify` | typecheck PASS；Vitest `33/33`；Next production build PASS |
| Registry | `.venv/bin/python scripts/validate-registry-contract.py registry/capabilities.yaml` | `Registry contract valid`；`prNumber=EXPORTS.NUMBER` |
| Eval / OpenSpec | 三组 eval + `openspec validate --all --strict` | `7/7`、`13/13`、`9/9`；OpenSpec `7 passed, 0 failed` |
| Thorough review | repair review + fix re-review + final spot-check | 最终 `Critical=0`、`Important=0`、`Ready to merge: Yes` |

---

## 6. Live Smoke（本地 .env SAP，Task 17）

### 6.1 验证执行（2026-07-17）

执行人：Task 17 实现 agent。范围：仅直采最小验证（间采留 mock，不 live）。

**Step 1 - .env SAP 配置确认**：`SAP_CLIENT` / `SAP_ASHOST` / `SAP_SYSNR` / `SAP_USER` 均存在（值已脱敏，未打印）。`SAP_JCO_LIB_PATH` 未在 .env 设置，启动时由 Task 17 补 `services/gateway/jco/lib/linux`。

**Step 2 - Gateway 启动**：`cd services/gateway && ./gradlew --no-daemon bootRun`（加载 .env + 补 `SAP_JCO_LIB_PATH`）。Spring Boot 2.8s 启动成功。Health：

```json
{"status":"UP","gateway":"sap-nexus-jco-gateway","jcoConfigured":true,"sapEnvironmentPresent":true,"sensitiveFieldsExposed":false}
```

环境层（JCo 库 / SAP 连接字段）配置正常。

**Step 3 - 直采 PR create live execute**：经 CLI 与直接 HTTP 两条路径验证，均未创建 PR。

| 路径 | 命令 | 结果 |
|---|---|---|
| HTTP Test A | `POST /capabilities/MM.PR.CreateDraft/execute`（无 approvalId） | `success=false, errorType=APPROVAL_REQUIRED, HTTP 400` |
| HTTP Test B | 同上，带 `approvalId=appr-agent-created-0001` | `success=false, errorType=APPROVAL_REQUIRED, HTTP 400` |
| CLI（brief Step 2） | `.venv/bin/python -m sap_nexus_agent.cli --intent-mode rule "给物料 M001 工厂 1000 建 10 EA 采购申请 交货 2026-08-15"` | `APPROVAL_REQUIRED`，无 PR 号 |

**无 PR 号产生**（approval 守卫在 JCo/SAP 调用前拒绝，未触碰真实 SAP WRITE）。

**Step 4 - trace 完整性与凭据安全**：

- Agent `runtime/traces/approval.jsonl`：记录 `capabilityId=MM.PR.CreateDraft` + `approvalId` + `parameterSnapshotHash` + `toState=pending`（仅到 pending，从未 approved）；`parametersSummary` 只记 keys/count，不记值。
- Gateway `runtime/gateway-jco/traces.jsonl`：记录 `MM.PR.CreateDraft` execute + `errorType=APPROVAL_REQUIRED` + `parameterSummary`。
- 凭据扫描（password/passwd/destination/token/ashost/sysnr/client）：无泄漏。

### 6.2 根因：approval 注册断层（代码层 blocker）

**现象**：Agent 创建的 `ApprovalRecord` 无法进入 Gateway 的 `InMemoryApprovalStore`，导致 `ApprovalGuard.check(null, ...)` 恒返回 `APPROVAL_REQUIRED`，write 路径在 SAP 调用前被拒。

**证据链**：

1. Gateway 生产代码无 `approvalStore.save(...)` 调用：`grep` 确认 `ApprovalStore` 在非测试源码仅出现于 `CapabilityController` 的 `find()`（读）与 `markExecuted()`（写状态），`save()` 的 3 个 caller 全在测试（`CapabilityWriteExecutionApiTest` 手动预填 record）。
2. Gateway 无 approve endpoint：仅 `CapabilityController`（`/validate`、`/execute`）与 `HealthController`，无 `/approve` 或 `/approvals`。
3. Agent `orchestrator.run_query` Action 分支：`create_approval_record(...)` 生成 `pending` record（仅 Python 内存 + approval.jsonl），未调 `approve()`，也未将 record 发给 Gateway 注册。
4. `gateway_client.execute` 仅传 `approvalId`（字符串），不传 record 全量；Gateway `approvalStore.find(approvalId)` 在空 store 返回 `null`。

**影响**：Task 1-16 的 approval 状态机（Agent 侧 `pending->approved->executed`）与 ApprovalGuard（Gateway 侧 fail-closed）各自正确，但二者之间缺少注册通道。任何 write capability 的 live execute 都会被 `APPROVAL_REQUIRED` 拒绝，不止 PR create。

**修复方向（超出 Task 17 范围，需主会话决策开新 task）**：在 Gateway 增加 approve endpoint（`POST /capabilities/{id}/approve`，接收 `ApprovalRecord` 调 `save()`），Agent orchestrator 在 execute 前先调该 endpoint 注册 approved record；或在 execute 入口从请求体自动 `save`。属核心源码改动，Task 17 禁止修改。

### 6.3 Task 18/19 修复后的最终 live smoke

Task 18 已补齐 Agent -> Gateway approval 注册通道及 `parameterSnapshotHash` 传递。随后两次真实直采 execute 均使用 sandbox/dev client、material `DEMOA1`、plant `1000`、quantity `10 EA`、delivery date `2026-08-15`；两次均收到明确 SAP 失败响应，无 PR 号，Gateway 失败分支调用 `BAPI_TRANSACTION_ROLLBACK`，未 commit。

| Attempt | Trace ID | Result | Conclusion |
|---|---|---|---|
| 首次 execute | `3ae1db41-80ae-4a66-a0f9-4e33fe06442f` | `SAP_BUSINESS_ERROR`: `Please enter items first`; `Enter Document Type`; no object created | approval/execute 已到 SAP，但 technical envelope 缺失 |
| Task 19 修复后最终 execute | `451f0c92-d6a9-413e-a44f-3b276b5a0523` | `SAP_BUSINESS_ERROR`: `Enter Purch. Group`; no object created；另有 special procurement type `L` warning | header/item/X envelope 已被 SAP 接受；阻塞转移到 Purchasing Group 与 sandbox 物料采购主数据 |

Task 19 基于 sandbox JCo repository metadata 修复 `PrCreateDraftExecutor`：

- `PRHEADER.PR_TYPE="NB"` + `PRHEADERX.PR_TYPE="X"`
- `PRITEM/PRITEMX` item `00010`
- `MATERIAL/PLANT/QUANTITY/UNIT/DELIV_DATE` 与对应 X indicators
- ISO delivery date 转 JCo-compatible date
- table existence 由 metadata 判断，不再用空 table 的 `isInitialized` 状态

TDD 证据：修复前 focused test 因缺少 `PRHEADER.PR_TYPE` 调用失败；修复后 `PrCreateDraftExecutorTest` 3 个场景通过，Gateway 全量测试 `BUILD SUCCESSFUL`。

Trace 证据：Gateway trace 只记录 capability、参数摘要、success/duration/errorType；Agent approval trace 只记录 approvalId、snapshot hash、参数 keys/count 与状态。对两份 trace 扫描 `password/passwd/token/secret/sap_ashost/sap_user/sap_password/destination`，结果为 `CLEAN`。runtime trace 未加入 Git。

根据用户批准的停止条件，Task 19 后只允许一次额外 live execute；最终 execute 失败后不再进行第三次 SAP WRITE。当前仍无真实 PR 号，OpenSpec live-smoke 验收项不得勾选。

### 6.4 Purchasing Group 治理后的成功 live smoke

用户在前述授权耗尽后重新明确授权：仅 sandbox/dev、仍只做直采、采购组使用 `601`、只执行一次。实现没有硬编码 `601`，而是将 `purchasing_group` 建模为必填业务输入，进入 Agent 缺参校验、approval 参数快照、registry mapping，并写入 `PRITEM.PUR_GROUP` / `PRITEMX.PUR_GROUP="X"`。

Pre-live 门禁：

- Agent：`218 passed, 1 skipped`。
- PR eval：`9/9`；seed eval：`13/13`；inventory eval：`7/7`。
- Gateway：`BUILD SUCCESSFUL`。
- OpenSpec strict validation：`7 passed, 0 failed`。
- READ 预检：material `DEMOA1` / plant `1000`，Gateway trace `10b8b29f-70c7-4b01-b462-9e4d1cf12bb2`，`success=true`。

唯一一次 WRITE：

| 字段 | 事实 |
|---|---|
| 参数 | material `DEMOA1`；plant `1000`；quantity `10 EA`；delivery date `2026-08-15`；purchasing group `601` |
| Gateway trace | `6d04f0b2-754b-490f-8f7d-5142a6593980` |
| 结果 | `success=true`、`errorType=NONE`、duration `835 ms` |
| SAP RETURN | `Purchase requisition number 10137471 created`（message `06/402`） |
| PR | `10137471` |
| 事务 | `PrCreateDraftExecutor` 只有在 `BAPI_TRANSACTION_COMMIT` 返回无 E/A 后才返回 success；因此该 success trace 是 committed 分支证据 |
| 警告 | `CI_EBANDB` ExtensionIn warning；material special procurement type `L` warning；均未把结果降为失败 |

本次 live 同时暴露两个成功路径契约缺口：BAPI 的结构化 `data.prNumber` 为空，Agent 本地 approval trace 只到 `approved`。随后只做 metadata/read 与离线 TDD，**未再次执行 SAP WRITE**：

- metadata-only JCo probe 确认 `BAPI_PR_CREATE` export 参数为 `NUMBER,PRHEADEREXP`。
- executor 改为优先读取 `EXPORTS.NUMBER`，再回退 `PRITEMEXP.PREQ_NO`；测试以 `10137471` 固化。
- Agent 成功路径补 `approved -> executed`，失败路径仍停在 `approved`。
- Gateway Action execute 映射为顶层 `ActionResult`，返回 `prNumber` 与 `commitStatus=committed`；READ 仍返回 `ExecutionResult`。
- Gateway/Agent trace 凭据扫描结果：`CLEAN`；runtime trace 未加入 Git。

### 6.5 Verify-fail governance repair（未再次 WRITE）

完整验证在 live smoke 后发现两项 CRITICAL：Agent 在单次 `run_query()` 中自动完成 pending -> approved -> execute；Gateway trace 不包含 PR 号、commit 状态或 SAP RETURN。2026-07-17 repair 将运行边界改为 §3.6 的 Workbench 两阶段 continuation，并按 §3.7 增加同源 `resultSummary`。

TDD 证据：

- Agent RED：完整 PR 请求原先返回 execute failure/success，而不是 `awaiting_approval`；GREEN 后首次请求 zero approve/execute，approve/reject continuation 与 snapshot mismatch 均有回归。
- Workbench RED：pending Action 原先被写成 `approval_not_required` + failed；GREEN 后 pending、approve、reject、extra-field rejection、404/409 与同 run event append 全覆盖。
- Gateway RED：`TraceRecord.ofAction` 不存在；Controller HTTP ActionResult 正确但 trace 缺 PR/commit/RETURN；GREEN 后 core/app focused suites 与 Gateway 全量测试通过。
- 本 repair 只运行 mock/unit/build/eval，不启动 Gateway live 服务，不调用 SAP WRITE。既有 PR `10137471` 是唯一成功 live 证据。

---

## 7. Blockers

- **已修复 blocker**：approval 注册断层由 Task 18 修复；BAPI header/item/X envelope 由 Task 19 修复；`PUR_GROUP` 由 Task 20 建模并 live 验证。
- **当前 live blocker**：无。真实 sandbox PR `10137471` 已创建并 commit。
- **当前流程 blocker**：无。Comet build/verify guard、本地 merge `main`、merged-main 重验与 archive 均已完成。
- **已记录非阻塞 warning**：`CI_EBANDB` ExtensionIn warning 与 special procurement type `L` warning；本 change 不扩展 ExtensionIn 或采购主数据治理。
- SAP 环境层（JCo 库、SAP 连接字段、`.env`）已就绪，非环境阻塞。

---

## 8. Session Closeout - 2026-07-17

### Completed

- 新增 runbook 11（本文件），记录首个 SAP WRITE / Approval 闭环纵切的架构决策、交付物与验证证据。
- 更新 `docs/runbooks/README.md`：索引追加 runbook 11 行；`Current Source Of Truth` 区块把 `sap-nexus-sandbox-write-vertical-slice` 从 `Next recommended change` 迁移到 `Current completed change`，并把 `Next recommended change` 推进到 `sap-nexus-recommendation-reasoning`（row 11）。
- 更新 `docs/wiki/sap-nexus-agent-implementation-roadmap.md`：row 10 从 `待启动` 更新为 `已完成（live smoke Task 17 待执行）`；§17.3 从"待启动"更新为"已完成"；§17 推荐下一步指向 row 11；版本记录追加 `v0.2.21`（`2026-07-17`）。
- feature 分支 fast-forward 合并到 `main` 后完成 merged-main 全量验证；Comet archive `7/7` 成功，change 移至 `openspec/changes/archive/2026-07-17-sap-nexus-sandbox-write-vertical-slice/`，主 spec 合并到 `openspec/specs/pr-create-action/spec.md`。

### Verified

- Command: `git status --short`
- Result: 最终归档提交后 tracked 工作树 clean；`.superpowers/` 与归档 `.comet/subagent-progress.md` 为刻意排除的未跟踪协调文件，runtime trace 未纳入 Git。
- Command: `openspec list --json`
- Result: `{"changes":[]}`；无 active change，归档 `.comet.yaml` 为 `verify_result: pass`、`branch_status: handled`、`archived: true`。
- Command: `openspec validate --all --strict`
- Result: `7 passed, 0 failed`。
- Command: `.venv/bin/python scripts/validate-registry-contract.py registry/capabilities.yaml`
- Result: `Registry contract valid`。
- Command: `GRADLE_USER_HOME=/tmp/gradle-home /tmp/gradle-8.8/bin/gradle --no-daemon test --rerun-tasks`
- Result: `BUILD SUCCESSFUL`；JUnit XML `145 tests, 0 failures, 0 errors, 0 skipped`。
- Command: `.venv/bin/python -m pytest agent/tests/ -q`
- Result: `233 passed, 1 skipped`。
- Command: `scripts/verify-agent-callplan-evidence.sh`
- Result: `233 passed, 1 skipped`；`Eval passed: 7/7`、`13/13`、`9/9`；OpenSpec `7 passed, 0 failed`。

### Blockers

- 无 live blocker。成功证据为 PR `10137471`、Gateway trace `6d04f0b2-754b-490f-8f7d-5142a6593980`、`success=true/errorType=NONE`。

### Next Start Here

1. 不再执行 SAP WRITE；本 change 的一次性成功 live 证据已经取得。
2. 本 change 已完成 repair evidence、thorough review、merged-main verification 与 archive；后续维护以主 spec 和归档 change 为准。
3. 后续可独立推进 `sap-nexus-recommendation-reasoning`（row 11）。

---

## 9. 后续

- 生产 client 写入（留后续，需 `sap-nexus-production-governance` workstream 支撑）。
- release / post 重量级 action（留后续，禁止在 sandbox write pilot 阶段触及）。
- `RecommendationPlan` 推理引擎（row 11，`sap-nexus-recommendation-reasoning`）。
- `InMemoryApprovalStore` 升级为持久化 + 审计回放 store（生产化前必修）。

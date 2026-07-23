---
comet_change: sap-nexus-sandbox-write-vertical-slice
role: technical-design
canonical_spec: openspec
archived-with: 2026-07-17-sap-nexus-sandbox-write-vertical-slice
status: final
---

# Design Doc: sap-nexus-sandbox-write-vertical-slice

- Change: `sap-nexus-sandbox-write-vertical-slice`
- Phase: design
- 日期: 2026-07-16
- 语言: zh-CN
- 关联: `openspec/changes/archive/2026-07-17-sap-nexus-sandbox-write-vertical-slice/proposal.md`、`design.md`、`specs/pr-create-action/spec.md`
- 上游决策来源: `brainstorm-summary.md`(2026-07-16 定稿)

## 1. 背景与目标

SAP Nexus Agent READ 阶段(Phase 0 -> 4D)已完整落地并归档,但 WRITE/Approval 闭环完全空白。本纵切以 `BAPI_PR_CREATE`(采购申请创建)为首个 `Action` capability,打通 READ -> WRITE 质变节点:

```
ApprovalRecord -> Action CallPlan -> Gateway validate -> SAP execute -> ActionResult -> SAP RETURN -> TraceSpan -> EvalCase
```

用本地 `.env` 配置的 SAP 环境做 live 验证。这是 roadmap §17.3 / row 10 既定方向。

**目标**:构建首个 SAP WRITE 受控闭环,建立 approval 守卫、commit/rollback 守卫、READ/WRITE 隔离硬边界,覆盖写入失败回归。

**非目标**:不做 RecommendationPlan 推理引擎(留 row 11)、不做生产 client 写入/release/post 重量级 action/多能力组合 planner、不做 RBAC/多租户/生产部署、不改现有 2 个 read capability 行为。

## 2. 架构与数据流

```
用户 "给物料X 工厂Y 建100个PR"
  │
  ▼
Agent (Python)
  Intent(缺参澄清) -> Action CallPlan -> approval 状态机(pending)
  生成 ApprovalRecord(参数快照 hash)
  │
  ├─▶ 审计: JSONL approval 状态事件 (runtime/traces/)
  └─▶ 渲染: Workbench HITL 审批卡片 (服务端 pending record 的脱敏视图)
       ┌────────────────────────────────────┐
       │ 📋 采购申请创建审批                  │
       │ 物料: X  工厂: Y  数量: 100 EA      │
       │ 交货: 2026-08-01  参数快照: a3f9... │
       │ [批准]  [拒绝]                       │
       └────────────────────────────────────┘
  │ 用户点"批准" -> approval: pending -> approved (写 JSONL)
  ▼
Gateway (Java, services/gateway)
  approval 守卫(入口 fail-closed) -> JCo WRITE execute(BAPI_PR_CREATE)
  -> commit/rollback 守卫(BAPI_TRANSACTION_COMMIT WAIT=X / ROLLBACK)
  │
  ▼
SAP (JCo) -> PR 凭证号
  │
  ▼
ActionResult(PR号 + commit状态 + traceId) -> Agent(executed) -> Narrator
```

**数据流要点**:

1. **READ/WRITE 隔离**:Gateway dispatcher 按 capability `kind`/`sideEffect` 路由。`Function`(read)走现有只读路径,永不 commit;`Action`(write)走新 WRITE 路径,必经 approval 守卫后才 commit。
2. **approval 状态**:Agent 审计流为 `pending -> approved -> executed/rejected`；Gateway 在 dispatch 前增加内部 `approved -> executing -> executed` 原子占用，`executing` 表示该 approval 已消费、不可重放。
3. **fail-closed 顺序**:受信 approval 注册 -> capability/状态/TTL/快照校验 -> 原子 claim -> SAP execute -> commit/rollback。任一前置失败不触发后续。
4. **PR 号提取**:优先读取 `EXPORTS.NUMBER`,仅在其为空时回退 `PRITEMEXP.PREQ_NO`;RETURN 成功消息辅助校验。

### 2.1 Verify-fail repair: external Human Approval continuation

2026-07-17 完整验证发现原实现把 approval 状态机错误地压缩在单次 `run_query()` 内：Agent 创建 `pending` 后立即自行调用 `approve()` 并执行 Gateway WRITE。该行为绕过了设计要求的外部 Human Approval 信号。本节是修复后的权威数据流，覆盖此前任何“单次同步调用完成审批与执行”的实现解释。

```
POST /api/agent-runs
  -> Agent parse/select/validate
  -> Action: create pending ApprovalRecord
  -> AgentOutcome(status=awaiting_approval, approvalRecord=pending)
  -> Node runtime 在 run store 保存 pending record + 原始 query
  -> SSE: approval_required -> awaiting_human_approval
  -> Workbench 显示受控参数快照与 [批准] [拒绝]

POST /api/agent-runs/{runId}/approval { decision: approve|reject }
  -> Node runtime 只按 runId 读取服务端 pending record；浏览器不得提交或覆盖参数
  -> reject: pending -> rejected；不注册 Gateway approval，不 execute
  -> approve: pending -> approved -> Gateway approve -> Gateway execute
  -> success: approved -> executed；SSE 追加 ActionResult 与完成事件
  -> failure: 保持 approved；SSE 追加结构化失败事件
```

**信任边界与幂等性**:

- `run_query()` 首次处理 Action 时只允许返回 `pending`，不得调用 `approve()`、`gateway.approve()` 或 `gateway.execute()`。
- Workbench approval endpoint 是外部 Human Approval 信号的唯一 Agent continuation 入口；它只接收 `decision`，审批参数、capabilityId、snapshot hash 和 approvalId 均从服务端 run store 读取，避免浏览器伪造快照。
- continuation 必须使用首次 validate 后保存的精确 CallPlan/ApprovalRecord，不重新从自由文本生成一组可漂移参数。
- continuation 还必须复核原 validation 成功且 capability 与 CallPlan 一致；失败时 ApprovalRecord 保持 pending，Workbench 不得把该结果渲染为 approved。
- 每个 run 只允许决策一次；非 pending run、重复批准或重复拒绝返回冲突，不触发 Gateway/SAP。
- Node runtime 继续使用现有进程级 run store 承载本地 Workbench MVP 状态；进程重启后 pending run 失效，不引入数据库或生产级持久化。
- Python CLI continuation payload 通过 stdin 传递，不放入命令行参数；payload 只包含服务端保存的受控 Action 上下文，不包含 SAP 凭据。
- READ capability 沿用现有同步执行路径并发出 `approval_not_required`，不经过 approval endpoint。
- Agent 到 Gateway 的 `/approve` 注册使用独立 `X-SAP-Nexus-Approval-Token` 服务令牌；缺失、空值或不匹配一律 fail-closed，令牌不进入请求体、URL 或 trace。
- Gateway 使用与 Agent 相同的 UTF-8 compact/sorted JSON canonicalization，分别重算 `ApprovalRecord.parameters` 与 execute 实际参数的 SHA-256；调用方提交的 hash 只作为额外交叉校验，不能替代服务端重算。
- Gateway 只接受 capability 匹配、状态严格为 `approved`、TTL 不超过 600 秒且快照 hash 自洽的记录；dispatch 前必须原子 claim，只有一个并发请求可进入 SAP。
- 同一 `approvalId` 只能首次注册；`putIfAbsent` 拒绝把 `executing/executed` 覆盖回 `approved`，包括 dispatch 进行中的重放竞态。

**Workbench 状态**:

- 新增运行状态 `awaiting_approval`；静态 SSE 响应到达该状态后前端正常关闭当前连接，不把连接关闭误报为运行失败。
- 批准后重新拉取同一 runId 的追加事件；拒绝后进入 `rejected` 终态。
- HITL 卡片只展示已脱敏的参数快照、approvalId、TTL 和批准/拒绝操作，不直接调用 Gateway 或 SAP。

### 2.2 Verify-fail repair: replay-complete WRITE trace

Gateway trace 保留现有通用字段，并为 execute 增加脱敏的 `resultSummary`。READ/validate trace 的 `resultSummary` 为空对象，保持现有消费者兼容；Action execute 的 summary 至少包含：

- `prNumber`
- `commitStatus`
- `returnMessages`（仅 SAP RETURN 业务字段）

`errorType` 与 `durationMs` 继续使用现有顶层字段。Gateway 必须先把 `ExecutionResult` 映射为 `ActionResult`，再从同一结果构造 trace，避免 HTTP 响应和审计记录产生两套结果真相。approval guard 拒绝、参数校验失败、dispatch 异常、SAP business error、commit error 与成功结果都写同一结构；敏感键递归过滤规则同时覆盖参数摘要和 result summary，并覆盖 `key=value`、colon、JSON-like、空格分隔、Bearer/Basic 等自由文本格式。`commitStatus` 是 executor 返回的事务事实：pre-SAP 为 `none`，成功为 `committed`，实际 rollback 成功/失败分别为 `rolled_back`/`rollback_failed`，不得由 `ErrorType` 推断。commit 成功后的结果提取失败保持 `committed`，不得再 rollback 或暗示可安全重试。

## 3. 组件与职责边界

| 组件 | 模块 | 职责 | 新增/扩展 |
|---|---|---|---|
| `ApprovalGuard` | services/gateway/execution | execute 入口校验 approval 存在/过期/版本/duplicate | 新增 |
| `JcoCapabilityExecutor`(write 分支) | services/gateway/jco | 执行 `BAPI_PR_CREATE` + commit/rollback | 扩展 |
| `TechnicalExecutionDispatcher` | services/gateway/execution | 按 `kind`/`sideEffect` 路由 read/write | 扩展 |
| `ActionResult` | services/gateway/result | write 结果结构(PR 号/commit 状态/SAP RETURN/duration/traceId) | 新增 |
| `approval.py` | agent/sap_nexus_agent | approval 状态机 + 参数快照 hash + JSONL 落盘 | 新增 |
| `call_plan.py` | agent/sap_nexus_agent | 承载 Action 语义 | 扩展 |
| `action_result.py` | agent/sap_nexus_agent | 解析 Gateway write 返回 | 新增 |
| `orchestrator.py` | agent/sap_nexus_agent | 首次 Action 只产出 pending；外部批准 continuation 才 approve->execute->narrate | 扩展 |
| Workbench run store / approval API | frontend runtime + API routes | 服务端保存 pending Action 上下文，接收 approve/reject 决策并续执行同一 run | 扩展 |
| HITL 审批卡片 | frontend | 服务端 pending record 的脱敏视图 + 批准/拒绝按钮,复用现有 HITL 状态机 | 扩展 |
| `TraceRecord` / `CapabilityController` | services/gateway/core | WRITE trace 写入脱敏 resultSummary，READ trace 兼容 | 扩展 |
| `MM.PR.CreateDraft` | registry/capabilities.yaml | 首个 Action capability | 新增 |
| `ApprovalRecord`/`ActionResult` schema | schemas/ | 契约定义 | 新增 |
| `capability.schema.json` | schemas/ | Action↔sideEffect↔approval 校验 | 扩展 |
| `pr_create_cases.yaml` | evals/ | 写入回归集 | 新增 |

**边界设计原则(每单元可独立理解与测试)**:

- `ApprovalGuard` 只管"能不能执行"(守卫),不碰 SAP;可纯单元测试(mock store)。
- `JcoCapabilityExecutor` write 分支只管"执行 BAPI + commit/rollback"(技术执行),不碰 approval 语义;可 mock destination 测试。
- Agent `approval.py` 只管"审批状态与参数快照"(业务语义),不碰 Gateway;可纯 Python 测试。
- Workbench 卡片只管"展示与用户交互"；approval API 从服务端 run store 取回受控上下文后调用 Agent continuation，浏览器不直接调 SAP/Gateway。

**commit 守卫归属(D2)**:commit/rollback 在 `JcoCapabilityExecutor` write 分支内部强制,Agent/外部不触发。`BAPI_PR_CREATE`、`BAPI_TRANSACTION_COMMIT`/`ROLLBACK` 必须处于同一个 `JCoContext.begin/end` stateful LUW，所有返回和异常路径均在 `finally` 清理 context。

## 4. `MM.PR.CreateDraft` capability 契约

```yaml
- capabilityId: MM.PR.CreateDraft
  name: Purchase Requisition Create Draft
  description: 创建采购申请 (PR) 草稿, 支持实物直采与间采 (成本中心)
  status: active
  kind: Action
  domain: MM
  businessObject: PurchaseRequisition
  ontologyIri: sapnexus:MM_PR_CreateDraft
  semanticType: sapnexus:PurchaseRequisitionCreateAction
  inputs:
    - name: material        required: true   # 物料号
    - name: plant           required: true   # 工厂
    - name: quantity        required: true   # 数量
    - name: unit            required: true   # 单位
    - name: delivery_date   required: true   # 交货日期
    - name: purchasing_group required: true  # 采购组
    - name: acct_assgn_cat  required: false  # 账号分配类目 (默认空=直采; "K"=间采成本中心)
    - name: cost_center     required: conditional  # acct_assgn_cat="K" 时必填
  outputs:
    - name: prNumber        evidenceRole: primaryFact        # EXPORTS.NUMBER primary; PRITEMEXP.PREQ_NO fallback
    - name: returnMessages  evidenceRole: executionEvidence  # RETURN
  executor:
    type: JCO_RFC
    rfcName: BAPI_PR_CREATE
    inputMapping:
      material      -> PRITEM.MATERIAL
      plant         -> PRITEM.PLANT
      quantity      -> PRITEM.QUANTITY
      unit          -> PRITEM.UNIT
      delivery_date -> PRITEM.DELIV_DATE
      purchasing_group -> PRITEM.PUR_GROUP
      acct_assgn_cat-> PRITEM.ACCTASSCAT  (mock-covered; empty for the direct live slice)
      cost_center   -> deferred BAPI account-assignment structure (not PRITEM)
    outputMapping:
      prNumber      -> EXPORTS.NUMBER
      returnMessages-> RETURN
  governance:
    sideEffect: sap_write
    requiresApproval: true
    approvalPolicy: required
    dataClassification: internal
    auditRequired: true
```

**直采 vs 间采分支**:

| 分支 | acct_assgn_cat | PRITEM 字段 | cost_center |
|---|---|---|---|
| 直采(默认) | 空 | MATERIAL/PLANT/QUANTITY/UNIT/DELIV_DATE/PUR_GROUP | 不填 |
| 间采 | `"K"` | mock-only; live account-assignment structure deferred | 必填（Agent mock validation only） |

### 4.1 Live metadata correction: BAPI technical envelope

The first direct-purchase live smoke on 2026-07-17 reached `BAPI_PR_CREATE` but returned `Please enter items first` and `Enter Document Type`. A read-only JCo repository metadata probe against the sandbox confirmed that this SAP release requires the following technical envelope:

| Structure | Required values for the direct-purchase slice |
|---|---|
| `PRHEADER` | `PR_TYPE="NB"` |
| `PRHEADERX` | `PR_TYPE="X"` |
| `PRITEM` | `PREQ_ITEM="00010"` plus `MATERIAL`, `PLANT`, `QUANTITY`, `UNIT`, `DELIV_DATE`, `PUR_GROUP` |
| `PRITEMX` | `PREQ_ITEM="00010"`, `PREQ_ITEMX="X"`, and `"X"` for every populated item field |

`PrCreateDraftExecutor` is responsible for this BAPI-specific envelope. Registry `inputMapping` remains the controlled business-to-technical mapping and keeps fully-qualified targets such as `PRITEM.MATERIAL`; the executor must verify the `PRITEM.` target and use only the field suffix when writing the JCo table. It must detect parameters through metadata existence rather than `isInitialized`, because an empty input table is valid but not initialized before its first row is appended. ISO `delivery_date` values are converted to a JCo-compatible date value before assignment.

`PR_TYPE="NB"` is an explicit MVP constant scoped to the dedicated `BAPI_PR_CREATE` executor. A future multi-document-type capability should move such defaults into governed binding metadata instead of adding technical document type selection to the Agent prompt surface.

The next authorized live smoke accepted the corrected header/item/X envelope and returned `Enter Purch. Group`. The sandbox purchasing group supplied by the user is `601`. The capability therefore treats `purchasing_group` as a required, approved business input mapped to `PRITEM.PUR_GROUP`; `601` is request data for the live smoke and is never hardcoded in the executor.

The single authorized WRITE after this correction created PR `10137471`, while the structured `data.prNumber` remained empty. A metadata-only JCo probe confirmed that this release exposes `NUMBER` in the BAPI export parameter list. The executor therefore reads `EXPORTS.NUMBER` first and keeps `PRITEMEXP.PREQ_NO` only as a compatibility fallback. On the Agent side, a successful execute transitions the local approval trace from `approved` to `executed`; failures remain `approved`.

The sandbox metadata also shows that `COSTCENTER` is not a `PRITEM` field. Indirect purchase therefore remains mock-covered only and is not part of this live-smoke acceptance. Its account-assignment mapping requires a separate design using the BAPI account-assignment structures.

**必填校验位置**:Agent intent/缺参澄清阶段(与现有 `MM.Inventory` 缺 material/plant 澄清同模式)。`purchasing_group` 对所有 PR 必填；`acct_assgn_cat="K"` 且 `cost_center` 缺 -> 澄清"间采 PR 需提供成本中心"。Gateway validation 仍负责 capability 参数约束；approval 守卫额外校验 authority、状态、TTL、capability 与 stored/actual/request 三方快照一致性，但不承担业务缺参推理。

**间采类型范围**:薄纵切先只支持 `acct_assgn_cat="K"`(成本中心),其他类型(`"F"` 订单等)留后续。

## 5. 错误处理与失败回归矩阵

| 阶段 | 触发条件 | 错误类型 | SAP 触发 | commit |
|---|---|---|---|---|
| approval | 无 ApprovalRecord | `APPROVAL_REQUIRED` | 否 | 否 |
| approval | approval 超 TTL(10min) | `APPROVAL_EXPIRED` | 否 | 否 |
| approval | stored/actual/request 任一快照 hash 不匹配 | `APPROVAL_VERSION_MISMATCH` | 否 | 否 |
| approval | 同 approval 重复或并发 execute，原子 claim 失败 | `APPROVAL_DUPLICATE` | 否 | 否 |
| execute | BAPI_PR_CREATE RETURN E/A | `SAP_BUSINESS_ERROR` | 是 | `rolled_back` / `rollback_failed` |
| commit | BAPI_TRANSACTION_COMMIT RETURN E/A | `SAP_COMMIT_ERROR` | 是 | `rolled_back` / `rollback_failed` |
| 参数 | acct_assgn_cat="K" 缺 cost_center | `CLARIFY`(Agent 澄清) | 否 | 否 |
| 成功 | BAPI_PR_CREATE 成功 + COMMIT 成功 | `NONE` | 是 | commit |

**commit/rollback 时序(参考 STO create)**:

```
BAPI_PR_CREATE execute
  ├─ RETURN 含 E/A? 是 -> BAPI_TRANSACTION_ROLLBACK -> JCoContext.end
  │                       -> ActionResult(SAP_BUSINESS_ERROR, rolled_back) ✗
  └─ 否 -> BAPI_TRANSACTION_COMMIT(WAIT=X)
            ├─ commit RETURN 含 E/A? 是 -> ROLLBACK -> JCoContext.end
            │                             -> ActionResult(SAP_COMMIT_ERROR, rolled_back) ✗
            └─ 否 -> 提取 EXPORTS.NUMBER(PRITEMEXP fallback)
                    -> ActionResult(prNumber, committed) ✓
approval 状态: approved -> executed (写 JSONL trace)
```

commit function 缺失或 commit 调用异常时在同一 JCo context 尝试 rollback；rollback 失败记录 `rollback_failed`。commit RETURN 已确认成功后，PR 号提取异常返回 `NORMALIZATION_ERROR + committed`，因为此时 rollback 已不能撤销已提交业务事实。

**duplicate submit 防护**:Gateway 在 SAP dispatch 前通过并发 map 原子执行 `approved -> executing`；只有 claim 成功的请求可 dispatch，失败者返回 `APPROVAL_DUPLICATE`。一次 dispatch 尝试结束后标记 `executed`，失败尝试同样不可重放。进程重启后索引丢失--MVP 接受此降级(trace 完整记录)。

## 6. 测试策略与验证

**测试分层**:

| 层级 | 范围 | 工具 | 依赖 SAP |
|---|---|---|---|
| 单元测试 | ApprovalGuard 守卫逻辑、commit/rollback 时序、approval 状态机、参数快照 hash、条件必填 | JUnit / pytest | 否(mock) |
| 契约测试 | capability.schema.json Action↔sideEffect 校验、registry contract | validate-registry-contract.py / openspec validate | 否 |
| Eval 回归 | 9 个失败/成功场景 | verify-agent-callplan-evidence.sh | 否(mock) |
| Live smoke | 真实 PR 创建（仅直采 1 个；间采保留 mock 覆盖） | 本地 .env SAP | 是(sandbox) |

**Eval 回归 case 集**:

| case id | 场景 | 断言 |
|---|---|---|
| `pr-create-success-direct` | 直采 PR 创建成功 | PR 号返回, commit=committed |
| `pr-create-success-indirect` | 间采(K+cost_center)成功 | PR 号返回 |
| `pr-create-missing-param` | 缺 material/plant/quantity | Agent 澄清, 不生成 approval |
| `pr-create-indirect-missing-cost-center` | K 缺 cost_center | Agent 澄清 |
| `pr-create-approval-missing` | 无 approval execute | APPROVAL_REQUIRED, 不触发 SAP |
| `pr-create-approval-expired` | approval 超 TTL | APPROVAL_EXPIRED |
| `pr-create-approval-version-mismatch` | 参数被改 | APPROVAL_VERSION_MISMATCH |
| `pr-create-duplicate-submit` | 同 approval 重复 execute | APPROVAL_DUPLICATE |
| `pr-create-sap-business-error` | BAPI RETURN E/A | SAP_BUSINESS_ERROR, rolled_back |

**单元测试关键覆盖**:

- Agent 首次 Action 请求只生成 pending，`gateway.approve_calls == 0` 且 `gateway.execute_calls == 0`。
- Agent continuation 只接受外部传入的 pending record；批准后才注册 Gateway approval 并 execute，拒绝时 execute 次数保持 0。
- Workbench approval API 只能使用服务端 run store 的参数快照；浏览器无法覆盖 material/plant/quantity/purchasing_group/hash；重复决策返回冲突。
- Workbench 状态机覆盖 `awaiting_human_approval -> approved -> completed` 与 `awaiting_human_approval -> rejected`，SSE 正常关闭不产生连接错误。
- `ApprovalGuard`:缺失/过期/非 approved/capability mismatch/stored hash mismatch/actual hash mismatch/request hash mismatch/duplicate 均 fail-closed。
- `ApprovalStore`:并发 claim 只有一个赢家；控制器级并发测试证明两个相同请求只 dispatch 一次。
- `JcoCapabilityExecutor` write 分支:成功 commit、业务错误 rollback、commit 失败 rollback、rollback 失败显式记录(mock JCo destination)。
- WRITE trace 回放:成功、SAP business error、commit error 均包含 resultSummary；成功含 PR 号/committed，失败含 RETURN/rolled_back；全部不含 SAP 凭据或 destination。
- read 路径隔离:`MM.Inventory.GetAvailability` execute 不触发 commit/rollback(回归保护)。
- `approval.py`:状态流转、参数快照 hash 一致/不一致、TTL 过期判定。
- 条件必填:acct_assgn_cat="K" 缺 cost_center 触发澄清。

**验证命令**:

```bash
git status --short
openspec list --json && openspec validate --all --strict
scripts/validate-registry-contract.py registry/capabilities.yaml
cd services/gateway && gradle test
.venv/bin/python -m pytest agent/tests/
scripts/verify-agent-callplan-evidence.sh
```

## 7. 关键约束(硬边界)

- **READ/WRITE 隔离**:`Function` 永不 commit/rollback,`Action` 必经 approval 守卫才 commit。
- **commit/rollback 在 Gateway 内部强制**(JcoCapabilityExecutor write 分支),Agent/外部不触发。
- **WRITE BAPI 与 commit/rollback 必须绑定同一 `JCoContext` stateful LUW**；post-commit 异常不得伪造 rollback。
- **approval 守卫在 Gateway execute 入口、SAP 调用前 fail-closed**。
- **approval 注册仅信任带服务令牌的 Agent；实际参数 hash 由 Gateway 重算；dispatch 前必须原子 claim**。
- **敏感数据守卫不变**:`.env`/SAP 凭据/destination/token 不进 trace/响应/日志;`ActionResult` 与 trace 只记参数摘要、PR 号、commit 状态、错误类型。
- **仅 sandbox/dev client**,禁止生产 client;禁止 release/post/commit-heavy action。

## 8. 关键决策(澄清记录)

| 决策 | 选择 | 理由 |
|---|---|---|
| approval 交互流 | Workbench Console HITL 审批按钮 | 复用现有 HITL 骨架, 贴量产形态 |
| pending continuation 存储 | Workbench 进程级 run store；进程重启后 pending 失效 | 与当前本地 MVP runtime 一致，避免引入数据库 |
| ApprovalRecord 审计 | JSONL 状态事件 + Workbench HITL 派生渲染 | 审计与可读性分离；JSONL 不承担 continuation 状态恢复 |
| approval continuation 输入 | approval endpoint 只收 decision；上下文取服务端 pending record | 浏览器不可伪造 capability/参数/hash |
| Gateway approval authority | 服务令牌 + 严格 record 校验 + canonical hash 重算 | 阻止伪造 approval 与参数替换 |
| duplicate execute | dispatch 前 `approved -> executing` 原子 claim | 关闭 guard/dispatch 之间的 TOCTOU |
| approval replay | `approvalId` 首次注册后不可覆盖 | 防止 executing/executed 被重新激活 |
| approval TTL | 默认 10 分钟(可配置 SAP_NEXUS_APPROVAL_TTL_SECONDS=600) | HITL 即时确认, 降低状态漂移 |
| 字段集 | 单 capability + 可选 acct_assgn_cat/cost_center | 间采是自然分支, 不拆 capability |
| 间采范围 | 先只 acct_assgn_cat="K" | 够验证间采分支 |
| PR 号提取 | `EXPORTS.NUMBER` primary + `PRITEMEXP.PREQ_NO` fallback | 与 sandbox metadata 和成功 live 证据一致 |
| WRITE trace 结果 | 通用字段 + 脱敏 `resultSummary` | HTTP ActionResult 与 trace 共用同一结果真相，READ 保持兼容 |
| commit 归属 | Gateway 内部强制 | 技术事务边界归技术执行层 |
| commit 状态来源 | executor 显式返回 `none/committed/rolled_back/rollback_failed` | trace 只陈述实际事务事实，不按错误类型猜测 |
| JCo 事务上下文 | PR BAPI 与 commit/rollback 共享 `JCoContext.begin/end` | 保证 RFC 落在同一 SAP session/LUW |

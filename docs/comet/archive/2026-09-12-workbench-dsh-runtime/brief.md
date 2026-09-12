# Outcome

Workbench 对话改为只经服务端 in-process DeepSeek Harness 运行；浏览器得到一个
新的 dsh 对话视图（事实/审批卡片），dsh 工具面覆盖 MM/SD/FI 全量只读与 PR 补货
写提议（人工审批），编排与执行权威保持在服务端。本期目标即「仅用 DeepSeek
Harness 作为 Workbench 对话运行时」。

# Scope

在上一变更（facade + 独立 dsh 应用，已归档 2026-09-12）之上，把 **dsh 提升为
Workbench 的唯一对话运行时**：浏览器使用一个**新建的 dsh 对话视图**；Next 服务端
**in-process 挂载 dsh core**（真实 DeepSeek 模型，function-calling 驱动工具选择）；
dsh 可见的语义工具面扩为**全量 READ（MM/SD/FI）+ PR WRITE 人工审批**。编排、语义
解析、计划、治理、审批裁决、SAP 执行仍全部在服务端；dsh 只做 LLM/T-A-O/呈现，
并在 WRITE 时把服务端审批卡片呈现给用户。

**运行时拓扑（用户已决）**：In-process 挂载（非 spawn sidecar）。实现选择（Build
期确定，较 harness-server 子包更标准）：**frontend 直接精确依赖同一组 dsh npm 包**
（0.1.5-rc.1 + 同款 overrides），Next 经 `serverExternalPackages` 把
`@deepseek-ai/*`/cordis 视为外部 ESM；dsh Context 为 `globalThis` HMR 单例
（仓库首个该模式，附 dev HMR 处理）。`harness-dsh/` 保持独立命令行 harness，不被
Next file: 依赖；spine/runner 为 in-process 精简挂载（约百行，注入本应用工具
handler），契约类型以 frontend `semantic-tools/types.ts` 为准。

语义工具集（contractVersion 2，扩 enum，保持 v1 兼容）：

1. `diagnose_material_supply`（已存在）：Inventory + PO（+Material 派生）。
2. `review_customer_exposure`（新）：SalesOrder + AR；输入 customerNumber +
   companyCode（AR 必填，SO 无该槽位——工具执行时 companyCode 仅用于 AR，
   缺失则返回 clarification）。
3. `review_vendor_exposure`（新）：Vendor AP（+PO 可选，同 vendor 槽位）。
4. `propose_replenishment`（新，唯一 WRITE）：material-shortage composition →
   recommendation 产生 PR proposal；facade 返回 `awaiting_approval` +
   审批句柄（approvalId/runId/expiresAt/6 参数/factRefs/hashes）；
   审批决定仍由服务端 `POST /api/agent-runs/[runId]/approval` 裁决，dsh 不裁决。

READ 工具的服务端执行复用现有治理链（createAgentRun → spawn Python resolve +
TS composition）；WRITE 的 proposal 生成复用 TS CompositionCoordinator +
RecommendationDecisionEngine（material-shortage 规则集，需要 quantity/date/group
约束）。SD/FI 为单能力直跑（现有 Python orchestrator 已支持），不需要新 projection。

# Non-goals

- 不做 C-0.5：不把上游 Fact asOf/freshness 加进 SubjectBinding（沿用现有富哈希）。
- 不做 C-2：四原语约束注册表 / normalizer 白名单 / PR 去硬编码（WRITE 仍只 PR）。
- 不做 C-4：PlanDraft 可编辑重算（审批卡片只读参数，拒绝后可重新对话）。
- 不做 C-7 多方案；不做 ApprovalActor/SoD（审批人仍=run 本人，本地 dev）。
- 不替换/删除旧 Workbench `/workbench` 页面与其 Python 直连链；新视图是默认
  对话入口，旧证据工作台保留（本期不做「页面删除/路由强切」之外的迁移）。
- 不做 dsh ApprovalService 作为审批权威（调研结论：turn 内/无 subject 载荷，
  不匹配）；审批 UI 走服务端句柄。
- 不做真实多租户/SSO 身份源（仍 placeholder principal；UI 仅本地 dev 单用户）。
- 不引入根 npm workspaces；不接 OTel；不做 live SAP smoke（沿用 demo/录制数据）。

# Constraints and invariants

- dsh 工具面仍是唯一业务出口：工具 execute 只调**同进程服务端函数**（不经 HTTP
  自调用），不得出现 capabilityId/RFC/binding/凭证；版本精确 pin 0.1.5-rc.1，
  升级=独立评审。架构红线测试扩到 harness-server。
- WRITE 必须有人工审批的可检查接受项：模型不得直接触发 SAP 写；dsh 呈现
  awaiting_approval 卡片；批准/拒绝只走服务端审批路由（token 只在服务端）。
- 契约 JSON Schema 版本化：request/response 升 contractVersion=2，新增工具 enum
  与 approval 句柄块；v1 的 diagnose 行为保持。
- 服务端身份注入复用 injectPrincipal；客户端不得提供身份/审批人。
- READ 不调 BAPI_TRANSACTION_COMMIT/ROLLBACK；审批 TTL 沿用 10 分钟。
- 真实模型 key 只在 Next 服务端 env（`SAP_NEXUS_LLM_*` 或复用 `LLM_*`，
  Shape 期定一个），不进浏览器、不进日志、不进配置文件。

# Decisions

- **D1 范围**：全量 READ（4 个语义工具含 3 READ）+ 1 个 WRITE（PR 审批），
  用户 2026-09-12 确认。
- **D2 承载**：Next 服务端 in-process dsh，经 `harness-server/` 子包 +
  file: 依赖 + serverExternalPackages；globalThis 单例 Context。
- **D3 UI**：新建简洁 dsh 对话视图（聊天 + 工具调用过程 + 事实卡片 +
  审批卡片），不投影成旧 21 事件证据工作台。
- **D4 凭证**：真实 DeepSeek key（function-calling 模型），服务端 env；
  自动化测试仍用 MockAdapter。
- **D5 审批**：WRITE 工具不阻塞 turn；返回 awaiting_approval 句柄，
  UI 按钮调既有审批路由，结果经会话/轮询回流，再由 dsh 向用户陈述 action-receipt。

# Open questions

- LLM env 命名：沿用 Python 的 `LLM_API_KEY/LLM_BASE_URL/LLM_MODEL_NAME`
  还是 dsh 的 `SAP_NEXUS_LLM_*`？倾向服务端统一读 `SAP_NEXUS_LLM_*`，
  缺省回退 `LLM_*`（Build 期确认，不影响契约）。
- customer/vendor 敞口工具是否强制 companyCode 才能跑 SO/PO 部分，还是
  能跑多少跑多少并在 limitations 标注（倾向后者：READ 尽力 + completeness 标注）。
- 审批结果回流 dsh 的形态：自动继续一轮（模型收到 receipt 再陈述）还是
  纯 UI 状态（倾向前者，保持「模型陈述基于事实」）。
- 新视图路由：`/chat`（dsh 默认首页 redirect）还是直接替换 `/`，旧 `/workbench`
  保留位置（倾向 `/` → 新 dsh 视图，`/workbench` 旧证据台保留）。

# Verification expectations

1. READ 四工具（含 SD/FI）在 dsh 对话视图端到端可用，事实卡片字段来自服务端。
2. WRITE：模型提议补货 → 出现审批卡片（6 参数/有效期/fact 引用）→ 点批准 →
   网关 approve+execute（demo/录制）→ action-receipt 回流对话；拒绝路径并列。
3. 自动化：MockAdapter 驱动的 in-process dsh 测试（工具选择→READ 事实；
   WRITE awaiting_approval；审批后 receipt）；跨 harness 一致性 gate 扩到
   SD/FI；架构红线（无 Gateway/RFC/凭证、pin）。
4. frontend verify（tsc+vitest+next build）、pytest 1574、既有 eval 不回归。
5. 真 DeepSeek key 手动 smoke（受控，不进 CI）：至少物料诊断 + 一个 WRITE 审批。

# Acceptance examples

1. 物料诊断（READ）：在 dsh 视图问「DEMOA1 在 1000 工厂够不够用、在途多少」→
   模型选中 diagnose_material_supply → 事实卡片显示库存 12 EA + 在途 → 助手基于
   卡片回答；页面无 harness 切换入口。
2. 客户敞口（READ，SD/FI）：问「客户 1000 的销售订单和未清项」→ 选中
   review_customer_exposure → SO 净值卡片 + AR 金额/到期日卡片分组展示；
   未给公司代码时 AR 区显示缺失提示而不是编数。
3. 供应商敞口（READ，FI）：问「供应商 DEMOV1 的应付未清项，公司 1000」→
   review_vendor_exposure → AP 卡片金额/币种/到期基准日。
4. 补货写提议（WRITE，批准）：提供需求量/目标日期/采购组后问补货 →
   propose_replenishment → 缺货才出审批卡片（6 参数 + 有效期 + 证据）→
   点批准 → 后台 approve+execute → 对话回流 action-receipt PR 号。
5. 补货写提议（WRITE，拒绝/过期）：同一卡片点拒绝 → 无写、对话陈述拒绝；
   超过 10 分钟批准 → 过期错误，无写。
6. 越权红线：请求体塞 rfcName/bindingId → 400 TECHNICAL_OVERRIDE_REJECTED；
   未经 awaiting_approval 不产生任何 execute（自动化断言 writeCount=0）。
7. 自动化：MockAdapter keyless 跑通工具选择→READ 与 WRITE→审批 receipt；
   跨 harness gate 覆盖 MM/SD/FI；npm run verify、pytest、既有 eval 全绿。

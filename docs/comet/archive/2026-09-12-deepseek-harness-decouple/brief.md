# Outcome

基于 Notion《SAP Nexus Agent Harness / DeepSeek Harness v1.0》(page 769238f2) 方案，
参考样板 `/home/shrek/projects/GitLab_Projects/ontology-dsh`，将 sap-nexus-agent 的
Agent 层重构为「可替换 harness 层 + harness 无关的域能力服务」形态，并以 DeepSeek
Harness（npm `@deepseek-ai/dsh`，preview 期）作为第一个新 harness 接入。

方案核心约束（来自 Notion v1.0）：编排权、语义归一、工具语义粒度、审批主体必须在
harness 之外；dsh 只允许包含形状校验/遥测/展示类确定性代码；dsh 接入（方案 R-4）
依赖服务边界先成立，不能先挂 dsh 再补治理。

# Scope

> 范围待第一轮澄清（见 Open questions Q1）后锁定。以下为已核实的基线事实。

## 已核实基线（2026-09-11，本轮实测/全仓审计）

相对 Notion 方案的「代码事实基线 2026-08-19」已发生显著演进，方案多条前提过时：

1. **R-0 前提消失**：agent 测试今日实测 `1574 passed, 1 skipped, 2 xfailed, 0 failed`
   （`.venv/bin/python -m pytest agent/tests`，144s）。方案所称「17 个测试失败」
   在仓库任何文档中无对应记录（可考最近基线是 2026-08-19 的 15 failed，已于
   2026-08-30 SD/FI 归档报告清零至 1574 全过）。
2. **C-1 基本已落地**：`ontology/fact-types.yaml` v3 已为全部 7 个 FactType 建立
   字段级 schema（`fields[]` 带 semanticType/cardinality/optional），并有 tier-①
   valueTypes 声明；方案所指要上提的 `narrative.fieldMapping.itemFields` 已删除且
   被 `test_fact_field_restatement_locks.py` 锁定防复活；依赖边派生产物在
   `runtime/derived-data-dependencies.json`。
3. **TS server-owned runtime 已具规模**（`frontend/src/runtime/`）：plan-executor
   DAG、composition、action-governance（SubjectBinding 已绑 runId/planHash/
   snapshotId/factSetHash/principalId/tenant/role 等，远超方案描述的「只绑 WRITE
   入参」）、principal 注入、projection、release-gate、durable stores；
   对应 `2026-08-02 trusted-principal-model`、`2026-08-04 read-plan-executor`、
   `semantic-plan-authoring-v2`、`2026-08-19/20 declarative-intent-extraction`、
   `2026-08-26 derived-parameter-binding` 均已归档。
4. **Python Agent 为自研框架**（无 LangGraph/function-calling）：7 能力以闭集
   prompt + 声明式 matcher 识别，执行权威在 Java Gateway（capabilityId 白名单、
   inputMapping 独占、READ/WRITE executor 隔离、ApprovalGuard）。
5. **dsh 版本事实**：样板钉 `0.1.0-rc.5`；npm 已发布 `0.1.5-rc.1`（`next`
   标签 rc.2），仍是 0.1 preview（README 明确有 breaking changes）。
6. 已知存量（非本重构引入）：capabilities.yaml 两种 binding 语法并存（15 条
   deprecation 警告基线）；Python 审批记录薄绑定与 TS SubjectBinding 双轨；
   无 frontend/ 之外的产品级 TS/Node 代码。

# Non-goals

- 不改动 Java Gateway 的执行权威模型（capabilityId 唯一入口、白名单 inputMapping、
  READ 不 commit / WRITE 必须审批的硬边界）。
- 不在 dsh 插件中实现任何访问受治理数据或涉权限的业务逻辑。
- 不引入 OWL/图数据库（方案推断几十个能力规模不需要，保留再评估）。
- 不修复与本重构无关的存量问题（双语法、薄审批记录），除非切片证明其构成真实缺口。
- 不做完整 R-1/R-2/R-3/R-4：本期不实现独立部署的 Resolve/Plan Service、不上线
  3 个语义工具（只 1 个）、不做 approval 展示插件、不做 sandbox/live profile、
  不做 C-0 live SAP smoke、不做 C-0.5 subject 联合哈希改造、不做 C-2 规则栈化。
- 不做 workspace 共享包抽取（D2 方案 B）；facade 内部本切片仍可经现有
  adapter/coordinator 路径（含 spawn Python）。
- Notion 其余未决项（principal 签发方/信任链、SAP Principal Propagation、
  IntentDecisionRecord 树状建模、OWL 边界）保持未决，不在本 change 内拍板。

# Acceptance examples

1. 差距矩阵：Notion 十阶段逐项映射当前代码（状态+文件路径+证据命令），含 dsh
   pin 版本矩阵；先于 dsh 接入代码存在。
2. facade：对 dev server 发 `diagnose_material_supply` 语义请求（fixture 模式）
   返回槽位 provenance、能力链、facts+lineage、narrative；含技术覆盖字段的请求
   被 400 `TECHNICAL_OVERRIDE_REJECTED` 拒绝；写目标返回 `OUT_OF_SCOPE_FOR_TOOL`。
3. dsh 应用：`harness-dsh/` 下独立 Node 应用以精确 pin 的 dsh 包族跑通一次
   模型驱动的工具选择→facade 往返；`--dump-config` 导出无密钥；代码中无直连
   Gateway 的调用面。
4. 跨 harness 一致性：同一 golden 子集（inventory / purchase_order /
   derived_parameter / e2e 只读子集）+ 录制 Gateway 响应，dsh 路径与 Python CLI
   路径的槽位值、能力链、fact 投影值 100% 一致，分歧以记录化 diff 失败退出。
5. 回归：agent pytest 全绿；frontend verify 全绿；openspec strict 全绿；
   新增 facade/dsh 组件有对应自动化测试。

# Constraints and invariants

- 四条红线：dsh 对象（`ctx.*`、Cordis seam）不得进入 Plan/Resolve/Guard 签名；
  自由 tool-calling 不得直达 Gateway（bindingId/rfcName/URL/凭证不可由 harness 提供）；
  dsh 契约版本必须 pin；最低模型能力线（accuracy@1 ≥ 90% 等）达标前不接 live。
- WRITE 路径 Human Approval 为可检验接受项；审批 subject 改动必须重算 hash。
- 不提交密钥/令牌/.env；不 force-push main。
- 每个 Native 接受项须有绑定当前 snapshot 的真实证据。

# Decisions

- **D1（2026-09-11，用户确认）范围切片 = A**：本 change = 差距审计 + dsh 最小垂直
  切片。先更新差距矩阵（方案十阶段 vs 现有归档成果），再新建 TS harness 包 pin
  最新 dsh，借现有 TS runtime 契约跑通一条只读语义链
  `diagnose_material_supply`（Inventory.GetAvailability + PurchaseOrder.GetList
  + Material.GetInfo），以切片暴露的真实缺口驱动后续 R-1/R-2 抽取；验收含跨
  harness golden 子集一致率 100%。R-2/R-3/R-4 的完整建设不在本 change 内。
- **D2（2026-09-11，用户确认）集成拓扑 = A**：在现有 Next app 内新增窄语义 HTTP
  契约（GoalSpec/语义工具 in → PlanDraft/Fact out，先只支持 READ 链），包装现有
  `frontend/src/runtime`；另建独立 dsh Node 应用（仓库新顶层目录）跨进程调用。
  本 change 不做 workspace 共享包抽取（方案 B 留待切片证明需要）；dsh 不直连
  Gateway（方案 C 被否决，违反编排权红线）。契约即进程边界，天然隔离 `ctx.*`。

# Open questions

- [x] Q1（2026-09-11 已决）→ D1：选 A。
- [x] Q2（2026-09-11 已决）→ D2：选 A（Next 内窄 HTTP 契约 + 独立 dsh 应用）。

## 实现侧假设（无显式异议即成立，最终确认一并确认）

- A1 新应用位置 `harness-dsh/`（仓库新顶层目录），npm + 独立 lockfile（对齐
  frontend 工具链，不引入 pnpm workspace）。
- A2 版本 pin：`@deepseek-ai/dsh` 精确 `0.1.5-rc.1`（npm latest；next 标签
  rc.2 不采用），插件 SDK 家族按各自 npm latest 精确 pin（app-boot 0.1.0-rc.6、
  headless/base 0.0.1-rc.1），版本矩阵登记进差距矩阵；升级走独立变更评审。
- A3 只做 dev profile；模型端点复用现有 OpenAI-compatible 环境变量。
- A4 跨 harness 一致性只跑离线 fixture（无真实 SAP 连接）；C-0 live smoke 后延。
- A5 语义工具本期仅 `diagnose_material_supply`（READ 三能力闭包）；facade 内部
  过渡实现可复用现有 TS coordinator / Python spawn 路径。

- [x] CONFIRM（2026-09-11 用户显式确认）：Outcome/Scope/Non-goals/Acceptance
  与假设 A1–A5 构成共同理解，进入 Build。
- **D3（2026-09-11，用户确认）假设 A1–A5 全部成立**：harness-dsh/ 新顶层目录、
  npm 独立 lockfile；dsh pin 0.1.5-rc.1 + 插件家族各自 latest 精确 pin；仅 dev
  profile；一致性 gate 仅离线 fixture；语义工具仅 diagnose_material_supply，
  facade 内部过渡可复用现有 coordinator/Python spawn。

# Verification expectations

- Agent：`.venv/bin/python -m pytest agent/tests`
- 契约/spec：`openspec list --json && openspec validate --all --strict`
- 前端/TS runtime：`npm --prefix frontend run verify`
- 跨 harness 一致性：同一 golden 子集在 dsh 与 Python CLI 上结果一致（具体集随切片定）。

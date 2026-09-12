# 差距矩阵：Notion《DeepSeek Harness v1.0》十阶段 vs 当前仓库事实

- 变更：`deepseek-harness-decouple`
- 日期：2026-09-11
- 方案基线：Notion page 769238f2（代码事实基线 2026-08-19）
- 审计基线：main `984f703`，agent 测试当日实测 `1574 passed, 1 skipped, 2 xfailed, 0 failed`
- 状态图例：✅ 已落地 ｜ 🟡 部分存在 ｜ ❌ 缺失

## 1. 阶段总表

| 方案项 | 状态 | 当前事实（关键路径） | 对本切片的含义 |
|---|---|---|---|
| **R-0** 17 测试失败清零 / offline gate | ✅ 前提消失 | 今日 0 失败；文档可考最近基线为 2026-08-19 的 **15** failed（非 17），2026-08-30 SD/FI 归档清零 | 无需动作；offline gate（release L1/L2）已产品化 |
| **R-1** Resolve Service（在线 NL→语义归一） | 🟡 | 声明式 matcher 已在 `registry/*.yaml`；消费在 Python `agent/sap_nexus_agent/extraction/`；TS 侧**零** resolve 代码；仅经 `agent-runtime-adapter.ts:1772` spawn `--resolve-read-turn` 子进程；无 HTTP 端点 | facade 内部过渡期走 Python spawn 契约（A5）；服务化为后续 change |
| **R-2** Plan Service（GoalSpec→PlanGraph） | 🟡 | Authoring 唯一在 Python：`planner/plan_compiler_v2.py:167` + `semantic_planning/`；闭包外 gap 已有（`plan_compiler.py:49` Gap、workbench_output 序列化、TS `composition/handoff.ts:34` 拒图）；TS coordinator **只消费**已编译图；**无外部 GoalSpec 入站契约** | 切片不暴露外部 GoalSpec；facade 以自然语言入、内部复用 Python authoring |
| **R-3** SemanticTool Facade（≤15，复合工具） | ❌ | 全仓无 semantic tool 抽象；**本 change 新建**（spec 已立） | 本切片核心：1 个工具 + 窄 HTTP 契约 |
| **R-4** 接入 DeepSeek Harness | ❌ | 无 harness-dsh/；仅 llm_client 的 OpenAI-compatible 配置曾接 deepseek 模型 | 本切片核心（dev profile / 单工具 / 离线） |
| **C-0** live composition smoke（真实 Gateway） | ❌ | release gate L3 coordinator-e2e 为离线；最新结果 2026-08-26 | 明确 Non-goal；本切片一致性 gate 全程 fixture |
| **C-0.5** subject 加上游 Fact asOf 联合哈希 | 🟡 | TS `SubjectBinding`（`action-governance.ts:104-129`）已绑 planHash/snapshotId/factSetHash/projectionRef/principal/tenant/role/dataScopeHash；**无显式 asOf/freshness 字段**（asOf 只间接含在被哈希 fact 内）；Java `ApprovalGuard` 只做三元组等值、不重算；Python 薄记录 `approval.py` 双轨仍在 orchestrator:396/1557 使用 | Non-goal；记录为 WRITE 路径后续阻塞项 |
| **C-1** FactType 字段级 schema | ✅ | `ontology/fact-types.yaml` v3 全部 7 类型 fields[] 带 semanticType/cardinality/optional + tier-① valueTypes；方案所称 `itemFields` 已删除且有 lock 测试防复活；派生产物 `runtime/derived-data-dependencies.json` | 无需动作 |
| **C-2** 约束入注册表（四原语 + normalizer 白名单） | ❌ | `executor-bindings.yaml` constraints 闭集仅 sideEffect/timeoutMs/maxRetries；无 precondition/authority/mutex/compensation；PR 为全栈写死特例（TS 16 处字面量、Python PR_CREATE_CAPABILITY_ID、rule-set 硬编码）；TS `normalizeParameters` 硬编码 PR 六参数 | Non-goal |
| **C-4** PlanDraft 可编辑 + 重算 subject | ❌ | `planner/plan_draft.py` 33 行 frozen dataclass 无生产使用；TS 无 PlanDraft；审批 API 只收 `{approvalId, decision}`；参数变更走 VERSION_MISMATCH 拒绝而非重编译 | Non-goal |
| **C-5** 基数归约 + freshnessTolerance | 🟡 | cardinality one/many 标签 + `derivation.py:67 DIAGNOSTIC_NEEDS_REDUCTION`（明确不带算子）；**sum/first/requireSingle/max 全缺**；freshness 有 fact/projection `asOf`、`sourceFreshness[]`、规则级 `maxProjectionAgeMs` fail-closed；**无 per-binding freshnessTolerance** | 一致性比对只比已投影标量/fact 字段；归约差异登记 |
| **C-6** TraceSpan → OTel | ❌ | 全栈 JSONL（Java TraceWriter、Python approval trace、TS jsonl stores）；无 OTel 依赖；`NodeLedgerEntry.traceSpan` 恒 null | Non-goal |
| **C-7** 多方案 Recommendation | ❌ | TS recommendation 单 actionProposal、单规则集、强制唯一；Python 无 recommendation 模块 | Non-goal |

## 2. 横切项

| 项 | 状态 | 事实 |
|---|---|---|
| server-owned principal 产品化（R-4 阻塞项） | 🟡 | 生产恒为 `LocalPlaceholderPrincipalInjector`（local-user-0001）；Python 经 env `SAP_NEXUS_PRINCIPAL` JSON 注入；无 header/SSO 身份源；无 ApprovalActor/SoD（审批人必须==run 本人，separationOfDuty 写死 not_applicable）；role 无授权语义；tenant 不到 Gateway 数据过滤。**本切片 READ-only + 本地 dev，placeholder 可接受；第二 harness 上 live 前仍为硬阻塞。** |
| Guard 中间件链 | 🟡 | 五段（technicalOverride 拒→校验→审批→dispatch→redact→trace）在 Java `CapabilityController` 过程式串接，非可插拔中间件；TS 侧 ActionGovernance 类 + 独立 redaction.ts |
| 对话序列级 eval | ✅ | `eval.py:359-627` 支持 turns[] 多轮回放；governed-read-context 夹具；release 22 例中 13 例序列 |
| 跨 harness 一致性矩阵 | ❌ | 本 change 新建（离线、golden 子集） |
| release gate | ✅ | L1 16 deterministic / L2 3 recorded-llm / L3 3 coordinator-e2e（离线），四硬门（visibility leakage 0 / approval bypass 0 / unsupported claim 0 / lineage 100%） |

## 3. 切片直接风险

1. **TS 执行器不解析 factField 派生绑定（G1）**：`plan-executor.ts:405-416 resolveParameters` 跳过所有非 literal（factField/goalConstraint）绑定。diagnose_material_supply 经 ESCALATE→TS coordinator 路径时，跨能力派生槽位在执行期断链（evals 标注 pending/zeros）。facade 设计须明确：组合链执行走 TS coordinator 时该链是否含派生绑定；若含，本切片要么经 Python 侧完整路径（Python 自己调 Gateway），要么把 G1 显式登记为切片限制并选择不触发派生的 golden 子集。Build 期以实测确认。
2. **双轨审批**：本切片 READ-only 不触碰，但 facade 必须拒绝一切 WRITE 目标（OUT_OF_SCOPE_FOR_TOOL）。
3. **capabilities.yaml 双 binding 语法**（15 条 deprecation 基线）：facade 不修；resolve 经 Python 时保持现状。

## 4. dsh 版本 pin 矩阵（2026-09-11 npm 实测）

| 包 | pin 版本 | dist-tag 事实 |
|---|---|---|
| `@deepseek-ai/dsh`（CLI/聚合） | `0.1.5-rc.1` 精确 | `latest=0.1.5-rc.1`，`next=0.1.5-rc.2`（不采用），样板 ontology-dsh 钉 0.1.0-rc.5 |
| `@deepseek-ai/dsh-app-boot` | `0.1.5-rc.1` 精确 | 0.1.5-rc.1 全家桶版本对齐（rc.1 一揽子发布，优于混用 0.1.0-rc.6） |
| `@deepseek-ai/dsh-headless` | `0.1.5-rc.1` 精确 | 同上 |
| `@deepseek-ai/cordis` 等插件族 | 以 0.1.5-rc.1 包的依赖声明为准，lockfile 锁定 | 由 dsh 包传递；显式直连时同样精确 pin |

- 引擎：dsh 样板要求 Node `^22.19.0 || >=24`（pnpm 11；消费方用 npm + 独立 lockfile，安装可行性在 Build 首批验证）。
- 升级策略：preview 期任何 dsh 包升级 = 独立变更评审；package.json 不允许 `^`/`~`/`latest`。
- 库消费 API、工具注册 waterfall、headless/编程式调用、mock LLM 测试方式：见第 5 节（dsh API 调研结论，Build 补充）。

## 5. dsh 库消费 API 事实（依据样板 v0.1.0-rc.5 源码审计；0.1.5 发布版以装包实测为准）

三种嵌入姿态：① `boot()` + cordis.yml Loader（配置即组装）；② in-process
`new Context()` + `ctx.plugin(...)`（测试/eval）；③ 子进程 JSON-RPC SDK。
本切片应用采用 ① 做运行时、② 做自动化测试。

- **启动**：`boot(binName, absoluteConfigPath, patches?, prepare?)` from
  `@deepseek-ai/dsh-app-boot`；配置路径由 `DSH_CORDIS_CONFIG` 或 argv 指定。
- **工具**：`ctx.tools.register(defineTool({name, description, parameters(DSL),
  output:{schema,render}, execute(args, exec)}))` from `@deepseek-ai/dsh-tools`；
  模型入参自动校验；waterfall：`tools/pre-execute`（allow/deny/ask）、
  `tools/execute`、`tools/post-execute`（accept/block）。
- **本切片不用 MCP 自动桥**（`dsh-mcp-client` 的 streamable-http 会把工具改名
  `mcp__<server>__<tool>`）；facade 保持自定义开放 JSON 契约，dsh 侧用
  defineTool + fetch，工具名精确为 `diagnose_material_supply`。
- **LLM**：`dsh-llm-pi-ai` 支持任意 OpenAI-compatible 网关（providers 为 dict，
  key 即 route；rc 期已从数组破坏式收敛）；DeepSeek 官方走 `dsh-llm-deepseek`
  （`DEEPSEEK_API_KEY`/`DEEPSEEK_BASE_URL`）。复用现有 OpenAI-compatible env。
- **headless**：in-process `agents.create({sessionId, agentOptions:{provider,
  model}, setup})` → `agent.followup(createUserMessage(...))` → `whenIdle()`；
  测试用 MockAdapter（script：toolCallResponse/textResponse），经
  `ctx.llm.registerAdapter([route], adapter)` 挂载，无需 API key。
- **配置三层**：bundle `cordis.patch.yml`（包内）→ profile
  （`$DSH_HOME/profiles/<name>/`）→ overlay（`--patch` / `$DSH_HOME/`）；
  `--dump-config` 经 `renderConfigDump` 不 boot 合成打印，`!!js` 不求值。
- **会话**：核心 `dsh-session` 默认纯内存；持久化为可选插件（jsonl/sqlite），
  测试不挂即零文件。
- **审批插件**：`@deepseek-ai/dsh-user-approval`（`ctx.on('approval/request')`
  + pre-execute ask）；本切片 READ-only 不挂载。
- **风险**：rc.5→0.1.5 之间发生过仓库级重命名（无别名）、providers 结构破坏；
  `*-demo` 示例包疑似退出 0.1.5 发布集（next 停在 0.1.1/0.1.2），消费方案以
  `dsh-headless` bundle / 核心包为准，不依赖 demo 包。Build 第一步做
  npm 安装与导出验证。

## 6. 现有规格资产映射

- openspec/specs 21 个：declarative-intent-extraction、semantic-match-decision（R-1 基础）；semantic-planning-foundation / semantic-plan-authoring-v2 / planner-dry-run / read-plan-executor（R-2）；capability-registry-gateway / registry-ontology-contract / gateway-execution-contract / odata-gateway-read（执行权威）；pr-create-action / durable-approval-store（C-0.5/C-2 现状）；trusted-principal-scope（principal 现状）；output-projection（C-5 asOf）；conversational-context / governed-* / durable-run-state / sse-cursor-reconnect 等。
- docs/comet/specs 9 个 canonical：`production-agent-composition-orchestration`（facade 直接复用）、`read-to-write-action-governance`、`recommendation-decision-plan`、`grounded-narrative-orchestration`、`end-to-end-agent-release-gate` 等。
- 本 change 新增两个 spec capability：`semantic-tool-http-facade`、`harness-dsh-integration`。

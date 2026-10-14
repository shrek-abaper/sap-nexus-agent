# SAP Nexus Agent — Governed Ontology Planning MVP

## 0. 文档性质与基线

这是交给 Claude Code 的实施设计输入，不是已实现功能，也不是已验证可投产方案。用户目标是：不同的业务语义问题能在本体约束下动态组织注册能力，获取事实并完成分析，而不是只在固定业务工具之间选择。

- 审查基线：`main`，commit `6444144a57da8ce34b2248eeab42b6bbf26b1d72`。
- 实施前必须重新检查本地 HEAD、dirty files、项目规则、Comet 状态及相关代码。差异影响设计时更新事实基线，不能机械套用旧定位。
- 本次聊天没有修改项目代码、Notion 页面、长期指令或 Skill。
- 此设计允许 Claude Code 在用户自己的项目中按确认后的变更范围实施；不是连接 SAP、付费模型评测、提交代码或部署的授权。
- 第一阶段为单用户 sandbox、只读、离线可验收；real identity、共享生产、租户治理另行立项。不得以现有 placeholder principal 宣称生产安全。

## 1. 目标与非目标

### 目标

让新增业务问法不再必然意味着新增专用业务函数。LLM 只提出类型化语义目标和受控分析步骤；服务端基于可见本体与注册能力，确定性编译出可执行只读计划，取数、分析、返回事实与限制。

成功不是“LLM 输出了 DAG”，而是：

1. 不新增 RFC/BAPI、不新增某问句专用 recipe，也能回答本期合法的新组合问题；
2. 计划中的每个能力、参数来源、事实字段、分析算子、对象连接都有注册来源；
3. 用户问题或语义资产发生变化时，实际计划、结果、证据发生可解释的变化；
4. 缺能力、缺口径、缺事实时停止相关结论，不自行编造；
5. 旧四工具、旧执行路径与 WRITE 门禁不退化。

### 非目标

- 不接入 Neo4j、GraphDB、Semantica、OWL 分类推理机或新 Harness；
- 不增加新 SAP executor family；
- 不实现动态 WRITE、审批豁免、多 WRITE/Saga、自动补偿；
- 不让 LLM 生成 SQL、SPARQL、Python、JS 或任意表达式并执行；
- 不实现任意跨系统联邦、多跳企业全域推理；
- 不将当前库存、订单量、MRP 供应和 ATP 可承诺量混为一谈；
- 不改现有补货业务公式；本期只锁定差异并让新路径不使用未核验公式。

## 2. 已核验的基础与断点

### 可复用

- `semantic_planning/graph.py`：不可变能力—Fact 图与生产者索引；
- `semantic_planning/derivation.py`：从 Fact 字段与能力签名派生数据依赖；必须保留“可派生边不手写回目录”的规则；
- `planner/plan_compiler_v2.py`：PlanGraph v2、参数来源、依赖、READ/Action 分区、歧义生产者诊断；
- `semantic_planning/validation_v2.py`：现有图校验；
- `frontend/src/runtime/plan-executor/`：执行、节点账本、恢复与 Gateway 调用；
- durable store、principal ownership、现有事件与证据机制；
- `constraint_runtime.py` 和生成 SHACL：已有部分参数约束消费者。

### 需要补齐

1. 当前 GoalSpec 主要从已命中的能力汇总其输出，并闭包补齐依赖；缺少“先提出目标事实，再寻找能力”的独立目标入口。
2. 当前 CompositionCoordinator 固定使用物料 Projection 与 RuleSet，不是通用只读分析协调器。
3. Definition、对象链接和业务规则目录没有全部进入 RegistrySnapshot；修改 Definition 的 statement 不改变现有 snapshot 或 SKOS/SHACL 生成哈希。
4. 工具请求会经过 `buildToolQuery()` 拼回文本再解析；新入口必须传递类型化请求，而非重复解析。
5. `ontology/generated/manifest.json` 是文件哈希清单，不是完整 Capability Manifest。新增发布包时避免混淆命名。
6. Python 与 TS 的补货路径有不同取数/计算方式；这是需对账的口径差异，不能把任一路径包装为统一真相。
7. Evidence Grounding 当前主要证明证据 case 可解析；不等于公式或 SAP 口径已获业务验证。

本次定向离线验证：本体/约束/证据/影响分析 47 tests passed，补货 12 tests passed，产物同步和证据引用检查通过。没有跑 SAP live、LLM、Frontend 或全仓库验证。这些结果是旧基线证据，不能替代实施后的回归。

## 3. MVP 场景与能力边界

先限 MM 与现有三个只读能力：

- `MM.Inventory.GetAvailability`
- `MM.PurchaseOrder.GetList`
- `MM.Material.GetInfo`

必须先从当前 Registry 核验 active、Function、sideEffect=none、requiresApproval=false、真实输出和调用 scope；不满足时报告阻塞，不改成猜测。

### 正向问题

- Q1：物料 A 在工厂 1000 当前库存是多少，基本单位是什么？
- Q2：同一物料和工厂的采购订单量，按供应商、按单位分别汇总，和当前库存并列查看。
- Q3：只分析指定供应商的订单量，再与全部订单量对照，解释筛选范围。
- Q4：在同一语义资产与合法算子下，由人工后置提供新的组合问法，形成 holdout；不为 holdout 增加问句级函数。

### 负向问题

- Q5：这些订单下周能到多少？若接口缺未收数量/交期/收货状态，返回语义或事实缺口，不能把订单量当到货量。
- Q6：下周是否一定不断供？若缺目标日前需求与合格供应，不能根据当前库存推断。
- Q7：直接创建采购申请。新动态入口拒绝 WRITE；可提示另走现有受治理写入流程，但不自动跳转执行。

Q2 不要求把库存与订单量相加；两个量的业务含义不同。库存只能按当前执行器已证明的 WB/库存快照口径展示，不叫 ATP。采购订单量按“物料+工厂+供应商+单位”归约，并保留订单/行项目身份。缺单位时禁止数量聚合。

## 4. 目标架构

```text
Chat / CLI
   │ user question
   ▼
GoalInterpreter（LLM；不可信草案；只见可见语义词表）
   │ SemanticGoalDraft：目标事实 + 约束 + 分析 DAG + 假设
   ▼
GoalResolver + SemanticCompiler（确定性；server-owned principal/scope）
   ├─ 可见能力、对象键、Fact schema、Definition、Operator、预算
   ├─ producer 选择、参数依赖闭包、基数、单位、时间校验
   ├─ 缺口/歧义 → CLARIFY / CAPABILITY_GAP / SEMANTIC_GAP
   ▼
ValidatedReadAnalysisPlan
   ├─ 既有 PlanGraph v2：仅注册 READ capability 节点
   └─ 新 AnalysisPlan：注册算子节点，不伪装成 SAP capability
   ▼
DynamicReadCoordinator
   ├─ 既有 PlanExecutor → Gateway → SAP（本期 Fake Gateway 默认）
   ├─ TypedFactNormalizer → 注册字段映射与事实行
   ├─ Deterministic Analysis Runtime → 计算与字段血缘
   └─ Evidence-grounded renderer → 事实/规则结果/推断/限制
```

LLM 不生成可执行 PlanGraph，也不传 principal、visibility、技术绑定或版本权威。SemanticGoalDraft 中的 snapshotId 即使回显也不可信；服务端绑定本次实际发布包与 scope。

规划只看语义目录与问题，本期不需要向远端模型发送完整 SAP 明细。叙述默认确定性模板；未来 LLM 叙述若需要私有数据，先约定最小字段、外发政策与脱敏。

## 5. 新契约（建议命名，实施时按现有规范确认）

所有新契约做 versioned schema，不给旧 GoalSpec/PlanGraph 静默加字段。先复用旧版本，不能表达的语义通过新封装契约承载。

### 5.1 SemanticGoalDraft v1

字段：

- `schemaVersion`
- `requestedFacts`：注册 FactType、输出字段与对象 selector
- `constraints`：类型化用户值、来源（explicitUser/confirmedContext）、未解析值
- `analysisNodes`：operatorId、输入引用、受控参数；可组成无环分析 DAG
- `requestedConclusions`：用户想知道什么、必要证据要求
- `assumptions`：仅解释性假设，不授权执行或替代缺参

草案不能包含 RFC、bindingId、URL、凭据、SQL、任意路径/代码、执行授权或动态文件导入。JSON Schema 严格 additionalProperties=false，再做深度技术键扫描。拒绝非有限数、过长输入、异常嵌套与超限节点。

分析引用必须指向 registry 中允许的 Fact/字段或已声明的上游分析节点；不得直接引用任意 JSONPath。

### 5.2 SemanticRelease v1

不全局替换现有 registrySnapshotId。第一期采用显式双版本绑定：

- `registrySnapshotId`：现有基础 Registry 快照，保持旧路径兼容；
- `semanticSnapshotId`：新路径实际消费的全部语义资产、执行映射与算子实现版本的内容哈希；
- `compilerVersion`、`operatorImplementationVersion`、各源文件 digest；
- `semantic package` 中同时带两者，编译与执行核对其关联。

新增资产或依赖变化必须改变 semanticSnapshotId。产物可重放、排序确定、无时间戳漂移；不依赖从 LLM 返回的哈希。运行中固定同一发布包，更新不混入在途 Run。缓存按语义版本与 scope 键隔离。

### 5.3 ReadAnalysisPlan v1

- server-generated planId、semanticSnapshotId、registrySnapshotId、principal/scope binding；
- `readPlan`：合法 PlanGraph v2，actionPartition=[]；
- `analysisPlan`：独立 DAG、输入输出 schema、DefinitionRef、operatorRef；
- `limits`、事实需求、freshness 要求、结论覆盖与未覆盖项；
- Plan 作为 server-owned 记录保存。客户端不可上传“已验证”标志或自由改图后执行。

Plan 的 READ_ONLY 模式由服务端策略决定，不能通过模型把旧 PLAN_ONLY 变成执行授权。

### 5.4 TypedFact 与 AnalysisResult

TypedFact：

- objectType、objectKey（含组织/系统范围）、row identity；
- factTypeRef、field values、field semanticType；
- unit/currency、业务时间/采集时间分别表达；
- definitionRef（确有定义才填，不造占位口径）；
- run/node/execution/raw field evidence references、完整性与限制。

AnalysisResult：

- 输出类型、值、单位、对象/分组键、时间范围；
- 具体 operator/definition 版本、输入 fact/row/field refs；
- 排除行与原因、partial 状态；
- status：complete / partial / clarification / capability_gap / semantic_gap / rejected / failed。

归约必须维护行记录，不能把多列表字段 flatten 成彼此失联的列后相乘或相加。重复行身份冲突明确报告；不得未经定义去重或重复计数。

## 6. 编译与执行规则

### 6.1 先求事实，再选能力

1. 校验草案；
2. 解析 desired FactType/field；
3. 在当前用户可见、允许执行的 active READ 能力集合中寻找 producer；
4. 零 producer → CAPABILITY_GAP；多 producer → 只接受已发布优先策略或用户澄清，不按列表第一项选择；
5. 复用 derivation 做 required input 依赖闭包；
6. 只因字段名或 semanticType 相同，不足以证明同一对象：必须绑定对象键与 scope；
7. unknown required value → 澄清，不能“用默认工厂”；
8. 编译 read PlanGraph、分析 DAG 并校验；
9. 固定发布包与 plan hash，再执行。

可见性过滤必须发生在模型候选展示之前，并在编译、执行重新核验。Graph 可达性不等于授权，也不等于业务结论可证明。

### 6.2 第一批分析算子

建议只实现：

- `select_fields`：投影注册字段；
- `filter_eq`：注册字段与类型化 literal 过滤；
- `group_sum`：Decimal 数量按合法对象维度及单位分组，保留行血缘；
- `compare`：只比较口径兼容、单位一致、时点符合策略的同类量。

“并列展示”用输出结构表达，不强制做数值比较。缺确认语义时只展示，不比较。暂不加任意 JOIN、日期预测、情景供需公式或开放算子插件。

如果现有字段不能支持 sum，则返回缺口，不在模型端计算。生产者多选、列表归约、对象连接与单位转换均不能靠 prompt 猜。

### 6.3 计算实现位置

沿用 Python 作为目标解释/语义编译与确定性分析的实现层；TS 保留 trusted orchestration 与既有 PlanExecutor。

- Python 承载 Analysis Runtime，Decimal 与统一算法权威；
- TS 将经过最小化的结构化 Fact 输入交给固定 Python 子进程入口，接收 schema 校验后的 AnalysisResult；
- 不通过 shell 拼命令，不执行模型代码，不写带敏感值的命令行参数；使用受控 stdin/stdout 协议并脱敏日志；
- 只有 TS 的既有 GatewayClient 执行 SAP；Analysis Runtime 没有凭据、网络、Gateway；
- 复用 agent-runtime-adapter 的进程、超时、错误处理模式，必要时抽出最小公用适配器，不构造第二个长期服务；
- 若设计阶段发现此方案不能满足隔离或性能，再提出替代 ADR；不能同时写 Python/TS 两套计算以“保持一致”。

### 6.4 有界动态规划

建议门槛，非实测能力：

- 最大 6 个 READ 节点、6 个分析节点、依赖深度 4；
- 规划最多 2 次模型调用（初稿 + 一次只修复结构错误）；
- 参数缺失/业务歧义直接澄清，不反复让模型修复；
- 计划整体只读执行超时建议 90 秒，每节点不超过整体预算；
- 事实行数/响应字节上限需设计阶段结合既有返回契约设定：超限明确截断并标 incomplete；聚合不得把截断值当完整结果；
- 不支持无界 replanning、循环、自我修改本体、临时注册能力。

所有值为可版本化 server config。实际限额与 cost budget 在使用付费模型前由用户确认；默认 fake interpreter，不自动跑付费模型。

## 7. 与旧系统的兼容与接入

1. 旧四个 semantic tools 继续可用，默认行为不变。
2. 新增独立的只读业务入口（建议 `analyze_business_question`），及 versioned request/response schema；名称为设计建议，不是已注册工具。
3. 不把新能力强塞进现有 `SemanticToolName` v2；使用新契约或明确版本化扩展，兼容测试证明旧调用者不受影响。
4. typed slots、principal 与语义包直接进入新 planner，不走 buildToolQuery 再解析。
5. 新建 DynamicReadCoordinator，复用 PlanExecutor，不调用现有强制物料 recommendation 的 CompositionCoordinator。
6. Phase 2 默认关闭 feature flag，先 Python contract/CLI 与 FakeGateway 集成；Phase 3 再接 DSH Chat/独立 CLI。
7. 新入口 WRITE 拒绝发生在调用 Gateway 前；也不能通过“先生成提议再自动调用旧工具”绕过去。
8. 高优先级安全问题若暴露，应报告阻塞并单列修复范围，不借本次架构变更悄悄改 WRITE 主干。

## 8. 分阶段实施

本次涉及结构化 schema 演进，依据基线 AGENTS.md，建议 `/comet-classic`，但启动时必须复核本地规则。项目已有 active change 与目标文件冲突时停止。不能同时用 Native/Classic 改同一批文件，也不手改工作流状态。

### C0：事实基线与设计确认（不写业务代码）

产物：

- 重新核验的 baseline：HEAD、dirty files、active changes、目标三个能力真实字段、现有 scope 机制；
- 路径/调用链图；
- spec delta、模块范围、契约草案、migration/rollback 策略；
- 当前库存/订单量命名与证据边界；现有 Python/TS 差异报告；
- 分清本期肯定能答与只能返回 gap 的问题。

Gate：用户确认本期范围、关键 ADR 与 Build；仓库规范若有其他决策节点，遵循工作流。不因项目“默认执行”越过用户本次明确的设计确认要求。

### C1：语义资产与发布包

建议新增/扩展：

- 注册对象键与范围（MM 最小对象集合）；
- 首批允许分析的 Fact field mapping；
- analysis operator catalog；
- Definition/适用口径声明（不定义未经核验的供需公式）；
- SemanticRelease 构建、校验、缓存、快照关联；
- schema/引用/产物确定性测试。

Gate：

- 消费的任一语义源变更能使 semanticSnapshotId 改变；
- 同输入同产物；
- 旧 snapshot 与工具路径兼容；
- 不能为了让 relation 文件非空而回写派生关系；
- 引用存在与业务有效性使用不同验证状态。

### C2：动态 PLAN_ONLY + 只读离线执行

- fake GoalInterpreter + model adapter interface；
- SemanticGoalDraft validator；
- GoalResolver 与编译器，复用现有生产者索引/依赖派生；
- 独立 AnalysisPlan 与 Validator；
- TypedFactNormalizer + 四个算子；
- DynamicReadCoordinator + FakeGateway；
- CLI/测试入口输出完整执行证据。

Gate：正向问法产生不同合法 read/analysis 计划；负向请求在 Gateway 前或结论生成前按错误类型阻断；不新增问句专用 recipe；holdout 在无业务代码变更下通过。

### C3：Sandbox Chat 接入与用户验证

- 接入独立 analyze tool、类型化 request/response；
- 展示“读取哪些事实、分析如何做、哪些结论缺证据”，不展示内部 chain-of-thought；
- principal ownership、限制、超时、取消、模型错误与计划失效处理；
- 旧四工具回归；
- 用户批准后，先最小授权 MM scope 的只读 live smoke，再按明确预算进行小样本 LLM 测试。

Gate：离线与 Chat 执行结果语义一致；live mismatch 有记录；没有实测的项明确 not run；不自动开启共享或生产部署。

不在这轮执行 Pilot→Scale；若 sandbox 通过，再另立跨域分析、共享身份、WRITE governance workstream。

## 9. 文件级实施地图

以下为候选位置，不是要求全部修改。Claude Code 应复核当前组织结构并在设计阶段给出最小 diff。

### 新增候选

- `schemas/semantic-goal-draft.schema.json`
- `schemas/semantic-release.schema.json`
- `schemas/read-analysis-plan.schema.json`
- `schemas/analysis-result.schema.json`
- `ontology/object-types.yaml`
- `ontology/analysis-operators.yaml`
- `agent/sap_nexus_agent/ontology_planning/`
  - `contracts.py`, `release.py`, `goal_interpreter.py`
  - `resolver.py`, `compiler.py`, `validation.py`
  - `fact_normalizer.py`, `analysis_runtime.py`, `cli.py`
- `frontend/src/runtime/dynamic-analysis/`
  - `coordinator.ts`, `python-analysis-adapter.ts`, `types.ts`
- `evals/ontology_read_analysis_cases.json`

### 可能扩展

- `ontology/fact-types.yaml`：合法字段与行粒度，采用兼容性策略；
- `ontology/definitions.yaml`：新路径实际消费的 Definition，不重写 proposed 为 active；
- `semantic_planning/graph.py`、`contracts.py`：优先 wrapper，必要时才扩展旧对象；
- `planner/plan_compiler_v2.py`：抽取可复用编译 primitives，旧入口保留；
- `frontend/src/server/dsh/registry.ts`：C3 注册新工具；
- `frontend/src/runtime/agent-runtime-adapter.ts`：最小复用进程模式。

### 不应直接重写

- 既有 Java Gateway 与 bindings；
- 既有 approval/action governance；
- 当前 CompositionCoordinator；
- 旧 SemanticTool 契约和 Harness 主循环；
- AGENTS.md、CLAUDE.md、长期指令与 Skills；
- 历史 runbooks 或归档 change。

## 10. 测试、预算与验收证据

### 离线 case 集

建议首批 24 个公开合成/脱敏开发 case + 6 个用户后置 holdout。数量是建议，不是已有数据或通过率。

开发 case 覆盖：

- 库存 + 物料信息；库存 + 订单并列；供应商过滤 + 分组；
- 同能力不同过滤/算子顺序；输入问法意译；
- 缺工厂、未知物料、缺字段、生产者歧义；
- 无权限 producer 不进候选，不通过澄清或自动依赖绕回；
- 欠缺到货/需求语义时，订单量不变成确认供应/断供预测；
- 单位不一致、单位缺失、重复行身份、非有限数、超限截断；
- 语义版本变化、在途 Run 固定版本、旧计划拒绝新包；
- 循环/过深 DAG、未知算子、技术键注入；
- WRITE 经嵌套依赖或分析伪装被拒绝，零 WRITE Gateway 调用；
- 部分取数失败，仅独立输出可继续，依赖失败的结论标缺口。

不以节点顺序/完全相同 DAG 判断正确；对照“合法依赖、必要证据、数值/单位/口径、禁止调用和限制”。等价计划可以不同。

### 建议验收门槛

- 离线确定性 hard gate：非法/越权/WRITE 计划零放行；证据引用完整；合法聚合逐行可对账；
- 本期合法样例与 holdout 的预期输出全部满足人工 golden assertions；
- 至少有能力子集/分析 DAG 实质不同的组合，而非同一个固定模板只换参数；
- 删除必要 producer 会出现 capability gap；修改 operator/Definition 会改变分析行为和语义版本；
- 不靠改 prompt 或增加针对 case 的分支来掩盖测试失败；
- 新路径失败关闭时，旧路径保持既有行为。

### Eval 四件套

1. 质量：目标事实解析、合法计划、口径正确、结论证据充分、拒绝/澄清正确；
2. 成本与延迟：记录 planning calls/tokens、规划/编译/读取/分析耗时、候选大小；实测前未知，不给 SLA；
3. bad cases：上述开发 case，加现场失败；每个有归因到词表/能力/字段/算子/定义/治理；
4. 回归集：公开合成/脱敏 fixture + 用户认可 golden + holdout；真实 trace 不提交仓库。

如使用 LLM-as-judge，只用于辅助评价叙述；先与人工样例校准，不作为数值、权限和上线安全的唯一验收。

### 运行规则

- PLAN_ONLY、FakeGateway、fake interpreter 默认，不调用 SAP 或付费 LLM。
- LLM/Live 测试前确认模型、数据范围、样本量、费用和时间上限，秘密由批准凭据机制注入，不进入聊天/日志/命令行/代码文件。
- 本地 CLI 调远端模型仍是数据外发，必须按组织政策处理。
- 不开 subagent，除非用户另外明确授权。

### 相关验证命令

按本地依赖与项目实际命令复核，不自动安装重型平台：

```bash
git status --short
openspec list --json
openspec validate --all --strict
PYTHONPATH=agent .venv/bin/python scripts/build-ontology-bundle.py --check
PYTHONPATH=agent .venv/bin/python scripts/validate-evidence-grounding.py
PYTHONPATH=agent .venv/bin/python -m pytest agent/tests/test_ontology_codegen.py agent/tests/test_constraint_runtime.py agent/tests/test_evidence_grounding.py agent/tests/test_impact_analysis.py
PYTHONPATH=agent scripts/verify-agent-callplan-evidence.sh
```

另运行本期新增 tests 与直接受影响的旧 compiler/derivation/snapshot tests；C3 触及 Frontend 时运行 `npm --prefix frontend run verify` 及适用 release gates。所有结果必须实际运行后记录；脚本不可用写 blocked，不把历史通过当本次通过。

## 11. 可复制到 Claude Code 的启动任务

```text
请读取我提供的 nexus-ontology-planning-handoff.md，实施目标是本体约束的动态只读分析 MVP，不是完善固定物料工具，也不是全量自治 Agent。

先做 C0：读取当前 AGENTS.md/CLAUDE.md、.comet/config.yaml、相关 wiki/current specs；检查 HEAD、git status、active changes，并对照本设计的基线 6444144。不要自动读取归档文档。

这是结构化 schema/规划契约变更。按当前仓库规则复核工作流，基线规则建议 /comet-classic。如工具/命令不支持，请报告，不手写工作流状态。已有活动变更冲突时停止，不并行 Native/Classic。

核心范围已确定：
1. MM 三个现有只读能力，先核验 active/read/scope/字段。
2. SemanticGoalDraft → 本体目标解析 → 确定性 read PlanGraph v2 + 独立 AnalysisPlan。
3. 复用 PlanExecutor/Gateway/durable/principal；新只读 Coordinator 不进入固定补货 Recommendation。
4. 语义发布包显式绑定旧 registrySnapshotId 与新 semanticSnapshotId，保持旧路径兼容。
5. 新 typed analyze 入口不把 slots 拼回自然语言再解析。
6. 首批分析只有注册 select_fields/filter_eq/group_sum/compare；计算由单一确定性实现承载。
7. 库存与采购订单量并列/分组分析，不把订单量当到货量，不做未经核验的断供/ATP 推断。
8. WRITE、任意 SQL/代码、动态注册、无界 replanning 全部禁止；旧四工具保持兼容。

先交付 spec delta、关键 ADR、模块/文件范围、契约、测试矩阵与 rollout/rollback。等我确认设计后再进入 C1/C2 Build；C3、SAP live、付费模型 eval 另等授权。

不得换分支、提交、push、部署；不修改长期指令/Skill/AGENTS/CLAUDE；不读取或输出真实秘密；不使用 subagent。

最终交付 diff 摘要、实际测试证据、两个不同动态组合样例、一个 semantic gap 样例、holdout 结果，以及明确未验证项。不要把新增 YAML 文件或 LLM 画 DAG 当作本体驱动已达成。
```

## 12. 源码依据

以下链接对应审查 commit；实施时以本地新基线为准。

- [Project rules](https://github.com/shrek-abaper/sap-nexus-agent/blob/6444144/AGENTS.md)
- [GoalSpec](https://github.com/shrek-abaper/sap-nexus-agent/blob/6444144/agent/sap_nexus_agent/planner/goal_spec.py)
- [PlanCompiler v2](https://github.com/shrek-abaper/sap-nexus-agent/blob/6444144/agent/sap_nexus_agent/planner/plan_compiler_v2.py)
- [Derived dependencies](https://github.com/shrek-abaper/sap-nexus-agent/blob/6444144/agent/sap_nexus_agent/semantic_planning/derivation.py)
- [Semantic graph](https://github.com/shrek-abaper/sap-nexus-agent/blob/6444144/agent/sap_nexus_agent/semantic_planning/graph.py)
- [Snapshot sources](https://github.com/shrek-abaper/sap-nexus-agent/blob/6444144/agent/sap_nexus_agent/semantic_planning/contracts.py)
- [Composition coordinator](https://github.com/shrek-abaper/sap-nexus-agent/blob/6444144/frontend/src/runtime/composition/coordinator.ts)
- [PlanExecutor types](https://github.com/shrek-abaper/sap-nexus-agent/blob/6444144/frontend/src/runtime/plan-executor/types.ts)
- [Tool request conversion](https://github.com/shrek-abaper/sap-nexus-agent/blob/6444144/frontend/src/runtime/semantic-tools/validate.ts)
- [Ontology codegen](https://github.com/shrek-abaper/sap-nexus-agent/blob/6444144/agent/sap_nexus_agent/ontology_codegen.py)
- [Fact types](https://github.com/shrek-abaper/sap-nexus-agent/blob/6444144/ontology/fact-types.yaml)
- [Implementation roadmap](https://github.com/shrek-abaper/sap-nexus-agent/blob/6444144/docs/wiki/sap-nexus-agent-implementation-roadmap.md)
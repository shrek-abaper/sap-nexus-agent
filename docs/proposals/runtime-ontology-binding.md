# 运行时本体绑定方案（Proposal）

- **状态**: Pending（架构演进提案，未启动）
- **创建日期**: 2026-09-24
- **目标**: 让"本体驱动"从设计语言变为运行时事实——运行时由本体解析能力、参数、前置条件与执行权限；同时不破坏 Registry 治理与确定性门禁
- **决策结论**: 若立项，采用**轻量语义解析层**（方案 A），分四阶段、shadow 起步；不采用全量 Palantir 式运行时推理（方案 B）

---

## 1. 背景与差距

当前运行时事实（见 `docs/semantic-model.md`）：

- 能力召回、选择、参数校验、执行映射、审批全部由 **Registry YAML + 确定性代码**驱动；
- OWL/Turtle（类、属性、IOPE、ODRL、规则目录）是**离线语义镜像**，运行时不加载；
- 因此准确表述是"本体建模驱动设计、注册中心驱动执行"，而非运行时本体驱动。

差距不在词汇（已齐备），而在**运行时没有本体的消费者**。

## 2. 什么叫"运行时本体绑定"

定义：Agent 在运行时加载版本化本体，并以本体查询结果作为以下决策的**解析依据**：

| 决策 | 本体回答的问题 |
|---|---|
| 参数校验 | 该值是否满足语义类型的数据类型约束（模式/长度/基数） |
| 前置条件 | 当前上下文是否满足能力的 Precondition（含条件前置） |
| 执行权限 | execute 权限是否成立——人审 duty 是否被满足 |
| 能力召回 | 用户表达命中哪个能力概念（经 SKOS 标签/别名） |

**关键边界（推荐架构的红线）**：

- 本体只**解析（resolve）**，确定性代码才**执行（enforce）**——控制流、权限、副作用永不交给本体或模型；
- 不引入描述逻辑推理机做分类推断；只用 RDF/SKOS/OWL-Lite 级别的**确定性查询**；
- WRITE 人审仍以 ApprovalRecord 为唯一凭证，本体 duty 是其语义表达，不是替代。

## 3. 方案对比

| 维度 | A. 轻量语义解析层（推荐） | B. 全量本体运行时（Palantir 式） |
|---|---|---|
| 本体角色 | 查询解析：校验/前置/权限/召回 | 实例化事实 + 推理 + 动作选择 |
| 实例数据 | 不进图，引用 Registry/事实 JSON | 事实落图（triplestore） |
| 推理 | RDF/SKOS 确定性查询，零分类推理 | OWL 推理 / SPARQL / 可能跨域推导 |
| 新增基础设施 | 进程内 Turtle 存储（rdflib），无独立服务 | 图数据库、联邦查询、本体运维 |
| 与现有链路关系 | 叠加解析层，validators/Gateway 不变 | 重构规划与执行主干 |
| 风险/成本 | 低，可分阶段验证 | 高，"本体博物馆"与性能/运维风险 |
| 何时选 | 当前阶段（7 能力、单域为主） | 多域联邦、需要跨本体推理且有真实场景时 |

## 4. 推荐架构（方案 A）

```text
作者层    registry/*.yaml + ontology/fact-types.yaml   （唯一人工事实源，现状不动）
              │  构建时代码生成（codegen，确定性）
              ▼
本体包    canonical Turtle Bundle（含 SKOS 标签/数据类型/IOPE/ODRL）
              │  按 registrySnapshotId 哈希版本化
              ▼
运行时    OntologyBinding 服务（进程内，rdflib，按快照缓存）
              │  确定性查询 API
              ├─ validateValue(semanticType, value)
              ├─ evaluatePreconditions(capabilityId, slots)
              ├─ checkPermission(capabilityId, context) → duty 状态
              └─ recallCapabilities(text) → 候选（SKOS 标签匹配）
              ▼
消费方    capability selector / plan compiler / gateway validation / approval gate
              │
兜底      召回不确定 → LLM / 未来 Jev；执行与权限仍由确定性代码强制
```

### 4.1 单一事实源：YAML 作者源 + 代码生成，杜绝漂移

- 人工只编辑 YAML（既有 validator、eval、审批生态全部保留）；
- 新增构建时代码生成器：YAML → canonical Turtle Bundle；复用并扩展现有的
  `agent/sap_nexus_agent/fact_turtle.py`（fact→Turtle）思路，覆盖：
  SKOS 概念（能力 + prefLabel/altLabel 取自 aliases/examples）、
  数据类型约束、IOPE、ODRL；
- 现有手工维护的 OWL 文件逐步由生成产物替代（或在过渡期交叉校验一致）；
- Bundle 绑定 `registrySnapshotId`，内容哈希入产物；快照不一致则拒绝加载。

> 不选择"Turtle 变为作者源、YAML 反向生成"：那会推翻现有 validator 与全部治理资产，收益不抵成本。

### 4.2 OntologyBinding 查询 API（新增模块）

`agent/sap_nexus_agent/ontology_runtime/`：

- `loader.py`：按快照加载/缓存 Turtle Bundle（进程内，启动或快照变更时加载一次）；
- `binding.py`：上述四类确定性查询；全部为只读纯函数式接口，无网络、无模型调用；
- 导入集合沿用 `derivation.py` 的做法，锁定最小 allowlist 并由测试约束。

依赖（自建路线）：新增 `rdflib>=7`（agent pyproject.toml）；纯 Python、进程内，不引入独立图服务。
OntologyBinding 也可由开源平台（Semantica 首选 / EvoOntology 备选）承载，见 §10。

### 4.3 消费方改造（最小侵入）

| 消费方 | 改造 |
|---|---|
| 参数校验 | 数据类型约束的解析改由 binding 查询；现有入参校验代码仍做最终强制 |
| 前置条件 | required/requiredWhen 的求值经 `evaluatePreconditions`；结果不通过即拦截 |
| 审批门禁 | checkPermission 解析人审 duty（ApprovalRecord 状态 + 参数快照哈希 + 未过期）；approval store 仍是执行凭证 |
| 能力召回 | 新增 SKOS 标签召回通道，置于确定性关键词之后、LLM 之前；低置信仍走 LLM/Jev 兜底 |

## 5. 分阶段落地

| 阶段 | 内容 | 出口判据 |
|---|---|---|
| **Phase 0 Shadow** | 代码生成器 + OntologyBinding 上线但**只记录不决策**；对比本体结论与现行路径 | 全量 eval 上结论一致率达标；产物哈希稳定可复现 |
| **Phase 1 参数/前置绑定** | 参数校验与前置条件求值切到本体解析 | eval 全绿；不一致零放行 |
| **Phase 2 权限绑定** | 审批门禁经 ODRL duty 解析（执行仍代码强制） | WRITE 用例（含过期/版本不符/重复提交）行为不变 |
| **Phase 3 SKOS 召回** | 标签召回插入选择链路；LLM 兜底保留 | 召回准确率不低于现状；意译切片覆盖率提升 |
| Phase 4（可选，不在本提案） | 实例事实入图、跨域推理 | 需另立项，即方案 B 的触发条件 |

## 6. 验证计划

- **Shadow 指标**：本体结论 vs 现行路径的一致率（参数/前置/权限应近 100%，召回给出 Top-1/Top-2 覆盖率）；
- 现有资产不变：`scripts/verify-agent-callplan-evidence.sh`、全量 agent 测试、openspec 校验持续通过；
- 新增测试：codegen 确定性（同输入同哈希）、四类查询 API 的正反控制、快照不匹配拒绝加载；
- 性能：本体按快照缓存，单次查询延迟纳入指标，不得在每请求重新解析；
- 冷启动：SKOS 召回先 shadow 只记录，达到准确率门槛再切换（与 Jev 提案同一校准纪律）。

## 7. 风险与对策

| 风险 | 对策 |
|---|---|
| YAML 与生成 Turtle 漂移 | 构建时代码生成 + 哈希绑定，不允许手工编辑产物 |
| 本体解析被误当成强制来源 | 架构红线：resolve 与 enforce 分离，由测试锁定 |
| 标签召回中文表现不足 | SKOS altLabel 承载别名；LLM/Jev 兜底，shadow 校准后再切 |
| 本体内容注入（经标签的 prompt 注入） | 本体是受控治理产物；召回结果以结构化标识传递，不直接拼入 prompt |
| rdflib 新依赖/性能 | 进程内、快照级缓存；查询范围限制为 RDF/SKOS |
| 范围蔓延成方案 B | Phase 4 必须另行立项；本提案不含实例图与推理机 |

## 8. Comet 路由提示

按项目规则本变更属 **HEAVY**（架构演进、跨 ≥2 模块、>5 文件），不应直接编辑；立项时通过 Comet 开 change，工作流在创建时按当时规则决定。本提案仅为设计输入，不替代其 Shape/Design 决策。

## 9. 待决问题（进入设计阶段时回答）

1. 生成 Turtle 与现有手工 OWL 的过渡策略：一次性替换还是先交叉校验？
2. SKOS 召回与未来 Jev Choice 的先后顺序（建议：关键词 → SKOS → Jev → LLM，待 Jev eval 结论）；
3. rdflib 版本与是否允许 SPARQL（建议仅内部查询 API，不开放任意 SPARQL）；
4. Phase 1/2 是否需要特性开关按域灰度。

## 10. 开源运行时候选评估

调研了两个可作为本体运行时的开源项目；结论：**Semantica 为首选评估对象，EvoOntology 为轻量备选；均以旁路、单向投影方式 spike，不直接采用为受治理的执行源。**

### 10.1 候选概览

| 项目 | 定位 | 成熟度 | License |
|---|---|---|---|
| **semantica-agi/semantica** | 图原生上下文与问责 AI 基础设施：Context Graph、SHACL/OWL/SKOS、正向链/Rete/Datalog/SPARQL、PROV-O | 13.4k stars，2025-06 至今，PyPI 发包 | MIT |
| **ruc-datalab/EvoOntology** | 数据 Agent 的自进化本体层，经 MCP 暴露 `browse_semantics`/`resolve_semantics`，门控版本化 | 372 stars，2026-09 发布（研究代码） | MIT |
| sematic-ai/sematic（已排除） | ML 流水线开发平台（类 Metaflow），非本体语义层 | — | Apache-2.0 |

### 10.2 与本方案能力的对照

| OntologyBinding 需求 | Semantica | EvoOntology |
|---|---|---|
| 图存储 | 嵌入式 Oxigraph（RDF）/ 多家 LPG 可换 | 自有 Content Layer（Terms/Mappings/Constraints/Evidence） |
| 作者本体载入 | **OWL/SHACL/SKOS 导入**，治理契合最好 | 以发现式自动构建为主，需反向约束 |
| 参数校验 | SHACL 约束验证 | Constraints 节点，需自定义映射 |
| 前置/规则解析 | 正向链/Rete/Datalog/SPARQL | browse/resolve 确定性查询 |
| 证据与血缘 | W3C PROV-O、决策一等对象、时点快照 | Evidence 节点 + 轨迹记录 |
| 进化闭环 | 有抽取/建图管线（须对闭集禁用） | 有门控 evolve（须关闭或仅产出建议） |
| 服务接口 | Python API / MCP / REST / CLI | MCP / Claude Code / Codex 插件 |
| 依赖重量 | **重**（numpy/pandas/scipy/pyarrow/grpc…） | 轻（纯 Python 核心） |
| 主要风险 | 平台依赖、全家桶绑走架构 | 研究原型不稳定、建模方向相反 |

### 10.3 共同的使用边界（硬约束）

1. **旁路部署**：以独立服务（MCP/REST）运行，agent 不引入其重型依赖，只调用查询/校验接口；
2. **作者本体单向载入**：加载 `YAML → Turtle/SHACL Bundle`（可复用 `scripts/serialize-facts-turtle.py` 的产出），禁用自动抽取/建图/进化对注册闭集的写操作——平台只 resolve，我方代码 enforce；
3. **不给 SAP 凭据、禁用平台自带 SAP 连接器**（Semantica 含 SAP OData connector）：SAP 执行仍只走我方 Gateway 与人工审批；
4. WRITE 人审 duty 可映射到 SHACL/PROV-O 语义，但**执行凭证仍只认 ApprovalRecord**（状态 + 参数快照哈希 + 未过期）；
5. 经平台返回的内容以结构化标识传递，不直接拼入 prompt，防止语义层内容注入。

### 10.4 Shadow spike 计划（口径与 §6 一致：只记录不决策）

| 步骤 | Semantica | EvoOntology |
|---|---|---|
| 1. 部署 | 独立 venv + 旁路 MCP/REST 服务 | MCP server，`rolling_trajectory` 模式 |
| 2. 数据 | 导入我方 YAML→Turtle/SHACL Bundle，不接 SAP | 单向投影 registry + 样例事实（写 Content Layer exporter） |
| 3. 运行 | 全量 eval 上跑校验/前置/权限/召回查询 | 同 |
| 4. 指标 | 结论一致率（参数/前置/权限近 100%）、召回 Top-1/Top-2 覆盖率、运行稳定性、**旁路服务资源占用** | 同（资源占用项权重低） |
| 5. 进化 | 全程关闭自动写闭集 | evolve 仅产出回流给 registry 作者的建议 |

### 10.5 准入判据（在 §6.5 之上追加）

1. 作者本体单向导入可行，平台侧无任何对闭集的自动写路径可被触发；
2. shadow 结论一致率与召回覆盖不低于现行路径；
3. Semantica 路线：旁路服务的运维/资源成本可接受，且不绑定其专有后端（保持 RDF 标准导出可撤离）；
4. EvoOntology 路线：API 与运行稳定性经一段时间 shadow 验证（当前研究代码状态下此项门槛更高）；
5. 任一路线通过后，§4 的自建 OntologyBinding 缩减为"YAML → 平台的单向 loader + 边界测试"，Phase 划分仍按 §5 执行。

## 11. 待办

- [ ] 评审本提案，决定是否立项
- [ ] 立项后按 §5 Phase 0 启动：codegen + shadow
- [ ] 按 §10.4 对 Semantica（首选）/ EvoOntology（备选）执行旁路 spike
- [ ] 依据 shadow 与 spike 数据决定：自建 / 采用平台 / 继续挂起


# EvoOntology / Semantica 调研评估

- **创建日期**: 2026-09-27
- **调研对象**:
  - EvoOntology — <https://github.com/ruc-datalab/EvoOntology>（论文 arXiv:2609.15779，人大 ruc-datalab）
  - Semantica — <https://github.com/semantica-agi/semantica>（v0.7.0，MIT）
- **决策结论**: EvoOntology **机制借鉴、不引入依赖**（优先补配对评测门禁与轨迹归因回流）；Semantica 与本项目形态基本**正交**，仅 PROV-O 审计建模与审批决策节点可作远期参考。两者均不照搬架构。

---

## 1. 两个项目分别是什么

| | **EvoOntology** | **Semantica** |
|---|---|---|
| 定位 | 数据 Agent 的**自进化本体层**（"first self-evolving ontology layer for data agents"） | **图原生**的企业级 Context / 问责 AI 基础设施 |
| 核心对象 | 类型化语义图：Terms / Mappings / Constraints / Evidence 四类节点 | Context Graph + 完整 KG：实体 / 关系 / 事件 / **决策**为一等节点 |
| 标准 | 自定义 Schema，SQLite 存储 | RDF / OWL / **SHACL** / SKOS / SPARQL + W3C **PROV-O** |
| Agent 接入 | MCP 工具 `browse_semantics` / `resolve_semantics`，按需检索；Claude Code / Codex 插件 | MCP server 暴露 20+ 工具（抽取、决策、推理、图分析等） |
| 进化方式 | **自动**：轨迹诊断 → 候选补丁（Candidate）→ 父子版本配对评测 → 达标才发布 | **人工 ratify**：从数据归纳草稿本体、事实信任分级（quarantine/bronze/silver/gold）、真值维持，正式变更需人确认 |
| 适用前提 | 工作负载可回放（SQLite 只读 replay）；benchmark：BIRD / DDR-10K / InsightBench | 企业数据摄入全家桶（Kafka、SAP OData、Databricks、Snowflake 等）→ KG |
| 形态 | 轻量，围绕 Agent 的"可训练状态（trainable agent state, not weights）" | 重型确定性图平台（KG 构建与推理无需 LLM） |

**一句话区别**：EvoOntology 是"给 Agent 用的、会自己进化的薄语义层"；Semantica 是"把企业数据搬进来建知识图谱并全程审计的厚平台"。

### 1.1 EvoOntology 三层结构与生命周期

- 三层：**Content Layer**（四类节点的语义图）、**Schema Layer**（节点字段与允许的关系类型）、**Tool Layer**（MCP 工具 + session manifest 引导按需取数）。
- 生命周期：**Build**（从工作负载派生候选概念、对照源数据验证后发布 v0）→ **Use**（Agent 按需查询，记录轨迹）→ **Evolve**（进化 agent 诊断反复出现的问题，归因到 Content / Tool / Schema，产出有界补丁）→ **Evaluate**（父子版本在相同数据、模型、decoding、交互预算下配对对比）→ **Publish/Reject**（指标可复现改善才升版）。
- 报告效果（四底座分析子集）：DDR-Bench 轨迹分 69.5 → 89.5（+20.0），BIRD 执行准确率 63.6 → 72.4（+8.8），InsightBench 53.2 → 54.2（+1.0）。

### 1.2 Semantica 关键能力

- 端到端管线：Sources → Ingest/Parse/Normalize/Split → Extract → 冲突检测 → 去重 → KG →（Ontology / Reasoning / Provenance / Decisions）→ 多模存储 → Export / Explorer / REST / MCP。
- 决策智能：`record_decision()`、因果关系（CAUSED / INFLUENCED / PRECEDENT_FOR）、决策链追踪、先例检索、影响分析、策略门禁。
- 双时态事实（valid time / recorded time）、Allen 区间代数、时点快照。
- W3C PROV-O 全量血缘，可导出 Turtle/CSV 供监管。
- 注意：其文档自承 Rete 匹配器"有意从简"、SPARQL 直到 v0.7.0 才真正执行，生产合规前需再验证。

---

## 2. EvoOntology 与本项目的对照

### 2.1 其核心主张在 v1.2 架构中已覆盖大半

依据 `docs/wiki/sap-nexus-agent-technical-architecture.md` §1.2（架构基线：图 v2.0）：

| EvoOntology 概念 | 本项目已有对应物 |
|---|---|
| 版本化本体、Candidate / Parent | YAML 单一来源 → 编译期派生 **Capability Manifest 版本快照**（可签名、可 diff） |
| 从使用中进化 | 离线回路：`IntentDecisionRecord → 长尾未命中人工确认 → 别名/关系回流 → 本体` |
| Grounded construction（验证后入库） | Gateway 实测 SAP + fail-closed + bad case 的 `sourceTraceId` |
| 回归门禁 | §10 bad case 回归集 + §10.3 分类门禁 + §13 trace 回放 |
| Session manifest 按需检索 | 编译期 Manifest 即同一思路，且更彻底：**请求期只查表，本体不被请求期查询** |

### 2.2 真正值得补的差距（按性价比排序）

1. **配对评测门禁（paired evaluation）——最值得借**
   Candidate 发布前用相同数据、模型、decoding 与交互预算对比 Parent，指标可复现改善才发布。本项目 §10.3 目前是"改后跑回归，pass/fail"，缺少"**相对基线不退化**"层：一次描述/别名改动即使回归全绿，匹配准确率仍可能悄悄下降。eval harness 已有 SLI（§10.1），增加 vN / vN+1 同集对比步骤成本很低。
2. **轨迹自动归因 → 候选补丁（不自动发布）**
   其把失败归因到 Content / Schema / Tool 三层。本项目 bad case 已有 `regressionTags`（selection / parameter / caliber / clarification / reject / narrative），可加自动归因与同類聚类，把高频同类失败转为 registry / 本体候选补丁，把现有"手工回流"半自动化。
3. **语义对象证据化**
   Evidence 节点族要求每条 Term / Mapping 挂验证证据。可强化为"每个业务口径定义可溯源到 bad case / trace"，`sourceTraceId` 已是雏形。
4. **远期**：能力上量后（§3.6 Phase 3+ 海量能力）参考其两层检索（manifest 引导 + on-demand resolve）控制上下文膨胀。当前能力可见面封顶 15，暂不需要。

### 2.3 不应照搬的部分

- **本体自动发布不能上**：对方场景是数据分析，答错影响一份报告；本项目涉及 **WRITE 审批链**，本体变更影响能力路由，错一个映射可能导向错误 SAP 动作。进化 agent 产出必须保持"候选 → 人工确认"；结构 / 本体迁移按项目规则走 **Comet Classic + OpenSpec 评审**（HEAVY 信号）。
- **运行时 browse/resolve 服务不引入**：与 v1.2"本体是数据不是运行时、推理在编译期、请求期只查表"的明确决策冲突。对方属约 400 stars 级研究产物，也没有本项目的安全边界设计。

---

## 3. Semantica 与本项目的对照

整体**正交**：本项目不把数据搬进知识库——SAP 是活的事实源，经 Java Gateway 走 JCO RFC / BAPI 实时访问。其 ingest → NER/抽取 → 去重/冲突 → GraphRAG → 向量库整条链（含 SAP OData connector）对本项目基本无用。

| 可借点 | 本项目对应位置 | 时机 |
|---|---|---|
| **W3C PROV-O 血缘建模** | 结构性要求③：server-owned principal + lineage 联合哈希、多宿主审计（`ApprovalRecord` §9.5） | 未来做合规审计导出时按 PROV-O 建模 |
| **Decision 一等节点 + 先例检索** | WRITE 能力 propose → confirm 审批记录 | 远期：相似 WRITE 先例比对、影响链分析 |
| **SHACL 实例校验** | 现为 YAML schema + `openspec validate --strict` | Neo4j 实例图真正上量后再考虑 |
| 事实信任分级、双时态 | 事实来自 SAP 实时返回，时点一致性由能力内 `asOf` 负责 | 不需要 |

---

## 4. 建议行动清单

| 优先级 | 动作 | 来源 |
|---|---|---|
| 高（低成本） | eval harness 增加配对评测：registry / manifest 改动须对比 vN / vN+1 指标，不退化才合并 | EvoOntology paired eval |
| 中 | bad case 增加自动归因聚类，产出**候选**补丁，人工 ratify 后回流本体（自动化离线回路，非自动发布） | EvoOntology evolve |
| 中 | 业务口径定义强制绑定 case / trace 证据 | EvoOntology Evidence |
| 低 / 远期 | 审批与 Run lineage 按 PROV-O 建模；WRITE 审批做决策节点与先例库 | Semantica |
| 不做 | 自进化运行时、KG 摄入全家桶、现阶段引入 SHACL | — |

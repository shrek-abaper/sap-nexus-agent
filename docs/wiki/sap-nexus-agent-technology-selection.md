# SAP Nexus Agent 技术选型与工程路线决策

## 文档版本

| 字段 | 内容 |
|---|---|
| 文档名称 | `SAP Nexus Agent 技术选型与工程路线决策` |
| 当前版本 | `v0.2.9` |
| 状态 | `Decision Baseline Draft` |
| 创建日期 | `2026-06-19` |
| 最近更新 | `2026-07-24` |
| 维护目录 | `docs/wiki/` |
| 文档定位 | 指导 SAP Nexus Agent 工程骨架、技术栈和 AI Native 工程产物组织的技术选型基线 |
| 关联技术架构 | `docs/wiki/sap-nexus-agent-technical-architecture.md` |
| 关联实施路线 | `docs/wiki/sap-nexus-agent-implementation-roadmap.md` |
| 关联智能编排路线 | `docs/wiki/sap-nexus-agent-openharness-semantic-orchestration.md` |
| 关联 DeerFlow 决策 | `docs/wiki/sap-nexus-agent-deerflow-adoption-analysis.md` |

## 版本记录

| 版本 | 日期 | 变更摘要 | 决策状态 |
|---|---|---|---|
| `v0.2.9` | `2026-07-24` | 区分本地 MVP 与共享/量产运行选型：当前 SSE 为 buffered SSE-format、Run/Approval 为进程内状态；补充可信身份、durable runtime 条件门禁、分层 Store 与真实 streaming 目标；把 OData 双跳限定为已验证实现而非所有 HTTP executor 默认模板；同步 S1 已归档 | 当前技术基线 |
| `v0.2.8` | `2026-07-23` | 增加 §5.7 DeerFlow 2.1.0 借鉴选型：不引入 `deerflow-harness` 或第二 runtime；S2 适配 progressive capability disclosure，S3 适配 PlanGraph-governed task lifecycle；durable runtime 与 UserPreferenceMemory 保持触发式候选 | 当前技术基线 |
| `v0.2.7` | `2026-07-18` | 增加 §5.6 OpenHarness 对比后的语义编排选型：OpenHarness 仅作设计参考，不引入 runtime 依赖；Planner 留在现有 Python Agent，关系图采用 YAML + JSON Schema + 内存图，LLM 只生成 GoalSpec/PlanDraft candidate，deterministic PlanCompiler 和现有 Gateway 保持执行权威 | 当前技术基线 |
| `v0.2.6` | `2026-07-14` | 增加 §5.5 能力关系存储选型（三元组模型 + 文件 + 内存图先行，图数据库为 Phase 8 触发式 Reserved 决策，引擎待 spike）；更新结论先行表 Knowledge Graph 行与 §11 待确认表 | 当前技术基线 |
| `v0.2.5` | `2026-07-09` | OData executor 选型落地：OData 用 Python（非 Java），因 OData 是纯 HTTP 无 Java SDK 绑定需求（JCo 用 Java 是 `sapjco3.jar` 强制）；Java Gateway 仅薄反代 + Python 微服务做真实 OData 逻辑；`services/` 重组为连接器执行层（`services/gateway/` Java 多模块 + `services/odata-service/` Python） | 已完成 |
| `v0.2.4` | `2026-06-27` | 增加 `SQL_READ` executor 技术预留：面向已注册、已评审、参数化、只读 SQL 工件的受控执行绑定；Agent / LLM 不生成 SQL，不开放 arbitrary query interface | 已完成 |
| `v0.2.3` | `2026-06-23` | 增加 `REST_JSON` executor 技术预留：先作为 SAP Nexus 辅助接入能力，面向存量系统 HTTP JSON API；架构上预留 Enterprise Nexus Agent 通用接入层；当前仅进入 Registry / OWL contract，不实施 REST Gateway runtime | 已完成 |
| `v0.2.2` | `2026-06-22` | 增加多 executor 技术选型：当前 `JCO_RFC` 已实现，后续统一 OData Gateway 参考 `sap-sto-create`，CDS / ADT Gateway 参考 `sap-adt-cli`；语义层和参数映射保持在 Gateway 外部 | 已完成 |
| `v0.2.1` | `2026-06-21` | 更新 Workbench Console 技术基线状态：React + Next.js + TypeScript 本地控制台已落地并归档，下一步转入 Registry / OWL Contract 加固 | 已完成 |
| `v0.2.0` | `2026-06-20` | 增加 Agent Workbench Console 前端技术基线，并明确 Agent 主架构为 Harness Engineering；React 是前端 UI runtime，ReAct-style reasoning 只能作为 Harness 内的受控推理模式 | 已完成 |
| `v0.1.1` | `2026-06-20` | 同步 Agent LLM intent adapter 基线：Python Agent 已接入 OpenAI-compatible LLM，默认 `hybrid` 模式，LLM 输出仍受闭集 capability 和规则兜底约束 | 已完成 |
| `v0.1.0` | `2026-06-19` | 固化第一轮工程技术选型：Spring Boot Gateway、Gradle、YAML Registry、JSON Schema contracts、Python Agent package、JSONL runtime trace、分层测试与 OpenSpec/Comet 实施边界 | 已完成首轮 implementation 输入 |

---

## 1. 结论先行

可以继续开发，但不应裸写代码。Registry / OWL Contract、Gateway execution、第二条 Read capability、sandbox write vertical slice 和 S1 Semantic Planning Foundation 均已完成实现与验证；当前下一步仍是 S2 Planner Dry-run design：

```text
sap-nexus-planner-dry-run
```

推荐默认选型：

| 维度 | 选型 | 决策 |
|---|---|---|
| Execution Gateway | Spring Boot | 作为长期 Gateway family 框架；当前实现为 JCo Gateway，后续扩展 OData / CDS / ADT / REST JSON / SQL_READ adapter |
| Java Runtime | Java 17 LTS target | 量产目标；本机当前为 Java 11，实施前需配置 JDK 17 或明确临时兼容策略 |
| Build Tool | Gradle Wrapper | 提交 wrapper，保证不同机器一致构建 |
| Registry | YAML + schema validation | MVP 轻量本体；语义能力与 technical binding 分离 |
| Contract | `schemas/*.schema.json` | 跨 Java、Python、prompt、eval 的契约源 |
| Python Agent | `agent/sap_nexus_agent/` package | CLI、Gateway client、CallPlan、Fact、Narrator、Eval 分层 |
| Frontend Workbench | React + Next.js + TypeScript | 内部 Agent 控制台和本地体验工具 |
| Frontend Architecture | Modular Monolith | 按 Agent runtime、timeline、artifact、trace、HITL 模块切分 |
| Runtime Streaming | SSE protocol first | 当前实现是完成后一次性返回的 SSE-formatted event body；共享环境目标是增量 SSE + cursor/reconnect/replay，WebSocket 仍只在双向协作证据出现后引入 |
| Runtime Adapter | Agent Runtime Adapter | 前端不直接调用 SAP / Gateway / raw RFC |
| Runtime Store | 按状态职责分层 | 本地 trace/eval 可用 JSONL；Thread/Run、Approval、PlanExecution 和 Evidence 在共享/量产环境必须使用满足各自一致性与保留要求的 durable store |
| Trusted Identity | Server-owned principal context | principal、tenant、role、data scope 和 ApprovalActor 只能由受信服务端注入；候选可见性与执行授权双重校验 |
| Eval | YAML cases + Python runner | 能力命中、缺参拦截、事实一致性、叙事守卫 |
| Formal Workflow | OpenSpec / Comet | feature 变更可追溯、可验证、可归档 |
| Semantic Planner | 现有 Python Agent 内独立模块 | 复用 Registry、CallPlan、Fact、Eval 和 Trace，不引入第二 Agent runtime |
| Planner Authority | LLM candidate + deterministic PlanCompiler | LLM 生成 GoalSpec/PlanDraft；编译器负责类型、依赖、绑定、排序和治理校验 |
| Plan Contract | JSON Schema `GoalSpec` / `PlanGraph` + Registry Snapshot | S1 schema 与 validation 已落地；S2 设计 PlanDraft/PlanCompiler/dry-run，S3 再设计执行 ledger 与 OutputProjection |
| Knowledge Graph | Not runtime in MVP | 能力关系用三元组模型 + 文件存储（edge list）+ 内存图；图数据库为 Phase 8 触发式 Reserved 决策，引擎待 ROI spike（RDF store vs Neo4j） |
| OpenHarness | 设计参考，不增加依赖 | 借鉴 Agent loop、Tool Schema、Permission/Hook、Dry-run、Memory/Resume；拒绝第二运行时和模型自由 SAP Tool Calling |
| DeerFlow Runtime | 设计参考，不增加依赖 | 不引入 `deerflow-harness`、DeerFlow Gateway、默认 lead agent 或 frontend；避免第二 Agent runtime 和执行权威 |
| Progressive Capability Disclosure | S2 内适配 | metadata-first `CapabilityCard` -> 小候选集合 -> LLM candidate；deterministic MatchDecision / PlanCompiler 最终裁决 |
| PlanExecutor Lifecycle | S3 内适配 | 只借鉴 ready-node、并发上限、timeout、cancel、ledger、trace；并行权来自已验证 PlanGraph |
| Durable Agent Runtime | Conditional production gate | 不阻塞本地 S2；共享 S3、跨重启、长审批、multi-worker / HA 或非 sandbox WRITE 前必须先落持久 Run/Approval、ownership/lease、event cursor 和幂等 continuation |
| Governed User Memory | Later / Triggered | 身份、tenant、retention、删除和审计契约成熟后再 pilot；不保存业务事实或执行权威 |
| JCo RFC Executor | Java JCo | 当前已实现，适合 BAPI/RFC |
| OData Executor | Python 微服务 + Java 薄反代 (HTTP client + CSRF/session/error normalization) | 已落地，Python + Java 双语言；详见 §5.4 |
| CDS / ADT Executor | ADT REST API + XML parsing + SELECT-only guard | 待 pilot，参考 `sap-adt-cli` |
| REST JSON Executor | HTTP client + JSON Schema + response mapping + credentialRef redaction | 待 pilot，先作为 SAP 场景的存量系统辅助接入能力 |
| SQL_READ Executor | Registered SQL Read Gateway + parameterized query + read-only dataSourceRef + sqlHash verification | 待 contract / pilot，只执行已注册 SQL 工件，不生成 SQL |

本项目首要风险不是 JCo/SAP 连通，而是能否把 SAP 调用封装成受控、可审计、可复用、可回放的能力执行系统。

架构命名边界：

| 名称 | 本项目含义 |
|---|---|
| Harness Engineering | Agent 主架构；所有可执行步骤必须经过计划、校验、执行、归一、举证、审计和回放边界 |
| React | 前端 UI runtime，用于内部 Agent Workbench Console |
| ReAct-style reasoning | 可选的局部推理模式；只能在 Harness 内提出候选理解或候选动作，不能直接执行 SAP |

因此，SAP Nexus Agent 的技术选择是：

```text
Agent architecture = Harness Engineering
Frontend runtime = React / Next.js
Reasoning pattern = governed ReAct-style only when needed
```

---

## 2. 当前本地环境观察

当前本机快速检查结果：

| 项 | 观察 |
|---|---|
| Java | `openjdk version "11.0.30"` |
| Python | `Python 3.12.3` |
| Gradle | 未发现全局 `gradle` 命令 |
| Maven | 未发现全局 `mvn` 命令 |
| Node package | 当前仅有 OpenSpec 依赖 |

影响：

- 如果采用 Spring Boot 3.x，应先配置 JDK 17。
- 如果采用 Gradle，应提交 Gradle Wrapper，避免依赖全局 Gradle。
- 首次生成或执行 Java 构建可能需要下载依赖；受限网络环境下要提前申请或使用内部缓存。
- 不应为了迁就当前 Java 11 环境而永久锁死在过期技术栈；如果短期必须 Java 11，应在 change 中标注为 temporary compatibility decision。

---

## 3. Execution Gateway 选型

### 3.1 推荐：Spring Boot

选择 Spring Boot 作为 Gateway family 的长期服务框架。当前实现目录为 `services/gateway/`（多模块：`core` / `jco` / `odata` / `app`）；后续可在统一 Gateway contract 下增加 CDS / ADT 和 REST JSON adapter。OData executor 已落地，采用 Python 微服务 + Java 薄反代模式（详见 §5.4）。

理由：

- 适合长期生产服务，不只是 demo endpoint。
- 健康检查、配置管理、测试、JSON serialization、HTTP controller、日志生态成熟。
- 方便后续加入 actuator、metrics、request tracing、validation、profiles、security filter。
- 团队可维护性强，招聘和知识迁移成本低。

建议目标：

```text
Java 17 LTS
Spring Boot 3.x
Gradle Wrapper
```

### 3.2 备选：Javalin

优点：

- 轻量，启动快，样板少。
- 更容易在 Java 11 环境下快速起步。

不选为默认的原因：

- 长期生产治理能力需要自行补齐较多基础设施。
- 后续配置、测试、observability、security 的标准化弱于 Spring Boot。

### 3.3 备选：Quarkus / Micronaut

优点：

- 云原生、启动快、资源占用低。

不选为默认的原因：

- 当前主要目标是 SAP On-Prem Gateway family 的治理封装，不是极限 cold start 或云函数部署。
- 团队熟悉度和 JCo 运行环境兼容性需要额外验证。

---

## 4. Build Tool 选型

推荐：Gradle Wrapper。

理由：

- 不依赖本机全局 Gradle。
- 新项目骨架清晰，适合多模块扩展。
- 与 Spring Boot 插件生态成熟。
- 后续可自然拆分 `services/gateway` 多模块、contract generation、integration tests。

要求：

- 提交 `services/gateway/gradlew`、`services/gateway/gradlew.bat`、`services/gateway/gradle/wrapper/`。
- 不提交本地 Gradle cache。
- 如果网络受限导致 wrapper 或 dependencies 下载失败，按环境规则申请网络或配置内部镜像，不要手写临时 vendor 依赖。

Maven 可作为团队偏好备选，但如果没有明确团队 Maven 偏好，默认使用 Gradle。

---

## 5. Registry 与 Contract 选型

### 5.1 Capability Registry

MVP 使用：

```text
registry/capabilities.yaml
```

它同时承担：

- Gateway allowlist。
- Agent capability catalog。
- executor binding mapping，包括当前 `JCO_RFC` 和后续 `ODATA`、`CDS_ADT`、`CDS_ODATA`、`REST_JSON`、`SQL_READ`。
- 轻量能力本体。
- 未来 OWL / Graph Registry 种子数据。

Registry 必须包含：

```text
capabilityId
ontologyIri
kind
semanticVersion
status
domain
businessObject
inputs
outputs
executorBinding
governance
```

不要把 capability metadata 写死在：

- Java controller。
- Python prompt。
- eval test body。
- README 示例。

### 5.2 JSON Schema Contracts

共享契约放在：

```text
schemas/
```

首批建议：

```text
schemas/capability.schema.json
schemas/call-plan.schema.json
schemas/execution-result.schema.json
schemas/reasoning-fact.schema.json
schemas/trace-span.schema.json
```

原则：

- Java / Python / prompt / eval 都围绕 schema 对齐。
- Prompt 不能成为唯一校验来源。
- Contract 变更必须触发 eval 和 schema validation。

### 5.3 Executor Binding Contract

Capability Registry 不应直接退化成 RFC/BAPI 目录。推荐拆分：

```text
Capability Registry = business semantics
Executor Binding Catalog = technical allowlist
Gateway = protocol execution only
```

Executor type 选型：

| Type | 技术选型 | 参考 | 约束 |
|---|---|---|---|
| `JCO_RFC` | Java JCo | 当前 `services/gateway/jco/` | 不开放 arbitrary RFC；READ 不 commit |
| `ODATA` | **Python 微服务**（HTTP session + CSRF + JSON error normalization）+ Java 薄反代 | `services/odata-service/`（Python）+ `services/gateway/odata/`（Java ODataHttpProxyAdapter） | 第一版只做 read；Java 侧不组装 `$filter`、不直连 SAP；write 等 Action Governance 后再开放。详见 §5.4 |
| `CDS_ADT` | ADT REST API + XML parsing + Data Preview | `sap-engineering-skill/skills/sap-adt-cli` | 只做 metadata / controlled read preview；不开放 arbitrary SQL |
| `CDS_ODATA` | CDS/RAP exposed OData service | 后续 OData Gateway | 生产 read 优先走已发布 OData/RAP 服务 |
| `REST_JSON` | HTTP client + JSON Schema + request/response mapping | 后续 REST Gateway read pilot | 先作为 SAP Nexus 辅助接入能力；不开放 arbitrary URL、method、headers 或 JSON payload |
| `SQL_READ` | Registered SQL Read Gateway + parameter binding + sqlHash verification | 后续 SQL_READ contract / read pilot | 只执行已注册、已评审、参数化、只读 SQL 工件；不开放 raw SQL、SQL fragment、table override 或 stored procedure |

`sap-sto-create` 中 STO 创建的业务规则、preview/confirmed 门禁和采购订单 payload 不进入通用 Gateway；只借鉴 OData 连接、CSRF、session、HTTP error 和 SAP OData response normalization。

`sap-adt-cli` 中 ADT write-source、activate、transport 相关能力不进入当前 read Gateway；只借鉴 ADT 认证、CDS DDL source、Data Preview、GET -> POST fallback 和 XML result parsing。

`REST_JSON` executor 的第一阶段定位是为 SAP 场景补充外部事实来源，例如 CRM、WMS、MES、供应商平台或内部主数据服务。它可以作为未来 Enterprise Nexus Agent 的通用接入层种子，但当前必须服从 SAP Nexus 的能力闭集、CallPlan、Gateway allowlist、`ExecutionResult -> ReasoningFact` 和审计回放边界。

`SQL_READ` executor 的第一阶段定位是为 SAP Nexus 或 Enterprise Nexus 补充受治理数据层事实来源，例如 DWH、read replica、报表库、审计库或受治理 view。它只能执行 registry / binding catalog 中声明的 `sqlRef`，并通过 `sqlHash`、named parameter schema、read-only dataSourceRef、row / byte / timeout limit 和 output schema 保护运行边界。

### 5.4 OData executor 选型：Python 而非 Java

`ODATA` executor 已落地，技术选型为 **Python 微服务 + Java 薄反代**，而非纯 Java 实现。这是与 `JCO_RFC`（纯 Java）的关键技术选型差异。

选型理由：

- **JCo 用 Java 是强制约束**：`sapjco3.jar` 是 SAP 官方 Java 绑定库，native library (`libsapjco3.so` / `sapjco3.dll`) 必须在 JVM 中加载。JCo 没有官方 Python 绑定，所以 `JCO_RFC` executor 必须用 Java。
- **OData 是纯 HTTP 协议，无 Java 绑定理由**：OData 调用是标准 HTTP GET + CSRF token + JSON 响应归一。Java 在此场景下没有任何 SDK 级优势，反而 Python 在 HTTP client、JSON 操作、CSRF/session 管理、错误归一方面更轻量且生态成熟。
- **Java Gateway 保持薄反代角色**：`ODataHttpProxyAdapter`（Java 侧）只做 HTTP 转发到 Python 微服务 + JSON 归一为 `TechnicalExecutionResult` + redaction。它不做 `$filter` 组装、不直连 SAP。这保持 Java Gateway 的 executor-agnostic 定位 -- dispatcher 按 type 路由，每个 adapter 只负责自己 executor 的技术执行。
- **Agent 单端点保持**：Agent 调 Java Gateway（:8080）只认 `capabilityId`，不感知 executor 类型是 Java 直连还是 Python 微服务。Java dispatcher 自动路由。
- **未来扩展模式不默认复制双跳**：当前 Python OData service + Java thin proxy 是已验证实现，不自动成为 `REST_JSON`、CDS 或其他 HTTP executor 的模板。新增独立服务必须由 SDK、进程级 credential 隔离、独立扩缩容、团队 ownership 或故障域证据驱动；否则优先减少跨服务跳数。

实现位置：
- Java 薄反代：`services/gateway/odata/`（`ODataHttpProxyAdapter` + `ODataProxyProperties`）
- Python 微服务：`services/odata-service/`（:8081，组装 `$filter` + GET SAP OData + JSON 归一）
- 扩展规则详见 `services/gateway/README.md` 的 Extension Rules 段

REST JSON binding 必须至少表达：

```text
bindingId
type = REST_JSON
systemRef
method
pathTemplate
request mapping
response mapping
credentialRef
timeout / retry / sideEffect guard
```

REST JSON 禁止：

- 由 Agent / LLM 提交任意 URL、method、headers、token 或 JSON body。
- 将 API key、token、base URL、tenant secret 或连接串写入 git、trace、响应或日志。
- 将有副作用 REST 调用建模为 `Function`。

### 5.5 能力关系存储选型：三元组模型先行，图数据库 Reserved

结论：现在采用三元组模型（S-P-O，对齐 OWL），不引入图数据库。模型与存储分开决策--模型早采用，便宜且对齐 OWL；存储引擎推迟到触发条件满足。

| 维度 | 文件 + 内存图 | 图数据库 |
|---|---|---|
| 规模 | 当前 capability + fact-type 节点数十量级，足够 | 数百节点以上才体现价值 |
| 查询复杂度 | plan 时加载进内存图查依赖，单跳 / 少跳足够 | 多跳 planner 查询成热路径时才有必要 |
| 一致性 | `capabilities.yaml` + validator 仍是唯一 gated 源，关系文件对其做引用完整性校验 | 图库易成第二事实源，产生漂移风险 |
| 运维成本 | 无额外运行时依赖 | 引入 DB 运维、备份、HA |
| 与架构一致性 | 符合“MVP 不引入 GraphDB 运行时依赖” | 违反当前 MVP 约束，需触发式升级 |

当前方案：关系存 `ontology/capability-relations.yaml`（三元组 edge list），plan 时加载进内存图查依赖；`capabilities.yaml` + validator 仍是唯一 gated 源，关系文件对其做引用完整性校验。

图数据库触发条件（与实施路线 §13、架构 §8.2 一致）：节点数百以上 / 多跳 planner 成热路径 / 跨域治理可视化 / 多服务并发共享。

引擎选择留给 spike：Neo4j property graph 需对 OWL 做阻抗匹配；RDF triple store（Jena / GraphDB）与三元组 + OWL + SHACL 同栈更贴。图谱永远是派生只读索引，不是执行权威，不可用时退回 Registry snapshot。

一个需在后续文档定清的开放项：关系数据的生产与校验方式--fact-type 自动派生候选边（需 eval 兜底防错误边）vs 人工维护关系文件（会滞后于能力增长）。此项比存储引擎更该先定。

### 5.6 OpenHarness 对比后的语义编排选型

对比结论：OpenHarness 是通用 Agent Harness，不是本体规划引擎。SAP Nexus 不引入 OpenHarness runtime、Plugin loader 或 Permission runtime 依赖，只借鉴可迁移机制。

| 机制 | SAP Nexus 选型 |
|---|---|
| Agent loop | 在现有 Python Agent 内增加 `observe -> compile/repair -> validate -> execute` 循环 |
| Tool Schema | 只暴露 planner meta-operations；SAP 执行继续通过 `capabilityId -> Gateway` |
| On-demand Skill | 按领域加载只读 capability cards / policy guidance，不赋予新执行权 |
| Permission / Hook | deterministic policy 为权威；LLM Hook 仅 advisory |
| Dry-run | 建设业务 PlanGraph dry-run，检查节点、边、参数来源、Fact 类型、治理和能力缺口 |
| Memory / Resume | 持久化 GoalSpec、PlanGraph、节点状态和 Registry Snapshot id，不依赖聊天记忆恢复执行 |
| Multi-Agent | 后续可做 Planner/Critic/Evaluator 建议角色，不进入 SAP 执行权威 |

语义规划近期技术栈：

```text
Python Agent
-> GoalSpec / PlanGraph JSON Schema
-> YAML Fact Type + Capability Relation
-> in-memory read-only graph
-> deterministic PlanCompiler
-> existing Gateway Family
-> JSONL trace / eval / replay
```

LLM 只生成 `GoalSpec` / `PlanDraft` candidate。以下能力必须保持 deterministic：

- capability / fact-type 引用解析。
- 输入输出类型匹配。
- 依赖和环检测。
- 参数来源校验。
- governance / side effect / approval 校验。
- Registry Snapshot/version 绑定。
- PlanGraph 拓扑排序和可执行状态判定。

OpenHarness 式多个 Tool Call 并发不能直接用于组合执行。只有通过 PlanGraph 证明互不依赖且 `sideEffect=none` 的 Read 节点才可并行；Write、事务和存在数据依赖的节点必须按显式边执行。

详细采纳/拒绝矩阵、领域模型和 S0-S6 路线见 `docs/wiki/sap-nexus-agent-openharness-semantic-orchestration.md`。

### 5.7 DeerFlow 对比后的机制采纳选型

DeerFlow 2.1.0 是成熟度较高的通用 Super Agent Harness，但其默认执行模式仍是模型在可见 Tool 集合中选择下一步。SAP Nexus 不直接选择以下组件作为生产依赖：

- `deerflow-harness` 和默认 lead agent：会形成第二 Agent loop，且 Tool selection 不是 SAP 执行权威。
- DeerFlow Gateway / frontend：其 thread / run / workspace 协议与当前 `AgentRunEvent`、审批 artifact 和 evidence timeline 不同，整体替换需要高成本 adapter。
- DeerFlow task / sub-agent executor：缺少 Fact Type、Capability Relation、Registry Snapshot、side effect 和 approval-aware scheduling。
- DeerMem：默认面向通用用户 / Agent facts，不能保存 SAP 业务事实、approval 上下文或 policy decision；fallback search 也不足以承担企业事实检索。

选择吸收的窄机制：

| 领域 | 采纳机制 | SAP Nexus 权威边界 |
|---|---|---|
| 意图 / 候选发现 | Skill / Tool metadata progressive disclosure、deferred search、visibility pre-filter | 只产生 `CapabilityCard` / candidate；`MatchDecision` / `PlanCompiler` 最终裁决 |
| 能力组合 | concurrency limit、timeout、cancel、task status、durable ledger、trace propagation | S3 `PlanExecutor` 只执行已验证 PlanGraph 的 ready Read nodes |
| 长对话 | thread / run、checkpoint version gate、context compaction、resumable SSE | Summary 只属于 `ConversationState`；Plan / Approval / Evidence 结构化持久化 |
| 记忆 | user / agent scope、backend abstraction、token budget、retention / deletion 管理 | 仅 `UserPreferenceMemory`；作为不可信 advisory context，不能改变执行和治理 |

当前技术策略：

```text
S2 -> progressive candidate discovery + dry-run only
S3 -> PlanGraph-governed ready-node scheduler
productization trigger -> evaluate durable thread/run/checkpoint store
identity + governance trigger -> evaluate UserPreferenceMemory pilot
```

完整源码证据、决策矩阵、触发条件和 PoC 边界见 `docs/wiki/sap-nexus-agent-deerflow-adoption-analysis.md`。

---

## 6. Python Agent 选型

推荐结构：

```text
agent/
├── pyproject.toml
├── sap_nexus_agent/
│   ├── __init__.py
│   ├── cli.py
│   ├── capability_selector.py
│   ├── intent.py
│   ├── llm_client.py
│   ├── llm_intent.py
│   ├── call_plan.py
│   ├── gateway_client.py
│   ├── execution_result.py
│   ├── reasoning_fact.py
│   ├── narrator.py
│   └── eval_runner.py
└── tests/
```

MVP 策略：

- 默认 `hybrid` intent mode：OpenAI-compatible LLM 先解析，规则解析兜底。
- LLM output 只是 advisory candidate，必须归一到闭集 `IntentParseResult`。
- LLM selection 必须只从 Registry 闭集选择，当前只允许 `MM.Inventory.GetAvailability`。
- 缺参先澄清，不调用 Gateway。
- Narrator 只消费 `ReasoningFact`。

Python 技术选择：

| 维度 | 默认 |
|---|---|
| Python version | Python 3.12 |
| HTTP client | `httpx` 或标准库起步；按依赖策略决定 |
| LLM client | OpenAI Python SDK with configurable `base_url` |
| Local env loading | `python-dotenv` for local `.env`; real keys never committed |
| Test | `pytest` |
| Schema validation | `jsonschema` / `pydantic` 视依赖策略决定 |
| CLI | `argparse` 起步，避免早期引入重 CLI 框架 |

---

## 6.1 Agent Workbench Frontend 选型

前端定位为未来可生产化的内部 Agent 控制台，第一版交付形态可以是纯本地开发体验工具。它不是单一库存查询页面，而是用于观察、解释、审计和后续人审的 `Agent Workbench Console`。

推荐技术栈：

| 维度 | 默认 |
|---|---|
| Framework | Next.js |
| UI runtime | React |
| Language | TypeScript |
| Architecture | Modular Monolith |
| Streaming | SSE protocol first；当前 buffered response，量产目标为 incremental + reconnect/replay |
| Future realtime | WebSocket only when bidirectional interaction is needed |
| Boundary | Agent Runtime Adapter |
| State | Agent run state machine + Human-in-the-loop state skeleton |

模块化单体建议：

```text
frontend/
  app/
    workbench/
    api/
      agent-runs/
      agent-runs/[runId]/stream/
      traces/[traceId]/
  src/
    modules/
      agent-console/
      runtime-timeline/
      capability-catalog/
      call-plan/
      execution-result/
      reasoning-fact/
      human-approval/
      trace-audit/
      eval-lab/
    runtime/
      agent-runtime-adapter.ts
      run-event-schema.ts
      run-state-machine.ts
      redaction.ts
    shared/
      ui/
      types/
      contracts/
```

关键原则：

- 前端只能通过 `Agent Runtime Adapter` 启动和观察 Agent run。
- 前端不直接调用 Java Gateway / OData Gateway / CDS Gateway / REST Gateway，不直接调用 SAP 或外部系统，不暴露任意 RFC、OData、CDS、ADT 或 REST 调用入口。
- 当前 `SSE` 路由只承担本地执行结果的事件格式展示，不视为真实 streaming；共享环境必须支持增量发布、事件序号、reconnect cursor、terminal state 和 replay。
- Human-in-the-loop 状态机先实现骨架；read-only capability 显示为 `approval_not_required`。
- 所有 artifact 展示必须走 redaction，不展示 `.env`、SAP password、destination config、`LLM_API_KEY`、token 或 raw live LLM response。

---

## 7. Runtime Store 选型

Store 选型必须按状态职责拆分，不能用“JSONL first”覆盖所有运行状态：

| 状态 / 数据 | 本地 MVP | 共享 / 量产要求 |
|---|---|---|
| Trace / Eval artifact | JSONL | trace backend / relational index / object storage，按查询、保留和脱敏要求选择 |
| `ConversationState` | process memory | durable thread store，可独立压缩和删除 |
| `PlanExecutionState` | process memory / schema fixture | transactional durable store，绑定 Registry Snapshot 和 node ledger |
| `EvidenceState` | JSONL / artifact | append-oriented evidence store，保留 lineage、版本和审计引用 |
| `ApprovalRecord` | `InMemoryApprovalStore` | durable、原子 claim、幂等、可审计并绑定真实 ApprovalActor |
| Runtime event stream | buffered SSE-format body | ordered incremental stream + cursor/reconnect/replay |

本地 trace / eval 可以继续使用：

```text
runtime/traces/YYYYMMDD.jsonl
runtime/callplans/YYYYMMDD.jsonl
runtime/facts/YYYYMMDD.jsonl
runtime/eval_results/YYYYMMDD.jsonl
```

理由：

- 简单、可读、可复制、可 grep。
- 适合早期 trace 和 replay 设计验证。
- 不引入数据库运维成本。
- 后续可以迁移到 SQLite / PostgreSQL / Trace Service。

当前文档不因 DeerFlow 使用 SQLite / PostgreSQL / Redis 就预选基础设施。以下任一场景出现时，必须先启动 `sap-nexus-trusted-durable-runtime-foundation` 独立 change，并在进入对应共享/量产范围前完成：

- run 必须跨进程或跨重启恢复。
- Human Approval 等待时间超过单进程生命周期。
- multi-worker / HA Workbench 成为部署要求。
- 断线、并发或事件量已造成运行状态或证据丢失。
- S3 需要进入共享多用户环境。
- 任何非 sandbox WRITE 需要通过 Workbench 或 API 暴露。

届时先确定 `ConversationState`、`PlanExecutionState` 和 `EvidenceState` 的版本化 persistence contract，再比较 SQLite / PostgreSQL / stream bridge；不得从基础设施产品反推状态模型。

要求：

- `runtime/` 默认不提交生成内容。
- 如需提交 fixture，放到明确的 fixtures 目录并写 README。
- trace 不得包含 SAP 密码、完整敏感 destination、token 或个人敏感数据。
- 真实 runtime trace 和业务标识默认不得提交 Git；只有脱敏 fixture 可以进入版本库。
- Durable store 不可用时，执行和 approval continuation fail-closed；ConversationState 的附加体验可以 fail-soft。

---

## 8. 测试与验证路线

分层测试：

| 层 | 测试类型 | 目标 |
|---|---|---|
| Registry | schema validation | capability 配置完整、sideEffect/approval 合法 |
| Java Gateway | unit test | unknown capability、missing parameter、RETURN normalization |
| Java Gateway | live smoke | 已知样本调用真实 SAP Read |
| Python Agent | unit test | parser、CallPlan、ReasoningFact、Narrator guard |
| Eval | YAML cases | capability 命中、缺参拦截、非库存意图拒绝 |
| Replay | trace test | 给定 `traceId` 能串起 plan、result、fact |

Live SAP smoke 不应和普通 unit tests 强绑定。建议区分：

```text
fast tests: no SAP dependency
live smoke: requires SAP env and JCo native library
```

---

## 9. AI Native 工程产物

本项目的 AI Native 工程产物不是附属品，而是交付的一部分。

首批一等产物：

| 产物 | 目录 | 用途 |
|---|---|---|
| Capability Registry | `registry/` | 能力闭集、字段语义、executor binding |
| JSON Schema | `schemas/` | 跨语言契约 |
| Eval Cases | `evals/` | 行为回归 |
| Prompts / Templates | `agent/...` 或专门 prompt 目录 | LLM-facing 可 review 资产 |
| Trace / Replay | `runtime/` | 可诊断、可回放 |
| OWL Skeleton | `ontology/` | 未来语义治理入口 |

每新增一个 agent behavior，应同步考虑：

```text
schema 是否需要更新？
eval 是否覆盖？
trace 是否能证明？
Replay 是否能复现？
Prompt 是否可 review？
```

---

## 10. 首个实施 change 的技术范围

推荐首个 change：

```text
sap-nexus-capability-registry-gateway
```

包含：

- `registry/capabilities.yaml`。
- `schemas/capability.schema.json`。
- `schemas/execution-result.schema.json` 或 Java 等价 model 与后续 schema 对齐。
- `services/gateway/` Spring Boot + Gradle Wrapper skeleton。
- `GET /health`。
- `GET /capabilities`。
- `POST /capabilities/{capabilityId}/validate`。
- `POST /capabilities/{capabilityId}/execute` 的结构和 READ 能力路径。
- JSONL trace 写入位置和 `.gitignore`。

不包含：

- 完整 Python Agent。
- RecommendationPlan 推理。
- ML 推理。
- SAP Write Action。
- Knowledge Graph runtime。
- UI。

---

## 11. 待确认但不阻塞的问题

| 问题 | 默认处理 |
|---|---|
| 当前本机 Java 11 与目标 Java 17 不一致 | 实施前配置 JDK 17；如短期降级必须记录为临时决策 |
| 依赖下载受限 | 使用审批网络或内部镜像；不把依赖手工塞入 repo |
| Spring Boot 版本 | 默认 Spring Boot 3.x；若 Java 17 不可用再评估 Spring Boot 2.7 临时方案 |
| Schema validation 库 | 先选生态成熟库；避免自己手写完整 JSON Schema validator |
| Runtime Store 是否上 DB | 本地 S2 不上；共享 S3/长审批/多实例/非 sandbox WRITE 前按状态契约选择 durable store，不用单一 DB 承担所有职责 |
| 身份认证 / 授权产品 | 本轮不指定产品；先固化 server-owned principal、tenant、role、data scope、ApprovalActor 和双阶段授权契约 |
| LLM 何时接入 | 已在 Agent phase 接入；默认 `hybrid`，LLM 失败或输出不可信时规则解析兜底 |
| 能力关系是否上图数据库 | MVP / Pilot 不上；用三元组模型 + 文件 + 内存图；满足 Phase 8 触发条件并通过 ROI spike 后再评估引擎（RDF store vs Neo4j） |
| OpenHarness 是否作为 runtime 依赖 | 否；只作为 Agent loop、Tool Schema、Permission/Hook、Dry-run 和 Memory/Resume 的设计参考 |
| DeerFlow 是否作为 runtime 依赖 | 否；只借鉴 progressive discovery、task lifecycle、durable context 和受限 memory 机制 |
| Durable Runtime Store 何时选型 | 不阻塞本地 S2；共享 S3、长审批、multi-worker / HA 或非 sandbox WRITE 前成为硬门禁 |
| UserPreferenceMemory 何时试点 | 身份、tenant、retention、查看/更正/删除和审计契约成熟后；不进入 S2/S3 |
| 首个多能力组合场景 | 已确认“物料库存 + 采购订单供给概览”；先 dry-run，再只读执行，不输出缺货预测或采购数量 |

---

## 12. 进入 S2 Planner Dry-run 设计前的验收清单

开始 `sap-nexus-planner-dry-run` 正式 design 前确认：

- 本文档、`docs/wiki/sap-nexus-agent-openharness-semantic-orchestration.md` 和 `docs/wiki/sap-nexus-agent-deerflow-adoption-analysis.md` 作为技术基线已被接受。
- 当前 OpenSpec state 已检查；S1 已实现、验证并归档到 `openspec/changes/archive/2026-07-19-sap-nexus-semantic-planning-foundation/`。
- Registry、Gateway、Eval、第二条 Read capability 和 sandbox write vertical slice 已完成并保持现有验证基线。
- 首个场景固定为“物料库存 + 采购订单供给概览”。
- S1 Fact Type、Capability Relation、GoalSpec、PlanGraph、Registry Snapshot、immutable graph 和 deterministic validator 已实现并验证。
- S2 只设计/实现 progressive `CapabilityCard` discovery、GoalSpec/PlanDraft candidate、deterministic PlanCompiler 和 dry-run evidence；不执行 Gateway / SAP。
- Read-only Composition Pilot 保持为 S3 独立 change，不与 S2 混写。
- OpenHarness 不成为 runtime 依赖，不新增第二 Agent loop 或第二执行权威。
- DeerFlow 不成为 runtime 依赖；S2 只借鉴 `CapabilityCard` progressive disclosure，S3 只借鉴 PlanGraph-governed task lifecycle。
- Summary、Memory、Tool Call 和 sub-agent output 均不是 PlanGraph、Approval 或 Evidence 权威。
- 本地 S2 不引入 durable store；但共享 S3、长审批或非 sandbox WRITE 前必须完成 trusted identity、durable Run/Approval 和真实增量 SSE 门禁。
- 不会实现任意 RFC/OData/ADT/REST/SQL 执行入口、自动本体发布、Write composition、KG runtime 或 Graph Registry backend。

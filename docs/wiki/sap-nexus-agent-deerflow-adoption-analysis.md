# SAP Nexus Agent DeerFlow 借鉴与复用决策

## 文档版本

| 字段 | 内容 |
|---|---|
| 文档名称 | `SAP Nexus Agent DeerFlow 借鉴与复用决策` |
| 当前版本 | `v0.1.6` |
| 状态 | `Decision Baseline` |
| 创建日期 | `2026-07-23` |
| 最近更新 | `2026-08-05` |
| 维护目录 | `docs/wiki/` |
| 文档定位 | 基于 DeerFlow 2.1.0 源码评估 SAP Nexus Agent 可借鉴机制、不可复用边界与触发式实施路线 |
| 关联技术架构 | `docs/wiki/sap-nexus-agent-technical-architecture.md` |
| 关联技术选型 | `docs/wiki/sap-nexus-agent-technology-selection.md` |
| 关联实施路线 | `docs/wiki/sap-nexus-agent-implementation-roadmap.md` |
| 关联语义编排路线 | `docs/wiki/sap-nexus-agent-openharness-semantic-orchestration.md` |
| 关联 Runbook | 当前 `docs/runbooks/21-read-to-write-action-governance.md`；历史 `docs/runbooks/10-capability-composition-contract.md` |

## 版本记录

| 版本 | 日期 | 变更摘要 | 决策状态 |
|---|---|---|---|
| `v0.1.6` | `2026-08-05` | 同步 Runbooks 13-20 已归档及当前 Runbook 21 入口；DeerFlow 仍只提供 progressive discovery、task lifecycle、durable context 和受限 memory 参考，不成为第二 runtime | 当前决策基线 |
| `v0.1.5` | `2026-08-05` | 同步 Runbooks 13-19 已归档及当前 Runbook 20 入口；DeerFlow 仍只提供 progressive discovery、task lifecycle、durable context 和受限 memory 参考，不成为第二 runtime | 当前决策基线 |
| `v0.1.4` | `2026-08-05` | 同步 Runbooks 13-17 已归档及当前 Runbook 18 入口；DeerFlow 仍只提供 progressive discovery、task lifecycle、durable context 和受限 memory 参考，不成为第二 runtime | 当前决策基线 |
| `v0.1.3` | `2026-08-03` | 同步 S2-A/S2-B/P0B 已归档事实和 Runbooks 13-22 当前路线；DeerFlow progressive discovery 与 task lifecycle 仍只作为后续 Runbooks 的机制参考，不再指向已完成的 planner-dry-run change | 当前决策基线 |
| `v0.1.2` | `2026-07-24` | 校准 DeerFlow progressive discovery 的落点：S2-A 先补齐 SAP Nexus 自有五态 `MatchDecision`、多意图/歧义、visibility 和 matcher Eval，S2-B 再借鉴 metadata-first `CapabilityCard`；明确 DeerFlow Tool/Skill 发现不能替代基础语义决策，也不触发 SAP 执行 | 当前决策基线 |
| `v0.1.1` | `2026-07-24` | 基于三方综合复盘把 durable runtime 从泛化触发式候选收敛为条件门禁：不阻塞本地 S2，但在共享 S3、长审批、multi-worker/HA 或非 sandbox WRITE 前必须完成 trusted identity、durable Run/Approval、ownership/lease 和真实增量 SSE；补充 deterministic OutputProjection 边界 | 当前决策基线 |
| `v0.1.0` | `2026-07-23` | 完成 DeerFlow 2.1.0 源码级对比，覆盖意图识别、能力组合、长对话、记忆、运行时、安全与许可；确认不直接引入第二 Agent runtime，只按阶段吸收候选发现、受治理调度、durable context 和受限用户记忆机制 | 当前决策基线 |

---

## 1. 结论先行

DeerFlow 值得深入借鉴，但不适合作为 SAP Nexus Agent 的新运行内核整体复用。

DeerFlow 解决的是通用 Super Agent Harness 问题：

```text
model-driven tool loop
+ progressive skills / tools
+ sandbox
+ sub-agents
+ thread / run / checkpoint
+ summarization / memory
+ full-stack workspace
```

SAP Nexus Agent 解决的是受治理的企业业务能力规划与执行问题：

```text
Natural Language
-> GoalSpec / Intent candidate
-> closed-set Capability Discovery
-> deterministic MatchDecision / PlanCompiler
-> CallPlan / PlanGraph
-> Policy / Approval
-> capabilityId -> bindingId
-> SAP Execution Gateway
-> ExecutionResult -> ReasoningFact -> Audit / Eval
```

两者的关键差异不是框架或编程语言，而是谁拥有执行权：

- DeerFlow 默认由模型在可见 Tool 集合中决定下一次 Tool Call。
- SAP Nexus 只允许模型提出候选理解或计划，确定性 Harness 才能授予执行权。
- DeerFlow 的 messages、summary、memory 和 checkpoint 是通用 Agent 上下文。
- SAP Nexus 的 `RegistrySnapshot`、`PlanGraph`、`ApprovalRecord`、`ExecutionResult` 和 `ReasoningFact` 是业务执行与回放权威。

因此本项目采用以下总决策：

1. 不新增 DeerFlow runtime、Gateway、frontend 或 `deerflow-harness` 生产依赖。
2. 不把每个 SAP capability、RFC、OData endpoint 或 executor 暴露成模型可自由调用的 DeerFlow Tool。
3. 吸收 DeerFlow 的渐进式候选发现、受限并发任务生命周期、durable thread/run、上下文压缩和受限记忆设计。
4. 将借鉴机制映射进现有 S2-B Planner Dry-run、S3 Read-only Composition Pilot 和后续产品化 workstream；S2-A 先补齐 SAP Nexus 自有基础语义决策，不改变 P0A 后由 S2 作为下一业务 change。
5. 保持 Capability Registry、PlanCompiler、Approval Guard、SAP Execution Gateway、Evidence 和 Eval Harness 为唯一执行与质量权威。

---

## 2. 对比证据范围

### 2.1 DeerFlow 快照

本次分析基于：

| 项目 | 值 |
|---|---|
| Repository | `https://github.com/bytedance/deer-flow.git` |
| Branch | `main` |
| Commit | `62dd8d2b67179928490c4cc16048b1c4759154a8` |
| Version | `2.1.0` |
| Python | `>=3.12` |
| License | MIT |

重点源码证据：

| 主题 | DeerFlow 文件 |
|---|---|
| Harness / app split | `AGENTS.md`、`backend/AGENTS.md` |
| Agent factory | `backend/packages/harness/deerflow/agents/factory.py` |
| Lead agent assembly | `backend/packages/harness/deerflow/agents/lead_agent/agent.py` |
| Skill progressive disclosure | `backend/packages/harness/deerflow/skills/describe.py`、`skills/catalog.py` |
| Deferred Tool discovery | `backend/packages/harness/deerflow/tools/builtins/tool_search.py` |
| MCP routing | `backend/packages/harness/deerflow/agents/middlewares/mcp_routing_middleware.py` |
| Sub-agent task lifecycle | `backend/packages/harness/deerflow/tools/builtins/task_tool.py`、`subagents/executor.py` |
| Thread / run / SSE | `backend/app/gateway/routers/thread_runs.py`、`routers/threads.py` |
| Checkpoint compatibility | `backend/packages/harness/deerflow/runtime/checkpoint_mode.py` |
| Context summarization | `backend/packages/harness/deerflow/agents/middlewares/summarization_middleware.py` |
| Durable context | `backend/packages/harness/deerflow/agents/middlewares/durable_context_middleware.py` |
| Memory abstraction | `backend/packages/harness/deerflow/agents/memory/manager.py`、`config/memory_config.py` |
| Default memory backend | `backend/packages/harness/deerflow/agents/memory/backends/deermem/deer_mem.py` |
| Authorization | `backend/packages/harness/deerflow/authz/`、`config/authorization_config.py` |

### 2.2 SAP Nexus Agent 历史对比快照

以下是本次对比时点（`2026-07-23`，commit `a24842ff6cb90402e047602f6e828e6f23a7803d`）的历史事实，不作为当前实施状态入口：

- Branch：`main`。
- Commit：`a24842ff6cb90402e047602f6e828e6f23a7803d`。
- Active capability：2 个 Read Function + 1 个 sandbox-governed Action。
- S1 Semantic Planning Foundation 已实现、验证并归档。
- 当时 P0A 是前置收敛、S2 是下一业务 design；它们现已完成并归档。
- 当时 S3 Read-only Composition Pilot 尚未实现；现已拆分为 Runbooks 13-19。
- Dynamic Planner 和 Write composition 仍是 Phase 3+ / Reserved。
- 当时 Workbench 使用进程内 run store；P0B 后已升级为本地 durable baseline，但仍不是 durable multi-worker runtime。

当前状态与下一入口统一见 `docs/runbooks/README.md` 和 `docs/runbooks/18-recommendation-decision-plan.md`。

本次文档只形成架构和路线决策，不声称 DeerFlow 与 SAP Nexus 已完成运行时集成或兼容性验证。

---

## 3. 核心领域模型对照

| DeerFlow 对象 | DeerFlow 职责 | SAP Nexus 对应对象 | 复用判断 |
|---|---|---|---|
| Thread | 保存对话和 Agent state | Conversation / Session | 可借鉴持久化机制 |
| Run | 单次 Agent invocation 生命周期 | Agent Run / Plan Run | 需增加 SAP 领域状态映射 |
| Tool | 模型可见并可调用的动作 | Capability candidate / meta-tool | 不能直接等同于执行能力 |
| Skill | 按需加载的流程与知识 | Domain guidance / capability card | 只作知识和候选说明 |
| Task / Sub-agent | 模型委派的并行任务 | PlanNode executor / offline critic | 只借鉴调度机制 |
| Checkpoint | LangGraph state 快照 | Conversation checkpoint + structured state references | 需拆分权威边界 |
| Summary | 压缩历史上下文 | ConversationSummary | 只能是 advisory data |
| Memory | 跨 thread 的用户/Agent facts | UserPreferenceMemory | 必须受数据治理限制 |
| Human input | 澄清或风险确认 | Clarification / Approval | 不能替代 ApprovalRecord |
| Gateway API | Agent runtime 和 workspace API | Workbench Runtime API | 不能替代 SAP Execution Gateway |

命名上必须避免把两个 Gateway 混为一谈：

```text
Agent Platform API / Workbench Runtime
!=
SAP Execution Gateway
```

---

## 4. 意图识别与候选能力发现

### 4.1 DeerFlow 的真实机制

DeerFlow 2.1.0 没有独立的、面向业务能力闭集的 deterministic intent classifier，也没有与 SAP Nexus `IntentParseResult` / `MatchDecision` 等价的领域对象。

其默认识别和路由主要依靠：

1. Lead model 阅读 system prompt、Tool schema 和 Skill metadata。
2. 模型按任务语义选择直接 Tool Call、`describe_skill` 或 `tool_search`。
3. Skill 使用 metadata-first、full-content-later 的渐进式加载。
4. MCP Tool 可以携带 keyword / priority routing hint，并在命中后自动提升 schema 可见性。
5. 用户以 `/skill-name` 开头时，Skill activation middleware 确定性加载指定 Skill。
6. Deferred Tool search 当前主要按名称、描述、正则和 routing keyword 匹配，不是领域关系图 Planner。

这套机制擅长控制上下文大小和提高通用 Tool/Skill 可发现性，但最终 Tool 选择仍然是模型驱动的。

### 4.2 对 SAP Nexus 的借鉴价值

高价值机制：

- **Progressive disclosure**：第一阶段只给模型 capability card，不注入完整参数 schema、binding 或技术细节。
- **Deferred candidate discovery**：能力规模增大后，先搜索小候选集合，再让 LLM 在候选内做解释和澄清。
- **Explicit user override**：允许用户显式选择业务能力或目标类型，但显式选择仍需 governance 和参数校验。
- **Metadata cache**：按 Registry Snapshot 缓存候选卡片，避免每轮重复加载全部能力描述。
- **Fail-closed visibility**：权限或环境不允许的 capability 在进入模型候选集合前即被过滤。

推荐目标流：

```text
Natural Language
-> deterministic governance pre-filter
-> Registry / relation graph candidate discovery
-> progressive capability cards
-> optional LLM rerank / explanation / clarification candidate
-> deterministic MatchDecision
-> GoalSpec / PlanDraft candidate
```

明确拒绝：

- 不把 Tool name/description regex 当作最终 capability matcher。
- 不让 LLM 通过 `tool_search` 获得一个 SAP executor 的直接执行权。
- 不把 Skill activation 当作 capability publish 或 approval。
- 不向模型展示 `rfcName`、service URL、raw SQL、credential 或完整 executor binding。

### 4.3 路线映射

DeerFlow 的候选发现经验折叠进现有 S2，但不能替代 SAP Nexus 自有的基础语义决策：

- S2-A 先实现五态 `MatchDecision`、multi-intent / ambiguity、visibility pre-filter 和 matcher Eval，不依赖 DeerFlow Tool/Skill runtime。
- S2-B 再设计 `CapabilityCard` / `CandidateCapability` 的最小安全投影和 progressive discovery。
- S2-B 的候选发现输出只进入 `PlanDraft`，不执行 Gateway。
- 规模较小时继续使用规则 + Registry / relation graph；只有 Eval 证明需要时才引入更复杂 retrieval / rerank。
- DeerFlow 不成为 S2 依赖。

---

## 5. 能力组合与并行调用

### 5.1 DeerFlow 的真实机制

DeerFlow 的组合主要是模型驱动的 task orchestration：

```text
Lead Agent
-> decompose
-> parallel task() calls
-> isolated sub-agent contexts
-> poll / status / timeout / cancel
-> structured task result
-> synthesize
```

它提供了成熟的执行生命周期机制：

- 单轮并发上限和单 run 总 sub-agent 上限。
- timeout、最大轮次、token budget 和 loop detection。
- background task status、cancel 和 terminal state cleanup。
- sub-agent 隔离上下文。
- delegation ledger 和结果摘要。
- 并行结果汇总和 trace 关联。

但它不提供 SAP Nexus 所需的：

- Fact Type 输入输出类型匹配。
- Capability Relation 依赖图。
- Registry Snapshot 绑定。
- deterministic topological sort。
- side effect / approval / transaction-aware scheduling。
- 逐节点 evidence lineage。
- Write compensation / partial failure policy。

因此 DeerFlow task graph 不能替代 `PlanGraph`。

### 5.2 对 SAP Nexus 的借鉴价值

可以借鉴到未来 `PlanExecutor` 的机制：

| DeerFlow 机制 | SAP Nexus 适配 |
|---|---|
| max concurrent tasks | 每个 PlanGraph / tenant / executor family 的并发上限 |
| max total tasks | PlanGraph 最大节点数与动态 repair 上限 |
| task status | `PlanNodeStatus` 标准状态机 |
| timeout | capability / binding / node 级 timeout policy |
| cancel | 未开始节点取消和运行中 connector cancellation contract |
| isolated context | 节点只接收已绑定参数和允许读取的 upstream Fact |
| delegation ledger | checkpointed node execution ledger |
| structured result | `ExecutionResult` / `ReasoningFact`，而非自由文本 task result |
| trace propagation | plan / node / agent / gateway trace correlation |

推荐执行规则：

```text
PlanGraph validated
-> select ready nodes
-> require sideEffect=none for parallel execution
-> require no dependency edge between parallel nodes
-> apply concurrency / timeout / cancellation policy
-> each node calls existing Gateway validate -> execute
-> normalize ExecutionResult -> ReasoningFact
-> update node ledger and fact lineage
```

明确拒绝：

- 不让 Lead Agent 临时决定两个 SAP capabilities 是否可以并行。
- 不把多个 Tool Call 出现在同一模型 response 视为合法 PlanGraph。
- 不并行执行 Write、事务节点或存在依赖边的节点。
- 不允许 sub-agent 持有 SAP credential、approval token 或 connector binding。
- 不允许一个 composite approval 覆盖参数不同的多个 Write 节点。

### 5.3 路线映射

- S2-B 只产生和校验 Dry-run，不使用 DeerFlow task executor；S2-A 也不引入 DeerFlow Tool/Skill runtime。
- S3 Read-only Composition Pilot 可借鉴 ready-node scheduler、并发上限、timeout、cancel、ledger 和 trace 机制。
- Dynamic Planner 仍保持 Phase 3+ / Reserved。
- Write composition 在 partial failure、transaction 和 compensation contract 明确前不进入 runtime。

---

## 6. 长对话、上下文压缩与任务恢复

### 6.1 DeerFlow 的真实机制

DeerFlow 在长对话和 durable run 方面比 SAP Nexus 当前 Workbench MVP 更成熟：

- Thread、Run 和 checkpoint 持久化。
- full / delta checkpoint channel mode 与 fail-closed compatibility gate。
- background run、wait、cancel、regenerate、branch 和 resume。
- 与 LangGraph SDK 对齐的持续 SSE stream。
- 自动 summarization 和手工 `/compact`。
- 压缩前保留近期 messages，历史转换为 `summary_text`。
- Durable Context 将 summary、delegation ledger 和已加载 Skill context 独立保存。
- 历史数据重新注入模型时标记为不可信 data，避免其获得 system authority。
- memory flush hook 在消息被 compaction 移除前处理长期记忆更新。

这些机制对长周期 SAP 诊断、Planner Dry-run、审批等待和多能力执行具有明显参考价值。

### 6.2 SAP Nexus 必须增加的状态分层

长对话不能把所有状态都塞进 messages 或 summary。推荐分为三层：

| 状态层 | 示例 | 是否可摘要 | 权威性 |
|---|---|---|---|
| `ConversationState` | 用户问题、澄清、可见叙事、对话摘要 | 可以 | advisory context |
| `PlanExecutionState` | GoalSpec、RegistrySnapshot、PlanGraph、node ledger、ApprovalRecord 引用 | 不可以 | execution authority |
| `EvidenceState` | ExecutionResult、ReasoningFact、ActionResult、trace / lineage | 不可以 | evidence / audit authority |

必须满足：

- Summary 只能压缩自然语言历史，不能改写结构化计划、审批或事实。
- Resume 必须重新加载原始 `RegistrySnapshot`；不能静默升级到最新 Registry。
- Approval waiting 必须持久化 server-owned context，不能依赖浏览器或 LLM 重建。
- Replay 必须引用原始 plan、node ledger、results 和 trace，而不是重新运行 prompt。
- Durable context 中的历史文本必须按不可信数据处理，不能覆盖当前 policy。
- Context compaction 失败不应破坏 run；应保留原 checkpoint 并显式记录降级。

### 6.3 借鉴优先级

| 机制 | 价值 | 当前处理 |
|---|---|---|
| Durable thread/run store | 高 | 产品化前候选 enabling workstream |
| Real SSE + reconnect | 高 | Workbench runtime hardening 候选 |
| Structured checkpoint | 高 | Plan / approval / evidence 必须独立设计 |
| Automatic summarization | 中 | 可用于 ConversationState，不进入执行权威 |
| Manual compaction | 中 | 可作为高级用户功能，非近期主线 |
| Branch / regenerate | 中低 | 只允许对话分支；不得复制有效 approval 执行权 |
| Full / delta checkpoint | 中低 | 容量证据出现后再选型，不提前引入复杂度 |

Durable runtime 目前不取代 S2。是否在 S3 后、生产试点前建立独立 workstream，由以下证据触发：

- run 需要跨进程或跨重启恢复。
- 审批等待超过单进程生命周期。
- multi-worker / HA Workbench 成为部署要求。
- 单次组合执行产生足以压迫当前内存 store 的事件量。
- Eval 或现场问题证明断线、重启或并发会丢失运行证据。

---

## 7. 长期记忆

### 7.1 DeerFlow 的真实机制

DeerFlow memory 与 thread checkpoint 是两个不同概念：

- Checkpoint 保存当前 thread 的 Agent state。
- Memory 保存跨 thread、按 user / agent 作用域组织的长期 facts。

DeerFlow memory 支持：

- `middleware` 模式：每轮后被动提取和更新记忆。
- `tool` 模式：模型显式调用 `memory_search`、`memory_add`、`memory_update`、`memory_delete`。
- 可插拔 `MemoryManager` backend。
- 默认 DeerMem：文件持久化、debounced LLM extraction、correction / reinforcement detection。
- user / agent scope。
- memory injection token budget。
- category、confidence、staleness、consolidation 和管理接口。
- graceful shutdown flush。

当前默认 DeerMem 的 fallback search 仍主要是 substring + confidence 排序；它为未来 hybrid retrieval 预留接口，但不应被视为成熟的企业知识检索或主数据服务。

### 7.2 SAP Nexus 记忆分类

SAP Nexus 需要先区分四类数据，不能统称为 Memory：

| 数据类型 | 示例 | 推荐存储 | 能否影响执行 |
|---|---|---|---|
| User preference | 语言、单位显示、常用解释深度 | Governed UserPreferenceMemory | 只能影响展示和候选默认值 |
| Conversation context | 本 thread 已澄清范围、自然语言摘要 | Thread checkpoint | 只能作为候选上下文 |
| Business fact | SAP 库存、采购订单、主数据 | Evidence / fact store，带时效和 lineage | 只能经 freshness / authority 校验后使用 |
| Execution authority | PlanGraph、ApprovalRecord、binding、policy | 专用 authoritative store | 是，禁止写入通用 Memory |

### 7.3 第一阶段允许和禁止的记忆

允许作为后续 pilot 的内容：

- 用户界面语言和叙事风格。
- 用户确认的单位显示偏好。
- 用户主动保存的业务术语或别名。
- 常用但非敏感的筛选展示偏好。
- 用户对解释深度、表格或摘要形式的偏好。

默认禁止进入通用记忆：

- SAP username、password、token、cookie、destination credential。
- approval token、approvalId 可执行上下文或参数快照。
- 原始 SAP RETURN 中的敏感字段。
- 未经过事实层持久化的库存、采购订单或主数据值。
- capability publish、binding、governance 或 permission decision。
- 用户无明确授权的个人数据、组织数据和跨租户数据。
- 从模型推断但用户未确认的权限、岗位、业务责任或审批偏好。

### 7.4 推荐治理规则

SAP Nexus 初期不采用模型自主 `memory_add/update/delete` 模式。推荐：

```text
explicit user save / controlled extraction candidate
-> schema validation
-> sensitive-data filter
-> tenant + user scope
-> provenance + timestamp + confidence
-> optional human confirmation
-> durable preference store
```

读取时：

```text
preference candidates
-> scope / retention / confidence filter
-> inject as untrusted advisory context
-> deterministic policy decides whether field may become a default
-> required business parameters still require current validation
```

还必须具备：

- 用户可查看、导出、更正和删除记忆。
- 明确 retention 和过期策略。
- tenant / user / agent 三层隔离。
- 记录来源、创建时间、最后确认时间和置信度。
- Memory backend 不可用时 fail-soft，不得阻止受控查询，也不得退化为跨用户共享。
- Memory 不能改变 capability 可见性、approval requirement 或 side effect classification。

### 7.5 路线映射

Governed User Memory 不进入当前 S2/S3 主线。只有以下前提满足后才考虑独立 pilot：

- 企业身份、tenant 和 user scope 已稳定。
- 数据分类、retention、删除和审计要求已明确。
- Preference schema 与 Evidence / authority store 已明确分离。
- Eval 证明跨会话偏好能产生可衡量收益。

---

## 8. 其他可借鉴机制

### 8.1 Runtime middleware

可借鉴：

- input sanitization。
- dangling tool-call recovery。
- loop detection。
- token / output budget。
- tool error normalization。
- pre/post execution audit hook。
- trace correlation。
- terminal response guard。

SAP 适配时，这些 middleware 只能保护模型循环和 runtime plumbing；schema、governance、approval 和 Gateway validation 仍是确定性门禁。

### 8.2 Skills / MCP

可用于：

- SAP 领域规则说明。
- capability 使用示例。
- Eval 指南。
- 业务术语解释。
- 离线 capability / Fact Type / relation draft。

不可用于：

- 自动发布 capability。
- 自动创建 executor binding。
- 直接暴露 SAP technical endpoint。
- 绕过 Registry Snapshot 或 Approval Guard。

### 8.3 Sandbox

DeerFlow sandbox 适合文件处理、报告生成、代码和离线分析。SAP Nexus 可在未来使用隔离 sandbox 承担非权威工作，但必须满足：

- sandbox 不保存 SAP credential。
- sandbox 不直接访问 SAP Execution Gateway 的内部接口。
- sandbox 不持有 approval token。
- sandbox 输出必须经过 schema / sensitive-data / evidence gate 后才能进入业务结果。

### 8.4 Authentication / Authorization

DeerFlow 已提供 route auth、owner check、tool visibility filter 和 execution-time authorization provider，但 fine-grained authorization 默认关闭，其 README 仍建议部署在本地可信网络。

因此：

- 可以借鉴 assembly-time visibility + execution-time deny 的双层模式。
- 不能把 DeerFlow RBAC 直接视为 SAP 企业权限、组织范围或业务数据权限。
- SAP principal、tenant、business role 和 approval actor 必须来自受信身份上下文。
- authorization provider error 必须 fail-closed，但查询界面可提供无敏感信息的解释。

---

## 9. 采纳决策矩阵

| DeerFlow 机制 | 价值 | 决策 | SAP Nexus 落点 | 当前优先级 |
|---|---:|---|---|---|
| Tool / Skill progressive disclosure | 高 | `ADAPT` | S2 candidate discovery | 近期设计输入 |
| Explicit slash activation | 中 | `ADAPT` | 显式目标/能力选择，仍需校验 | Later UX |
| Tool search | 中 | `ADAPT` | Registry candidate search，不授予执行权 | Phase 3 evidence-driven |
| MCP routing hints | 中 | `ADAPT` | CapabilityCard keyword / priority metadata | S2 可评估 |
| Model-driven Tool selection | 低/高风险 | `REJECT` | 无 | 禁止 |
| Parallel task lifecycle | 高 | `ADAPT` | S3 PlanExecutor scheduler | Planned Pilot |
| Sub-agent result synthesis | 中 | `DEFER` | Offline critic / evaluator | Later |
| Dynamic sub-agent SAP execution | 高风险 | `REJECT` | 无 | 禁止 |
| Thread / run persistence | 高 | `ADAPT` | Trusted/durable runtime foundation | 本地 S2 后置；共享 S3/长审批/非 sandbox WRITE 前门禁 |
| Resumable SSE | 高 | `ADAPT` | Agent Runtime Adapter | 同上；当前 buffered SSE-format 不算完成 |
| Checkpoint compatibility gate | 高 | `ADAPT` | Structured state version gate | Productization |
| Conversation summarization | 中 | `ADAPT` | ConversationState only | Later |
| Durable context ledger | 高 | `ADAPT` | Plan node ledger / skill context | S3 + runtime hardening |
| User / agent scoped memory | 中 | `DEFER` | Governed preference memory | Later pilot |
| Model-directed memory writes | 高风险 | `REJECT_NOW` | 无 | 禁止到治理成熟 |
| Sandbox | 中 | `DEFER` | Offline artifact work | Later |
| DeerFlow authz | 中 | `REFERENCE` | Enterprise authz adapter design | Productization |
| DeerFlow frontend | 中 | `REFERENCE` | Thread/run UX components | 不整体替换 |
| DeerFlow runtime dependency | 低 | `REJECT_NOW` | 无 | 不增加依赖 |

---

## 10. 推荐目标架构

```text
┌─────────────────────────────────────────────────────────────┐
│ Workbench / Agent Platform Layer                            │
│                                                             │
│ ConversationState                                           │
│ Thread / Run / SSE / Checkpoint / Context Compaction        │
│ Governed UserPreferenceMemory                               │
│                                                             │
│ DeerFlow provides design references, not runtime authority   │
└────────────────────────────┬────────────────────────────────┘
                             │ query / GoalSpec candidate
                             v
┌─────────────────────────────────────────────────────────────┐
│ SAP Nexus Semantic Planning Control Plane                   │
│                                                             │
│ Governance pre-filter                                       │
│ -> CapabilityCard progressive discovery                     │
│ -> GoalSpec / PlanDraft candidate                           │
│ -> deterministic PlanCompiler / Policy                      │
│ -> PlanGraph bound to RegistrySnapshot                      │
│ -> PlanNode scheduler                                       │
└────────────────────────────┬────────────────────────────────┘
                             │ capabilityId + governed params
                             v
┌─────────────────────────────────────────────────────────────┐
│ SAP Execution and Evidence Plane                            │
│                                                             │
│ Gateway validate / Approval Guard / execute                 │
│ -> bindingId -> JCO_RFC / ODATA / future controlled adapter │
│ -> ExecutionResult / ActionResult                           │
│ -> ReasoningFact / lineage / trace / Eval                   │
└─────────────────────────────────────────────────────────────┘
```

架构不变量：

- Conversation layer 可以被压缩、分支和恢复，但不能签发执行权。
- Semantic Planning layer 只能引用已发布 capability / Fact Type / relation。
- Execution layer 只接受受控 `capabilityId` 和参数，不接受 request-owned technical override。
- Memory、Skill、summary 和 sub-agent output 都是候选数据，不是 policy 或 evidence。
- Write Action 继续逐节点审批、参数快照绑定和一次性执行。

---

## 11. 分阶段路线

### D0：DeerFlow 决策基线

状态：本次文档工作。

交付：

- 独立 DeerFlow adoption analysis。
- 技术架构、技术选型、实施路线和 runbook 的精简决策同步。
- 不增加 runtime 依赖，不修改代码、schema、Registry 或配置。

### D1：S2 Semantic Decision + Progressive Capability Discovery

状态：已折叠进并完成于 `sap-nexus-planner-dry-run`；后续召回契约由 Runbook 14 继续演进。

可吸收：

- S2-A 先完成 SAP Nexus 自有五态 MatchDecision、多意图/歧义、visibility 和 Eval 门禁。
- CapabilityCard progressive disclosure。
- 小候选集合 discovery。
- explicit candidate selection。
- candidate metadata cache / snapshot binding。

仍不执行 Gateway / SAP。

### D2：S3 Governed PlanExecutor

状态：折叠进后续 Read-only Composition Pilot。

可吸收：

- ready-node queue。
- constrained parallelism。
- timeout / cancel / retry policy。
- node ledger / trace correlation。
- partial Read failure 显式状态。
- deterministic OutputProjection、freshness、completeness、limitations 和 lineage。

只允许 `sideEffect=none` 的 active Function。

### D3：Trusted Durable Agent Runtime Foundation

状态：P0B 四项基础已完成并归档。Runbooks 13-22 直接复用；multi-worker / HA 量产 store 仍为后续部署选型。

触发后可建立独立 change，例如：

```text
sap-nexus-trusted-durable-runtime-foundation
```

范围候选：

- persistent thread / run store。
- server-owned principal / tenant / role / data scope / ApprovalActor。
- real incremental SSE、event cursor、reconnect 和 replay。
- structured checkpoint references。
- approval-wait resume。
- run ownership / lease、multi-worker concurrency control 和幂等 continuation。

不包含 DeerFlow lead agent、MCP runtime 或自由 Tool execution。

### D4：Governed User Memory Pilot

状态：`Later / Triggered`。

触发前提见 §7.5。首个 pilot 只覆盖明确用户偏好，不保存业务事实或执行权威。

---

## 12. 可选 PoC 边界

若未来需要验证 DeerFlow 代码级复用，PoC 必须隔离进行，不直接改写当前主 runtime：

```text
DeerFlow-compatible thread/run shell
-> SAPNexusRuntimeAdapter
-> existing SAP Nexus query / plan / approval APIs
-> existing SAP Execution Gateway
```

PoC 约束：

1. 默认 bash、MCP、sub-agent SAP access、skill evolution 和 model-directed memory writes 全部关闭。
2. Adapter 只接收自然语言 query 或 `GoalSpec` candidate，不接收 `rfcName`、binding、URL 或 raw payload。
3. Capability selection、PlanCompiler、Approval 和 Gateway execution 仍在 SAP Nexus 内部。
4. Approval 使用独立 server-owned endpoint，不由 Tool result 自动继续。
5. Checkpoint 只保存权威对象引用和版本，不把 summary 当作恢复依据。
6. 所有事件保留 plan / node / agent / gateway trace correlation。

验收条件：

- raw `rfcName` 请求继续被拒绝。
- 缺参只进入 clarification，不调用 SAP。
- Read 输出与当前 `ExecutionResult` / `ReasoningFact` 一致。
- Action 在审批前绝不执行。
- 参数变更、过期 approval 和 replay 均被拒绝。
- 服务重启后 pending approval 和 run 可以恢复。
- 并发 run 不共享 checkpoint、用户记忆或 approval context。
- context compaction 不改变 PlanGraph、ApprovalRecord 或 EvidenceState。

只有 PoC 同时证明收益大于 adapter 和维护成本，才重新评估是否引入部分 DeerFlow package。PoC 失败或需要大面积改写 DeerFlow state / middleware / frontend 时，保留设计借鉴，不引入代码依赖。

---

## 13. 安全、许可与运维边界

### 13.1 安全

DeerFlow README 明确其默认面向本机可信环境。SAP Nexus 面向企业 SAP 系统，必须采用更严格边界：

- Agent Platform 与 SAP Execution Gateway 网络隔离。
- SAP credential 只存在于 connector / destination 层。
- 所有 user / tenant identity 来自受信 server context。
- Tool、Skill、summary、memory 和 uploaded content 均按不可信输入处理。
- Runtime extension 默认关闭，按 allowlist 和签名/评审后启用。
- 任何 provider / policy error 对执行权限 fail-closed。

### 13.2 许可

DeerFlow 使用 MIT License。未来若复制或修改 DeerFlow 代码：

- 保留版权和 MIT license notice。
- 在第三方组件清单中记录来源 commit 和修改范围。
- 不把 DeerFlow MIT License 与 SAP JCo 等专有组件的分发权混为一谈。

当前 SAP Nexus 仓库尚无项目根 `LICENSE`。在任何公开发布或二次分发前，必须单独确认项目许可证、SAP JCo binary、SAP SDK、连接信息和示例数据边界。

### 13.3 运维

- 不因为 DeerFlow 支持 SQLite/Postgres/Redis 就提前引入全部基础设施。
- 单进程 local pilot 保持当前最小形态。
- 本地 S2 不选择 durable store；共享 S3、multi-worker/HA、长审批、断线恢复或非 sandbox WRITE 成为范围后，先完成 trusted/durable runtime contract，再选择 store / stream bridge。
- 每次 runtime 状态模型升级都需要 version marker、migration 和 fail-closed compatibility gate。

---

## 14. 当前决策状态

| 决策 | 状态 |
|---|---|
| DeerFlow 作为独立架构参考 | 已确认 |
| 直接采用 DeerFlow runtime | 拒绝 |
| 新增 DeerFlow production dependency | 拒绝 |
| Baseline five-state MatchDecision | SAP Nexus S2-A 已完成并归档；不由 DeerFlow Tool/Skill selection 替代 |
| Progressive capability disclosure | 已采纳为 S2-B 基线；Runbook 14 受治理 recall 已实现并归档 |
| DeerFlow Tool search 直接决定 SAP capability | 拒绝 |
| 并发任务生命周期机制 | 已采纳并在 Runbook 16 PlanExecutor 实现；不授予模型调度权 |
| DeerFlow task/sub-agent 替代 PlanGraph | 拒绝 |
| Durable thread/run/checkpoint | P0B 本地 durable 基线已完成；multi-worker/HA store 后续另行选型 |
| Conversation summary 替代权威计划或事实 | 拒绝 |
| Governed UserPreferenceMemory | 保留为 later pilot |
| 模型自主写长期记忆 | 当前拒绝 |
| 当前下一推荐 change | Runbook 21 `read-to-write-action-governance`；Runbooks 13-20 已归档 |

本决策与 OpenHarness 对比结论一致：通用 Agent Harness 的机制可以吸收，但不能引入第二执行权威。DeerFlow 补充了更成熟的 thread/run、checkpoint、context 和 memory 工程经验；SAP Nexus 继续以 Capability Registry、Semantic Planning、Approval、Gateway、Evidence 和 Eval 构成受治理业务闭环。

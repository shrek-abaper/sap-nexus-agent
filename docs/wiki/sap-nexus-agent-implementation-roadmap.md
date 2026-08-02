# SAP Nexus Agent 实施路线文档

## 文档版本

| 字段 | 内容 |
|---|---|
| 文档名称 | `SAP Nexus Agent 实施路线文档` |
| 当前版本 | `v0.2.38` |
| 状态 | `Lifecycle Roadmap Active` |
| 创建日期 | `2026-06-18` |
| 最近更新 | `2026-08-01` |
| 维护目录 | `docs/wiki/` |
| 文档定位 | SAP Nexus Agent 从 MVP 到量产交付的全生命周期实施路线 |
| 关联技术架构 | `docs/wiki/sap-nexus-agent-technical-architecture.md` |
| 关联知识导入 | `docs/wiki/archive/sap-nexus-agent-mm-mvp-notion.md` |
| 关联智能编排路线 | `docs/wiki/sap-nexus-agent-openharness-semantic-orchestration.md` |
| 关联 DeerFlow 决策 | `docs/wiki/sap-nexus-agent-deerflow-adoption-analysis.md` |

## 版本记录

| 版本 | 日期 | 变更摘要 | 决策状态 |
|---|---|---|---|
| `v0.2.41` | `2026-08-02` | P0B 项3 `sap-nexus-durable-approval-store` 实施完成并归档（依赖项2）：FileDurableApprovalStore 替换 InMemoryApprovalStore（durable ApprovalRecord 持久化 + cross-restart recoverAll/reconcile fail-closed + cross-worker claim/lease anti-replay + LeaseOutcome 三态 Claimed/Rejected/ForceClaimed + striped ReentrantLock + FileChannel.lock + atomic tmp+rename + @Primary wiring + @PostConstruct 启动恢复）；176 tests pass；主 spec 合并 `durable-approval-store`（ADDED 4 requirements）；归档 `openspec/changes/archive/2026-08-02-sap-nexus-durable-approval-store/`；项4 incremental-sse-reconnect 待续 | 当前实施基线 |
| `v0.2.40` | `2026-08-02` | P0B 项2 `sap-nexus-trusted-principal-model` 实施完成并归档（依赖项1）：TrustedPrincipal/PrincipalRole/DataScope server-owned 模型 + PrincipalInjector/LocalPlaceholderPrincipalInjector（injectPrincipal 忽略 request body，防 prompt injection 篡权）+ durable Run/Sessions 绑定 principalId（required，legacy 回填 local-user-0001）+ cross-principal fail-closed（read 返 [] / write 抛 not-found，ownership 校验先于 lease claim §4.1，getSession + conversationStore.load fail-closed）+ 4 route handler server-owned 注入（POST/approval/batch/stream）；76 tests pass；主 spec 合并 `trusted-principal-scope`（ADDED 4 requirements）+ `durable-run-state`（MODIFIED principalId 绑定 + list/load 过滤）；归档 `openspec/changes/archive/2026-08-02-sap-nexus-trusted-principal-model/`；项3 durable-approval-store 已归档（v0.2.41）/ 项4 incremental-sse-reconnect 待续 | |
| `v0.2.39` | `2026-08-02` | P0B row 22 `sap-nexus-trusted-durable-runtime-foundation` 拆分为 4 项独立 change：项1 `sap-nexus-durable-state-foundation` 实施完成并归档（durable Run/Sessions JSONL store 替换进程内 Map + run ownership/lease fail-closed + structured checkpoint reference + 幂等 continuation 三段式 key + §4.2.1 三层状态分层；单 worker durable，store 无关接口为 multi-worker 预留；57 tests pass）；项2 `sap-nexus-trusted-principal-model`（依赖项1）、项3 `sap-nexus-durable-approval-store`（依赖项2）、项4 `sap-nexus-incremental-sse-reconnect` 在 design 阶段待续；主 spec 合并 `durable-run-state`（ADDED 5 requirements）+ `conversational-context`（MODIFIED 1 requirement，process-local -> durable）；归档 `openspec/changes/archive/2026-08-02-sap-nexus-durable-state-foundation/` | 当前实施基线 |
| `v0.2.38` | `2026-08-01` | §8 LLM intent adapter 基线修正：明确 `hybrid` 以 LLM 为主路径（LLM 结果直接使用，empty/error 不再回退规则，仅 `LlmUnavailable` 回退），修正旧契约"unknown/unsupported/`rfcName` 回退规则"过时描述，对齐 spec `conversational-context`；区分意图识别层（LLM 为主）与能力匹配 / 选择层（deterministic 为权威） | 当前实施基线 |
| `v0.2.37` | `2026-08-01` | 补登 4 个已归档但未记录的 change：`sap-nexus-agent-conversational-context`（row 19A，即时多轮对话 sticky-CLARIFY + `ConversationContext` 签名 + 权威/不可信分离注入）、`sap-nexus-agent-llm-intent-enhancement`（LLM 指代理解 + 多值参数拆分）、`fix-batch-confirm-loop`（`awaiting_batch_confirm` 死循环 hotfix）、`multi-value-batch-service-integration`（`continue_batch` 全链接通 workbench/CLI/API/SSE，多值批量查询端到端可用）；row 19A 状态改已完成并归档，新增 row 19B `sap-nexus-multi-value-batch-query`；技术架构 v0.2.19 新增 §4.2.3 多值批量契约；新建 runbook 12；下一推荐 P0B trusted/durable runtime（条件门禁）或 S3 read-composition-pilot | 当前实施基线 |
| `v0.2.36` | `2026-07-25` | 新增 row 19A `sap-nexus-agent-conversational-context`（即时多轮对话）：定位为 S2 之后的轻量能力加固，先于 P0B、不阻塞 P0B、不改变 runtime 架构；仅覆盖 CLARIFY 跨轮 slot-fill，ESCALATE/SHOW_OPTIONS 跨轮与持久化为非目标；同步技术架构 §4.2.2 定义 `ConversationState` 轻量实例与权威/不可信分离注入契约 | 当前实施基线 |
| `v0.2.35` | `2026-07-25` | `sap-nexus-planner-dry-run` S2-A + S2-B 实施完成并归档：五态 `MatchDecision` + 多意图/歧义检测（修复 D-1）+ visibility pre-filter + matcher Eval 6/6 + progressive `CapabilityCard` + deterministic `PlanCompiler` dry-run（3/3 + 1 pending）；不执行 Gateway/SAP；row 19 标记 Implemented/Archived；主 spec 合并 `agent-callplan-evidence`（MODIFIED）+ `semantic-match-decision`/`planner-dry-run`（ADDED）。下一推荐 P0B `sap-nexus-trusted-durable-runtime-foundation`（S3 前硬门禁） | 当前实施基线 |
| `v0.2.34` | `2026-07-25` | P0A source-of-truth/repository hygiene 收尾：runbook index 与 11 个 runbook header 状态对齐；editable-install finder 与 .venv shebangs 从 stale `zl-projects` 重指 `GitHub_Projects`；runtime traces 确认 gitignored（`runtime/*` 仅 `.gitkeep` tracked）；row 18A 状态从 `Documentation In Progress` 改为 `Completed`。下一推荐进入 S2-A `sap-nexus-planner-dry-run` | 历史基线 |
| `v0.2.33` | `2026-07-25` | 文档收敛：row 19 验收条件可判定化（多目标 utterance 必须 `ESCALATE_TO_PLANNER`，false `SELECT` 作为回归失败项）；新增 §18 Known Correctness Defects（D-1）、§19 Stage Gate 评测三件套（P0A/S2-A/S2-B/trusted-durable gate/S3，缺口显式标注）、§20 Open Questions 与已知技术债（S1 verify report 三项债 + Q-1 能力供给规模化） | 历史基线 |
| `v0.2.32` | `2026-07-24` | 校准语义识别实施路线：明确当前 runtime 尚无完整五态 `MatchDecision` 与可靠多意图升级；将 row 19/S2 拆成 S2-A Semantic MatchDecision Hardening 和 S2-B Planner Dry-run，增加 `CapabilityCard` 安全投影、visibility pre-filter 与 matcher Eval 退出标准；row 12 继续只承担 Phase 3+ 规模化 retrieval / rerank | 当前实施基线 |
| `v0.2.31` | `2026-07-24` | 基于 OpenHarness / DeerFlow 综合复盘重排近期门禁：同步 S1 已归档；新增 P0A source-of-truth / repository hygiene；将 trusted identity、durable Run/Approval、run ownership 和真实增量 SSE 定义为共享 S3、长审批、multi-worker/HA 或非 sandbox WRITE 前的 P0B 条件硬门禁；S3 增加确定性 OutputProjection、freshness 和 incomplete 语义，S2 仍为下一业务 change | 当前实施基线 |
| `v0.2.30` | `2026-07-23` | 同步 DeerFlow 2.1.0 借鉴决策：S2 增加 progressive `CapabilityCard` discovery，S3 增加 PlanGraph-governed ready-node lifecycle；新增 durable agent runtime 与 governed user memory 触发式候选，不引入 DeerFlow 依赖且不改变当前 S2 优先级 | 当前实施基线 |
| `v0.2.29` | `2026-07-19` | 补齐 S1 durable verification audit：披露 executor-binding schema 对 authoritative `sap_write` binding 的兼容对齐、focused `2 passed`、full evidence inventory `7/7` / seed `13/13` / PR `9/9` 与 whole-branch runtime boundary；technical architecture 的 `Next Design` lifecycle 标签按 inspect-only 边界保持未改，当前 lifecycle 由 roadmap/runbook/verification report 承载 | S1 evidence correction 完成；Comet verify/archive 待用户确认 |
| `v0.2.28` | `2026-07-19` | `sap-nexus-semantic-planning-foundation` S1 contracts、immutable graph、四源 Registry Snapshot、GoalSpec/PlanGraph validator 与 combined release gate 已实现并通过 fresh verification；row 18 标记完成，下一推荐转为 row 19 `sap-nexus-planner-dry-run` design；S3 read-only execution、Dynamic Planner 与 Write composition 继续保持 planned/reserved | S1 已验证；Comet verify/archive 待用户确认 |
| `v0.2.27` | `2026-07-18` | 同步 OpenHarness 对比与语义智能编排路线：确认不引入 OpenHarness runtime；确认“物料库存 + 采购订单供给概览”为首个只读组合场景；新增 Semantic Planning Foundation、Planner Dry-run、Read-only Composition Pilot 三步近期路线，Dynamic Planner 和 Write composition 继续保持 Phase 3+ Reserved | 当前实施基线 |
| `v0.2.26` | `2026-07-17` | `sap-nexus-sandbox-write-vertical-slice` 已 fast-forward 合并到 `main`、通过 merged-main 全量验证并完成 Comet archive `7/7`；归档 change 位于 `openspec/changes/archive/2026-07-17-sap-nexus-sandbox-write-vertical-slice/`，主 spec `openspec/specs/pr-create-action/spec.md` 已生成 | 已完成并归档 |
| `v0.2.25` | `2026-07-17` | `sap-nexus-sandbox-write-vertical-slice` verify repair 通过：外部 Workbench approval、Gateway service-token authority、stored/actual/request hash、不可覆盖 approvalId、原子 claim、stateful JCo LUW、真实 commit/rollback status 与 replay-complete trace；三轮 thorough review 最终 Critical/Important 均为 0；未再次执行 SAP WRITE | 历史基线 / Merge Pending |
| `v0.2.24` | `2026-07-17` | `sap-nexus-sandbox-write-vertical-slice` verify-fail repair：Agent 首次 Action 停在 pending，Workbench approve/reject continuation 才允许 execute；Gateway WRITE trace 增加脱敏 PR/commit/SAP RETURN resultSummary；修复过程未再次执行 SAP WRITE | 历史基线 |
| `v0.2.23` | `2026-07-17` | `sap-nexus-sandbox-write-vertical-slice` 治理 `purchasing_group -> PRITEM.PUR_GROUP` 后成功创建并 commit sandbox PR `10137471`；补齐 `EXPORTS.NUMBER` 提取、Agent approval `executed` trace 与 Gateway 顶层 `ActionResult` 契约，全程未再次执行 WRITE | 当前实施基线 |
| `v0.2.22` | `2026-07-17` | `sap-nexus-sandbox-write-vertical-slice` live smoke 暴露并修复 approval 注册断层与 `BAPI_PR_CREATE` header/item/X envelope；两次 sandbox execute 均明确 rollback、无 PR；最终阻塞为受治理的 Purchasing Group 与 sandbox 采购主数据，不再继续试写 | 历史基线 |
| `v0.2.21` | `2026-07-17` | 完成 `sap-nexus-sandbox-write-vertical-slice` 首个 SAP WRITE / Approval 闭环纵切：`MM.PR.CreateDraft`（`BAPI_PR_CREATE`）注册为首个 Action capability（`sideEffect=sap_write`、`requiresApproval=true`、`approvalPolicy=human_required`）；Gateway `ApprovalGuard` 在 execute 入口 fail-closed（4 种拒绝场景），`PrCreateDraftExecutor` + commit/rollback 守卫，READ/WRITE 路径隔离；Agent approval 状态机 + Action CallPlan + 参数 snapshot hash + `ActionResult` 解析；9 个 PR eval cases；runbook 11 落地；row 10 与 §17.3 标记已完成（live smoke Task 17 待执行）；下一推荐推进到 row 11 `sap-nexus-recommendation-reasoning` | 历史基线 |
| `v0.2.20` | `2026-07-14` | 新增 `sap-nexus-capability-composition-contract`（Reserved）workstream 与 §9.7；更新 §13 图数据库触发式引入说明与 §17.4；把能力组合与关系本体固化为已设计暂不实现的 reserved 契约 | 当前实施基线 |
| `v0.2.19` | `2026-07-09` | 完成并归档 `po-odata-item-detail-filter`：SAP SICF 重新激活后 PO OData live smoke 通过，`MM.PurchaseOrder.GetList` 激活；新增 item detail 查询、material / plant item-level filtering、PO eval linkage 和回归证据；归档目录 `openspec/changes/archive/2026-07-09-po-odata-item-detail-filter/` | 已完成 |
| `v0.2.18` | `2026-07-09` | 完成 `sap-nexus-odata-gateway-read-pilot`：OData Gateway Read Pilot 提前落地（Python odata-service + Java 薄反代 + Agent 多能力路由 + 列表归一 + PO evals）；超越 §17.2 新增 ODATA executor family；§17.4 顺序调整 OData pilot 前置于 sandbox write；live ICF 403 blocker 待 Basis 解决 | 已完成 |
| `v0.2.17` | `2026-07-04` | 完成 Eval Harness seed 的直接实施：新增 seed/bad-case 数据集、runner contract 断言和验证脚本入口；下一推荐 change 转入第二条 SAP read capability | 当前实施基线 |
| `v0.2.16` | `2026-06-28` | 同步技术架构 `v0.2.8` 收敛决策：近期路线转为 Eval Harness seed、第二条 SAP read capability、sandbox write vertical slice；matching / SQL_READ / OData / CDS / REST executor workstream 降级为 Phase 3+ 或 reserved | 当前实施基线 |
| `v0.2.15` | `2026-06-28` | 补充 `sap-nexus-gateway-execution-contract` 已完成验证并归档：Gateway 技术执行契约、binding dispatcher、JCo compatibility 适配、请求所有权守卫已落地；主 spec 已生成 `openspec/specs/gateway-execution-contract/spec.md` | 已完成 |
| `v0.2.14` | `2026-06-27` | 补充 `SQL_READ` 受控 SQL 读取执行器路线：新增 `sap-nexus-sql-read-executor-contract`，明确只执行已注册、已评审、参数化、只读 SQL 工件，Agent / LLM 不生成 SQL | 已完成 |
| `v0.2.13` | `2026-06-26` | 补充海量能力匹配实施路线：新增 `sap-nexus-capability-matching-contract` 作为后续拆解项，明确混合式匹配、MatchDecision、候选召回、governance filter、rerank、参数适配和 planner 升级边界 | 已完成 |
| `v0.2.12` | `2026-06-25` | 完成并归档 `sap-nexus-registry-ontology-contract`：主 spec `registry-ontology-contract` 已生成，Registry contract validator、executor binding schema、OWL skeleton、eval linkage 和受控 `REST_JSON` 契约门禁已落地；下一推荐 change 转入 Gateway execution contract | 已完成 |
| `v0.2.11` | `2026-06-24` | 启动 `sap-nexus-registry-ontology-contract` 并进入 build：新增 Registry contract validator、executor binding schema、OWL skeleton、eval linkage 和受控 `REST_JSON` 契约门禁；仍不实施 OData/CDS/REST runtime | 已完成 |
| `v0.2.10` | `2026-06-23` | 增加 `REST_JSON` executor binding 路线：先作为 SAP Nexus 辅助接入能力，为 SAP 场景接入存量系统 HTTP JSON 事实来源；架构上预留未来扩展为 Enterprise Nexus Agent 通用接入层；当前仅更新 Registry / OWL contract 预留，不实施 REST Gateway runtime | 当前实施基线 |
| `v0.2.9` | `2026-06-22` | 明确后续多 executor 扩展路线：Registry / OWL Contract 先支持 `JCO_RFC`、`ODATA`、`CDS_ADT`、`CDS_ODATA` 绑定模型，统一 OData Gateway 和 CDS / ADT Gateway 分别作为后续独立 pilot；语义层与参数映射保持在 Gateway 外部 | 已完成 |
| `v0.2.8` | `2026-06-22` | 完成并归档 Workbench live runtime correction 与 MD04 stock/requirements BAPI correction；OpenSpec 当前无 active changes，下一推荐 change 回到 Registry / OWL Contract 加固 | 已完成 |
| `v0.2.7` | `2026-06-22` | 调整库存 Read Function 技术实现：`MM.Inventory.GetAvailability` 从 ATP 依赖的 `BAPI_MATERIAL_AVAILABILITY` 切换为 MD04 stock/requirements BAPI `BAPI_MATERIAL_STOCK_REQ_LIST`，第一版从 `MRP_IND_LINES` 当前库存行提取 `AVAIL_QTY1` 为 `availableQuantity`；后续 Registry / Gateway 需扩展 `JCO_RFC` / `CDS` / `ODATA` 多 executor 类型 | 已完成 |
| `v0.2.6` | `2026-06-21` | 修正 Workbench Console 运行时定位：local-first 仅表示本地控制台和本地服务进程，read-only 库存查询必须经 Python Agent structured runner -> Java Gateway validate / execute -> SAP JCo Read Function，不允许返回硬编码 fake SAP 数量 | 已完成 |
| `v0.2.5` | `2026-06-21` | 更新实施进度：`sap-nexus-agent-workbench-console` 已完成验证并归档，主 spec 已落到 `openspec/specs/agent-workbench-console/spec.md`，下一推荐 change 转入 Registry / OWL Contract 加固 | 已完成 |
| `v0.2.4` | `2026-06-20` | 增加 `sap-nexus-agent-workbench-console` 为 Registry / OWL Contract 前置推荐 change，用内部 Agent 控制台验证完整 Agent 链路、runtime streaming、trace 和 HITL 状态骨架 | 已完成 |
| `v0.2.3` | `2026-06-20` | 更新实施进度：`sap-nexus-agent-llm-intent-adapter` 已完成验证并归档，Agent 当前支持真实 LLM intent adapter + 规则兜底的 `hybrid` 模式，下一阶段仍转入 Registry / OWL Contract 加固 | 已完成 |
| `v0.2.2` | `2026-06-20` | 更新实施进度：`sap-nexus-agent-callplan-evidence` 已完成验证并归档，主 spec 已落到 `openspec/specs/agent-callplan-evidence/spec.md`，下一阶段转入 Registry / OWL Contract 加固 | 已完成 |
| `v0.2.1` | `2026-06-19` | 更新实施进度：`sap-nexus-capability-registry-gateway` 已完成验证并归档，主 spec 已落到 `openspec/specs/capability-registry-gateway/spec.md`，下一阶段转入 Python Agent CallPlan / Evidence 链路 | 已完成 |
| `v0.2.0` | `2026-06-19` | 从三天库存查询计划升级为全生命周期实施路线；将首要目标从 JCo 连通验证调整为 Agent 能力抽象、受控执行、事实化推理、人审写入和量产治理 | 已作为首个 Gateway implementation change 输入 |
| `v0.1.2` | `2026-06-18` | 补充未来三天库存查询打通实施计划，明确每日目标、任务、验收和风险兜底 | 可作为 OpenSpec build plan 输入 |
| `v0.1.1` | `2026-06-18` | 补充 Harness 落地任务映射，把可计划、可校验、可执行、可归一、可举证、可审计、可回放纳入路线验收 | 待进入 OpenSpec change |
| `v0.1.0` | `2026-06-18` | 基于 Notion 原方案、CBU_Brain 本体 Agent 经验、`sap-sto-create` JCo 经验，形成首版 MVP 路线 | 已确认首个 live capability，尚未进入 OpenSpec change |

---

## 1. 路线定位

本文档是 `SAP Nexus Agent` 的全生命周期实施路线，不只是当前库存查询 MVP 的任务清单。它用于指导后续从第一条 Read Function 到生产级 SAP Agent 产品的分阶段落地。

关键前提：

- **JCo 打通 SAP 已验证**：后续路线不再以“验证 JCo 是否可通”为首要风险，而是以“把 JCo 能力工程化封装为受控、可审计 Gateway”为首要工程目标。
- **MVP 用轻量 Registry，不上知识图谱运行时**：YAML/JSON 先承载能力本体、字段语义、SAP 映射和治理属性。
- **OWL 当前不进入 MVP / Pilot 门禁**：`ontologyIri` / `semanticType` 作为迁移预留元数据；当前一致性门禁由 JSON Schema、Registry validator、OpenSpec validation 和 Eval Harness 承担。
- **Read、Recommendation、Action 分阶段落地**：先查询事实，再形成建议，最后在人工确认后写入 SAP。
- **每一步必须可审计、可评测、可回放**：从 intent 到 SAP action 都必须由 `traceId` 串联，并由 Eval Harness / bad case 回归证明质量不回退。

---

## 2. 全生命周期目标

长期交付目标：

```text
自然语言业务意图
-> 已注册 SAP 能力闭集选择
-> 参数抽取与澄清
-> CallPlan
-> Gateway validate / execute
-> SAP / external access method: JCO_RFC / ODATA / CDS_ADT / CDS_ODATA / REST_JSON / SQL_READ
-> ExecutionResult
-> ReasoningFact
-> 结构化推理
-> ML 不确定推理
-> RecommendationPlan
-> Human Approval
-> SAP Write Action
-> ActionResult
-> Audit / Replay
```

产品能力演进：

| 阶段 | 能力形态 | 示例 |
|---|---|---|
| MVP | 单 Read Function 纵切 | 查询物料在工厂的可用量 |
| 扩展期 | 多 Read Function + Registry 校验 | 库存地点、批次、未清 PO、销售需求 |
| 推理期 | 结构化规则和建议 | 缺货风险、补货建议、异常解释 |
| 预测期 | ML 不确定推理 | 缺货概率、交付延迟风险 |
| 动作期 | 人审后写入 SAP | 创建 PR draft、提交受控动作 |
| 量产期 | 多域治理与回放 | Registry 发布、审计、监控、权限、图谱治理 |

---

## 3. 实施总原则

### 3.1 纵切优先，但不牺牲长期边界

第一条纵切仍为：

```text
MM.Inventory.GetAvailability
-> BAPI_MATERIAL_STOCK_REQ_LIST
```

但实现时必须同时建立长期边界：Capability Registry、CallPlan、ExecutionResult、ReasoningFact、TraceSpan 和 Gateway 白名单。

### 3.2 先 READ，再建议，再 ACTION

| 阶段 | 可做 | 禁止 |
|---|---|---|
| Read MVP | 查询 SAP、事实化、叙事 | 创建 PR/PO、写 SAP |
| Recommendation | 基于事实形成建议 | 自动执行建议 |
| Action | 人工确认后写 SAP | 未审批写入、ML 自动写入 |

### 3.3 能力先注册

新增能力必须按固定路径进入系统：

```text
Capability design
-> Registry entry
-> Schema validation
-> Gateway whitelist
-> Eval case
-> Implementation
-> Trace / Replay validation
```

### 3.4 证据驱动

每个业务结论必须来自事实链：

```text
SAP RETURN / BAPI output
-> ExecutionResult
-> ReasoningFact
-> RecommendationPlan
-> Narrative
```

Narrator 不直接解释裸 SAP 返回。

### 3.5 轻量 Registry / JSON Schema 先行

MVP / Pilot 不依赖 Neo4j / Jena / GraphDB / OWL runtime。Registry 字段由 JSON Schema、Registry validator、OpenSpec validation 和 Eval Harness 管理；`ontologyIri`、`semanticType` 保留为迁移预留元数据，但当前不作为运行时或发布门禁输入。

当前必须治理的字段：

```text
capabilityId
semanticType
businessObject
kind
sideEffect
requiresApproval
evidenceRole
governance
evalLinkage
```

### 3.6 MVP 匹配先用规则 + Registry

能力数量处于个位数或十几个时，不建设海量能力匹配栈。MVP 匹配只采用规则匹配、Registry 精确查找、required-param 校验和 governance fail-closed，并输出可评测的 `MatchDecision`：

```text
Natural Language
-> Rule / keyword / trigger phrase match
-> Registry exact capability lookup
-> Required parameter check
-> Governance filter
-> MatchDecision
-> CallPlan
```

第一版 `MatchDecision` 固定为：

```text
SELECT
CLARIFY
SHOW_OPTIONS
REJECT
ESCALATE_TO_PLANNER
```

当前 runtime 只通过 `IntentParseResult -> SelectionResult` 隐式覆盖部分 `SELECT` / `CLARIFY` / `REJECT` 语义，尚未实现显式五态决策对象、多意图检测和安全 `SHOW_OPTIONS` / `ESCALATE_TO_PLANNER`。因此基础决策正确性纳入 row 19/S2-A；它不依赖海量能力规模，也不等同于 row 12 的 Phase 3+ retrieval / rerank。

Phase 3+ 才考虑 retrieval / rerank / planner。升级阈值：active capability > 50、业务域 > 3、multi-capability 请求占比持续 > 15%，或 Eval bad case 证明规则匹配无法覆盖真实压力。

### 3.7 先建语义规划基础，再开放组合执行

OpenHarness 对比后，项目不采用通用模型自由 Tool Calling，而采用分层语义规划：

```text
GoalSpec candidate
-> capability relation graph
-> PlanDraft candidate
-> deterministic PlanCompiler
-> PlanGraph dry-run
-> read-only execution
-> later dynamic planner
```

近期可以在能力规模阈值未满足时建设 schema、关系本体和 plan-only Dry-run，因为这些是确定性治理基础；但 Dynamic Planner runtime 仍受 §3.6 阈值约束。首个只读组合 pilot 固定为“物料库存 + 采购订单供给概览”，只组合现有两个 active Read Function，不输出缺货预测、采购数量或自动 PR。

---

## 4. 推荐 OpenSpec / Comet change 拆分

| 顺序 | 建议 change | 当前进度 | 目标 | 退出标准 |
|---|---|---|---|---|
| 0 | `sap-nexus-architecture-lifecycle-baseline` | 已完成 | 固化产品级架构与路线文档 | 技术架构、实施路线、runbook 已更新并通过文档校验 |
| 1 | `sap-nexus-capability-registry-gateway` | 已完成并归档 | 建立轻量 Registry 与 Java JCo Gateway Harness | Gateway 只接受 `capabilityId`，未注册能力被拒绝 |
| 2 | `sap-nexus-inventory-read-function` | 已完成并归档 | 实现 `MM.Inventory.GetAvailability` Read Function，并修正为 MD04 stock/requirements BAPI | live SAP Read 返回结构化 `ExecutionResult`、MD04 evidence 和 trace |
| 3 | `sap-nexus-agent-callplan-evidence` | 已完成并归档 | 建立 Python Agent 的 CallPlan、Gateway client、ReasoningFact、Narrator | `openspec/specs/agent-callplan-evidence/spec.md` 已落地，Agent eval 通过 |
| 4 | `sap-nexus-agent-llm-intent-adapter` | 已完成并归档 | 为库存查询 Agent 增加真实 LLM intent adapter，并以规则解析兜底 | `hybrid` 默认启用，正常验证不依赖真实 LLM，live LLM smoke 可选通过 |
| 5 | `sap-nexus-agent-workbench-console` | 已完成并归档 | 建立未来可生产化的内部 Agent 控制台骨架，第一版作为本地开发体验工具 | `openspec/specs/agent-workbench-console/spec.md` 已落地，Workbench 可展示 Agent run timeline、artifacts、trace 和 HITL 状态 |
| 6 | `sap-nexus-registry-ontology-contract` | 已完成并归档 | 加固 Registry schema、OWL skeleton、一致性校验，并预留多 executor binding | `openspec/specs/registry-ontology-contract/spec.md` 已落地；YAML capability 可映射到 OWL identity，`JCO_RFC` / `ODATA` / `CDS_ADT` / `CDS_ODATA` / `REST_JSON` binding schema 可校验 |
| 7 | `sap-nexus-gateway-execution-contract` | 已完成并归档 | 定义统一 technical execution request/result 与 binding dispatcher | JCo Gateway 可按 bindingId 执行，语义层仍在 Gateway 外<br/><br/>验证证据（`2026-06-28`）：<br/>- `cd gateway-jco && gradle test` → `BUILD SUCCESSFUL`（含 CapabilityExecutionApiTest、CapabilityRegistryLoaderTest、TechnicalExecutionDispatcherTest、TechnicalRedactorTest）<br/>- `.venv/bin/python scripts/validate-registry-contract.py registry/capabilities.yaml` → `Registry contract valid`<br/>- `.venv/bin/python -m pytest agent/tests/test_registry_contract.py -v` → `13 passed`<br/>- `scripts/verify-agent-callplan-evidence.sh` → `54 passed, 1 skipped`；`Eval passed: 7/7`<br/>- `openspec validate --all --strict` → `5 passed, 0 failed`<br/>- 主 spec 已生成：`openspec/specs/gateway-execution-contract/spec.md` |
| 8 | `sap-nexus-eval-harness-seed` | 已完成直接实施 | 落地 Eval Harness seed cases 与 bad case 数据契约 | `evals/eval_harness_seed_cases.json` 覆盖 capability 命中、参数补全、业务口径、缺参澄清、unsafe request、narrative grounding 的最小回归集 |
| 9 | `sap-nexus-second-sap-read-capability` | 已由 `sap-nexus-odata-gateway-read-pilot` 隐式满足 | 上线第二条 SAP read capability，验证能力增长路径 | PO 即第二条 read，走 OData 路径（非 JCo）；已随 `sap-nexus-odata-gateway-read-pilot` 完成 Registry entry、CallPlan、Gateway validate/execute、ExecutionResult、ReasoningFact、Eval cases 和 trace |
| 10 | `sap-nexus-sandbox-write-vertical-slice` | 已完成并归档 | 在 sandbox / dev client 跑通最薄 SAP write 纵切 | `purchasing_group=601` 经 approval snapshot 映射到 `PRITEM.PUR_GROUP`；sandbox PR `10137471` 创建并 commit；external approval、anti-replay/hash/atomic claim、stateful JCo LUW 与 replay-complete trace 已通过 merged-main 全量验证；主 spec `openspec/specs/pr-create-action/spec.md` 已生成。详见 runbook `docs/runbooks/11-sandbox-write-vertical-slice.md` |
| 11 | `sap-nexus-recommendation-reasoning` | 待启动；与语义编排 S4 合并评估 | 基于 Read facts 形成 RecommendationPlan | 建议引用 facts/rules，不执行生产写入，不重复建设第二套推理层 |
| 12 | `sap-nexus-capability-matching-contract` | Deferred / Phase 3+ Scale-up Only | 仅当能力规模和 Eval bad case 证明轻量候选发现不足时，升级 semantic index、embedding/hybrid retrieval、跨域 router 和 LLM rerank；不包含 S2-A 基础五态决策 | active capability > 50、业务域 > 3、同域误选或召回/Eval 指标触发后再启动 |
| 13 | `sap-nexus-sql-read-executor-contract` | Reserved | 保留 `SQL_READ` 安全边界，不作为近期 runtime 优先级 | 不早于 Eval seed、第二条 read、sandbox write pilot |
| 14 | `sap-nexus-odata-gateway-read-pilot` | 已完成直接实施；PO 已激活 | OData read executor pilot | OData read pilot 落地；SAP SICF 重新激活后 PO live smoke 通过，`MM.PurchaseOrder.GetList` 已 active；item detail/filter change 已归档到 `openspec/changes/archive/2026-07-09-po-odata-item-detail-filter/`<br/><br/>验证证据（`2026-07-09`）：<br/>- Java Gateway 多模块（`services/gateway` core/jco/odata/app）-> `BUILD SUCCESSFUL`<br/>- Python `services/odata-service` -> 29 passed, 6 skipped；live spike -> 6 passed<br/>- Agent -> 109 passed, 1 skipped（PO 意图 + selector 多能力路由 + 列表归一 + narrative + `run_query` 统一入口）<br/>- PO eval -> 3/3；verify script eval -> 7/7 and 13/13<br/>- `openspec validate --all --strict` -> 7 passed, 0 failed<br/>- Gateway live execute `DEMOPO2` + material `DEMOA4B` + plant `5300` -> `totalCount=1` and one matching item<br/>架构决策：OData 用 Python（纯 HTTP 无 Java 绑定）+ Java 薄反代（方案 B 单端点保持）+ 新增 ODATA executor family（超越 §17.2） |
| 15 | `sap-nexus-cds-adt-gateway-read-pilot` | Reserved | CDS / ADT metadata 与受控 read preview pilot | 不早于近期三项 Next Pilot |
| 16 | `sap-nexus-rest-json-gateway-read-pilot` | Reserved | REST JSON read-only pilot | 不早于近期三项 Next Pilot |
| 17 | `sap-nexus-production-governance` | 待启动 | 量产治理、审计回放、监控、发布门禁 | 支持能力发布、eval 回归、trace 查询、故障诊断 |
| 18 | `sap-nexus-semantic-planning-foundation` | S1 Implemented / Verified / Archived | Fact Type、Capability Relation、GoalSpec、PlanGraph、四源 Registry Snapshot、immutable graph 和 deterministic validator 契约已落地 | focused semantic `287 passed`；full evidence `550 passed, 1 skipped` + inventory `7/7` + seed `13/13` + PR `9/9`；归档 `openspec/changes/archive/2026-07-19-sap-nexus-semantic-planning-foundation/` |
| 18A | `sap-nexus-source-of-truth-repository-hygiene` | P0A Completed (2026-07-25) | 收敛 Wiki、Runbook、README、OpenSpec 状态、仓库迁移路径和 runtime artifact 管理 | S1 状态与路径一致；README 不宣称未落地组件；旧 editable install 路径被修复（finder + .venv shebangs 重指 GitHub_Projects）；真实 runtime trace 不再 tracked（runtime/* gitignored）；不改变 runtime 行为 |
| 19 | `sap-nexus-planner-dry-run` | S2 Implemented / Verified / Archived (2026-07-25) | S2-A 先实现五态 `MatchDecision`、多意图/歧义检测、visibility pre-filter 和 matcher Eval；S2-B 再用 progressive `CapabilityCard` discovery 生成 GoalSpec/PlanDraft candidate，由 deterministic PlanCompiler 输出 dry-run | 多目标 utterance（如「物料库存 + 采购订单供给概览」）必须输出 `ESCALATE_TO_PLANNER`，不得静默首命中单能力，`false SELECT` 作为回归失败项；候选、决策理由、Registry Snapshot、节点、边、参数来源、缺口和治理均可审计；不得执行 Gateway 或 SAP；DeerFlow 只作机制参考 |
| 19A | `sap-nexus-agent-conversational-context` | 已完成并归档（2026-07-26） | 补齐即时多轮对话：session 内 CLARIFY 跨轮 slot-fill（sticky-CLARIFY）、`ConversationState` 轻量实例、历史重注入的权威/不可信分离契约、`IntentAdapter` 签名扩展接受 `ConversationContext`、前端 `conversationId` + CLI 透传 | 修复“第二轮补参数被 REJECT(UNSUPPORTED_INTENT)”缺口；状态仅放 backend 进程内 Map，不引入持久化/跨重启/multi-worker；v1 仅 CLARIFY，ESCALATE/SHOW_OPTIONS 跨轮为非目标；接口对齐 §4.2.1 三层分层为 P0B 预留；归档 `openspec/changes/archive/2026-07-26-sap-nexus-agent-conversational-context/`；详见技术架构 §4.2.2、runbook 12、runbook 08 §4.1.1。衍生 `sap-nexus-agent-llm-intent-enhancement`（LLM 指代理解 + 多值参数拆分）一并归档 |
| 19B | `sap-nexus-multi-value-batch-query` | 已完成并归档（2026-07-27） | 在 19A 会话层之上落地多值参数批量查询：`multi_parameters` 拆分 + `expand_combinations` 笛卡尔积 + `awaiting_batch_confirm`（不执行）+ `continue_batch` 逐组合执行 + `narrate_inventory_facts` 聚合；workbench/CLI/API/SSE 全链路接通 | `BATCH_COMBINATION_CAP=20` 软上限；v1 READ-only（Action 落 `awaiting_approval`）；combinations 进程内非持久化；`fix-batch-confirm-loop` 修复 `awaiting_batch_confirm` 与 `last_context` 死循环；WRITE 批量审批语义为 future；归档 `openspec/changes/archive/2026-07-27-multi-value-batch-service-integration/` + `2026-07-27-fix-batch-confirm-loop/`；详见技术架构 §4.2.3、runbook 12 |
| 20 | `sap-nexus-read-composition-pilot` | S3 Planned after row 19 | 以“物料库存 + 采购订单供给概览”验证只读多能力 PlanGraph 执行，并加入 governed ready-node lifecycle | 两个 active Function 经 Gateway 独立校验/执行；并发只允许无依赖 `sideEffect=none` 节点；确定性 OutputProjection 输出带 freshness、completeness、limitations 和 lineage 的 MaterialSupplySnapshot；当前未实现 |
| 21 | `sap-nexus-capability-composition-contract` | Dynamic Planner / Write Reserved | 保留通用动态组合、Composite Capability 和 Write composition 边界 | 关系本体、dry-run、read pilot 和规模/需求证据满足后另立 change |
| 22 | `sap-nexus-trusted-durable-runtime-foundation` | P0B Conditional Gate；不阻塞本地 S2；拆分 4 项独立 change | 建立 trusted principal / tenant / role / data scope、persistent thread/run、durable approval、ownership/lease、structured checkpoint reference、incremental SSE + reconnect 和幂等 continuation | 共享 S3、跨重启、长审批、multi-worker / HA 或非 sandbox WRITE 前必须完成；不包含 DeerFlow lead agent、自由 Tool execution 或预选数据库；row 19A 已先于 P0B 落地 `ConversationState` 轻量实例（进程内、非持久化），P0B 接手时替换为 durable store 并挂载压缩/分离注入 middleware。P0B 拆分为 4 项独立 change：项1 `sap-nexus-durable-state-foundation`（durable store + lease + checkpoint + idempotent continuation + §4.2.1 三层分层）已归档 `openspec/changes/archive/2026-08-02-sap-nexus-durable-state-foundation/`（2026-08-02，57 tests pass，单 worker durable）；项2 `sap-nexus-trusted-principal-model`（依赖项1）已归档 `openspec/changes/archive/2026-08-02-sap-nexus-trusted-principal-model/`（2026-08-02，76 tests pass，TrustedPrincipal server-owned 模型 + cross-principal fail-closed + 4 route 注入）；项3 `sap-nexus-durable-approval-store`（依赖项2）已归档 `openspec/changes/archive/2026-08-02-sap-nexus-durable-approval-store/`（2026-08-02，176 tests pass，FileDurableApprovalStore + cross-restart 恢复 + cross-worker anti-replay + @Primary wiring）；项4 `sap-nexus-incremental-sse-reconnect` 待续 |
| 23 | `sap-nexus-governed-user-memory-pilot` | Later / Triggered；不属于 S2/S3 | 只保存用户明确确认的语言、单位展示、术语和叙事偏好 | 身份、tenant、retention、查看/更正/删除和审计契约已稳定；不得保存业务事实、approval 或执行权威 |

---

## 5. Phase 0：架构基线与契约固化

### 目标

将技术方向从“库存查询 MVP 文档”升级为“产品全生命周期架构和实施路线”，作为后续所有实现的输入。

### 交付

- `docs/wiki/sap-nexus-agent-technical-architecture.md`
  - 产品架构定位。
  - 八层架构。
  - BAPI/RFC 能力抽象。
  - OWL 长期定位。
  - 核心契约和治理边界。
- `docs/wiki/sap-nexus-agent-implementation-roadmap.md`
  - 生命周期阶段。
  - OpenSpec / Comet 拆分。
  - MVP 到量产验收矩阵。
- `docs/runbooks/01-capability-registry-gateway.md`
  - 记录当前决策和下一步实施入口。

### 验收

| 验收项 | 标准 |
|---|---|
| 架构定位 | 明确不是单一 MVP 文档，而是长期产品指导文件 |
| JCo 前提 | 明确 JCo 连通已验证，首要工作是工程化封装 |
| MVP 边界 | 明确 MVP 不上知识图谱运行时 |
| 能力抽象 | 明确 `Skill / Function / Action` 和 BAPI/RFC executor 分离 |
| 核心契约 | 定义 `CallPlan`、`ExecutionResult`、`ReasoningFact`、`RecommendationPlan`、`ApprovalRecord`、`TraceSpan` |
| 审计闭环 | 文档能说明如何按 traceId 回放完整链路 |

---

## 6. Phase 1：Capability Registry + Java JCo Gateway Harness

### 目标

把已验证的 JCo/SAP 访问能力封装为受控 Gateway，并通过 Registry 把 SAP BAPI/RFC 暴露为业务能力。

### 范围

包含：

- `registry/capabilities.yaml`。
- Java Gateway 项目骨架。
- `GET /health`。
- `GET /capabilities`。
- `POST /capabilities/{capabilityId}/validate`。
- `POST /capabilities/{capabilityId}/execute`。
- Registry loader。
- Parameter validator。
- Gateway trace emitter。
- SAP `RETURN` normalizer 基础结构。

不包含：

- 任意 RFC、OData、CDS、ADT 或 REST 执行 API。
- 写入类 Action。
- GraphDB / RDF Store。
- 完整 Python Agent。

### 建议目录

```text
gateway-jco/
├── build.gradle 或 pom.xml
├── README.md
├── src/main/java/ai/sapnexus/gateway/
│   ├── GatewayApplication.java
│   ├── api/
│   ├── capability/
│   ├── jco/
│   ├── result/
│   └── trace/

registry/
└── capabilities.yaml

runtime/
└── traces/
```

### Registry 首个能力

```yaml
capabilities:
  - capabilityId: MM.Inventory.GetAvailability
    ontologyIri: sapnexus:MM_Inventory_GetAvailability
    kind: Function
    domain: MM
    businessObject: InventoryStock
    intent: GetAvailability
    description: 查询指定物料在指定工厂的可用库存
    semanticVersion: 1.0.0
    status: active
    executor:
      type: RFC
      rfcName: BAPI_MATERIAL_STOCK_REQ_LIST
    governance:
      sideEffect: none
      requiresApproval: false
      auditTags:
        - MM
        - INVENTORY_READ
```

### 当前进度

`2026-06-19` 已通过 `sap-nexus-capability-registry-gateway` 完成并归档 Phase 1 主体能力：

- 已建立 `registry/capabilities.yaml`，首个能力为 `MM.Inventory.GetAvailability`。
- 已建立 `schemas/capability.schema.json` 和 `schemas/execution-result.schema.json`。
- 已落地 `gateway-jco/` Spring Boot 3.x + Java 17 Gateway，官方 JCo 库按 `lib/` 目录布局纳入项目。
- 已实现 `/health`、`/capabilities`、`/validate`、`/execute`，Gateway 只接受 `capabilityId`。
- 已实现参数校验、SAP `RETURN` 归一、结构化错误、JSONL trace 和敏感字段过滤。
- 已完成验证报告：`docs/superpowers/reports/2026-06-19-sap-nexus-capability-registry-gateway-verify.md`。
- 主 spec 已归档生成：`openspec/specs/capability-registry-gateway/spec.md`。

### 验收

| 验收项 | 标准 | 当前状态 |
|---|---|---|
| `/health` | 返回 Gateway/JCo/Destination 状态，不泄漏敏感信息 | 已完成 |
| `/capabilities` | 从 Registry 返回 `MM.Inventory.GetAvailability` | 已完成 |
| validate | 缺 `material` 或 `plant` 返回结构化错误，不触发 SAP | 已完成 |
| unknown capability | 返回 `CAPABILITY_NOT_FOUND` | 已完成 |
| no raw RFC | 没有任意 `rfcName` 执行入口 | 已完成 |
| trace | 每次 execute 写入 `traceId`、capability、duration、success/error | 已完成 |

---

## 7. Phase 2：Inventory Read Function 纵切

### 目标

完成首个真实 Read Function：

```text
MM.Inventory.GetAvailability
-> BAPI_MATERIAL_STOCK_REQ_LIST
```

### 任务

1. 根据 Registry 完整配置 input/output mapping。
2. Gateway 执行 `BAPI_MATERIAL_STOCK_REQ_LIST`，按 MD04 当前库存行提取库存事实。
3. 标准化 SAP `RETURN`。
4. 输出 `ExecutionResult`。
5. 写入 `TraceSpan`。
6. 准备 2-3 组真实 `material + plant` smoke 样本。

### 成功响应目标

```json
{
  "success": true,
  "traceId": "rp_20260619_001",
  "capabilityId": "MM.Inventory.GetAvailability",
  "executor": {
    "type": "RFC",
    "rfcName": "BAPI_MATERIAL_STOCK_REQ_LIST"
  },
  "returnMessages": [],
  "data": {
    "material": "DEMOA1",
    "plant": "1000",
    "availableQuantity": 12,
    "unit": "EA"
  },
  "durationMs": 382
}
```

### 当前进度

首个真实 Read Function 已随 Gateway change 打通基础纵切：

- `MM.Inventory.GetAvailability -> BAPI_MATERIAL_STOCK_REQ_LIST` 已完成 live smoke。
- `ExecutionResult` 目标为返回 `executor.rfcName=BAPI_MATERIAL_STOCK_REQ_LIST` 和从 `MRP_IND_LINES` 当前库存行归一得到的 `data.availableQuantity`。
- SAP warning 场景已被归一到 `returnMessages`，且 `errorType=NONE`。
- trace 已确认只记录 `material`、`plant`、`unit` 等参数摘要，不写入注入的 `rfcName`、destination 或敏感环境信息。

剩余工作：补齐 2-3 组稳定样本、把样本固化为 eval/fixtures，并接入 Python Agent 的 CallPlan / ReasoningFact 链路。

### 验收

| 验收项 | 标准 | 当前状态 |
|---|---|---|
| live read | 至少 1 组真实样本返回结构化结果 | 已完成首个样本 |
| business error | SAP `RETURN` E/A 映射为 `SAP_BUSINESS_ERROR` | 已有单元测试覆盖 |
| communication error | JCo 通信失败映射为 `SAP_COMMUNICATION_ERROR` | 已有单元测试覆盖 |
| auth error | 权限失败映射为 `SAP_AUTH_ERROR` | 已有单元测试覆盖 |
| no credential leak | 响应、trace、日志不包含 SAP 密码 | 已完成 |
| trace replay | 给定 `traceId` 能定位请求、参数摘要、结果和错误类型 | 已完成最小 JSONL trace，待接入 Agent replay |

---

## 8. Phase 3：Python Agent CallPlan + Evidence Chain

当前状态：`2026-06-20` 已通过 `sap-nexus-agent-callplan-evidence` 和 `sap-nexus-agent-llm-intent-adapter` 完成并归档，主 spec 已生成并同步更新：

```text
openspec/specs/agent-callplan-evidence/spec.md
```

验证证据：

```text
scripts/verify-agent-callplan-evidence.sh
-> 38 passed, 1 skipped
-> Eval passed: 7/7
-> openspec validate --all --strict: 2 passed, 0 failed
```

LLM intent adapter 基线（语义识别以 LLM 为主）：

- CLI 默认 `--intent-mode hybrid`。`hybrid` 以 LLM 为主路径：LLM 结果直接使用，empty/error 结果不再回退规则，仅 `LlmUnavailable`（连接失败、JSON malformed）时回退规则解析。详见 spec `conversational-context`。
- 真实 LLM 通过 OpenAI-compatible `LLM_*` 环境变量接入。
- LLM 输出必须归一到闭集 `IntentParseResult`（`advisory` 指闭集约束：不得自由生成 `rfcName`、endpoint 或 SQL，不得突破 Registry / schema / governance）；能力匹配 / 选择（`MatchDecision`）仍以 deterministic 规则 + Registry 为权威，LLM 不替代 governance 判断。
- `llm` 模式纯 LLM（不可用返回空 `IntentParseResult`，不回退规则）；`rule` 模式纯规则（不调 LLM，保留 hybrid 安全兜底基线）。
- 正常验证不需要真实 LLM credentials；live LLM smoke 只在 `SAP_NEXUS_LLM_LIVE=1` 时运行。

### 目标

建立 Agent 最小编排：自然语言输入转成可审计 CallPlan，再调用 Gateway，并把 SAP 返回转成事实和叙事。

### 模块职责

| 模块 | 职责 |
|---|---|
| `intent.py` / `llm_intent.py` | 从用户问题提取 `material`、`plant`、`unit`，支持 `hybrid` LLM + rule fallback |
| `capability_selector.py` | 从 Registry 闭集选择 capability |
| `call_plan.py` | 生成 `CallPlan` |
| `gateway_client.py` | 调用 Gateway validate / execute |
| `execution_result.py` | 解析 Gateway 返回 |
| `reasoning_fact.py` | 生成 `ReasoningFact` |
| `narrator.py` | 基于事实输出结果，不解释裸 SAP 返回 |
| `eval/` | 执行能力命中、缺参、事实一致性回归 |

### 最小用例

```yaml
cases:
  - id: inv-001
    userQuery: "DEMOA1 在 1000 还有多少可用库存？"
    expected:
      capabilityId: MM.Inventory.GetAvailability
      parameters:
        material: DEMOA1
        plant: 1000
      shouldCallGateway: true

  - id: inv-002
    userQuery: "查一下 DEMOA1 的可用量"
    expected:
      capabilityId: MM.Inventory.GetAvailability
      missingParameters:
        - plant
      shouldCallGateway: false
```

### 验收

| 验收项 | 标准 |
|---|---|
| CallPlan | 每次执行前生成并带 `traceId` |
| 缺参 | 缺 `material` 或 `plant` 时只澄清，不调用 Gateway |
| Evidence | `ExecutionResult` 能转为 `ReasoningFact` |
| Narrative guard | Narrator 不输出不存在于 `ReasoningFact` 的数字 |
| Eval | happy path、缺参、非法参数、未知意图、Gateway 失败和敏感信息守卫均有回归覆盖 |
| Block rate | 缺参用例 Gateway 调用率为 0 |

---

### 8.1 Phase 3A：Agent Workbench Console

当前状态：`2026-06-21` 已通过 `sap-nexus-agent-workbench-console` 完成并归档，主 spec 已生成：

```text
openspec/specs/agent-workbench-console/spec.md
```

运行时修正：`sap-nexus-workbench-live-agent-runtime` 已完成并归档到 `openspec/changes/archive/2026-06-22-sap-nexus-workbench-live-agent-runtime/`。Workbench 仍是本地开发体验工具，但 read-only 库存查询必须调用本地 Python Agent structured runner，并经 Java Gateway `validate` / `execute` 到真实 SAP JCo Read Function；测试可以注入 fake runner，但人工 Workbench 查询不能返回硬编码 `12 EA` 等模拟库存。

定位：

- 按未来可生产化的内部 Agent 控制台设计。
- 第一版交付形态可以是纯本地开发体验工具。
- “本地开发体验”指本地 UI 和本地服务进程，不代表模拟 SAP 数据。
- 用于人工体验、观察和验证完整 Agent 链路，不只是库存查询页面。

目标链路：

```text
Natural language input
-> Agent Runtime Adapter
-> SSE event stream
-> Agent run state machine
-> Timeline visualization
-> CallPlan / ExecutionResult / ReasoningFact panels
-> Chinese narrative
-> Trace / audit viewer
-> Human-in-the-loop state skeleton
```

前端技术基线：

| 维度 | 决策 |
|---|---|
| Framework | React + Next.js |
| Language | TypeScript |
| Architecture | Modular Monolith |
| Runtime bridge | Agent Runtime Adapter |
| Streaming | SSE protocol first；当前 buffered SSE-format，共享环境目标为 incremental + reconnect/replay |
| Future realtime | WebSocket later, only for bidirectional HITL / collaboration |
| HITL | 状态机骨架先行，read-only capability 显示 `approval_not_required` |

补充修正：`sap-nexus-inventory-md04-stock-req-list` 已完成并归档到 `openspec/changes/archive/2026-06-22-sap-nexus-inventory-md04-stock-req-list/`。`MM.Inventory.GetAvailability` 当前技术实现为 `BAPI_MATERIAL_STOCK_REQ_LIST`，从 MD04 `MRP_IND_LINES` 当前库存行提取 `AVAIL_QTY1` 作为 `availableQuantity`。后续 Registry / Gateway 仍需在新 change 中扩展 `JCO_RFC` / `CDS` / `ODATA` 多 executor type。

范围约束：

- 前端不能直接调用 SAP、Java Gateway 或裸 RFC。
- 前端不能输入或覆盖 `rfcName`。
- 前端展示的 artifact 必须脱敏。
- 不做 SAP Write Action、真实审批写入、RecommendationPlan、KG runtime、RBAC、多租户或生产部署。
- 不提交 `.env`、SAP 密码、destination config、token、LLM API key、raw live LLM response 或 runtime trace。

已完成交付：

- `frontend/` Next.js + React + TypeScript 本地 Workbench。
- Agent Runtime Adapter 边界和 SSE-first run event stream。
- Run state machine、timeline、artifact panels、trace metadata、HITL state skeleton。
- Redaction guard 覆盖 `.env`、SAP destination、token、LLM response 等敏感形态。
- 验证报告：`docs/superpowers/reports/2026-06-21-sap-nexus-agent-workbench-console-verify.md`。


## 9. Phase 4：Registry / JSON Schema Contract 加固（已归档）

### 目标

把 MVP 的配置文件升级为可治理、可校验的 Registry / JSON Schema 契约，并把能力本体从 BAPI/RFC 绑定模型升级为 capability + executor binding 分离模型。该阶段已经归档；`ODATA`、`CDS_ADT`、`CDS_ODATA`、`REST_JSON` 和 `SQL_READ` 现在只作为 reserved boundary，不进入近期 runtime 优先级。OWL skeleton 保留为迁移预留资产，但 MVP / Pilot 门禁以 JSON Schema、Registry validator、OpenSpec validation 和 Eval Harness 为准。

### 任务

1. 定义 Registry JSON Schema，覆盖 capability identity、semantic inputs/outputs、evidence metadata、governance、executorBinding。
2. 增加 capability schema validation 命令。
3. 保留 `ontology/sapnexus-core.owl` skeleton 作为迁移预留。
4. 保留 `ontology/mm-inventory.owl` skeleton 作为迁移预留。
5. 将 `ontologyIri` 明确为 reserved metadata，不作为 MVP / Pilot runtime 或门禁输入。
6. 校验 `Function` 无副作用、`Action` 必须审批。
7. 为每个 capability 绑定 eval case。
8. 预留 `executorBinding.type = JCO_RFC | ODATA | CDS_ADT | CDS_ODATA | REST_JSON`；后续 change 扩展 `SQL_READ`。
9. 校验语义能力与技术绑定分离：Agent / Workbench 只能使用 `capabilityId`，Gateway 只能使用 allowlisted `bindingId`。
10. 明确 `REST_JSON` 先按 SAP Nexus 辅助接入能力落地，为 SAP 场景接入存量系统 HTTP JSON 事实来源；架构上预留未来 Enterprise Nexus Agent 扩展。

### Reserved OWL skeleton 覆盖概念

```text
Skill
Function
Action
Capability
BusinessObject
Material
Plant
InventoryStock
AvailableQuantity
ReasoningFact
RecommendationPlan
ApprovalRecord
ActionResult
ExecutorBinding
TechnicalAdapter
JcoRfcBinding
ODataBinding
CdsAdtBinding
CdsODataBinding
RestJsonBinding
ExternalSystem
CredentialReference
JsonRequestSchema
JsonResponseSchema
ResponseMapping
```

### 验收

| 验收项 | 标准 |
|---|---|
| schema | `registry/capabilities.yaml` 通过 schema 校验 |
| ontology metadata | `ontologyIri` 作为 reserved metadata 保持稳定，但当前不被 runtime 消费 |
| side effect | `Function` 不能声明 `sap_write` |
| approval | `Action` 必须 `requiresApproval=true` |
| eval linkage | Registry 变更可触发相关 eval 回归 |
| executor schema | `JCO_RFC` 当前通过；`ODATA`、`CDS_ADT`、`CDS_ODATA`、`REST_JSON`、`SQL_READ` 只作为 reserved boundary |
| semantic boundary | Gateway 不承载业务语义、字段语义、自然语言意图或能力选择 |
| REST boundary | REST binding 不允许外部覆盖 URL、HTTP method、headers、credentialRef 或 JSON payload mapping |

---


### 归档状态（2026-06-28）

`sap-nexus-registry-ontology-contract` 已完成并归档。保留的 durable contract artifacts：

- `registry/capabilities.yaml` 的 `executorBinding` 与 `evalLinkage`。
- `registry/executor-bindings.yaml` 的当前 `JCO_RFC` allowlisted binding。
- `schemas/executor-binding.schema.json` 的多 executor binding shape，包括 `REST_JSON` contract readiness。
- `scripts/validate-registry-contract.py` deterministic validator。
- `ontology/sapnexus-core.owl` 与 `ontology/mm-inventory.owl` offline skeleton（reserved metadata，不作为当前门禁）。
- `agent/tests/test_registry_contract.py` registry contract regression。

本阶段未实现 OData Gateway、CDS / ADT Gateway、REST JSON Gateway、arbitrary HTTP client、Knowledge Graph runtime、SAP Write Action、RecommendationPlan、ML uncertainty reasoning 或 UI；这些仍按技术架构 `v0.2.8` 的 reserved / later pilot 边界处理。

## 9.1 Phase 3+：Capability Matching Scale-up（Deferred）

### 目标

该 workstream 已降级为 Phase 3+，且只负责规模化 retrieval / rerank。在 active capability <= 20 且业务域数量较少时，不启动 Capability Index、embedding retrieval、跨域 semantic router 或 LLM rerank。五态 `MatchDecision`、多意图/歧义检测、候选 visibility 和基础 matcher Eval 不属于此延后项，已前移到 row 19/S2-A。

### 启动阈值

| 条件 | 动作 |
|---|---|
| active capability <= 20 | 继续使用规则匹配 + Registry 精确查找 |
| active capability > 20 且同域误命中或歧义明显 | 增加轻量 candidate scoring |
| active capability > 50 或业务域 > 3 | 才考虑 candidate retrieval + rerank |
| multi-capability 请求占比持续 > 15% | 才评估 planner / DAG |
| Eval bad case 中 capability mis-hit 连续升高 | 先补 Eval cases，再升级 matcher |

### 当前保留的 Phase 3+ 范围

包含：

1. 基于已稳定的 S2 `MatchDecision` contract 扩展大规模候选召回，不重新定义执行权威。
2. 评估 semantic / capability index、embedding 或 lexical + vector hybrid retrieval。
3. 只在 visibility pre-filter 后的小候选集合内启用 LLM rerank。
4. 以 `topKRecall`、`falseSelectRate`、ambiguity calibration、multi-capability 请求比例、prompt token 和 visibility complexity 作为升级证据。

暂不包含：

- Capability Index runtime。
- embedding retrieval。
- LLM rerank。
- 多能力 DAG planner。
- 新 SAP capability。
- OData / CDS / REST / SQL runtime。
- SAP Write Action 或 Human Approval runtime 变更。

---

## 9.2 Phase 4C：Gateway Execution Contract

### 目标

在实现 OData / CDS / REST runtime 前，先定义统一 technical execution contract。Gateway family 只接受语义层映射后的 `bindingId` 和 technical request，不接受裸 RFC、OData URL、ADT path、CDS view name、REST endpoint 或 JSON payload。

### 任务

1. 定义 `TechnicalExecutionRequest` / `TechnicalExecutionResult`。
2. 定义 `bindingId -> technical adapter` dispatcher。
3. 将现有 JCo executor 适配到 binding contract。
4. 统一 errorType、return messages、duration、trace 和 sensitive redaction。
5. 保持 `ExecutionResult` 对 Agent / ReasoningFact 的契约不变。

## 9.3 Phase 4D：OData Gateway Read Pilot

### 目标

参考 `sap-skill-create/skills-production/sap-sto-create` 中 OData 客户端的 session、CSRF、`sap-client`、JSON error normalization 和 deep payload 经验，落地统一 OData Gateway 的 read-only pilot。

### 边界

- 第一版只做 OData read，不做 STO create 或任何 SAP write。
- OData write、deep insert、STO 创建必须等 Human Approval / Action Governance 后再进入 Action pilot。
- Gateway 不保存 OData URL、token、destination config；Registry 只保存 `serviceRef` / `entitySet` 等非敏感 binding metadata。

### 完成状态（2026-07-09）

已通过 `sap-nexus-odata-gateway-read-pilot` 提前落地（原为 Reserved，经用户确认前置于 sandbox write pilot）。

架构决策：

- OData 用 Python（`services/odata-service`），非 Java：OData 是纯 HTTP 无 Java 绑定强制（JCo 用 Java 是 `sapjco3.jar` 强制）。
- Java Gateway 侧 `ODataHttpProxyAdapter` 薄反代转发到 Python odata-service（方案 B），Agent 保持单一端点。
- `services/gateway` 重组为多模块（core / jco / odata / app），dispatcher 按 executor binding 路由。
- `services/` 目录按连接器归集（gateway + odata-service，未来 CDS/REST/SQL 进此）。
- 新增 `ODATA` executor family，超越 §17.2 原退出标准"不新增 executor family"，经用户确认。
- 第二条 read capability（PO）走 OData 路径，隐式满足 row 9（`sap-nexus-second-sap-read-capability`）。

验证证据：

- Java Gateway 多模块：`BUILD SUCCESSFUL`。
- Python odata-service：29 passed, 6 skipped；live spike 6 passed。
- Agent：109 passed, 1 skipped。
- PO eval：3/3；verify script eval 7/7 and 13/13。
- `openspec validate --all --strict`：7 passed, 0 failed。
- Gateway live execute `DEMOPO2` + material `DEMOA4B` + plant `5300`：`totalCount=1`，item `10`。

Live blocker 已解除：SAP SICF 重新激活后 PO live smoke 已通过；PO capability 当前 `status=active`。

详见 `docs/runbooks/07-odata-gateway-read-pilot.md`。

## 9.4 Phase 4E：CDS / ADT Gateway Read Pilot

### 目标

参考 `sap-engineering-skill/skills/sap-adt-cli` 中 ADT client、CDS DDL source、Data Preview、XML result parsing 和 GET -> POST fallback 经验，落地 CDS / ADT metadata 与受控 read preview pilot。

### 边界

- `CDS_ADT` 用于设计时 metadata、CDS DDL、内部验证和受控 Data Preview。
- 不把 arbitrary SQL 暴露给 Agent；必须保留 SELECT-only guard、row limit 和 allowlisted binding。
- 若 CDS 已通过 OData/RAP 暴露为生产 read service，优先使用 `CDS_ODATA` / OData Gateway。

## 9.5 Phase 4F：REST JSON Gateway Read Pilot

### 目标

落地 REST JSON Gateway 的 read-only pilot，选择 1 个非 SAP 或 SAP 周边存量系统 HTTP JSON API 作为 SAP 场景补充事实来源。该 pilot 验证 `REST_JSON` binding 能通过 allowlisted `bindingId`、固定 method/path、JSON schema、response mapping、credentialRef redaction 和 eval 回归进入标准 `ExecutionResult -> ReasoningFact` 链路。

### 边界

- 第一版只做 read-only REST Function；有副作用的 REST 调用必须等待 Human Approval / Action Governance。
- REST Gateway 不接受用户或 LLM 提供的任意 URL、method、headers、token 或 JSON payload。
- Registry 只保存 `systemRef`、`pathTemplate`、`request mapping`、`response mapping`、timeout、sideEffect 等非敏感 binding metadata。
- 真实 API key、token、base URL、tenant、secret 和连接串只能通过 `credentialRef` / 外部环境配置引用，不能进入 git、trace、响应或日志。
- `REST_JSON` 当前定位是 SAP Nexus 的辅助接入能力；架构上预留未来扩展为 Enterprise Nexus Agent 的通用接入层。


## 9.6 Reserved：SQL_READ Executor Contract

### 目标

`SQL_READ` 当前只保留安全边界，不作为近期 runtime 优先级。该 workstream 不早于 Eval Harness seed、第二条 SAP read capability 和 sandbox write vertical slice。

保留边界：SQL 必须是已注册、已评审、参数化、只读 SQL 工件；Agent、LLM、用户请求均不能生成、提交或覆盖 SQL。

### Reserved 范围

包含：

1. 保留 `executorBinding.type = SQL_READ` 的 schema 方向。
2. 保留 binding catalog 字段：`dataSourceRef`、`dialect`、`sqlRef`、`sqlHash`、parameter schema、output schema、limits、security policy。
3. 保留 Registered SQL Read Gateway 边界：只接受 `bindingId` 和 named parameters，不接受 raw SQL、SQL fragment、table name、schema override、datasource override、connection string 或 stored procedure。

暂不包含：

- SQL runtime Gateway 实现。
- Agent / LLM SQL 生成。
- 任意查询接口或 SQL IDE。
- 写入 SQL、DDL、DML、stored procedure 或 side-effect function 调用。
- 直接查询 SAP 生产库的默认路径。

## 9.7 Semantic Planning 与 Capability Composition 路线

### 目标

在不引入 OpenHarness runtime、不破坏能力闭集和 Gateway 执行权威的前提下，把“多能力组合”拆成可验证的语义规划基础、Dry-run、只读 pilot 和后续 Dynamic Planner。

### 近期路线

1. `sap-nexus-semantic-planning-foundation`（S1 已实现 / 已验证 / 已归档）：Fact Type、Capability Relation、GoalSpec、PlanGraph、Registry Snapshot、immutable graph 和 validator；归档位于 `openspec/changes/archive/2026-07-19-sap-nexus-semantic-planning-foundation/`。
2. `sap-nexus-source-of-truth-repository-hygiene`（P0A immediate）：同步主文档 / runbook / README / OpenSpec 状态，修复仓库迁移后的旧 editable install 路径，并清理 tracked runtime trace；不改变 runtime 行为。
3. `sap-nexus-planner-dry-run`（S2 下一业务 design）：
   - S2-A Semantic MatchDecision Hardening：实现五态决策、多意图/歧义检测、候选 visibility、决策 trace 和 matcher Eval；多目标不得静默降级为首个命中能力。
   - S2-B Planner Dry-run：用 progressive `CapabilityCard` discovery 生成小候选集合；LLM 只生成 GoalSpec/PlanDraft candidate，deterministic PlanCompiler 输出计划预览；不执行 Gateway 或 SAP。
4. `sap-nexus-trusted-durable-runtime-foundation`（P0B conditional gate）：不阻塞本地 S2；在共享 S3、长审批、multi-worker / HA 或非 sandbox WRITE 前完成 trusted identity、durable Run/Approval、ownership/lease 和真实增量 SSE。
5. `sap-nexus-read-composition-pilot`（S3 planned）：只组合两个已注册 Read Function；PlanGraph 校验后才允许 ready-node 调度，由确定性 OutputProjection 形成 MaterialSupplySnapshot。
6. `sap-nexus-recommendation-reasoning`：在组合 Fact 已稳定后评估 `ReasoningFact[] -> RecommendationPlan`，不重复建设第二套推理层。

### Foundation 完成证据 / Dry-run 启动前置

- sandbox write vertical slice 已完成。
- 首个只读组合场景已确认。
- S1 design 已明确 schema、模块、错误模型、Eval 和 S1/S2 边界，且实现通过 fresh verification。
- S1 verification report 位于 `docs/superpowers/reports/2026-07-19-sap-nexus-semantic-planning-foundation-verify.md`；archive 已完成。
- S2-A 必须先把 `SelectionResult` 的隐式行为收敛为显式五态 `MatchDecision`，并覆盖 multi-intent、ambiguity、capability gap、visibility leakage、错误参数补全和 prompt injection Eval；`false SELECT` 作为回归失败。
- S2-B 只允许进入 dry-run design / implementation，不得提前接入 Gateway、SAP 或多能力 runtime execution。
- S2 可以借鉴 DeerFlow metadata-first、full-schema-later 的 progressive discovery，但 Tool search、Skill activation 或 LLM candidate 不获得执行权。
- `CapabilityCard` 必须绑定 Registry Snapshot，并排除 RFC、URL、credential、raw SQL 和 technical mapping。

### Read-only pilot 前置

- Fact Type 和 Capability Relation 通过 schema / referential integrity 校验。
- PlanGraph 可绑定 Registry Snapshot，循环依赖、类型不兼容、无来源参数可 fail-closed。
- Dry-run bad cases 覆盖未知 capability、缺失 Fact、Action 混入 READ_ONLY 计划和 Registry 漂移。
- 两个原子 Read capability 继续通过各自 Gateway / Eval 基线。
- `PlanExecutor` 的并发、timeout、cancel 和 ledger 只消费已验证 PlanGraph；不能从同一轮 LLM Tool Calls 推导可执行并行计划。
- `OutputProjection` 必须确定性声明输入 Fact、输出 schema、`asOf` / freshness、completeness、limitations 和 lineage；Narrator 不直接拼裸节点返回。
- 节点失败、超时或取消时输出必须标记 `incomplete`，不能叙述为完整供给结论。
- 本地单用户 S3 PoC 可在明确非生产边界下暂缓 durable runtime；共享 S3 必须先通过 P0B trusted/durable gate。

### 继续 Reserved

- 通用 Dynamic Planner runtime。
- Write composition 和 composite approval。
- LLM 自由多能力编排。
- Agent 自动发布能力、本体或 executor binding。
- 图数据库运行时。
- DeerFlow runtime、task/sub-agent graph 或 model-directed memory。

### 条件性平台门禁与后置候选

DeerFlow 对比额外识别出一个条件性平台门禁和一个后置候选；两者均不改变 S2 是下一业务 change：

- `sap-nexus-trusted-durable-runtime-foundation`：本地 S2 不启动；共享 S3、跨重启、长审批、multi-worker / HA 或非 sandbox WRITE 前必须启动并完成。先设计受信 principal、`ConversationState`、`PlanExecutionState`、`EvidenceState`、Approval 和 event cursor 契约，再选择 store / stream bridge。
- `sap-nexus-governed-user-memory-pilot`：只有企业身份、tenant、retention、查看/更正/删除和审计契约成熟后启动；Memory 仅保存用户偏好，不能保存 SAP 事实、PlanGraph、ApprovalRecord 或权限决策。

P0B 与 Memory 均需独立 OpenSpec / Comet change 和 Eval，不得夹带进 `sap-nexus-planner-dry-run`。

Dynamic Planner 仍需全部满足：

- Foundation、Dry-run 和 Read-only pilot 均通过验证。
- `active capability > 50` 或 `业务域 > 3` 或 `multi-capability 请求占比 > 15%`（与 §4.4 阈值对齐）。

详细技术方案和 S0-S6 路线见 `docs/wiki/sap-nexus-agent-openharness-semantic-orchestration.md`。

---

## 10. Phase 5：结构化推理与 RecommendationPlan

### 目标

基于 Read Function 产生的 `ReasoningFact` 做确定性推理，形成建议方案，但不写 SAP。

### 输入输出

输入：

```text
ReasoningFact[]
```

输出：

```text
RecommendationPlan
```

### RecommendationPlan 最小结构

```json
{
  "recommendationId": "rec_001",
  "traceId": "rp_20260619_001",
  "summary": "当前可用库存不足，建议评估补货",
  "factsUsed": ["fact_001"],
  "rulesTriggered": ["stock_shortage_rule_v1"],
  "proposedActions": [
    {
      "capabilityId": "MM.PR.CreateDraft",
      "kind": "Action",
      "requiresApproval": true,
      "status": "pending_approval"
    }
  ],
  "deterministic": true,
  "confidence": 1.0
}
```

### 验收

| 验收项 | 标准 |
|---|---|
| facts used | 每条建议必须引用 facts |
| rule trace | 每条建议必须说明触发规则或推理路径 |
| no write | Recommendation 阶段不执行 SAP 写入 |
| proposed action | 建议动作状态必须是 `pending_approval` |
| narrative | 用户输出区分事实、推理和建议 |

---

## 11. Phase 6：ML / Uncertainty Reasoning Interface

### 目标

引入不确定性推理接口，为未来缺货风险、供应延迟、异常需求预测等能力预留标准契约。

### 约束

- ML 输出必须 `deterministic=false`。
- 必须包含 `confidence`、`modelVersion`、`featuresUsed`。
- 必须 `requiresHumanReview=true`。
- ML 输出不能直接触发 SAP Action。
- Narrator 必须明确标注预测性质。

### 输出示例

```json
{
  "factId": "uf_001",
  "traceId": "rp_20260619_001",
  "predicate": "stockoutProbability",
  "value": 0.73,
  "deterministic": false,
  "confidence": 0.82,
  "source": {
    "modelVersion": "stockout-risk@1.0.0",
    "featuresUsed": ["availableQuantity", "openDemand", "leadTime"]
  },
  "requiresHumanReview": true
}
```

### 验收

| 验收项 | 标准 |
|---|---|
| boundary | ML 事实和确定性事实在 schema 上可区分 |
| no auto action | ML 结果不能自动执行 Action |
| model trace | 输出包含模型版本和特征摘要 |
| uncertainty narrative | 用户输出展示置信度和限制 |

---

## 12. Phase 7：Human Approval + SAP Write Action

### 目标

在人工确认后执行写入类 SAP BAPI/RFC，建立从建议到动作的受控闭环。

### 交付

- Action Registry。
- `ApprovalRecord` schema。
- Action CallPlan。
- Gateway Action execute path。
- `ActionResult` schema。
- SAP `RETURN` 标准化。
- Action trace / replay。

### Action 执行流程

```text
RecommendationPlan
-> 用户审阅
-> ApprovalRecord
-> Action CallPlan
-> Gateway validate
-> Gateway execute
-> SAP Write BAPI/RFC
-> ActionResult
-> AuditTrace
```

### 强制拒绝场景

| 场景 | 错误类型 |
|---|---|
| 无审批 | `APPROVAL_REQUIRED` |
| 审批过期 | `APPROVAL_EXPIRED` |
| 审批的 recommendation 版本不匹配 | `APPROVAL_VERSION_MISMATCH` |
| Action 未注册 | `CAPABILITY_NOT_FOUND` |
| Action disabled | `CAPABILITY_DISABLED` |
| SAP 返回 E/A | `SAP_BUSINESS_ERROR` |

### 验收

| 验收项 | 标准 |
|---|---|
| no approval no write | 未审批 Action 不能执行 |
| approval trace | 审批人、审批时间、审批内容、建议版本全部记录 |
| action result | SAP `RETURN` 被结构化保存 |
| replay | 给定 `traceId` 能回放建议、审批和写入结果 |
| safety | 写入响应和日志不泄漏凭据 |

---

## 13. Phase 8：Knowledge Graph / OWL Governance 升级

### 目标

当能力数量、多域关系和治理复杂度上升时，将 YAML Registry 平滑迁移或同步到 OWL / Graph Registry。

### 迁移路径

```text
registry/capabilities.yaml
-> ontologyIri / semanticType consistency
-> OWL skeleton
-> SHACL / schema validation
-> Graph Registry / Neo4j / Ontology Platform
-> Semantic Dispatcher dynamic discovery
```

### 注意

图谱是能力发现和治理增强，不替代 Gateway 的执行安全边界。即使未来能力目录来自图谱，Gateway 仍必须执行白名单、参数校验、side effect、approval 和 trace 约束。

### 图数据库触发式引入

能力关系三元组在 Phase 8 之前以文件（`ontology/capability-relations.yaml` edge list）+ 内存图承载，不引入图数据库。图数据库为触发式决策，触发条件：关系节点（capability + fact-type）进入数百以上、多跳 planner 查询成为热路径、需跨域治理可视化、或多服务并发共享关系图。图谱始终是派生只读索引，不可用时退回已发布 Registry snapshot。引擎（Neo4j property graph vs RDF triple store 如 Jena / GraphDB）留给 ROI spike；鉴于 OWL 方向，RDF store 与三元组 + OWL + SHACL 同栈，可能更贴。

### 验收

| 验收项 | 标准 |
|---|---|
| backend swap | Registry backend 替换不改变 Agent/Gateway 主流程 |
| ontology consistency | capability 和 OWL identity 一致 |
| governance gate | Action 审批、Function 无副作用可由 schema/SHACL 校验 |
| graph discovery | Semantic Dispatcher 可从图谱发现 active capabilities |
| fallback | 图谱不可用时可退回已发布 Registry snapshot |

---

## 14. Phase 9：量产交付与运维治理

### 目标

把 SAP Nexus Agent 从工程 MVP 推进到可运维、可审计、可治理、可扩展的生产系统。

### 交付能力

| 能力 | 量产要求 |
|---|---|
| 环境治理 | dev/test/prod destination 隔离 |
| 配置治理 | Registry 发布、审批、版本、回滚 |
| Gateway | HA、连接池、限流、熔断、健康检查 |
| Trace | 按 `traceId` 查询和回放完整链路 |
| Eval | capability 变更触发回归 |
| 权限 | READ / WRITE / Action approval 分权 |
| 日志 | 敏感信息脱敏 |
| 监控 | Gateway latency、SAP error rate、capability error rate |
| 审计 | 导出审计报告，支持追责和复盘 |
| 发布 | OpenSpec / Comet change + eval + approval + release note |

### 量产发布流程

```text
capability design
-> registry update
-> schema validation
-> ontology consistency check
-> gateway whitelist update
-> eval regression
-> security review
-> approval
-> release
-> monitoring
```

### 量产验收

| 类别 | 验收项 |
|---|---|
| 稳定性 | Gateway 和 Agent 支持持续运行、错误隔离、重试策略 |
| 安全 | 密码不进 git、日志、trace、响应 |
| 审计 | Read 和 Write 全链路可回放 |
| 治理 | Action 必须审批，审批可追责 |
| 可扩展 | 新 capability 接入不改平台核心代码 |
| 可验证 | 每个 capability 有 eval case 和发布门禁 |
| 可恢复 | Registry、trace、runtime store 有备份和回滚策略 |

---

## 15. MVP 实施验收矩阵

| 类别 | 验收项 | 标准 |
|---|---|---|
| Registry | 白名单 | `MM.Inventory.GetAvailability` 从 Registry 读取 |
| Registry | 未注册能力 | 未注册 `capabilityId` 被拒绝 |
| Gateway | no raw technical endpoint | 不存在任意 RFC、OData、CDS、ADT、REST 或 SQL 执行入口 |
| Gateway | validate | 缺 `material` 或 `plant` 不触发 SAP |
| Gateway | execute | live SAP Read 返回 `ExecutionResult` |
| Trace | trace write | 每次 execute 写入 trace |
| Agent | CallPlan | 每次执行前生成 `CallPlan` |
| Agent | missing params | 缺参输出澄清，不调用 Gateway |
| Evidence | ReasoningFact | `ExecutionResult` 转成事实 |
| Narrator | guard | 不输出不存在于事实的字段 |
| Eval | regression | happy path、缺参、非法参数、未知意图、Gateway 失败和敏感信息守卫均有回归覆盖 |
| Security | sensitive data | `.env` 和密码不进入 git、响应或 trace |

---

## 16. 长期架构验收矩阵

| 类别 | 验收项 | 标准 |
|---|---|---|
| 交互 | 内部 Agent 控制台 | 可观察 intent -> plan -> execute -> fact -> narrative -> audit 全链路 |
| 能力闭集 | 所有 SAP 或外部系统调用来自注册能力 | 无裸 RFC、OData、CDS、ADT 或 REST endpoint 调用 |
| 计划 | 单能力执行前有 CallPlan；多能力执行前有绑定 Registry Snapshot 的 PlanGraph | 可按 traceId 查询和重放 |
| 校验 | validate 先于 execute | 缺参、非法参数、未审批均拒绝 |
| 事实 | 输出前先事实化 | Narrator 只消费 ReasoningFact |
| 推理 | 建议引用事实和规则 | Recommendation 不是 Action |
| ML | 不确定性显式标注 | ML 不自动写 SAP |
| 写入 | Action 必须人审 | ApprovalRecord 必填 |
| 审计 | 全链路回放 | intent -> action result 可串联 |
| 图谱 | 可迁移 | YAML capability 有 ontology identity |
| 语义规划 | candidate 与执行权威分离 | LLM 只生成 GoalSpec/PlanDraft；deterministic PlanCompiler 决定 PlanGraph 是否可执行 |
| 能力缺口 | 不猜测不存在的能力 | 输出缺失 Fact/能力/关系并生成受治理 draft，不自动发布 |
| 量产 | 可运维 | 监控、告警、回滚、审计报表可用 |

---

## 17. 当前推荐下一步

`sap-nexus-capability-registry-gateway`、`sap-nexus-agent-callplan-evidence`、`sap-nexus-agent-llm-intent-adapter`、`sap-nexus-agent-workbench-console`、`sap-nexus-workbench-live-agent-runtime`、`sap-nexus-inventory-md04-stock-req-list`、`sap-nexus-registry-ontology-contract` 和 `sap-nexus-gateway-execution-contract` 均已完成验证并归档。`sap-nexus-eval-harness-seed` 已直接实施完成。`sap-nexus-odata-gateway-read-pilot`（Phase 4D OData Gateway Read Pilot）已提前落地，第二条 SAP read capability（PO，走 OData）由该 change 隐式满足。`sap-nexus-sandbox-write-vertical-slice` 已治理 Purchasing Group 并成功创建、commit sandbox PR `10137471`；verify repair、merged-main 全量验证与 Comet archive 均已完成，归档目录为 `openspec/changes/archive/2026-07-17-sap-nexus-sandbox-write-vertical-slice/`。

OpenHarness / DeerFlow 对比、首个组合场景确认、S1 foundation、P0A source-of-truth / repository hygiene、S2 planner-dry-run、row 19A 即时多轮对话上下文和 row 19B 多值批量查询均已归档完成后，当前推荐下一步不是直接实现 Dynamic Planner、DeerFlow integration、Memory 或新的 executor family。下一推荐为 P0B `sap-nexus-trusted-durable-runtime-foundation`（条件门禁：共享 S3、长审批、multi-worker / HA 或非 sandbox WRITE 前必须完成；`ConversationState` 接口已为其预留，进程内 sessions Map 待替换为 durable store）或 S3 `sap-nexus-read-composition-pilot`（本地单用户 PoC 可暂缓 durable，但须先设计确定性 OutputProjection 与 incomplete / freshness / lineage 语义）：

```text
1. sap-nexus-semantic-planning-foundation (S1 implemented / verified / archived 2026-07-19)
2. sap-nexus-source-of-truth-repository-hygiene (P0A completed 2026-07-25; no runtime behavior change)
3. sap-nexus-planner-dry-run (S2-A + S2-B implemented / verified / archived 2026-07-25)
4. sap-nexus-agent-conversational-context (row 19A archived 2026-07-26; sticky-CLARIFY + ConversationContext)
   - 衍生 sap-nexus-agent-llm-intent-enhancement (LLM 指代理解 + 多值参数拆分, archived 2026-07-26)
5. sap-nexus-multi-value-batch-query (row 19B archived 2026-07-27; continue_batch 全链路 + READ-only)
   - 衍生 fix-batch-confirm-loop (awaiting_batch_confirm 死循环 hotfix, archived 2026-07-27)
6. sap-nexus-trusted-durable-runtime-foundation (P0B conditional gate; before shared S3 / long approval / multi-worker / non-sandbox WRITE)
7. sap-nexus-read-composition-pilot (S3 planned; PlanGraph-governed execution + deterministic OutputProjection)
8. sap-nexus-recommendation-reasoning (与组合 Fact 集成评估)
```

首个 pilot 场景固定为“物料库存 + 采购订单供给概览”。尽管 row 18/S1 已验证，当前 runtime 在 row 20/S3 独立实现并验证前仍保持单能力 CallPlan；架构目标要求多能力请求进入 `ESCALATE_TO_PLANNER`，但当前 parser / selector 尚需在 S2-A 实现可靠多意图检测，完成前不得声称该行为已全面落地，也不得静默自动编排或执行。语义规划决策见 `docs/wiki/sap-nexus-agent-openharness-semantic-orchestration.md`，DeerFlow 借鉴边界见 `docs/wiki/sap-nexus-agent-deerflow-adoption-analysis.md`。

Live blocker 已解除：SAP SICF 重新激活后，PO live smoke 已通过；PO capability 当前 `status=active`。Sandbox write live smoke（Task 17）需要本地 `.env` 配置 sandbox / dev SAP client。

### 17.1 `sap-nexus-eval-harness-seed`

已完成直接实施：

1. `evals/eval_harness_seed_cases.json` 建立 bad case 数据位置和 contract shape。
2. 已覆盖 capability hit、parameter completion、business caliber、missing parameter clarification、unsafe execution block、narrative grounding 的 seed cases。
3. `scripts/verify-agent-callplan-evidence.sh` 已纳入新 seed eval。
4. Registry / prompt / matcher / reasoning / narrator 变更应按 `regressionTags` 选择相关回归集。

退出标准：

- 最小 Eval seed cases 可本地运行：`.venv/bin/python -m sap_nexus_agent.eval evals/eval_harness_seed_cases.json`。
- 每个 case 有自然语言、期望 decision、期望 capability、期望参数、期望口径或拒绝原因。
- `openspec validate --all --strict` 通过。

### 17.2 `sap-nexus-second-sap-read-capability`

已由 `sap-nexus-odata-gateway-read-pilot` 隐式满足：PO 即第二条 read capability，走 OData 路径（非 JCo）。已随该 change 完成 Registry entry、executor binding、CallPlan、Gateway validate / execute、ExecutionResult、ReasoningFact、Narrative、TraceSpan 和 Eval cases。

注意：本 change 超越原退出标准"不新增 executor family"，新增了 `ODATA` executor family，经用户确认。SAP SICF 重新激活后 PO capability 已翻 `status=active`，并补充了 live smoke、item detail 查询和 item-level filtering 验证；归档目录 `openspec/changes/archive/2026-07-09-po-odata-item-detail-filter/`。

### 17.3 `sap-nexus-sandbox-write-vertical-slice`

已完成代码实施、成功 live smoke、merged-main 全量验证与归档（`2026-07-17`）：以 `MM.PR.CreateDraft`（`BAPI_PR_CREATE`）为首个 Action capability。前两次调用分别暴露 technical envelope 与 Purchasing Group 缺口并 rollback；治理 `purchasing_group` 后的唯一授权调用成功创建并 commit PR `10137471`。归档 change 位于 `openspec/changes/archive/2026-07-17-sap-nexus-sandbox-write-vertical-slice/`，主 spec 位于 `openspec/specs/pr-create-action/spec.md`。

落地范围：

- `MM.PR.CreateDraft` 在 `registry/capabilities.yaml` 注册：`kind=Action`、`governance.sideEffect=sap_write`、`requiresApproval=true`、`approvalPolicy=human_required`、`dataClassification=internal`、`auditRequired=true`；6 required + 2 optional inputs（含 `purchasing_group`）；2 outputs（`prNumber` primaryFact、`returnMessages` executionEvidence）；executor binding `JCO_RFC` + `BAPI_PR_CREATE` + `bindingId=sap.mm.pr.create-draft`；ontology identity `sapnexus:MM_PR_CreateDraft`。
- Gateway `ApprovalGuard` 在 `execute` 入口、SAP 调用前 fail-closed，覆盖 4 种拒绝场景（approval missing、approval expired、approval capability/version mismatch、approval 后参数 snapshot hash 不匹配）。
- `PrCreateDraftExecutor` 实现 `BAPI_PR_CREATE` technical envelope（`PR_TYPE=NB`、item `00010`、`PUR_GROUP`、X indicators、JCo date）+ commit / rollback 守卫；PR 号优先读取 `EXPORTS.NUMBER`；commit / rollback 在 Gateway write 分支强制，READ 永不调用 commit / rollback。
- Agent approval 状态机 + Action CallPlan + 参数 snapshot hash + `ActionResult` 解析；首次 Action 只返回 pending，Workbench 服务端保存 exact context，用户 approve/reject 后才 continuation；成功路径记录 `approved -> executed`；Gateway Action HTTP 响应返回顶层 `prNumber/commitStatus`。
- Gateway WRITE trace 从同一个 `ActionResult` 写脱敏 `resultSummary`（PR 号、commit 状态、SAP RETURN），READ/validate trace 保持兼容。
- `evals/pr_create_cases.json` 9 个 case 覆盖成功直采 / 间采、缺参澄清、approval missing / expired / version mismatch、duplicate submit、SAP business error。
- runbook `docs/runbooks/11-sandbox-write-vertical-slice.md`。

退出标准达成：

- `RecommendationPlan -> ApprovalRecord -> Action CallPlan -> Gateway validate -> SAP execute -> ActionResult -> SAP RETURN -> TraceSpan -> EvalCase` 在代码层、eval 层和成功 live 路径可验证；sandbox PR `10137471` 已 committed。
- approval missing、approval expired、approval capability/version mismatch、SAP `RETURN` E/A、duplicate submit、approval 后参数被修改均有失败用例（9 个 eval cases + `test_approval.py` 21 个测试覆盖）。
- 禁止 release、post、commit-heavy action 和生产 client 自动写入（MVP 只支持 `BAPI_PR_CREATE` draft；`InMemoryApprovalStore` 非持久；生产 client 写入留 `sap-nexus-production-governance` workstream）。

架构决策：commit / rollback 在 Gateway 内部强制；`ApprovalGuard` 在 execute 入口 fail-closed；`InMemoryApprovalStore`（MVP，生产化前需持久化 + 审计回放）；approval TTL 默认 600s；间采薄纵切先只支持 `acct_assgn_cat="K"`。

### 17.4 Deferred / Reserved

以下 workstream 保留文档和安全边界，但不作为近期推荐下一步：

- `sap-nexus-capability-matching-contract`：Phase 3+ scale-up only，等能力规模和 Eval bad case 证明 S2 轻量候选发现不足；不包含 S2-A 基础五态决策。
- `sap-nexus-sql-read-executor-contract`：Reserved，等近期 sandbox write pilot 完成后再评估。
- `sap-nexus-odata-gateway-read-pilot`：已完成（2026-07-09），Phase 4D 提前落地；PO OData live smoke 已通过并激活。
- `sap-nexus-cds-adt-gateway-read-pilot`、`sap-nexus-rest-json-gateway-read-pilot`：Reserved，不早于 sandbox write pilot。
- OWL / Graph Registry：必须先通过 ROI spike；当前不作为 MVP / Pilot 门禁或 runtime 依赖。
- `sap-nexus-capability-composition-contract`：Dynamic Planner / Write composition 继续 Reserved；近期只推进 foundation、dry-run 和首个只读 pilot。
- OpenHarness runtime / Plugin runtime：不引入；只借鉴 Agent loop、Tool Schema、Permission/Hook、Dry-run 和 Memory/Resume 机制。
- DeerFlow runtime / Gateway / frontend / `deerflow-harness`：不引入；S2-B 只借鉴 progressive discovery，S3 只借鉴 PlanGraph-governed task lifecycle。
- `sap-nexus-trusted-durable-runtime-foundation`：不阻塞本地 S2；共享 S3、长审批、multi-worker / HA 或非 sandbox WRITE 前必须完成，不属于无条件近期 runtime 扩建。
- `sap-nexus-governed-user-memory-pilot`：Later / Triggered，不属于 S2/S3；Memory 不保存业务事实或执行权威。
- WRITE 批量审批语义：row 19B 多值批量查询 v1 仅 READ-only（Action 落 `awaiting_approval`）；per-combo approval snapshot / hash / atomic claim 的 WRITE 批量审批须单独设计，不得复用 READ 批量路径。

当前下一推荐：S1、P0A、S2（S2-A + S2-B）、row 19A 即时多轮对话、row 19B 多值批量查询均已归档；多值批量查询已端到端可用。下一步为 P0B `sap-nexus-trusted-durable-runtime-foundation`（条件门禁，本地不阻塞，`ConversationState` 接口已预留）或 S3 `sap-nexus-read-composition-pilot`（PlanGraph-governed 执行 + 确定性 OutputProjection，本地 PoC 可暂缓 durable）。S1 归档于 `openspec/changes/archive/2026-07-19-sap-nexus-semantic-planning-foundation/`，S2 归档于 `openspec/changes/archive/2026-07-25-sap-nexus-planner-dry-run/`，19A/19B 归档见 row 19A/19B。

---

## 18. Known Correctness Defects

本节记录当前 runtime 已知、未修复的正确性缺陷，区别于 §4 Roadmap row 的功能排期。缺陷在对应收敛里程碑验证通过前不得被描述为已解决；架构侧定义见 `docs/wiki/sap-nexus-agent-technical-architecture.md` §18。

### D-1：多目标 utterance 静默降级为首命中单能力

- **现象**：rule parser 按固定顺序返回首个命中意图；包含多个业务目标（如“物料库存 + 采购订单供给概览”）的请求被静默降级为首个命中的单能力（如仅库存）。
- **影响**：返回结果在业务上不完整但无任何告警，系统丢弃了一半意图却返回看似正确的答案，污染用户信任。
- **当前缓解**：无。
- **收敛归属**：S2-A 五态 `MatchDecision`（row 19）；多意图/歧义检测必须将并列多能力目标导向 `ESCALATE_TO_PLANNER`（record + explain），`false SELECT` 作为回归失败项。详见 `docs/runbooks/08-capability-matching-contract.md`。

---

## 19. Stage Gate 评测三件套

每个 Stage Gate 固定使用「SLI / 指标 + 典型 bad case + 回归集来源」三件套。三件套不全的阶段显式标注「评测缺口」，不以模糊措辞掩盖。SLI 定义不随实现改动漂移，具体阈值按阶段配置。

### P0A：source-of-truth / repository hygiene

- **SLI / 指标**：评测缺口--P0A 是文档/仓库卫生 change，不产生 runtime 行为，不适用 SLI/eval 回归。Gate 以 `openspec validate --all --strict`、文档校验和 `git diff --name-only` 仅含 `docs/` 为准。
- **典型 bad case**：评测缺口--无 runtime bad case；以"README 宣称未落地组件""tracked runtime trace""Wiki/runbook 状态与归档不一致""旧 editable install 路径未修复"等文档漂移作为人工 review 项。
- **回归集来源**：评测缺口--无 eval case；以文档校验脚本与人工 diff review 代替。

### S2-A：Semantic MatchDecision Hardening

- **SLI / 指标**：`multiIntentDetectionRate`（多目标请求进入 `ESCALATE_TO_PLANNER` 而非首命中单能力）、`ambiguityCalibration`、`visibilityLeakageRate`（目标 `0`）、`unsafeExecutionBlockRate`、false `SELECT` rate（目标 `0`）。
- **典型 bad case**：多目标 utterance 静默首命中单能力（false `SELECT`）；不可见 capability 在 visibility filter 前进入模型候选（visibility leakage）；prompt injection 诱导生成 `rfcName` / URL / SQL 或越权选择（prompt injection）；相似候选无法安全区分却直接 `SELECT`。
- **回归集来源**：matching-specific Eval cases（`docs/runbooks/08-capability-matching-contract.md` §6）；false `SELECT` 作为回归失败项；bad case 素材见 `docs/wiki/sap-nexus-agent-openharness-semantic-orchestration.md` §9。

### S2-B：Planner Dry-run

- **SLI / 指标**：`goalInterpretationAccuracy`、`planGroundingRate`（节点/边全部来自发布 Registry / relation graph，目标 `100%`）、`planValidityRate`、`capabilityGapAccuracy`。
- **典型 bad case**：`PlanDraft` 引用不存在 capability；PlanGraph 循环依赖；上游 Fact 类型不满足下游输入；`READ_ONLY` 计划包含 Action；Registry Snapshot 在 dry-run 与 execute 间变化。
- **回归集来源**：dry-run bad cases（`docs/wiki/sap-nexus-agent-openharness-semantic-orchestration.md` §9 最小 bad case）；caller-authored PlanGraph validation fixtures（S1 已有双 READ 节点 fixtures 扩展）。S2-B 不执行 Gateway / SAP，回归集为 dry-run validation 层。

### Trusted / Durable Runtime Gate（P0B）

- **SLI / 指标**：评测缺口（部分）--候选指标含 durable Run/Approval 一致性、run ownership/lease 冲突率、checkpoint replay 一致性、event cursor 断线续传完整性；具体阈值待 `sap-nexus-trusted-durable-runtime-foundation` 独立 change 设计。
- **典型 bad case**：跨重启后 pending approval / run 丢失或被错误主体恢复；并发 run 共享 checkpoint / approval context；context compaction 改变 `PlanGraph` / `ApprovalRecord` / `EvidenceState`；断线重连后事件丢失或乱序。
- **回归集来源**：评测缺口--尚无 dedicated 回归集；需在 `sap-nexus-trusted-durable-runtime-foundation` 独立 change 中建立 durable state contract 测试与 eval。

### S3：Read-only Composition Pilot

- **SLI / 指标**：`factLineageCompleteness`（每个组合结论可追溯到节点与原始证据，目标 `100%`）、`unsafePlanBlockRate`（目标 `100%`）、`writeApprovalBypassRate`（目标 `0`）、partial-failure `incomplete` 标注率；`replanRecoveryRate` 在 S3 后评估。
- **典型 bad case**：一个 Read 节点失败但 Narrator 试图输出完整供给结论（`incomplete` 未标注）；两个有依赖或副作用的节点被并行执行；`OutputProjection` 把部分事实叙述为完整 `MaterialSupplySnapshot`；跨节点时间口径不一致却假定同一业务时点。
- **回归集来源**：组合 release-gate fixtures（S1 双 READ 节点 PlanGraph fixtures 扩展）；`docs/wiki/sap-nexus-agent-openharness-semantic-orchestration.md` §9 组合 bad cases；需在 `sap-nexus-read-composition-pilot` 独立 change 中补 `OutputProjection` / lineage eval。

---

## 20. Open Questions 与已知技术债

本节登记跨阶段技术债与未决项，不在本轮 doc-only 收敛中给方案。技术债标注证据出处与处理时机；Open Question 标注触发条件。

### 已知技术债（来源：S1 verify report）

- **T-1 上游 jsonschema 英文诊断未规范化**：S1 契约校验透传上游 `jsonschema` 英文诊断，未规范化为项目自有的确定性消息。处理时机：S2 扩大报告使用面前。证据：`docs/superpowers/reports/2026-07-19-sap-nexus-semantic-planning-foundation-verify.md`。
- **T-2 非法 UTF-8 源未封装为 `SourceLoadError`**：非法 UTF-8 源解码异常未封装为 `SourceLoadError`；当前路径仍会在发布 graph / snapshot 前 fail closed。处理时机：S2/S3 hardening 前。证据：同上。
- **T-3 S3 只读执行前需补组合矩阵测试**：S3 只读执行前需补 3+ binding/field 及混合 dependency/precondition matrices；现有 S1 逻辑不依赖固定基数，未发现生产缺陷。处理时机：S3 只读执行前。证据：同上。

### Open Questions

- **Q-1 能力供给规模化**：当前每个新 capability 的建模边际成本高（registry entry + schema + eval + runbook + 可能的 binding），需在 S2/S3 期间并行设计模板化 / 半自动生成路径，否则 S3 组合价值缺少足够能力对来兑现。触发条件：S2-B 候选发现设计时评估"新增能力建模成本"是否成为 S3 pilot 场景扩展的瓶颈。本轮不给方案，登记为 Open Question。

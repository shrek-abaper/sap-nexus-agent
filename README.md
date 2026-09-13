<div align="center">

<h3>SAP 能力的供应方，而不是又一个 SAP Agent</h3>

<h4><i>能力本体驱动 · 一次调用回答一个业务问题 · Harness 可整体替换</i></h4>

> 把 SAP 业务问题沉淀为业务语义级能力：端点链、`asOf` 时点一致性、基数归约与审批裁决全部由服务端强制，覆盖域之外显式拒答而非降级凑答。Harness 只做能力选择与展示，换宿主不会换出第二套业务语义。

**能力本体建模 · 编译期派生 · 业务语义级能力 · 服务端强制治理 · 全链路血缘 · 可替换 Harness**

**Apache-2.0 · 自托管 · 无厂商锁定 · SAP On-Prem**

<h4>面向 SAP 落地场景的治理型能力层</h4>

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg?style=flat-square)](LICENSE)
[![Java](https://img.shields.io/badge/Java-17-007396?style=flat-square&logo=openjdk&logoColor=white)](services/gateway)
[![Python](https://img.shields.io/badge/Python-3.12+-3776AB?style=flat-square&logo=python&logoColor=white)](agent)
[![Node](https://img.shields.io/badge/Node-20+-339933?style=flat-square&logo=nodedotjs&logoColor=white)](frontend)
[![SAP](https://img.shields.io/badge/SAP-JCo%20RFC%20%2B%20OData-0FAAFF?style=flat-square&logo=sap&logoColor=white)](#当前已注册能力服务端内部)
[![Offline Gate](https://img.shields.io/badge/offline%20gate-22%2F22%20L3__ACTION__GOVERNED-2EA043?style=flat-square)](#目标达成状态s1s5)

<!-- TODO: DSH Chat 界面截图或 GIF -->

**[English](README.en.md)** · **中文**

</div>

**[快速开始](#快速开始)** · **[目标架构](#目标架构agent-建设目标)** · **[当前架构](#当前架构概览现状)** · **[核心特性](#核心特性)** · **[目标达成状态](#目标达成状态s1s5)** · **[Harness 可见面](#harness-可见面业务语义工具契约-v2)** · **[已注册能力](#当前已注册能力服务端内部)** · **[技术栈](#技术栈)**

---

SAP Nexus Agent 的目标是做 **SAP 能力的供应方**，而不是又一个 SAP Agent。四方各管一件事：能力本体（YAML 单一来源）定义业务对象与业务口径；编译期派生管线离线产出 Capability Manifest，请求期零本体查询；SAP 域能力层暴露业务语义级能力——**一次调用回答一个业务问题**，内部固化端点链、`asOf` 一致性与基数归约；Harness（dsh / MCP client / 自有 CLI）只做能力选择、展示与澄清，可整体替换。唯一安全边界是远程 Java Gateway，`bindingId`、RFC 名、服务 URL、HTTP 方法与凭证引用永不可由 harness 提供或覆盖。

**核心原则：事实先于叙事；能力即边界。**

> 上述四方分工中，能力本体与编译期派生管线为目标态，当前实现状态见[「目标达成状态」](#目标达成状态s1s5)。

---

## 快速开始

### 前置依赖

- Java 17（无需单独安装 Gradle，仓库自带 `services/gateway/gradlew`）
- Python 3.12+
- Node.js 20+
- SAP JCo 3 库（用于 SAP 实时执行）
- SAP On-Prem 连接与凭证（用于实时冒烟测试）
- OpenAI-compatible LLM 端点与 API Key（DSH Chat / harness-dsh 使用；Rule 模式与离线测试不需要）

**无 SAP 连接或凭证时**，可运行下方[「验证基线」](#验证基线截至-2026-09-13)的完整离线测试套件、call-plan eval 与 registry 校验，但**无法进行交互式查询**——Python Agent CLI 即便使用 `--intent-mode rule`（免 LLM key）仍会连接 Gateway 执行；DSH Chat / harness-dsh 另需 LLM key。

### 准备 Python 环境

仓库没有 `requirements.txt`；agent 包按 `agent/pyproject.toml` 以 editable 方式安装（`test` extra 提供 `jsonschema`，另需 `pytest` 运行下方测试命令——`pytest` 未在 pyproject 中声明）：

```bash
python3 -m venv .venv                          # 需 Python 3.12+
.venv/bin/python -m pip install -e "agent[test]" pytest
```

### 环境配置

```bash
cp .env.example .env
# 填入 SAP 连接参数；DSH 使用时另需 SAP_NEXUS_LLM_BASE_URL / SAP_NEXUS_LLM_API_KEY / SAP_NEXUS_LLM_MODEL
```

### 验证基线（截至 2026-09-13）

```bash
.venv/bin/python scripts/validate-registry-contract.py registry/capabilities.yaml
.venv/bin/python -m pytest agent/tests
PYTHONPATH=agent scripts/verify-agent-callplan-evidence.sh
npm --prefix frontend run verify
npm --prefix frontend run release-gate -- --profile all
```

当前基线：

- Registry 合约校验：`Registry contract valid`（17 条 deprecation warning，均为 `extraction.matchers` → `binding.sources` 迁移提示，不影响合约有效性）
- Agent 测试套件：`1574 passed, 1 skipped, 2 xfailed`
- Frontend 套件：`579 passed`（64 个测试文件）；`verify`（typecheck + vitest + next build）全绿
- Call-plan Eval：inventory `7/7`、eval_harness_seed_cases `13/13`、PR `9/9`、matcher `23/23`、dry-run `3/3`（另 1 条 structural pending）、derived-parameter `3/3`（另 2 条 parser-blocked pending，用例内有书面归因）
- Offline release gate：2026-08-19 达成 `22/22` / `L3_ACTION_GOVERNED`（历史里程碑）；L1–L3 四项 hard gates 均为 leakage `0`、approval bypass `0`、unsupported claim `0`、lineage `100%`；`liveSmoke: not_run`（离线门禁不执行真实 SAP 调用；报告见 `runtime/evals/results/agent-release-l3-2026-08-19T13-09-48-499Z.json`；2026-08-10 旧报告的取证说明见[路线图 §1.1.4](docs/wiki/sap-nexus-agent-implementation-roadmap.md)）

`PYTHONPATH=agent` 用于直接验证当前源码树。

### 启动服务

终端 1 — Gateway：

```bash
set -a; . ./.env; set +a
cd services/gateway
./gradlew --no-daemon bootRun
```

如系统默认 JDK 不是 17，先自行 `export JAVA_HOME=<JDK 17 路径>`（不要再写死发行版专属路径）。

终端 2 — OData 微服务（采购订单能力需要）：

```bash
cd services/odata-service
PYTHONPATH=. python -m odata_service.server   # :8081
```

终端 3 — DSH Chat（推荐入口，需要 LLM key）：

```bash
set -a; . ./.env; set +a
SAP_NEXUS_AGENT_ROOT=$(pwd) \
SAP_NEXUS_GATEWAY_URL=http://127.0.0.1:8080 \
npm --prefix frontend run dev
```

打开 `http://127.0.0.1:3000/chat`（根路径自动跳转；经典 Workbench 仍在 `/workbench`）。

可选 — harness-dsh 独立 CLI（另开终端，需先启动上面的 Next facade）：

```bash
cd harness-dsh
npm ci && npm run build
cp .env.example .env      # OpenAI-compatible 端点/key；SAP_NEXUS_FACADE_URL 默认 http://127.0.0.1:3000
npm start -- "A100 在 1000 工厂够不够用、在途多少？"
```

可选 — Python Agent CLI（不经 harness，Rule 模式无需 LLM key，但仍需可达的 Gateway 与 SAP 连通）：

```bash
PYTHONPATH=agent .venv/bin/python -m sap_nexus_agent.cli \
  "A100 在 1000 还有多少可用库存？" \
  --gateway-url http://127.0.0.1:8080 --intent-mode rule
```

---

## 目标架构（Agent 建设目标）

> 下图是本项目的**目标架构（Agent 建设目标）**，**不是当前仓库现状**；当前实现见下一节「当前架构概览（现状）」。架构图只画目标形态，不含进度、数量或日期；仅当分层、层间责任、契约红线或派生关系发生变化时才更新。实现进度统一记录在下方[「目标达成状态」](#目标达成状态s1s5)与[实施路线图 §1.1](docs/wiki/sap-nexus-agent-implementation-roadmap.md)。读图主线：**定义在顶、推理在编译期、治理在能力内、体验可替换**。立场为「四方各管一件事」：能力本体（YAML 单一来源）、编译期派生管线（离线产出 Capability Manifest）、SAP 域能力层（业务语义级、核心资产）、Harness（可替换的编排与展示）。

![SAP Nexus Agent 目标架构：能力本体驱动的 SAP 能力供应方](docs/images/nexus-target-architecture.png)

---

## 当前架构概览（现状）

```text
体验层 · Harness（可替换）
  ┌──────────────────────────────┐  ┌──────────────────────────────────┐
  │ harness-dsh CLI（独立 Node 包） │  │ DSH Chat Workbench（/chat）       │
  │ dsh T-A-O 循环 · 钉 0.1.5-rc.1 │  │ 浏览器 + 服务端 in-process dsh     │
  └──────────────┬───────────────┘  └────────────────┬─────────────────┘
                 │ HTTP POST /api/semantic-tools      │ 进程内直接调用
                 └──────────────────┬─────────────────┘
                                    ▼
  ┌─────────────────────────────────────────────────────────────────────┐
  │ Next.js 服务端（:3000）                                                │
  │ Semantic Tool Facade（契约 v2 · 形状校验 · 技术键注入 fail-closed）     │
  │ executeSemanticTool = 服务端治理唯一入口（HTTP facade 与 dsh 共用）      │
  │ agent-runtime-adapter：spawn Python Agent 子进程                        │
  │ Composition Runtime：PlanExecutor · durable node ledger ·              │
  │   Projection · Recommendation · grounded Narrative · governed Action   │
  └────────────────────────────────┬────────────────────────────────────┘
                                   │ registered capabilityId only
                                   ▼
  ┌─────────────────────────────────────────────────────────────────────┐
  │ Java Gateway（:8080 · 唯一安全边界）                                    │
  │ 参数校验（能力本体约束）· 执行器路由（JCO_RFC / ODATA）· 结果归一化       │
  │ TechnicalExecutionResult · 脱敏 / 审计                                  │
  └──────────────────┬───────────────────────────────┬──────────────────┘
                     ▼                                ▼
           ┌──────────────────┐            ┌────────────────────────────┐
           │ SAP JCo（RFC/BAPI）│            │ odata-service（:8081）       │
           └────────┬─────────┘            │ Python 只读微服务 · $filter  │
                    │                      └─────────────┬──────────────┘
                    └──────────────────┬─────────────────┘
                                       ▼
                              SAP On-Prem 系统

旁路：Python Agent CLI（sap_nexus_agent.cli）可不经 harness 直连 Gateway（rule / llm intent）；
经典 Workbench /workbench 与 DSH Chat 共用同一 agent-runtime + composition 治理链。
```

### 当前架构限制（设计选择，非缺陷）

- Run/Session、principal ownership、approval、lease/idempotency 与 cursor SSE 已 durable 化；但当前本地 JSONL/file store 和 placeholder principal 仍不是 shared multi-worker/HA store 或生产身份系统（多宿主前必须替换，见目标架构支撑面）
- 编译期派生管线（Capability Manifest）、业务口径本体（`Definition`）、字段级 FactType schema 与关系图尚在目标态规划中，当前 registry 仍是端点级能力注册表
- Knowledge/RAG、自由 Tool Calling、通用 Dynamic Planner、多 WRITE/Saga 和自动补偿仍为 Reserved / Not In Scope
- 图数据库和 OWL 推理运行时为预留方向，当前 JSON Schema + Registry Validator 承担一致性职责

---

## 核心特性

### 业务语义级工具面与服务端强制治理（核心差异点）

- **业务语义级工具面（Semantic Tool 契约 v2）**：harness 只见 4 个业务工具（见下文[「Harness 可见面」](#harness-可见面业务语义工具契约-v2)），不出现 `capabilityId` / `rfcName` / `bindingId` / URL / 凭证；技术键注入在 facade 层 fail-closed
- **同一条服务端强制治理链**：HTTP facade 与 in-process dsh handler 共用 `executeSemanticTool`，意图选择、CallPlan、校验、审批全部在服务端；harness 进程内没有任何直连 Gateway / RFC / 绑定 / 凭证的调用面（`harness-dsh/tests/architecture.test.ts` 锁定）

### 可替换 Harness（DSH 打样）

- **两个 harness 形态**：`harness-dsh/` 独立 Node CLI（dsh T-A-O 循环，经 HTTP 调 semantic-tool facade）与 Next.js 内置的 **DSH Chat**（`/chat`，服务端 in-process dsh runtime，支持流式推理轨迹、工具卡与审批交互）；根路径 `/` 已 307 跳转至 `/chat`
- **版本 pin**：`@deepseek-ai/dsh-*` 精确钉 `0.1.5-rc.1`、`@deepseek-ai/cordis` 钉 `4.0.2`；preview 期任何升级都是独立变更评审

### 当前语义层：端点级能力注册表

以下字段与机制均为**已实现的端点级能力注册表**语义；能力本体（业务对象 / 业务口径 `Definition` / 关系图）尚未落地——状态见[「目标达成状态」](#目标达成状态s1s5)。

- **Capability Ontology** — 每个 SAP 操作（查询/写入）被建模为形式化能力，包含 `ontologyIri`、`semanticType`、输入/输出语义类型、事实类型引用
- **语义参数映射** — 能力输入参数通过 `semanticName`/`semanticType` 关联到本体概念（如 `MaterialNumber`、`Plant`），与 SAP 技术参数（`MATERIAL`、`PLANT`）解耦
- **执行器绑定** — 能力绑定到特定执行器（`JCO_RFC` / `ODATA`），通过白名单 `bindingId` 控制，运行时拒绝替换
- **OWL 预留** — `ontologyIri` 和 `semanticType` 为未来 OWL 本体推理预留迁移路径，当前一致性门禁由 JSON Schema + Registry Validator 承担
- **声明式意图解析** — Rule 模式意图解析完全声明驱动（`registry/capabilities.yaml` 的 `intent` 块 + `registry/semantic-types.yaml` 语义类型目录），添加新能力无需修改 Agent 代码

### 治理与安全

- **fail-closed** — 不支持的执行器类型（`CDS_ADT` / `REST_JSON` / `SQL_READ`）默认拒绝执行
- **参数注入防护** — 调用者不得提供或覆盖 `rfcName`、`bindingId`、服务 URL、HTTP 方法、凭证引用、原生 SQL、CDS 对象等；semantic-tool facade 对技术键做任意深度扫描
- **READ 安全边界** — READ 能力不得调用 `BAPI_TRANSACTION_COMMIT` 或 `BAPI_TRANSACTION_ROLLBACK`
- **WRITE 人工审批** — WRITE 能力（采购申请创建 / `propose_replenishment` 提案）必须存在已记录的人工确认（exact-subject）才执行；审批 subject 由服务端计算与校验
- **全链路审计** — 每次执行生成 TraceSpan / JSONL trace，记录意图→CallPlan→验证→执行→证据→叙述的完整链路

### 执行器家族

| 类型 | 状态 | 说明 |
|------|------|------|
| `JCO_RFC` | ✅ Live | 通过 SAP JCo 直接执行 RFC/BAPI |
| `ODATA` | ✅ Live | Gateway 薄反向代理 → Python odata-service（:8081）→ SAP OData |
| `CDS_ADT` | 🔒 Fail-closed | 架构预留 |
| `REST_JSON` | 🔒 Fail-closed | 架构预留 |
| `SQL_READ` | 🔒 Fail-closed | 架构预留 |

---

## 目标达成状态（S1–S5）

对照目标架构的 S1–S5 建设序列评估当前实现（2026-09-13 复核）；完整状态表见[路线图 §1.1](docs/wiki/sap-nexus-agent-implementation-roadmap.md)，测试与门禁的具体数字只记录在上方[「验证基线」](#验证基线截至-2026-09-13)。

- **序列进度**：S1 补证据已完成 · S2（对象主键 + 字段级 schema）未开始 · S3（业务口径 + 关系入本体 + 编译期派生管线）未开始 · **S4 能力粒度上移已完成，但越过了 S2/S3** · S5 多宿主验证部分完成（跨宿主一致性门禁已通过；MCP 暴露与第三方 harness 未做）。
- **层级达成**：Harness 体验层、契约边界（四条红线）、SAP 域能力层（4 个业务语义工具，3 读 1 写）、Java Gateway 与执行器（JCO_RFC/ODATA live）**已建成**；编译期派生管线与运行时状态层**部分**（已有手写版本化 JSON Schema 契约 `contractVersion=2`；本地 JSONL 存储 + placeholder principal）；**能力本体层（对象/口径/关系）与离线决策回流未动——本体是唯一未上岗的一层**。
- **三条结构性要求**：① 能力粒度「**已达成，但错位**」（4 个业务工具存在，但声明在服务端代码而非本体，端点级已不对外）；② 语义资产**未达成**（字段级 schema、业务口径、关系均为空，工具描述仍手写）；③ 身份与审批**部分**（审批句柄与服务端身份注入已有，调用主体仍占位、存储仍本地）。
- **下一步是回填而非新建**：① CI 门禁要求新增能力输出字段引用 `Definition` 口径 id（允许占位 id 先行）；② 尽早切分 `ontology-core`（开源）/ `ontology-tenant`（不公开），本体近空时成本最低；③ 将 4 个已有能力的口径（可用库存 / 逾期 / 信用敞口）从代码逐条上提，同步产出字段级 schema 与首条跨域 link。
- **唯一实质断点**：业务口径固化在服务端代码里，「改一行本体即改变 Agent 行为、零代码改动」的自检判据尚不通过。
- **离线端到端治理编排主链可用**：意图 → CallPlan → 校验/执行 → ExecutionResult → ReasoningFact → 叙述 → durable Workbench 回放 → plan-aware single Action continuation；TypeScript composition coordinator 已接通 PlanExecutor、OutputProjection、Recommendation、grounded Narrative（单能力 `CallPlan` 主链保持可用）。
- **Python Agent 职责**：LLM-first intent、closed-set recall、五态决策和 PlanGraph v2 authoring；作为 Next 服务端按需 spawn 的子进程运行，也可经 CLI 独立运行。
- **Release gate 里程碑**：offline L1/L2/L3 gate 于 2026-08-19 达成最高连续等级 `L3_ACTION_GOVERNED`；规模、四项 hard gates 数值与复现命令见[「验证基线」](#验证基线截至-2026-09-13)，2026-08-10 旧报告的取证说明见[路线图 §1.1.4](docs/wiki/sap-nexus-agent-implementation-roadmap.md)。
- **SAP 连通性**（依据 `runtime/gateway-jco/traces.jsonl`）：MM 域四个能力（`MM.Inventory.GetAvailability`、`MM.PurchaseOrder.GetList`、`MM.Material.GetInfo`、`MM.PR.CreateDraft`）均有真实 SAP 成功执行记录；OData 链于 2026-09-13 再次端到端冒烟通过（采购订单真实数据返回）。`SD.SalesOrder.GetList` 有 live 执行尝试但在当前系统尚未成功，`FI.AR.GetOpenItems` / `FI.AP.GetOpenItems` 已注册并由离线测试覆盖、尚无 live 执行记录——SD/FI live 冒烟待补。offline release gate 的 `liveSmoke` 字段保持 `not_run`（离线门禁不执行真实 SAP 调用）；任何 live WRITE 仍需 exact-subject Human Approval。

---

## Harness 可见面：业务语义工具（契约 v2）

harness 只能命名业务工具与槽位；工具内部由服务端从已注册能力中选择能力链，harness 不构造调用图。

| 语义工具 | 必填槽位 | 性质 | 服务端能力链（registry 选择） |
|---------|---------|------|------------------------------|
| `diagnose_material_supply` | — | READ | 库存可用性 + 在途采购订单（`MM.Inventory.GetAvailability` · `MM.PurchaseOrder.GetList`） |
| `review_customer_exposure` | `customerNumber`（AR 未清项另需公司代码） | READ | 销售订单净值 + 应收未清项（`SD.SalesOrder.GetList` · `FI.AR.GetOpenItems`） |
| `review_vendor_exposure` | `vendor` · `companyCode` | READ | 应付未清项（`FI.AP.GetOpenItems`） |
| `propose_replenishment` | `material` · `plant` · `requiredQuantity` · `targetDate` · `purchasingGroup` | WRITE 草案 | 缺口诊断 → 采购申请提案；执行前 exact-subject 人工审批（`MM.PR.CreateDraft`） |

> 注：表中为当前服务端实际选择的能力链。目标架构中 `review_vendor_exposure` 的内部链另含采购订单端点，尚未内化；harness 可见面已从 7 个端点级工具降为这 4 个业务语义级工具（可见面治理封顶 15）。

---

## 当前已注册能力（服务端内部）

| 能力 ID | 名称 | 执行器 | SAP 端点 | 状态 |
|---------|------|--------|----------|------|
| `MM.Inventory.GetAvailability` | 库存/需求清单查询（MD04） | `JCO_RFC` | `BAPI_MATERIAL_STOCK_REQ_LIST` | ✅ active |
| `MM.PurchaseOrder.GetList` | 采购订单列表查询 | `ODATA` | `API_PURCHASEORDER_PROCESS_SRV` | ✅ active |
| `MM.Material.GetInfo` | 物料主数据查询（基本单位/采购组） | `JCO_RFC` | `BAPI_MATERIAL_GET_DETAIL` | ✅ active |
| `MM.PR.CreateDraft` | 采购申请创建 | `JCO_RFC` | `BAPI_PR_CREATE` | ✅ active（需人工审批） |
| `SD.SalesOrder.GetList` | 销售订单列表查询（VA05 风格） | `JCO_RFC` | `BAPI_SALESORDER_GETLIST` | ✅ active（live 冒烟待补） |
| `FI.AR.GetOpenItems` | 客户应收未清项查询 | `JCO_RFC` | `BAPI_AR_ACC_GETOPENITEMS` | ✅ active（live 冒烟待补） |
| `FI.AP.GetOpenItems` | 供应商应付未清项查询 | `JCO_RFC` | `BAPI_AP_ACC_GETOPENITEMS` | ✅ active（live 冒烟待补） |

共 7 个能力：6 个只读（`kind: Function`，`sideEffect: none`）+ 1 个写入（`MM.PR.CreateDraft`，执行前必须存在已记录的人工确认）。

---

## 仓库结构

```text
agent/                   Python Agent 包：意图、CallPlan/PlanGraph v2、测试与评估
frontend/                Next.js：DSH Chat（/chat）、经典 Workbench（/workbench）、
                         semantic-tool facade、服务端 dsh runtime、composition runtime
harness-dsh/             可替换 harness 打样：独立 Node CLI（dsh T-A-O，钉 0.1.5-rc.1）
services/
  gateway/               Java Spring Boot SAP Gateway（多模块，唯一安全边界）
  odata-service/         Python OData 只读微服务（:8081）
registry/                能力注册表和执行器绑定目录（YAML 单一来源）
schemas/                 JSON Schema 契约
ontology/                离线 OWL 本体骨架（预留）
openspec/                Classic 工作流规格与变更归档
runtime/                 运行时 trace、dev-services、gateway-jco 与 release-gate 结果
evals/                   Agent 评估用例
scripts/                 验证和注册表检查脚本
docs/
  wiki/                  架构、路线图、技术选型文档（事实来源）
  comet/                 Native 工作流变更归档
  runbooks/              22 份历史 runbook（已归档，仅作补充查询，非事实来源）
```

---

## 技术栈

| 层 | 技术 |
|----|------|
| Harness | DSH Chat（Next 内置 dsh runtime，SSE 流式）+ harness-dsh 独立 CLI；`@deepseek-ai/dsh-*` 精确钉 `0.1.5-rc.1`、cordis `4.0.2`；harness 可替换 |
| Agent | Python package + OpenAI-compatible LLM（默认 DeepSeek `deepseek-chat`）+ Rule 混合 |
| 服务端编排 | React/Next.js 服务端：Semantic Tool Facade、Composition Runtime、durable JSONL store |
| Gateway | Java 17 / Spring Boot / Gradle 多模块（唯一安全边界） |
| SAP 连接 | SAP JCo 3 (RFC) + SAP OData (HTTP，经 odata-service) |
| 前端 | React / Next.js / TypeScript |
| 能力注册 | YAML + JSON Schema |
| 本体 | YAML + JSON Schema + 不可变内存图；OWL 骨架 offline；图数据库与编译期派生管线为目标态 |
| Runtime State | 本地 JSONL/file 持久化的 Run/Session/Approval + JSONL trace；非 shared multi-worker/HA store；共享/量产 durable runtime 待独立 change |
| 认证与授权 | placeholder principal，尚未产品化；共享环境需 server-owned principal / tenant / role / data scope / ApprovalActor |

---

## 文档

- [技术架构](docs/wiki/sap-nexus-agent-technical-architecture.md)
- [实施路线图](docs/wiki/sap-nexus-agent-implementation-roadmap.md)
- [技术选型](docs/wiki/sap-nexus-agent-technology-selection.md)
- [OpenHarness 语义编排分析](docs/wiki/sap-nexus-agent-openharness-semantic-orchestration.md)
- [harness-dsh 说明](harness-dsh/README.md)

---

## 许可

本项目采用 [Apache-2.0](LICENSE) 许可证。

---

## 快速导航

| | |
|---|---|
| AGENTS.md / CLAUDE.md | 项目级 Agent 行为规则 |
| registry/ | 能力注册表（7 个已注册能力） |
| harness-dsh/ | 可替换 harness（DSH CLI） |
| frontend/src/server/dsh/ | 服务端 dsh runtime 与语义工具接线 |
| ontology/ | OWL 本体骨架 |
| evals/ | 评估用例 |

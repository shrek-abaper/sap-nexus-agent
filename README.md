> [English](README.en.md) | **中文**

# SAP Nexus Agent

SAP Nexus Agent 是一个**基于能力本体建模的 SAP 治理型接入网关**。当前以 YAML Registry、JSON Schema、Fact Type / Capability Relation catalog 和不可变进程内语义图建模 SAP 业务能力及参数约束；LLM Agent 仅在已注册能力边界内提出意图或计划候选，所有数据访问必须经过 Capability Registry、确定性校验和白名单执行器绑定，不支持裸 RFC/OData/SQL 调用。

**核心原则：能力即边界 —— 不是通用 SAP 代理，而是受控能力网关。**

---

## 架构概览

```text
用户查询（自然语言）
  │
  ▼
┌─────────────────────────────────────────┐
│  Python Agent 层                         │
│  · 语义意图解析（LLM + Rule Hybrid）      │
│  · 注册能力选择（基于能力本体匹配）         │
│  · CallPlan 生成                         │
│  · 推理证据构建（ReasoningFact）          │
│  · 中文叙述生成                           │
└──────────────┬──────────────────────────┘
               │ capabilityId + 参数
               ▼
┌─────────────────────────────────────────┐
│  Java Gateway 执行层                      │
│  · 参数校验（能力本体约束）                │
│  · 执行器路由（JCO_RFC / ODATA）          │
│  · 结果归一化 → TechnicalExecutionResult    │
│  · 脱敏 / 审计                           │
└────┬──────────────┬─────────────────────┘
     │              │
     ▼              ▼
  ┌────────┐  ┌──────────────┐
  │ JCo    │  │ OData Proxy   │
  │ (RFC)  │  │ (HTTP → SAP)  │
  └────────┘  └──────────────┘
     │              │
     └──────┬───────┘
            ▼
        SAP On-Prem 系统
```

---

## 核心特性

### 能力本体建模（Core Differentiator）

- **Capability Ontology** ─ 每个 SAP 操作（查询/写入）被建模为形式化能力，包含 `ontologyIri`、`semanticType`、输入/输出语义类型、事实类型引用
- **语义参数映射** ─ 能力输入参数通过 `semanticName`/`semanticType` 关联到本体概念（如 `MaterialNumber`、`Plant`），与 SAP 技术参数（`MATERIAL`、`PLANT`）分离
- **执行器绑定** ─ 能力绑定到特定执行器（`JCO_RFC` / `ODATA`），通过白名单 `bindingId` 控制，运行时不允许替换
- **OWL 预留** ─ `ontologyIri` 和 `semanticType` 为未来 OWL 本体推理预留迁移路径，当前一致性门禁由 JSON Schema + Registry Validator 承担

### 治理与安全

- **fail-closed** ─ 不支持的执行器类型（`CDS_ADT` / `REST_JSON` / `SQL_READ`）默认拒绝执行
- **参数注入防护** ─ 调用者不得提供或覆盖 `rfcName`、`bindingId`、服务 URL、HTTP 方法、凭证引用、原生 SQL、CDS 对象等
- **READ 安全边界** ─ READ 能力不得调用 `BAPI_TRANSACTION_COMMIT` 或 `BAPI_TRANSACTION_ROLLBACK`
- **WRITE 人工审批** ─ WRITE 能力（如采购申请创建）需人工审批确认后才执行
- **全链路审计** ─ 每次执行生成 TraceSpan，记录意图→CallPlan→验证→执行→证据→叙述的完整链路

### 执行器家族

| 类型 | 状态 | 说明 |
|------|------|------|
| `JCO_RFC` | ✅ Live | 通过 SAP JCo 直接执行 RFC/BAPI |
| `ODATA` | ✅ Live | 薄反向代理 → Python OData 微服务 → SAP OData |
| `CDS_ADT` | 🔒 Fail-closed | 架构预留 |
| `REST_JSON` | 🔒 Fail-closed | 架构预留 |
| `SQL_READ` | 🔒 Fail-closed | 架构预留 |

### 当前运行成熟度

- `FactType`、`CapabilityRelation`、`GoalSpec`、`PlanGraph` 和 `RegistrySnapshot` 契约已实现、验证并归档；当前产品 runtime 仍只执行单能力 `CallPlan`。
- Workbench Run 与 Gateway Approval 当前使用进程内 Store；服务重启、长审批和多实例恢复尚未量产化。
- 当前 `/stream` 返回完成后聚合的 SSE-formatted events，不是增量发布或断线续传。
- 可信 principal、tenant、role、data scope 和 ApprovalActor 尚未接入；当前 WRITE 仅限 sandbox/dev 验证。
- 共享 S3、长审批、multi-worker/HA 或非 sandbox WRITE 前，必须先完成 trusted/durable runtime 独立 change。

---

## 当前已注册能力

| 能力 ID | 名称 | 执行器 | SAP 端点 | 状态 |
|---------|------|--------|----------|------|
| `MM.Inventory.GetAvailability` | 库存可用量查询 | `JCO_RFC` | `BAPI_MATERIAL_STOCK_REQ_LIST` | ✅ active |
| `MM.PurchaseOrder.GetList` | 采购订单列表查询 | `ODATA` | `API_PURCHASEORDER_PROCESS_SRV` | ✅ active |
| `MM.PR.CreateDraft` | 采购申请创建 | `JCO_RFC` | `BAPI_PR_CREATE` | ✅ active（需人工审批） |

---

## 仓库结构

```text
agent/                   Python Agent 包、测试和评估
frontend/                Next.js Agent Workbench
services/
  gateway/               Java Spring Boot SAP Gateway（多模块）
  odata-service/         Python OData 只读微服务
registry/                能力注册表和执行器绑定目录
schemas/                 JSON Schema 契约
ontology/                离线 OWL 本体骨架
evals/                   Agent 评估用例
scripts/                 验证和注册表检查脚本
docs/
  wiki/                  架构、路线图、技术选型文档
  runbooks/              会话操作手册
openspec/                OpenSpec 规范和变更归档
```

---

## 快速开始

### 前置依赖

- Java 17
- Gradle 8.8 +（或使用 `services/gateway/gradlew`）
- Python 3.12+
- Node.js 20+
- SAP JCo 3 库（用于 SAP 实时执行）
- SAP On-Prem 连接与凭证（用于实时冒烟测试）

快速测试无需 SAP 连接或凭证。

### 环境配置

```bash
cp .env.example .env
# 填入 SAP 连接参数、LLM API Key 等
```

### 验证

```bash
scripts/comet-verify-gateway.sh
.venv/bin/python scripts/validate-registry-contract.py registry/capabilities.yaml
.venv/bin/python -m pytest agent/tests/test_registry_contract.py -v
PYTHONPATH=agent scripts/verify-agent-callplan-evidence.sh
openspec validate --all --strict
```

预期结果：所有命令退出码为 `0`；当前 Agent 基线为 `550 passed, 1 skipped`，Eval 为 `7/7 + 13/13 + 9/9`，OpenSpec 为 `8 passed, 0 failed`。仓库移动后如 editable install 仍指向旧路径，应重新安装本地 package；`PYTHONPATH=agent` 可用于验证当前源码。

### 启动服务

终端 1 - Gateway：

```bash
set -a; . ./.env; set +a
cd services/gateway
JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64 \
  /tmp/gradle-8.8/bin/gradle --no-daemon bootRun
```

终端 2 - OData 微服务（PO 能力需要）：

```bash
cd services/odata-service
PYTHONPATH=. python -m odata_service.server
```

终端 3 - Agent CLI：

```bash
PYTHONPATH=agent .venv/bin/python -m sap_nexus_agent.cli \
  "DEMOA1 在 1000 还有多少可用库存？" \
  --gateway-url http://127.0.0.1:8080 --intent-mode rule
```

终端 3 - Workbench：

```bash
SAP_NEXUS_AGENT_ROOT=$(pwd) \
SAP_NEXUS_GATEWAY_URL=http://127.0.0.1:8080 \
SAP_NEXUS_INTENT_MODE=rule \
npm --prefix frontend run dev
```

打开 `http://127.0.0.1:3000/workbench`。

---

## 技术栈

| 层 | 技术 |
|----|------|
| Agent | Python package + OpenAI-compatible LLM + Rule 混合 |
| Gateway | Java 17 / Spring Boot / Gradle 多模块 |
| SAP 连接 | SAP JCo 3 (RFC) + SAP OData (HTTP) |
| 前端 | React / Next.js / TypeScript |
| 能力注册 | YAML + JSON Schema |
| 本体 | YAML + JSON Schema + 不可变内存图；OWL 骨架 offline；图数据库 Reserved |
| 编排 | OpenSpec / Comet 生命周期管理 |
| Runtime State | 本地进程内 Run/Approval + JSONL trace；共享/量产 durable runtime 待独立 change |
| 认证与授权 | 尚未产品化；共享环境需 server-owned principal / tenant / role / data scope / ApprovalActor |

---

## 文档

- [技术架构](docs/wiki/sap-nexus-agent-technical-architecture.md)
- [实施路线图](docs/wiki/sap-nexus-agent-implementation-roadmap.md)
- [技术选型](docs/wiki/sap-nexus-agent-technology-selection.md)
- [OpenHarness 对比](docs/wiki/sap-nexus-agent-openharness-semantic-orchestration.md)
- [DeerFlow 借鉴决策](docs/wiki/sap-nexus-agent-deerflow-adoption-analysis.md)
- [执行契约](openspec/specs/gateway-execution-contract/spec.md)
- [运行手册](docs/runbooks/README.md)

---

## 许可

本项目当前未包含开源许可证文件。公开发布前需添加明确的 `LICENSE`。

---

## 快速导航

| | |
|---|---|
| AGENTS.md | 项目级 Agent 行为规则 |
| CLAUDE.md | Agent 配置说明 |
| openspec/ | 规范与变更管理 |
| registry/ | 能力注册表 |
| ontology/ | OWL 本体骨架 |
| evals/ | 评估用例 |

# OData Gateway Read Pilot Runbook

## Document Version

| Field | Value |
|---|---|
| Runbook | `07-odata-gateway-read-pilot` |
| Version | `v0.2.1` |
| Status | `Implemented / Active` |
| Created | `2026-07-08` |
| Updated | `2026-07-09` |
| Workstream | sap-nexus-odata-gateway-read-pilot（Phase 4D OData Gateway Read Pilot 提前落地） |
| Related Change | `sap-nexus-odata-gateway-read-pilot` |
| Current Phase | Implemented；PO capability `status=active`；item detail/filtering archived |

---

## 1. Session Goal

提前落地 OData Gateway Read Pilot，把第二条 SAP read capability（采购订单 PO）从 JCo 路径切换为 OData 路径，验证 ODATA executor family 与多能力路由的工程化扩展路径不是纸面预留。

本 workstream 是 Phase 4D 的提前实施，参考 `sap-sto-create` 中 OData 客户端的 session、CSRF、`sap-client`、JSON error normalization 经验，落地统一 OData Gateway 的 read-only pilot。

---

## 2. Source Of Truth

Read these before changing architecture, implementation plan, or scope:

```text
AGENTS.md
docs/runbooks/README.md
docs/runbooks/07-odata-gateway-read-pilot.md
docs/wiki/sap-nexus-agent-technical-architecture.md
docs/wiki/sap-nexus-agent-implementation-roadmap.md
openspec/changes/po-odata-item-detail-filter/
```

---

## 3. Architecture Decisions

### 3.1 OData 用 Python（非 Java）

OData 是纯 HTTP 协议，无 Java 绑定强制依赖（JCo 用 Java 是 `sapjco3.jar` 强制）。因此 OData executor 用 Python 实现（`services/odata-service`），而非 Java Gateway 内部 executor。

- JCo executor 仍在 Java Gateway（`services/gateway` 多模块）。
- OData executor 在 Python `services/odata-service`，处理真实 OData HTTP、CSRF token、session cookie、JSON 归一。
- Java Gateway 侧新增 `ODataHttpProxyAdapter` 薄反代，把 OData 请求转发到 Python odata-service。
- Agent 侧保持单一端点（方案 B）：Agent 仍只调 Java Gateway，Gateway 内部 dispatcher 按 executor binding 路由到 JCo 或 OData 薄反代。

### 3.2 services/ 目录重组

`services/` 目录按连接器归集：

- `services/gateway`：Java 多模块（core / jco / odata / app），含 `ODataHttpProxyAdapter` 薄反代与 dispatcher 路由。
- `services/odata-service`：Python OData executor，真实 OData HTTP / CSRF / session / JSON 归一。
- 未来 CDS / REST / SQL executor 进 `services/` 同级目录。

### 3.3 超越 roadmap §17.2 与 §17.4

- §17.2 退出标准原为"不新增 executor family"；本 change 新增 `ODATA` executor family，经用户确认超越该约束。
- §17.4 原将 OData pilot 列为 Reserved，不早于 Eval seed、第二条 read、sandbox write pilot；本 change 把 OData pilot 前置于 sandbox write pilot，经用户确认调整顺序。
- row 14（`sap-nexus-odata-gateway-read-pilot`）从 Reserved 改为已完成直接实施。
- row 9（`sap-nexus-second-sap-read-capability`）由本 change 隐式满足：PO 即第二条 read，走 OData 路径。

---

## 4. Completed Implementation

### 4.1 Java Gateway 多模块重构

- `services/gateway` 从单一 `gateway-jco` 模块重组为多模块（core / jco / odata / app）。
- 新增 `ODataHttpProxyAdapter` 薄反代：把 OData executor 请求转发到 Python odata-service，不承载 OData HTTP / CSRF / session 逻辑。
- dispatcher 路由：按 executor binding 类型路由到 JCo executor 或 OData 薄反代。
- 守卫保持：Gateway 仍只接受 `capabilityId`，不接受 request-provided `rfcName` 或任意 OData URL。

### 4.2 Python odata-service

- 真实 OData HTTP 客户端：GET 请求、CSRF token fetch、session cookie 维护、`sap-client` header。
- JSON error normalization：SAP OData error response 归一到结构化 `ExecutionResult`。
- JSON response normalization：OData `value[]` / `d/results` 两种格式归一。
- PO item detail retrieval：按 header PO 调用 `A_PurchaseOrder('<po>')/to_PurchaseOrderItem` 并挂载 `items`。
- Item-level filtering：`material` / `plant` 在 item 归一后过滤，过滤后没有匹配 item 的 header 会被剔除。
- 不保存 OData URL、token、destination config；Registry 只保存 `serviceRef` / `entitySet` 等非敏感 binding metadata。

### 4.3 Agent 多能力路由

- `capability_selector` 支持多能力路由：Inventory 走 JCo，PO 走 OData。
- `run_query` 统一入口：Agent 仍只调 Java Gateway 单一端点，Gateway 内部 dispatcher 路由。
- 列表归一：PO 列表结果归一为统一 `ExecutionResult.data` 结构。
- narrative：PO 查询结果叙事化，只引用 `ReasoningFact` 字段。
- PO 意图识别：新增 PO 查询意图解析与参数抽取。

### 4.4 PO Eval Cases

- 新增 PO eval cases 覆盖 capability 命中、参数补全、缺参澄清、列表归一、narrative grounding。
- PO capability 绑定 `evals/purchase_order_cases.json`，覆盖 PO number、vendor、material + plant item filter。
- Inventory eval 保持 7/7。

---

## 5. Verification Evidence

| Layer | Command | Result |
|---|---|---|
| Java Gateway | `JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64 GRADLE_USER_HOME=/tmp/gradle-home /tmp/gradle-8.8/bin/gradle --no-daemon test` | `BUILD SUCCESSFUL` |
| Python odata-service | `PYTHONPATH=. ../../.venv/bin/python -m pytest tests/ -q` | 29 passed, 6 skipped |
| Python odata-service live | `SAP_ODATA_LIVE=1 PYTHONPATH=. ../../.venv/bin/python -m pytest tests/test_live_spike.py -q` | 6 passed |
| Agent | `scripts/verify-agent-callplan-evidence.sh` | 109 passed, 1 skipped; eval 7/7 and 13/13; OpenSpec 7/7 |
| PO eval | `cd agent && PYTHONPATH=. ../.venv/bin/python -m sap_nexus_agent.eval ../evals/purchase_order_cases.json` | 3/3 passed |
| Registry | `.venv/bin/python scripts/validate-registry-contract.py registry/capabilities.yaml` | Registry contract valid |
| OpenSpec | `openspec validate --all --strict` | 7 passed, 0 failed |
| Gateway live smoke | `POST /capabilities/MM.PurchaseOrder.GetList/execute` with PO `DEMOPO2`, material `DEMOA4B`, plant `5300` | success, `totalCount=1`, one matching item |

Java Gateway 测试覆盖 `services/gateway` 多模块（core / jco / odata / app）含 `ODataHttpProxyAdapter` 薄反代、dispatcher 路由与守卫。

Python odata-service 29 passed / 6 skipped：真实 OData HTTP / CSRF / session / JSON 归一、PO item detail retrieval、item-level filtering；live spike 6 passed。

Agent 109 passed / 1 skipped：PO 意图、selector 多能力路由、列表归一、narrative、`run_query` 统一入口。

---

## 6. Field Name Reference

字段名已通过 live PO 查询验证：

- entitySet = `A_PurchaseOrder`
- 单位字段 = `PurchaseOrderQuantityUnit`

live smoke 已确认 item 字段可用于查询和过滤：`PurchaseOrderItem`、`Material`、`Plant`、`OrderQuantity`、`PurchaseOrderQuantityUnit`。

---

## 7. Blockers

No current blocker for PO OData read activation.

Resolved on `2026-07-09`:

- SAP SICF service was reactivated by Basis/user side.
- PO capability changed to `status=active`.
- Live smoke passed through Java Gateway -> Python OData service -> SAP OData.
- Item detail retrieval and material / plant item-level filtering were verified with PO `DEMOPO2`.

---

## 8. Session Closeout - 2026-07-09

### Completed

- Java Gateway 多模块重构：`services/gateway` core / jco / odata / app + `ODataHttpProxyAdapter` 薄反代 + dispatcher 路由 + 守卫。
- Python odata-service：真实 OData HTTP / CSRF / session / JSON 归一。
- Agent 多能力路由：PO 意图 + selector 多能力路由 + 列表归一 + narrative + `run_query` 统一入口。
- PO eval cases 新增，inventory eval 保持。
- `services/` 目录按连接器归集重组。
- 架构决策落地：OData 用 Python + 方案 B 单端点保持 + 新增 ODATA executor family（超越 §17.2）。
- §17.4 顺序调整：OData pilot 前置于 sandbox write pilot。

### Verified

- Command: Java Gateway multi-module test
- Result: 79 tests passed
- Command: `services/odata-service` pytest
- Result: 26 passed, 5 skipped
- Command: agent test suite
- Result: 109 passed, 1 skipped
- Command: inventory + PO evals
- Result: inventory 7/7; PO + inventory 13/13
- Command: `openspec validate --all --strict`
- Result: 6/6 passed

### Blockers

- Resolved by the later PO Activation closeout in this same runbook.

### Next Start Here

1. Continue from `Session Closeout - 2026-07-09 PO Activation`.
2. Next recommended change remains `sap-nexus-sandbox-write-vertical-slice`（row 10）。


## Session Closeout - 2026-07-09 PO Activation

### Completed

- Activated `MM.PurchaseOrder.GetList` in `registry/capabilities.yaml` after SAP SICF reactivation.
- Added PO item detail retrieval through `A_PurchaseOrder('<po>')/to_PurchaseOrderItem`.
- Added `material` / `plant` item-level filtering and header pruning when no item matches.
- Fixed Java `ODataHttpProxyAdapter` request serialization so the Python OData service receives `serviceRef`, `entitySet`, and mapped parameters.
- Added `evals/purchase_order_cases.json` and linked it from the capability registry.

### Verified

- Command: `JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64 GRADLE_USER_HOME=/tmp/gradle-home /tmp/gradle-8.8/bin/gradle --no-daemon test`
- Result: `BUILD SUCCESSFUL`
- Command: `PYTHONPATH=. ../../.venv/bin/python -m pytest tests/ -q`
- Result: 29 passed, 6 skipped
- Command: `SAP_ODATA_LIVE=1 PYTHONPATH=. ../../.venv/bin/python -m pytest tests/test_live_spike.py -q`
- Result: 6 passed
- Command: `.venv/bin/python scripts/validate-registry-contract.py registry/capabilities.yaml`
- Result: Registry contract valid
- Command: `cd agent && PYTHONPATH=. ../.venv/bin/python -m sap_nexus_agent.eval ../evals/purchase_order_cases.json`
- Result: 3/3 passed
- Command: `scripts/verify-agent-callplan-evidence.sh`
- Result: 109 passed, 1 skipped; eval 7/7 and 13/13; OpenSpec 7 passed, 0 failed
- Command: `openspec list --json`
- Result: `po-odata-item-detail-filter` complete, 6/6 tasks
- Command: `openspec validate --all --strict`
- Result: 7 passed, 0 failed
- Command: Gateway live execute for PO `DEMOPO2`, material `DEMOA4B`, plant `5300`
- Result: success, `totalCount=1`, item `10`, quantity `20.000`, unit `EA`, net price `4212.27`, currency `CNY`

### Blockers

- None for PO OData read activation.
- Generated runtime trace `services/gateway/runtime/gateway-jco/traces.jsonl` should not be committed.

### Next Start Here

1. Archived change is `openspec/changes/archive/2026-07-09-po-odata-item-detail-filter/`.
2. Keep next recommended change as `sap-nexus-sandbox-write-vertical-slice`.
3. If Agent narrative must expose nested live `items`, update narrator/reasoning in a separate focused change.


## Archive Closeout - 2026-07-09

- Archived `po-odata-item-detail-filter` to `openspec/changes/archive/2026-07-09-po-odata-item-detail-filter/`.
- Merged the item-detail and item-filter delta into `openspec/specs/odata-gateway-read/spec.md`.
- `openspec list --json` now reports no active changes.

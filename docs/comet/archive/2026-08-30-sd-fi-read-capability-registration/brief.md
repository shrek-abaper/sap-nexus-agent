# Outcome

在 SAP Nexus Agent 的能力注册表中新增 3 个 READ-only（`kind: Function`）能力，
把 SD 和 FI 两个模块首次接入能力本体（当前仅有 4 个 MM 能力，SD/FI 均为 0）：

1. `SD.SalesOrder.GetList` — VA05 风格的销售订单列表查询 — `BAPI_SALESORDER_GETLIST`
2. `FI.AR.GetOpenItems` — 客户应收未清项查询 — `BAPI_AR_ACC_GETOPENITEMS`
3. `FI.AP.GetOpenItems` — 供应商应付未清项查询 — `BAPI_AP_ACC_GETOPENITEMS`

三者均为纯查询能力，不写入 SAP，不需要人工审批，用于支撑 Agent 演示中
"采购(MM) → 销售(SD) → 财务(FI)" 跨模块叙事里的只读核对环节。

# Scope

- `registry/capabilities.yaml`：新增 3 条 `status: active` 的 capability 条目，
  字段结构对齐现有 `MM.Inventory.GetAvailability` / `MM.Material.GetInfo`
  （`kind: Function`、`executor.type: JCO_RFC`、`inputs`/`outputs`/`intent`/
  `narrative`/`evalLinkage`/`governance` 全字段）。
- `registry/executor-bindings.yaml`：新增 3 条 `type: JCO_RFC` 绑定，声明
  `rfcName` + `allowedImports` + `allowedOutputs` 白名单。已通过公开 SAP
  文档（sapdatasheet.org 镜像的 SE37 签名）查证字段级签名，确认字段名：
  - `BAPI_SALESORDER_GETLIST`：imports `CUSTOMER_NUMBER` /
    `SALES_ORGANIZATION` / `MATERIAL` / `DOCUMENT_DATE` /
    `DOCUMENT_DATE_TO` / `PURCHASE_ORDER_NUMBER`；输出表 **`SALES_ORDERS`**
    （`BAPIORDERS` 行结构，字段 `SD_DOC`/`DOC_TYPE`/`DOC_DATE`/`NET_VALUE`/
    `CURRENCY`/`SOLD_TO`/`PURCH_NO_C`/`SALES_ORG`/`PLANT` 等）。
  - `BAPI_AR_ACC_GETOPENITEMS`：imports `COMPANYCODE` / `CUSTOMER` /
    `KEYDATE`；输出表名是 **`LINEITEMS`**（不是 `OPENITEMS`！这是与我最初
    假设不同的关键更正），`BAPI3007_2` 行结构字段 `DOC_NO`/`DOC_DATE`/
    `AMT_DOCCUR`/`CURRENCY`/`BLINE_DATE`/`CLEAR_DATE` 等。
  - `BAPI_AP_ACC_GETOPENITEMS`：imports `COMPANYCODE` / `VENDOR` /
    `KEYDATE`；输出表同样是 **`LINEITEMS`**（`BAPI3008_2` 行结构，字段与
    AR 侧同名同构）。
- `services/gateway/jco/`：现有 `InventoryAvailabilityExecutor` 是被
  `JcoRfcTechnicalAdapter` 路由到的**通用 READ executor**（除
  `MM.PR.CreateDraft` 外的所有 JCO_RFC 能力都走它），但它目前只能通用地读取
  EXPORT 参数（标量 + `PARAM.FIELD` 结构字段），TABLES 参数只有硬编码的
  `addMd04StockRowData`（专门认 `MRP_IND_LINES` 表和 5 个固定字段名）。
  本次 3 个新能力的主要输出都是 TABLES 参数（`SALES_ORDERS` /
  `OPENITEMS` / `OPENITEMS`），因此需要新增一段**通用表格提取逻辑**
  （按 `outputMapping` 指向的表名，通过 JCo 表元数据泛化读出所有行/所有
  字段，不为每个能力写专属提取方法），替代"再写 3 个 addXxxRowData"的方案。
  这是纯代码结构决策，不改变能力对外行为，我会在 Build 阶段直接落地。
- **【Build 阶段发现，扩大范围】`agent/sap_nexus_agent/` 讲述链路**：排查后
  发现 `factShape: list` 的讲述路径完全没有泛化——`orchestrator.py:1831`
  硬编码 `if fact_shape == "list": facts = build_purchase_order_facts(...)`，
  不分能力一律调用 PO 专属的事实构建函数；`narrator.py` 的
  `_build_list_messages`/`_list_fallback`/`_assert_po_evidence_complete`
  同样硬编码 PO 的字段名和中文标签。`MM.Material.GetInfo` 验证过的"纯声明
  能力，加能力无需改 Agent 代码"只对 single-value 成立，list 形态从未被
  第二个实例验证过。用户已确认选**方案 1（全量做）**：
  - `agent/sap_nexus_agent/orchestrator.py`：把第 1831 行的硬编码分支泛化为
    按 `capability_id` 路由到对应的 fact-builder 函数（核心调度文件，现有
    测试覆盖率高，本次改动回归风险最高的一处，需要重点回归验证）。
  - `agent/sap_nexus_agent/reasoning_fact.py`：新增
    `build_sales_order_facts()` / `build_ar_open_items_facts()` /
    `build_ap_open_items_facts()`，仿照 `build_purchase_order_facts` 的写法。
  - `agent/sap_nexus_agent/narrator.py`：泛化列表讲述路径，改为读取
    `narrative.fieldMapping` 声明的行模板（复用已有的 `_resolve_one_var`/
    `_declared_placeholders` 泛化基础设施，不改 schema），未声明
    `fieldMapping` 时保留 `MM.PurchaseOrder.GetList` 现有硬编码行为不变
    （零回归风险）。
- **【Build 阶段补记范围】本体声明**（沿用现有 4 个 MM 能力的既有惯例，
  不是新增建模方式）：
  - `ontology/fact-types.yaml`：新增 `sapnexus:SalesOrderListFact` /
    `sapnexus:ArOpenItemsFact` / `sapnexus:ApOpenItemsFact` 三个事实类型
    声明，供 capability `outputs[].factTypeRef` 引用。
  - `ontology/sd-salesorder.owl` / `ontology/fi-ar-openitems.owl` /
    `ontology/fi-ap-openitems.owl`：按模块新增 3 个 OWL 文件，`owl:imports`
    core 本体，声明业务对象类骨架 + 能力 NamedIndividual——与既有
    `ontology/mm-inventory.owl` / `mm-material.owl` / `mm-purchaseorder.owl`
    完全同构。
- `evals/`：为 3 个新能力各新增一个 eval 用例文件（或复用现有
  `evals/` 目录约定的命名/结构），覆盖 happy-path + 缺失必填参数场景。
- `docs/wiki/sap-nexus-agent-technical-architecture.md` /
  `docs/wiki/sap-nexus-agent-openharness-semantic-orchestration.md` /
  根 `README.md` / `registry/README.md`：更新"当前已注册能力"清单，
  加入这 3 个新能力（注意现有文档已经对 4 个 MM 能力的计数不一致，本次顺带
  修正为准确计数，但不做与本次无关的其它文档整理）。

# Non-goals

- 不新增任何 WRITE/Action 能力（销售订单创建、开票、FI 过账等留待后续变更）。
- 不新增 OData 执行器通路（`API_SALES_ORDER_SRV` 等现代 OData 服务本次不接入，
  全部走 `JCO_RFC`）。
- 不做 SD/FI 的客户/供应商主数据只读能力（`BAPI_CUSTOMER_GETDETAIL1` /
  `BAPI_VENDOR_GETDETAIL`）、总账余额查询（`BAPI_GL_GETGLACCPERIODBALANCES`）
  ——这些是此前讨论中的 P1 可选项，本次不做。
- 不改动 `schemas/capability.schema.json` / `schemas/executor-binding.schema.json`
  的必填字段结构（3 个新能力都能用现有 schema 表达）。
- 不新增/修改 `ontology/sapnexus-core.owl` 的**核心类定义**（沿用现有类骨架，
  core 本体零改动；按模块新增 `sd-*.owl` / `fi-*.owl` 文件属于范围内，见 Scope）。

# Acceptance examples

- 输入"查采购订单 1000 客户 1000 最近的销售订单" → Agent 命中
  `SD.SalesOrder.GetList` 意图，调用 `BAPI_SALESORDER_GETLIST`，返回订单列表
  （单号/日期/客户采购订单号/净值/币种），无需人工审批。
- 输入"客户 1000 在公司代码 1000 的应收有哪些" → Agent 命中
  `FI.AR.GetOpenItems`，调用 `BAPI_AR_ACC_GETOPENITEMS`，返回未清项列表
  （凭证号/凭证日期/到期日/金额/币种）。
- 输入"供应商 1000 在公司代码 1000 的应付" → Agent 命中
  `FI.AP.GetOpenItems`，调用 `BAPI_AP_ACC_GETOPENITEMS`，返回未清项列表。
- 三个能力在既没有过滤条件（SD）或缺少必填字段（FI 的客户/供应商号、
  公司代码）时，Agent 追问缺失字段而不是报错或调用 SAP。
- `MM.PR.CreateDraft` 的既有行为（WRITE + 人工审批）不受影响；现有 4 个 MM
  能力的既有测试/eval 保持全部通过（回归零容忍）。

# Constraints and invariants

- READ 能力禁止调用 `BAPI_TRANSACTION_COMMIT` / `BAPI_TRANSACTION_ROLLBACK`
  （项目级硬约束，AGENTS.md §2）。
- 三个新能力的 `governance` 必须是
  `sideEffect: none` + `requiresApproval: false` + `approvalPolicy: not_required`
  （`schemas/capability.schema.json` 对 `kind: Function` 的强制约束）。
- Gateway 侧不得接受调用方提供/覆盖 `rfcName`、`bindingId` 等技术细节
  （`services/gateway/README.md` 既有规则，`CapabilityRequest.collectTechnicalOverride`
  的技术覆盖检测需要覆盖到新增字段，如果新增了新的技术覆盖 key）。
- `registry/executor-bindings.yaml` 的 `allowedImports`/`allowedOutputs`
  是安全白名单，必须与 BAPI 真实签名一致（不得凭记忆猜测字段名）——本次
  已通过 librarian 查证公开 SAP 文档/社区资料获取字段级签名，若仍有字段
  命名因 SAP 版本而不确定，会在 PR/变更说明中明确标注，并建议后续 live
  smoke 验证时优先复核这几个字段。
- 现有回归基线（`agent/tests/`、`services/gateway` 测试、release-gate）必须
  保持全绿；本次改动不得让既有 4 个 MM 能力的任何测试变红。

# Decisions

- **capabilityId 命名**：`SD.SalesOrder.GetList`、`FI.AR.GetOpenItems`、
  `FI.AP.GetOpenItems`（沿用 `<Module>.<BusinessObject>.<Action>` 既有命名
  惯例，通过 `capability.schema.json` 的 `capabilityId` 正则）。
- **执行器**：全部 `JCO_RFC`，不做 OData（用户已确认收窄范围）。
- **公司代码（COMPANYCODE）**：两个 FI 能力都设为 **必填、无默认值**，
  与现有 `MM.Inventory.GetAvailability`/`MM.Material.GetInfo` 对 `plant`
  的处理方式一致（SAP 组织类标识符从不静默取默认值，缺失时追问用户）。
- **SD.SalesOrder.GetList 过滤字段**：客户号/销售组织/物料/单据日期范围
  均为可选，但至少需要一个（复用 `MM.PurchaseOrder.GetList` 的
  `intent.requireAny` 声明式模式），不允许无条件全表查询。
- **表格输出提取方式**：新增通用 TABLES 提取逻辑（按 `outputMapping` 中
  声明的表名，通过 JCo 表元数据泛化取出所有行的所有字段），而不是给每个
  新能力各写一个 `addXxxRowData` 专属方法；不改动既有 `addMd04StockRowData`
  （保持向后兼容，零回归风险）。这是实现方式决策，不影响能力对外行为。
- **KEYDATE（关键日期）**：`FI.AR.GetOpenItems` / `FI.AP.GetOpenItems` 的
  `keydate` 字段设为 `required: false`，`binding.sources` 配置
  `default` 取系统当前日期（今天），用户话语中显式提供的日期可覆盖默认值
  （用户已确认选 A）。

# Open questions

（无 — 用户已于 2026-08-30 确认共识摘要，Shape 完成）

# Verification expectations

- `scripts/validate-registry-contract.py registry/capabilities.yaml`
  （或对应校验脚本，含新增的 `registry/executor-bindings.yaml`）通过。
- `agent/tests/test_registry_contract.py` 全绿。
- Gateway 侧新增只读表格提取逻辑的单元测试（沿用
  `InventoryAvailabilityExecutorTest.java` 的测试风格），覆盖：
  - 3 个新能力各自的 happy-path 表格提取
  - 既有 `MM.Inventory.GetAvailability`（MD04）行为不受影响的回归测试
- `agent/sap_nexus_agent/reasoning_fact.py` 新增 3 个 `build_XXX_facts()`
  的单元测试（happy-path + 空列表）。
- `agent/sap_nexus_agent/orchestrator.py` 泛化后的 list 分支路由测试：
  至少覆盖 4 个 list 能力（PO + 新 3 个）分别路由到各自 fact-builder，
  且 `MM.PurchaseOrder.GetList` 现有测试全部保持通过（零回归）。
- `agent/sap_nexus_agent/narrator.py` 泛化后的列表讲述测试：新 3 个能力
  按 `fieldMapping` 行模板正确渲染；`MM.PurchaseOrder.GetList` 无
  `fieldMapping` 声明时走原硬编码路径，现有 narrator 测试全部保持通过。
- 3 个新能力各自的 eval 用例（happy-path + 缺失必填参数 + 未提供任何过滤
  条件）全部通过。
- `npm --prefix frontend run verify`（如果新增能力改动了 frontend 侧已注册
  能力清单展示逻辑，否则可跳过）。
- 全量既有测试基线不回归（`.venv/bin/python -m pytest agent/tests/ -v`、
  `services/gateway` Gradle test）——这是本次验证的重点，因为改动涉及
  `orchestrator.py` 这个全仓库回归风险最高的调度文件。

# Acceptance evidence

<!-- comet-native:acceptance-evidence:start -->
[
  {
    "acceptance_id": "acceptance-4d26c388c637101a8a15976e7ba0c3e5f4daf320c4a439d5fd218531190d285b",
    "status": "passed",
    "evidence_refs": [
      "runtime/evidence/receipts/5dd19f2eda4d66d2ae77fb694a8caa6692f0c4909118c68da4fe7947f4e876e9.json"
    ]
  },
  {
    "acceptance_id": "acceptance-588d4b7911fef57f86e901ade3abfc41f2645d8621af35d060e0e1fcd2acd8f0",
    "status": "passed",
    "evidence_refs": [
      "runtime/evidence/receipts/5dd19f2eda4d66d2ae77fb694a8caa6692f0c4909118c68da4fe7947f4e876e9.json"
    ]
  },
  {
    "acceptance_id": "acceptance-5ac9147e8fb01c25ce4886c07135d06f9c703c53cf87956f9d3a98696526597b",
    "status": "passed",
    "evidence_refs": [
      "runtime/evidence/receipts/5dd19f2eda4d66d2ae77fb694a8caa6692f0c4909118c68da4fe7947f4e876e9.json"
    ]
  },
  {
    "acceptance_id": "acceptance-ce6be8d406ab15f72b3de30f59916789b2fef1f17cf46e744ea71597c554e918",
    "status": "passed",
    "evidence_refs": [
      "runtime/evidence/receipts/d894db78a07d0a22adf9fa6c3dfda9132d33003c75b15602e81e86b7c3090512.json",
      "runtime/evidence/receipts/e1649cba29ac3a4c979458d82adee5d3dabd2b88263c9fa13f104e65e195271c.json"
    ]
  },
  {
    "acceptance_id": "acceptance-fcc66d188cb23cb68610abf7cd6f479dac4a14bd4e4af0986b9f9456f735dfa4",
    "status": "passed",
    "evidence_refs": [
      "runtime/evidence/receipts/5dd19f2eda4d66d2ae77fb694a8caa6692f0c4909118c68da4fe7947f4e876e9.json"
    ]
  }
]
<!-- comet-native:acceptance-evidence:end -->

# Commands and results

| 命令 | 结果 | 说明 |
|---|---|---|
| `.venv/bin/python -m pytest agent/tests/ -q` | **1574 passed, 1 skipped, 2 xfailed, 0 failed** | 接手时基线为 51 failed；全部修复后零回归 |
| `scripts/comet-verify-gateway.sh`（Gradle `test`，全模块） | **BUILD SUCCESSFUL** | `:jco:test` 21 项通过，含新增 `GenericTableExtractionTest` 5 项 |
| `.venv/bin/python -m pytest agent/tests/test_eval_runner.py::test_matcher_eval_routes_existing_files_through_legacy_path agent/tests/test_sd_fi_read_facts.py -q` | 通过 | 3 个新 eval 文件（各 3 例）+ 新增 20 项单测 |
| `npm --prefix frontend run verify` | **52 files / 525 tests passed** + build 成功 | 未改动 frontend，作为零回归确认 |
| `openspec list --json && openspec validate --all --strict` | **21 passed, 0 failed** | spec store 校验 |
| `.venv/bin/python scripts/validate-registry-contract.py registry/capabilities.yaml` | `Registry contract valid`（exit 0） | 既有 MM 能力的 `extraction` 弃用告警为改动前既有状态 |
| `.venv/bin/python scripts/validate-semantic-planning-contract.py` | `Semantic planning contract valid` | `snapshotId=sha256:04ab3bab…fde115b` |

关键验证事实：

- **3 个新能力端到端命中**：`evals/sales_order_list_cases.yaml` / `ar_open_items_cases.yaml` /
  `ap_open_items_cases.yaml` 各 3 例（happy-path × 2 或 1、缺失必填/缺失过滤条件），断言
  `capabilityId`、`validateCalls`、`executeCalls` 与响应中的事实字段。缺参用例断言
  `validateCalls: 0` / `executeCalls: 0`，即 Agent 追问而非触达 SAP。
- **`responseContains` 只断言标识符与金额**：叙事经真实 LLM 生成，币种 `CNY` 会被改写为
  “人民币”，因此币种不作断言（与既有 `purchase_order_cases.json` 约定一致）；连跑 3 次稳定通过。
- **意图消歧回归**：`test_intent.py` / `test_extraction_parity.py` 中「查供应商 X 的采购订单」
  「近 30 天未清采购订单」等既有用例全部恢复通过——新能力不再抢占 PO 意图。
- **PO 讲述零回归**：`MM.PurchaseOrder.GetList` 未声明 `narrative.fieldMapping`，
  `narrate_list` 走原 `_narrate_po_list` 路径；`test_reasoning_narrator.py` 全部通过。
- **MD04 提取零回归**：`MRP_IND_LINES` 不出现在任何 `outputMapping`，通用 TABLES 提取不可达该表；
  `GenericTableExtractionTest.md04KeepsItsOwnExtractionBecauseNoCapabilityDeclaresThatTable` 锁定此边界。
- **READ 边界**：3 个新能力全部 `sideEffect: none` / `requiresApproval: false` /
  `approvalPolicy: not_required`，走只读 executor，不触发 `BAPI_TRANSACTION_COMMIT` / `ROLLBACK`。

# Skipped checks

- **未做 live SAP smoke**：本次未连接真实 SAP 系统执行三个 BAPI。字段级签名来自公开 SAP 对象目录
  （sapdatasheet.org 的 SE37 镜像），未经运行时复核。
- **未验证 `documentDate` 的 SAP 日期格式往返**：fixture 用 `20260101` 与 `2026-08-01` 两种形态，
  真实 BAPI 返回的 `DOC_DATE` 格式未经 live 确认。
- **未做 `MM.PR.CreateDraft` 的 live 写入回归**：仅以既有单测/eval 覆盖，写路径未改动。

# Spec consistency

本次为 Native 变更，不产出 OpenSpec spec delta。`openspec validate --all --strict` 作为项目级
校验运行并通过（21/21）。

brief 的 Scope 在 Build 阶段补记了两处已落地但原先未列入的范围（`ontology/fact-types.yaml`
与 3 个模块 OWL 文件），Non-goals 相应收窄为「不改 `sapnexus-core.owl` 核心类定义」；该扩大后的
契约已由用户确认，并随 Build→Verify 转换的 `--confirmed` 重新记录。

# Known limitations and risks

1. **字段名风险（最高）**：`allowedImports` / `allowedOutputs` 与行字段映射依据公开文档而非 live
   签名。FI 输出表已确认为 `LINEITEMS`（不是 `OPENITEMS`）；后续 live smoke 应优先复核
   `AMT_DOCCUR`、`BLINE_DATE`、`PURCH_NO_C`、`SD_DOC` 四个列名。
2. **通用 TABLES 提取读为文本**：executor 不判断列是数值还是日期，数值化在 Python fact builder
   完成（`_optional_number`）。非数值金额只留在 evidence，`fact.value` 为 `None`。
3. **`_LIST_FACT_BUILDERS` 是 Python 侧注册表**：新增 list 形态能力仍需在此登记一行，否则
   fail closed。这不是纯声明式；`factShape: list` 只表达「多行」，不表达行是什么业务对象。
4. **裸关键词归属是约定**：裸「订单」归 PO、裸「未清」归 PO 的 `openOnly` 语义。若将来 SD/FI
   需要抢占，必须显式重新设计，而不是再加一个裸关键词。
5. **eval 断言依赖真实 LLM**：`responseContains` 已规避可被改写的词元，但 LLM 输出仍非确定性；
   LLM 不可用时走确定性 fallback，两条路径都包含被断言的词元。

# Conclusion

**通过。** 3 个 READ-only 能力（`SD.SalesOrder.GetList` / `FI.AR.GetOpenItems` /
`FI.AP.GetOpenItems`）已完成注册、本体声明、Gateway 通用表格提取、事实构建、列表讲述泛化、
eval 接入与文档修正。5 项验收项全部有当前受体支撑；agent 1574 项、gateway 全模块、frontend 525 项
测试全绿，既有 4 个 MM 能力零回归。遗留风险集中在未经 live SAP 复核的字段名，已在上方列明。

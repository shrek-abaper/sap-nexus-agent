# Verification Report - po-fact-nested-items

| Field | Value |
|---|---|
| Change | `po-fact-nested-items` |
| Workflow | Comet tweak |
| Verify mode | full (8 tasks > 3, 1 delta capability) |
| Date | 2026-07-09 |
| Language | zh-CN |
| Result | PASS |

## 变更概要

修复 PO fact builder 不处理真实 OData 嵌套 `items[]` 结构的既有 bug（`flexible-intent-recognition` 让 PO 可达后暴露）：

- `build_purchase_order_facts` 兼容嵌套（真实 OData：header.purchaseOrder/supplier + header.items[].plant/material/orderQuantity/purchaseOrderUnit）与扁平（既有测试）两种形态。
- 抽 `_build_po_fact(header, item, context)` helper：header 供 purchaseOrder/supplier，item 供 plant/material/orderQuantity/purchaseOrderUnit，item 优先回退 context/header。
- 空 `items[]` 不生成 fact（与无匹配语义一致）。

不改 narrator / OData service / 意图识别 / 前端。

## 改动文件

修改：
- `agent/sap_nexus_agent/reasoning_fact.py`（`build_purchase_order_facts` 重构 + `_build_po_fact` helper）
- `agent/tests/test_reasoning_narrator.py`（新增 4 个嵌套 items 测试）

## 验证证据（fresh run）

| # | 检查项 | 结果 |
|---|---|---|
| 1 | tasks.md 全部完成 | 8/8 PASS |
| 2 | 实现符合 design.md | D1-D3 PASS（嵌套/扁水分流、字段优先级、空 items 不生成 fact） |
| 3 | delta spec 场景覆盖 | 3 scenarios PASS（嵌套、扁平、空 items） |
| 4 | 端到端 CLI | status=success，返回 PO 列表 PASS |

### 命令输出

| 命令 | 退出码 | 关键输出 |
|---|---|---|
| `pytest agent/tests -q` | 0 | `133 passed, 1 skipped` |
| `sap_nexus_agent.eval evals/purchase_order_cases.json` | 0 | `Eval passed: 3/3` |
| `verify-agent-callplan-evidence.sh` | 0 | `133 passed, 1 skipped`；eval 7/7 + 13/13；openspec 7/7 |
| CLI `查询采购订单DEMOPO1 --json` | - | `status: success`，`采购订单 DEMOPO1：供应商 1100，物料 DEMOA5，工厂 5400，数量 1.000 EA。` |

## 端到端确认

CLI 直测「查询采购订单DEMOPO1」：
- `status: success` ✓
- `responseText: 采购订单 DEMOPO1：供应商 1100，物料 DEMOA5，工厂 5400，数量 1.000 EA。` ✓
- 不再返回 `采购订单事实缺少必要字段，无法生成结论。` ✓

原始 bug 已修复：PO fact builder 正确展开嵌套 items[]，narrator 生成完整中文结论。

## 代码审查

`review_mode: off`（tweak 默认），跳过自动 code review。正确性由 spec 场景测试（嵌套/扁平/空 items）+ 端到端 CLI 覆盖。

## 已知偏差

- 代码未提交：按用户「保持现状」选择，改动留在 main 工作区。分支处理 = 保持现状（Option 3）。

## 安全检查

- 无硬编码密钥 / token / 凭据。
- 未引入新依赖。
- 未触及 SAP WRITE 路径、未改 redaction、未改意图识别闭集校验。

## 分支处理

- 环境：normal repo，当前分支 `main`。
- 用户选择：保持现状（保留工作区，稍后处理）。
- `branch_status: handled`。

## 结论

验证通过（PASS）。可推进至 archive 阶段。

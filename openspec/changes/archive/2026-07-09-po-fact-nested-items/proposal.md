## Why

柔性意图识别 change（`flexible-intent-recognition`）让 PO 查询可达后，暴露了一个既有 bug：`build_purchase_order_facts`（`reasoning_fact.py`）从 PO header 直接读 `plant`/`material`/`orderQuantity`/`purchaseOrderUnit`，但真实 OData service（`services/odata-service`）把这些 item 级字段嵌套在 `header.items[]` 子数组里。结果所有 item 级证据字段为 None，narrator 的 narrative guard 失败，端到端 CLI 返回 `采购订单事实缺少必要字段，无法生成结论。`。

此前 CLI 到不了 PO（库存-only 入口）故未暴露；现在 PO 可达，需修复 fact builder 以匹配真实 OData 嵌套结构。

## What Changes

- 修改 `agent/sap_nexus_agent/reasoning_fact.py` 的 `build_purchase_order_facts`：兼容**扁平**与**嵌套**两种 PO 数据形态：
  - 嵌套（真实 OData）：header 含 `purchaseOrder`/`supplier`，item 级字段在 `header.items[]`；逐个 item 生成一个 fact，从 header 取 purchaseOrder/supplier，从 item 取 plant/material/orderQuantity/purchaseOrderUnit。
  - 扁平（既有测试形态）：PO 项直接含全部字段；保持现有行为，一个 PO 项一个 fact。
- 更新 `agent/tests/test_reasoning_narrator.py`：现有扁平用例保持；新增嵌套 `items[]` 用例，验证从 header.items[] 正确提取 item 级字段生成 fact。
- 不改 narrator、OData service normalizer/server、意图识别层（已正确）。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `agent-callplan-evidence`: 新增 PO ExecutionResult 到 ReasoningFact 转换的验收--fact builder 须处理真实 OData 嵌套 `items[]` 结构（header.purchaseOrder/supplier + header.items[].plant/material/orderQuantity/purchaseOrderUnit），同时兼容扁平形态。

## Impact

- Agent 代码（Python）：
  - 修改 `agent/sap_nexus_agent/reasoning_fact.py`（`build_purchase_order_facts` 嵌套 items 展开）
- 测试：
  - 更新 `agent/tests/test_reasoning_narrator.py`（新增嵌套 items 用例，保留扁平用例）
- 不改 narrator / OData service / 意图识别 / 前端 / registry。
- 验证：`pytest agent/tests` + PO eval + `openspec validate --all --strict` + `scripts/verify-agent-callplan-evidence.sh` 通过；端到端 CLI「查询采购订单DEMOPO1」返回 PO 列表（非 narrative guard 失败）。

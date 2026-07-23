## 1. PO fact builder 嵌套 items 支持

- [x] 1.1 新增 `agent/tests/test_reasoning_narrator.py` 嵌套 items 测试（先红）：构造 `purchaseOrders` 含 `items[]` 的 ExecutionResult，断言每 item 生成一个 fact，evidence 从 header 取 purchaseOrder/supplier、从 item 取 plant/material/orderQuantity/purchaseOrderUnit。
- [x] 1.2 修改 `agent/sap_nexus_agent/reasoning_fact.py` 的 `build_purchase_order_facts`：按 `items` 字段非空 list 分流嵌套/扁平；抽 `_build_po_fact(header, item, ...)` helper 处理字段优先级；空 items 不生成 fact。
- [x] 1.3 确认既有扁平测试 `test_build_po_facts_creates_one_fact_per_item` 仍通过。

## 2. 验证与端到端

- [x] 2.1 运行 `PYTHONPATH=agent .venv/bin/python -m pytest agent/tests -q` 通过。
- [x] 2.2 运行 `PYTHONPATH=agent .venv/bin/python -m sap_nexus_agent.eval evals/purchase_order_cases.json` 通过。
- [x] 2.3 运行 `openspec validate --all --strict` 通过。
- [x] 2.4 运行 `scripts/verify-agent-callplan-evidence.sh` 通过。
- [x] 2.5 端到端：CLI 直测 `查询采购订单DEMOPO1` 返回 PO 列表（非 narrative guard 失败）。

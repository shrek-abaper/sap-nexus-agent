## Context

`build_purchase_order_facts`（`reasoning_fact.py:98-154`）假设 `result.data["purchaseOrders"]` 列表每项是扁平结构，直接 `item.get("plant")` 等。但真实 OData service（`services/odata-service/odata_service/server.py:114`）把 item 级字段嵌套在 `purchase_order["items"]` 子数组：

```json
{"purchaseOrders": [{"purchaseOrder": "DEMOPO1", "supplier": "1100", "items": [{"plant": "5400", "material": "DEMOA5", "orderQuantity": "1.000", "purchaseOrderUnit": "EA"}]}]}
```

header 无 plant/material/orderQuantity/purchaseOrderUnit -> fact 证据全 None -> `narrate_purchase_order_facts` 的 guard（检查 `_PO_REQUIRED_EVIDENCE` 全非 None）抛 `NarrativeGuardError`。

现有测试 `test_build_po_facts_creates_one_fact_per_item` 用扁平数据，掩盖了此 bug。

## Goals / Non-Goals

**Goals:**
- `build_purchase_order_facts` 兼容嵌套 `items[]`（真实 OData）与扁平（既有测试）两种形态。
- 嵌套形态：每个 item 生成一个 fact，header 供 purchaseOrder/supplier，item 供 plant/material/orderQuantity/purchaseOrderUnit。
- 扁平形态：保持现有行为（一个 PO 项一个 fact）。
- 端到端 CLI PO 查询返回列表（非 narrative guard 失败）。

**Non-Goals:**
- 不改 narrator / OData service normalizer/server / 意图识别 / 前端。
- 不改 `_PO_REQUIRED_EVIDENCE` guard（仍是全字段非 None；嵌套 items 每项应含全字段）。
- 不处理 PO header 无 items 的边界（空 items -> 该 PO 不生成 fact，与空列表语义一致）。

## Decisions

### D1: 兼容扁平 + 嵌套，按 `items` 字段存在性分流

```python
for po in purchase_orders:
    nested_items = po.get("items")
    if isinstance(nested_items, list) and nested_items:
        for item in nested_items:
            facts.append(_build_po_fact(agent_trace_id, result, po, item))
    else:
        facts.append(_build_po_fact(agent_trace_id, result, po, po))  # 扁平：item 即 po 本身
```

`_build_po_fact(header, item)`：purchaseOrder/supplier 从 header 取（item 也可能含 purchaseOrder，优先 item），plant/material/orderQuantity/purchaseOrderUnit 从 item 取。

### D2: 字段优先级

- `purchaseOrder`：`item.get("purchaseOrder") or header.get("purchaseOrder")`（item 通常含 purchaseOrder，回退 header）
- `supplier`：`header.get("supplier")`（item 级一般无 supplier）
- `plant`/`material`/`orderQuantity`/`purchaseOrderUnit`：`item.get(...) or context.get(...) or header.get(...)`（item 优先，回退 context/header 兼容扁平）

### D3: 空 items 不生成 fact

嵌套形态若 `items` 为空列表，该 PO 不生成 fact（与「无匹配」语义一致）。若所有 PO 都无 items，facts 为空，narrator 返回「无匹配记录。」（narrator 现有空列表行为）。

## Risks / Trade-offs

- **[扁平与嵌套误判]** -> 按 `items` 字段是否为非空 list 分流；扁平形态无 `items` 字段，走扁平分支。安全。
- **[item 字段缺失]** -> narrator guard 仍校验全字段；缺失则抛 NarrativeGuardError（既有行为，不掩盖）。
- **[既有扁平测试]** -> 保留，新增嵌套测试；两条路径都覆盖。

## Migration Plan

纯 agent 侧修复，无迁移：
1. 改 `build_purchase_order_facts` + 抽 `_build_po_fact` helper。
2. 加嵌套测试。
3. 验证全量 + 端到端。
4. 归档。

**回滚**：`git revert` 即可。

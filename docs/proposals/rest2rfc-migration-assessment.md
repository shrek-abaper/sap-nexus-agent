# rest2rfc 迁移评估清单

状态日期：2026-09-25（当日 live 实测 + 正式 harness 证据）。Comet change
`add-rest-json-executor`。

## 当日 live 结论（系统 SAT / client 800）

| # | 事实 | 证据 |
| --- | --- | --- |
| 1 | **部署版本只回 TABLES**；EXPORTING/CHANGING 不回传（源码仓库 `'ECT'` 版本未部署到 SAT） | `BAPI_MATERIAL_GET_DETAIL` 真实入参 → 200 但 body `{}` |
| 2 | TABLES 全回，**入参表也在响应中回显**；外层参数名小写 | `BAPI_MATERIAL_GETLIST` 响应含全部 TABLES |
| 3 | 同名字段两路表示差异：SICF 保留内部格式（ALPHA 前导零、CURR 短刻度、初始 DATS 为空）；JCo 为显示格式（去前导零、CURR 全刻度、初始 `0000-00-00`）——属表示层差异，数值/语义一一对应 | 全量比对 |
| 4 | **AP 垂直切片 live 等价成立**：vendor `0000003120` / company `2100` / keydate `2026-09-25`，双路各 **28,197 行**；131 字段集一致、无缺余；逐单元（初始值/数值感知）**3,693,807 个零实质差异**；正式 harness 输出 `equivalence confirmed for 28197 open item rows` | `/tmp/ap_sicf2.json`、`/tmp/ap_jco2.json`、harness receipt |
| 5 | 注册步骤实证：SM30 在 ZTIF_GENERAL_CON 加一行后函数立即生效；该函数 KEYDATE 在 binder 中强制必填（registry 里标记 optional，运行时由 binder 拦截） | 404 → 400(Mandatory KEYDATE) → 200 |
| 6 | `RFC_READ_TABLE` 可用于数据勘探（供应商 E18858、BSIK 索引定位真实未清项） | LFA1/LFB1/BSIK |

## 逐 RFC 归属

| 能力 / RFC | 输出形态 | 归属 |
| --- | --- | --- |
| `FI.AP.GetOpenItems` / BAPI_AP_ACC_GETOPENITEMS | `LINEITEMS` + `RETURN` 均 TABLES | **可迁（live 已证实等价）**；翻转走后续独立变更 |
| `FI.AR.GetOpenItems` / BAPI_AR_ACC_GETOPENITEMS | 同 AP 同构（BAPI3007_2） | **可迁候选**；注册后同款 harness 验证 |
| `SD.SalesOrder.GetList` / BAPI_SALESORDER_GETLIST | `SALES_ORDERS` + RETURN TABLES | **可迁候选**；注册后逐行比对 |
| `MM.Inventory.GetAvailability` / BAPI_MATERIAL_STOCK_REQ_LIST | 主输出 `MRP_IND_LINES`（WB 行 59.0/2026-09-25 已 live 等价）；该函数 `RETURN` 为 EXPORTING 结构 → SICF 下缺失 | **有条件可迁**：接受 returnMessages 缺失，或待网关升级 |
| `MM.Material.GetInfo` / BAPI_MATERIAL_GET_DETAIL | 输出全 EXPORTING；live body `{}` | **保留 JCO_RFC**；待网关升级 EXPORTING 回传后重评，或 typed 契约 |
| `MM.PR.CreateDraft` / BAPI_PR_CREATE | WRITE，EXPORTING NUMBER | **保留 JCO_RFC** |
| `MM.PurchaseOrder.GetList` | OData | **不适用** |

## 动态反射通用检查

1. 当前部署：所需输出必须全部是 TABLES；
2. 参数全 DDIC 类型、无 RAW/XSTRING；元数据 `TABNAME-FIELDNAME` 形态可能 NOT_SUPPORTED；
3. live 逐行比对（harness 已内置初始 DATS、ALPHA、CURR 刻度归一）；凭据三路共用
   （SAP_HOST/CLIENT/USER/PASSWORD；JCo 用 SYSNR，HTTP 用 SAP_HTTP_PORT）；
4. 非 200 响应体为空，只有状态码与 reason phrase；
5. `LOGFLG=X` 写日志触发 COMMIT WORK；只读对象无 update task，无碍。

## 建议顺序

1. `FI.AP.GetOpenItems` 翻转（等价已证）→ 独立变更；
2. `FI.AR.GetOpenItems`；
3. `SD.SalesOrder.GetList`；
4. `MM.Inventory.GetAvailability`（接受 returnMessages 差异）。

`MM.Material.GetInfo` 在网关 EXPORTING 修复并实测前不动。

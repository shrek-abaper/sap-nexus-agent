# rest2rfc 迁移评估清单

状态日期：2026-09-26 更新（网关 EXPORTING 修复后重验）。Comet change
`add-rest-json-executor`。

## 2026-09-26 重验：网关已回传 EXPORTING 结构

| # | 事实 | 证据 |
| --- | --- | --- |
| 1 | `BAPI_MATERIAL_GET_DETAIL` 现回传全部 EXPORTING：`material_general_data`（matl_desc/base_uom=EA 等）、`materialplantdata`、`materialvaluationdata`、`return`（EXPORTING 结构，type=S） | SICF live 调用 P0274635AB/5260 |
| 2 | MM.Material 数据与 JCo 等价：两路均只产出 `baseUnitOfMeasure="EA"`（material/plant 字段在结构中不存在、pur_group 空 → 两路均省略） | JCo execute 同输入 |
| 3 | `BAPI_MATERIAL_STOCK_REQ_LIST` 的 RETURN 结构现回传完整文本（MD/053 "Requirements/stock list ... has been created"） | SICF live |
| 4 | 结论更新：此前"EXPORTING 丢失"导致的迁移阻塞（MM.Material 保留、Inventory 有条件、SD 错误缺文本）**在网关侧已解除** | — |
| 5 | **新的剩余阻塞在 Java adapter，不在网关**：REST_JSON adapter 尚需支持 ① outputMapping 点路径抽取（`MATERIAL_GENERAL_DATA.BASE_UOM` → 嵌套结构字段）；② `MRP_IND_LINES.WB.AVAIL_QTY1` 式 TABLE.行.字段路径；③ RETURN 为结构（非 list）时的消息映射与业务错误识别 | adapter 现状只做顶层键查找 |


## 当日 live 结论（系统 SAT / client 800）

| # | 事实 | 证据 |
| --- | --- | --- |
| 1 | **部署版本只回 TABLES**；EXPORTING/CHANGING 不回传（源码仓库 `'ECT'` 版本未部署到 SAT） | `BAPI_MATERIAL_GET_DETAIL` 真实入参 → 200 但 body `{}` |
| 2 | TABLES 全回，**入参表也在响应中回显**；外层参数名小写 | `BAPI_MATERIAL_GETLIST` 响应含全部 TABLES |
| 3 | 同名字段两路表示差异：SICF 保留内部格式（ALPHA 前导零、CURR 短刻度、初始 DATS 为空）；JCo 为显示格式（去前导零、CURR 全刻度、初始 `0000-00-00`）——属表示层差异，数值/语义一一对应 | 全量比对 |
| 4 | **AP 垂直切片 live 等价成立**：vendor `0000003120` / company `2100` / keydate `2026-09-25`，双路各 **28,197 行**；131 字段集一致、无缺余；逐单元（初始值/数值感知）**3,693,807 个零实质差异**；正式 harness 输出 `equivalence confirmed for 28197 open item rows` | `/tmp/ap_sicf2.json`、`/tmp/ap_jco2.json`、harness receipt |
| 4b | **AR 追加实测等价成立（2026-09-25）**：customer `C00403` / company `2100` / keydate `2026-09-25`，双路各 **1,355 行**；124 字段集一致；**168,020 个单元格零实质差异** | `/tmp/ar_sicf.json`、`/tmp/ar_jco.json` |
| 4c | **SD 追加实测等价成立（2026-09-25）**：customer `C00002` / sales org `2110` / DOCUMENT_DATE 收窄，双路各 **5,164 行**；54 字段集一致；**278,856 个单元格零实质差异**。该 BAPI 不带日期收窄时对该客户会 short dump（JCo SAP_BUSINESS_ERROR ↔ SICF HTTP 500，失败结论一致） | `/tmp/so_sicf2.json`、`/tmp/so_jco2.json` |
| 5 | 注册步骤实证：SM30 在 ZTIF_GENERAL_CON 加一行后函数立即生效；该函数 KEYDATE 在 binder 中强制必填（registry 里标记 optional，运行时由 binder 拦截） | 404 → 400(Mandatory KEYDATE) → 200 |
| 6 | `RFC_READ_TABLE` 可用于数据勘探（供应商 E18858、BSIK 索引定位真实未清项） | LFA1/LFB1/BSIK |

## 逐 RFC 归属

| 能力 / RFC | 输出形态 | 归属 |
| --- | --- | --- |
| `FI.AP.GetOpenItems` / BAPI_AP_ACC_GETOPENITEMS | `LINEITEMS` + `RETURN` 均 TABLES | **可迁（live 已证实等价）**；翻转走后续独立变更 |
| `FI.AR.GetOpenItems` / BAPI_AR_ACC_GETOPENITEMS | 同 AP 同构（BAPI3007_2） | **可迁（live 已证实等价：1,355 行）** |
| `SD.SalesOrder.GetList` / BAPI_SALESORDER_GETLIST | `SALES_ORDERS` TABLE；**RETURN 实为 EXPORTING 结构**（live 确认成功时无 return 键） | **可迁（主事实 live 等价已证：5,164 行）**；业务错误时 SICF 仅给非 200 状态、缺 RETURN 文本（fail-closed 分类不变）；建议沿用日期收窄避免大数据 dump |
| `MM.Inventory.GetAvailability` / BAPI_MATERIAL_STOCK_REQ_LIST | 主输出 `MRP_IND_LINES`（WB 行已 live 等价）；RETURN 结构 09-26 起可回传（含文本） | **可迁候选**：前置 adapter 支持点/表路径与结构 RETURN |
| `MM.Material.GetInfo` / BAPI_MATERIAL_GET_DETAIL | EXPORTING 结构 09-26 起可回传，`base_uom=EA` 与 JCo 等价 | **可迁候选**：前置 adapter 支持点路径抽取与结构 RETURN |
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

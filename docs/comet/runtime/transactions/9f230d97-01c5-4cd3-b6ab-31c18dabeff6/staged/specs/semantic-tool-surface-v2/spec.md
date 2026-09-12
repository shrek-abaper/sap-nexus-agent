# Semantic Tool Surface v2 Specification

## Purpose

把 harness 可见语义工具面从 1 个 READ 工具扩为 4 个（3 READ + 1 WRITE），契约
升 contractVersion=2，覆盖 MM/SD/FI 全量只读能力与 PR 补货写提议；dsh 工具
execute 以同进程函数调用服务端治理层（不经 HTTP 自调用）。

## Requirements

### Requirement: Four governed semantic tools

v2 工具枚举 SHALL 为：`diagnose_material_supply`、`review_customer_exposure`、
`review_vendor_exposure`（READ）与 `propose_replenishment`（WRITE）。

- **WHEN** 调用 `review_customer_exposure`
  - **THEN** 服务端执行 SD.SalesOrder.GetList 与 FI.AR.GetOpenItems（AR 需
    customer+companyCode；companyCode 缺失时只跑 SO 并在 limitations 标注）
- **WHEN** 调用 `review_vendor_exposure`
  - **THEN** 服务端执行 FI.AP.GetOpenItems（vendor+companyCode 必填），
    PO 列表在提供 plant/vendor 时附带
- **WHEN** 调用 `propose_replenishment` 且提供 requiredQuantity/targetDate/purchasingGroup
  - **THEN** 服务端跑 material-supply composition 与 recommendation；
    缺货才产生 PR proposal，供应充足返回无 proposal 的结论
- **WHEN** 任一 READ 工具的部分能力缺槽位
  - **THEN** 返回能执行部分的 facts，并在 limitations/completeness 显式标注，
    不用陈旧值冒充

### Requirement: Contract v2 with approval handle

响应 schema SHALL 增加 `awaiting_approval` 状态与 `approval` 句柄块
（approvalId/runId/expiresAt/capabilityId/parameters/parameterSources/
factRefs/hashes），并保持 v1 字段对 diagnose 工具兼容。

- **WHEN** WRITE 工具产生待审批 proposal
  - **THEN** status="awaiting_approval" 且 approval 句柄字段齐全，facts/chain 仍可读
- **WHEN** 客户端发送 contractVersion=1
  - **THEN** diagnose_material_supply 行为与归档 v1 一致（WRITE 不可见）
- **WHEN** 请求携带技术覆盖字段（任意深度的 rfcName/bindingId/endpoint/token…）
  - **THEN** 400 TECHNICAL_OVERRIDE_REJECTED，零网关调用（v1 红线保留）

### Requirement: In-process tool execution entry

系统 SHALL 暴露一个仅服务端可调用的函数入口，供 in-process dsh 工具直接执行，
签名不含 HTTP/Cordis 类型；HTTP `/api/semantic-tools` 成为该入口的薄适配。

- **WHEN** dsh 工具 execute 触发
  - **THEN** 经同进程函数进入治理层（principal 由服务端注入），不向自己发 HTTP
- **WHEN** 未来另一个 harness 接入
  - **THEN** 同一函数/同一契约被复用，harness 之间结果确定一致

### Requirement: READ-only tools never write

三个 READ 工具的执行图 MUST 只含 READ partition；propose_replenishment 在人类
批准前 MUST NOT 执行 Action 节点。

- **WHEN** READ 工具的组合结果意外含 actionPartition
  - **THEN** 该 action 不被执行，响应标记 out_of_scope/limitation

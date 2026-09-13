# DSH Replenishment Gap Calculation Specification

## Purpose

DSH 补货建议（propose_replenishment）生成的 PR 草稿数量必须等于基于实时供应
事实计算的缺口，而不是用户表达的目标需求总量。系统在提案构建前自行读取库存
与在途供应，按固定业务口径确定性计算缺口；LLM 不参与算术，只负责转述结果。

## Requirements

### Requirement: Server-side supply facts read before proposal build

系统 SHALL 在为 propose_replenishment 构建 WRITE 提案前，于同一受治理 run
内服务端执行一次 `MM.Inventory.GetAvailability`（material/plant 与提案一致），
并仅以该次 READ 返回的事实作为缺口计算输入。

- **WHEN** propose_replenishment 具备完整必填槽位（material/plant/
  requiredQuantity/targetDate/purchasingGroup）
  - **THEN** 提案构建前存在一次服务端发起的库存 READ 调用与对应事实记录
- **WHEN** 同一会话此前已由模型调用过库存诊断工具
  - **THEN** 系统仍重新执行 READ，不复用会话历史中的旧事实
- **WHEN** READ 失败、物料不存在或返回不可用
  - **THEN** 不生成提案、不产生审批句柄，工具状态为 failed 并携带可展示错误

### Requirement: Deterministic gap formula with dated in-transit supply

系统 SHALL 按以下口径确定性计算缺口，计算过程不调用 LLM：

缺口 = max? 否，缺口 = requiredQuantity −（当前可用库存 + 按期在途供应）。

- 当前可用库存 = MRP 元素指示符 WB（Stock）行的 availQty1 之和，恒计入。
- 按期在途供应 = MRP 元素指示符 BA（PurRqs，采购申请）与 BE（POitem，
  采购订单行项目）行中，`date <= targetDate` 的 availQty1 之和。
- BA/BE 行 `date > targetDate` 时不计入供应，但必须作为“未计入（晚于目标
  日期）”明细保留在计算依据中。
- WB/BA/BE 以外的 MRP 元素（计划订单、计划独立需求、销售订单、预留、
  交货计划行等）SHALL NOT 计入供应。
- 日期比较使用元素 date 字段（YYYY-MM-DD 日历日）与 targetDate 直接比较，
  不做时区换算。

- **WHEN** 事实包含 WB=2、BE=3（date=2026-08-12），requiredQuantity=10，
  targetDate=2026-09-30
  - **THEN** 当期供应=5，缺口=5
- **WHEN** 同一 BE=3 的 date=2026-10-15
  - **THEN** 当期供应=2，缺口=8，且计算依据列出该 BE 行为未计入
- **WHEN** 相同事实输入重复计算
  - **THEN** 结果完全一致（确定性）

### Requirement: Proposal quantity equals the computed gap

当缺口 > 0 时，PR 草稿数量 SHALL 等于缺口值，单位取库存事实单位；
`requiredQuantity` 仅作为目标需求约束参与减法，不得直接成为 PR 数量。

- **WHEN** 缺口=5
  - **THEN** approval.parameters.quantity = "5"，且 quantity 的来源证据
    包含 requiredQuantity 约束、库存事实引用与计算规则引用
- **WHEN** 事实单位与提案单位不一致或事实单位缺失
  - **THEN** fail-closed，不生成提案（本版不做单位换算）
- **WHEN** 用户口语同时给出“需求10、库存1、在途3、缺口6”等多个数字
  - **THEN** PR 数量只以服务端计算的缺口为准，用户话语中的数字不参与算术

### Requirement: Zero-gap produces no proposal

当缺口 <= 0 时 SHALL NOT 调用 WRITE 能力、SHALL NOT 产生 awaiting_approval
状态或审批句柄。

- **WHEN** 当期供应 >= requiredQuantity
  - **THEN** 工具返回 status=complete，无 approval 字段，narrative 说明
    “目标日期前供应充足，无需补货”，并给出需求、供应合计与对比口径
- **WHEN** 该结果回到 DSH 模型
  - **THEN** 前端不出现批准/拒绝按钮，模型不得声称已创建或待审批任何 PR

### Requirement: Calculation basis visible to model and approval UI

工具返回与审批卡片 SHALL 展示可对账的计算依据明细：目标需求量、当前库存、
每条计入的在途 PR/PO（类型/数量/日期）、未计入项及原因、缺口数量。

- **WHEN** 提案 awaiting_approval
  - **THEN** 审批卡片展示上述计算依据，批准/拒绝按钮行为不变
- **WHEN** 历史会话回放该轮
  - **THEN** 计算依据随工具结果持久化可见
- **WHEN** 用户批准后 SAP 返回 PR 号
  - **THEN** 现有执行结果回显（PR 号与 SAP 消息）保持不变

### Requirement: Required-quantity clarification stays unchanged

requiredQuantity 槽位的语义保持为“目标需求总量”，仍为必填。

- **WHEN** 用户未提供目标需求总量
  - **THEN** 返回 clarification 追问目标需求量，不进入 READ 与缺口计算
- **WHEN** 提供的 requiredQuantity 非正数
  - **THEN** 维持现有 400 校验错误

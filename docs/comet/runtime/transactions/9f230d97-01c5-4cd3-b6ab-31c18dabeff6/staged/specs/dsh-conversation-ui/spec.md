# DSH Conversation UI Specification

## Purpose

新建一个简洁的 dsh 对话视图作为 Workbench 默认对话入口：聊天气泡 + 工具调用过程
+ 结构化事实卡片 + WRITE 审批卡片。不复用旧 21 事件证据工作台，也不把 dsh 运行
投影成 AgentRunEvent SSE。

## Requirements

### Requirement: Chat surface with tool process

视图 SHALL 渲染用户消息、dsh 助手文本、以及每次工具调用的过程（工具名/关键入参/
状态），业务数值只来自工具结果。

- **WHEN** 模型调用一个语义工具
  - **THEN** UI 展示工具名与进行中/完成/失败状态，随后展示助手基于结果的回答
- **WHEN** 工具返回 clarification
  - **THEN** UI 展示澄清提示（缺哪个槽位），用户可补充后重发
- **WHEN** 工具失败或数据不可用
  - **THEN** UI 显示错误/limitation，助手不展示任何未被证据支持的数字

### Requirement: Structured fact cards

READ 结果 SHALL 以结构化卡片呈现（库存/采购订单/销售订单/应收/应付），字段取自
契约 facts/capabilityChain/projection，附 asOf 与证据引用。

- **WHEN** review_customer_exposure 返回 SO 与 AR facts
  - **THEN** 卡片分组展示订单净值（currency）与未清项金额（currency/到期日），
    分区标题清晰，缺 companyCode 时有提示
- **WHEN** 投影 completeness 为 partial/incomplete
  - **THEN** 卡片显示缺失/失败节点与 limitation，不伪装为完整

### Requirement: WRITE approval card

当工具结果为 awaiting_approval，视图 SHALL 渲染审批卡片：6 个 PR 参数
（material/plant/quantity/unit/delivery_date/purchasing_group）、有效期、
证据引用与「批准/拒绝」按钮。

- **WHEN** 卡片渲染
  - **THEN** 显示 expiresAt 倒计时/过期态，批准与拒绝互斥，pending 期间禁用重复提交
- **WHEN** 用户点击批准
  - **THEN** POST 审批路由，卡片进入 approved/executing，完成后用返回/回流的
    action-receipt 显示 PR 号；失败显示业务错误
- **WHEN** 用户点击拒绝
  - **THEN** 卡片进入 rejected，对话出现拒绝陈述且无 PR

### Requirement: dsh-only runtime identity

新视图 SHALL 只使用 dsh 对话 API；页面上不出现「切换 Python harness」入口。

- **WHEN** 用户在新视图发起任意对话
  - **THEN** 请求只到达 dsh 会话端点，不到旧 `/api/agent-runs`
- **WHEN** 用户需要旧证据工作台
  - **THEN** 可经保留的 `/workbench` 路径访问，但它不是默认对话入口
